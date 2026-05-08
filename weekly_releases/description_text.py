"""Normalize release descriptions / changelogs and keep them within a length budget."""

from __future__ import annotations

import re

MAX_DESCRIPTION_LENGTH = 300


def _strip_release_markup(text: str) -> str:
    """Light cleanup so excerpts are readable outside GitHub/npm rendering."""
    s = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = re.sub(r"^#+\s*", "", s, flags=re.MULTILINE)
    s = re.sub(r"^\s*[-*+]\s+", "", s, flags=re.MULTILINE)
    return s


def _summarize_to_budget(text: str, budget: int) -> str:
    """Fit within ``budget`` characters using leading sentences, else word truncation."""
    suffix = "…"
    if budget <= len(suffix):
        return suffix[: max(1, budget)]
    hard_limit = budget - len(suffix)
    if len(text) <= hard_limit:
        return text

    parts: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        s = sentence.strip()
        if not s:
            continue
        candidate = " ".join(parts + [s])
        if len(candidate) <= hard_limit:
            parts.append(s)
        else:
            break

    if parts:
        return " ".join(parts) + suffix

    cut = text[:hard_limit]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    cut = cut.rstrip(".,; ")
    return cut + suffix


def normalize_release_description(raw: str | None) -> str | None:
    """Return plain text at most MAX_DESCRIPTION_LENGTH chars, or None if empty."""
    if raw is None:
        return None
    cleaned = _strip_release_markup(raw).strip()
    if not cleaned:
        return None
    collapsed = " ".join(cleaned.split())
    if len(collapsed) <= MAX_DESCRIPTION_LENGTH:
        return collapsed
    return _summarize_to_budget(collapsed, MAX_DESCRIPTION_LENGTH)
