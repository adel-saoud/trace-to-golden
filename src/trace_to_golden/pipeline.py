"""The pipeline steps the CLI exposes (ingest, triage, export) and the offline demo run."""

from __future__ import annotations

import shutil
from collections import Counter
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from trace_to_golden import review
from trace_to_golden.config import Settings
from trace_to_golden.export.regression_detector import (
    DatasetSchema,
    ExportResult,
    export_candidates,
    load_existing_inputs,
    write_dataset,
)
from trace_to_golden.ingest.mlflow_json import read_mlflow_file
from trace_to_golden.ingest.otel_genai import read_otel_file
from trace_to_golden.language import clustering_stop_words
from trace_to_golden.models import GoldenCandidate, ReviewStatus, TraceRecord, TraceSource
from trace_to_golden.redact import Redactor, build_redactor, redact_record
from trace_to_golden.samples import DEMO_REDACTION_PATTERNS
from trace_to_golden.store import Store
from trace_to_golden.triage import candidates_from_triage, triage_traces


@dataclass(frozen=True)
class IngestReport:
    """What one ingest run read, stored and redacted."""

    records_read: int
    records_new: int
    redacted_entities: Counter[str] = field(default_factory=Counter[str])


@dataclass(frozen=True)
class TriageReport:
    """How many traces were triaged and how many new candidates were queued."""

    traces: int
    clusters: int
    flagged: int
    enqueued: int


def read_records(path: Path, source: TraceSource, settings: Settings) -> list[TraceRecord]:
    """Parse one export file with the ingester for `source`."""
    if source is TraceSource.MLFLOW:
        return read_mlflow_file(path)
    return read_otel_file(
        path,
        feedback_score_attribute=settings.feedback_score_attribute,
        feedback_comment_attribute=settings.feedback_comment_attribute,
    )


def ingest(
    paths: list[Path],
    source: TraceSource,
    *,
    store: Store,
    redactor: Redactor,
    settings: Settings,
) -> IngestReport:
    """Read, redact, then store. Raw text never reaches the store."""
    records = [record for path in paths for record in read_records(path, source, settings)]
    redacted = [redact_record(record, redactor) for record in records]
    counts: Counter[str] = Counter()
    for trace in redacted:
        counts.update(trace.redacted_entity_counts)
    return IngestReport(
        records_read=len(records),
        records_new=store.add_traces(redacted),
        redacted_entities=counts,
    )


def triage(store: Store, settings: Settings) -> TriageReport:
    """Cluster and flag every stored trace, then queue new candidates."""
    traces = store.traces()
    results = triage_traces(
        traces,
        min_cluster_size=settings.min_cluster_size,
        outlier_z_threshold=settings.outlier_z_threshold,
        stop_words=clustering_stop_words(list(settings.spacy_models)),
    )
    enqueued = store.enqueue(candidates_from_triage(traces, results))
    return TriageReport(
        traces=len(traces),
        clusters=len({t.cluster_id for t in results if t.cluster_id >= 0}),
        flagged=sum(1 for t in results if t.flags),
        enqueued=enqueued,
    )


def export(
    store: Store,
    settings: Settings,
    *,
    out_path: Path,
    existing_dataset: Path | None,
    schema: DatasetSchema = DatasetSchema.V2,
) -> ExportResult:
    """Write approved, deduplicated cases to `out_path`.

    Nothing is written when no case is left, because schema v2 rejects a file
    with no cases and an empty v1 file would only hide that from a CI gate.
    """
    existing = load_existing_inputs(existing_dataset) if existing_dataset else []
    result = export_candidates(
        store.candidates(),
        existing_inputs=existing,
        dedupe_similarity_threshold=settings.dedupe_similarity_threshold,
        schema=schema,
    )
    if result.cases:
        write_dataset(result, out_path)
    return result


DEMO_SOURCES = (
    ("otel_traces.jsonl", TraceSource.OTEL),
    ("mlflow_traces.jsonl", TraceSource.MLFLOW),
)
"""Bundled sample files and their formats, ingested in this order by the demo."""


@dataclass(frozen=True)
class DemoReport:
    """Everything one demo run produced, for the CLI to print and reproduce.py to measure."""

    ingest: dict[str, IngestReport]
    triage: TriageReport
    queued: list[GoldenCandidate]
    export: ExportResult
    out_path: Path


def run_demo(workdir: Path, settings: Settings) -> DemoReport:
    """Run every step on the bundled synthetic traces in a fresh `workdir`.

    Candidates are auto-approved with the first term of their cluster topic as
    category, which a person does by hand in real use. The sample order ids
    (`CMD-12345678`) are added to the redaction patterns, as a shop would set its
    own format through `TTG_EXTRA_REDACTION_PATTERNS`.
    """
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)
    settings = settings.model_copy(
        update={
            "db_path": workdir / "demo.db",
            "extra_redaction_patterns": DEMO_REDACTION_PATTERNS | settings.extra_redaction_patterns,
        }
    )
    data = resources.files("trace_to_golden.samples") / "data"
    store = Store(settings.db_path)
    redactor = build_redactor(settings)
    ingest_reports: dict[str, IngestReport] = {}
    for name, source in DEMO_SOURCES:
        with resources.as_file(data / name) as path:
            ingest_reports[name] = ingest(
                [path], source, store=store, redactor=redactor, settings=settings
            )
    triage_report = triage(store, settings)
    queued = store.candidates()
    for candidate in store.candidates(ReviewStatus.PENDING):
        topic = (candidate.topic or "uncategorized").split(",")[0]
        review.approve(store, candidate.record_id, category=topic)
    out_path = workdir / "golden.json"
    with resources.as_file(data / "existing_golden.json") as existing:
        result = export(store, settings, out_path=out_path, existing_dataset=existing)
    return DemoReport(
        ingest=ingest_reports, triage=triage_report, queued=queued, export=result, out_path=out_path
    )
