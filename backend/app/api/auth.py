from datetime import datetime,timezone
from fastapi import APIRouter,Depends,HTTPException,Response,Cookie
from fastapi.security import HTTPAuthorizationCredentials,HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.schemas import Registration,Login,DoctorRegistration
from app.core.security import hash_password,verify_password,issue_access,issue_refresh,hash_token,signing_secret,ALGORITHM
from app.core.config import settings
from app.api.dependencies import get_current_user
from app.db.models import User,PatientProfile,DoctorProfile,AuthSession
from app.db.session import get_db
import jwt,uuid
router=APIRouter(prefix="/auth",tags=["authentication"])
logout_bearer=HTTPBearer(auto_error=False)
def safe_user(user):return {"id":user.id,"name":user.name,"email":user.email,"role":user.role}
def new_session(db,user,family_id=None):
    sid=str(uuid.uuid4()); refresh=issue_refresh()
    session=AuthSession(id=sid,user_id=user.id,family_id=family_id or str(uuid.uuid4()),refresh_hash=hash_token(refresh),expires_at=datetime.now(timezone.utc)+timedelta(days=settings.refresh_token_days))
    db.add(session);db.flush();return session,refresh,issue_access(user,sid)
from datetime import timedelta
@router.post("/register/patient",status_code=201)
def register_patient(data:Registration,db:Session=Depends(get_db)):
    if data.role!="patient":raise HTTPException(400,"Patient registration only")
    if db.scalar(select(User).where(User.email==data.email.lower())):raise HTTPException(409,"Email already registered")
    user=User(email=data.email.lower(),name=data.name,password_hash=hash_password(data.password),role="patient");db.add(user);db.flush()
    db.add(PatientProfile(user_id=user.id,date_of_birth=data.date_of_birth,phone=data.phone,preferred_language=data.preferred_language));db.commit();db.refresh(user);return safe_user(user)
@router.post("/register/doctor",status_code=201)
def register_doctor(data:DoctorRegistration,db:Session=Depends(get_db)):
    if db.scalar(select(User).where(User.email==data.email.lower())):raise HTTPException(409,"Email already registered")
    user=User(email=data.email.lower(),name=data.name,password_hash=hash_password(data.password),role="doctor");db.add(user);db.flush()
    db.add(DoctorProfile(user_id=user.id,license_number=data.license_number,specialty=data.specialty));db.commit();return safe_user(user)
@router.post("/login")
def login(data:Login,db:Session=Depends(get_db)):
    user=db.scalar(select(User).where(User.email==data.email.lower()))
    if not user or not user.is_active or not verify_password(data.password,user.password_hash):raise HTTPException(401,"Invalid email or password")
    session,refresh,access=new_session(db,user);db.commit();return {"access_token":access,"refresh_token":refresh,"token_type":"bearer","user":safe_user(user)}
@router.post("/refresh")
def refresh_tokens(data:dict,db:Session=Depends(get_db)):
    token=data.get("refresh_token","");session=db.scalar(select(AuthSession).where(AuthSession.refresh_hash==hash_token(token)).with_for_update())
    if not session:raise HTTPException(401,"Invalid refresh token")
    now=datetime.now(timezone.utc)
    if session.revoked_at:
        db.query(AuthSession).filter(AuthSession.family_id==session.family_id).update({AuthSession.revoked_at:now});db.commit();raise HTTPException(401,"Refresh token reuse detected; session family revoked")
    if session.expires_at.replace(tzinfo=timezone.utc)<=now:
        session.revoked_at=now;db.commit();raise HTTPException(401,"Refresh token expired")
    user=db.get(User,session.user_id)
    if not user or not user.is_active:raise HTTPException(401,"Account inactive")
    session.revoked_at=now;replacement,new_refresh,access=new_session(db,user,session.family_id);session.replaced_by=replacement.id;db.commit()
    return {"access_token":access,"refresh_token":new_refresh,"token_type":"bearer"}
@router.post("/logout",status_code=204)
def logout(data:dict,credentials:HTTPAuthorizationCredentials|None=Depends(logout_bearer),access_token:str|None=Cookie(default=None),db:Session=Depends(get_db)):
    session=None;token=credentials.credentials if credentials else access_token
    if token:
        try:
            payload=jwt.decode(token,signing_secret(),algorithms=[ALGORITHM]);session=db.get(AuthSession,payload["sid"])
        except (jwt.InvalidTokenError,KeyError,RuntimeError):session=None
    refresh=data.get("refresh_token","")
    if refresh:
        candidate=db.scalar(select(AuthSession).where(AuthSession.refresh_hash==hash_token(refresh)))
        if candidate:session=candidate
    if session and not session.revoked_at:session.revoked_at=datetime.now(timezone.utc);db.commit()
@router.get("/me")
def me(user:User=Depends(get_current_user)):return safe_user(user)

from fastapi import Request
from fastapi.responses import Response
from secrets import token_urlsafe

def set_web_cookies(response, access, refresh, csrf):
    common={"secure":settings.secure_cookies,"samesite":"lax","path":"/api/v1/auth"}
    response.set_cookie("access_token",access,httponly=True,max_age=settings.access_token_minutes*60,**{**common,"path":"/api/v1"})
    response.set_cookie("refresh_token",refresh,httponly=True,max_age=settings.refresh_token_days*86400,**common)
    response.set_cookie("csrf_token",csrf,httponly=False,max_age=settings.refresh_token_days*86400,**{**common,"path":"/api/v1"})

@router.post("/web/login")
def web_login(data:Login,response:Response,db:Session=Depends(get_db)):
    user=db.scalar(select(User).where(User.email==data.email.lower()))
    if not user or not user.is_active or not verify_password(data.password,user.password_hash):raise HTTPException(401,"Invalid email or password")
    _,refresh,access=new_session(db,user);db.commit();csrf=__import__("secrets").token_urlsafe(32)
    set_web_cookies(response,access,refresh,csrf);return {"user":safe_user(user),"csrf_token":csrf}

@router.post("/web/refresh")
def web_refresh(request:Request,response:Response,db:Session=Depends(get_db)):
    token=request.cookies.get("refresh_token","");session=db.scalar(select(AuthSession).where(AuthSession.refresh_hash==hash_token(token)).with_for_update())
    if not session or session.revoked_at:raise HTTPException(401,"Invalid or revoked refresh token")
    now=datetime.now(timezone.utc)
    if session.expires_at.replace(tzinfo=timezone.utc)<=now:session.revoked_at=now;db.commit();raise HTTPException(401,"Refresh token expired")
    user=db.get(User,session.user_id)
    if not user or not user.is_active:raise HTTPException(401,"Account inactive")
    session.revoked_at=now;replacement,new_refresh,access=new_session(db,user,session.family_id);session.replaced_by=replacement.id;db.commit()
    csrf=__import__("secrets").token_urlsafe(32);set_web_cookies(response,access,new_refresh,csrf);return {"csrf_token":csrf}

@router.post("/web/logout",status_code=204)
def web_logout(request:Request,response:Response,actor:User=Depends(get_current_user),db:Session=Depends(get_db)):
    token=request.cookies.get("refresh_token","");session=db.scalar(select(AuthSession).where(AuthSession.refresh_hash==hash_token(token),AuthSession.user_id==actor.id))
    if session and not session.revoked_at:session.revoked_at=datetime.now(timezone.utc);db.commit()
    for name in ("access_token","refresh_token","csrf_token"):response.delete_cookie(name,path="/api/v1/auth" if name=="refresh_token" else "/api/v1")
