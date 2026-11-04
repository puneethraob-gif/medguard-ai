# External integrations

External service clients are isolated behind backend service interfaces. The first consultation ASR/LLM adapter uses the Sarvam SDK behind `backend/app/consultations/providers.py`; configuration is opt-in and credentials must come from environment variables or a secrets manager. Do not commit keys or use real patient recordings in development tests.
