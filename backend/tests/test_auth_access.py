from cryptography.fernet import Fernet
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine,select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.core.config import settings
import app.main as main_module
from app.main import app
from app.db.models import Base,PatientProfile
from app.db.session import get_db

settings.jwt_secret="test-jwt-secret-with-at-least-32-bytes"
class _AllowAuthRateLimiter:
    def consume(self, key, window_seconds): return 1
main_module.auth_rate_limiter = _AllowAuthRateLimiter()
settings.patient_data_encryption_key=Fernet.generate_key().decode()
engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
TestingSession=sessionmaker(bind=engine,autoflush=False,autocommit=False)
Base.metadata.create_all(engine)
def override_db():
    db=TestingSession()
    try:yield db
    finally:db.close()
app.dependency_overrides[get_db]=override_db
client=TestClient(app)
@pytest.fixture(autouse=True)
def clean_db():
    with TestingSession() as db:
        for table in reversed(Base.metadata.sorted_tables):db.execute(table.delete())
        db.commit()
def register_patient(email="patient@example.test"):
    return client.post("/api/v1/auth/register/patient",json={"email":email,"name":"Test Patient","password":"a-very-long-password","role":"patient","medical_history":"ignored"})
def register_caregiver(email="care@example.test"):
    return client.post("/api/v1/auth/register/caregiver",json={"email":email,"name":"Care Partner","password":"a-very-long-password","role":"caregiver"})
def login(email,password="a-very-long-password"):
    return client.post("/api/v1/auth/login",json={"email":email,"password":password}).json()
def headers(access):return {"Authorization":f"Bearer {access}"}
def test_patient_registration_login_and_own_profile():
    response=register_patient();assert response.status_code==201
    tokens=login("patient@example.test");assert "refresh_token" in tokens
    profile=client.get("/api/v1/patients/me",headers=headers(tokens["access_token"]))
    assert profile.status_code==200 and profile.json()["name"]=="Test Patient"
def test_patient_cannot_read_another_patients_record():
    register_patient("one@example.test");register_patient("two@example.test")
    access=login("one@example.test")["access_token"]
    assert client.get("/api/v1/patients/2",headers=headers(access)).status_code==404
def test_unauthorized_and_invalid_login():
    assert client.get("/api/v1/patients/me").status_code==401
    register_patient()
    assert client.post("/api/v1/auth/login",json={"email":"patient@example.test","password":"incorrect-password"}).status_code==401
def test_access_token_expiration(monkeypatch):
    from app.core import security
    from datetime import datetime,timezone,timedelta
    register_patient();tokens=login("patient@example.test")
    session_id=login("patient@example.test")["access_token"]
    import jwt
    payload=jwt.decode(session_id,settings.jwt_secret,algorithms=["HS256"],options={"verify_exp":False})
    payload["exp"]=datetime.now(timezone.utc)-timedelta(seconds=1)
    expired=jwt.encode(payload,settings.jwt_secret,algorithm="HS256")
    assert client.get("/api/v1/auth/me",headers=headers(expired)).status_code==401
def test_refresh_rotation_reuse_revokes_family_and_logout_revokes_access():
    register_patient();first=login("patient@example.test");old=first["refresh_token"]
    rotated=client.post("/api/v1/auth/refresh",json={"refresh_token":old});assert rotated.status_code==200
    assert rotated.json()["refresh_token"]!=old
    reuse=client.post("/api/v1/auth/refresh",json={"refresh_token":old});assert reuse.status_code==401
    assert client.get("/api/v1/auth/me",headers=headers(rotated.json()["access_token"])).status_code==401
    fresh=login("patient@example.test")
    out=client.post("/api/v1/auth/logout",json={"refresh_token":fresh["refresh_token"]},headers=headers(fresh["access_token"]))
    assert out.status_code==204
    assert client.get("/api/v1/auth/me",headers=headers(fresh["access_token"])).status_code==401
