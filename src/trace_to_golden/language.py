"""Language handling for redaction and clustering.

The detector picks, among the configured languages, the one whose spaCy stop
words appear most in a text. It needs no extra dependency or model download,
works well for clearly different languages such as English and French, and is
weak between close languages (Spanish, Portuguese, Italian) and on very short
questions. Swap in another `LanguageDetector` when a closer language is added.
"""

from __future__ import annotations

import re
from functools import cache
from typing import Protocol

from spacy.util import get_lang_class

WORD_TOKEN = re.compile(r"\w+", re.UNICODE)
"""Word tokens counted against each language's stop words."""

TFIDF_TOKEN = re.compile(r"^\w\w+$")
"""scikit-learn's default token pattern keeps words of two or more characters."""


class LanguageDetector(Protocol):
    """Returns one of the configured language codes for a text."""

    def detect(self, text: str) -> str:
        """Language code of `text`."""
        ...


@cache
def spacy_stop_words(language: str) -> frozenset[str]:
    """spaCy's stop-word list for a language code.

    Read from the language class defaults, so no trained pipeline is loaded or downloaded.
    """
    return frozenset(get_lang_class(language).Defaults.stop_words)


def clustering_stop_words(languages: list[str]) -> list[str]:
    """Union of stop words in the token shape TF-IDF produces, sorted for stable output."""
    words = {w for lang in languages for w in spacy_stop_words(lang) if TFIDF_TOKEN.match(w)}
    return sorted(words)


class StopWordLanguageDetector:
    """Counts stop words per language; ties go to the first configured language."""

    def __init__(self, languages: list[str]) -> None:
        """Keep the languages in priority order; the first one wins a tie."""
        if not languages:
            raise ValueError("at least one language is required")
        self._languages = languages

    def detect(self, text: str) -> str:
        """The configured language with the most stop-word hits in `text`."""
        words = [w.lower() for w in WORD_TOKEN.findall(text)]
        scores = {
            lang: sum(1 for w in words if w in spacy_stop_words(lang)) for lang in self._languages
        }
        best = max(scores.values())
        return next(lang for lang in self._languages if scores[lang] == best)
