# Personal Healthcare Companion monorepo

A modular patient and doctor application with authentication, patient management, Healthcare Timeline, and a consent-gated consultation transcription and doctor-approved summary workflow. Prescription processing and autonomous AI medical advice are not implemented.

## Repository layout

- `apps/patient-mobile`: Expo + React Native + TypeScript
- `apps/doctor-dashboard`: React + TypeScript + Tailwind CSS + Vite
- `backend`: FastAPI, SQLAlchemy, Alembic, Celery
- `database`: PostgreSQL/pgvector initialization
- `ai-services`, `integrations`: isolated extension points
- `shared`: cross-app types and constants
- `docs`: setup and architecture notes

## Local setup (Docker; recommended)

1. Install Docker Desktop, Node.js 20+, and npm.
2. Copy `.env.example` to `.env` and set nonempty `POSTGRES_PASSWORD`, `JWT_SECRET`, `PATIENT_DATA_ENCRYPTION_KEY`, and `CONSULTATION_AUDIO_ENCRYPTION_KEY` values. Secret examples are blank; Compose refuses to start without the database password. `.env` is ignored by Git.
3. Start everything: `docker compose up --build`.
4. Open dashboard at http://localhost:5173. It calls `GET http://localhost:8000/api/v1/health` and displays API status.
5. API docs: http://localhost:8000/docs (OpenAPI JSON: http://localhost:8000/openapi.json). Liveness: `/health`; readiness including database: `/api/v1/health/ready`.
6. Stop with `docker compose down`; add `-v` only when you intend to remove the local database volume.

The database image includes pgvector and the initialization script enables the `vector` extension. SQLAlchemy connection settings are read from `DATABASE_URL`; migrations live in `backend/alembic`. Run migrations in the API container with `docker compose exec api alembic upgrade head`.

## Patient mobile app

Install frontend dependencies from the repository root with `npm run install:all`, then run `npm run dev:mobile`. The two applications are installed independently and keep their own lockfiles; npm workspaces are intentionally not used because this Windows environment cannot create the workspace symlinks required by npm. Set `EXPO_PUBLIC_API_BASE_URL` in `.env` or the shell to a URL reachable from the device. Android emulator: use `http://10.0.2.2:8000/api/v1`; iOS simulator: `http://localhost:8000/api/v1`; physical device: use the host computer's LAN IP. Create `apps/patient-mobile/.env` from its `.env.example`, or set the variable in your shell. The app includes a connection check button.

## Local development without Docker

- Backend (Windows PowerShell): `cd backend`; `py -3.12 -m venv .venv`; `.\.venv\Scripts\Activate.ps1`; `python -m pip install --upgrade pip`; `python -m pip install -r requirements.txt`; `Copy-Item ..\.env.example ..\.env` and configure `DATABASE_URL`, `REDIS_URL`, and `JWT_SECRET`; run `alembic upgrade head`; start with `uvicorn app.main:app --reload`. Python is pinned to 3.12 in `backend/.python-version` and constrained to `>=3.12,<3.13` in `backend/pyproject.toml`.
- Dashboard: `npm run install:all` from the repository root, then `npm run dev:web` (Vite uses `VITE_API_BASE_URL`, default `http://localhost:8000/api/v1`).
- Mobile: `npm run dev:mobile`.

## Verification

Frontend setup and checks (PowerShell, from the repository root): run `npm run install:all`; then `npm run test:web`, `npm run build:web`, and `npm run test:mobile`. The apps install independently and maintain separate lockfiles; npm workspaces are not used because this Windows environment cannot create the workspace symlinks npm requires. Check patient TypeScript with `npx tsc --noEmit -p apps/patient-mobile/tsconfig.json`. To export the Expo web build when the user profile is not writable, keep Expo state in `work/`:

```powershell
New-Item -ItemType Directory -Force .\work\expo-home | Out-Null
$env:__UNSAFE_EXPO_HOME_DIRECTORY = (Resolve-Path .\work\expo-home).Path
$env:EXPO_NO_TELEMETRY = '1'
npx --prefix apps/patient-mobile expo export --platform web
```

The patient app uses Expo SDK 52, React Native 0.76.9, and React 18.3.1.

Backend tests (PowerShell): `Set-Location backend`; activate `.venv` if needed with `.\.venv\Scripts\Activate.ps1`; run `$env:PYTHONPATH='.'; python -m pytest -q`. Create the venv with `py -3.12 -m venv .venv` first. Requirements are pinned in `backend/requirements.txt`, including SQLAlchemy 2.0.48 and Sarvam SDK 0.1.41. The consultation suite uses synthetic audio and fake providers; it never transmits test data to external services. Dashboard: `npm run test:web` and `npm run build:web`. See [docs/consultations.md](docs/consultations.md) for feature-specific API, provider and security details. Docker Compose is the integrated local stack.

