"""Rule-based flags that mark a trace as worth reviewing.

Latency and token outliers use the robust z-score of Iglewicz and Hoaglin
(0.6745 * (x - median) / MAD, outlier above 3.5). Median and MAD are not pulled
up by the very outliers they look for, unlike mean and standard deviation.
"""

from __future__ import annotations

import statistics

from trace_to_golden.models import Flag, TraceRecord

MAD_SCALE = 0.6745
"""0.75 quantile of the standard normal, so MAD-based scores read like z-scores."""


def robust_z_scores(values: list[float]) -> list[float]:
    """Robust z-score of each value; all zeros when MAD is zero."""
    if not values:
        return []
    median = statistics.median(values)
    mad = statistics.median(abs(v - median) for v in values)
    if mad == 0:
        return [0.0] * len(values)
    return [MAD_SCALE * (v - median) / mad for v in values]


def _outliers(values: list[float | None], threshold: float) -> list[bool]:
    """Scores known values only, so a missing value neither counts nor shifts the median."""
    known = [v for v in values if v is not None]
    scores = iter(robust_z_scores(known))
    return [v is not None and next(scores) > threshold for v in values]


def flag_records(records: list[TraceRecord], *, outlier_z_threshold: float) -> list[set[Flag]]:
    """Error, negative feedback, latency and token flags, in input order."""
    latency = _outliers([r.latency_ms for r in records], outlier_z_threshold)
    tokens = _outliers(
        [
            float((r.input_tokens or 0) + (r.output_tokens or 0))
            if r.input_tokens is not None or r.output_tokens is not None
            else None
            for r in records
        ],
        outlier_z_threshold,
    )
    flags: list[set[Flag]] = []
    for index, record in enumerate(records):
        found: set[Flag] = set()
        if record.error_type is not None:
            found.add(Flag.ERROR)
        if record.feedback_score is not None and record.feedback_score < 0:
            found.add(Flag.NEGATIVE_FEEDBACK)
        if latency[index]:
            found.add(Flag.LATENCY_OUTLIER)
        if tokens[index]:
            found.add(Flag.TOKEN_OUTLIER)
        flags.append(found)
    return flags
