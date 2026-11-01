# Configuration

Every setting is a `TTG_*` environment variable, read by pydantic-settings in
`src/trace_to_golden/config.py`. List and map values are JSON, as pydantic-settings reads them.

A `TTG_*` variable that matches no setting stops the command with exit code 2 and the closest
valid name (`TTG_DB_PTH (did you mean TTG_DB_PATH?)`): pydantic-settings would otherwise
ignore it and keep the default.

| Variable | Default | Meaning |
|---|---|---|
| `TTG_DB_PATH` | `trace_to_golden.db` | SQLite store |
| `TTG_REDACTOR` | `presidio` | `presidio` (regex + NER) or `regex` (light mode) |
| `TTG_SPACY_MODELS` | `{"en": "en_core_web_sm", "fr": "fr_core_news_md"}` | JSON map of language to spaCy model; its keys are the languages detected and clustered. French uses the medium model because the small one tags phrases like "Ma livraison" as a name |
| `TTG_REDACTION_ENTITIES` | names, emails, phones, cards, IBANs, IPs, locations, US SSN | JSON list of Presidio entity types (DATE_TIME is off: it fires on "after 2 years") |
| `TTG_REDACTION_SCORE_THRESHOLD` | `0.4` | Presidio `score_threshold`: findings scored lower are kept in the text |
| `TTG_EXTRA_REDACTION_PATTERNS` | `{}` | JSON map of extra regexes, e.g. `{"ORDER_ID": "CMD-\\d{8}"}` |
| `TTG_FEEDBACK_SCORE_ATTRIBUTE` | `user_feedback.score` | OTel attribute holding the user feedback score |
| `TTG_FEEDBACK_COMMENT_ATTRIBUTE` | `user_feedback.comment` | OTel attribute holding the user feedback comment |
| `TTG_MIN_CLUSTER_SIZE` | `3` | HDBSCAN `min_cluster_size` |
| `TTG_OUTLIER_Z_THRESHOLD` | `3.5` | robust z-score above which latency or tokens are outliers |
| `TTG_DEDUPE_SIMILARITY_THRESHOLD` | `0.9` | cosine similarity counted as a near duplicate |

## Getting traces out of your stack

- **OpenTelemetry:** the Collector `file` exporter (`format: json`) writes the expected
  newline-delimited OTLP/JSON. Message content is opt-in in the GenAI conventions; turn it on
  in your instrumentation, and set `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental`
  where the instrumentation supports it.
- **MLflow:** `mlflow.search_traces(return_type="list")`, then `trace.to_json()` per line.

User feedback has no OpenTelemetry convention. By default the score is read from
`user_feedback.score` (from -1.0 to 1.0) on any span of the trace. MLflow human feedback
assessments are read natively.
