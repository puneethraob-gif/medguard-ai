from datetime import date, datetime, timezone
from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint, Float, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base
from app.db.encryption import EncryptedText,EncryptedDate
class User(Base):
    __tablename__="users"
    id:Mapped[int]=mapped_column(primary_key=True)
    email:Mapped[str]=mapped_column(String(320),unique=True,index=True)
    name:Mapped[str]=mapped_column(String(200))
    password_hash:Mapped[str]=mapped_column(String(256))
    role:Mapped[str]=mapped_column(String(20),index=True)
    is_active:Mapped[bool]=mapped_column(Boolean,default=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
    patient:Mapped["PatientProfile"]=relationship(back_populates="user",uselist=False)
    doctor:Mapped["DoctorProfile"]=relationship(back_populates="user",uselist=False)
class PatientProfile(Base):
    __tablename__="patient_profiles"
    user_id:Mapped[int]=mapped_column(ForeignKey("users.id",ondelete="CASCADE"),primary_key=True)
    date_of_birth:Mapped[date|None]=mapped_column(EncryptedDate())
    phone:Mapped[str|None]=mapped_column(EncryptedText())
    preferred_language:Mapped[str]=mapped_column(String(16),default="en")
    emergency_contact_name:Mapped[str|None]=mapped_column(EncryptedText())
    emergency_contact_phone:Mapped[str|None]=mapped_column(EncryptedText())
    medical_history:Mapped[str|None]=mapped_column(EncryptedText())
    allergies:Mapped[str|None]=mapped_column(EncryptedText())
    user:Mapped[User]=relationship(back_populates="patient")
class DoctorProfile(Base):
    __tablename__="doctor_profiles"
    user_id:Mapped[int]=mapped_column(ForeignKey("users.id",ondelete="CASCADE"),primary_key=True)
    license_number:Mapped[str|None]=mapped_column(String(100),unique=True)
    specialty:Mapped[str|None]=mapped_column(String(160))
    user:Mapped[User]=relationship(back_populates="doctor")
class Hospital(Base):
    __tablename__="hospitals"
    id:Mapped[int]=mapped_column(primary_key=True)
    name:Mapped[str]=mapped_column(String(200))
    registration_number:Mapped[str]=mapped_column(String(100),unique=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
class HospitalStaff(Base):
    __tablename__="hospital_staff"
    __table_args__=(UniqueConstraint("hospital_id","user_id"),)
    id:Mapped[int]=mapped_column(primary_key=True)
    hospital_id:Mapped[int]=mapped_column(ForeignKey("hospitals.id",ondelete="CASCADE"),index=True)
    user_id:Mapped[int]=mapped_column(ForeignKey("users.id",ondelete="CASCADE"),index=True)
    staff_role:Mapped[str]=mapped_column(String(40),default="staff")
class PatientDoctor(Base):
    __tablename__="patient_doctors"
    patient_id:Mapped[int]=mapped_column(ForeignKey("patient_profiles.user_id",ondelete="CASCADE"),primary_key=True)
    doctor_id:Mapped[int]=mapped_column(ForeignKey("doctor_profiles.user_id",ondelete="CASCADE"),primary_key=True)
    authorized_by:Mapped[int]=mapped_column(ForeignKey("users.id"))
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
class PatientHospital(Base):
    __tablename__="patient_hospitals"
    patient_id:Mapped[int]=mapped_column(ForeignKey("patient_profiles.user_id",ondelete="CASCADE"),primary_key=True)
    hospital_id:Mapped[int]=mapped_column(ForeignKey("hospitals.id",ondelete="CASCADE"),primary_key=True)
    linked_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
class CareConsent(Base):
    __tablename__="care_consents"
    id:Mapped[int]=mapped_column(primary_key=True)
    patient_id:Mapped[int]=mapped_column(ForeignKey("patient_profiles.user_id",ondelete="CASCADE"),index=True)
    grantee_id:Mapped[int]=mapped_column(ForeignKey("users.id",ondelete="CASCADE"),index=True)
    scope:Mapped[str]=mapped_column(String(30))
    active:Mapped[bool]=mapped_column(Boolean,default=True)
    granted_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
    revoked_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
class AccessAudit(Base):
    __tablename__="access_audit"
    id:Mapped[int]=mapped_column(primary_key=True)
    actor_id:Mapped[int|None]=mapped_column(ForeignKey("users.id",ondelete="SET NULL"),index=True)
    patient_id:Mapped[int|None]=mapped_column(ForeignKey("patient_profiles.user_id",ondelete="SET NULL"),index=True)
    action:Mapped[str]=mapped_column(String(80))
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
class AuthSession(Base):
    __tablename__="auth_sessions"
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    user_id:Mapped[int]=mapped_column(ForeignKey("users.id",ondelete="CASCADE"),index=True)
    family_id:Mapped[str]=mapped_column(String(36),index=True)
    refresh_hash:Mapped[str]=mapped_column(String(64),unique=True)
    expires_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    revoked_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    replaced_by:Mapped[str|None]=mapped_column(String(36))

class TimelineEvent(Base):
    __tablename__="timeline_events"
    __table_args__=(
        CheckConstraint("event_type IN (" + ",".join(repr(value) for value in ("consultation_scheduled","consultation_completed","summary_generated","summary_approved","prescription_uploaded","prescription_approved","medication_schedule_activated","prescription_updated","medication_course_completed","medication_started","medication_completed","medication_schedule_changed","refill_required","test_recommended","test_scheduled","test_completed","report_uploaded","report_reviewed","follow_up_scheduled","appointment_updated","appointment_completed","appointment_cancelled")) + ")",name="ck_timeline_event_type"),
        CheckConstraint("status IN (" + ",".join(repr(value) for value in ("scheduled","pending","recommended","pending_review","active","updated","completed","approved","reviewed","cancelled","rejected","in_progress")) + ")",name="ck_timeline_status"),
        CheckConstraint("source_module IN ('consultation','prescription','medicine','laboratory','appointment')",name="ck_timeline_source_module"),
        UniqueConstraint("patient_id","event_type","source_module","source_record_id",name="uq_timeline_source_event"),
        Index("ix_timeline_patient_date","patient_id","event_date"),
        Index("ix_timeline_patient_type_date","patient_id","event_type","event_date"),
        Index("ix_timeline_patient_status_date","patient_id","status","event_date"),
    )
    id:Mapped[int]=mapped_column(primary_key=True)
    patient_id:Mapped[int]=mapped_column(ForeignKey("patient_profiles.user_id",ondelete="CASCADE"),nullable=False)
    event_type:Mapped[str]=mapped_column(String(48),nullable=False)
    title:Mapped[str]=mapped_column(String(180),nullable=False)
    description:Mapped[str|None]=mapped_column(String(500))
    event_date:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    source_module:Mapped[str]=mapped_column(String(40),nullable=False)
    source_record_id:Mapped[str]=mapped_column(String(100),nullable=False)
    status:Mapped[str]=mapped_column(String(32),nullable=False)
    event_metadata:Mapped[dict]=mapped_column("metadata",JSON,nullable=False,default=dict)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc),nullable=False)
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc),onupdate=lambda:datetime.now(timezone.utc),nullable=False)


