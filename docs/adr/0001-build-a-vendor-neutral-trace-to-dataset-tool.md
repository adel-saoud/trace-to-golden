---
status: accepted
date: 2026-10-31
---

# Build a vendor-neutral trace-to-dataset tool instead of using a platform's datasets

## Context and Problem Statement

The best eval cases come from production failures, which sit in traces next to thousands of
ordinary calls and full of personal data. Tracing platforms can turn traces into datasets, but
each one works on its own store. MLflow 3, for example, builds eval datasets from traces with
`mlflow.genai.datasets.create_dataset` and `merge_records` (README, Limits). The traces in this
system come from llm-gateway and agent-mesh as OpenTelemetry GenAI spans, and the cases feed
llm-regression-detector, which gates merges.

## Considered Options

- Use the dataset feature of one tracing platform (MLflow, Langfuse or Phoenix).
- Build a small tool that reads exported traces from any source and writes the
  llm-regression-detector dataset format.

## Decision Outcome

Chosen option: build trace-to-golden. The platforms' features cover the step from trace to dataset, but not the steps
this system needs around it, namely input from OpenTelemetry files without a platform,
redaction before anything is stored, triage that picks the traces worth a review, and export
straight into the CI gate's schema.

### Consequences

- Good: works on any OpenTelemetry export and on MLflow exports
  ([ADR 0004](0004-opentelemetry-genai-as-primary-input.md)).
- Good: the whole pipeline runs offline with no API key; `uv run ttg demo` processes 102
  traces end to end (`results/manifest.json`, `runs.presidio.traces`).
- Bad: one more tool to maintain, and a team already on one platform gets less from it. The
  README points such a team to MLflow datasets.
