import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Consultation, ConsultationApproval, ConsultationConsent, ConsultationRecording, ConsultationSummary, ConsultationTranscriptSegment
from app.timeline.integrations import register_source_verifier
from app.timeline.service import record_timeline_event


def verify_timeline_source(db: Session, patient_id: int, source_record_id: str) -> bool:
    try:
        consultation = db.get(Consultation, int(source_record_id))
    except (TypeError, ValueError):
        return False
    return bool(consultation and consultation.patient_id == patient_id)


register_source_verifier("consultation", verify_timeline_source)


def timeline_event(db: Session, consultation: Consultation, event_type: str, title: str, event_date: datetime, status: str):
    return record_timeline_event(db, patient_id=consultation.patient_id, event_type=event_type,
        title=title, event_date=event_date, source_module="consultation",
        source_record_id=str(consultation.id), status=status)


def active_consent(db: Session, consultation_id: int) -> ConsultationConsent | None:
    latest = db.scalar(select(ConsultationConsent).where(
        ConsultationConsent.consultation_id == consultation_id,
    ).order_by(ConsultationConsent.consented_at.desc(), ConsultationConsent.id.desc()).limit(1))
    return latest if latest and latest.consented and latest.revoked_at is None else None


def latest_summary(db: Session, consultation_id: int) -> ConsultationSummary | None:
    return db.scalar(select(ConsultationSummary).where(
        ConsultationSummary.consultation_id == consultation_id,
        ConsultationSummary.status != "superseded",
    ).order_by(ConsultationSummary.version.desc()))


def summary_dict(summary: ConsultationSummary | None):
    if not summary:
        return None
    return {"id": summary.id, "version": summary.version, "status": summary.status,
        "content": json.loads(summary.content), "generated_by": summary.generated_by,
        "created_at": summary.created_at, "updated_at": summary.updated_at}


def record_audit(db: Session, actor_id: int, patient_id: int, action: str):
    from app.db.models import AccessAudit
    db.add(AccessAudit(actor_id=actor_id, patient_id=patient_id, action=action))
