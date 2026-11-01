---
status: accepted
date: 2026-10-31
---

# Not built: a web review UI or a server; a CLI over one local SQLite file

## Context and Problem Statement

Reviewers need to approve, edit or reject candidates, and the redacted traces and queue need
to persist between runs. The redacted store is still sensitive (ADR 0002), so where it lives
and who can reach it matters.

## Considered Options

- A web review UI backed by a server and a shared database.
- A CLI (`ttg review`, `ttg approve`, `ttg reject`) over one local SQLite file.

## Decision Outcome

Chosen option: the CLI over SQLite (`src/trace_to_golden/cli.py`, `src/trace_to_golden/store.py`).
A CLI keeps the redacted
text on one machine with no network surface, and SQLite needs no service to run. Records are
stored as pydantic JSON in one column, so every read goes back through model validation
(`store.py` docstring). Triage results are not stored; they live on the queued candidates and
are recomputed on each `ttg triage` run (CHANGELOG, Removed).

### Consequences

- Good: the whole review loop runs offline and is tested end to end (`tests/test_cli.py`).
- Bad: one reviewer at a time; there is no shared queue, no assignment and no audit view.
- Bad: no retention policy is enforced; the store keeps redacted traces until someone deletes
  the file. How long to keep them is an open question for the maintainer.
- Re-ingesting a file skips records already stored, and a queued candidate keeps its review
  state (`docs/architecture.md`, Failure modes).
