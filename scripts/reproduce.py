"""Regenerate every number the README shows and write them to results/manifest.json.

Run: `uv run python scripts/reproduce.py`. It runs the offline demo pipeline
(`pipeline.run_demo`) twice on the bundled synthetic traces, once with Presidio
and once in regex-only light mode, then measures the stored bytes against
`pii_ground_truth.json`. No step calls a paid API, so there is no `--live` mode.

The manifest records what a reader needs to rerun and trust the numbers: date,
git commit, Python and package versions, spaCy models, the sample seed, each
dataset file's SHA-256, a hardware summary, and every metric with its sample size.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import runpy
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import UTC, datetime
from importlib import metadata, resources
from pathlib import Path
from typing import Any

import jsonschema

from trace_to_golden import pipeline
from trace_to_golden.config import RedactorName, Settings

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "results" / "manifest.json"
SAMPLES = Path(str(resources.files("trace_to_golden.samples") / "data"))
SCHEMA = ROOT / "tests" / "fixtures" / "golden-dataset.v2.schema.json"
PACKAGES = (
    "trace-to-golden",
    "presidio-analyzer",
    "presidio-anonymizer",
    "spacy",
    "scikit-learn",
    "numpy",
    "pydantic",
    "jsonschema",
)
ALLOWLIST_PROBES = ("enduser.id", "url.full")
"""Span attributes the samples fill with customer data that the allowlist must drop."""


def git_commit() -> str:
    """HEAD commit, or `uncommitted` when there is no commit or the tree has changes.

    A dirty tree means the numbers may not match any commit, so it is not
    reported as one.
    """
    executable = shutil.which("git")
    if executable is None:
        return "uncommitted"

    def output(*args: str) -> str:
        # S603: the arguments are fixed read-only subcommands, never user input.
        return subprocess.run(  # noqa: S603
            [executable, *args], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()

    try:
        head = output("rev-parse", "HEAD")
        dirty = output("status", "--porcelain")
    except (OSError, subprocess.CalledProcessError):
        return "uncommitted"
    return "uncommitted" if dirty else head


def sha256(path: Path) -> str:
    """Hex digest of a file, so a reader can tell the dataset has not changed."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def distribution_version(name: str) -> str | None:
    """Installed version of a distribution, or None when it is not installed."""
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def allowlist_probe_values() -> set[str]:
    """Every value the samples put in `ALLOWLIST_PROBES` attributes."""
    values: set[str] = set()
    for line in (SAMPLES / "otel_traces.jsonl").read_text(encoding="utf-8").splitlines():
        for resource in json.loads(line)["resourceSpans"]:
            for scope in resource["scopeSpans"]:
                for span in scope["spans"]:
                    for attribute in span.get("attributes", []):
                        if attribute["key"] in ALLOWLIST_PROBES:
                            values.add(attribute["value"]["stringValue"])
    return values


def metric(value: int | float, sample_size: int, method: str) -> dict[str, Any]:
    """One manifest metric: the number, what it was measured on, and how."""
    return {"value": value, "sample_size": sample_size, "method": method}


def measure(redactor: RedactorName, workdir: Path, truth: list[dict[str, str]]) -> dict[str, Any]:
    """Run the demo with one redactor and measure redaction, triage and export."""
    report = pipeline.run_demo(workdir, Settings(redactor=redactor))
    stored = (workdir / "demo.db").read_bytes()
    leaked = [t for t in truth if t["text"].encode() in stored]
    planted = Counter(t["entity"] for t in truth)
    detected: Counter[str] = Counter()
    for ingested in report.ingest.values():
        detected.update(ingested.redacted_entities)
    extra = {entity: n - planted[entity] for entity, n in detected.items() if n > planted[entity]}
    probes = allowlist_probe_values()
    metrics: dict[str, Any] = {
        "planted_pii_removed": metric(
            len(truth) - len(leaked), len(truth), "planted value absent from the SQLite bytes"
        ),
        "extra_detections": metric(
            sum(extra.values()),
            sum(detected.values()),
            "redactions beyond the planted count, per entity type",
        ),
        "extra_detections_by_entity": extra,
        "leaked_by_entity": dict(Counter(t["entity"] for t in leaked)),
        "allowlist_values_stored": metric(
            sum(1 for v in probes if v.encode() in stored),
            len(probes),
            f"distinct {' and '.join(ALLOWLIST_PROBES)} values found in the SQLite bytes",
        ),
    }
    for language in sorted({t["language"] for t in truth}):
        subset = [t for t in truth if t["language"] == language]
        metrics[f"planted_pii_removed_{language}"] = metric(
            sum(1 for t in subset if t not in leaked), len(subset), "same, for one language"
        )
    if redactor is RedactorName.PRESIDIO:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        dataset = json.loads(report.out_path.read_text(encoding="utf-8"))
        jsonschema.validate(dataset, schema, cls=jsonschema.Draft202012Validator)
        metrics |= {
            "traces": metric(report.triage.traces, report.triage.traces, "records stored"),
            "intent_clusters": metric(
                report.triage.clusters, report.triage.traces, "HDBSCAN clusters, noise excluded"
            ),
            "flagged_traces": metric(
                report.triage.flagged, report.triage.traces, "traces with at least one flag"
            ),
            "review_candidates": metric(
                report.triage.enqueued, report.triage.traces, "candidates queued by triage"
            ),
            "cases_exported": metric(
                len(report.export.cases),
                report.triage.enqueued,
                "approved candidates written as schema v2, file valid against the copied schema",
            ),
            "duplicates_dropped": metric(
                len(report.export.skipped), report.triage.enqueued, "exact or near duplicates"
            ),
        }
    return metrics


def main() -> int:
    """Measure both redactor modes and write the manifest."""
    truth: list[dict[str, str]] = json.loads(
        (SAMPLES / "pii_ground_truth.json").read_text(encoding="utf-8")
    )
    settings = Settings()
    with tempfile.TemporaryDirectory() as tmp:
        runs = {
            mode.value: measure(mode, Path(tmp) / mode.value, truth)
            for mode in (RedactorName.PRESIDIO, RedactorName.REGEX)
        }
    manifest = {
        "date": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": git_commit(),
        "command": "uv run python scripts/reproduce.py",
        "python": platform.python_version(),
        "packages": {name: distribution_version(name) for name in PACKAGES},
        "models": {
            language: {"name": model, "version": distribution_version(model.replace("_", "-"))}
            for language, model in settings.spacy_models.items()
        },
        "seed": runpy.run_path(str(ROOT / "scripts" / "generate_samples.py"))["SEED"],
        "datasets": {
            str(path.relative_to(ROOT)): sha256(path)
            for path in [*sorted(SAMPLES.glob("*.json*")), SCHEMA]
            if path.is_relative_to(ROOT)
        },
        "hardware": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
        },
        "runs": runs,
    }
    MANIFEST.parent.mkdir(exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {MANIFEST.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
