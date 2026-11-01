from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from conftest import otlp_attribute, otlp_document, write_otlp
from trace_to_golden.ingest.otel_genai import read_otel_file
from trace_to_golden.ingest.otlp_json import decode_any_value, iter_spans
from trace_to_golden.models import TraceSource

FEEDBACK_ATTRIBUTES = {
    "feedback_score_attribute": "user_feedback.score",
    "feedback_comment_attribute": "user_feedback.comment",
}


def messages(role: str, text: str) -> str:
    return json.dumps([{"role": role, "parts": [{"type": "text", "content": text}]}])


def otlp_span(span_id: str, attributes: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "traceId": "ABCDEF0123456789ABCDEF0123456789",
        "spanId": span_id,
        "startTimeUnixNano": "1000000000",
        "endTimeUnixNano": "2500000000",
        "attributes": attributes,
    }
    base.update(extra)
    return base


def genai_attributes(question: str = "Where is my order?") -> list[dict[str, Any]]:
    return [
        otlp_attribute("gen_ai.operation.name", "invoke_agent"),
        otlp_attribute("gen_ai.provider.name", "gcp.gemini"),
        otlp_attribute("gen_ai.request.model", "gemini-2.5-flash"),
        otlp_attribute("gen_ai.conversation.id", "conv-1"),
        otlp_attribute("gen_ai.input.messages", messages("user", question)),
        otlp_attribute("gen_ai.output.messages", messages("assistant", "It arrives in 3 days.")),
        otlp_attribute("gen_ai.usage.input_tokens", 300),
        otlp_attribute("gen_ai.usage.output_tokens", 40),
    ]


def test_decode_any_value_covers_every_type():
    assert decode_any_value({"stringValue": "a"}) == "a"
    assert decode_any_value({"boolValue": True}) is True
    assert decode_any_value({"intValue": "42"}) == 42
    assert decode_any_value({"doubleValue": 1.5}) == 1.5
    assert decode_any_value({"arrayValue": {"values": [{"intValue": "1"}]}}) == [1]
    kvlist = {"kvlistValue": {"values": [{"key": "k", "value": {"stringValue": "v"}}]}}
    assert decode_any_value(kvlist) == {"k": "v"}
    assert decode_any_value({}) is None


def test_iter_spans_reads_json_lines_and_empty_files(tmp_path: Path):
    lines = tmp_path / "batches.jsonl"
    doc = json.dumps(otlp_document([otlp_span("01", [])]))
    lines.write_text(f"{doc}\n{doc}\n", encoding="utf-8")
    assert len(list(iter_spans(lines))) == 2
    empty = tmp_path / "empty.json"
    empty.write_text("", encoding="utf-8")
    assert list(iter_spans(empty)) == []


def test_semconv_span_maps_to_record(tmp_path: Path):
    path = write_otlp(tmp_path / "t.json", [otlp_span("01", genai_attributes())])
    [record] = read_otel_file(path, **FEEDBACK_ATTRIBUTES)
    assert record.source is TraceSource.OTEL
    assert record.trace_id == "abcdef0123456789abcdef0123456789"
    assert record.input_text == "Where is my order?"
    assert record.output_text == "It arrives in 3 days."
    assert record.provider_name == "gcp.gemini"
    assert record.model == "gemini-2.5-flash"
    assert record.conversation_id == "conv-1"
    assert record.latency_ms == 1500.0
    assert (record.input_tokens, record.output_tokens) == (300, 40)
    assert record.error_type is None


def test_structured_messages_and_deprecated_system(tmp_path: Path):
    structured = {
        "key": "gen_ai.input.messages",
        "value": {
            "arrayValue": {
                "values": [
                    {
                        "kvlistValue": {
                            "values": [
                                {"key": "role", "value": {"stringValue": "user"}},
                                {
                                    "key": "parts",
                                    "value": {
                                        "arrayValue": {
                                            "values": [
                                                {
                                                    "kvlistValue": {
                                                        "values": [
                                                            {
                                                                "key": "type",
                                                                "value": {"stringValue": "text"},
                                                            },
                                                            {
                                                                "key": "content",
                                                                "value": {"stringValue": "Hi?"},
                                                            },
                                                        ]
                                                    }
                                                }
                                            ]
                                        }
                                    },
                                },
                            ]
                        }
                    }
                ]
            }
        },
    }
    attributes = [
        otlp_attribute("gen_ai.operation.name", "chat"),
        otlp_attribute("gen_ai.system", "openai"),
        structured,
    ]
    [record] = read_otel_file(
        write_otlp(tmp_path / "t.json", [otlp_span("01", attributes)]), **FEEDBACK_ATTRIBUTES
    )
    assert record.input_text == "Hi?"
    assert record.output_text == ""
    assert record.provider_name == "openai"


