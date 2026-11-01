"""The `<ENTITY_TYPE>` tokens every redactor leaves behind."""

from __future__ import annotations

import re

PLACEHOLDER = re.compile(r"<[A-Z][A-Z_]*>")
"""Matches `<PERSON>`, `<ORDER_ID>` and any other token a redactor writes."""


def strip_placeholders(text: str) -> str:
    """Remove redaction tokens, so clustering and dedupe compare the question, not the PII shape."""
    return PLACEHOLDER.sub(" ", text)
