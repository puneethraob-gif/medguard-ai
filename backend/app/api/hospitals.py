from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.dependencies import get_current_user
from app.api.schemas import HospitalRegistration
from app.core.security import hash_password
from app.db.models import User, Hospital, HospitalStaff, PatientHospital, PatientDoctor, DoctorProfile
from app.db.session import get_db

router = APIRouter(prefix="/hospitals", tags=["hospitals"])
@router.post("", status_code=201)
def register_hospital(data: HospitalRegistration, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if actor.role not in {"hospital_staff", "doctor"}: raise HTTPException(403, "Hospital account required")
    hospital = Hospital(name=data.name, registration_number=data.registration_number)
    db.add(hospital); db.flush(); db.add(HospitalStaff(hospital_id=hospital.id, user_id=actor.id, staff_role="admin")); db.commit()
    return {"id": hospital.id, "name": hospital.name, "registration_number": hospital.registration_number}

@router.post("/{hospital_id}/staff", status_code=201)
def add_staff(hospital_id: int, email: str, name: str, password: str, staff_role: str = "staff", actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    admin = db.scalar(select(HospitalStaff).where(HospitalStaff.hospital_id == hospital_id, HospitalStaff.user_id == actor.id, HospitalStaff.staff_role == "admin"))
    if not admin: raise HTTPException(404, "Hospital not found")
    email = email.lower()
    user = db.scalar(select(User).where(User.email == email))
    if user: raise HTTPException(409, "Email already registered")
    user = User(email=email, name=name, password_hash=hash_password(password), role="hospital_staff")
    db.add(user); db.flush(); db.add(HospitalStaff(hospital_id=hospital_id, user_id=user.id, staff_role=staff_role)); db.commit()
    return {"id": user.id, "email": email, "role": user.role, "staff_role": staff_role}

@router.post("/{hospital_id}/patients/{patient_id}", status_code=204)
def link_patient(hospital_id: int, patient_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if actor.role != "patient" or actor.id != patient_id: raise HTTPException(403, "Patients may link only their own account")
    if not db.get(Hospital, hospital_id): raise HTTPException(404, "Hospital not found")
    if not db.get(PatientHospital, (patient_id, hospital_id)): db.add(PatientHospital(patient_id=patient_id, hospital_id=hospital_id)); db.commit()

@router.post("/doctors/{doctor_id}/patients/{patient_id}", status_code=204)
def authorize_doctor(doctor_id: int, patient_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if actor.role != "patient" or actor.id != patient_id: raise HTTPException(403, "Patients may authorize doctors for their own account")
    if not db.get(DoctorProfile, doctor_id): raise HTTPException(404, "Doctor not found")
    if not db.get(PatientDoctor, (patient_id, doctor_id)): db.add(PatientDoctor(patient_id=patient_id, doctor_id=doctor_id, authorized_by=actor.id)); db.commit()
