"""Timeline write service for verified clinical-module integrations."""
import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import TimelineEvent
from app.timeline.integrations import SOURCE_MODULES, get_source_verifier

EVENT_TYPES = frozenset({
    "consultation_scheduled", "consultation_completed", "summary_generated", "summary_approved",
    "prescription_uploaded", "prescription_approved", "medication_schedule_activated", "prescription_updated",
    "medication_course_completed", "medication_started", "medication_completed", "medication_schedule_changed",
    "refill_required", "test_recommended", "test_scheduled", "test_completed", "report_uploaded", "report_reviewed",
    "follow_up_scheduled", "appointment_updated", "appointment_completed", "appointment_cancelled",
})
EVENT_STATUSES = frozenset({
    "scheduled", "pending", "recommended", "pending_review", "active", "updated",
    "completed", "approved", "reviewed", "cancelled", "rejected", "in_progress",
})
EVENT_SOURCE_MODULE = {
    **{name: "consultation" for name in ("consultation_scheduled", "consultation_completed", "summary_generated", "summary_approved")},
    **{name: "prescription" for name in ("prescription_uploaded", "prescription_approved", "prescription_updated")},
    **{name: "medicine" for name in ("medication_schedule_activated", "medication_course_completed", "medication_started", "medication_completed", "medication_schedule_changed", "refill_required")},
    **{name: "laboratory" for name in ("test_recommended", "test_scheduled", "test_completed", "report_uploaded", "report_reviewed")},
    **{name: "appointment" for name in ("follow_up_scheduled", "appointment_updated", "appointment_completed", "appointment_cancelled")},
}
_SENSITIVE_METADATA_KEYS = frozenset({
    "diagnosis", "symptoms", "medical_history", "allergies", "clinical_notes", "report_text",
    "prescription_text", "summary_text", "patient_record", "full_record",
})


class InvalidTimelineEvent(ValueError):
    pass


class UnverifiedTimelineSource(ValueError):
    pass


def record_timeline_event(
    db: Session,
    *,
    patient_id: int,
    event_type: str,
    title: str,
    event_date: datetime,
    source_module: str,
    source_record_id: str,
    status: str,
    description: str | None = None,
    metadata: dict | None = None,
) -> tuple[TimelineEvent, bool]:
    """Create one event only when its owning module confirms the source record.

    Returns ``(event, created)``. The owning transaction remains the caller's.
    Repeated delivery is idempotent; a database unique constraint handles races.
    Timeline fields are short references, never full source records.
    """
    if event_type not in EVENT_TYPES:
        raise InvalidTimelineEvent("Unsupported timeline event type")
    if source_module not in SOURCE_MODULES:
        raise InvalidTimelineEvent("Unsupported timeline source module")
    if EVENT_SOURCE_MODULE[event_type] != source_module:
        raise InvalidTimelineEvent("Event type does not belong to the selected source module")
    if status not in EVENT_STATUSES:
        raise InvalidTimelineEvent("Unsupported timeline status")
    if not title.strip() or len(title) > 180:
        raise InvalidTimelineEvent("Title must contain 1 to 180 characters")
    if description is not None and len(description) > 500:
        raise InvalidTimelineEvent("Description must be no more than 500 characters")
    if not source_record_id.strip() or len(source_record_id) > 100:
        raise InvalidTimelineEvent("A source record reference is required")
    if event_date.tzinfo is None:
        raise InvalidTimelineEvent("event_date must include a timezone")
    metadata = metadata or {}
    if not isinstance(metadata, dict):
        raise InvalidTimelineEvent("Metadata must be an object")
    if _SENSITIVE_METADATA_KEYS.intersection(key.lower() for key in metadata):
        raise InvalidTimelineEvent("Metadata must not contain medical record content")
    try:
        if len(json.dumps(metadata, ensure_ascii=False).encode("utf-8")) > 2048:
            raise InvalidTimelineEvent("Metadata is limited to small source-reference details")
        json.dumps(metadata)
    except (TypeError, ValueError) as exc:
        if isinstance(exc, InvalidTimelineEvent):
            raise
        raise InvalidTimelineEvent("Metadata must contain JSON values") from exc

    verifier = get_source_verifier(source_module)
    if verifier is None or not verifier(db, patient_id, source_record_id):
        raise UnverifiedTimelineSource("The source module did not verify this patient record")

    identity = (patient_id, event_type, source_module, source_record_id)
    existing = db.scalar(select(TimelineEvent).where(
        TimelineEvent.patient_id == identity[0], TimelineEvent.event_type == identity[1],
        TimelineEvent.source_module == identity[2], TimelineEvent.source_record_id == identity[3],
    ))
    if existing:
        return existing, False

    event = TimelineEvent(
        patient_id=patient_id,
        event_type=event_type,
        title=title.strip(),
        description=description.strip() if description else None,
        event_date=event_date.astimezone(timezone.utc),
        source_module=source_module,
        source_record_id=source_record_id,
        status=status,
        event_metadata=metadata,
    )
    savepoint = db.begin_nested()
    db.add(event)
    try:
        savepoint.commit()
        return event, True
    except IntegrityError:
        savepoint.rollback()
        duplicate = db.scalar(select(TimelineEvent).where(
            TimelineEvent.patient_id == identity[0], TimelineEvent.event_type == identity[1],
            TimelineEvent.source_module == identity[2], TimelineEvent.source_record_id == identity[3],
        ))
        if duplicate:
            return duplicate, False
        raise

