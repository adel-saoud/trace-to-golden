"""Map OpenTelemetry GenAI spans to `TraceRecord`.

Every semantic-convention name lives in this module, because the GenAI
conventions are still at Development status and moved to their own repository
(github.com/open-telemetry/semantic-conventions-genai) with no release yet.

Two attribute layouts are read:

- `SEMCONV_1_37`: the layout verified against semconv v1.37.0
  (`gen_ai.input.messages` / `gen_ai.output.messages`, each a JSON string or a
  structured list of `{"role", "parts": [{"type": "text", "content"}]}`).
- `LEGACY_INDEXED`: the flat `gen_ai.prompt.{i}.content` /
  `gen_ai.completion.{i}.content` layout emitted by older instrumentations.
  UNVERIFIED against any spec; kept because many existing exporters still use it.

One record is built per top-most GenAI span (a span carrying
`gen_ai.operation.name` whose parent is not itself a GenAI span), so an agent
span and its nested model calls produce one record, not several.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

from trace_to_golden.ingest.otlp_json import (
    STATUS_CODE_ERROR,
    AttributeValue,
    Span,
    iter_spans,
    span_attributes,
)
from trace_to_golden.models import TraceRecord, TraceSource

OPERATION_NAME = "gen_ai.operation.name"
PROVIDER_NAME = "gen_ai.provider.name"
DEPRECATED_SYSTEM = "gen_ai.system"
"""Deprecated name of `gen_ai.provider.name`, read as a fallback for older instrumentations."""

REQUEST_MODEL = "gen_ai.request.model"
RESPONSE_MODEL = "gen_ai.response.model"
CONVERSATION_ID = "gen_ai.conversation.id"
INPUT_TOKENS = "gen_ai.usage.input_tokens"
OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
INPUT_MESSAGES = "gen_ai.input.messages"
OUTPUT_MESSAGES = "gen_ai.output.messages"
ERROR_TYPE = "error.type"
"""General semconv attribute, set by GenAI instrumentations when a call fails."""

LEGACY_PROMPT = re.compile(r"^gen_ai\.prompt\.(\d+)\.(role|content)$")
"""`gen_ai.prompt.{i}.role|content`; group 1 is the message index, group 2 the field."""

LEGACY_COMPLETION = re.compile(r"^gen_ai\.completion\.(\d+)\.(role|content)$")
LEGACY_INPUT_TOKENS = "gen_ai.usage.prompt_tokens"
LEGACY_OUTPUT_TOKENS = "gen_ai.usage.completion_tokens"


def _as_str(value: AttributeValue) -> str | None:
    """The value if it is a string, else None."""
    return value if isinstance(value, str) else None


def _as_int(value: AttributeValue) -> int | None:
    """A token count from an int or float attribute; booleans are not counts."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _as_float(value: AttributeValue) -> float | None:
    """A numeric attribute as float; booleans are rejected, since `bool` subclasses `int`."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _load_messages(value: AttributeValue) -> list[dict[str, Any]]:
    """Accept the JSON-string and the structured forms of a messages attribute."""
    if isinstance(value, str):
        try:
            value = cast(AttributeValue, json.loads(value))
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    return [cast(dict[str, Any], item) for item in value if isinstance(item, dict)]


def _message_text(message: dict[str, Any]) -> str:
    """Text parts of one semconv message joined by newlines; tool calls and media are skipped."""
    parts = cast(list[Any], message.get("parts", []))
    texts = [
        str(cast(dict[str, Any], part).get("content", ""))
        for part in parts
        if isinstance(part, dict) and cast(dict[str, Any], part).get("type") == "text"
    ]
    return "\n".join(text for text in texts if text)


def _semconv_texts(attributes: dict[str, AttributeValue]) -> tuple[str, str] | None:
    """(last user turn, assistant answer) from the v1.37 layout, or None if it is absent."""
    if INPUT_MESSAGES not in attributes and OUTPUT_MESSAGES not in attributes:
        return None
    inputs = _load_messages(attributes.get(INPUT_MESSAGES))
    outputs = _load_messages(attributes.get(OUTPUT_MESSAGES))
    user_turns = [_message_text(m) for m in inputs if m.get("role") == "user"]
    answers = [_message_text(m) for m in outputs if m.get("role", "assistant") == "assistant"]
    return (user_turns[-1] if user_turns else "", "\n".join(a for a in answers if a))


def _legacy_texts(attributes: dict[str, AttributeValue]) -> tuple[str, str] | None:
    """(last user turn, answer) from the legacy indexed layout, or None if it is absent."""
    prompts: dict[int, dict[str, str]] = defaultdict(dict)
    completions: dict[int, dict[str, str]] = defaultdict(dict)
    for key, value in attributes.items():
        for pattern, target in ((LEGACY_PROMPT, prompts), (LEGACY_COMPLETION, completions)):
            match = pattern.match(key)
            if match and isinstance(value, str):
                target[int(match.group(1))][match.group(2)] = value
    if not prompts and not completions:
        return None
    user_turns = [
        prompts[i].get("content", "")
        for i in sorted(prompts)
        if prompts[i].get("role", "user") == "user"
    ]
    answers = [completions[i].get("content", "") for i in sorted(completions)]
    return (user_turns[-1] if user_turns else "", "\n".join(a for a in answers if a))


def _top_level_genai_spans(spans: list[Span]) -> list[Span]:
    """GenAI spans whose parent is not a GenAI span, so nested model calls are not counted."""
    genai_ids = {
        span.span_id for span in spans if any(kv.key == OPERATION_NAME for kv in span.attributes)
    }
    return [
        span for span in spans if span.span_id in genai_ids and span.parent_span_id not in genai_ids
    ]


def _trace_feedback(
    spans: list[Span], score_attribute: str, comment_attribute: str
) -> tuple[float | None, str | None]:
    """Feedback may sit on any span of the trace (often the HTTP root span)."""
    score: float | None = None
    comment: str | None = None
    for span in spans:
        attributes = span_attributes(span)
        score = score if score is not None else _as_float(attributes.get(score_attribute))
        comment = comment or _as_str(attributes.get(comment_attribute))
    return score, comment


def spans_to_records(
    spans: list[Span],
    *,
    feedback_score_attribute: str,
    feedback_comment_attribute: str,
) -> Iterator[TraceRecord]:
    """Build one `TraceRecord` per top-most GenAI span, grouping spans by trace."""
    by_trace: dict[str, list[Span]] = defaultdict(list)
    for span in spans:
        by_trace[span.trace_id.lower()].append(span)
    for trace_id, trace_spans in by_trace.items():
        score, comment = _trace_feedback(
            trace_spans, feedback_score_attribute, feedback_comment_attribute
        )
        for span in _top_level_genai_spans(trace_spans):
            attributes = span_attributes(span)
            texts = _semconv_texts(attributes) or _legacy_texts(attributes)
            if texts is None or not texts[0]:
                continue
            latency_ms = None
            if span.start_time_unix_nano is not None and span.end_time_unix_nano is not None:
                latency_ms = (span.end_time_unix_nano - span.start_time_unix_nano) / 1_000_000
            error_type = _as_str(attributes.get(ERROR_TYPE))
            if error_type is None and span.status.code == STATUS_CODE_ERROR:
                error_type = span.status.message or "error"
            yield TraceRecord(
                trace_id=trace_id,
                span_id=span.span_id.lower(),
                source=TraceSource.OTEL,
                input_text=texts[0],
                output_text=texts[1],
                conversation_id=_as_str(attributes.get(CONVERSATION_ID)),
                operation_name=_as_str(attributes.get(OPERATION_NAME)),
                provider_name=_as_str(attributes.get(PROVIDER_NAME))
                or _as_str(attributes.get(DEPRECATED_SYSTEM)),
                model=_as_str(attributes.get(RESPONSE_MODEL))
                or _as_str(attributes.get(REQUEST_MODEL)),
                start_time_unix_nano=span.start_time_unix_nano,
                latency_ms=latency_ms,
                input_tokens=_as_int(attributes.get(INPUT_TOKENS))
                or _as_int(attributes.get(LEGACY_INPUT_TOKENS)),
                output_tokens=_as_int(attributes.get(OUTPUT_TOKENS))
                or _as_int(attributes.get(LEGACY_OUTPUT_TOKENS)),
                error_type=error_type,
                feedback_score=score,
                feedback_comment=comment,
            )


def read_otel_file(
    path: Path,
    *,
    feedback_score_attribute: str,
    feedback_comment_attribute: str,
) -> list[TraceRecord]:
    """Read an OTLP/JSON export and return its GenAI records."""
    return list(
        spans_to_records(
            list(iter_spans(path)),
            feedback_score_attribute=feedback_score_attribute,
            feedback_comment_attribute=feedback_comment_attribute,
        )
    )
