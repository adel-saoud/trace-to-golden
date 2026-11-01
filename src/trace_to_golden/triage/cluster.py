"""Group similar user questions so a reviewer sees one case per intent.

TF-IDF vectors are L2-normalised by default, so euclidean distance ranks pairs
the same way cosine distance does, and HDBSCAN can use its default metric.
HDBSCAN labels points that fit no cluster as -1 (scikit-learn >= 1.3).

Scale limit: on sparse input HDBSCAN runs brute-force pairwise distances, so
memory grows with the square of the number of traces. Run triage on a time
window or a sample (a few tens of thousands of traces at most).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from sklearn.cluster import HDBSCAN
from sklearn.feature_extraction.text import TfidfVectorizer

from trace_to_golden.redact.placeholders import strip_placeholders

NOISE_LABEL = -1
"""HDBSCAN label for a text that fits no cluster."""

TOPIC_TERMS = 3
"""Top TF-IDF terms joined into a cluster topic: enough to tell intents apart, short
enough to read in the queue table."""


@dataclass(frozen=True)
class ClusteringResult:
    """Per-text cluster label, membership strength and a short topic per cluster."""

    labels: list[int]
    probabilities: list[float]
    topics: dict[int, str]


def cluster_texts(
    texts: list[str], *, min_cluster_size: int, stop_words: list[str]
) -> ClusteringResult:
    """Cluster texts; with fewer texts than `min_cluster_size` everything is noise.

    `stop_words` should cover every language in the traces (see
    `trace_to_golden.language.clustering_stop_words`). The same intent asked in
    two languages lands in two clusters, which gives one eval case per language.
    """
    if len(texts) < min_cluster_size:
        return ClusteringResult([NOISE_LABEL] * len(texts), [0.0] * len(texts), {})
    # scikit-learn ships no type hints, so its objects are handled as Any here
    # and converted to typed numpy arrays right away.
    vectorizer: Any = TfidfVectorizer(stop_words=stop_words, ngram_range=(1, 2), sublinear_tf=True)
    matrix: Any = vectorizer.fit_transform([strip_placeholders(t) for t in texts])
    # copy=True keeps HDBSCAN from mutating the input; scikit-learn 1.9 types the
    # parameter as its "warn" sentinel during the default change.
    model: Any = HDBSCAN(min_cluster_size=min_cluster_size, copy=True)  # pyright: ignore[reportArgumentType]
    model.fit(matrix)
    labels: NDArray[np.int_] = np.asarray(model.labels_, dtype=np.int_)
    probabilities: NDArray[np.float64] = np.asarray(model.probabilities_, dtype=np.float64)
    terms: list[str] = [str(t) for t in vectorizer.get_feature_names_out()]
    dense: NDArray[np.float64] = np.asarray(matrix.todense(), dtype=np.float64)
    topics: dict[int, str] = {}
    for label in sorted({int(x) for x in labels} - {NOISE_LABEL}):
        weights = [float(w) for w in dense[labels == label].mean(axis=0)]
        top = sorted(range(len(weights)), key=lambda i: weights[i], reverse=True)[:TOPIC_TERMS]
        topics[label] = ", ".join(terms[i] for i in top)
    return ClusteringResult(
        labels=[int(x) for x in labels],
        probabilities=[float(x) for x in probabilities],
        topics=topics,
    )