def test_doctor_access_requires_patient_authorization():
    patient_id=register_patient("patient@example.test").json()["id"]
    doctor_id=client.post("/api/v1/auth/register/doctor",json={"email":"doctor@example.test","name":"Doctor","password":"a-very-long-password","license_number":"LIC-1"}).json()["id"]
    doctor=login("doctor@example.test")["access_token"]
    assert client.get(f"/api/v1/patients/{patient_id}",headers=headers(doctor)).status_code==404
    patient=login("patient@example.test")["access_token"]
    linked=client.post(f"/api/v1/hospitals/doctors/{doctor_id}/patients/{patient_id}",headers=headers(patient));assert linked.status_code==204
    assert client.get(f"/api/v1/patients/{patient_id}",headers=headers(doctor)).status_code==200
    assert client.get("/api/v1/doctors/me/patients",headers=headers(doctor)).json()[0]["id"]==patient_id
def test_caregiver_consent_scope_and_revocation():
    patient_id=register_patient().json()["id"];register_caregiver()
    patient=login("patient@example.test")["access_token"];caregiver=login("care@example.test")["access_token"]
    client.patch("/api/v1/patients/me",headers=headers(patient),json={"medical_history":"recorded history"})
    assert client.get(f"/api/v1/patients/{patient_id}",headers=headers(caregiver)).status_code==404
    profile=client.post("/api/v1/consents",headers=headers(patient),json={"caregiver_email":"care@example.test","scope":"profile"}).json()
    assert client.get(f"/api/v1/patients/{patient_id}",headers=headers(caregiver)).json()["medical_history"] is None
    history=client.post("/api/v1/consents",headers=headers(patient),json={"caregiver_email":"care@example.test","scope":"medical_history"}).json()
    assert client.get(f"/api/v1/patients/{patient_id}",headers=headers(caregiver)).json()["medical_history"]=="recorded history"
    client.delete(f"/api/v1/consents/{profile['id']}",headers=headers(patient))
    client.delete(f"/api/v1/consents/{history['id']}",headers=headers(patient))
    assert client.get(f"/api/v1/patients/{patient_id}",headers=headers(caregiver)).status_code==404
def test_patient_sensitive_fields_are_encrypted_at_rest():
    register_patient()
    with TestingSession() as db:
        raw=db.execute(select(PatientProfile.__table__.c.medical_history)).scalar_one_or_none()
        assert raw is None or raw!="Test Patient"
def test_web_session_uses_http_only_same_site_cookies_and_csrf():
    register_patient()
    response=client.post("/api/v1/auth/web/login",headers={"Origin":"http://localhost:5173"},json={"email":"patient@example.test","password":"a-very-long-password"})
    assert response.status_code==200
    cookies=response.headers.get_list("set-cookie")
    access=next(c for c in cookies if c.startswith("access_token="))
    assert "httponly" in access.lower() and "samesite=lax" in access.lower()
    assert client.get("/api/v1/auth/me").status_code==200
    bad=client.post("/api/v1/auth/web/logout",headers={"Origin":"http://localhost:5173","X-CSRF-Token":"wrong"})
    assert bad.status_code==403
    csrf=client.cookies.get("csrf_token")
    good=client.post("/api/v1/auth/web/logout",headers={"Origin":"http://localhost:5173","X-CSRF-Token":csrf})
    assert good.status_code==204
    assert client.get("/api/v1/auth/me").status_code==401

def test_web_login_rejects_untrusted_origin():
    response=client.post("/api/v1/auth/web/login",headers={"Origin":"https://evil.example"},json={"email":"nobody@example.test","password":"bad"})
    assert response.status_code==403

def _timeline_event(patient_id,event_type,status,event_date,source_record_id,source_module="appointment"):
    from app.timeline.service import record_timeline_event
    with TestingSession() as db:
        event,created=record_timeline_event(db,patient_id=patient_id,event_type=event_type,title=event_type.replace("_"," ").title(),event_date=event_date,source_module=source_module,source_record_id=source_record_id,status=status)
        db.commit()
        return event.id,created

