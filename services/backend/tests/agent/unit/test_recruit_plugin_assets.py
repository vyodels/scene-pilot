from __future__ import annotations

import json

from recruit_agent.asset_paths import plugin_asset_path
from recruit_agent.plugins.recruit import persona as persona_module


def test_recruit_persona_fragment_reads_from_plugin_asset_root() -> None:
    persona_module._load_recruit_persona_fragment.cache_clear()

    index = json.loads(plugin_asset_path("recruit", "plugin.json").read_text(encoding="utf-8"))
    expected = plugin_asset_path("recruit", index["persona_assets"]["handover"]).read_text(encoding="utf-8").strip()

    assert persona_module._load_recruit_persona_fragment() == expected
