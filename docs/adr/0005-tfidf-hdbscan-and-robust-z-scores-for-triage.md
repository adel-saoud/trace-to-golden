---
status: accepted
date: 2026-10-31
---

# Triage with TF-IDF + HDBSCAN and robust z-scores instead of embeddings

## Context and Problem Statement

A reviewer cannot read every trace. Triage must pick one representative per user intent and
every trace that looks wrong: errors, negative feedback, intents that fit no cluster, and
unusual latency or token counts. It has to run offline with no API key, like the rest of the
pipeline.

## Considered Options

- Embed questions with a model, then cluster the embeddings.
- TF-IDF vectors with English and French stop words removed, clustered by HDBSCAN.
- For outliers: mean and standard deviation z-scores, or median and MAD (robust) z-scores.

## Decision Outcome

Chosen option: TF-IDF (word 1-grams and 2-grams, sublinear TF) with HDBSCAN, and robust
z-scores (0.6745 x (x - median) / MAD, outlier above 3.5) for latency and tokens
(`src/trace_to_golden/triage/cluster.py`, `src/trace_to_golden/triage/flags.py`). HDBSCAN needs no cluster count and labels
traces that fit no intent as noise, which is itself a review signal; TF-IDF needs no model or
key; median and MAD are not pulled by the very outliers they look for.

### Consequences

- On the 102 sample traces: 16 intent clusters, 33 flagged traces, 47 candidates for review
  (`results/manifest.json`, `runs.presidio.intent_clusters`, `flagged_traces`,
  `review_candidates`).
- Bad: on sparse input HDBSCAN computes brute-force pairwise distances, so memory grows with
  the square of the trace count; above a few tens of thousands of traces per run, triage a
  window or a sample (README, Limits; `cluster.py` docstring).
- Bad: TF-IDF groups by shared words, so paraphrases with no word in common land in different
  clusters. Embeddings would group them, at the cost of a model.
- Fewer traces than `TTG_MIN_CLUSTER_SIZE` makes every trace noise, and only flagged traces
  are queued (`docs/architecture.md`, Failure modes).
