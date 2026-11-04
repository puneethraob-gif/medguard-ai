import io
import shutil
import uuid
import wave
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.models import (Base, Consultation, ConsultationRecording, ConsultationTranscriptSegment,
    ConsultationConsent, ConsultationSummary, TimelineEvent)
from app.db.session import get_db
import app.main as main_module
from app.main import app
from app.timeline.integrations import register_source_verifier

settings.jwt_secret = "test-jwt-secret-with-at-least-32-bytes"
class _AllowAuthRateLimiter:
    def consume(self, key, window_seconds): return 1
main_module.auth_rate_limiter = _AllowAuthRateLimiter()
settings.patient_data_encryption_key = Fernet.generate_key().decode()
settings.consultation_audio_encryption_key = Fernet.generate_key().decode()
engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base.metadata.create_all(engine)


def override_db():
    db = TestSession()
    try: yield db
    finally: db.close()


client = TestClient(app)
PASSWORD = "a-very-long-password"


@pytest.fixture(autouse=True)
def clean_db(monkeypatch):
    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_db
    with TestSession() as db:
        for table in reversed(Base.metadata.sorted_tables): db.execute(table.delete())
        db.commit()
    audio_dir = Path(__file__).resolve().parents[2] / "work" / f"consultation-test-{uuid.uuid4().hex}"
    monkeypatch.setattr(settings, "consultation_audio_dir", str(audio_dir / "audio"))
    register_source_verifier("consultation", lambda db, pid, rid: (row := db.get(Consultation, int(rid))) is not None and row.patient_id == pid)
    yield audio_dir
    app.dependency_overrides.pop(get_db, None)
    if previous_override: app.dependency_overrides[get_db] = previous_override
    shutil.rmtree(audio_dir, ignore_errors=True)


