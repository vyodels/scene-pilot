from __future__ import annotations

import json
from typing import Any

from recruit_agent.asset_paths import plugin_asset_path


def read_optional_plugin_asset_index(namespace: str, filename: str = "plugin.json") -> dict[str, Any]:
    path = plugin_asset_path(namespace, filename)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def read_optional_plugin_text_asset(namespace: str, *parts: str) -> str:
    path = plugin_asset_path(namespace, *parts)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()