class Consultation(Base):
    __tablename__="consultations"
    __table_args__=(
        CheckConstraint("status IN ('scheduled','consented','recording','uploaded','completed','transcribing','transcribed','summarizing','in_review','approved','cancelled','failed')",name="ck_consultation_status"),
        Index("ix_consultation_patient_date","patient_id","scheduled_at"),
        Index("ix_consultation_doctor_date","doctor_id","scheduled_at"),
    )
    id:Mapped[int]=mapped_column(primary_key=True)
    patient_id:Mapped[int]=mapped_column(ForeignKey("patient_profiles.user_id",ondelete="CASCADE"),nullable=False)
    doctor_id:Mapped[int]=mapped_column(ForeignKey("doctor_profiles.user_id",ondelete="RESTRICT"),nullable=False)
    created_by_id:Mapped[int]=mapped_column(ForeignKey("users.id",ondelete="RESTRICT"),nullable=False)
    status:Mapped[str]=mapped_column(String(24),nullable=False,default="scheduled")
    scheduled_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    started_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    completed_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    transcript_patient_access:Mapped[bool]=mapped_column(Boolean,default=False,nullable=False)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc),nullable=False)
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc),onupdate=lambda:datetime.now(timezone.utc),nullable=False)


class ConsultationConsent(Base):
    __tablename__="consultation_consents"
    id:Mapped[int]=mapped_column(primary_key=True)
    consultation_id:Mapped[int]=mapped_column(ForeignKey("consultations.id",ondelete="CASCADE"),index=True,nullable=False)
    patient_id:Mapped[int]=mapped_column(ForeignKey("patient_profiles.user_id",ondelete="CASCADE"),index=True,nullable=False)
    consented_by_id:Mapped[int]=mapped_column(ForeignKey("users.id",ondelete="RESTRICT"),nullable=False)
    consented:Mapped[bool]=mapped_column(Boolean,nullable=False)
    consent_text_version:Mapped[str]=mapped_column(String(40),nullable=False)
    language:Mapped[str]=mapped_column(String(16),nullable=False)
    consented_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc),nullable=False)
    revoked_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))


