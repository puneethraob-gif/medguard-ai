from datetime import timedelta
import hashlib,hmac,secrets,uuid
import jwt
from app.core.config import settings
ALGORITHM="HS256"
def signing_secret():
    if len(settings.jwt_secret.encode())<32: raise RuntimeError("Set JWT_SECRET to a random value of at least 32 bytes")
    return settings.jwt_secret
def hash_password(password):
    salt=secrets.token_bytes(16); derived=hashlib.scrypt(password.encode(),salt=salt,n=2**14,r=8,p=1)
    return f"scrypt${salt.hex()}${derived.hex()}"
def verify_password(password,stored):
    try:
        scheme,salt,expected=stored.split("$")
        actual=hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=2**14,r=8,p=1).hex()
        return scheme=="scrypt" and hmac.compare_digest(actual,expected)
    except (ValueError,TypeError):return False
def hash_token(token):return hashlib.sha256(token.encode()).hexdigest()
def issue_access(user,session_id):
    from datetime import datetime,timezone
    now=datetime.now(timezone.utc)
    return jwt.encode({"sub":str(user.id),"role":user.role,"sid":session_id,"jti":secrets.token_urlsafe(16),"iat":now,"exp":now+timedelta(minutes=settings.access_token_minutes)},signing_secret(),algorithm=ALGORITHM)
def issue_refresh():return secrets.token_urlsafe(48)
