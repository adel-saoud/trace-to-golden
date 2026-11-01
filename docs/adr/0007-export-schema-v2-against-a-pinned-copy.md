---
status: accepted
date: 2026-10-31
---

# Export golden dataset schema v2 by default, validated against a copy pinned to a release tag

## Context and Problem Statement

llm-regression-detector owns the golden dataset schema; its decision on that contract is in its
own ADRs ([llm-regression-detector docs/adr](https://github.com/adel-saoud/llm-regression-detector/blob/main/docs/adr/)).
This record covers the producer side only: which schema version trace-to-golden writes, and how
it proves its exports stay valid when the schema changes in another repository.

## Considered Options

- Import `llm-regression-detector` as a dependency and validate with its models.
- Keep a copy of its JSON Schema with no link to a release.
- Keep a byte-for-byte copy pinned to a producer release tag, checked by
  `scripts/sync_schemas.py --check` in pre-commit and CI.

## Decision Outcome

Chosen option: a pinned copy, `tests/fixtures/golden-dataset.v2.schema.json`, at tag v0.2.0
(`scripts/sync_schemas.py`, `CONTRACTS`), with schema v2 as the default export and v1 behind
`--schema v1`. V2 carries the
reference answer, rubric and source that a reviewed trace provides, while v1 needs a category
and drops them; a pinned copy keeps the CLI free of the evaluator's dependencies and makes every
schema change an explicit pin bump with a CHANGELOG entry.

### Consequences

- Good: the 44 exported demo cases validate against the copied schema
  (`results/manifest.json`, `runs.presidio.cases_exported`).
- Good: the check fails when the copy drifts from the producer's file; locally it reads the
  sibling checkout, in CI the raw file at the pinned tag.
- Bad: the CI check fails until the pinned tag is pushed upstream (`.github/workflows/ci.yml`
  comment).
- Bad: a failed trace has no answer, so it exports only once a reviewer adds a category or a
  rubric; v2 also rejects an empty dataset, so no file is written when no case is left
  (README, Limits).
