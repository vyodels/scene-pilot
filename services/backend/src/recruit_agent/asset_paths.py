from __future__ import annotations

from pathlib import Path


def recruit_agent_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / ".recruit-agent"
        if candidate.exists():
            return candidate
    raise FileNotFoundError("missing .recruit-agent asset root")


def prompts_root() -> Path:
    return recruit_agent_root() / "prompts"


def prompt_path(prompt_key: str) -> Path:
    normalized = str(prompt_key).strip().strip("/")
    return prompts_root() / f"{normalized}.md"


def scene_templates_root() -> Path:
    return prompts_root() / "scene_templates"


def plugin_asset_path(*parts: str) -> Path:
    return recruit_agent_root() / "plugins" / Path(*parts)


def skills_root() -> Path:
    return recruit_agent_root() / "skills"


def mcp_root() -> Path:
    return recruit_agent_root() / "mcp"


def mcp_preset_templates_root() -> Path:
    return mcp_root() / "presets"
