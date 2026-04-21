from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from recruit_agent.plugins.assets import read_optional_plugin_asset_index, read_optional_plugin_text_asset


@lru_cache(maxsize=1)
def _load_recruit_persona_fragment() -> str:
    index = read_optional_plugin_asset_index("recruit")
    persona_assets = index.get("persona_assets")
    if not isinstance(persona_assets, dict):
        return ""

    handover_path = persona_assets.get("handover")
    if not isinstance(handover_path, str) or not handover_path.strip():
        return ""

    relative_path = Path(handover_path)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        return ""
    return read_optional_plugin_text_asset("recruit", *relative_path.parts)


RECRUIT_PERSONA_FRAGMENT = _load_recruit_persona_fragment()
