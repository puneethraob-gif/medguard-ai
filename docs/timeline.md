# Healthcare timeline

The patient timeline is a read-only, chronological projection of verified records owned by clinical modules. Timeline rows contain a concise title/description and a `(source_module, source_record_id)` reference. They must not duplicate a source record or contain full clinical notes, reports, prescriptions, or medical history.

## Event types

Supported event types are `consultation_scheduled`, `consultation_completed`, `summary_generated`, `summary_approved`, `prescription_uploaded`, `prescription_approved`, `medication_schedule_activated`, `prescription_updated`, `medication_course_completed`, `medication_started`, `medication_completed`, `medication_schedule_changed`, `refill_required`, `test_recommended`, `test_scheduled`, `test_completed`, `report_uploaded`, `report_reviewed`, `follow_up_scheduled`, `appointment_updated`, `appointment_completed`, and `appointment_cancelled`.

Source modules are `consultation`, `prescription`, `medicine`, `laboratory`, and `appointment`. The service validates that an event type belongs to the selected module. Status values are constrained in the database and service.

## Source-module integration

The owning module registers a patient-scoped source verifier using `register_source_verifier(module, verifier)` from `app.timeline.integrations`. Its verifier must confirm that the referenced record exists and belongs to the given patient. After persisting a real source record, the module calls `record_timeline_event(...)` from `app.timeline.service` in the same database transaction. The write service rejects missing/unverified sources, is idempotent for the same patient/type/module/source reference, and leaves commit/rollback to the caller. The unique database constraint also protects against duplicate delivery races.

Consultation, prescription, medicine, laboratory, and appointment source modules do not exist yet. No source verifiers are registered by the current application, no public event-creation endpoint exists, and no medical events are fabricated. These are explicit integration hooks for those modules.

## API

- `GET /api/v1/timeline`: chronological history, newest first. Supports repeated `event_type` and `status`, `date_from`, `date_to`, `page`, and `page_size` (maximum 100).
- `GET /api/v1/timeline/{event_id}`: detail for an event the caller may access.
- `GET /api/v1/timeline/upcoming`: upcoming nonterminal source records, oldest first, with the same filtering and pagination options.
- `GET /api/v1/timeline/summary`: current counts and deterministic `next_steps` derived from pending timeline records. It uses fixed backend text; no AI generates instructions.

Patients are scoped to their own records. Doctors need an active patient-doctor link. Hospital staff need an active patient-hospital/staff relationship. Caregivers need an active consent with the `timeline` scope; patients can grant/revoke it through existing consent endpoints. Unauthorized patient access returns 404 to avoid disclosing record existence. Timeline reads are written to `access_audit`.

The summary only treats the latest event for each source record as current. This prevents an older scheduled event from remaining in upcoming/next steps after the source module records completion or cancellation. The full timeline retains all events.

## Patient app

The Healthcare Timeline screen supports all/upcoming/completed/pending views, source categories, chronological event cards, expandable event details, and pagination. The home-page “Your Next Steps” card is populated only from `GET /timeline/summary`. Empty states are shown when there are no verified events.
