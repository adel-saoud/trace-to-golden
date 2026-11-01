"""Map exported MLflow 3 traces to `TraceRecord`, without importing MLflow.

Expected input: what `Trace.to_json()` writes (`{"info": ..., "data": ...}`),
either one JSON array of traces or one trace per line. Export with:

    traces = mlflow.search_traces(return_type="list")
    Path("traces.jsonl").write_text("\\n".join(t.to_json() for t in traces))

Field names follow `TraceInfo.to_dict()` in MLflow 3 (snake_case,
`execution_duration_ms`, `request_time` as an RFC 3339 string) and
`Assessment.to_dictionary()` (`assessment_name`, `source.source_type`,
`feedback.value`). Only `info` is read: `request_preview` and
`response_preview` hold the JSON-encoded root span input and output, which
MLflow may truncate on very long requests.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from trace_to_golden.models import TraceRecord, TraceSource

INPUT_KEYS = ("question", "query", "input", "prompt", "request", "message")
"""Keys tried, in order, for the question in a dict-shaped root span input."""

OUTPUT_KEYS = ("answer", "response", "output", "content", "text")
"""Keys tried, in order, for the answer in a dict-shaped root span output."""


def _decode_preview(preview: str | None) -> object:
    """JSON-decoded preview; a preview that is not JSON is returned as plain text."""
    if not preview:
        return None
    try:
        return json.loads(preview)
    except json.JSONDecodeError:
        return preview


def _last_user_message(messages: list[Any]) -> str | None:
    """Content of the last `user` message: the turn the trace answered."""
    texts = [
        str(cast(dict[str, Any], m).get("content", ""))
        for m in messages
        if isinstance(m, dict) and cast(dict[str, Any], m).get("role") == "user"
    ]
    return texts[-1] if texts else None


def _input_text(preview: object) -> str:
    """User question from a decoded request preview, or "" when none is found.

    Root span inputs have no fixed shape: a chat payload gives its last user
    message, a dict gives the first string under `INPUT_KEYS` (in that order),
    and a plain string is the question itself.
    """
    if isinstance(preview, str):
        return preview
    if isinstance(preview, dict):
        payload = cast(dict[str, Any], preview)
        messages = payload.get("messages")
        if isinstance(messages, list):
            text = _last_user_message(cast(list[Any], messages))
            if text:
                return text
        for key in INPUT_KEYS:
            if isinstance(payload.get(key), str):
                return str(payload[key])
    return ""


def _output_text(preview: object) -> str:
    """Answer from a decoded response preview, or "" when none is found.

    Reads the first choice of an OpenAI-style chat completion, then the first
    string under `OUTPUT_KEYS`. An empty answer keeps the trace: a failed call
    is still worth a review.
    """
    if isinstance(preview, str):
        return preview
    if isinstance(preview, dict):
        payload = cast(dict[str, Any], preview)
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            first = cast(list[Any], choices)[0]
            if isinstance(first, dict):
                message = cast(dict[str, Any], first).get("message", {})
                if isinstance(message, dict):
                    return str(cast(dict[str, Any], message).get("content", ""))
        for key in OUTPUT_KEYS:
            if isinstance(payload.get(key), str):
                return str(payload[key])
    return ""


def _worst_human_feedback(assessments: list[Any]) -> tuple[float | None, str | None]:
    """Worst human feedback on the trace.

    Booleans map to 1.0 / -1.0; numbers are kept only inside [-1.0, 1.0], so a
    1 to 5 rating scale is ignored rather than misread.
    """
    worst: tuple[float, str | None] | None = None
    for raw in assessments:
        if not isinstance(raw, dict):
            continue
        assessment = cast(dict[str, Any], raw)
        source = cast(dict[str, Any], assessment.get("source", {}))
        feedback = assessment.get("feedback")
        if source.get("source_type") != "HUMAN" or not isinstance(feedback, dict):
            continue
        value = cast(dict[str, Any], feedback).get("value")
        if isinstance(value, bool):
            score = 1.0 if value else -1.0
        elif isinstance(value, int | float) and -1.0 <= value <= 1.0:
            score = float(value)
        else:
            continue
        rationale = assessment.get("rationale")
        if worst is None or score < worst[0]:
            worst = (score, rationale if isinstance(rationale, str) else None)
    return (worst[0], worst[1]) if worst else (None, None)


def _request_time_nano(value: object) -> int | None:
    """RFC 3339 `request_time` as Unix nanoseconds, matching OTLP span timestamps."""
    if not isinstance(value, str):
        return None
    try:
        return int(datetime.fromisoformat(value).timestamp() * 1_000_000_000)
    except ValueError:
        return None


def trace_to_record(trace: dict[str, Any]) -> TraceRecord | None:
    """Convert one MLflow trace dict; None when it has no user input."""
    info = cast(dict[str, Any], trace.get("info", {}))
    input_text = _input_text(_decode_preview(info.get("request_preview")))
    if not input_text:
        return None
    score, comment = _worst_human_feedback(cast(list[Any], info.get("assessments", [])))
    duration = info.get("execution_duration_ms")
    state = info.get("state")
    trace_id = str(info.get("trace_id", ""))
    return TraceRecord(
        trace_id=trace_id,
        span_id="root",
        source=TraceSource.MLFLOW,
        input_text=input_text,
        output_text=_output_text(_decode_preview(info.get("response_preview"))),
        conversation_id=info.get("client_request_id"),
        start_time_unix_nano=_request_time_nano(info.get("request_time")),
        latency_ms=float(duration) if isinstance(duration, int | float) else None,
        error_type="ERROR" if state == "ERROR" else None,
        feedback_score=score,
        feedback_comment=comment,
    )


def read_mlflow_file(path: Path) -> list[TraceRecord]:
    """Read a JSON array or JSON-lines file of exported MLflow traces."""
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("["):
        traces = cast(list[dict[str, Any]], json.loads(text))
    else:
        traces = [cast(dict[str, Any], json.loads(line)) for line in text.splitlines() if line]
    return [record for trace in traces if (record := trace_to_record(trace)) is not None]
