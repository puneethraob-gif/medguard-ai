from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.api.dependencies import get_current_user
from app.db.models import AccessAudit, CareConsent, HospitalStaff, PatientDoctor, PatientHospital, PatientProfile, TimelineEvent, User
from app.db.session import get_db
from app.api.schemas import TimelineEventResponse, TimelinePageResponse, TimelineSummaryResponse
from app.timeline.service import EVENT_STATUSES, EVENT_TYPES

router = APIRouter(prefix="/timeline", tags=["healthcare timeline"])
TERMINAL_STATUSES = ("completed", "cancelled", "rejected")
NEXT_STEP_TEXT = {
    "consultation_scheduled": "Attend your upcoming consultation.",
    "follow_up_scheduled": "Attend your scheduled follow-up.",
    "test_recommended": "Arrange your recommended laboratory test.",
    "test_scheduled": "Complete your scheduled laboratory test.",
    "report_uploaded": "Collect your pending laboratory report.",
    "refill_required": "Arrange a refill for your medicine.",
    "medication_started": "Follow your active medication schedule.",
    "medication_schedule_activated": "Follow your active medication schedule.",
    "medication_schedule_changed": "Follow your updated medication schedule.",
    "appointment_updated": "Check your updated appointment details.",
}
PENDING_STATUSES = ("scheduled", "pending", "recommended", "pending_review", "active", "updated", "in_progress")


def _authorize_patient(db: Session, actor: User, patient_id: int) -> None:
    if not db.get(PatientProfile, patient_id):
        raise HTTPException(status_code=404, detail="Patient not found")
    if actor.role == "patient" and actor.id == patient_id:
        return
    if actor.role == "doctor" and db.get(PatientDoctor, (patient_id, actor.id)):
        return
    if actor.role == "caregiver" and db.scalar(select(CareConsent.id).where(
        CareConsent.patient_id == patient_id, CareConsent.grantee_id == actor.id,
        CareConsent.active.is_(True), CareConsent.scope == "timeline",
    )):
        return
    if actor.role == "hospital_staff" and db.scalar(select(HospitalStaff.id).join(
        PatientHospital, PatientHospital.hospital_id == HospitalStaff.hospital_id,
    ).where(PatientHospital.patient_id == patient_id, HospitalStaff.user_id == actor.id)):
        return
    raise HTTPException(status_code=404, detail="Patient not found")


def _resolve_patient_id(actor: User, patient_id: int | None) -> int:
    if actor.role == "patient":
        if patient_id is not None and patient_id != actor.id:
            raise HTTPException(status_code=404, detail="Patient not found")
        return actor.id
    if patient_id is None:
        raise HTTPException(status_code=400, detail="patient_id is required for this account")
    return patient_id