def test_timeline_event_creation_verification_and_duplicate_prevention():
    from datetime import datetime,timezone,timedelta
    from app.timeline.integrations import clear_source_verifiers,register_source_verifier
    clear_source_verifiers()
    patient_id=register_patient().json()["id"]
    register_source_verifier("appointment",lambda _db,pid,rid:pid==patient_id and rid=="verified-appointment-1")
    event_id,created=_timeline_event(patient_id,"follow_up_scheduled","scheduled",datetime.now(timezone.utc)+timedelta(days=2),"verified-appointment-1")
    duplicate_id,duplicate_created=_timeline_event(patient_id,"follow_up_scheduled","scheduled",datetime.now(timezone.utc)+timedelta(days=2),"verified-appointment-1")
    assert created is True and duplicate_created is False and duplicate_id==event_id
    from app.timeline.service import UnverifiedTimelineSource,record_timeline_event
    with TestingSession() as db, pytest.raises(UnverifiedTimelineSource):
        record_timeline_event(db,patient_id=patient_id,event_type="appointment_completed",title="Completed",event_date=datetime.now(timezone.utc),source_module="appointment",source_record_id="not-verified",status="completed")

def test_timeline_retrieval_filters_chronology_upcoming_summary_and_next_steps():
    from datetime import datetime,timezone,timedelta
    from app.timeline.integrations import clear_source_verifiers,register_source_verifier
    clear_source_verifiers()
    patient_id=register_patient().json()["id"]
    register_source_verifier("appointment",lambda _db,pid,rid:pid==patient_id and rid.startswith("src-"))
    register_source_verifier("consultation",lambda _db,pid,rid:pid==patient_id and rid=="src-consultation")
    now=datetime.now(timezone.utc)
    from app.timeline.service import record_timeline_event
    with TestingSession() as db:
        record_timeline_event(db,patient_id=patient_id,event_type="consultation_completed",title="Consultation complete",event_date=now-timedelta(days=1),source_module="consultation",source_record_id="src-consultation",status="completed")
        db.commit()
    _timeline_event(patient_id,"follow_up_scheduled","scheduled",now+timedelta(days=2),"src-follow")
    _timeline_event(patient_id,"appointment_cancelled","cancelled",now+timedelta(days=1),"src-cancel")
    _timeline_event(patient_id,"follow_up_scheduled","scheduled",now+timedelta(days=3),"src-cancelled-follow-up")
    _timeline_event(patient_id,"appointment_cancelled","cancelled",now+timedelta(days=3),"src-cancelled-follow-up")
    token=login("patient@example.test")["access_token"]
    response=client.get("/api/v1/timeline?page=1&page_size=10",headers=headers(token));assert response.status_code==200
    body=response.json();assert body["total"]==5
    event_dates=[item["event_date"] for item in body["items"]]
    assert event_dates==sorted(event_dates,reverse=True)
    filtered=client.get("/api/v1/timeline?event_type=consultation_completed",headers=headers(token)).json()
    assert filtered["total"]==1 and filtered["items"][0]["event_type"]=="consultation_completed"
    ranged=client.get("/api/v1/timeline",params={"date_from":now.isoformat(),"date_to":(now+timedelta(days=1)).isoformat()},headers=headers(token)).json()
    assert ranged["total"]==1 and ranged["items"][0]["event_type"]=="appointment_cancelled"
    event_detail=client.get(f"/api/v1/timeline/{body['items'][0]['id']}",headers=headers(token))
    assert event_detail.status_code==200 and event_detail.json()["id"]==body["items"][0]["id"]
    upcoming=client.get("/api/v1/timeline/upcoming",headers=headers(token)).json()
    assert upcoming["total"]==1 and upcoming["items"][0]["event_type"]=="follow_up_scheduled"
    summary=client.get("/api/v1/timeline/summary",headers=headers(token)).json()
    assert summary["total_events"]==5 and summary["upcoming_count"]==1 and summary["completed_count"]==1
    assert summary["next_steps"][0]["action"]=="Attend your scheduled follow-up."

def test_timeline_patient_isolation_and_event_detail_permissions():
    from datetime import datetime,timezone
    from app.timeline.integrations import clear_source_verifiers,register_source_verifier
    clear_source_verifiers()
    patient_one=register_patient("one@example.test").json()["id"]
    patient_two=register_patient("two@example.test").json()["id"]
    register_source_verifier("appointment",lambda _db,pid,rid:rid==f"patient-{pid}")
    event_id,_=_timeline_event(patient_one,"appointment_completed","completed",datetime.now(timezone.utc),f"patient-{patient_one}")
    one=login("one@example.test")["access_token"];two=login("two@example.test")["access_token"]
    assert client.get("/api/v1/timeline",headers=headers(one)).json()["total"]==1
    assert client.get("/api/v1/timeline",headers=headers(two)).json()["total"]==0
    assert client.get(f"/api/v1/timeline/{event_id}",headers=headers(two)).status_code==404
    assert client.get("/api/v1/timeline").status_code==401

