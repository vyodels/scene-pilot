from __future__ import annotations

from typing import Any


def score_index_entry(entry: dict[str, Any], query: str) -> int:
    haystacks = [
        str(entry.get("index_name") or ""),
        str(entry.get("index_description") or ""),
        str(entry.get("summary") or ""),
        str(entry.get("content") or ""),
    ]
    normalized_query = query.strip().lower()
    score = 0
    for haystack in haystacks:
        score += haystack.lower().count(normalized_query)
    return score
