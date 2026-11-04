"""Celery tasks for audio transcription and AI summary generation."""
import json
from datetime import datetime, timedelta, timezone
from pydantic import ValidationError

from celery import shared_task
from sqlalchemy import select, update

from app.consultations.providers import (ConsultationSummaryContent, ProviderJobFailed, ProviderNotConfigured,
    ProviderUnavailable, SarvamSpeechProvider, speech_provider, summary_provider)
from app.consultations.service import active_consent, latest_summary, record_audit, timeline_event
from app.consultations.storage import audio_storage
from app.core.config import settings
from app.db.models import Consultation, ConsultationRecording, ConsultationSummary, ConsultationTranscriptSegment
from app.db.session import SessionLocal


@shared_task(name="consultations.transcribe")
def transcribe_consultation(consultation_id: int):
    with SessionLocal() as db:
        consultation = db.get(Consultation, consultation_id)
        recording = db.scalar(select(ConsultationRecording).where(ConsultationRecording.consultation_id == consultation_id))
        if not consultation or not recording or not active_consent(db, consultation_id):
            return {"status": "blocked"}
        if consultation.status not in {"completed", "transcribing", "failed"}:
            return {"status": "not_ready"}
        claim_time = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        claimed = db.execute(update(ConsultationRecording).where(
            ConsultationRecording.id == recording.id,
            ConsultationRecording.transcription_claimed_at.is_(None),
        ).values(transcription_claimed_at=claim_time,
                 transcription_queued_at=None,
                 transcription_attempts=ConsultationRecording.transcription_attempts + 1))
        if claimed.rowcount != 1:
            db.rollback()
            return {"status": "already_processing"}
        consultation.status = "transcribing"
        db.commit()
        try:
            audio_suffix = {"audio/wav": ".wav", "audio/x-wav": ".wav", "audio/mpeg": ".mp3",
                "audio/mp4": ".m4a", "audio/aac": ".aac", "audio/ogg": ".ogg",
                "audio/webm": ".webm", "audio/flac": ".flac", "audio/3gpp": ".3gp"}.get(recording.content_type, ".audio")
            provider = speech_provider()
            def remember_job(job_id: str):
                recording.provider_job_id = job_id
                recording.provider_job_terminal = False
                recording.provider_job_uploaded = False
                recording.provider_job_started = False
                db.commit()
            def remember_uploaded():
                recording.provider_job_uploaded = True
                db.commit()
            def remember_started():
                recording.provider_job_uploaded = True
                recording.provider_job_started = True
                db.commit()
            if recording.provider_job_id and recording.provider_job_started:
                audio = b""
            elif recording.audio_deleted_at is not None:
                raise ProviderUnavailable("Audio expired before provider submission completed")
            else:
                audio = audio_storage.get(recording.storage_key)
            if isinstance(provider, SarvamSpeechProvider):
                result = provider.transcribe(audio, recording.content_type, "consultation" + audio_suffix,
                    resume_job_id=recording.provider_job_id,
                    resume_uploaded=recording.provider_job_uploaded,
                    resume_started=recording.provider_job_started,
                    on_job_created=remember_job, on_job_uploaded=remember_uploaded,
                    on_job_started=remember_started)
            else:
                result = provider.transcribe(audio, recording.content_type, "consultation" + audio_suffix)
        except ProviderNotConfigured:
            recording.transcription_claimed_at = None
            consultation.status = "completed"
            db.commit()
            return {"status": "provider_unavailable"}
        except ProviderJobFailed:
            recording.provider_job_terminal = True
            recording.transcription_claimed_at = None
            consultation.status = "failed"
            db.commit()
            return {"status": "provider_job_failed", "recoverable": False}
        except ProviderUnavailable:
            recording.transcription_claimed_at = None
            consultation.status = "failed"
            db.commit()
            return {"status": "provider_failed", "recoverable": bool(recording.provider_job_id)}
        except Exception:
            # Without a persisted job ID an interrupted submit is ambiguous; never
            # automatically submit again and create a duplicate billable job.
            recording.transcription_claimed_at = None
            consultation.status = "failed"
            db.commit()
            return {"status": "provider_failed", "recoverable": bool(recording.provider_job_id)}
        if not active_consent(db, consultation_id):
            consultation.status = "failed"
            recording.transcription_claimed_at = None
            db.commit()
            return {"status": "consent_revoked"}
        db.query(ConsultationTranscriptSegment).filter_by(consultation_id=consultation_id).delete()
        for sequence, segment in enumerate(result.segments):
            if segment.end_seconds < segment.start_seconds or segment.start_seconds < 0:
                continue
            db.add(ConsultationTranscriptSegment(consultation_id=consultation_id, sequence=sequence,
                text=segment.text, language_code=segment.language_code or result.detected_language,
                start_seconds=segment.start_seconds, end_seconds=segment.end_seconds,
                speaker_id=segment.speaker_id, speaker_role=None, confidence=segment.confidence,
                provider=result.provider))
        consultation.status = "transcribed"
        recording.transcription_claimed_at = None
        record_audit(db, consultation.doctor_id, consultation.patient_id, "consultation.transcription.completed")
        db.commit()
        return {"status": "transcribed", "segments": len(result.segments)}


