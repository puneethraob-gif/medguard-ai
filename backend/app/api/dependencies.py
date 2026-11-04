from fastapi import Depends,HTTPException,Cookie
from fastapi.security import HTTPAuthorizationCredentials,HTTPBearer
import jwt
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.security import ALGORITHM,signing_secret
from app.db.session import get_db
from app.db.models import User,AuthSession
bearer=HTTPBearer(auto_error=False)
def get_current_user(credentials:HTTPAuthorizationCredentials|None=Depends(bearer),access_token:str|None=Cookie(default=None),db:Session=Depends(get_db))->User:
    token=credentials.credentials if credentials else access_token
    if not token:raise HTTPException(401,"Authentication required")
    try:
        payload=jwt.decode(token,signing_secret(),algorithms=[ALGORITHM]);user=db.get(User,int(payload["sub"]));session=db.get(AuthSession,payload["sid"])
    except (jwt.InvalidTokenError,KeyError,ValueError,RuntimeError):user=None;session=None
    if not user or not user.is_active or not session or session.revoked_at:raise HTTPException(401,"Invalid or revoked access token")
    return user
def require_roles(*roles):
    def guard(user:User=Depends(get_current_user)):
        if user.role not in roles:raise HTTPException(403,"Insufficient permissions")
        return user
    return guard
