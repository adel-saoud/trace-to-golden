# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.0] - 2026-11-01

### Changed

- **Breaking:** Python 3.12 or newer is required (was 3.11). CI tests 3.12, 3.13 and 3.14; local development uses 3.14.
- Build backend switched from hatchling to `uv_build`.
- Tooling: ruff 0.17.2, pyright 1.1.414, pytest 9, pytest-cov 7. Pre-commit hooks and GitHub Actions are pinned by commit SHA.
- README follows the shared layout. Configuration moved to `docs/configuration.md`, `docs/ARCHITECTURE.md` renamed to `docs/architecture.md` (with a failure modes section), `docs/VERIFIED.md` renamed to `docs/verified.md`.
- Docs: `docs/DECISIONS.md` replaced by eight Architecture Decision Records in MADR 4.0.0 format under `docs/adr/`, all accepted.
- Synthetic traces from the local model now name `qwen3.5:4b` (was `llama3.1:8b`), matching agent-mesh and llm-gateway. Every measured number is unchanged.
- **Breaking:** `trace_to_golden.models.Triage` renamed to `TriageResult` and `trace_to_golden.triage.cluster.Clustering` to `ClusteringResult`, so each name says it holds a result. No alias is kept for the old names.

### Added

- CI jobs for pre-commit and for building the wheel and running `ttg --help` from a clean venv.
- gitleaks and commitizen pre-commit hooks, commitizen config (`cz bump` writes the version and the tag; this file stays hand-written), Dependabot for uv, GitHub Actions and pre-commit.
- `docs/demo.tape` and the recorded `docs/demo.gif`.
- A `TTG_*` environment variable that matches no setting now stops every command with exit code 2 and the closest valid name, instead of being silently ignored.
- `scripts/reproduce.py` regenerates every README number into `results/manifest.json` (versions, seed, dataset SHA-256, hardware, each metric with its sample size). `pipeline.run_demo` is the shared demo run behind it and `ttg demo`.
- `scripts/sync_schemas.py` keeps `tests/fixtures/golden-dataset.v2.schema.json` identical to llm-regression-detector's schema at a pinned tag; its `--check` runs in pre-commit and CI. The copy is synced to the schema llm-regression-detector releases as v0.2.0 (contract version 2).

### Removed

- **Breaking:** the SQLite `triage` table and `Store.save_triage` / `Store.triage`. Nothing read them; triage flags and topics stay on the queued candidates. Stores created by 0.1.0 keep an unused `triage` table.
- pytest as a pre-commit hook; the CI `tests` job runs it.

### Fixed

- Triage gave different clusters on macOS and Linux for the same traces. Texts with no word in common sit at distance sqrt(2), and HDBSCAN broke those ties on the last bit of a float, which differs by platform. Distances are now rounded to 9 decimals before clustering (`DISTANCE_DECIMALS`), so ties are exact everywhere. README numbers are unchanged.

## [0.1.0] - 2026-10-20

Not published; the baseline for the changes above.

### Added

- OpenTelemetry GenAI ingester for OTLP/JSON and Collector file exports (semconv v1.37 and the legacy indexed layout).
- MLflow 3 ingester for exported trace JSON, including human feedback assessments.
- Attribute allowlist and PII redaction before storage: regex (Luhn and IBAN checks, street addresses, custom patterns), then Presidio in English (`en_core_web_sm`) or French (`fr_core_news_md`).
- Stop-word language detection, also used to strip English and French stop words before clustering.
- Triage: TF-IDF + HDBSCAN intent clusters, error, negative feedback, cluster, latency and token outlier flags.
- Review queue with approve, edit and reject (`ttg review`, `ttg approve`, `ttg reject`); a rubric is a list of pass or fail criteria (`--rubric` repeated).
- Dedupe against an existing golden dataset (v1 or v2 file) and export to llm-regression-detector schema v2 (default: reference answer, rubric criteria, source) or v1 (`--schema v1`).
- Synthetic English and French traces from a shopping and after-sales assistant with planted PII, and an offline `ttg demo`.