def test_timeline_doctor_and_caregiver_access_requires_current_authorization():
    from datetime import datetime,timezone,timedelta
    from app.timeline.integrations import clear_source_verifiers,register_source_verifier
    clear_source_verifiers()
    patient_id=register_patient().json()["id"]
    doctor_id=client.post("/api/v1/auth/register/doctor",json={"email":"timeline-doctor@example.test","name":"Doctor","password":"a-very-long-password","license_number":"TL-1"}).json()["id"]
    register_caregiver("timeline-caregiver@example.test")
    register_source_verifier("appointment",lambda _db,pid,rid:pid==patient_id and rid=="src-permission")
    _timeline_event(patient_id,"follow_up_scheduled","scheduled",datetime.now(timezone.utc)+timedelta(days=1),"src-permission")
    patient=login("patient@example.test")["access_token"]
    doctor=login("timeline-doctor@example.test")["access_token"]
    caregiver=login("timeline-caregiver@example.test")["access_token"]
    assert client.get(f"/api/v1/timeline?patient_id={patient_id}",headers=headers(doctor)).status_code==404
    assert client.get(f"/api/v1/timeline?patient_id={patient_id}",headers=headers(caregiver)).status_code==404
    assert client.post(f"/api/v1/hospitals/doctors/{doctor_id}/patients/{patient_id}",headers=headers(patient)).status_code==204
    assert client.get(f"/api/v1/timeline?patient_id={patient_id}",headers=headers(doctor)).json()["total"]==1
    consent=client.post("/api/v1/consents",headers=headers(patient),json={"caregiver_email":"timeline-caregiver@example.test","scope":"timeline"}).json()
    assert client.get(f"/api/v1/timeline?patient_id={patient_id}",headers=headers(caregiver)).json()["total"]==1
    assert client.delete(f"/api/v1/consents/{consent['id']}",headers=headers(patient)).status_code==204
    assert client.get(f"/api/v1/timeline?patient_id={patient_id}",headers=headers(caregiver)).status_code==404

def test_timeline_endpoints_are_published_in_openapi():
    paths=client.get("/openapi.json").json()["paths"]
    assert "/api/v1/timeline" in paths
    assert "/api/v1/timeline/upcoming" in paths
    assert "/api/v1/timeline/summary" in paths
    assert "/api/v1/timeline/{event_id}" in paths
    assert "TimelinePageResponse" in client.get("/openapi.json").json()["components"]["schemas"]

def test_timeline_hospital_staff_access_uses_patient_hospital_link():
    from datetime import datetime,timezone
    from app.timeline.integrations import clear_source_verifiers,register_source_verifier
    clear_source_verifiers()
    patient_id=register_patient().json()["id"]
    client.post("/api/v1/auth/register/doctor",json={"email":"hospital-doctor@example.test","name":"Hospital Doctor","password":"a-very-long-password","license_number":"HOSP-1"})
    doctor=login("hospital-doctor@example.test")["access_token"]
    patient=login("patient@example.test")["access_token"]
    hospital=client.post("/api/v1/hospitals",headers=headers(doctor),json={"name":"Linked Hospital","registration_number":"HOSP-REG-1"}).json()
    assert client.post(f"/api/v1/hospitals/{hospital['id']}/patients/{patient_id}",headers=headers(patient)).status_code==204
    staff=client.post(f"/api/v1/hospitals/{hospital['id']}/staff",headers=headers(doctor),params={"email":"staff@example.test","name":"Staff Member","password":"a-very-long-password"})
    assert staff.status_code==201
    register_source_verifier("appointment",lambda _db,pid,rid:pid==patient_id and rid=="hospital-event")
    from datetime import timedelta
    _timeline_event(patient_id,"follow_up_scheduled","scheduled",datetime.now(timezone.utc)+timedelta(days=1),"hospital-event")
    staff_token=login("staff@example.test")["access_token"]
    assert client.get(f"/api/v1/timeline?patient_id={patient_id}",headers=headers(staff_token)).json()["total"]==1

