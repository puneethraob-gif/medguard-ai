# Architecture

```text
Patient Expo app ─┐
Doctor React app ──┼─ HTTP/JSON ─> FastAPI ─> SQLAlchemy ─> PostgreSQL + pgvector
                  │                 └─ Celery ─> Redis
                  └─ shared contracts/constants
```

The API owns configuration, routing, request validation, persistence, and error mapping. Database schema changes are managed by Alembic. Background tasks are registered under `app.workers`.

The consultation domain lives under `backend/app/consultations` and uses the existing patient-doctor authorization, encrypted text type, audit model, and timeline writer. Celery tasks own asynchronous transcription and summary generation. Provider clients implement separate protocols; external inference is disabled unless configured. Patient and caregiver reads are restricted to doctor-approved summary content.
