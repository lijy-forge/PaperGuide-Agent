# PaperGuide API Overview

## Scope

The FastAPI layer is a thin, synchronous HTTP boundary over the persistent task runtime. Research execution occurs in the independent Task Host; API request handlers do not create a Graph, Provider or Worker.

Base path: `/api/v1`

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/research` | Validate and enqueue a research request |
| `GET` | `/api/v1/tasks/{task_id}` | Return sanitized task status |
| `POST` | `/api/v1/tasks/{task_id}/cancel` | Request idempotent cancellation |
| `GET` | `/api/v1/tasks/{task_id}/events` | Return paginated public task events |
| `GET` | `/api/v1/tasks/{task_id}/artifact` | Download a completed report artifact |
| `GET` | `/api/v1/metrics` | Return JSON runtime metrics |
| `GET` | `/health/live` | Process liveness |
| `GET` | `/health/ready` | Runtime readiness |

## Submit research

```http
POST /api/v1/research
Content-Type: application/json

{
  "question": "What methods combine YOLO with visual SLAM?",
  "max_papers": 3,
  "export_format": "markdown"
}
```

A successful request returns HTTP `202 Accepted` with a task ID, initial status and creation timestamp. The response does not echo the research question.

Supported formats are `markdown`, `html` and `pdf`. `max_papers` must be between 1 and 50.

## Task status

The public status response includes:

- task and run identifiers;
- lifecycle status and timestamps;
- whether an artifact is available;
- artifact format;
- human-review and retry flags;
- a safe error code when applicable.

It excludes the question, Python exception text, database paths, artifact filesystem paths, Host IDs, execution IDs, lease owners and fencing tokens.

## Events

`GET /api/v1/tasks/{task_id}/events` accepts `limit`, `offset` and an optional public event type. Events contain lifecycle status, attempt count, optional duration and timestamp. Internal coordination metadata is not exposed.

Typical event types include task creation, queueing, start, completion, failure, cancellation, lease renewal, lease expiration, aborted execution and dead-letter transition.

## Artifact download

Artifacts are available only for completed tasks. The server resolves the stored path beneath the configured artifact root and rejects traversal or mismatched task metadata.

Relevant response headers:

- `Content-Type`
- `Content-Disposition`
- `X-Artifact-SHA256`
- `Content-Security-Policy`

The download name is normalized to `research-report` with the corresponding extension.

## Errors and request IDs

Errors use a stable public code, a safe message and a request ID. Internal tracebacks, raw Provider responses and local paths are not returned. Clients should use the response status and public code for behavior, and the request ID for support correlation.

Common conditions include invalid input, missing task, unavailable Host and artifact-not-ready.

## Security boundary

The current API has no user authentication. Bind it to loopback or place it behind a trusted authenticated gateway. Do not expose it directly to an untrusted network.

Interactive schema documentation is available from `/docs` while the API is running; the machine-readable OpenAPI document is `/openapi.json`.
