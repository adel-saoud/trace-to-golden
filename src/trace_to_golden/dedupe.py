"""Drop candidates that repeat an existing golden case or an earlier candidate.

Two checks: an exact match after removing redaction tokens and normalising
case, punctuation and spacing, then a near-duplicate check with TF-IDF cosine
similarity at `dedupe_similarity_threshold`.
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np
from numpy.typing import NDArray
from sklearn.feature_extraction.text import TfidfVectorizer

from trace_to_golden.redact.placeholders import strip_placeholders

NON_WORD_RUN = re.compile(r"[^\w]+")
"""Runs of punctuation and spacing, collapsed to one space before the exact-match check."""


def normalize(text: str) -> str:
    """Drop redaction tokens, lowercase, and collapse punctuation and spacing."""
    return NON_WORD_RUN.sub(" ", strip_placeholders(text).lower()).strip()


def find_duplicates(
    candidate_inputs: list[str], existing_inputs: list[str], *, threshold: float
) -> list[str | None]:
    """For each candidate, why it is a duplicate, or None to keep it.

    A candidate is compared with every existing case and with the candidates
    kept before it, so the first of two near-identical candidates survives.
    """
    reasons: list[str | None] = [None] * len(candidate_inputs)
    if not candidate_inputs:
        return reasons
    texts = existing_inputs + candidate_inputs
    normalized = [normalize(t) for t in texts]
    # scikit-learn ships no type hints; see triage/cluster.py.
    vectorizer: Any = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)
    matrix: Any = vectorizer.fit_transform(normalized)
    # TfidfVectorizer L2-normalises rows by default, so a dot product is the cosine similarity.
    vectors: NDArray[np.float64] = np.asarray(matrix.todense(), dtype=np.float64)
    offset = len(existing_inputs)
    kept: list[int] = list(range(offset))
    for index in range(len(candidate_inputs)):
        row = offset + index
        reason = None
        for other in kept:
            if normalized[other] == normalized[row]:
                reason = "exact"
            else:
                similarity = float(vectors[row] @ vectors[other])
                if similarity >= threshold:
                    reason = f"near ({similarity:.2f})"
            if reason is not None:
                where = "existing case" if other < offset else "earlier candidate"
                reason = f"{reason} duplicate of {where}"
                break
        reasons[index] = reason
        if reason is None:
            kept.append(row)
    return reasons
