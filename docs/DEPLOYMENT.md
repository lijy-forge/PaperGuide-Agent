# PaperGuide Deployment

## Supported deployment profile

PaperGuide v1 targets a trusted single-machine environment. Docker Compose runs three processes while preserving a single Active Host execution model.

The API and Host images install the Debian `fonts-noto-cjk` system package.
The Survey PDF renderer uses PyMuPDF's built-in CJK face for Chinese runs and
Helvetica for Latin runs, so font binaries are not committed to the repository.

```mermaid
flowchart LR
    Browser["Browser :80"] --> Nginx["Dashboard / Nginx"]
    Nginx -->|/api and /health| API["FastAPI :8000"]
    API --> DB[("SQLite Runtime")]
    Host["Task Host"] --> DB
    Host --> Artifacts["Artifact directory"]
    API --> Artifacts
    DB --- Volume["paperguide-data"]
    Artifacts --- Volume
```

## Docker Compose quick start

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Access the Dashboard at [http://localhost](http://localhost). API port 8000 is bound to loopback by default.

For an offline demonstration, set this in `.env` before startup:

```env
PAPERGUIDE_MODE=demo
```

For production research, leave `PAPERGUIDE_MODE=production`, select the Provider and inject its standard credential variable at runtime.

## Service responsibilities

| Service | Process | Responsibility |
| --- | --- | --- |
| `dashboard` | Nginx serving a Vite build | SPA, `/api/` reverse proxy and history fallback |
| `api` | Uvicorn/FastAPI | Public validation, safe task/status/event/artifact endpoints |
| `host` | `paperguide server start` | Task claims, execution, recovery, Graph and Artifact generation |

The API never constructs the Graph or starts Workers. The Host is the only process that owns execution dependencies.

## Persistent volume

The named Volume `paperguide-data` is mounted at `/app/data` by API and Host.

```text
/app/data/
├── runtime.db
├── paperguide-runtime.sqlite3 -> runtime.db
├── artifacts/
├── logs/
└── paperguide-downloads/
```

Removing containers does not remove the named Volume. Running `docker compose down --volumes` does remove it and should be treated as a destructive operation.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `PAPERGUIDE_MODE` | `production` | Select production or offline demo composition |
| `PAPERGUIDE_LLM_PROVIDER` | `openai` | Non-secret Provider selector |
| `PAPERGUIDE_MODEL_NAME` | `gpt-5.4` | Structured model name |
| `PAPERGUIDE_EXPORT_DIRECTORY` | `/app/data/artifacts` in containers | Artifact root shared by Host and API |
| `PAPERGUIDE_MAX_PAPERS` | `10` | Default research limit |
| `PAPERGUIDE_LOG_LEVEL` | `INFO` | Standard logging threshold |
| `PAPERGUIDE_API_PORT` | `8000` | Host-side API port |
| `PAPERGUIDE_DASHBOARD_PORT` | `80` | Host-side Dashboard port |
| `VITE_PAPERGUIDE_API_BASE_URL` | `http://localhost` | Public build-time API origin |

`RuntimeSettings` intentionally rejects secret-like `PAPERGUIDE_*` names. Provider credentials must use the Provider's standard runtime environment variables. Never bake credentials into an image, Vite variable, Compose file or README.

## Health checks

- Dashboard: `GET /healthz` on Nginx.
- API liveness: `GET /health/live`.
- API readiness: `GET /health/ready`.
- Host: persistent heartbeat checked against the shared SQLite Runtime.

Liveness means the process responds. Readiness additionally depends on the Host heartbeat, schema and writable artifact storage.

## Local three-terminal deployment

```powershell
# Terminal 1: worker host
poetry run paperguide server start
```

```powershell
# Terminal 2: API
poetry run paperguide-api
```

```powershell
# Terminal 3: Dashboard
Set-Location paperguide-dashboard
npm install
npm run dev
```

All Python processes must use the same `PAPERGUIDE_EXPORT_DIRECTORY`; this also determines the shared SQLite Runtime location.

## Operational checks

```powershell
docker compose config
docker compose ps
docker compose logs api host dashboard
```

Logs may be inspected for task IDs, status and duration. Do not enable logging of prompts, Provider responses, credentials or complete paper text.

## Current limitations

- Local single-machine deployment only.
- SQLite is not intended for high-write distributed clusters.
- One Active Host coordinates execution.
- At-least-once execution requires idempotent artifacts and fenced result writes.
- No built-in authentication or TLS termination.
- No Redis, Celery, Kubernetes or external database integration.

For Internet-facing deployment, place the system behind authenticated TLS ingress and complete a separate threat model before use.