@shared_task(name="consultations.generate_summary")
def generate_consultation_summary(consultation_id: int):
    with SessionLocal() as db:
        consultation = db.get(Consultation, consultation_id)
        if not consultation or not active_consent(db, consultation_id):
            return {"status": "blocked"}
        segments = db.scalars(select(ConsultationTranscriptSegment).where(
            ConsultationTranscriptSegment.consultation_id == consultation_id
        ).order_by(ConsultationTranscriptSegment.sequence)).all()
        if not segments:
            return {"status": "transcript_required"}
        consultation.status = "summarizing"
        db.commit()
        source = [{"id": item.id, "text": item.text, "language_code": item.language_code,
            "start_seconds": item.start_seconds, "end_seconds": item.end_seconds,
            "speaker_id": item.speaker_id, "speaker_role": item.speaker_role} for item in segments]
        try:
            content = ConsultationSummaryContent.model_validate(
                summary_provider().summarize(source, history_context=None)
            ).model_dump()
        except ProviderUnavailable:
            consultation.status = "transcribed"
            db.commit()
            return {"status": "provider_unavailable"}
        except ValidationError:
            consultation.status = "transcribed"
            db.commit()
            return {"status": "invalid_provider_output"}
        if not active_consent(db, consultation_id):
            consultation.status = "transcribed"
            db.commit()
            return {"status": "consent_revoked"}
        available_ids = {item.id for item in segments}
        for key, facts in content.items():
            if not isinstance(facts, list):
                raise ValueError("Summary provider returned an invalid summary structure")
            for fact in facts:
                refs = fact.get("source_segment_ids", [])
                if not refs or not set(refs).issubset(available_ids):
                    consultation.status = "transcribed"
                    db.commit()
                    return {"status": "invalid_source_references"}
        previous = latest_summary(db, consultation_id)
        version = (previous.version + 1) if previous else 1
        if previous:
            previous.status = "superseded"
        summary = ConsultationSummary(consultation_id=consultation_id, version=version,
            status="in_review", content=json.dumps(content, ensure_ascii=False), generated_by=settings.llm_provider)
        db.add(summary)
        consultation.status = "in_review"
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        timeline_event(db, consultation, "summary_generated", "Consultation summary ready for review", now, "pending_review")
        record_audit(db, consultation.doctor_id, consultation.patient_id, "consultation.summary.generated")
        db.commit()
        return {"status": "in_review", "summary_id": summary.id}


@shared_task(name="consultations.delete_expired_audio")
def delete_expired_consultation_audio():
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.consultation_audio_retention_days)
    removed = 0
    with SessionLocal() as db:
        rows = db.scalars(select(ConsultationRecording).where(
            ConsultationRecording.uploaded_at < cutoff,
            ConsultationRecording.audio_deleted_at.is_(None),
            ConsultationRecording.transcription_claimed_at.is_(None),
        )).all()
        for recording in rows:
            audio_storage.delete(recording.storage_key)
            recording.audio_deleted_at = datetime.now(timezone.utc)
            removed += 1
        db.commit()
    return {"deleted_recordings": removed, "retention_days": settings.consultation_audio_retention_days}
