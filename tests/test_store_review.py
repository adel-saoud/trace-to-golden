from __future__ import annotations

from collections.abc import Callable

import pytest

from trace_to_golden import review
from trace_to_golden.models import GoldenCandidate, RedactedTrace, ReviewStatus
from trace_to_golden.store import Store


def pending_candidate(record_id: str = "t1:s1") -> GoldenCandidate:
    return GoldenCandidate(record_id=record_id, input_text="Q?", reference_answer="A.")


def test_traces_are_stored_once(store: Store, trace_factory: Callable[..., RedactedTrace]):
    trace = trace_factory()
    assert store.add_traces([trace]) == 1
    assert store.add_traces([trace, trace_factory(span_id="s2")]) == 1
    assert [t.record.record_id for t in store.traces()] == ["t1:s1", "t1:s2"]


def test_enqueue_keeps_review_state(store: Store):
    assert store.enqueue([pending_candidate()]) == 1
    review.reject(store, "t1:s1", reason="off topic")
    assert store.enqueue([pending_candidate()]) == 0
    stored = store.candidate("t1:s1")
    assert stored is not None
    assert stored.status is ReviewStatus.REJECTED
    assert stored.review_reason == "off topic"
    assert store.candidate("missing") is None


def test_approve_applies_edits_and_can_override_a_reject(store: Store):
    store.enqueue([pending_candidate(), pending_candidate("t2:s1")])
    review.reject(store, "t1:s1", reason="unsure")
    approved = review.approve(
        store,
        "t1:s1",
        input_text="Q2?",
        reference_answer="A2.",
        category="order_tracking",
        rubric=["Mentions the Orders page.", " ", "Gives a date."],
    )
    assert approved.status is ReviewStatus.APPROVED
    assert (approved.input_text, approved.reference_answer) == ("Q2?", "A2.")
    assert (approved.category, approved.rubric, approved.review_reason) == (
        "order_tracking",
        ("Mentions the Orders page.", "Gives a date."),
        None,
    )
    kept = review.approve(store, "t1:s1", rubric=[" "])
    assert kept.rubric == ("Mentions the Orders page.", "Gives a date.")
    assert [c.record_id for c in store.candidates(ReviewStatus.PENDING)] == ["t2:s1"]
    assert len(store.candidates()) == 2


def test_review_of_unknown_candidate_raises(store: Store):
    with pytest.raises(review.CandidateNotFoundError):
        review.approve(store, "nope")
    with pytest.raises(review.CandidateNotFoundError):
        review.reject(store, "nope", reason="x")
