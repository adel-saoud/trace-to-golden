from __future__ import annotations

import pytest

from trace_to_golden.language import (
    StopWordLanguageDetector,
    clustering_stop_words,
    spacy_stop_words,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Where is my order and when will it arrive?", "en"),
        ("Où en est ma commande et quand va-t-elle arriver ?", "fr"),
        ("Bonjour, je suis <PERSON>. Pouvez-vous suivre ma commande ?", "fr"),
        ("CMD-48213977", "en"),  # no stop words: first configured language wins
    ],
)
def test_detector_picks_language_with_most_stop_words(text: str, expected: str):
    assert StopWordLanguageDetector(["en", "fr"]).detect(text) == expected


def test_detector_needs_a_language():
    with pytest.raises(ValueError, match="language"):
        StopWordLanguageDetector([])


def test_clustering_stop_words_match_tfidf_token_shape():
    assert "the" in spacy_stop_words("en")
    assert "est" in spacy_stop_words("fr")
    words = clustering_stop_words(["en", "fr"])
    assert words == sorted(words)
    assert {"the", "est"} <= set(words)
    assert all(len(w) >= 2 and "'" not in w for w in words)
