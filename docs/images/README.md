# PaperGuide screenshot capture slots

This directory reserves the following release artifact names:

- `dashboard.png`
- `task-detail.png`
- `artifact-viewer.png`

The files must be captured from a real local Demo Runtime. Do not substitute generated UI mockups or unrelated GPT Researcher screenshots.

## Capture checklist

1. Start Host with `PAPERGUIDE_MODE=demo`, then start API and Dashboard.
2. Use a clean browser profile and a 1440 × 900 viewport.
3. Ensure no API key, absolute path, full question query parameter or internal runtime identifier is visible.
4. Capture `dashboard.png` after readiness and metrics have loaded.
5. Complete one Demo task and capture `task-detail.png` with the public event timeline.
6. Open the report preview and capture `artifact-viewer.png` with the synthetic-data warning and SHA-256 metadata visible.
7. Review every image before commit and update the README Screenshot table status.

No placeholder PNG is committed because a generated placeholder could be mistaken for verified application output.
