import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.consultations.service import active_consent, latest_summary, record_audit, summary_dict, timeline_event
from app.consultations.consent_text import (CONSENT_TEXT, RETENTION_TEXT, consent_version,
    is_supported_language, language_key)
from app.consultations.storage import audio_storage
from app.consultations.tasks import generate_consultation_summary, transcribe_consultation
from app.core.config import settings
from app.db.models import (CareConsent, Consultation, ConsultationApproval, ConsultationConsent,
    ConsultationRecording, ConsultationSummary, ConsultationTranscriptSegment, PatientDoctor, PatientProfile, User)
from app.db.session import get_db

router = APIRouter(prefix="/consultations", tags=["consultations"])


def _audio_signature_matches(content_type: str, data: bytes) -> bool:
    if content_type in {"audio/wav", "audio/x-wav"}:
        return len(data) >= 12 and data[:4] in {b"RIFF", b"RF64"} and data[8:12] == b"WAVE"
    if content_type == "audio/mpeg":
        return data.startswith(b"ID3") or (len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0)
    if content_type == "audio/aac":
        return len(data) >= 2 and data[0] == 0xFF and data[1] & 0xF6 == 0xF0
    if content_type == "audio/ogg":
        return data.startswith(b"OggS")
    if content_type == "audio/webm":
        return data.startswith(b"\x1a\x45\xdf\xa3")
    if content_type == "audio/flac":
        return data.startswith(b"fLaC")
    if content_type in {"audio/mp4", "audio/3gpp"}:
        return len(data) >= 12 and data[4:8] == b"ftyp" and (content_type != "audio/3gpp" or data[8:11] == b"3gp")
    return False


class ConsultationCreate(BaseModel):
    patient_id: int
    scheduled_at: datetime


class ConsentInput(BaseModel):
    consented: bool
    consent_text_version: str = Field(min_length=1, max_length=40)
    language: str = Field(min_length=2, max_length=16)


class SummaryEdit(BaseModel):
    content: dict
    comment: str | None = Field(default=None, max_length=2000)


class ApprovalInput(BaseModel):
    comment: str | None = Field(default=None, max_length=2000)
    transcript_patient_access: bool = False


class SpeakerRolesInput(BaseModel):
    roles: dict[str, str]


def _get_consultation(db: Session, actor: User, consultation_id: int, *, doctor_only: bool = False) -> Consultation:
    consultation = db.get(Consultation, consultation_id)
    if not consultation:
        raise HTTPException(404, "Consultation not found")
    if actor.role == "doctor" and actor.id == consultation.doctor_id and db.get(PatientDoctor, (consultation.patient_id, actor.id)):
        return consultation
    if not doctor_only and actor.role == "patient" and actor.id == consultation.patient_id:
        return consultation
    if not doctor_only and actor.role == "caregiver" and db.scalar(select(CareConsent.id).where(
        CareConsent.patient_id == consultation.patient_id, CareConsent.grantee_id == actor.id,
        CareConsent.active.is_(True), CareConsent.scope == "consultations",
    )):
        return consultation
    raise HTTPException(404, "Consultation not found")


def _transcript(db: Session, consultation_id: int):
    rows = db.scalars(select(ConsultationTranscriptSegment).where(
        ConsultationTranscriptSegment.consultation_id == consultation_id
    ).order_by(ConsultationTranscriptSegment.sequence)).all()
    return [{"id": s.id, "sequence": s.sequence, "text": s.text, "language_code": s.language_code,
        "start_seconds": s.start_seconds, "end_seconds": s.end_seconds,
        "speaker_id": s.speaker_id, "speaker_role": s.speaker_role, "confidence": s.confidence}
        for s in rows]


