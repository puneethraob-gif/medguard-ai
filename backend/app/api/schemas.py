from pydantic import BaseModel, Field
from datetime import date, datetime
from typing import Any

class Registration(BaseModel):
    email: str
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=12, max_length=128)
    role: str = "patient"
    date_of_birth: date | None = None
    phone: str | None = None
    preferred_language: str = "en"
class Login(BaseModel):
    email: str
    password: str
class PatientUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    date_of_birth: date | None = None
    phone: str | None = None
    preferred_language: str | None = Field(default=None, max_length=16)
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    medical_history: str | None = None
    allergies: str | None = None
class DoctorRegistration(BaseModel):
    email: str
    name: str
    password: str = Field(min_length=12, max_length=128)
    license_number: str
    specialty: str | None = None
class HospitalRegistration(BaseModel):
    name: str
    registration_number: str
class ConsentGrant(BaseModel):
    caregiver_email: str
    scope: str = "profile"

class TimelineEventResponse(BaseModel):
    id: int
    patient_id: int
    event_type: str
    title: str
    description: str | None
    event_date: datetime
    source_module: str
    source_record_id: str
    status: str
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime

class TimelinePageResponse(BaseModel):
    items: list[TimelineEventResponse]
    total: int
    page: int
    page_size: int

class TimelineNextStepResponse(BaseModel):
    event_id: int
    event_type: str
    title: str
    description: str | None
    event_date: datetime
    action: str
    status: str

class TimelineSummaryResponse(BaseModel):
    total_events: int
    upcoming_count: int
    pending_count: int
    completed_count: int
    next_steps: list[TimelineNextStepResponse]
