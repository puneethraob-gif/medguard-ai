# Local configuration

| Variable | Purpose | Default |
| --- | --- | --- |
| `DATABASE_URL` | SQLAlchemy PostgreSQL connection | Required for local backend runs; blank in examples |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Compose database initialization | Nonsecret local identifiers; password required and blank in examples |
| `REDIS_URL` | Celery broker/result backend | `redis://localhost:6379/0` |
| `CORS_ORIGINS` | Comma-separated browser origins | local Vite and Expo web origins |
| `VITE_API_BASE_URL` | Dashboard API prefix | `http://localhost:8000/api/v1` |
| `EXPO_PUBLIC_API_BASE_URL` | Patient app API prefix | `http://localhost:8000/api/v1` |

Values prefixed `EXPO_PUBLIC_` are bundled into the client and must not contain secrets.

The root and backend `.env.example` files leave credentials, encryption keys, and provider API keys empty. Fill them in a protected local `.env` or a deployment secrets manager; `.env` files are ignored by Git. Production PostgreSQL connections must use certificate-verified TLS (for example, `sslmode=verify-full`) and managed credentials.