def _event_date(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def serialize_event(event: TimelineEvent) -> dict:
    return {
        "id": event.id,
        "patient_id": event.patient_id,
        "event_type": event.event_type,
        "title": event.title,
        "description": event.description,
        "event_date": _event_date(event.event_date),
        "source_module": event.source_module,
        "source_record_id": event.source_record_id,
        "status": event.status,
        "metadata": event.event_metadata or {},
        "created_at": _event_date(event.created_at),
        "updated_at": _event_date(event.updated_at),
    }


def _query_events(
    db: Session,
    patient_id: int,
    event_types: list[str],
    statuses: list[str],
    date_from: datetime | None,
    date_to: datetime | None,
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from must be earlier than or equal to date_to")
    if event_types:
        invalid = set(event_types) - EVENT_TYPES
        if invalid:
            raise HTTPException(status_code=422, detail=f"Unsupported event_type: {sorted(invalid)[0]}")
    if statuses:
        invalid_statuses = set(statuses) - EVENT_STATUSES
        if invalid_statuses:
            raise HTTPException(status_code=422, detail=f"Unsupported status: {sorted(invalid_statuses)[0]}")
    query = select(TimelineEvent).where(TimelineEvent.patient_id == patient_id)
    if event_types:
        query = query.where(TimelineEvent.event_type.in_(event_types))
    if statuses:
        query = query.where(TimelineEvent.status.in_(statuses))
    if date_from:
        query = query.where(TimelineEvent.event_date >= date_from)
    if date_to:
        query = query.where(TimelineEvent.event_date <= date_to)
    return query


def _latest_source_event():
    newer = aliased(TimelineEvent)
    return ~select(newer.id).where(
        newer.patient_id == TimelineEvent.patient_id,
        newer.source_module == TimelineEvent.source_module,
        newer.source_record_id == TimelineEvent.source_record_id,
        or_(
            newer.created_at > TimelineEvent.created_at,
            and_(newer.created_at == TimelineEvent.created_at, newer.id > TimelineEvent.id),
        ),
    ).exists()


def _record_read(db: Session, actor: User, patient_id: int, action: str) -> None:
    db.add(AccessAudit(actor_id=actor.id, patient_id=patient_id, action=action))
    db.commit()


@router.get("", response_model=TimelinePageResponse, summary="List a patient's healthcare timeline", description="Returns the patient-scoped timeline in reverse chronological order. Supports repeated event_type/status filters, inclusive date filters, and pagination. Patients may omit patient_id to read their own timeline; other authorized roles must provide it.")
def get_timeline(
    patient_id: int | None = None,
    event_type: list[str] = Query(default=[], description="Repeat to filter by multiple event types."),
    status: list[str] = Query(default=[], description="Repeat to filter by multiple statuses."),
    date_from: datetime | None = Query(default=None, description="Inclusive lower event_date bound."),
    date_to: datetime | None = Query(default=None, description="Inclusive upper event_date bound."),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    target_id = _resolve_patient_id(actor, patient_id)
    _authorize_patient(db, actor, target_id)
    base = _query_events(db, target_id, event_type, status, date_from, date_to)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    events = db.scalars(base.order_by(TimelineEvent.event_date.desc(), TimelineEvent.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    _record_read(db, actor, target_id, "timeline.list.read")
    return {"items": [serialize_event(event) for event in events], "total": total, "page": page, "page_size": page_size}


@router.get("/upcoming", response_model=TimelinePageResponse, summary="List upcoming healthcare activities", description="Returns the latest nonterminal event for each source record whose event_date is now or later, ordered soonest first. Supports the same event, status, date, and pagination filters as the full timeline.")
def get_upcoming(
    patient_id: int | None = None,
    event_type: list[str] = Query(default=[], description="Repeat to filter by multiple event types."),
    status: list[str] = Query(default=[], description="Repeat to filter by multiple statuses."),
    date_from: datetime | None = Query(default=None, description="Inclusive lower event_date bound."),
    date_to: datetime | None = Query(default=None, description="Inclusive upper event_date bound."),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    target_id = _resolve_patient_id(actor, patient_id)
    _authorize_patient(db, actor, target_id)
    base = _query_events(db, target_id, event_type, status, date_from, date_to).where(
        TimelineEvent.event_date >= datetime.now(timezone.utc),
        TimelineEvent.status.not_in(TERMINAL_STATUSES),
        _latest_source_event(),
    )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    events = db.scalars(base.order_by(TimelineEvent.event_date.asc(), TimelineEvent.id.asc()).offset((page - 1) * page_size).limit(page_size)).all()
    _record_read(db, actor, target_id, "timeline.upcoming.read")
    return {"items": [serialize_event(event) for event in events], "total": total, "page": page, "page_size": page_size}


@router.get("/summary", response_model=TimelineSummaryResponse, summary="Get timeline counts and verified next steps", description="Counts current source-record events and returns fixed, non-AI next-step text derived from actual pending timeline records.")
def get_timeline_summary(
    patient_id: int | None = None,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    target_id = _resolve_patient_id(actor, patient_id)
    _authorize_patient(db, actor, target_id)
    now = datetime.now(timezone.utc)
    latest = _latest_source_event()
    base = select(TimelineEvent).where(TimelineEvent.patient_id == target_id, latest)
    total = db.scalar(select(func.count()).select_from(TimelineEvent).where(TimelineEvent.patient_id == target_id)) or 0
    upcoming_count = db.scalar(select(func.count()).select_from(TimelineEvent).where(
        TimelineEvent.patient_id == target_id, TimelineEvent.event_date >= now,
        TimelineEvent.status.not_in(TERMINAL_STATUSES), latest,
    )) or 0
    pending_count = db.scalar(select(func.count()).select_from(TimelineEvent).where(
        TimelineEvent.patient_id == target_id, TimelineEvent.status.in_(PENDING_STATUSES), latest,
    )) or 0
    completed_count = db.scalar(select(func.count()).select_from(TimelineEvent).where(
        TimelineEvent.patient_id == target_id, TimelineEvent.status == "completed", latest,
    )) or 0
    pending = db.scalars(base.where(
        TimelineEvent.status.in_(PENDING_STATUSES), TimelineEvent.event_type.in_(NEXT_STEP_TEXT.keys()),
    ).order_by(TimelineEvent.event_date.asc(), TimelineEvent.id.asc()).limit(10)).all()
    next_steps = [
        {"event_id": event.id, "event_type": event.event_type, "title": event.title, "description": event.description,
         "event_date": _event_date(event.event_date), "action": NEXT_STEP_TEXT[event.event_type], "status": event.status}
        for event in pending
    ]
    _record_read(db, actor, target_id, "timeline.summary.read")
    return {
        "total_events": total,
        "upcoming_count": upcoming_count,
        "pending_count": pending_count,
        "completed_count": completed_count,
        "next_steps": next_steps,
    }


@router.get("/{event_id}", response_model=TimelineEventResponse, summary="Get one authorized timeline event", description="Returns event details only when the current user can access the event's patient record.")
def get_timeline_event(
    event_id: int,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    event = db.get(TimelineEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Timeline event not found")
    _authorize_patient(db, actor, event.patient_id)
    _record_read(db, actor, event.patient_id, "timeline.event.read")
    return serialize_event(event)
