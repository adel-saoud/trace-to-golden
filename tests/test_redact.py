from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from trace_to_golden import pipeline
from trace_to_golden.config import RedactorName, Settings
from trace_to_golden.models import TraceRecord, TraceSource
from trace_to_golden.redact import ChainRedactor, Redactor, build_redactor, redact_record
from trace_to_golden.redact.regex import RegexRedactor, iban_valid, luhn_valid
from trace_to_golden.samples import DEMO_REDACTION_PATTERNS
from trace_to_golden.store import Store


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("mail maria.lopez@example.com now", "mail <EMAIL_ADDRESS> now"),
        ("card 4111 1111 1111 1111.", "card <CREDIT_CARD>."),
        ("iban GB82 WEST 1234 5698 7654 32 ok", "iban <IBAN_CODE> ok"),
        ("from 192.168.1.20 today", "from <IP_ADDRESS> today"),
        ("call +1 555 0142 3377 please", "call <PHONE_NUMBER> please"),
        ("appelez le 06 39 98 12 34 svp", "appelez le <PHONE_NUMBER> svp"),
        ("call +971 50 555 0142 now", "call <PHONE_NUMBER> now"),
        ("J'habite au 12 rue de Rivoli, 75001 Paris.", "J'habite au <STREET_ADDRESS>."),
        ("Livrez au 7 bis avenue Jean Jaurès demain", "Livrez au <STREET_ADDRESS>"),
        ("I live at 221 Baker Street, London.", "I live at <STREET_ADDRESS>, London."),
    ],
)
def test_regex_redacts_structured_identifiers(
    regex_redactor: RegexRedactor, text: str, expected: str
):
    redacted, counts = regex_redactor.redact(text)
    assert redacted == expected
    assert sum(counts.values()) == 1


@pytest.mark.parametrize(
    "text",
    [
        "order 1234 5678 9012 3456",  # fails Luhn
        "after 2 years and 25 days",  # too few digits for a phone
        "ticket 2026-10-01",
        "La tente 2 places est-elle en stock ?",  # "places", not the street word "place"
        "I want 3 Large Shirts",  # no street word
    ],
)
def test_regex_leaves_lookalikes(regex_redactor: RegexRedactor, text: str):
    assert regex_redactor.redact(text) == (text, {})


def test_invalid_iban_is_not_labelled_iban(regex_redactor: RegexRedactor):
    """Its long digit run is still masked as a phone number: over-redaction is the safe side."""
    text, counts = regex_redactor.redact("code GB00 WEST 1234 5698 7654 32")
    assert "IBAN_CODE" not in counts
    assert "5698" not in text


def test_luhn_and_iban_checksums():
    assert luhn_valid("5555 5555 5555 4444")
    assert not luhn_valid("4111")
    assert iban_valid("DE89 3704 0044 0532 0130 00")
    assert not iban_valid("DE00 3704 0044 0532 0130 00")


def test_extra_pattern_redacts_custom_entity():
    redactor = RegexRedactor(extra_patterns={"ORDER_ID": r"\bCMD-\d{8}\b"})
    assert redactor.name == "regex"
    assert redactor.redact("order CMD-48213977") == ("order <ORDER_ID>", {"ORDER_ID": 1})


def test_presidio_finds_names_and_keeps_durations(presidio_redactor: Redactor):
    text, counts = presidio_redactor.redact(
        "Hi, I'm Maria Lopez. Can I still return shoes after 2 weeks?"
    )
    assert "Maria" not in text
    assert "after 2 weeks" in text
    assert counts["PERSON"] == 1
    assert presidio_redactor.name == "regex+presidio"
    assert presidio_redactor.redact("") == ("", {})


def test_presidio_in_french(presidio_redactor: Redactor):
    text, counts = presidio_redactor.redact(
        "Bonjour, je suis Camille Dubois. Ma livraison est en retard, que faire ?"
    )
    assert "Camille" not in text
    assert "Ma livraison est en retard" in text
    assert counts["PERSON"] == 1


def test_presidio_leaves_regex_placeholders_alone():
    redactor = build_redactor(Settings(extra_redaction_patterns={"ORDER_ID": r"\bCMD-\d{8}\b"}))
    text, _ = redactor.redact("Où est ma commande CMD-48213977 ?")
    assert text == "Où est ma commande <ORDER_ID> ?"


def test_build_redactor_light_mode():
    assert build_redactor(Settings(redactor=RedactorName.REGEX)).name == "regex"


def test_chain_redactor_sums_counts(regex_redactor: RegexRedactor):
    chain = ChainRedactor([regex_redactor, RegexRedactor({"CODE": r"X-\d"})])
    text, counts = chain.redact("a@example.com X-1")
    assert text == "<EMAIL_ADDRESS> <CODE>"
    assert counts == {"EMAIL_ADDRESS": 1, "CODE": 1}
    assert chain.name == "regex+regex"


def test_redact_record_covers_every_text_field(
    regex_redactor: RegexRedactor, record_factory: Callable[..., TraceRecord]
):
    record = record_factory(
        input_text="me: a@example.com",
        output_text="reply to b@example.com",
        feedback_comment="call +1 555 0199 2041",
    )
    redacted = redact_record(record, regex_redactor)
    assert redacted.record.input_text == "me: <EMAIL_ADDRESS>"
    assert redacted.record.output_text == "reply to <EMAIL_ADDRESS>"
    assert redacted.record.feedback_comment == "call <PHONE_NUMBER>"
    assert redacted.redacted_entity_counts == {"EMAIL_ADDRESS": 2, "PHONE_NUMBER": 1}
    assert redact_record(record_factory(), regex_redactor).record.feedback_comment is None


def _ingest_samples(samples: Path, settings: Settings) -> bytes:
    store = Store(settings.db_path)
    redactor = build_redactor(settings)
    pipeline.ingest(
        [samples / "otel_traces.jsonl"],
        TraceSource.OTEL,
        store=store,
        redactor=redactor,
        settings=settings,
    )
    pipeline.ingest(
        [samples / "mlflow_traces.jsonl"],
        TraceSource.MLFLOW,
        store=store,
        redactor=redactor,
        settings=settings,
    )
    return settings.db_path.read_bytes()


def test_no_planted_pii_reaches_the_store(samples: Path, tmp_path: Path):
    """The redaction promise, checked on the raw SQLite bytes, in English and French."""
    settings = Settings(
        db_path=tmp_path / "p.db",
        redactor=RedactorName.PRESIDIO,
        extra_redaction_patterns=DEMO_REDACTION_PATTERNS,
    )
    raw = _ingest_samples(samples, settings)
    truth = json.loads((samples / "pii_ground_truth.json").read_text(encoding="utf-8"))
    assert {t["language"] for t in truth} == {"en", "fr"}
    leaked = [t["text"] for t in truth if t["text"].encode() in raw]
    assert leaked == []
    # url.full and enduser.id on the root span are dropped by the allowlist.
    assert b"example.com" not in raw
    assert b"cust-" not in raw


def test_regex_light_mode_misses_names(samples: Path, tmp_path: Path):
    settings = Settings(
        db_path=tmp_path / "r.db",
        redactor=RedactorName.REGEX,
        extra_redaction_patterns=DEMO_REDACTION_PATTERNS,
    )
    raw = _ingest_samples(samples, settings)
    truth = json.loads((samples / "pii_ground_truth.json").read_text(encoding="utf-8"))
    leaked = {t["entity"] for t in truth if t["text"].encode() in raw}
    assert leaked == {"PERSON"}
