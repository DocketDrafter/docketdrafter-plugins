"""Text and filename helpers."""

from __future__ import annotations

import re


def sanitize_filename(text: str, limit: int = 100) -> str:
    """Reduce arbitrary text to a safe single path segment.

    Slugs and case names arrive from API responses and become directory names,
    so the result must never be a traversal segment or empty. Callers rely on
    getting back something usable.
    """
    text = re.sub(r'[<>:"/\\|?*]', "", text)
    text = re.sub(r"[\x00-\x1f\x7f]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.strip(". ")
    if not text or set(text) <= {"."}:
        return "unnamed"
    return text[:limit].strip(". ") or "unnamed"
