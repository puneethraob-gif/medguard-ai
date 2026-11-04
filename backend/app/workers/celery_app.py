from celery import Celery
from celery.schedules import crontab
from app.core.config import settings

celery_app = Celery("healthcare_companion", broker=settings.redis_url, backend=settings.redis_url,
    include=["app.consultations.tasks"])
celery_app.conf.update(task_serializer="json", accept_content=["json"], result_serializer="json", timezone="UTC", enable_utc=True)
celery_app.conf.beat_schedule = {
    "delete-expired-consultation-audio-daily": {
        "task": "consultations.delete_expired_audio",
        "schedule": crontab(hour=2, minute=0),
    }
}
