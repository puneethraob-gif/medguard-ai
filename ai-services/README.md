# AI services

Consultation speech and summary adapters currently live at `backend/app/consultations/providers.py` so they share domain schemas and the Celery workflow. They implement replaceable `SpeechRecognitionProvider` and `SummaryProvider` protocols. Provider credentials are loaded from environment variables; tests make no provider calls. This directory remains the place for later cross-domain orchestration, prompt/version registries, evaluation datasets, and provider quality measurements. Do not add real patient audio or transcripts to evaluation fixtures.
