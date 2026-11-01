"""Choose which stored traces go to the review queue, and why.

A trace is queued when it carries a flag (error, negative feedback, outlier)
or when it is the strongest member of its cluster, so every recurring intent
gets one candidate even if nothing went wrong.
"""

from __future__ import annotations

from trace_to_golden.models import Flag, GoldenCandidate, RedactedTrace, TriageResult
from trace_to_golden.triage.cluster import NOISE_LABEL, cluster_texts
from trace_to_golden.triage.flags import flag_records


def triage_traces(
    traces: list[RedactedTrace],
    *,
    min_cluster_size: int,
    outlier_z_threshold: float,
    stop_words: list[str],
) -> list[TriageResult]:
    """Cluster and flag every trace."""
    records = [t.record for t in traces]
    clustering = cluster_texts(
        [r.input_text for r in records], min_cluster_size=min_cluster_size, stop_words=stop_words
    )
    rule_flags = flag_records(records, outlier_z_threshold=outlier_z_threshold)
    has_clusters = bool(clustering.topics)
    best: dict[int, int] = {}
    for index, label in enumerate(clustering.labels):
        if label == NOISE_LABEL:
            continue
        if (
            label not in best
            or clustering.probabilities[index] > clustering.probabilities[best[label]]
        ):
            best[label] = index
    representatives = set(best.values())
    results: list[TriageResult] = []
    for index, record in enumerate(records):
        label = clustering.labels[index]
        flags = set(rule_flags[index])
        if has_clusters and label == NOISE_LABEL:
            flags.add(Flag.CLUSTER_OUTLIER)
        results.append(
            TriageResult(
                record_id=record.record_id,
                cluster_id=label,
                cluster_topic=clustering.topics.get(label),
                is_representative=index in representatives,
                flags=tuple(sorted(flags)),
            )
        )
    return results


def candidates_from_triage(
    traces: list[RedactedTrace], results: list[TriageResult]
) -> list[GoldenCandidate]:
    """Turn flagged traces and cluster representatives into pending candidates."""
    by_id = {t.record.record_id: t.record for t in traces}
    candidates: list[GoldenCandidate] = []
    for triage in results:
        if not triage.flags and not triage.is_representative:
            continue
        record = by_id[triage.record_id]
        candidates.append(
            GoldenCandidate(
                record_id=record.record_id,
                input_text=record.input_text,
                reference_answer=record.output_text,
                topic=triage.cluster_topic,
                flags=triage.flags,
            )
        )
    return candidates
