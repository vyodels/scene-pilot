from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AgentAssembly:
    prompt_overlay: dict[str, Any] = field(default_factory=dict)
    scenario_policy: dict[str, Any] = field(default_factory=dict)
    tool_allowlist: list[str] = field(default_factory=list)
    guard_policy_override: dict[str, Any] = field(default_factory=dict)
    context_policy: dict[str, Any] = field(default_factory=dict)
    kernel_tuning: dict[str, Any] = field(default_factory=dict)
