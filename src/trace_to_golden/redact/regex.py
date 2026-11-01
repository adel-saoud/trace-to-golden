"""Pattern-based redaction for structured identifiers.

Catches what has a fixed shape (emails, phone numbers, cards, IBANs, IPs),
street addresses in English and French by their street word, and any pattern a
team adds through `extra_redaction_patterns`. It cannot find names in free
text; that is the Presidio redactor's job.

Presidio tags only the city in "12 rue de Rivoli, 75001 Paris", so the address
patterns run here, before Presidio. They redact up to the end of the clause,
which errs on the side of removing too much.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
CARD = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")
"""13 to 19 digits with optional space or dash separators: the usual card number lengths."""

IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,4})?\b")
IPV4 = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")
PHONE = re.compile(r"(?<![\w-])\+?\(?\d[\d ().-]{7,}\d(?![\w-])")
"""Loose on purpose: `phone_valid` then rejects matches with too few or too many digits."""

FR_STREET = re.compile(
    r"\b\d{1,4}(?:\s?(?:bis|ter))?,?\s+"
    r"(?:rue|avenue|boulevard|bd|place|chemin|all[ée]e|impasse|quai|route)\b"
    r"[^,.;:!?\n]{1,40}(?:,?\s*\d{5}(?:\s+[A-ZÀ-Ý][\w'\u2019-]*)?)?",
    re.IGNORECASE,
)
EN_STREET = re.compile(
    r"\b\d{1,5}[A-Za-z]?\s+(?:[A-Z][a-z]+\s+){1,3}"
    r"(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Drive|Dr|Way|Boulevard|Blvd|Court|Ct)\b\.?"
)

MIN_PHONE_DIGITS = 9
"""Fewer digits is usually a quantity, a date or a short reference."""

MAX_PHONE_DIGITS = 15
"""E.164 caps an international number at 15 digits."""


def _digits(text: str) -> str:
    """Digits only, so separators change neither a checksum nor a length check."""
    return "".join(ch for ch in text if ch.isdigit())


def luhn_valid(number: str) -> bool:
    """Luhn checksum, so order numbers and timestamps are not taken for cards.

    Presidio has the same check in `CreditCardRecognizer.validate_result`, an
    undocumented method; keeping it here leaves light mode off Presidio internals.
    """
    digits = [int(d) for d in _digits(number)]
    total = 0
    for index, digit in enumerate(reversed(digits)):
        doubled = digit * 2 if index % 2 else digit
        total += doubled - 9 if doubled > 9 else doubled
    return len(digits) >= 13 and total % 10 == 0


def iban_valid(candidate: str) -> bool:
    """ISO 13616 mod-97 check."""
    compact = candidate.replace(" ", "")
    rearranged = compact[4:] + compact[:4]
    numeric = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(numeric) % 97 == 1


def phone_valid(candidate: str) -> bool:
    """Digit count within [`MIN_PHONE_DIGITS`, `MAX_PHONE_DIGITS`]."""
    return MIN_PHONE_DIGITS <= len(_digits(candidate)) <= MAX_PHONE_DIGITS


Validator = Callable[[str], bool]
"""Returns False for a lookalike match (bad checksum, wrong length), which stays in the text."""

BUILTIN_PATTERNS: tuple[tuple[str, re.Pattern[str], Validator | None], ...] = (
    ("EMAIL_ADDRESS", EMAIL, None),
    ("IBAN_CODE", IBAN, iban_valid),
    ("CREDIT_CARD", CARD, luhn_valid),
    ("IP_ADDRESS", IPV4, None),
    ("STREET_ADDRESS", FR_STREET, None),
    ("STREET_ADDRESS", EN_STREET, None),
    ("PHONE_NUMBER", PHONE, phone_valid),
)


class RegexRedactor:
    """Built-in patterns plus team-specific ones, applied in a fixed order."""

    def __init__(self, extra_patterns: dict[str, str] | None = None) -> None:
        """Compile `extra_patterns` (entity name to regex) once."""
        extras = [
            (entity, re.compile(pattern), None)
            for entity, pattern in (extra_patterns or {}).items()
        ]
        self._patterns: list[tuple[str, re.Pattern[str], Validator | None]] = [
            *BUILTIN_PATTERNS,
            *extras,
        ]

    @property
    def name(self) -> str:
        """Identifier stored with redacted records."""
        return "regex"

    def redact(self, text: str) -> tuple[str, Counter[str]]:
        """Replace each valid match with `<ENTITY>`."""
        counts: Counter[str] = Counter()
        for entity, pattern, validator in self._patterns:

            def replace(
                match: re.Match[str], entity: str = entity, check: Validator | None = validator
            ) -> str:
                if check is not None and not check(match.group(0)):
                    return match.group(0)
                counts[entity] += 1
                return f"<{entity}>"

            text = pattern.sub(replace, text)
        return text, counts
