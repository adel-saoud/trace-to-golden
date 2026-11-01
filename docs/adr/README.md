# Architecture Decision Records

Format: [MADR 4.0.0](https://adr.github.io/madr/). A record stays `proposed` until the
maintainer confirms its reasoning; a replaced decision becomes `superseded by NNNN`.

| ADR | Title | Status |
|---|---|---|
| [0001](0001-build-a-vendor-neutral-trace-to-dataset-tool.md) | Build a vendor-neutral trace-to-dataset tool instead of using a platform's datasets | accepted |
| [0002](0002-allowlist-attributes-and-redact-before-storage.md) | Allowlist trace attributes and redact before storage, enforced by type | accepted |
| [0003](0003-regex-then-presidio-redaction.md) | Redact with regex first, then Presidio NER per language, with regex alone as a light mode | accepted |
| [0004](0004-opentelemetry-genai-as-primary-input.md) | Read OpenTelemetry GenAI exports as the primary input, and MLflow exports without importing MLflow | accepted |
| [0005](0005-tfidf-hdbscan-and-robust-z-scores-for-triage.md) | Triage with TF-IDF + HDBSCAN and robust z-scores instead of embeddings | accepted |
| [0006](0006-stop-word-language-detection-and-spacy-models.md) | Detect the language by counting stop words, and use the medium French spaCy model | accepted |
| [0007](0007-export-schema-v2-against-a-pinned-copy.md) | Export golden dataset schema v2 by default, validated against a copy pinned to a release tag | accepted |
| [0008](0008-no-web-ui-or-server-cli-and-local-sqlite.md) | Not built: a web review UI or a server; a CLI over one local SQLite file | accepted |