class ConsultationRecording(Base):
    __tablename__="consultation_recordings"
    id:Mapped[int]=mapped_column(primary_key=True)
    consultation_id:Mapped[int]=mapped_column(ForeignKey("consultations.id",ondelete="CASCADE"),unique=True,index=True,nullable=False)
    storage_key:Mapped[str]=mapped_column(String(120),unique=True,nullable=False)
    content_type:Mapped[str]=mapped_column(String(100),nullable=False)
    byte_size:Mapped[int]=mapped_column(Integer,nullable=False)
    sha256:Mapped[str]=mapped_column(String(64),nullable=False)
    audio_deleted_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    provider_job_id:Mapped[str|None]=mapped_column(String(100),unique=True)
    provider_job_terminal:Mapped[bool]=mapped_column(Boolean,default=False,nullable=False)
    provider_job_uploaded:Mapped[bool]=mapped_column(Boolean,default=False,nullable=False)
    provider_job_started:Mapped[bool]=mapped_column(Boolean,default=False,nullable=False)
    transcription_queued_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    transcription_claimed_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    transcription_attempts:Mapped[int]=mapped_column(Integer,default=0,nullable=False)
    duration_seconds:Mapped[float|None]=mapped_column(Float)
    uploaded_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc),nullable=False)


class ConsultationTranscriptSegment(Base):
    __tablename__="consultation_transcript_segments"
    __table_args__=(UniqueConstraint("consultation_id","sequence",name="uq_consultation_transcript_sequence"),Index("ix_consultation_transcript_time","consultation_id","start_seconds"))
    id:Mapped[int]=mapped_column(primary_key=True)
    consultation_id:Mapped[int]=mapped_column(ForeignKey("consultations.id",ondelete="CASCADE"),index=True,nullable=False)
    sequence:Mapped[int]=mapped_column(Integer,nullable=False)
    text:Mapped[str]=mapped_column(EncryptedText(),nullable=False)
    language_code:Mapped[str|None]=mapped_column(String(24))
    start_seconds:Mapped[float]=mapped_column(Float,nullable=False)
    end_seconds:Mapped[float]=mapped_column(Float,nullable=False)
    speaker_id:Mapped[str|None]=mapped_column(String(40))
    speaker_role:Mapped[str|None]=mapped_column(String(20))
    confidence:Mapped[float|None]=mapped_column(Float)
    provider:Mapped[str]=mapped_column(String(40),nullable=False)


class ConsultationSummary(Base):
    __tablename__="consultation_summaries"
    __table_args__=(CheckConstraint("status IN ('draft','in_review','approved','superseded')",name="ck_consultation_summary_status"),Index("ix_consultation_summary_status","consultation_id","status"))
    id:Mapped[int]=mapped_column(primary_key=True)
    consultation_id:Mapped[int]=mapped_column(ForeignKey("consultations.id",ondelete="CASCADE"),index=True,nullable=False)
    version:Mapped[int]=mapped_column(Integer,nullable=False)
    status:Mapped[str]=mapped_column(String(20),nullable=False,default="draft")
    content:Mapped[str]=mapped_column(EncryptedText(),nullable=False)
    generated_by:Mapped[str]=mapped_column(String(40),nullable=False)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc),nullable=False)
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc),onupdate=lambda:datetime.now(timezone.utc),nullable=False)


class ConsultationApproval(Base):
    __tablename__="consultation_approvals"
    id:Mapped[int]=mapped_column(primary_key=True)
    consultation_id:Mapped[int]=mapped_column(ForeignKey("consultations.id",ondelete="CASCADE"),index=True,nullable=False)
    summary_id:Mapped[int]=mapped_column(ForeignKey("consultation_summaries.id",ondelete="RESTRICT"),index=True,nullable=False)
    doctor_id:Mapped[int]=mapped_column(ForeignKey("doctor_profiles.user_id",ondelete="RESTRICT"),nullable=False)
    action:Mapped[str]=mapped_column(String(20),nullable=False)
    comment:Mapped[str|None]=mapped_column(EncryptedText())
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc),nullable=False)

