# PaperPilot v1.0.0 release checklist

Validation date: 2026-08-06

Release verdict: **NOT READY TO PUBLISH**

No publishing action is authorized by this checklist. PyPI, npm, Git tags and GitHub Releases remain explicit owner decisions.

## Demo validation

- [x] `paperpilot demo` completed without OpenAI, Anthropic or Tavily credentials.
- [x] A persistent task was created in the SQLite TaskStore.
- [x] The existing LangGraph workflow reached `completed`.
- [x] A Markdown Artifact was generated.
- [x] The Artifact warning identifies its papers and evidence as synthetic.
- [x] Automated Demo tests prevent network use and verify Dashboard-compatible task status.

Observed safe CLI result:

```json
{
  "artifact": "yoloslam.md",
  "mode": "demo",
  "status": "completed",
  "warnings": [
    "Demo verification used deterministic exact-quote checks.",
    "Offline demo uses synthetic papers and must not be cited as real research."
  ]
}
```

The validation record intentionally omits the temporary task ID, local database path and Artifact path.

## Backend validation

- [x] Historical pre-10.21.2A baseline: 532 PaperPilot tests passed.
- [x] Current PaperPilot Backend Gate (including 10.21.2A): 542 tests passed.
- [x] API tests passed.
- [x] Document, Reader, Evidence and reporting tests passed.
- [x] Runtime coordination, recovery, lease and dead-letter tests passed.
- [x] Docker deployment static tests passed.
- [x] Demo Mode tests passed.
- [x] `python -m compileall paperpilot` passed.

Non-blocking test-environment warnings:

- LangGraph emits a pending deprecation warning for checkpoint serializer defaults.
- FastAPI TestClient reports an upstream Starlette/httpx deprecation warning.
- The local validation environment cannot update the existing `.pytest_cache` directory.

## Dashboard validation

- [x] TypeScript application typecheck passed.
- [x] TypeScript Vite configuration typecheck passed.
- [x] 14 Vitest files passed.
- [x] 199 Dashboard tests passed.
- [x] Vite production build passed.
- [x] Artifact viewer, task detail, research form and API client tests passed.
- [ ] Main production JavaScript chunk is below 500 kB.

The build completed successfully, but one minified chunk is approximately 609 kB. This is a performance follow-up, not a correctness failure.

## Docker runtime validation

- [x] Compose, Dockerfile, environment, Volume and health-check contracts are covered by 10 passing static tests.
- [ ] `docker compose up --build` executed successfully on the release candidate.
- [ ] Dashboard opened through Nginx at `http://localhost`.
- [ ] API liveness and readiness were checked inside Compose.
- [ ] Host heartbeat became healthy inside Compose.
- [ ] A research task completed through Dashboard → API → Host.
- [ ] The completed Artifact was downloaded and its SHA-256 header verified.

Blocker: Docker CLI and Docker Desktop are not installed in the current validation environment. Static tests are not accepted as a substitute for these runtime checks.

## Security and packaging

- [x] No OpenAI-style key, GitHub token, AWS key or private-key signature was found.
- [x] Secret-assignment matches were manually reviewed as environment lookups, protocol types, redaction fixtures or documentation placeholders.
- [x] No database file is tracked by Git.
- [x] Runtime database and runtime-data patterns are excluded from Git and Docker build context.
- [x] New release documentation contains no absolute developer path.
- [x] `git diff --check` passed for release files and documentation.
- [ ] Remove or intentionally retain the ignored local `paperpilot-runtime.sqlite3` before creating a source archive outside Git.
- [ ] Review the complete dirty working tree and create an intentional release commit.

## Version consistency

- [ ] Python package version is `1.0.0`.
- [ ] FastAPI application metadata is `1.0.0`.
- [ ] Dashboard package version is `1.0.0`.
- [x] CHANGELOG contains a v1.0.0 release section.
- [x] README and release documentation consistently identify PaperPilot v1.

Current metadata:

| Component | Current value | Required value |
| --- | --- | --- |
| Python package | `0.14.7` | `1.0.0` |
| FastAPI metadata | `10.17` | `1.0.0` |
| Dashboard package | `0.1.0` | `1.0.0` |

The mismatch cannot be corrected in this task because Python and Dashboard source modification is explicitly out of scope.

## Documentation and governance

- [x] Main README describes architecture, Demo, deployment and current limitations.
- [x] Architecture, Demo, Deployment, API and Design Decision documents exist.
- [x] Demo documentation clearly labels all Demo papers and evidence as synthetic.
- [x] CHANGELOG documents v1.0.0 features and validation state.
- [ ] Capture the three real Dashboard screenshots defined in `docs/images/README.md`.
- [ ] Review upstream GPT Researcher license and all third-party release obligations.
- [ ] Approve final repository name, ownership, changelog comparison URL and release notes.

## Final release gate

Do not publish v1.0.0 until all of the following are complete:

1. Run the full Docker workflow on a Docker-enabled machine.
2. Align Python, API and Dashboard version metadata to `1.0.0` in an explicitly authorized task.
3. Review and commit the complete working tree intentionally.
4. Capture real Dashboard screenshots and complete the manual Demo checklist.
5. Review license and attribution obligations.

## 10.21.4C validation record (2026-08-09)

- [x] PaperPilot survey gate: 233 tests passed.
- [x] Survey rendering/PDF/Fishbone gate: 14 tests passed.
- [x] `python -m compileall -q paperpilot` passed.
- [x] `git diff --check` passed.
- [x] Dashboard typecheck passed.
- [x] Dashboard Vitest: 208 tests passed across 15 files.
- [x] Dashboard build passed.
- [x] Real Chrome PDF.js validation passed against a completed six-page PDF: page 1/2 render, next/previous, zoom and fit-width controls verified; no browser PDF plugin was used.
- [x] Real Chrome HTML validation passed against the Survey HTML artifact: contents, headings, comparison table and responsive document loaded without console errors.
- [x] PDF CJK smoke validation passed using PyMuPDF's built-in CJK face; Chinese title/body text remained readable and extractable.
- [x] PDF Fishbone 12-entry validation passed: entries were split into multiple figure pages without loss or duplication.
- [ ] Real external-provider research run: blocked because no provider credential is configured in this environment; no fake result is reported as real.
- [ ] Docker runtime validation: blocked because Docker CLI/Desktop is unavailable in this environment.

The browser checks used local completed artifacts and the running local API/Host. A real external-provider E2E run and Docker Compose run remain release-finalization items.
