from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trace_to_golden.ingest.mlflow_json import read_mlflow_file, trace_to_record
from trace_to_golden.models import TraceSource


def mlflow_trace(**info: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "trace_id": "tr-1",
        "request_preview": json.dumps({"question": "Can I return an item?"}),
        "response_preview": json.dumps("Yes, within 30 days."),
        "state": "OK",
        "request_time": "2026-10-01T09:00:00Z",
        "execution_duration_ms": 1200,
    }
    base.update(info)
    return {"info": base, "data": {"spans": []}}


def human_assessment(
    value: Any, rationale: str | None = None, source_type: str = "HUMAN"
) -> dict[str, Any]:
    return {
        "assessment_name": "user_satisfaction",
        "source": {"source_type": source_type, "source_id": "u"},
        "feedback": {"value": value},
        "rationale": rationale,
    }


def test_trace_maps_question_answer_timing_and_session():
    record = trace_to_record(mlflow_trace(client_request_id="session-1"))
    assert record is not None
    assert record.source is TraceSource.MLFLOW
    assert (record.input_text, record.output_text) == (
        "Can I return an item?",
        "Yes, within 30 days.",
    )
    assert record.latency_ms == 1200.0
    assert record.conversation_id == "session-1"
    assert record.start_time_unix_nano == 1_790_845_200_000_000_000
    assert record.error_type is None


def test_chat_shaped_previews():
    request = json.dumps(
        {"messages": [{"role": "system", "content": "x"}, {"role": "user", "content": "Hi?"}]}
    )
    response = json.dumps({"choices": [{"message": {"content": "Hello."}}]})
    record = trace_to_record(mlflow_trace(request_preview=request, response_preview=response))
    assert record is not None
    assert (record.input_text, record.output_text) == ("Hi?", "Hello.")


def test_plain_text_previews_and_output_key():
    record = trace_to_record(
        mlflow_trace(request_preview="not json", response_preview=json.dumps({"answer": "Yes."}))
    )
    assert record is not None
    assert (record.input_text, record.output_text) == ("not json", "Yes.")


def test_unusable_previews():
    assert trace_to_record(mlflow_trace(request_preview=json.dumps({"other": 1}))) is None
    assert trace_to_record(mlflow_trace(request_preview=None)) is None
    assert (
        trace_to_record(
            mlflow_trace(request_preview=json.dumps({"messages": [{"role": "system"}]}))
        )
        is None
    )
    record = trace_to_record(mlflow_trace(response_preview=json.dumps({"choices": ["x"]})))
    assert record is not None
    assert record.output_text == ""
    record = trace_to_record(mlflow_trace(response_preview=json.dumps([1])))
    assert record is not None
    assert record.output_text == ""


def test_error_state_and_bad_times():
    record = trace_to_record(
        mlflow_trace(state="ERROR", request_time="yesterday", execution_duration_ms=None)
    )
    assert record is not None
    assert record.error_type == "ERROR"
    assert record.start_time_unix_nano is None
    assert record.latency_ms is None
    record = trace_to_record(mlflow_trace(request_time=None))
    assert record is not None
    assert record.start_time_unix_nano is None


def test_feedback_keeps_worst_human_value():
    assessments = [
        human_assessment(True, "Helpful"),
        human_assessment(-0.5, "Meh"),
        human_assessment(False, "Wrong"),
        human_assessment(4, "five star scale is ignored"),
        human_assessment(False, source_type="LLM_JUDGE"),
        "not a dict",
        {"source": {"source_type": "HUMAN"}, "expectation": {"value": "x"}},
    ]
    record = trace_to_record(mlflow_trace(assessments=assessments))
    assert record is not None
    assert (record.feedback_score, record.feedback_comment) == (-1.0, "Wrong")
    record = trace_to_record(mlflow_trace(assessments=[human_assessment(0.5, None)]))
    assert record is not None
    assert (record.feedback_score, record.feedback_comment) == (0.5, None)


def test_read_json_array_lines_and_empty(tmp_path: Path):
    array = tmp_path / "a.json"
    array.write_text(
        json.dumps([mlflow_trace(), mlflow_trace(request_preview=None)]), encoding="utf-8"
    )
    assert len(read_mlflow_file(array)) == 1
    lines = tmp_path / "a.jsonl"
    lines.write_text(
        json.dumps(mlflow_trace()) + "\n" + json.dumps(mlflow_trace()) + "\n", encoding="utf-8"
    )
    assert len(read_mlflow_file(lines)) == 2
    empty = tmp_path / "e.jsonl"
    empty.write_text("\n", encoding="utf-8")
    assert read_mlflow_file(empty) == []


def test_bundled_samples_parse(samples: Path):
    records = read_mlflow_file(samples / "mlflow_traces.jsonl")
    assert len(records) == 15
    assert any(r.error_type == "ERROR" for r in records)
    assert any(r.feedback_score == -1.0 for r in records)