def _serialize(db: Session, consultation: Consultation, actor: User):
    summary = latest_summary(db, consultation.id)
    doctor_view = actor.role == "doctor"
    patient_view = actor.role in {"patient", "caregiver"}
    if patient_view and (not summary or summary.status != "approved"):
        summary = None
    allow_transcript = doctor_view or (consultation.transcript_patient_access and actor.role == "patient" and summary and summary.status == "approved")
    if actor.role == "caregiver" and consultation.transcript_patient_access:
        allow_transcript = bool(db.scalar(select(CareConsent.id).where(
            CareConsent.patient_id == consultation.patient_id, CareConsent.grantee_id == actor.id,
            CareConsent.active.is_(True), CareConsent.scope == "consultation_transcript",
        )))
    doctor = db.get(User, consultation.doctor_id)
    summary_content = summary_dict(summary)
    if summary_content:
        segment_by_id = {s["id"]: s for s in _transcript(db, consultation.id)}
        for facts in summary_content["content"].values():
            for fact in facts:
                fact["sources"] = [{"id": segment_by_id[source_id]["id"],
                    "start_seconds": segment_by_id[source_id]["start_seconds"],
                    "end_seconds": segment_by_id[source_id]["end_seconds"],
                    "speaker_id": segment_by_id[source_id]["speaker_id"],
                    "speaker_role": segment_by_id[source_id]["speaker_role"]}
                    for source_id in fact.get("source_segment_ids", []) if source_id in segment_by_id]
    result = {"id": consultation.id, "patient_id": consultation.patient_id,
        "doctor": {"id": doctor.id, "name": doctor.name} if doctor else None,
        "status": consultation.status, "scheduled_at": consultation.scheduled_at,
        "started_at": consultation.started_at, "completed_at": consultation.completed_at,
        "transcript_patient_access": consultation.transcript_patient_access,
        "summary": summary_content,
        "transcript": _transcript(db, consultation.id) if allow_transcript else None}
    if doctor_view:
        recording = db.scalar(select(ConsultationRecording).where(ConsultationRecording.consultation_id == consultation.id))
        result["transcription"] = {"attempts": recording.transcription_attempts,
            "recoverable": bool(recording.provider_job_id and not recording.provider_job_terminal and recording.transcription_attempts < 3 and (recording.provider_job_started or recording.audio_deleted_at is None)),
            "terminal_failure": bool(recording.provider_job_terminal),
            "ambiguous_submission": bool(consultation.status == "failed" and recording.transcription_attempts > 0 and (not recording.provider_job_id or (recording.audio_deleted_at is not None and not recording.provider_job_started)))} if recording else None
        approvals = db.scalars(select(ConsultationApproval).where(
            ConsultationApproval.consultation_id == consultation.id
        ).order_by(ConsultationApproval.created_at)).all()
        result["approval_history"] = [{"id": a.id, "summary_id": a.summary_id, "doctor_id": a.doctor_id,
            "action": a.action, "comment": a.comment, "created_at": a.created_at} for a in approvals]
        consent = db.scalar(select(ConsultationConsent).where(
            ConsultationConsent.consultation_id == consultation.id,
        ).order_by(ConsultationConsent.consented_at.desc()))
        result["recording_consent"] = {"consented": consent.consented, "language": consent.language,
            "consented_at": consent.consented_at, "revoked_at": consent.revoked_at} if consent else None
    elif actor.role == "patient":
        consent = db.scalar(select(ConsultationConsent).where(
            ConsultationConsent.consultation_id == consultation.id,
        ).order_by(ConsultationConsent.consented_at.desc()))
        result["recording_consent"] = {"consented": consent.consented, "language": consent.language,
            "consented_at": consent.consented_at, "revoked_at": consent.revoked_at} if consent else None
    record_audit(db, actor.id, consultation.patient_id, "consultation.read")
    db.commit()
    return result


