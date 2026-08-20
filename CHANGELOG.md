# Changelog

All notable changes to PaperPilot AI are documented in this file. The project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) conventions.

## [1.0.0] - Unreleased

### Features

- LangGraph Research Agent
- Evidence Grounding
- Persistent Runtime
- Dashboard
- Docker Deployment
- Offline Demo

### Added

- Multi-source paper retrieval through arXiv and Semantic Scholar adapters.
- Deterministic PDF ingestion, page extraction and heuristic section detection.
- Structured paper reading for methods, experiments and located Evidence.
- Independent Evidence verification, conflict detection and quality gating.
- LangGraph orchestration with conditional routing and recovery contracts.
- SQLite-backed tasks, events, Host heartbeat, leases, fencing tokens and dead-letter handling.
- Evidence-grounded report generation with Markdown, HTML and PDF export.
- FastAPI task API and React research Dashboard.
- Docker Compose packaging for Dashboard, API and Task Host.
- Fully offline Demo Mode using explicitly labelled synthetic papers and evidence.

### Security

- Provider credentials remain runtime environment variables and are excluded from PaperPilot settings.
- Public API responses omit research questions, internal paths and coordination metadata.
- Artifact paths are constrained to the configured export root and include SHA-256 metadata.
- Markdown and HTML report previews apply explicit content-safety boundaries.

### Release validation

- PaperPilot backend: 532 tests passed on 2026-08-06.
- Dashboard: typecheck passed; 199 tests passed; production build passed.
- Offline Demo: completed without Provider credentials and generated a persisted Markdown artifact.
- Docker static deployment tests: passed.

### Known release blockers

- Docker Compose runtime validation still requires a machine with Docker available.
- Version metadata is not yet aligned: Python package `0.14.7`, FastAPI metadata `10.17`, and Dashboard package `0.1.0`.
- The repository working tree contains extensive uncommitted PaperPilot changes that require an intentional release commit review.
