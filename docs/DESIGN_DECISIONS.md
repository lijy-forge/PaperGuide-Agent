# PaperPilot Design Decisions

This document records high-impact architecture decisions. Each ADR describes the context, selected choice and accepted tradeoff rather than treating a library name as an architectural justification.

## ADR-001: Why LangGraph

**Status:** Accepted

### Decision

Use LangGraph as the synchronous research workflow assembler while keeping Nodes as ordinary dependency-injected Python callables.

### Context

Paper research contains explicit stages, conditional retries, quality decisions, human-review routing and terminal states. These transitions need to be visible and testable without moving retrieval, parsing or verification logic into an Agent framework.

### Choice

`ResearchState` is the workflow contract. Node Adapters translate existing service results into new state values. Pure routing functions select the next registered node, and the composition root injects all business dependencies before Graph compilation.

### Tradeoff

LangGraph adds a framework dependency and requires strict state compatibility. In return, transitions are inspectable and conditional recovery is explicit. Business modules remain callable and testable without LangGraph.

## ADR-002: Why SQLite Runtime

**Status:** Accepted for v1 local deployment

### Decision

Use SQLite for persistent tasks, Host metadata, leases, event history, schema migrations and dead-letter records.

### Context

The v1 target is a local single-machine research tool and interview-ready demonstration. Requiring Redis, Celery and an external database would increase setup and operating cost before the workload justifies distributed infrastructure.

### Choice

Use transactions, WAL, lease expiry, fencing tokens and stable execution IDs to coordinate one Active Host and recover work after crashes.

### Tradeoff

SQLite provides portability, inspectability and low operational overhead, but it is not a high-throughput distributed queue. The design explicitly limits v1 to a single-machine, single-Active-Host model and at-least-once execution.

## ADR-003: Why Evidence Grounding

**Status:** Accepted

### Decision

Require structured claims to reference located Evidence, verify that Evidence independently, and generate reports only from accepted Evidence.

### Context

Fluent LLM summaries can overstate results, misquote metrics or invent citations. A technical literature tool must make it possible to trace report claims back to source text and location.

### Choice

Represent Evidence with a paper ID, exact quote, normalized fact, confidence and `SourceLocator`. Apply deterministic and semantic verification, remove rejected/conflicted evidence from report context, and verify citations again before export.

### Tradeoff

The pipeline may reject useful but weakly located claims and can produce shorter reports. Verification also adds latency and Provider cost. The benefit is a report with a materially stronger audit trail and explicit unsupported-content handling.

## ADR-004: Why Demo Provider

**Status:** Accepted for demonstration only

### Decision

Provide an offline Demo composition using synthetic papers, documents, analyses, Evidence and structured output.

### Context

Interviews, classrooms and automated tests need a repeatable demonstration without API keys, network availability, Provider cost or dependence on changing search results.

### Choice

Replace external Retriever, document acquisition, Reader, Verifier and Provider boundaries while reusing the production SearchPipeline, LangGraph, QualityGate, report verification, export and persistence layers.

### Tradeoff

Demo output cannot demonstrate retrieval recall, PDF compatibility or real LLM quality. It must always be labelled synthetic and must never be presented as an actual literature review. Its value is architectural and operational reproducibility.

## Consequences shared by these decisions

- The system favors explicit contracts and auditability over opaque autonomous behavior.
- Local deployment remains simple while runtime failure semantics remain visible.
- Real research and Demo execution share orchestration but not external data.
- A future distributed runtime can replace storage and coordination protocols without rewriting paper-analysis services.
