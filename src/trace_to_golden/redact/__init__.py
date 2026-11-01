"""PII redaction. `redact_record` is the only way to build a `RedactedTrace`."""

from __future__ import annotations

from collections import Counter
from typing import Protocol

from trace_to_golden.config import RedactorName, Settings
from trace_to_golden.models import RedactedTrace, TraceRecord


class Redactor(Protocol):
    """Replaces PII spans in text with `<ENTITY_TYPE>` placeholders."""

    @property
    def name(self) -> str:
        """Identifier stored with every redacted record."""
        ...

    def redact(self, text: str) -> tuple[str, Counter[str]]:
        """Return the redacted text and how many entities of each type were removed."""
        ...


class ChainRedactor:
    """Runs redactors in order; later ones see the earlier ones' placeholders."""

    def __init__(self, redactors: list[Redactor]) -> None:
        """Keep the redactors in the order they must run."""
        self._redactors = redactors

    @property
    def name(self) -> str:
        """Joined names, e.g. `presidio+regex`."""
        return "+".join(r.name for r in self._redactors)

    def redact(self, text: str) -> tuple[str, Counter[str]]:
        """Apply each redactor in turn and sum their counts."""
        counts: Counter[str] = Counter()
        for redactor in self._redactors:
            text, found = redactor.redact(text)
            counts.update(found)
        return text, counts


def build_redactor(settings: Settings) -> Redactor:
    """Regex then Presidio (NER) by default; regex alone in light mode.

    Regex runs first so whole street addresses and team patterns are replaced
    before Presidio splits them into smaller LOCATION spans.
    """
    from trace_to_golden.redact.regex import RegexRedactor

    regex = RegexRedactor(extra_patterns=settings.extra_redaction_patterns)
    if settings.redactor is RedactorName.REGEX:
        return regex
    from trace_to_golden.language import StopWordLanguageDetector
    from trace_to_golden.redact.presidio import PresidioRedactor

    presidio = PresidioRedactor(
        spacy_models=settings.spacy_models,
        detector=StopWordLanguageDetector(list(settings.spacy_models)),
        entities=settings.redaction_entities,
        score_threshold=settings.redaction_score_threshold,
    )
    return ChainRedactor([regex, presidio])


def redact_record(record: TraceRecord, redactor: Redactor) -> RedactedTrace:
    """Redact every free-text field of a record."""
    counts: Counter[str] = Counter()
    input_text, found = redactor.redact(record.input_text)
    counts.update(found)
    output_text, found = redactor.redact(record.output_text)
    counts.update(found)
    comment = record.feedback_comment
    if comment is not None:
        comment, found = redactor.redact(comment)
        counts.update(found)
    clean = record.model_copy(
        update={"input_text": input_text, "output_text": output_text, "feedback_comment": comment}
    )
    return RedactedTrace(
        record=clean, redactor_name=redactor.name, redacted_entity_counts=dict(counts)
    )
