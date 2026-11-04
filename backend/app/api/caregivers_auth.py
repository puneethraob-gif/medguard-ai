from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.schemas import Registration
from app.core.security import hash_password
from app.db.models import User
from app.db.session import get_db
router = APIRouter(prefix="/auth", tags=["authentication"])
@router.post("/register/caregiver", status_code=201)
def register_caregiver(data: Registration, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == data.email.lower())): raise HTTPException(409, "Email already registered")
    user = User(email=data.email.lower(), name=data.name, password_hash=hash_password(data.password), role="caregiver")
    db.add(user); db.commit(); db.refresh(user)
    return {"id": user.id, "email": user.email, "role": user.role}
