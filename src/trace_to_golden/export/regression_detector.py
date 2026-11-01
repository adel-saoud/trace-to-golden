"""Export approved candidates to the llm-regression-detector golden dataset.

This module is the only place that knows the target format. Both schemas are
defined in llm-regression-detector/src/llm_regression_detector/eval/dataset.py,
and neither allows extra keys:

- v1: a bare JSON list of `GoldenCase` objects with `id`, `topic`, `input_text`,
  `expected_category` (required), `expected_summary_keywords`, `difficulty`
  and `notes`.
- v2: `{"schema_version": 2, "cases": [...]}` with at least one case. A case
  adds `reference_answer`, `rubric` (a list of pass or fail criteria) and
  `source` (a string map), and needs at least one of `expected_category`,
  `reference_answer` or `rubric`. Its JSON Schema is
  llm-regression-detector/schemas/golden-dataset.v2.schema.json.

v2 is the default because it keeps what a reviewer wrote: v1 has nowhere to put
the reference answer or the rubric.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

from trace_to_golden.dedupe import find_duplicates
from trace_to_golden.models import GoldenCandidate, ReviewStatus

CASE_ID_PREFIX = "ttg-"
"""Marks generated case ids, so they never collide with hand-written ones."""

SOURCE_ORIGIN = "trace-to-golden"
"""Value of `source.origin` (v2) and the start of `notes` (v1)."""

V2_SCHEMA_VERSION = 2
"""`schema_version` llm-regression-detector expects in a v2 file."""


class DatasetSchema(StrEnum):
    """Target dataset schema versions."""

    V1 = "v1"
    V2 = "v2"


@dataclass(frozen=True)
class ExportResult:
    """Cases written, and every approved candidate left out with the reason."""

    schema: DatasetSchema
    cases: list[dict[str, Any]]
    skipped: dict[str, str] = field(default_factory=dict[str, str])


def case_id(record_id: str) -> str:
    """Stable, short case id, so re-exporting the same trace gives the same id."""
    return CASE_ID_PREFIX + hashlib.sha256(record_id.encode()).hexdigest()[:12]


def load_existing_inputs(path: Path) -> list[str]:
    """`input_text` of every case in an existing v1 (bare list) or v2 (wrapper) dataset."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = cast(dict[str, Any], data).get("cases", [])
    cases = cast(list[dict[str, Any]], data)
    return [str(case["input_text"]) for case in cases if "input_text" in case]


def _flags_text(candidate: GoldenCandidate) -> str:
    """Flags as one string, because v2 `source` is a string map and v1 `notes` is text."""
    return ", ".join(candidate.flags) or "none"


def to_v1_case(candidate: GoldenCandidate) -> dict[str, Any]:
    """One `GoldenCase` (schema v1) dict; the caller checks `category` is set."""
    case: dict[str, Any] = {
        "id": case_id(candidate.record_id),
        "topic": candidate.topic,
        "input_text": candidate.input_text,
        "expected_category": candidate.category,
        "notes": f"{SOURCE_ORIGIN} from {candidate.record_id}; flags: {_flags_text(candidate)}",
    }
    return {k: v for k, v in case.items() if v is not None}


def to_v2_case(candidate: GoldenCandidate) -> dict[str, Any]:
    """One `GoldenCase` (schema v2) dict; the caller checks it has something to score.

    An empty traced answer becomes no `reference_answer`, since the judge would
    compare every answer against nothing.
    """
    case: dict[str, Any] = {
        "id": case_id(candidate.record_id),
        "topic": candidate.topic,
        "input_text": candidate.input_text,
        "expected_category": candidate.category,
        "reference_answer": candidate.reference_answer.strip() or None,
        "rubric": list(candidate.rubric) if candidate.rubric else None,
        "source": {
            "origin": SOURCE_ORIGIN,
            "trace": candidate.record_id,
            "flags": _flags_text(candidate),
        },
    }
    return {k: v for k, v in case.items() if v is not None}


def _missing_requirement(candidate: GoldenCandidate, schema: DatasetSchema) -> str | None:
    """Why `schema` would reject this candidate, or None when it can be written."""
    if schema is DatasetSchema.V1:
        return None if candidate.category else "schema v1 needs a category"
    if candidate.category or candidate.reference_answer.strip() or candidate.rubric:
        return None
    return "schema v2 needs a category, a reference answer or a rubric"


def export_candidates(
    candidates: list[GoldenCandidate],
    *,
    existing_inputs: list[str],
    dedupe_similarity_threshold: float,
    schema: DatasetSchema = DatasetSchema.V2,
) -> ExportResult:
    """Approved, deduplicated candidates converted to `schema`."""
    to_case = to_v2_case if schema is DatasetSchema.V2 else to_v1_case
    skipped: dict[str, str] = {}
    exportable: list[GoldenCandidate] = []
    for candidate in candidates:
        if candidate.status is not ReviewStatus.APPROVED:
            continue
        missing = _missing_requirement(candidate, schema)
        if missing is not None:
            skipped[candidate.record_id] = missing
        else:
            exportable.append(candidate)
    reasons = find_duplicates(
        [c.input_text for c in exportable],
        existing_inputs,
        threshold=dedupe_similarity_threshold,
    )
    cases: list[dict[str, Any]] = []
    for candidate, reason in zip(exportable, reasons, strict=True):
        if reason is not None:
            skipped[candidate.record_id] = reason
        else:
            cases.append(to_case(candidate))
    return ExportResult(schema=schema, cases=cases, skipped=skipped)


def write_dataset(result: ExportResult, path: Path) -> None:
    """Write the cases in the file shape llm-regression-detector loads for `result.schema`."""
    document: object = result.cases
    if result.schema is DatasetSchema.V2:
        document = {"schema_version": V2_SCHEMA_VERSION, "cases": result.cases}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
