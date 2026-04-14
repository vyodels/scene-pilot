from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json
from typing import Any, Mapping

from .models import Message


@dataclass(slots=True)
class PromptLoader:
    root: Path = field(default_factory=lambda: Path(__file__).resolve().parents[1] / "prompts")

    def load_text(self, relative_path: str) -> str:
        path = self.root / relative_path
        if not path.exists():
            raise FileNotFoundError(path)
        return path.read_text(encoding="utf-8")

    def has_prompt(self, relative_path: str) -> bool:
        return (self.root / relative_path).exists()


class _SafeDict(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


@dataclass(slots=True)
class PromptBuilder:
    loader: PromptLoader = field(default_factory=PromptLoader)
    base_prompts: tuple[str, ...] = ("base/identity.md", "base/behavior_rules.md", "base/output_format.md")

    def render(self, template: str, values: Mapping[str, Any] | None = None) -> str:
        data = _SafeDict()
        if values:
            data.update(values)
        return template.format_map(data)

    def build_system_prompt(self, task_type: str, context: Mapping[str, Any] | None = None) -> str:
        parts = [self.loader.load_text(path).strip() for path in self.base_prompts]
        task_path = f"tasks/{task_type}.md"
        if self.loader.has_prompt(task_path):
            parts.append(self.render(self.loader.load_text(task_path), context or {}).strip())
        return "\n\n---\n\n".join(part for part in parts if part)

    def build_user_prompt(
        self,
        task_type: str,
        context: Mapping[str, Any] | None = None,
        extra_sections: Mapping[str, Any] | None = None,
    ) -> str:
        sections: list[str] = []
        if context:
            for key, value in context.items():
                sections.append(f"## {key}\n\n{self._render_section(value)}")
        if extra_sections:
            for key, value in extra_sections.items():
                sections.append(f"## {key}\n\n{self._render_section(value)}")
        return "\n\n---\n\n".join(section for section in sections if section)

    def build_messages(
        self,
        task: Any,
        *,
        session: Mapping[str, Any] | None = None,
        skill: Mapping[str, Any] | None = None,
        extra_context: Mapping[str, Any] | None = None,
    ) -> list[Message]:
        runtime_execution = isinstance(extra_context, Mapping) and isinstance(extra_context.get("execution_contract"), Mapping)
        task_type = (
            "runtime_execution"
            if runtime_execution
            else getattr(task, "task_type", None) or getattr(task, "workflow_node_id", None) or "initial_screening"
        )
        payload_context = dict(getattr(task, "payload", {}) or {})
        if extra_context:
            payload_context.update(extra_context)
        if session:
            payload_context.setdefault("session", session)
        if skill:
            payload_context.setdefault("skill", skill)

        system_prompt = self.build_system_prompt(task_type, payload_context)
        extra_sections: dict[str, Any] = {"task": getattr(task, "payload", {}) or {}}
        if runtime_execution:
            execution_contract = dict(extra_context.get("execution_contract") or {})
            extra_sections["Execution Contract"] = execution_contract
            if extra_context.get("scene_assessment") is not None:
                extra_sections["Scene Assessment"] = extra_context.get("scene_assessment")
            if extra_context.get("capability_drivers") is not None:
                extra_sections["Capability Drivers"] = extra_context.get("capability_drivers")
            if extra_context.get("execution_episode") is not None:
                extra_sections["Execution Episode"] = extra_context.get("execution_episode")

        user_prompt = self.build_user_prompt(task_type, context=payload_context, extra_sections=extra_sections)
        if skill:
            user_prompt = "\n\n---\n\n".join(
                part for part in [user_prompt, f"## Skill Reference\n\n{self._render_section(skill)}"] if part
            )

        messages = [Message(role="system", content=system_prompt)]
        if user_prompt:
            messages.append(Message(role="user", content=user_prompt))
        return messages

    def _render_section(self, value: Any) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)