def _validate_summary(content: dict, allowed_ids: set[int]) -> bool:
    fields = {"chief_complaints", "symptoms", "medical_history", "doctor_observations", "medicines_discussed", "tests_recommended", "dietary_instructions", "dos_and_donts", "follow_up_recommendations", "warnings"}
    if not isinstance(content, dict) or set(content) != fields:
        return False
    for facts in content.values():
        if not isinstance(facts, list): return False
        for fact in facts:
            if not isinstance(fact, dict) or not isinstance(fact.get("text"), str): return False
            refs = fact.get("source_segment_ids")
            if not isinstance(refs, list) or not refs or not set(refs).issubset(allowed_ids): return False
            if fact.get("statement_type") not in {"doctor_statement", "patient_statement", "ai_interpretation"}: return False
    return True


@router.post("", status_code=201, summary="Create a consultation")
def create_consultation(data: ConsultationCreate, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if actor.role != "doctor": raise HTTPException(403, "Doctor account required")
    if not db.get(PatientDoctor, (data.patient_id, actor.id)): raise HTTPException(404, "Authorised patient not found")
    if data.scheduled_at.tzinfo is None: raise HTTPException(422, "scheduled_at must include a timezone")
    consultation = Consultation(patient_id=data.patient_id, doctor_id=actor.id, created_by_id=actor.id,
        scheduled_at=data.scheduled_at, status="scheduled")
    db.add(consultation); db.flush()
    timeline_event(db, consultation, "consultation_scheduled", "Consultation scheduled", data.scheduled_at, "scheduled")
    record_audit(db, actor.id, data.patient_id, "consultation.created")
    db.commit(); db.refresh(consultation)
    return {"id": consultation.id, "patient_id": consultation.patient_id, "doctor_id": consultation.doctor_id,
        "status": consultation.status, "scheduled_at": consultation.scheduled_at, "created_at": consultation.created_at}


@router.get("", summary="List authorized consultation records")
def list_consultations(patient_id: int | None = None, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = select(Consultation)
    if actor.role == "patient": query = query.where(Consultation.patient_id == actor.id)
    elif actor.role == "doctor":
        query = query.where(Consultation.doctor_id == actor.id)
        if patient_id is not None:
            if not db.get(PatientDoctor, (patient_id, actor.id)): raise HTTPException(404, "Patient not found")
            query = query.where(Consultation.patient_id == patient_id)
    elif actor.role == "caregiver":
        grants = select(CareConsent.patient_id).where(CareConsent.grantee_id == actor.id,
            CareConsent.scope == "consultations", CareConsent.active.is_(True))
        query = query.where(Consultation.patient_id.in_(grants))
        if patient_id is not None: query = query.where(Consultation.patient_id == patient_id)
    else: raise HTTPException(403, "This account cannot access consultations")
    rows = db.scalars(query.order_by(Consultation.scheduled_at.desc()).limit(100)).all()
    return [_serialize(db, row, actor) for row in rows]


@router.get("/{consultation_id}", summary="Read one authorized consultation")
def get_consultation(consultation_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _serialize(db, _get_consultation(db, actor, consultation_id), actor)


@router.post("/{consultation_id}/consent", status_code=201, summary="Record patient recording consent")
def grant_recording_consent(consultation_id: int, data: ConsentInput, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    consultation = db.get(Consultation, consultation_id)
    if actor.role != "patient" or not consultation or consultation.patient_id != actor.id: raise HTTPException(404, "Consultation not found")
    if consultation.status not in {"scheduled", "consented"}: raise HTTPException(409, "Consent must be recorded before recording starts")
    profile = db.get(PatientProfile, actor.id)
    expected_language = language_key(profile.preferred_language if profile else "en")
    if data.consented and not is_supported_language(profile.preferred_language if profile else "en"):
        raise HTTPException(422, "The recording notice is not available in the patient's preferred language")
    if data.consent_text_version != consent_version(settings.consultation_audio_retention_days) or language_key(data.language) != expected_language:
        raise HTTPException(422, "Consent language or notice version does not match the patient's displayed notice")
    consent = ConsultationConsent(consultation_id=consultation.id, patient_id=actor.id, consented_by_id=actor.id,
        consented=data.consented, consent_text_version=data.consent_text_version, language=data.language,
        consented_at=datetime.now(timezone.utc))
    db.add(consent)
    consultation.status = "consented" if data.consented else "scheduled"
    record_audit(db, actor.id, actor.id, "consultation.consent.recorded" if data.consented else "consultation.consent.declined")
    db.commit()
    return {"consented": consent.consented, "consented_at": consent.consented_at, "language": consent.language}


@router.get("/{consultation_id}/consent-info", summary="Get the recording notice in the patient's preferred language")
def consultation_consent_info(consultation_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    consultation = db.get(Consultation, consultation_id)
    if actor.role != "patient" or not consultation or consultation.patient_id != actor.id:
        raise HTTPException(404, "Consultation not found")
    profile = db.get(PatientProfile, actor.id)
    language = language_key(profile.preferred_language if profile else "en")
    preferred = profile.preferred_language if profile else "en"
    return {"version": consent_version(settings.consultation_audio_retention_days), "language": language,
        "text": CONSENT_TEXT[language] + RETENTION_TEXT[language].format(days=settings.consultation_audio_retention_days),
        "fallback": not is_supported_language(preferred), "preferred_language": preferred}


@router.delete("/{consultation_id}/consent", status_code=204, summary="Revoke patient recording consent")
def revoke_recording_consent(consultation_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    consultation = db.get(Consultation, consultation_id)
    if actor.role != "patient" or not consultation or consultation.patient_id != actor.id: raise HTTPException(404, "Consultation not found")
    consent = active_consent(db, consultation_id)
    if consent:
        consent.revoked_at = datetime.now(timezone.utc)
        recording = db.scalar(select(ConsultationRecording).where(ConsultationRecording.consultation_id == consultation_id))
        if recording:
            audio_storage.delete(recording.storage_key); recording.audio_deleted_at = datetime.now(timezone.utc)
            if consultation.status in {"consented", "recording", "uploaded"}: consultation.status = "scheduled"
        record_audit(db, actor.id, actor.id, "consultation.consent.revoked"); db.commit()
    return Response(status_code=204)


@router.post("/{consultation_id}/recording/start", summary="Start recording after consent")
def start_recording(consultation_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    consultation = _get_consultation(db, actor, consultation_id, doctor_only=True)
    if not active_consent(db, consultation_id): raise HTTPException(409, "Active patient consent is required before recording")
    if consultation.status != "consented": raise HTTPException(409, "Consultation is not ready to record")
    consultation.status = "recording"; consultation.started_at = datetime.now(timezone.utc)
    record_audit(db, actor.id, consultation.patient_id, "consultation.recording.started"); db.commit()
    return {"id": consultation.id, "status": consultation.status, "started_at": consultation.started_at}


@router.put("/{consultation_id}/recording", status_code=201, summary="Securely upload consultation audio")
async def upload_recording(consultation_id: int, request: Request, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    consultation = _get_consultation(db, actor, consultation_id, doctor_only=True)
    if consultation.status != "recording" or not active_consent(db, consultation_id): raise HTTPException(409, "An active recording session and patient consent are required")
    recording = db.scalar(select(ConsultationRecording).where(ConsultationRecording.consultation_id == consultation_id))
    if recording and recording.audio_deleted_at is None: raise HTTPException(409, "A recording is already uploaded")
    content_type = request.headers.get("content-type", "application/octet-stream").split(";")[0].lower()
    allowed = {"audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp4", "audio/aac", "audio/ogg", "audio/webm", "audio/flac", "audio/3gpp"}
    if content_type not in allowed: raise HTTPException(415, "Unsupported audio content type")
    size = 0; chunks = []
    async for chunk in request.stream():
        size += len(chunk)
        if size > settings.consultation_max_audio_bytes: raise HTTPException(413, "Recording exceeds configured upload limit")
        chunks.append(chunk)
    audio = b"".join(chunks)
    if not audio: raise HTTPException(400, "Audio recording is empty")
    if not _audio_signature_matches(content_type, audio): raise HTTPException(415, "Audio bytes do not match the declared file type")
    key = audio_storage.put(audio)
    if recording:
        recording.storage_key = key; recording.content_type = content_type; recording.byte_size = size
        recording.sha256 = hashlib.sha256(audio).hexdigest(); recording.uploaded_at = datetime.now(timezone.utc)
        recording.provider_job_id = None; recording.provider_job_terminal = False
        recording.transcription_attempts = 0; recording.transcription_claimed_at = None
        recording.transcription_queued_at = None; recording.audio_deleted_at = None
        recording.provider_job_uploaded = False; recording.provider_job_started = False
    else:
        recording = ConsultationRecording(consultation_id=consultation.id, storage_key=key,
            content_type=content_type, byte_size=size, sha256=hashlib.sha256(audio).hexdigest())
        db.add(recording)
    consultation.status = "uploaded"
    record_audit(db, actor.id, consultation.patient_id, "consultation.recording.uploaded")
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        audio_storage.delete(key)
        raise HTTPException(503, "Recording metadata could not be saved; the upload was discarded") from exc
    return {"id": recording.id, "status": consultation.status, "byte_size": size, "sha256": recording.sha256}


@router.post("/{consultation_id}/recording/stop", summary="Stop and complete a consultation recording")
def stop_recording(consultation_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    consultation = _get_consultation(db, actor, consultation_id, doctor_only=True)
    if consultation.status not in {"recording", "uploaded"}: raise HTTPException(409, "Consultation is not recording")
    if not active_consent(db, consultation_id): raise HTTPException(409, "Active patient consent is required")
    if not db.scalar(select(ConsultationRecording.id).where(ConsultationRecording.consultation_id == consultation_id)): raise HTTPException(409, "Upload the recording before stopping")
    now = datetime.now(timezone.utc); consultation.status = "completed"; consultation.completed_at = now
    timeline_event(db, consultation, "consultation_completed", "Consultation completed", now, "completed")
    record_audit(db, actor.id, consultation.patient_id, "consultation.recording.stopped"); db.commit()
    return {"id": consultation.id, "status": consultation.status, "completed_at": consultation.completed_at}


@router.get("/{consultation_id}/recording", summary="Stream audio to the authorised doctor only")
def get_recording(consultation_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    consultation = _get_consultation(db, actor, consultation_id, doctor_only=True)
    if not active_consent(db, consultation_id): raise HTTPException(403, "Recording consent is not active")
    recording = db.scalar(select(ConsultationRecording).where(ConsultationRecording.consultation_id == consultation_id))
    if not recording or recording.audio_deleted_at is not None: raise HTTPException(404, "Recording not found")
    try: audio = audio_storage.get(recording.storage_key)
    except Exception as exc: raise HTTPException(503, "Recording storage unavailable") from exc
    record_audit(db, actor.id, consultation.patient_id, "consultation.recording.read"); db.commit()
    return Response(audio, media_type=recording.content_type, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.post("/{consultation_id}/transcribe", status_code=202, summary="Queue consented recording transcription")
def queue_transcription(consultation_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    consultation = _get_consultation(db, actor, consultation_id, doctor_only=True)
    if not active_consent(db, consultation_id): raise HTTPException(409, "Active patient consent is required")
    recording = db.scalar(select(ConsultationRecording).where(ConsultationRecording.consultation_id == consultation_id))
    if not recording: raise HTTPException(409, "No consultation recording is available")
    if consultation.status == "transcribing":
        now = datetime.now(timezone.utc)
        if recording.transcription_claimed_at is not None:
            claimed_at = recording.transcription_claimed_at
            if claimed_at.tzinfo is None: claimed_at = claimed_at.replace(tzinfo=timezone.utc)
            if recording.provider_job_id and now - claimed_at > timedelta(seconds=settings.stt_batch_timeout_seconds + 300):
                if recording.audio_deleted_at is not None and not recording.provider_job_started:
                    raise HTTPException(409, "Audio expired before the provider accepted it; administrator reconciliation is required")
                if recording.transcription_attempts >= 3:
                    raise HTTPException(409, "Transcription recovery limit reached; contact an administrator")
                recording.transcription_claimed_at = None
                recording.transcription_queued_at = now
            else:
                return {"id": consultation_id, "status": "transcription_processing"}
        elif recording.transcription_queued_at:
            queued_at = recording.transcription_queued_at
            if queued_at.tzinfo is None: queued_at = queued_at.replace(tzinfo=timezone.utc)
            if now - queued_at < timedelta(minutes=5):
                return {"id": consultation_id, "status": "transcription_queued"}
            recording.transcription_queued_at = now
        else:
            recording.transcription_queued_at = now
    elif consultation.status == "failed":
        if not recording.provider_job_id:
            raise HTTPException(409, "The provider submission outcome is unknown; automatic resubmission is blocked to prevent duplicate processing")
        if recording.provider_job_terminal:
            raise HTTPException(409, "The provider batch job failed permanently; administrator reconciliation is required")
        if recording.audio_deleted_at is not None and not recording.provider_job_started:
            raise HTTPException(409, "Audio expired before the provider accepted it; administrator reconciliation is required")
        if recording.transcription_attempts >= 3:
            raise HTTPException(409, "Transcription retry limit reached; contact an administrator")
        recording.transcription_claimed_at = None
        recording.transcription_queued_at = datetime.now(timezone.utc)
        consultation.status = "transcribing"
    elif consultation.status == "completed":
        if recording.audio_deleted_at is not None and not recording.provider_job_id:
            raise HTTPException(409, "The retained audio has expired; upload a new recording after obtaining current consent")
        consultation.status = "transcribing"
        recording.transcription_claimed_at = None
        recording.transcription_queued_at = datetime.now(timezone.utc)
    else:
        raise HTTPException(409, "Stop the recording before transcription")
    db.commit()
    try:
        transcribe_consultation.delay(consultation_id)
    except Exception as exc:
        # No provider call can begin until a worker claims the row.
        recording.transcription_queued_at = None
        if recording.transcription_claimed_at is None and not recording.provider_job_id:
            consultation.status = "completed"
        db.commit()
        raise HTTPException(503, "Transcription could not be queued; retry shortly") from exc
    return {"id": consultation_id, "status": "transcription_queued"}


@router.post("/{consultation_id}/summarize", status_code=202, summary="Queue structured summary generation")
def queue_summary(consultation_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    consultation = _get_consultation(db, actor, consultation_id, doctor_only=True)
    if not active_consent(db, consultation_id): raise HTTPException(409, "Active patient consent is required")
    if not db.scalar(select(ConsultationTranscriptSegment.id).where(ConsultationTranscriptSegment.consultation_id == consultation_id)): raise HTTPException(409, "A transcript is required before summary generation")
    if consultation.status == "summarizing": return {"id": consultation_id, "status": "summary_processing"}
    if consultation.status not in {"transcribed", "in_review"}: raise HTTPException(409, "Consultation is not ready for a new summary draft")
    consultation.status = "summarizing"
    db.commit()
    try:
        generate_consultation_summary.delay(consultation_id)
    except Exception as exc:
        consultation.status = "transcribed"
        db.commit()
        raise HTTPException(503, "Summary generation could not be queued; retry shortly") from exc
    return {"id": consultation_id, "status": "summary_queued"}


@router.patch("/{consultation_id}/speaker-roles", summary="Confirm diarized speaker identities")
def set_speaker_roles(consultation_id: int, data: SpeakerRolesInput, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    consultation = _get_consultation(db, actor, consultation_id, doctor_only=True)
    if not data.roles or any(role not in {"doctor", "patient", "other"} for role in data.roles.values()):
        raise HTTPException(422, "Speaker roles must map speaker IDs to doctor, patient, or other")
    segments = db.scalars(select(ConsultationTranscriptSegment).where(
        ConsultationTranscriptSegment.consultation_id == consultation_id,
        ConsultationTranscriptSegment.speaker_id.in_(data.roles.keys()),
    )).all()
    found = {segment.speaker_id for segment in segments}
    if found != set(data.roles): raise HTTPException(422, "One or more speaker IDs are not in this transcript")
    for segment in segments: segment.speaker_role = data.roles[segment.speaker_id]
    record_audit(db, actor.id, consultation.patient_id, "consultation.speaker_roles.confirmed")
    db.commit()
    return {"updated_speakers": sorted(found)}


@router.put("/{consultation_id}/summary", summary="Edit a draft AI summary")
def edit_summary(consultation_id: int, data: SummaryEdit, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    consultation = _get_consultation(db, actor, consultation_id, doctor_only=True)
    summary = latest_summary(db, consultation_id)
    if not summary or summary.status not in {"draft", "in_review"}: raise HTTPException(409, "No editable draft summary exists")
    allowed_ids = {s["id"] for s in _transcript(db, consultation_id)}
    if not _validate_summary(data.content, allowed_ids): raise HTTPException(422, "Each summary item needs a valid source segment")
    summary.status = "superseded"
    corrected = ConsultationSummary(consultation_id=consultation_id, version=summary.version + 1,
        status="in_review", content=json.dumps(data.content, ensure_ascii=False), generated_by=summary.generated_by)
    db.add(corrected); db.flush()
    db.add(ConsultationApproval(consultation_id=consultation_id, summary_id=corrected.id, doctor_id=actor.id, action="corrected", comment=data.comment))
    record_audit(db, actor.id, consultation.patient_id, "consultation.summary.corrected"); db.commit()
    return summary_dict(corrected)


@router.post("/{consultation_id}/approve", summary="Approve a consultation summary")
def approve_summary(consultation_id: int, data: ApprovalInput, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    consultation = _get_consultation(db, actor, consultation_id, doctor_only=True)
    summary = latest_summary(db, consultation_id)
    if not summary or summary.status not in {"draft", "in_review"}: raise HTTPException(409, "No reviewable summary exists")
    if not active_consent(db, consultation_id): raise HTTPException(409, "Active patient consent is required")
    allowed_ids = {s["id"] for s in _transcript(db, consultation_id)}
    content = json.loads(summary.content)
    if not _validate_summary(content, allowed_ids): raise HTTPException(409, "Summary contains unverified source references")
    summary.status = "approved"; consultation.status = "approved"
    consultation.transcript_patient_access = data.transcript_patient_access
    now = datetime.now(timezone.utc)
    db.add(ConsultationApproval(consultation_id=consultation_id, summary_id=summary.id, doctor_id=actor.id, action="approved", comment=data.comment))
    timeline_event(db, consultation, "summary_approved", "Doctor approved consultation summary", now, "approved")
    record_audit(db, actor.id, consultation.patient_id, "consultation.summary.approved"); db.commit()
    return summary_dict(summary)


@router.get("/{consultation_id}/transcript", summary="Read a permitted consultation transcript")
def get_transcript(consultation_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    consultation = _get_consultation(db, actor, consultation_id)
    summary = latest_summary(db, consultation_id)
    if actor.role == "patient" and (not summary or summary.status != "approved" or not consultation.transcript_patient_access): raise HTTPException(404, "Transcript not available")
    if actor.role == "caregiver" and not db.scalar(select(CareConsent.id).where(
        CareConsent.patient_id == consultation.patient_id, CareConsent.grantee_id == actor.id,
        CareConsent.active.is_(True), CareConsent.scope == "consultation_transcript")): raise HTTPException(404, "Transcript not available")
    record_audit(db, actor.id, consultation.patient_id, "consultation.transcript.read"); db.commit()
    return {"segments": _transcript(db, consultation_id)}
