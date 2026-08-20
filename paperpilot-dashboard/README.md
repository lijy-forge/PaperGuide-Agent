# PaperPilot AI Dashboard

React 18 + TypeScript + Vite dashboard for the existing PaperPilot FastAPI API. It is intended for local portfolio and interview demonstrations. Authentication is not included; do not expose this setup directly to the public internet.

## Requirements

- Node.js 18.18 or newer
- npm (or a compatible package manager)
- PaperPilot Task Host and API from the repository root

## Install and run

```powershell
cd paperpilot-dashboard
npm install
Copy-Item .env.example .env.local
npm run dev
```

The development server runs at `http://127.0.0.1:5173`. Vite proxies `/api` and `/health` to `http://127.0.0.1:8000`, so changing FastAPI CORS settings is unnecessary.

For a production build, set `VITE_PAPERPILOT_API_BASE_URL` to the API origin, then run `npm run build`.

## Three-terminal local demo

From the repository root:

```powershell
# Terminal 1: persistent host
$env:PAPERPILOT_EXPORT_DIRECTORY = "E:\PaperPilotData\artifacts"
poetry run paperpilot server start

# Terminal 2: HTTP API
$env:PAPERPILOT_EXPORT_DIRECTORY = "E:\PaperPilotData\artifacts"
poetry run paperpilot-api

# Terminal 3: dashboard
cd paperpilot-dashboard
npm install
npm run dev
```

## Configuration

`VITE_PAPERPILOT_API_BASE_URL` is non-secret and defaults to same-origin requests (the Vite proxy during development). Never put API keys, tokens, or passwords in a `VITE_` variable because Vite embeds those values in browser assets.

## Common errors

- **Host Offline:** start the long-running host with `paperpilot server start` and confirm both host and API use the same runtime configuration.
- **API Offline:** start `paperpilot-api` and verify port 8000 is available.
- **Artifact Not Ready:** the task has not reached `completed`; the dashboard will keep polling.
- **Runtime DB mismatch:** make sure the host and API point to the same SQLite runtime database and export directory.

Task questions used for recent-history labels stay in this browser's local storage. Reports and evidence are never stored there.
