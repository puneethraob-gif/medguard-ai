from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.dependencies import get_current_user
from app.api.schemas import PatientUpdate, ConsentGrant
from app.db.models import User, PatientProfile, DoctorProfile, PatientDoctor, PatientHospital, Hospital, HospitalStaff, CareConsent, AccessAudit
from app.db.session import get_db

router = APIRouter(tags=["patient management"])
def serialize_profile(profile: PatientProfile, user: User):
    return {"id": user.id, "name": user.name, "email": user.email, "date_of_birth": profile.date_of_birth, "phone": profile.phone, "preferred_language": profile.preferred_language, "emergency_contact_name": profile.emergency_contact_name, "emergency_contact_phone": profile.emergency_contact_phone, "medical_history": profile.medical_history, "allergies": profile.allergies}

def authorized_patient(actor: User, patient_id: int, db: Session):
    patient = db.get(PatientProfile, patient_id); user = db.get(User, patient_id) if patient else None
    if not patient or not user: raise HTTPException(404, "Patient not found")
    if actor.id == patient_id: return patient, user
    consent = db.scalar(select(CareConsent).where(CareConsent.patient_id == patient_id, CareConsent.grantee_id == actor.id, CareConsent.active.is_(True)))
    doctor_link = db.get(PatientDoctor, (patient_id, actor.id)) if actor.role == "doctor" else None
    staff_link = db.scalar(select(HospitalStaff).join(PatientHospital, PatientHospital.hospital_id == HospitalStaff.hospital_id).where(PatientHospital.patient_id == patient_id, HospitalStaff.user_id == actor.id))
    if not consent and not doctor_link and not staff_link: raise HTTPException(404, "Patient not found")
    return patient, user

@router.get("/patients/me")
def my_profile(actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if actor.role != "patient": raise HTTPException(403, "Patient account required")
    profile, user = authorized_patient(actor, actor.id, db)
    db.add(AccessAudit(actor_id=actor.id, patient_id=actor.id, action="patient.profile.read")); db.commit()
    return serialize_profile(profile, user)

@router.patch("/patients/me")
def update_my_profile(data: PatientUpdate, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if actor.role != "patient": raise HTTPException(403, "Patient account required")
    profile = db.get(PatientProfile, actor.id)
    if not profile: raise HTTPException(404, "Patient not found")
    updates = data.model_dump(exclude_unset=True)
    if "name" in updates: actor.name = updates.pop("name")
    for key, value in updates.items(): setattr(profile, key, value)
    db.add(AccessAudit(actor_id=actor.id, patient_id=actor.id, action="patient.profile.update")); db.commit(); db.refresh(profile)
    return serialize_profile(profile, actor)

@router.get("/patients/{patient_id}")
def get_patient(patient_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile, user = authorized_patient(actor, patient_id, db)
    db.add(AccessAudit(actor_id=actor.id, patient_id=patient_id, action="patient.record.read")); db.commit()
    result = serialize_profile(profile, user)
    scopes = set(db.scalars(select(CareConsent.scope).where(CareConsent.patient_id == patient_id, CareConsent.grantee_id == actor.id, CareConsent.active.is_(True))).all())
    if actor.role == "caregiver":
        allowed = scopes
        if "medical_history" not in allowed: result["medical_history"] = None
        if "allergies" not in allowed: result["allergies"] = None
    return result

@router.post("/consents", status_code=201)
def grant_consent(data: ConsentGrant, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if actor.role != "patient": raise HTTPException(403, "Patient account required")
    if data.scope not in {"profile", "medical_history", "allergies", "timeline", "consultations", "consultation_transcript"}: raise HTTPException(400, "Unsupported consent scope")
    grantee = db.scalar(select(User).where(User.email == data.caregiver_email.lower(), User.role == "caregiver"))
    if not grantee: raise HTTPException(404, "Caregiver account not found")
    consent = CareConsent(patient_id=actor.id, grantee_id=grantee.id, scope=data.scope)
    db.add(consent); db.add(AccessAudit(actor_id=actor.id, patient_id=actor.id, action="consent.grant")); db.commit(); db.refresh(consent)
    return {"id": consent.id, "caregiver_id": grantee.id, "scope": consent.scope, "active": consent.active}

@router.delete("/consents/{consent_id}", status_code=204)
def revoke_consent(consent_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    consent = db.get(CareConsent, consent_id)
    if not consent or consent.patient_id != actor.id: raise HTTPException(404, "Consent not found")
    consent.active = False; consent.revoked_at = datetime.now(timezone.utc)
    db.add(AccessAudit(actor_id=actor.id, patient_id=actor.id, action="consent.revoke")); db.commit()

