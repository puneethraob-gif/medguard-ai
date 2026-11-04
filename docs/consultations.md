# AI Consultation Assistant

This feature adds a consent-gated consultation workflow. It does not process prescriptions or create medicines, tests, or follow-up records. An LLM summary is a draft until an assigned doctor reviews and approves it. The patient API returns only the latest approved summary; an original transcript is additionally shared only when the doctor explicitly enables transcript access.

## Workflow and safeguards

1. An assigned doctor creates a consultation for an authorized patient.
2. The patient opens a localized consent notice (`recording-consent-v2`) in their preferred language. It explains encrypted audio storage, transcript and AI draft processing by Sarvam, doctor review, refusal/withdrawal, and the fact that an already-submitted external request cannot be recalled. The API only accepts the version/language it served, and records actor, time, and language. Recording cannot start without the latest decision being affirmative and unrevoked.
3. The doctor dashboard captures audio with the browser microphone, streams it to the API, and uploads audio only after recording stops. The API enforces type and byte limits, computes SHA-256, stores metadata, and writes Fernet-encrypted audio to a private directory/volume.
4. A doctor explicitly queues transcription. A Celery worker submits consented audio to the configured speech provider. The Sarvam adapter uses Saaras v4 Batch (audio file upload, `mode=codemix`, `language_code=unknown`, diarization and timestamps); uploaded audio has no patient-derived filename. Transcript segments are encrypted in PostgreSQL, preserve detected language, phrase timestamps, and diarization speaker IDs. IDs are not automatically treated as doctor/patient: a doctor labels them in the review screen before summary generation when attribution is reliable.
5. A doctor explicitly queues a summary. The LLM receives only the transcript segments, language/speaker metadata, and source segment IDs. It does not receive the patient profile or unrelated medical history. Structured output is validated; every non-empty fact must reference transcript segments that exist in this consultation. Unsupported/invalid output is not saved for approval.
6. The doctor can edit the JSON, inspect each source segment, correct diarized speaker identities, and approve. Corrections and approvals are recorded in immutable approval-history rows. Repeated timeline writes are idempotent.

The summary keys are `chief_complaints`, `symptoms`, `medical_history`, `doctor_observations`, `medicines_discussed`, `tests_recommended`, `dietary_instructions`, `dos_and_donts`, `follow_up_recommendations`, and `warnings`. A fact carries `text`, optional `duration`, `statement_type`, source segment IDs, and API-enriched timestamp references. `statement_type` is `doctor_statement`, `patient_statement`, or `ai_interpretation`. An unlabelled speaker must not be asserted as a doctor or patient by the model. Missing information is represented by empty arrays.

## Speech provider evaluation and selection

No vendor publishes an independently audited, comparable clinical word-error benchmark across Indian languages, accent groups, mixed-language speech, and medical terms. Published language coverage is not evidence of clinical accuracy. Before real clinical use, measure word/character error rate and medication/dose/negation capture on a representative, consented, de-identified evaluation set, with clinician adjudication. Synthetic tests in this repository verify the pipeline only, not recognition quality.

