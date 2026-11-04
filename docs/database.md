# Database schema notes

PostgreSQL is the system of record. SQLAlchemy models are in `backend/app/db/models.py`; Alembic revisions are in `backend/alembic/versions`.

## Healthcare timeline

Revision `0004_healthcare_timeline` creates `timeline_events` after `0003_auth_sessions_and_patient_encryption`.

| Column | Purpose |
| --- | --- |
| `id` | Event primary key |
| `patient_id` | Foreign key to `patient_profiles.user_id`, cascade deleted |
| `event_type` | Constrained timeline event kind |
| `title`, `description` | Concise patient-facing event text; description is limited to 500 characters |
| `event_date` | Timezone-aware date/time of the source activity |
| `source_module`, `source_record_id` | Reference to the owning module's source record; not a copy of it |
| `status` | Constrained source-record state |
| `metadata` | Small JSON object for nonclinical display/reference details; limited by the service to 2 KiB |
| `created_at`, `updated_at` | Audit timestamps |

Constraints include supported event type/status/module checks and a unique `(patient_id, event_type, source_module, source_record_id)` key for idempotency. Indexes support per-patient chronology, event-type filtering, and status filtering. See [timeline integration details](timeline.md).

## Migration commands

## Consultations (`0005_consultations`, `0006_consultation_recovery`)

- `consultations`: patient/authorized-doctor association, creator, schedule, status and lifecycle timestamps.
- `consultation_consents`: append-only yes/no recording decisions with actor, consent version/language, and timestamps.
- `consultation_recordings`: private encrypted-audio storage reference, type, size, digest, Sarvam batch job ID, bounded attempt/claim state and upload time. Bytes stay outside PostgreSQL.
- `consultation_transcript_segments`: sequence, encrypted text, original language, offsets, diarization ID, doctor-confirmed role and provider metadata.
- `consultation_summaries`: encrypted structured JSON with review status and version.
- `consultation_approvals`: append-only doctor correction/approval history.

Patient/doctor foreign keys plus status and consultation/date indexes support scoped listing. Audio bytes are deleted on consent withdrawal and by daily Celery Beat after `CONSULTATION_AUDIO_RETENTION_DAYS` (default 30), with an `audio_deleted_at` marker; transcript and approved summary rows remain. Retention should be reviewed against applicable medical-record retention requirements before deployment.

From `backend` with the Python 3.12 virtual environment active:

```powershell
alembic upgrade head
alembic current
```

The `0002_accounts_and_access` revision excludes tables introduced by later migrations from its metadata-driven `create_all`; dedicated `0004`, `0005`, and `0006` revisions create timeline and consultation tables and add recovery fields on fresh databases and databases already at earlier revisions.
