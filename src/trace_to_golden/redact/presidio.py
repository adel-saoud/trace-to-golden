"""NER-based redaction with Microsoft Presidio on lighter spaCy models.

Presidio's default model is `en_core_web_lg`; the small English and medium French
models keep setup light and are configured through `NlpEngineProvider`, one per
language. Each text is analyzed in the language a `LanguageDetector` picks.

Presidio's predefined recognizers differ per language: French has no
`CreditCardRecognizer`, for example. The regex redactor that runs before this one
covers structured identifiers in every language.
"""

from __future__ import annotations

from collections import Counter

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

from trace_to_golden.language import LanguageDetector
from trace_to_golden.redact.placeholders import PLACEHOLDER


class PresidioRedactor:
    """Replaces detected entities with `<ENTITY_TYPE>`, Presidio's default operator output."""

    def __init__(
        self,
        *,
        spacy_models: dict[str, str],
        detector: LanguageDetector,
        entities: tuple[str, ...],
        score_threshold: float,
    ) -> None:
        """Load the spaCy pipelines once; analysis is then in-process and offline."""
        nlp_engine = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [
                    {"lang_code": lang, "model_name": model} for lang, model in spacy_models.items()
                ],
            }
        ).create_engine()
        self._analyzer = AnalyzerEngine(
            nlp_engine=nlp_engine, supported_languages=list(spacy_models)
        )
        self._anonymizer = AnonymizerEngine()
        self._detector = detector
        self._entities = list(entities)
        self._score_threshold = score_threshold

    @property
    def name(self) -> str:
        """Identifier stored with redacted records."""
        return "presidio"

    def redact(self, text: str) -> tuple[str, Counter[str]]:
        """Analyze in the detected language, then anonymize with the `replace` operator."""
        if not text:
            return text, Counter()
        results = self._analyzer.analyze(
            text=text,
            language=self._detector.detect(text),
            entities=self._entities,
            score_threshold=self._score_threshold,
        )
        # Placeholders from the regex pass read like names ("ORDER_ID"); keep them intact.
        taken = [m.span() for m in PLACEHOLDER.finditer(text)]
        results = [
            r for r in results if not any(r.start < end and start < r.end for start, end in taken)
        ]
        anonymized = self._anonymizer.anonymize(
            text=text,
            analyzer_results=results,  # pyright: ignore[reportArgumentType]
            operators={"DEFAULT": OperatorConfig("replace")},
        )
        return anonymized.text, Counter(item.entity_type for item in anonymized.items)
