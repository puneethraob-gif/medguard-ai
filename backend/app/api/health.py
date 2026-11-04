from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db.session import get_db

router = APIRouter(tags=["health"])

@router.get("/health", summary="Liveness check")
def health():
    return {"status": "ok"}

@router.get("/health/ready", summary="Readiness check")
def readiness(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ready", "database": "ok"}
