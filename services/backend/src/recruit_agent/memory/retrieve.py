from __future__ import annotations

from typing import Any

from recruit_agent.memory.index import score_index_entry


def semantic_filter(entries: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    ranked = [(score_index_entry(entry, query), entry) for entry in entries]
    positive = [item for item in ranked if item[0] > 0]
    positive.sort(key=lambda item: item[0], reverse=True)
    return [entry for _score, entry in positive]
