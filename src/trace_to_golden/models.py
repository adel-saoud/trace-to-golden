"""Data models shared by every pipeline stage.

`TraceRecord` is the allowlist: an ingester copies only these fields out of a
trace, so any attribute not named here (user ids, URLs, tool arguments) is
dropped before redaction even runs. `RedactedTrace` is the only type the store
accepts, which makes "redact before storage" a type-checked rule, not a
convention.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class TraceSource(StrEnum):
    """Where a record was ingested from."""

    OTEL = "otel"
    MLFLOW = "mlflow"


class Flag(StrEnum):
    """Why a trace deserves a human look."""

    ERROR = "error"
    NEGATIVE_FEEDBACK = "negative_feedback"
    CLUSTER_OUTLIER = "cluster_outlier"
    LATENCY_OUTLIER = "latency_outlier"
    TOKEN_OUTLIER = "token_outlier"  # noqa: S105 (a flag name, not a secret)


class ReviewStatus(StrEnum):
    """State of a candidate in the review queue."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class TraceRecord(BaseModel):
    """One user turn extracted from a trace, before redaction.

    Only the fields below survive ingestion. Free text (`input_text`,
    `output_text`, `feedback_comment`) still holds raw PII at this point.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    trace_id: str
    span_id: str
    source: TraceSource
    input_text: str
    output_text: str
    conversation_id: str | None = None
    operation_name: str | None = None
    provider_name: str | None = None
    model: str | None = None
    start_time_unix_nano: int | None = None
    latency_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    error_type: str | None = None
    feedback_score: float | None = Field(
        default=None, description="User feedback in [-1.0, 1.0]; negative means a bad answer."
    )
    feedback_comment: str | None = None

    @property
    def record_id(self) -> str:
        """Stable id for one span of one trace."""
        return f"{self.trace_id}:{self.span_id}"


class RedactedTrace(BaseModel):
    """A `TraceRecord` whose free text went through a `Redactor`.

    Built only by `trace_to_golden.redact.redact_record`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    record: TraceRecord
    redactor_name: str
    redacted_entity_counts: dict[str, int] = Field(default_factory=dict[str, int])


class TriageResult(BaseModel):
    """Clustering and flagging result for one stored trace."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record_id: str
    cluster_id: int = Field(description="HDBSCAN label; -1 means the trace fits no cluster.")
    cluster_topic: str | None = None
    is_representative: bool = False
    flags: tuple[Flag, ...] = ()


class GoldenCandidate(BaseModel):
    """A trace proposed as a golden case, edited and judged by a reviewer.

    Holds a superset of the fields any dataset schema needs, so the exporter is
    the only place that knows the target format.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    record_id: str
    status: ReviewStatus = ReviewStatus.PENDING
    input_text: str
    reference_answer: str
    category: str | None = None
    rubric: tuple[str, ...] | None = Field(
        default=None, description="Criteria a good answer must meet, each judged pass or fail."
    )
    topic: str | None = None
    flags: tuple[Flag, ...] = ()
    review_reason: str | None = None
