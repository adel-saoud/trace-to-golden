---
status: accepted
date: 2026-10-31
---

# Read OpenTelemetry GenAI exports as the primary input, and MLflow exports without importing MLflow

## Context and Problem Statement

llm-gateway and agent-mesh emit OpenTelemetry GenAI spans; other teams keep traces in MLflow.
The GenAI semantic conventions are at Development status and moved to their own repository
with no release yet, so attribute names can still change (`docs/verified.md`). The question is
which input format the tool is built around and how it parses each one.

## Considered Options

- Build around MLflow traces and its Python client.
- Build around OTLP/JSON exports, parsed with the `opentelemetry-proto` package.
- Build around OTLP/JSON exports, parsed with small pydantic models, and read MLflow
  `Trace.to_json()` exports as plain JSON.

## Decision Outcome

Chosen option: OTLP/JSON parsed with small pydantic models, plus an MLflow file adapter.
OpenTelemetry is the
vendor-neutral format the producers in this system emit, and reading export files keeps the
tool free of a platform client. All GenAI attribute names live in one module,
`src/trace_to_golden/ingest/otel_genai.py`, so a convention change touches one file. The
MLflow adapter reads exported JSON without importing MLflow
(`src/trace_to_golden/ingest/mlflow_json.py`).

### Consequences

- Good: both the semconv v1.37 message attributes and the older indexed layout are read
  (`docs/verified.md`; `tests/test_ingest_otel.py`).
- Good: no dependency on `opentelemetry-proto` or `mlflow`.
- Bad: the small models must follow OTLP/JSON encoding rules by hand (hex ids, int64 as
  strings), which `docs/verified.md` records.
- Bad: the MLflow adapter reads `request_preview` and `response_preview`, which MLflow may
  truncate on very long requests (README, Limits).
- Bad: message content is opt-in in the GenAI conventions, so producers must turn it on
  (`docs/configuration.md`).
