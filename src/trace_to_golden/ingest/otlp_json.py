"""Parse OTLP/JSON trace exports into flat spans.

OTLP/JSON differs from the generic protobuf JSON mapping: trace and span ids
are hex strings (not base64), int64 values are decimal strings, and enums are
integers (https://opentelemetry.io/docs/specs/otlp/). That is why this module
uses small pydantic models instead of `google.protobuf.json_format`.

Accepted files: one `ExportTraceServiceRequest` JSON object, or newline-delimited
objects as written by the Collector file exporter (`format: json`).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

STATUS_CODE_ERROR = 2
"""`Status.code` value for ERROR in the OTLP proto (UNSET=0, OK=1, ERROR=2)."""

AttributeValue = str | int | float | bool | list[Any] | dict[str, Any] | None
"""A decoded OTLP `AnyValue`: arrays become lists, kvlists dicts, an empty value None."""


class _LenientOtlpModel(BaseModel):
    """Base for the OTLP models: unknown keys are ignored, so new OTLP fields never break
    parsing."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class KeyValue(_LenientOtlpModel):
    """One span attribute; `value` is the raw `AnyValue` JSON, see `decode_any_value`."""

    key: str
    value: dict[str, Any] = Field(default_factory=dict[str, Any])


class Status(_LenientOtlpModel):
    """Span status; only `STATUS_CODE_ERROR` is acted on."""

    code: int = 0
    message: str = ""


class Span(_LenientOtlpModel):
    """The span fields the GenAI mapper reads; int64 timestamps arrive as decimal strings."""

    trace_id: str = Field(alias="traceId")
    span_id: str = Field(alias="spanId")
    parent_span_id: str = Field(default="", alias="parentSpanId")
    start_time_unix_nano: int | None = Field(default=None, alias="startTimeUnixNano")
    end_time_unix_nano: int | None = Field(default=None, alias="endTimeUnixNano")
    attributes: list[KeyValue] = Field(default_factory=list[KeyValue])
    status: Status = Field(default_factory=Status)


class ScopeSpans(_LenientOtlpModel):
    """Spans from one instrumentation scope."""

    spans: list[Span] = Field(default_factory=list[Span])


class ResourceSpans(_LenientOtlpModel):
    """Spans from one resource; resource attributes are never read (allowlist)."""

    scope_spans: list[ScopeSpans] = Field(default_factory=list[ScopeSpans], alias="scopeSpans")


class ExportTraceServiceRequest(_LenientOtlpModel):
    """Top-level OTLP/JSON document: the whole file, or one line of a Collector export."""

    resource_spans: list[ResourceSpans] = Field(
        default_factory=list[ResourceSpans], alias="resourceSpans"
    )


def decode_any_value(value: dict[str, Any]) -> AttributeValue:
    """Turn an OTLP `AnyValue` JSON object into a plain Python value."""
    if "stringValue" in value:
        return cast(str, value["stringValue"])
    if "boolValue" in value:
        return bool(value["boolValue"])
    if "intValue" in value:
        return int(value["intValue"])
    if "doubleValue" in value:
        return float(value["doubleValue"])
    if "arrayValue" in value:
        items = cast(list[dict[str, Any]], value["arrayValue"].get("values", []))
        return [decode_any_value(item) for item in items]
    if "kvlistValue" in value:
        pairs = cast(list[dict[str, Any]], value["kvlistValue"].get("values", []))
        return {
            str(pair["key"]): decode_any_value(cast(dict[str, Any], pair.get("value", {})))
            for pair in pairs
        }
    return None


def span_attributes(span: Span) -> dict[str, AttributeValue]:
    """Attributes of a span as a plain dict."""
    return {kv.key: decode_any_value(kv.value) for kv in span.attributes}


def iter_spans(path: Path) -> Iterator[Span]:
    """Yield every span in an OTLP/JSON file or a newline-delimited OTLP/JSON file."""
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return
    try:
        documents = [json.loads(text)]
    except json.JSONDecodeError:
        documents = [json.loads(line) for line in text.splitlines() if line.strip()]
    for document in documents:
        request = ExportTraceServiceRequest.model_validate(document)
        for resource_spans in request.resource_spans:
            for scope_spans in resource_spans.scope_spans:
                yield from scope_spans.spans
