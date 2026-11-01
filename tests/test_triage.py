from __future__ import annotations

from collections.abc import Callable

from trace_to_golden.language import clustering_stop_words
from trace_to_golden.models import Flag, RedactedTrace, TraceRecord
from trace_to_golden.triage import candidates_from_triage, triage_traces
from trace_to_golden.triage.cluster import NOISE_LABEL, cluster_texts
from trace_to_golden.triage.flags import flag_records, robust_z_scores

TRACKING = [
    "Where is my order?",
    "Where is my order right now?",
    "Can you track my order for me?",
    "Where is my order today?",
    "Track my order please.",
]
RETOURS = [
    "Comment retourner un article ?",
    "Comment puis-je retourner un article ?",
    "Comment retourner un article acheté en ligne ?",
    "Je veux retourner un article.",
    "Retourner un article en magasin ?",
]
OFF_TOPIC = "Write a haiku about pirates and the moon."
STOP_WORDS = clustering_stop_words(["en", "fr"])


def test_robust_z_scores_single_out_the_outlier():
    assert robust_z_scores([]) == []
    assert robust_z_scores([5.0, 5.0, 5.0]) == [0.0, 0.0, 0.0]
    scores = robust_z_scores([1.0, 1.1, 0.9, 1.0, 30.0])
    assert scores[-1] > 3.5
    assert max(scores[:-1]) < 3.5


def test_flag_records_marks_errors_feedback_and_outliers(
    record_factory: Callable[..., TraceRecord],
):
    normal = [
        record_factory(latency_ms=1000.0 + i, input_tokens=300 + i, output_tokens=50)
        for i in range(6)
    ]
    records = [
        *normal,
        record_factory(latency_ms=40_000.0, input_tokens=300),
        record_factory(input_tokens=None, output_tokens=12_000),
        record_factory(error_type="timeout", feedback_score=-1.0),
        record_factory(feedback_score=1.0),
    ]
    flags = flag_records(records, outlier_z_threshold=3.5)
    assert all(not f for f in flags[:6])
    assert flags[6] == {Flag.LATENCY_OUTLIER}
    assert flags[7] == {Flag.TOKEN_OUTLIER}
    assert flags[8] == {Flag.ERROR, Flag.NEGATIVE_FEEDBACK}
    assert flags[9] == set()


def test_cluster_too_few_texts():
    result = cluster_texts(["a", "b"], min_cluster_size=3, stop_words=STOP_WORDS)
    assert result.labels == [NOISE_LABEL, NOISE_LABEL]
    assert result.topics == {}


def test_cluster_groups_intents_and_isolates_off_topic():
    texts = [*TRACKING, *RETOURS, OFF_TOPIC]
    texts[0] += " Reply to <EMAIL_ADDRESS>."
    result = cluster_texts(texts, min_cluster_size=3, stop_words=STOP_WORDS)
    assert len(set(result.labels[:5])) == 1
    assert len(set(result.labels[5:10])) == 1
    assert result.labels[0] != result.labels[5]
    assert result.labels[-1] == NOISE_LABEL
    assert "order" in result.topics[result.labels[0]]
    assert "retourner" in result.topics[result.labels[5]]
    assert all("email" not in topic for topic in result.topics.values())


def test_triage_queues_flagged_and_representatives(trace_factory: Callable[..., RedactedTrace]):
    texts = [*TRACKING, *RETOURS, OFF_TOPIC]
    traces = [trace_factory(span_id=f"s{i}", input_text=t) for i, t in enumerate(texts)]
    traces.append(trace_factory(span_id="err", input_text=TRACKING[0], error_type="timeout"))
    results = triage_traces(
        traces, min_cluster_size=3, outlier_z_threshold=3.5, stop_words=STOP_WORDS
    )
    by_id = {r.record_id: r for r in results}
    assert Flag.CLUSTER_OUTLIER in by_id["t1:s10"].flags
    assert Flag.ERROR in by_id["t1:err"].flags
    assert sum(r.is_representative for r in results) == 2
    candidates = candidates_from_triage(traces, results)
    queued = {c.record_id for c in candidates}
    assert {"t1:s10", "t1:err"} <= queued
    assert len(queued) == 4
    assert all(c.reference_answer == "It arrives in 3 days." for c in candidates)


def test_no_cluster_outlier_flag_when_nothing_clusters(trace_factory: Callable[..., RedactedTrace]):
    traces = [
        trace_factory(span_id="a", input_text="one"),
        trace_factory(span_id="b", input_text="two"),
    ]
    results = triage_traces(
        traces, min_cluster_size=3, outlier_z_threshold=3.5, stop_words=STOP_WORDS
    )
    assert all(not r.flags for r in results)
    assert candidates_from_triage(traces, results) == []
