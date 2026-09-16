# PaperGuide AI Dashboard

React 18 + TypeScript + Vite dashboard for the existing PaperGuide FastAPI API. It is intended for local portfolio and interview demonstrations. Authentication is not included; do not expose this setup directly to the public internet.

## Requirements

- Node.js 18.18 or newer
- npm (or a compatible package manager)
- PaperGuide Task Host and API from the repository root

## Install and run

```powershell
cd paperguide-dashboard
npm install
Copy-Item .env.example .env.local
npm run dev
```

The development server runs at `http://127.0.0.1:5173`. Vite proxies `/api` and `/health` to `http://127.0.0.1:8000`, so changing FastAPI CORS settings is unnecessary.

For a production build, set `VITE_PAPERGUIDE_API_BASE_URL` to the API origin, then run `npm run build`.

## Three-terminal local demo

From the repository root:

```powershell
# Terminal 1: persistent host
$env:PAPERGUIDE_EXPORT_DIRECTORY = "E:\PaperGuideData\artifacts"
poetry run paperguide server start

# Terminal 2: HTTP API
$env:PAPERGUIDE_EXPORT_DIRECTORY = "E:\PaperGuideData\artifacts"
poetry run paperguide-api

# Terminal 3: dashboard
cd paperguide-dashboard
npm install
npm run dev
```

## Configuration

`VITE_PAPERGUIDE_API_BASE_URL` is non-secret and defaults to same-origin requests (the Vite proxy during development). Never put API keys, tokens, or passwords in a `VITE_` variable because Vite embeds those values in browser assets.

## Common errors

- **Host Offline:** start the long-running host with `paperguide server start` and confirm both host and API use the same runtime configuration.
- **API Offline:** start `paperguide-api` and verify port 8000 is available.
- **Artifact Not Ready:** the task has not reached `completed`; the dashboard will keep polling.
- **Runtime DB mismatch:** make sure the host and API point to the same SQLite runtime database and export directory.

Task questions used for recent-history labels stay in this browser's local storage. Reports and evidence are never stored there.
