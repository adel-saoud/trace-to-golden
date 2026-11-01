---
status: accepted
date: 2026-10-31
---

# Detect the language by counting stop words, and use the medium French spaCy model

## Context and Problem Statement

Presidio runs NER with one spaCy model per language, and triage removes each language's stop
words before clustering, so every trace needs a language. The samples are support messages in
English and French. Model choice matters too: on the samples the small French model tags
sentence-initial phrases such as "Ma livraison" as a person, which destroys the question an eval
case needs (`docs/verified.md`; `src/trace_to_golden/config.py`, `DEFAULT_SPACY_MODELS`).

## Considered Options

- A trained language detector (an extra dependency and model).
- Count each configured language's spaCy stop words and pick the highest count.
- For French NER: `fr_core_news_sm` or `fr_core_news_md`.

## Decision Outcome

Chosen option: stop-word counting (`StopWordLanguageDetector`, `src/trace_to_golden/language.py`)
with `en_core_web_sm` and `fr_core_news_md`. The stop-word lists ship with spaCy and load without a trained pipeline, so
detection adds no dependency or download; the configured languages are the keys of
`TTG_SPACY_MODELS`, so a new language is a configuration change. The medium French model
avoids the false PERSON tags measured with the small one.

### Consequences

- Good: 32 of 32 French planted values removed (`results/manifest.json`,
  `runs.presidio.planted_pii_removed_fr`).
- Bad: one-word messages and mixed-language text are not detected reliably; a tie goes to the
  first configured language (`docs/architecture.md`, Language detection).
- Bad: the medium French model is a larger download than the small one; both are installed
  from the spaCy release page, not PyPI (`pyproject.toml`, `[tool.uv.sources]`).
