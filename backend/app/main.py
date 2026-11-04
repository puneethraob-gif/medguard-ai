import logging
import hmac
import json
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.api.health import router as health_router
from app.api.auth import router as auth_router
from app.api.caregivers_auth import router as caregivers_auth_router
from app.api.patients import router as patients_router
from app.api.hospitals import router as hospitals_router
from app.api.doctors import router as doctors_router
from app.api.timeline import router as timeline_router
from app.api.consultations import router as consultations_router
from app.core.config import settings
from app.core.rate_limit import AuthRateLimiter
from app.db import models
logging.basicConfig(level=logging.INFO)
# httpx includes complete URLs in INFO request logs. Sarvam's batch workflow
# uses short-lived signed object-store URLs, so those URLs must never enter logs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
app=FastAPI(title=settings.app_name,version="0.3.0",description="Personal Healthcare Companion API")
auth_rate_limiter = AuthRateLimiter(settings.redis_url)
_AUTH_RATE_LIMIT_PATHS = {
    f"{settings.api_v1_prefix}/auth/login": "login",
    f"{settings.api_v1_prefix}/auth/web/login": "web-login",
    f"{settings.api_v1_prefix}/auth/refresh": "refresh",
    f"{settings.api_v1_prefix}/auth/web/refresh": "web-refresh",
    f"{settings.api_v1_prefix}/auth/register/patient": "register-patient",
    f"{settings.api_v1_prefix}/auth/register/doctor": "register-doctor",
    f"{settings.api_v1_prefix}/auth/register/caregiver": "register-caregiver",
}
app.add_middleware(CORSMiddleware,allow_origins=settings.cors_origin_list,allow_credentials=True,allow_methods=["*"],allow_headers=["*","X-CSRF-Token"])
@app.middleware("http")
async def auth_rate_limit(request:Request,call_next):
    bucket = _AUTH_RATE_LIMIT_PATHS.get(request.url.path)
    if request.method == "POST" and bucket:
        client_ip = request.client.host if request.client else "unknown"
        ip_digest = hmac.new(settings.jwt_secret.encode(), client_ip.encode(), "sha256").hexdigest()
        try:
            count = await run_in_threadpool(auth_rate_limiter.consume,
                f"medguard:auth-rate:{bucket}:{ip_digest}",
                settings.auth_rate_limit_window_seconds,
            )
        except Exception:
            logging.warning(json.dumps({"event":"auth.rate_limiter_unavailable","route":bucket},separators=(",",":")))
            return JSONResponse(status_code=503,headers={"Retry-After":"5"},content={"error":{"code":"auth_temporarily_unavailable","message":"Authentication is temporarily unavailable."}})
        if count > settings.auth_rate_limit_per_minute:
            return JSONResponse(status_code=429,headers={"Retry-After":str(settings.auth_rate_limit_window_seconds)},content={"error":{"code":"rate_limit_exceeded","message":"Too many authentication attempts. Try again later."}})
    return await call_next(request)
@app.middleware("http")
async def csrf_protection(request:Request,call_next):
    if request.method in {"POST","PUT","PATCH","DELETE"}:
        origin=request.headers.get("origin")
        if request.url.path.startswith(settings.api_v1_prefix+"/auth/web/"):
            allowed={v.rstrip("/") for v in settings.cors_origin_list}
            if not origin or origin.rstrip("/") not in allowed:return JSONResponse(status_code=403,content={"error":{"code":"csrf_origin_rejected","message":"Request origin is not allowed"}})
        if request.cookies.get("access_token"):
            cookie=request.cookies.get("csrf_token","");header=request.headers.get("x-csrf-token","")
            if not cookie or not header or not hmac.compare_digest(cookie,header):return JSONResponse(status_code=403,content={"error":{"code":"csrf_token_missing","message":"CSRF validation failed"}})
    return await call_next(request)
@app.exception_handler(HTTPException)
async def http_exception_handler(request:Request,exc:HTTPException):return JSONResponse(status_code=exc.status_code,headers=exc.headers,content={"error":{"code":"http_error","message":str(exc.detail)}})
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request:Request,exc:RequestValidationError):
    errors=[{"location":e.get("loc",[]),"code":e.get("type","invalid"),"message":e.get("msg","Invalid value")} for e in exc.errors()]
    return JSONResponse(status_code=422,content={"error":{"code":"validation_error","message":"Request validation failed.","details":errors}})
@app.exception_handler(Exception)
async def unhandled_exception_handler(request:Request,exc:Exception):
    route = request.scope.get("route")
    logging.error(json.dumps({
        "event": "api.unhandled_exception",
        "method": request.method,
        "route": getattr(route, "path", "unmatched"),
        "error_type": type(exc).__name__,
    }, separators=(",", ":")))
    return JSONResponse(status_code=500,content={"error":{"code":"internal_server_error","message":"An unexpected error occurred."}})
for router in (health_router,auth_router,caregivers_auth_router,patients_router,hospitals_router,doctors_router,timeline_router,consultations_router):app.include_router(router,prefix=settings.api_v1_prefix)
app.include_router(health_router)
