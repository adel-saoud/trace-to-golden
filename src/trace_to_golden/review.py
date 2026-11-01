"""Review queue actions: approve (optionally with edits) or reject a candidate.

A reviewer can change their mind, so a reviewed candidate can be reviewed again.
"""

from __future__ import annotations

from trace_to_golden.models import GoldenCandidate, ReviewStatus
from trace_to_golden.store import Store


class CandidateNotFoundError(KeyError):
    """The record id is not in the review queue."""


def _queued_candidate(store: Store, record_id: str) -> GoldenCandidate:
    """The queued candidate; raises `CandidateNotFoundError` so the CLI can exit cleanly."""
    candidate = store.candidate(record_id)
    if candidate is None:
        raise CandidateNotFoundError(record_id)
    return candidate


def approve(
    store: Store,
    record_id: str,
    *,
    input_text: str | None = None,
    reference_answer: str | None = None,
    category: str | None = None,
    rubric: list[str] | None = None,
) -> GoldenCandidate:
    """Approve a candidate; any argument given replaces the traced value.

    Blank rubric criteria are dropped, and a rubric left with none keeps the current one,
    because schema v2 rejects empty criteria and empty rubrics.
    """
    candidate = _queued_candidate(store, record_id)
    criteria = tuple(c.strip() for c in rubric or [] if c.strip()) or None
    edits = {
        "input_text": input_text,
        "reference_answer": reference_answer,
        "category": category,
        "rubric": criteria,
    }
    update: dict[str, object] = {k: v for k, v in edits.items() if v is not None}
    update |= {"status": ReviewStatus.APPROVED, "review_reason": None}
    approved = candidate.model_copy(update=update)
    store.save_candidate(approved)
    return approved


def reject(store: Store, record_id: str, *, reason: str) -> GoldenCandidate:
    """Reject a candidate and keep the reason, so the same trace is not re-proposed blindly."""
    rejected = _queued_candidate(store, record_id).model_copy(
        update={"status": ReviewStatus.REJECTED, "review_reason": reason}
    )
    store.save_candidate(rejected)
    return rejected