def auth_headers(email: str):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def setup_pair():
    p = client.post("/api/v1/auth/register/patient", json={"email": "person@example.test", "name": "Asha Test", "password": PASSWORD})
    d = client.post("/api/v1/auth/register/doctor", json={"email": "doctor@example.test", "name": "Dr Test", "password": PASSWORD, "license_number": "CLIN-1"})
    assert p.status_code == d.status_code == 201
    patient_id, doctor_id = p.json()["id"], d.json()["id"]
    patient = auth_headers("person@example.test"); doctor = auth_headers("doctor@example.test")
    assert client.post(f"/api/v1/hospitals/doctors/{doctor_id}/patients/{patient_id}", headers=patient).status_code == 204
    created = client.post("/api/v1/consultations", headers=doctor, json={"patient_id": patient_id, "scheduled_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()})
    assert created.status_code == 201, created.text
    return patient_id, doctor_id, created.json()["id"], patient, doctor


def consent(patient, consultation_id, consented=True):
    notice = client.get(f"/api/v1/consultations/{consultation_id}/consent-info", headers=patient).json()
    return client.post(f"/api/v1/consultations/{consultation_id}/consent", headers=patient,
        json={"consented": consented, "consent_text_version": notice["version"], "language": notice["language"]})


def synthetic_wav():
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 1600)
    return out.getvalue()


def test_create_consultation_authorization_and_timeline_event():
    patient_id, doctor_id, consult_id, patient, doctor = setup_pair()
    assert client.get(f"/api/v1/consultations/{consult_id}").status_code == 401
    rows = client.get("/api/v1/consultations", headers=patient).json()
    assert len(rows) == 1 and rows[0]["id"] == consult_id and rows[0]["summary"] is None
    with TestSession() as db:
        events = db.scalars(select(TimelineEvent).where(TimelineEvent.source_module == "consultation")).all()
        assert len(events) == 1 and events[0].event_type == "consultation_scheduled"
    other = client.post("/api/v1/auth/register/doctor", json={"email":"other@example.test","name":"Other","password":PASSWORD,"license_number":"CLIN-2"}).json()
    other_headers = auth_headers("other@example.test")
    assert client.get(f"/api/v1/consultations/{consult_id}", headers=other_headers).status_code == 404
    assert client.get(f"/api/v1/consultations?patient_id={patient_id}", headers=other_headers).status_code == 404
    assert doctor and doctor_id


def test_recording_consent_notice_uses_patient_language_and_requires_displayed_version():
    patient_id, _doctor_id, consult_id, patient, doctor = setup_pair()
    with TestSession() as db:
        from app.db.models import PatientProfile
        profile = db.get(PatientProfile, patient_id)
        profile.preferred_language = "te-IN"
        db.commit()
    notice = client.get(f"/api/v1/consultations/{consult_id}/consent-info", headers=patient)
    assert notice.status_code == 200 and notice.json()["language"] == "te" and "Sarvam AI" in notice.json()["text"] and "30" in notice.json()["text"]
    declined = client.post(f"/api/v1/consultations/{consult_id}/consent", headers=patient,
        json={"consented": False, "consent_text_version": notice.json()["version"], "language": "en"})
    assert declined.status_code == 422
    agreed = client.post(f"/api/v1/consultations/{consult_id}/consent", headers=patient,
        json={"consented": True, "consent_text_version": notice.json()["version"], "language": notice.json()["language"]})
    assert agreed.status_code == 201 and agreed.json()["language"] == "te"
    assert client.post(f"/api/v1/consultations/{consult_id}/recording/start", headers=doctor).status_code == 200


def test_unsupported_consent_language_discloses_fallback_and_blocks_agreement():
    patient_id, _doctor_id, consult_id, patient, _doctor = setup_pair()
    with TestSession() as db:
        from app.db.models import PatientProfile
        db.get(PatientProfile, patient_id).preferred_language = "or-IN"
        db.commit()
    notice = client.get(f"/api/v1/consultations/{consult_id}/consent-info", headers=patient).json()
    assert notice["fallback"] is True and notice["language"] == "en"
    response = client.post(f"/api/v1/consultations/{consult_id}/consent", headers=patient,
        json={"consented": True, "consent_text_version": notice["version"], "language": notice["language"]})
    assert response.status_code == 422


def test_transcription_queue_is_idempotent_and_task_claim_prevents_duplicate_provider_calls(monkeypatch):
    from app.consultations import tasks
    patient_id, _doctor_id, consult_id, patient, doctor = setup_pair()
    consent(patient, consult_id)
    client.post(f"/api/v1/consultations/{consult_id}/recording/start", headers=doctor)
    client.put(f"/api/v1/consultations/{consult_id}/recording", headers={**doctor, "Content-Type": "audio/wav"}, content=synthetic_wav())
    client.post(f"/api/v1/consultations/{consult_id}/recording/stop", headers=doctor)
    monkeypatch.setattr(tasks, "SessionLocal", TestSession)
    delayed = []
    monkeypatch.setattr("app.api.consultations.transcribe_consultation.delay", lambda cid: delayed.append(cid))
    first = client.post(f"/api/v1/consultations/{consult_id}/transcribe", headers=doctor)
    duplicate = client.post(f"/api/v1/consultations/{consult_id}/transcribe", headers=doctor)
    assert first.status_code == duplicate.status_code == 202
    assert duplicate.json()["status"] == "transcription_queued" and delayed == [consult_id]
    calls = []
    class FakeSpeech:
        def transcribe(self, audio, content_type, filename):
            calls.append(1)
            return __import__("app.consultations.providers", fromlist=["SpeechResult", "SpeechSegment"]).SpeechResult(
                "fake", "en-IN", [__import__("app.consultations.providers", fromlist=["SpeechSegment"]).SpeechSegment("Synthetic test", 0, 1, "en-IN")])
    monkeypatch.setattr(tasks, "speech_provider", lambda: FakeSpeech())
    assert tasks.transcribe_consultation.run(consult_id)["status"] == "transcribed"
    assert tasks.transcribe_consultation.run(consult_id)["status"] == "not_ready"
    assert len(calls) == 1
    with TestSession() as db:
        record = db.scalar(select(ConsultationRecording).where(ConsultationRecording.consultation_id == consult_id))
        assert record.transcription_attempts == 1 and record.transcription_claimed_at is None


def test_ambiguous_provider_failure_is_not_resubmitted(monkeypatch):
    from app.consultations import tasks
    from app.consultations.providers import ProviderRequestError
    _patient_id, _doctor_id, consult_id, patient, doctor = setup_pair()
    consent(patient, consult_id)
    client.post(f"/api/v1/consultations/{consult_id}/recording/start", headers=doctor)
    client.put(f"/api/v1/consultations/{consult_id}/recording", headers={**doctor, "Content-Type": "audio/wav"}, content=synthetic_wav())
    client.post(f"/api/v1/consultations/{consult_id}/recording/stop", headers=doctor)
    monkeypatch.setattr(tasks, "SessionLocal", TestSession)
    monkeypatch.setattr("app.api.consultations.transcribe_consultation.delay", lambda _cid: None)
    assert client.post(f"/api/v1/consultations/{consult_id}/transcribe", headers=doctor).status_code == 202
    calls = []
    class LostSubmission:
        def transcribe(self, *_args):
            calls.append(1)
            raise ProviderRequestError("synthetic network failure")
    monkeypatch.setattr(tasks, "speech_provider", lambda: LostSubmission())
    assert tasks.transcribe_consultation.run(consult_id)["recoverable"] is False
    assert client.post(f"/api/v1/consultations/{consult_id}/transcribe", headers=doctor).status_code == 409
    assert len(calls) == 1


def test_audio_retention_job_deletes_expired_audio_but_keeps_transcript(monkeypatch, clean_db):
    from app.consultations.tasks import delete_expired_consultation_audio
    patient_id, _doctor_id, consult_id, patient, doctor = setup_pair()
    consent(patient, consult_id)
    client.post(f"/api/v1/consultations/{consult_id}/recording/start", headers=doctor)
    client.put(f"/api/v1/consultations/{consult_id}/recording", headers={**doctor, "Content-Type": "audio/wav"}, content=synthetic_wav())
    client.post(f"/api/v1/consultations/{consult_id}/recording/stop", headers=doctor)
    monkeypatch.setattr("app.consultations.tasks.SessionLocal", TestSession)
    with TestSession() as db:
        record = db.scalar(select(ConsultationRecording).where(ConsultationRecording.consultation_id == consult_id))
        audio_path = clean_db / "audio" / record.storage_key
        record.uploaded_at = datetime.now(timezone.utc) - timedelta(days=settings.consultation_audio_retention_days + 1)
        db.commit()
    assert audio_path.exists()
    assert delete_expired_consultation_audio.run()["deleted_recordings"] == 1
    assert not audio_path.exists()
    with TestSession() as db:
        retained_metadata = db.scalar(select(ConsultationRecording).where(ConsultationRecording.consultation_id == consult_id))
        assert retained_metadata and retained_metadata.audio_deleted_at is not None
        assert db.get(Consultation, consult_id).patient_id == patient_id


def test_recording_requires_consent_encrypts_audio_and_limits_audio_to_doctor(clean_db):
    patient_id, _doctor_id, consult_id, patient, doctor = setup_pair()
    audio = synthetic_wav()
    assert client.post(f"/api/v1/consultations/{consult_id}/recording/start", headers=doctor).status_code == 409
    assert consent(patient, consult_id).status_code == 201
    assert client.post(f"/api/v1/consultations/{consult_id}/recording/start", headers=doctor).status_code == 200
    uploaded = client.put(f"/api/v1/consultations/{consult_id}/recording", headers={**doctor, "Content-Type": "audio/wav"}, content=audio)
    assert uploaded.status_code == 201, uploaded.text
    with TestSession() as db:
        record = db.scalar(select(ConsultationRecording).where(ConsultationRecording.consultation_id == consult_id))
        ciphertext = (clean_db / "audio" / record.storage_key).read_bytes()
        assert ciphertext != audio and len(ciphertext) > len(audio)
    assert client.get(f"/api/v1/consultations/{consult_id}/recording", headers=patient).status_code == 404
    got = client.get(f"/api/v1/consultations/{consult_id}/recording", headers=doctor)
    assert got.status_code == 200 and got.content == audio and got.headers["cache-control"] == "no-store"
    stopped = client.post(f"/api/v1/consultations/{consult_id}/recording/stop", headers=doctor)
    assert stopped.status_code == 200 and stopped.json()["status"] == "completed"
    with TestSession() as db:
        events = db.scalars(select(TimelineEvent).where(TimelineEvent.source_record_id == str(consult_id))).all()
        assert {e.event_type for e in events} == {"consultation_scheduled", "consultation_completed"}


def test_recording_rejects_content_type_signature_mismatch():
    _patient_id, _doctor_id, consult_id, patient, doctor = setup_pair()
    assert consent(patient, consult_id).status_code == 201
    assert client.post(f"/api/v1/consultations/{consult_id}/recording/start", headers=doctor).status_code == 200
    response = client.put(
        f"/api/v1/consultations/{consult_id}/recording",
        headers={**doctor, "Content-Type": "audio/wav"},
        content=b"not a wav file",
    )
    assert response.status_code == 415


def test_consent_decline_and_revocation_block_recording_and_delete_unprocessed_audio():
    _patient_id, _doctor_id, consult_id, patient, doctor = setup_pair()
    assert consent(patient, consult_id, False).json()["consented"] is False
    assert client.post(f"/api/v1/consultations/{consult_id}/recording/start", headers=doctor).status_code == 409
    consent(patient, consult_id)
    client.post(f"/api/v1/consultations/{consult_id}/recording/start", headers=doctor)
    upload = client.put(f"/api/v1/consultations/{consult_id}/recording", headers={**doctor,"Content-Type":"audio/wav"}, content=synthetic_wav())
    assert upload.status_code == 201
    assert client.delete(f"/api/v1/consultations/{consult_id}/consent", headers=patient).status_code == 204
    assert client.post(f"/api/v1/consultations/{consult_id}/recording/stop", headers=doctor).status_code == 409
    assert client.post(f"/api/v1/consultations/{consult_id}/transcribe", headers=doctor).status_code == 409
    assert client.get(f"/api/v1/consultations/{consult_id}/recording", headers=doctor).status_code == 403
    with TestSession() as db:
        recording = db.scalar(select(ConsultationRecording).where(ConsultationRecording.consultation_id == consult_id))
        assert recording and recording.audio_deleted_at is not None
        latest_consent = db.scalar(select(ConsultationConsent).where(ConsultationConsent.consultation_id == consult_id).order_by(ConsultationConsent.consented_at.desc(), ConsultationConsent.id.desc()))
        assert latest_consent and latest_consent.revoked_at is not None


def test_transcription_summary_sources_doctor_approval_patient_access_and_isolation(monkeypatch):
    from app.consultations import tasks
    from app.consultations.providers import SpeechResult, SpeechSegment
    patient_id, _doctor_id, consult_id, patient, doctor = setup_pair()
    consent(patient, consult_id)
    client.post(f"/api/v1/consultations/{consult_id}/recording/start", headers=doctor)
    client.put(f"/api/v1/consultations/{consult_id}/recording", headers={**doctor,"Content-Type":"audio/wav"}, content=synthetic_wav())
    client.post(f"/api/v1/consultations/{consult_id}/recording/stop", headers=doctor)
    monkeypatch.setattr(tasks, "SessionLocal", TestSession)
    class FakeSpeech:
        def transcribe(self, audio, content_type, filename):
            assert audio == synthetic_wav()
            return SpeechResult("synthetic-test", "hi-IN", [
                SpeechSegment("मुझे दो दिन से खांसी है", 0.1, 1.2, "hi-IN", "0"),
                SpeechSegment("Synthetic English test: doctor noted blood pressure 140 over 90. Paracetamol 500 mg twice daily after food for two days. Avoid cold drinks, drink warm water, complete CBC tomorrow, follow up Friday.", 1.3, 6.0, "en-IN", "1"),
            ])
    monkeypatch.setattr(tasks, "speech_provider", lambda: FakeSpeech())
    assert tasks.transcribe_consultation.run(consult_id)["status"] == "transcribed"
    with TestSession() as db:
        rows = db.scalars(select(ConsultationTranscriptSegment).where(ConsultationTranscriptSegment.consultation_id == consult_id).order_by(ConsultationTranscriptSegment.sequence)).all()
        segment_id = rows[0].id
        assert rows[0].text.startswith("मुझे") and rows[0].language_code == "hi-IN" and rows[0].speaker_id == "0"
        stored_text = db.execute(text("SELECT text FROM consultation_transcript_segments WHERE id = :id"), {"id": segment_id}).scalar_one()
        assert "मुझे दो दिन से खांसी है" not in stored_text
    class FakeSummary:
        def summarize(self, transcript, history_context):
            assert history_context is None
            doctor_source = transcript[1]["id"]
            return {"chief_complaints": [{"text": "Patient reports cough for two days", "duration": "two days", "statement_type": "ai_interpretation", "source_segment_ids": [segment_id]}],
                "symptoms": [], "medical_history": [],
                "doctor_observations": [{"text": "Blood pressure noted as 140/90", "statement_type": "ai_interpretation", "source_segment_ids": [doctor_source]}],
                "medicines_discussed": [{"text": "Paracetamol 500 mg twice daily after food for two days", "duration": "two days", "statement_type": "ai_interpretation", "source_segment_ids": [doctor_source]}],
                "tests_recommended": [{"text": "Complete CBC tomorrow", "statement_type": "ai_interpretation", "source_segment_ids": [doctor_source]}],
                "dietary_instructions": [{"text": "Drink warm water", "statement_type": "ai_interpretation", "source_segment_ids": [doctor_source]}],
                "dos_and_donts": [{"text": "Avoid cold drinks", "statement_type": "ai_interpretation", "source_segment_ids": [doctor_source]}],
                "follow_up_recommendations": [{"text": "Follow up Friday", "statement_type": "ai_interpretation", "source_segment_ids": [doctor_source]}],
                "warnings": []}
    monkeypatch.setattr(tasks, "summary_provider", lambda: FakeSummary())
    assert tasks.generate_consultation_summary.run(consult_id)["status"] == "in_review"
    draft = client.get(f"/api/v1/consultations/{consult_id}", headers=doctor).json()
    assert draft["summary"]["status"] == "in_review"
    assert draft["summary"]["content"]["chief_complaints"][0]["sources"][0]["start_seconds"] == 0.1
    assert draft["summary"]["content"]["warnings"] == []
    assert "500 mg twice daily" in draft["summary"]["content"]["medicines_discussed"][0]["text"]
    for section in ("doctor_observations", "medicines_discussed", "tests_recommended", "dietary_instructions", "dos_and_donts", "follow_up_recommendations"):
        assert draft["summary"]["content"][section][0]["source_segment_ids"]
    with TestSession() as db:
        stored_summary = db.execute(text("SELECT content FROM consultation_summaries WHERE consultation_id = :id"), {"id": consult_id}).scalar_one()
        assert "Patient reports cough" not in stored_summary
    patient_draft = client.get(f"/api/v1/consultations/{consult_id}", headers=patient).json()
    assert patient_draft["summary"] is None and patient_draft["transcript"] is None
    corrected_content = {key: [{k: v for k, v in fact.items() if k != "sources"} for fact in facts]
        for key, facts in draft["summary"]["content"].items()}
    corrected_content["chief_complaints"][0]["text"] = "Patient reports a cough lasting two days"
    corrected = client.put(f"/api/v1/consultations/{consult_id}/summary", headers=doctor,
        json={"content": corrected_content, "comment": "Doctor reviewed transcript"})
    assert corrected.status_code == 200 and corrected.json()["version"] == 2
    approved = client.post(f"/api/v1/consultations/{consult_id}/approve", headers=doctor, json={"transcript_patient_access": True})
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    doctor_detail = client.get(f"/api/v1/consultations/{consult_id}", headers=doctor).json()
    assert [h["action"] for h in doctor_detail["approval_history"]] == ["corrected", "approved"]
    patient_final = client.get(f"/api/v1/consultations/{consult_id}", headers=patient).json()
    assert patient_final["summary"]["status"] == "approved" and len(patient_final["transcript"]) == 2
    assert client.get(f"/api/v1/consultations/{consult_id}/transcript", headers=patient).status_code == 200
    client.post("/api/v1/auth/register/caregiver", json={"email":"summary-caregiver@example.test","name":"Care partner","password":PASSWORD})
    caregiver = auth_headers("summary-caregiver@example.test")
    summary_grant = client.post("/api/v1/consents", headers=patient, json={"caregiver_email":"summary-caregiver@example.test","scope":"consultations"})
    assert client.get(f"/api/v1/consultations/{consult_id}", headers=caregiver).json()["summary"]["status"] == "approved"
    assert client.get(f"/api/v1/consultations/{consult_id}", headers=caregiver).json()["transcript"] is None
    transcript_grant = client.post("/api/v1/consents", headers=patient, json={"caregiver_email":"summary-caregiver@example.test","scope":"consultation_transcript"})
    assert len(client.get(f"/api/v1/consultations/{consult_id}", headers=caregiver).json()["transcript"]) == 2
    assert client.delete(f"/api/v1/consents/{transcript_grant.json()['id']}", headers=patient).status_code == 204
    assert client.get(f"/api/v1/consultations/{consult_id}", headers=caregiver).json()["transcript"] is None
    assert client.delete(f"/api/v1/consents/{summary_grant.json()['id']}", headers=patient).status_code == 204
    assert client.get(f"/api/v1/consultations/{consult_id}", headers=caregiver).status_code == 404
    other_patient = client.post("/api/v1/auth/register/patient", json={"email":"other-patient@example.test","name":"Other","password":PASSWORD}).json()
    other_headers = auth_headers("other-patient@example.test")
    assert client.get(f"/api/v1/consultations/{consult_id}", headers=other_headers).status_code == 404
    timeline = client.get("/api/v1/timeline", headers=patient).json()["items"]
    assert {e["event_type"] for e in timeline if e["source_record_id"] == str(consult_id)} >= {"consultation_scheduled", "consultation_completed", "summary_generated", "summary_approved"}
    assert other_patient["id"] != patient_id


def test_caregiver_consultation_scope_and_revocation():
    _patient_id, _doctor_id, consult_id, patient, _doctor = setup_pair()
    caregiver = client.post("/api/v1/auth/register/caregiver", json={"email":"caregiver@example.test","name":"Caregiver","password":PASSWORD})
    assert caregiver.status_code == 201
    care = auth_headers("caregiver@example.test")
    assert client.get("/api/v1/consultations", headers=care).json() == []
    grant = client.post("/api/v1/consents", headers=patient, json={"caregiver_email":"caregiver@example.test","scope":"consultations"})
    assert grant.status_code == 201
    assert len(client.get("/api/v1/consultations", headers=care).json()) == 1
    assert client.delete(f"/api/v1/consents/{grant.json()['id']}", headers=patient).status_code == 204
    assert client.get("/api/v1/consultations", headers=care).json() == []
    assert client.get(f"/api/v1/consultations/{consult_id}", headers=care).status_code == 404