def test_legacy_indexed_attributes(tmp_path: Path):
    attributes = [
        otlp_attribute("gen_ai.operation.name", "chat"),
        otlp_attribute("gen_ai.prompt.0.role", "system"),
        otlp_attribute("gen_ai.prompt.0.content", "Be nice."),
        otlp_attribute("gen_ai.prompt.1.role", "user"),
        otlp_attribute("gen_ai.prompt.1.content", "Is the tent in stock?"),
        otlp_attribute("gen_ai.completion.0.content", "Yes."),
        otlp_attribute("gen_ai.usage.prompt_tokens", 12),
        otlp_attribute("gen_ai.usage.completion_tokens", 4.0),
    ]
    [record] = read_otel_file(
        write_otlp(tmp_path / "t.json", [otlp_span("01", attributes)]), **FEEDBACK_ATTRIBUTES
    )
    assert record.input_text == "Is the tent in stock?"
    assert record.output_text == "Yes."
    assert (record.input_tokens, record.output_tokens) == (12, 4)


def test_only_top_level_genai_span_and_trace_feedback(tmp_path: Path):
    root = otlp_span(
        "01",
        [
            otlp_attribute("user_feedback.score", -1.0),
            otlp_attribute("user_feedback.comment", "Wrong."),
            otlp_attribute("enduser.id", "u1"),
        ],
    )
    agent = otlp_span("02", genai_attributes(), parentSpanId="01")
    child = otlp_span("03", genai_attributes("inner prompt"), parentSpanId="02")
    [record] = read_otel_file(
        write_otlp(tmp_path / "t.json", [root, agent, child]), **FEEDBACK_ATTRIBUTES
    )
    assert record.span_id == "02"
    assert record.feedback_score == -1.0
    assert record.feedback_comment == "Wrong."
    assert "u1" not in record.model_dump_json()


def test_errors_from_status_and_error_type(tmp_path: Path):
    by_status = otlp_span("01", genai_attributes(), status={"code": 2, "message": "boom"})
    by_type = otlp_span(
        "02", [*genai_attributes(), otlp_attribute("error.type", "timeout")], traceId="11" * 16
    )
    no_message = otlp_span("03", genai_attributes(), traceId="22" * 16, status={"code": 2})
    path = write_otlp(tmp_path / "t.json", [by_status, by_type, no_message])
    errors = {r.span_id: r.error_type for r in read_otel_file(path, **FEEDBACK_ATTRIBUTES)}
    assert errors == {"01": "boom", "02": "timeout", "03": "error"}


def test_spans_without_user_input_are_skipped(tmp_path: Path):
    no_messages = otlp_span("01", [otlp_attribute("gen_ai.operation.name", "chat")])
    bad_json = otlp_span(
        "02",
        [
            otlp_attribute("gen_ai.operation.name", "chat"),
            otlp_attribute("gen_ai.input.messages", "{not json"),
        ],
        traceId="11" * 16,
    )
    not_a_list = otlp_span(
        "03",
        [
            otlp_attribute("gen_ai.operation.name", "chat"),
            otlp_attribute("gen_ai.input.messages", '{"role": "user"}'),
        ],
        traceId="22" * 16,
    )
    no_times = otlp_span(
        "04", [otlp_attribute("gen_ai.usage.input_tokens", True)], traceId="33" * 16
    )
    path = write_otlp(tmp_path / "t.json", [no_messages, bad_json, not_a_list, no_times])
    assert read_otel_file(path, **FEEDBACK_ATTRIBUTES) == []


def test_missing_timestamps_and_odd_token_types(tmp_path: Path):
    attributes = [
        *genai_attributes()[:6],
        otlp_attribute("gen_ai.usage.input_tokens", True),
        otlp_attribute("gen_ai.usage.output_tokens", "x"),
    ]
    raw = otlp_span("01", attributes)
    del raw["startTimeUnixNano"]
    [record] = read_otel_file(write_otlp(tmp_path / "t.json", [raw]), **FEEDBACK_ATTRIBUTES)
    assert record.latency_ms is None
    assert (record.input_tokens, record.output_tokens) == (None, None)


def test_bundled_samples_parse(samples: Path):
    records = read_otel_file(samples / "otel_traces.jsonl", **FEEDBACK_ATTRIBUTES)
    assert len(records) == 87
    assert any(r.input_text.startswith("Bonjour") for r in records)
    assert any(r.error_type for r in records)
    assert any(r.feedback_score == -1.0 for r in records)
    assert any(r.provider_name == "ollama" for r in records)