| Provider | Indian language/mixed speech coverage | Timestamp/speaker limitations | Pricing and privacy considerations |
| --- | --- | --- | --- |
| **Sarvam Saaras v4 — selected first adapter** | Provider documentation lists 22 Indic languages plus Indian/Global English, automatic language detection, code-mix output, and keyterm prompting. This best matches the requested breadth and Hindi/English code mixing. | Long-form batch supports diarization and phrase/chunk timestamps (not word timestamps). Speaker IDs still need human role confirmation. No clinical accuracy guarantee is published. | Public self-serve rate shown as ₹0.49/min for STT and ₹0.59/min with diarization (prices may change; GST excluded). The Sarvam 105B model's public rates are ₹15/M input and ₹60/M output tokens. Workspace owners configure retention and model-training settings; these must be reviewed before enabling patient audio. |
| Google Cloud Speech-to-Text V2 | Broad language/model matrix; language and feature support varies by model/region. Alternative-language detection is constrained to global/us/eu multi-regions and works best with fewer candidates. | Diarization, confidence and adaptation depend on locale/model. | Pay-as-you-go price depends on model/region/volume. Google documents in-memory processing for synchronous/streaming and temporary transcript storage for asynchronous jobs; processing is not pinned to an India-only region in the cited service FAQ. |
| Amazon Transcribe | Supports several Indian locales (including Hindi, Tamil, Telugu, Marathi, Kannada, Malayalam, Gujarati, Punjabi and Odia) but per-locale features differ. Multi-language identification supports only a subset; AWS warns non-dominant languages can be misrecognized. | Feature availability differs by locale and AWS region; verify the current language matrix before deployment. | Price depends on AWS region and batch/streaming mode. Retention, region, encryption and account settings are operator responsibilities. |
| Azure AI Speech | Supports multiple Indian locales; its official feature matrix has locale-by-locale support differences. | Language identification and diarization require appropriate candidate locale and feature configuration; not every feature exists for every locale. | Price depends on region and feature tier. Processing geography and abuse-monitoring controls depend on the deployment offering and configuration. |

Sarvam is therefore the default adapter here, not a claim that it is the most accurate for every dialect or clinical term. Its SDK is pinned as `sarvamai==0.1.41` and the provider is replaceable behind `SpeechRecognitionProvider`. `STT_PROVIDER=disabled` is the default; `STT_PROVIDER=sarvam` enables the adapter after credentials and retention controls are configured. The Saaras adapter uses batch mode for long consultations, diarization and chunk-level timestamps. `STT_MODE=codemix` preserves code-mixed output; `STT_KEYTERMS` can contain an operator-vetted, generic medical vocabulary (never patient-specific names/diagnoses). The language detector output is preserved as returned; there is no automatic translation.

## LLM, audio and text-to-speech providers

`SummaryProvider` is a replaceable interface. The first implementation uses Sarvam Chat Completions (`sarvam-105b`) only when `LLM_PROVIDER=sarvam`; the default is disabled. It is instructed to avoid unsupported facts and must return the validated JSON schema. The assigned doctor remains the clinical approval authority. This is not a diagnostic system and does not issue independent recommendations. Text-to-speech uses Expo's device `expo-speech`; it does not send the approved summary to an external speech service.

The speech and LLM keys use separate environment variables. `SARVAM_API_KEY` is the preferred STT setting; the existing `STT_API_KEY` name remains a compatible fallback. Keep both provider keys in a deployment secrets manager; the local `backend/.env` is ignored by Git. The included local audio store encrypts file bytes with Fernet using a separate key. PostgreSQL transcript and summary text reuse the existing encrypted text type. Local audio is deleted immediately on consent withdrawal and by a daily Celery Beat task after `CONSULTATION_AUDIO_RETENTION_DAYS` (default 30 days), except while a transcription task actively holds a processing claim; the next scheduled cleanup removes it after that claim clears. Recording metadata and deletion timestamps are retained. Transcript and summary records remain in the medical record and have no automatic expiry in this phase. The external provider may retain its own submitted copy according to workspace/account settings; local deletion cannot erase that copy or recall an in-flight request. A production deployment must replace the local volume and environment-held Fernet key with private object storage, KMS/HSM-managed envelope encryption, access logging, backup/retention policies, and tested key rotation. Do not expose the audio volume through a static-file server.

For a single non-patient API smoke request, put a newly rotated key in `backend/.env` as `SARVAM_API_KEY=...` (never commit or print it), set `STT_PROVIDER=sarvam`, and run from `backend`:

```powershell
Add-Type -AssemblyName System.Speech
$sample = Join-Path (Get-Location) 'var\speech-test.wav'
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SetOutputToWaveFile($sample)
$synth.Speak('This is synthetic speech for transcription.')
$synth.Dispose()
.\.venv\Scripts\python.exe scripts\sarvam_smoke_test.py --audio var\speech-test.wav
```