## Configuration and security

See [docs/consultations.md](docs/consultations.md) for the consultation workflow, API, selected speech/LLM providers, privacy controls, migration and limitations.

Never commit `.env`, credentials, or API keys. CORS origins are configured with `CORS_ORIGINS` as a comma-separated list. Add explicit production origins before deployment; do not use wildcards with credentials. Errors use a consistent JSON envelope; unexpected errors are logged server-side and return a generic message.


## Accounts and patient access

Patient and doctor registration, shared login, role-bearing short-lived JWTs, patient profile updates, caregiver consent grants/revocation, hospital registration and staff management, patient-to-doctor authorization, and access audit events are included. Patient IDs are hidden from unauthorized callers (404). Caregiver access is consent-bound and scope-filtered. JWT_SECRET must be replaced with a strong random value outside local development. See /docs for endpoints. Mobile tokens are stored in Expo SecureStore. The web dashboard uses HTTP-only cookies and CSRF protection. Production must set SECURE_COOKIES=true behind HTTPS.




## Patient data and authentication keys

Authentication uses 15-minute signed access tokens and rotating, server-tracked refresh sessions. Refresh-token reuse revokes the session family; logout revokes the current session, which invalidates its access token. Patient contact, emergency contact, medical history, and allergy fields use Fernet authenticated encryption through SQLAlchemy. Set `JWT_SECRET` and `PATIENT_DATA_ENCRYPTION_KEY` in the ignored root `.env` before running the API or migrations. Generate these values in a secrets manager or secure local secret-generation workflow that writes directly to protected configuration; do not print them to a terminal.

Keep encryption keys in a deployment secret manager or protected environment configuration, back them up separately, and maintain a key-rotation plan. Never commit `.env`. Migration `0003_auth_sessions_and_patient_encryption` encrypts existing patient fields and intentionally refuses to run without `PATIENT_DATA_ENCRYPTION_KEY`; downgrade is unsupported because it would restore plaintext data.

Patient-management endpoints include `GET/PATCH /api/v1/patients/me`, `GET /api/v1/patients/{id}` (self, linked doctor, hospital staff relationship, or scoped caregiver consent), `POST /api/v1/consents`, and `DELETE /api/v1/consents/{id}`. Doctor profile and authorized-patient endpoints are under `/api/v1/doctors/me`.

Healthcare Timeline API endpoints are `GET /api/v1/timeline`, `GET /api/v1/timeline/{event_id}`, `GET /api/v1/timeline/upcoming`, and `GET /api/v1/timeline/summary`. Apply database revision `0004_healthcare_timeline` with `alembic upgrade head`. Source-module event creation requirements and schema details are documented in [docs/timeline.md](docs/timeline.md) and [docs/database.md](docs/database.md). Clinical source modules are not present yet, so the timeline remains empty until verified source integrations are registered.
## Session protection details

- Mobile: Expo stores both short-lived access and rotating refresh tokens in `expo-secure-store`; it refreshes on an authenticated request after an access-token 401 and clears stored tokens on logout or refresh failure.
- Browser: dashboard authentication uses `HttpOnly`, `SameSite=Lax` cookies. Set `SECURE_COOKIES=true` behind HTTPS in production. Unsafe browser requests require an allowed `Origin` for web auth and a matching CSRF cookie/header for cookie-authenticated writes. The web client does not write auth tokens to local storage.
- API clients may also use the bearer-token `/auth/login`, `/auth/refresh`, and `/auth/logout` endpoints.
- Refresh values are stored server-side only as SHA-256 hashes. Refresh reuse revokes the complete session family; a revoked session invalidates its access tokens too.
- Login, refresh, and registration routes use a Redis-backed per-IP fixed-window limit (`AUTH_RATE_LIMIT_PER_MINUTE`, `AUTH_RATE_LIMIT_WINDOW_SECONDS`). Authentication fails closed with HTTP 503 if Redis is unavailable. Configure Redis with network restrictions and authentication for deployed environments.
- Credentialed CORS rejects `*`; configure explicit trusted browser origins.
- Field encryption uses Fernet with the external `PATIENT_DATA_ENCRYPTION_KEY`. Back up/manage that key outside the repository; rotation is currently an operator-managed migration task, not automated.


Before starting locally, copy the root `.env.example` to `.env`, then populate `JWT_SECRET` and `PATIENT_DATA_ENCRYPTION_KEY` using the generation commands above. For production HTTPS, set `SECURE_COOKIES=true`. Mobile client storage uses `expo-secure-store`; install frontend dependencies with `npm run install:all` before launching the Expo app or dashboard.
