---
status: accepted
date: 2026-10-31
---

# Redact with regex first, then Presidio NER per language, with regex alone as a light mode

## Context and Problem Statement

Free text in traces holds structured identifiers (emails, phones, cards, IBANs, street
addresses, order ids) and names. Regular expressions catch the structured ones reliably,
including checksums, but cannot find names. NER finds names but needs spaCy models, has no
credit card recognizer in French, and splits a street address into smaller LOCATION spans
(`docs/verified.md`; `src/trace_to_golden/redact/__init__.py`, `build_redactor`).

## Decision Drivers

- No planted value may reach the store on the bundled samples.
- Few false positives, because an eval case must keep its meaning.
- A mode that runs without spaCy models.

## Considered Options

- Regex only.
- Presidio only.
- Regex first, then Presidio in the detected language, skipping findings that overlap a
  placeholder regex already wrote.

## Decision Outcome

Chosen option: regex, then Presidio, with regex alone available as `TTG_REDACTOR=regex`.
Regex replaces whole
addresses and team patterns before Presidio can split them, Presidio adds the names regex
cannot see, and skipping overlaps keeps `<ORDER_ID>` from becoming `<<PERSON>>`. DATE_TIME is
left out of the default entities because it fires on phrases like "after 2 years" that carry
the meaning of a case (`src/trace_to_golden/config.py`, `DEFAULT_REDACTION_ENTITIES`).

### Consequences

Measured on the 66 planted values in `pii_ground_truth.json` (`results/manifest.json`):

- Good: regex then Presidio removes 66 of 66 (34 of 34 English, 32 of 32 French)
  (`runs.presidio.planted_pii_removed`, `planted_pii_removed_en`, `planted_pii_removed_fr`).
- Bad: 6 extra detections, 4 PERSON and 2 LOCATION, beyond the planted counts
  (`runs.presidio.extra_detections`, `extra_detections_by_entity`).
- Light mode removes 55 of 66 and misses all 11 names
  (`runs.regex.planted_pii_removed`, `runs.regex.leaked_by_entity`).
- Bad: each new language needs its own spaCy model and a check of which Presidio recognizers
  exist for it (`docs/architecture.md`, Adding a source or a target).

## Pros and Cons of the Options

### Regex only

- Good: no model download, fast, deterministic.
- Bad: misses every name (11 of 66 planted values).

### Presidio only

- Good: one engine for names and structured data.
- Bad: no French credit card recognizer, and addresses split into LOCATION fragments
  (`docs/verified.md`).