The smoke script calls `SarvamSpeechProvider`, the same Saaras v4 adapter used by the consultation worker. It reports sanitized authentication, quota, invalid-request/audio, timeout, and provider failures. The consultation evaluation commands and measured synthetic results are in `backend/scripts/consultation_eval/README.md`.

Set `CONSULTATION_AUDIO_ENCRYPTION_KEY`, `PATIENT_DATA_ENCRYPTION_KEY`, `JWT_SECRET`, database credentials, and provider keys through protected local configuration or a deployment secrets manager. Do not print generated secrets or store them in source control. `SARVAM_API_KEY` is preferred for STT; `STT_API_KEY` remains a compatibility alias.

## API

All endpoints are under `/api/v1`; bearer token or the dashboard's existing HTTP-only cookie session is required unless specified. OpenAPI is available from FastAPI at `/docs` and `/openapi.json`.

| Method and path | Purpose/access |
| --- | --- |
| `POST /consultations` | Assigned doctor creates a consultation; creates `consultation_scheduled` timeline event. |
| `GET /consultations` | Patient's own history, assigned doctor's consultations, or caregiver with active `consultations` consent. |
| `GET /consultations/{id}` | Detail; patient/caregiver receive only approved summary. |
| `GET /consultations/{id}/consent-info` | Patient only; returns the versioned notice in preferred language (currently ten languages), the configured audio retention window, and indicates English fallback. Agreement is rejected when a localized notice is unavailable. |
| `POST /consultations/{id}/consent` | Patient records yes/no consent before recording. |
| `DELETE /consultations/{id}/consent` | Patient revokes consent; removes stored audio and blocks later jobs. In-flight external requests cannot be recalled. |
| `POST /consultations/{id}/recording/start` | Assigned doctor starts after active consent. |
| `PUT /consultations/{id}/recording` | Assigned doctor uploads raw audio bytes; `Content-Type` must be an allowed audio type. `X-Audio-Filename` is ignored for storage naming. |
| `POST /consultations/{id}/recording/stop` | Completes the recording and writes `consultation_completed`. |
| `GET /consultations/{id}/recording` | Assigned doctor only, active consent required; returns `no-store` audio bytes. |
| `POST /consultations/{id}/transcribe` | Assigned doctor queues a Celery transcription task. |
| `GET /consultations/{id}/transcript` | Assigned doctor; patient only after approval + transcript sharing; caregiver requires both `consultations` and `consultation_transcript` grants. |
| `PATCH /consultations/{id}/speaker-roles` | Assigned doctor maps diarization IDs to doctor/patient/other. |
| `POST /consultations/{id}/summarize` | Assigned doctor queues a summary draft after transcript exists. |
| `PUT /consultations/{id}/summary` | Assigned doctor corrects a draft; all facts must cite valid segment IDs. |
| `POST /consultations/{id}/approve` | Assigned doctor approves and chooses whether to share transcript. Writes `summary_approved`. |

All reads and sensitive actions create `access_audit` entries. Unauthorized consultation IDs return 404. Caregiver grants are checked on each request so revocation takes effect immediately.

## Database and migration

Migration `0005_consultations` adds consultation, consent, recording, transcript, summary and approval tables. Migration `0006_consultation_recovery` persists Sarvam job IDs and bounded task-claim/attempt fields so a retry resumes the same batch job. Audio bytes are not stored in PostgreSQL. Timeline rows use source module `consultation` and the consultation ID; event rows contain no transcript or summary content.

Run from the repository root after `.env` is configured:

```powershell
docker compose up -d db redis
Set-Location backend
..\.venv\Scripts\python.exe -m alembic upgrade head
```

Backend tests (synthetic WAV and fake local provider adapters; no real recordings or provider network calls):

```powershell
Set-Location backend
$env:PYTHONPATH = "."
.\.venv\Scripts\python.exe -m pytest -q
```

Frontend checks:

```powershell
Set-Location apps\patient-mobile
npm test -- --runInBand
npx tsc --noEmit -p tsconfig.json
npx expo export --platform web

Set-Location ..\doctor-dashboard
npm test
npm run build
```

## Limitations before real patient use

- No independent clinical accuracy evaluation has been performed; synthetic tests do not validate ASR or clinical summarization quality.
- Provider credentials are not configured. Both providers default to disabled, so background tasks report provider-unavailable until configured.
- Current public Sarvam pricing lists pay-as-you-go STT at ₹0.49/minute and diarized batch STT at ₹0.59/minute (billed per second, before GST; plan rates differ). Sarvam-105B is listed at ₹15/1M input tokens and ₹60/1M output tokens. Batch has a documented 20 job-requests/minute pay-as-you-go rate limit. The synthetic audio generator uses Bulbul v3 to cover Malayalam, currently ₹3/1,000 characters at pay-as-you-go. Rates/limits can change; inspect the [official pricing and limits](https://docs.sarvam.ai/api/getting-started/pricing) before running evaluations at scale.
- `backend/scripts/consultation_eval/` contains fictional reference utterances plus TTS/STT evaluation scripts. An eight-clip live synthetic Saaras v4 evaluation was run on 2026-11-04; per-case WER/CER, language match, exact medical-term match, speaker count and clip-boundary timestamp offsets are in ignored `backend/scripts/consultation_eval/audio/results.json`. These synthetic results are not clinical accuracy evidence. The actual Saaras transcript was also saved through the consultation worker into a disposable SQLite database; doctor review/approval used a source-linked synthetic summary provider because no live LLM key was configured. No real LLM summary quality result is available.
- Provider data retention/training controls, regional processing, contractual terms, and applicable consent/privacy requirements need deployment-specific review. Audio and transcript are sensitive health information; enabling a cloud provider transmits them after consent.
- No automated PII redaction is performed. The transcript itself can include names, phone numbers, and other sensitive information.
- Local audio encryption uses an environment-held symmetric key and local filesystem storage. This is for development; it is not production key management, object-store lifecycle management, or disaster recovery.
- Consent notices are provided in English, Hindi, Telugu, Tamil, Kannada, Malayalam, Bengali, Marathi, Gujarati and Punjabi and are served based on patient preferred language. Unsupported profile languages currently fall back to English and must not be treated as localized consent. These translations require qualified local clinical/legal review before production; the server records version/language and actor/time, not a signed legal form.
- No provider webhook status callback or cancellation is implemented; jobs are polled synchronously in the worker SDK call. Once a provider has received an audio or transcript request, revocation cannot recall that in-flight request.
- The Sarvam batch SDK requires a temporary local working file for its upload interface. It is placed inside the private audio directory and removed after each call; worker temp storage must be access-restricted and encrypted at rest, with crash cleanup monitored.
- Requests use finite HTTP timeouts; job creation disables SDK retries to avoid duplicate external jobs. Read/poll calls use the SDK's bounded retry behavior. Queue claim locking prevents duplicate Celery deliveries from creating parallel jobs. A persisted job ID is reused on retry. When submission fails before a job ID is durably recorded, the outcome is treated as ambiguous and resubmission is blocked; an administrator must reconcile the provider job. Sarvam does not provide a cancellation API in this integration.
- A transcription that remains claimed beyond its maximum batch timeout can be requeued only when its provider job ID is known; the retry limit is three. Unknown jobs are not automatically submitted again. Queue failures before worker claim can be retried without a provider submission.
- Transcript role assignment is doctor-reviewed but not itself clinical adjudication. Models may omit or misstate events. The approved summary remains a human-reviewed record and should be compared to source audio when needed.
- Medical history is extracted only when it appears in the consultation transcript; no profile history is added to external prompts, minimizing data sent but potentially omitting relevant prior history.
- Recording start/stop is controlled by the dashboard's browser microphone; local-browser microphone capture is supported on secure contexts such as localhost/HTTPS.
