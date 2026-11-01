from __future__ import annotations

import json
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from typing import Any

import pytest

from trace_to_golden.config import RedactorName, Settings
from trace_to_golden.models import RedactedTrace, TraceRecord, TraceSource
from trace_to_golden.redact import Redactor, build_redactor
from trace_to_golden.redact.regex import RegexRedactor
from trace_to_golden.store import Store

SAMPLES = Path(str(resources.files("trace_to_golden.samples") / "data"))


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(db_path=tmp_path / "test.db", redactor=RedactorName.REGEX)


@pytest.fixture
def store(settings: Settings) -> Store:
    return Store(settings.db_path)


@pytest.fixture
def regex_redactor() -> RegexRedactor:
    return RegexRedactor()


@pytest.fixture(scope="session")
def presidio_redactor() -> Redactor:
    return build_redactor(Settings(redactor=RedactorName.PRESIDIO))


@pytest.fixture
def samples() -> Path:
    return SAMPLES


def make_record(**overrides: Any) -> TraceRecord:
    values: dict[str, Any] = {
        "trace_id": "t1",
        "span_id": "s1",
        "source": TraceSource.OTEL,
        "input_text": "Where is my order?",
        "output_text": "It arrives in 3 days.",
    }
    values.update(overrides)
    return TraceRecord.model_validate(values)


def make_trace(**overrides: Any) -> RedactedTrace:
    return RedactedTrace(record=make_record(**overrides), redactor_name="regex")


@pytest.fixture
def record_factory() -> Callable[..., TraceRecord]:
    return make_record


@pytest.fixture
def trace_factory() -> Callable[..., RedactedTrace]:
    return make_trace


def otlp_attribute(key: str, value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        encoded: dict[str, Any] = {"boolValue": value}
    elif isinstance(value, int):
        encoded = {"intValue": str(value)}
    elif isinstance(value, float):
        encoded = {"doubleValue": value}
    else:
        encoded = {"stringValue": value}
    return {"key": key, "value": encoded}


def otlp_document(spans: list[dict[str, Any]]) -> dict[str, Any]:
    return {"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]}


def write_otlp(path: Path, spans: list[dict[str, Any]]) -> Path:
    path.write_text(json.dumps(otlp_document(spans)), encoding="utf-8")
    return path
