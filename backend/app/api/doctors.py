from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.dependencies import get_current_user
from app.db.models import User,DoctorProfile,PatientDoctor,PatientProfile,AccessAudit
from app.db.session import get_db
router=APIRouter(prefix="/doctors",tags=["doctor management"])
@router.get("/me")
def doctor_profile(actor:User=Depends(get_current_user),db:Session=Depends(get_db)):
    if actor.role!="doctor":raise HTTPException(403,"Doctor account required")
    profile=db.get(DoctorProfile,actor.id)
    if not profile:raise HTTPException(404,"Doctor profile not found")
    return {"id":actor.id,"name":actor.name,"email":actor.email,"license_number":profile.license_number,"specialty":profile.specialty}
@router.patch("/me")
def update_doctor_profile(data:dict,actor:User=Depends(get_current_user),db:Session=Depends(get_db)):
    if actor.role!="doctor":raise HTTPException(403,"Doctor account required")
    profile=db.get(DoctorProfile,actor.id)
    if not profile:raise HTTPException(404,"Doctor profile not found")
    if "name" in data:actor.name=data["name"]
    if "specialty" in data:profile.specialty=data["specialty"]
    db.commit();return {"id":actor.id,"name":actor.name,"email":actor.email,"license_number":profile.license_number,"specialty":profile.specialty}
@router.get("/me/patients")
def authorized_patients(actor:User=Depends(get_current_user),db:Session=Depends(get_db)):
    if actor.role!="doctor":raise HTTPException(403,"Doctor account required")
    rows=db.execute(select(User.id,User.name,User.email).join(PatientDoctor,PatientDoctor.patient_id==User.id).where(PatientDoctor.doctor_id==actor.id)).all()
    return [{"id":r.id,"name":r.name,"email":r.email} for r in rows]

