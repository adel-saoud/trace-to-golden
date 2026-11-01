"""Runtime settings, read from `TTG_*` environment variables or CLI flags."""

from __future__ import annotations

import difflib
import os
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "TTG_"


class RedactorName(StrEnum):
    """Which redaction backend to run.

    `presidio` adds NER (names, places) on top of the regex patterns; `regex`
    is the light mode for machines without the spaCy model.
    """

    PRESIDIO = "presidio"
    REGEX = "regex"


DEFAULT_REDACTION_ENTITIES = (
    "PERSON",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "CREDIT_CARD",
    "IBAN_CODE",
    "IP_ADDRESS",
    "LOCATION",
    "US_SSN",
)
"""Presidio entity types to redact. DATE_TIME is left out on purpose: it fires on
"after 2 years" and similar phrases that carry the meaning of an eval case."""


DEFAULT_SPACY_MODELS = {"en": "en_core_web_sm", "fr": "fr_core_news_md"}
"""French uses the medium model: the small one tags sentence-initial words such as
"Ma livraison" as PERSON, which destroys the question an eval case needs."""


class Settings(BaseSettings):
    """All tunables in one place, so a new team or country changes config, not code."""

    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, extra="forbid")

    db_path: Path = Path("trace_to_golden.db")
    redactor: RedactorName = RedactorName.PRESIDIO
    spacy_models: dict[str, str] = Field(
        default_factory=lambda: dict(DEFAULT_SPACY_MODELS),
        description="Language code to spaCy pipeline. Its keys are the languages detected, "
        "redacted and used for clustering stop words; the first key wins ties.",
    )
    redaction_entities: tuple[str, ...] = DEFAULT_REDACTION_ENTITIES
    redaction_score_threshold: float = 0.4
    extra_redaction_patterns: dict[str, str] = Field(
        default_factory=dict[str, str],
        description="Extra regexes by entity name, e.g. {'ORDER_ID': 'CMD-\\\\d{8}'}.",
    )
    feedback_score_attribute: str = "user_feedback.score"
    feedback_comment_attribute: str = "user_feedback.comment"
    min_cluster_size: int = Field(default=3, ge=2)
    outlier_z_threshold: float = Field(
        default=3.5,
        description="Robust z-score (median and MAD) above which a value is an outlier.",
    )
    dedupe_similarity_threshold: float = Field(default=0.9, gt=0.0, le=1.0)

    @model_validator(mode="after")
    def _reject_unknown_env_vars(self) -> Self:
        """Fail on a `TTG_*` variable that maps to no field.

        pydantic-settings ignores such variables even with `extra="forbid"`, so a
        typo like `TTG_DB_PTH` would silently keep the default store path.
        """
        check_env_vars(os.environ)
        return self


def check_env_vars(environ: Mapping[str, str]) -> None:
    """Raise `ValueError` naming every unknown `TTG_*` variable and its closest valid name.

    Names are compared upper-cased because pydantic-settings reads environment
    variables case-insensitively by default.
    """
    valid = [f"{ENV_PREFIX}{name}".upper() for name in Settings.model_fields]
    unknown = sorted(
        name
        for name in environ
        if name.upper().startswith(ENV_PREFIX) and name.upper() not in valid
    )
    if not unknown:
        return
    hints: list[str] = []
    for name in unknown:
        closest = difflib.get_close_matches(name.upper(), valid, n=1)
        hints.append(f"{name} (did you mean {closest[0]}?)" if closest else name)
    raise ValueError(
        f"Unknown {ENV_PREFIX}* environment variables: {', '.join(hints)}. "
        f"Valid names: {', '.join(valid)}."
    )
