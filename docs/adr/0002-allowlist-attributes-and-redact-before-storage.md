---
status: accepted
date: 2026-10-31
---

# Allowlist trace attributes and redact before storage, enforced by type

## Context and Problem Statement

Traces carry personal data in two places: free text (questions, answers, feedback comments)
and span attributes such as `enduser.id` and `url.full`. The sample traces plant both
(`scripts/generate_samples.py`). Whatever reaches the SQLite store can leak later through
exports, backups or a reviewer's screen, so the question is where personal data is removed and
how a future change is kept from bypassing that.

## Considered Options

- Store traces as received and redact at export time.
- Redact every attribute and every text field before storage.
- Copy only an allowlist of fields out of each trace, redact the remaining free text, and make
  the store accept redacted records only.

## Decision Outcome

Chosen option: allowlist, then redact, then store. An attribute nobody listed is dropped by default, so a new
attribute cannot leak until someone adds it on purpose, and redaction only has to handle the
few free-text fields. `TraceRecord` is the allowlist (`src/trace_to_golden/models.py`);
`Store.add_traces` accepts `RedactedTrace` only, which only `redact_record` builds, so Pyright
in strict mode rejects code that would store raw text (`src/trace_to_golden/store.py`,
`docs/architecture.md`, Privacy rules).

### Consequences

- Good: 0 of 95 distinct `enduser.id` and `url.full` values from the samples reach the store
  (`results/manifest.json`, `runs.presidio.allowlist_values_stored`).
- Good: `tests/test_redact.py` scans the raw SQLite bytes for every planted value.
- Bad: a useful new attribute, for example agent-mesh's `agent_mesh.outcome`, is ignored until
  `TraceRecord` gains a field for it.
- Bad: the redacted text is still sensitive, because NER misses names it has never seen in
  context (README, Limits).
