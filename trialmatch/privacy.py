from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RedactionResult:
    text: str
    pii_types: tuple[str, ...]


_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("national_id", re.compile(r"(?<!\d)\d{11}(?!\d)")),
    (
        "email",
        re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    ),
    (
        "phone",
        re.compile(r"(?<!\w)(?:\+?90[\s().-]*)?0?5\d{2}[\s().-]*\d{3}[\s().-]*\d{2}[\s().-]*\d{2}(?!\w)"),
    ),
    (
        "date_of_birth",
        re.compile(
            r"\b(?:doğum tarihi|dogum tarihi|date of birth|dob)\s*[:=]?\s*"
            r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b",
            re.IGNORECASE,
        ),
    ),
    (
        "file_or_protocol_id",
        re.compile(r"\b(?:protokol|dosya)\s*(?:no|numarası|numarasi)?\s*[:#-]?\s*[A-Z0-9-]{5,}\b", re.IGNORECASE),
    ),
    (
        "address",
        re.compile(
            r"\b(?:adres|address)\s*[:=]\s*[^,\n;]{8,}",
            re.IGNORECASE,
        ),
    ),
    (
        "person_name_labeled",
        re.compile(
            r"\b(?:hasta\s*[:=]?\s*|ad\s*soyad\s*[:=]\s*)"
            r"[A-ZÇĞİÖŞÜ][a-zçğıöşü]{1,}(?:\s+[A-ZÇĞİÖŞÜ][a-zçğıöşü]{1,}){1,2}\b"
        ),
    ),
    (
        "person_name",
        re.compile(
            r"(?<![A-Za-zÇĞİÖŞÜçğıöşü])"
            r"[A-ZÇĞİÖŞÜ][a-zçğıöşü]{1,}\s+[A-ZÇĞİÖŞÜ][a-zçğıöşü]{1,}"
            r"(?=\s*[,;])"
        ),
    ),
)


def redact_pii(text: str) -> RedactionResult:
    """Mask common identifiers before parsing, tracing, or external requests."""
    masked = text
    found: set[str] = set()
    for pii_type, pattern in _PATTERNS:
        if pii_type == "person_name_labeled":
            labeled_pattern = pattern.pattern.replace(
                r"hasta\s*[:=]?\s*",
                r"hasta\b\s*[:=]?\s*",
            )
            pattern = re.compile(labeled_pattern, pattern.flags | re.IGNORECASE)
        masked, count = pattern.subn("[REDACTED]", masked)
        if count:
            found.add(pii_type)
    return RedactionResult(text=masked, pii_types=tuple(sorted(found)))


def contains_unmasked_common_pii(text: str) -> bool:
    for pii_type, pattern in _PATTERNS:
        if pii_type == "person_name_labeled":
            labeled_pattern = pattern.pattern.replace(
                r"hasta\s*[:=]?\s*",
                r"hasta\b\s*[:=]?\s*",
            )
            pattern = re.compile(labeled_pattern, pattern.flags | re.IGNORECASE)
        if pattern.search(text):
            return True
    return False
