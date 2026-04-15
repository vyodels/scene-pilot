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
        managed_execution = isinstance(extra_context, Mapping) and isinstance(extra_context.get("execution_contract"), Mapping)
        task_type = (
            "scale_execution"
            if managed_execution
            else getattr(task, "task_type", None) or "candidate_probe"
        )
        task_payload = dict(getattr(task, "payload", {}) or {})
        if managed_execution:
            execution_contract = dict(extra_context.get("execution_contract") or {})
            active_step = self._active_runtime_step(execution_contract)
            payload_context: dict[str, Any] = {}
            if session:
                payload_context["session"] = session
            if skill:
                payload_context["skill"] = skill
            payload_context["runtime_context"] = self._managed_execution_payload_context(extra_context, execution_contract, active_step)
            system_prompt = self.build_system_prompt(task_type, payload_context)
            extra_sections: dict[str, Any] = {
                "Task Brief": self._runtime_task_brief(task_payload),
                "Execution Contract Summary": self._execution_contract_summary(execution_contract, active_step),
            }
            if extra_context.get("scene_assessment") is not None:
                extra_sections["Scene Assessment Summary"] = self._scene_assessment_summary(extra_context.get("scene_assessment"))
            if extra_context.get("capability_drivers") is not None:
                extra_sections["Capability Drivers"] = self._capability_driver_summary(extra_context.get("capability_drivers"))
        else:
            payload_context = dict(task_payload)
            if extra_context:
                payload_context.update(extra_context)
            if session:
                payload_context.setdefault("session", session)
            if skill:
                payload_context.setdefault("skill", skill)
            system_prompt = self.build_system_prompt(task_type, payload_context)
            extra_sections = {"task": task_payload}

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

    def _managed_execution_payload_context(
        self,
        extra_context: Mapping[str, Any],
        execution_contract: Mapping[str, Any],
        active_step: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        scene_assessment = extra_context.get("scene_assessment")
        planner_guidance = extra_context.get("planner_guidance")
        scene_profile = extra_context.get("scene_profile")
        return {
            "plan_name": execution_contract.get("plan_name"),
            "domain": execution_contract.get("domain"),
            "goal": execution_contract.get("goal"),
            "scene_type": execution_contract.get("scene_type"),
            "planner_posture": execution_contract.get("planner_posture"),
            "current_step_id": execution_contract.get("current_step_id"),
            "active_step": {
                "id": active_step.get("id") if active_step else None,
                "capability": active_step.get("capability") if active_step else None,
                "summary": active_step.get("summary") if active_step else None,
                "preferred_tools": list(active_step.get("preferred_tools") or []) if active_step else [],
            },
            "blockers": list(execution_contract.get("blockers") or []),
            "recommended_capabilities": list(execution_contract.get("recommended_capabilities") or []),
            "scene_assessment": {
                "plan_fit": scene_assessment.get("plan_fit") if isinstance(scene_assessment, Mapping) else None,
                "confidence": scene_assessment.get("confidence") if isinstance(scene_assessment, Mapping) else None,
                "blockers": list(scene_assessment.get("blockers") or []) if isinstance(scene_assessment, Mapping) else [],
            },
            "planner_guidance": {
                "posture": planner_guidance.get("posture") if isinstance(planner_guidance, Mapping) else None,
                "requires_human_review": planner_guidance.get("requires_human_review") if isinstance(planner_guidance, Mapping) else None,
                "should_checkpoint": planner_guidance.get("should_checkpoint") if isinstance(planner_guidance, Mapping) else None,
            },
            "scene_profile": {
                "interaction_mode": scene_profile.get("interaction_mode") if isinstance(scene_profile, Mapping) else None,
                "signals": list(scene_profile.get("signals") or []) if isinstance(scene_profile, Mapping) else [],
            },
        }

    def _execution_contract_summary(
        self,
        execution_contract: Mapping[str, Any],
        active_step: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        steps = list(execution_contract.get("steps") or [])
        return {
            "plan_name": execution_contract.get("plan_name"),
            "domain": execution_contract.get("domain"),
            "goal": execution_contract.get("goal"),
            "scene_type": execution_contract.get("scene_type"),
            "planner_posture": execution_contract.get("planner_posture"),
            "approval_policy": self._compact_approval_policy(execution_contract.get("approval_policy")),
            "output_contract": self._compact_output_contract(execution_contract.get("output_contract")),
            "recommended_capabilities": list(execution_contract.get("recommended_capabilities") or []),
            "blockers": list(execution_contract.get("blockers") or []),
            "current_step_id": execution_contract.get("current_step_id"),
            "active_step": self._compact_step(active_step),
            "remaining_step_ids": [
                step.get("id")
                for step in steps
                if isinstance(step, Mapping) and step.get("id") != execution_contract.get("current_step_id")
            ],
            "checkpoint_count": len(list(execution_contract.get("checkpoints") or [])),
        }

    def _scene_assessment_summary(self, scene_assessment: Any) -> dict[str, Any]:
        if not isinstance(scene_assessment, Mapping):
            return {}
        return {
            "scene_type": scene_assessment.get("scene_type"),
            "scene_key": scene_assessment.get("scene_key"),
            "confidence": scene_assessment.get("confidence"),
            "plan_fit": scene_assessment.get("plan_fit"),
            "blockers": list(scene_assessment.get("blockers") or []),
            "recommended_capabilities": list(scene_assessment.get("recommended_capabilities") or []),
            "notes": list(scene_assessment.get("assessment_notes") or [])[:6],
        }

    def _capability_driver_summary(self, capability_drivers: Any) -> list[dict[str, Any]]:
        if not isinstance(capability_drivers, list):
            return []
        summary: list[dict[str, Any]] = []
        for item in capability_drivers:
            if not isinstance(item, Mapping):
                continue
            summary.append(
                {
                    "key": item.get("key"),
                    "risk": item.get("risk"),
                    "executor_mode": item.get("executor_mode"),
                    "preferred_tools": list(item.get("preferred_tools") or []),
                    "scene_required": bool(item.get("scene_required")),
                }
            )
        return summary

    def _active_runtime_step(self, execution_contract: Mapping[str, Any]) -> dict[str, Any] | None:
        current_step_id = execution_contract.get("current_step_id")
        for step in list(execution_contract.get("steps") or []):
            if isinstance(step, Mapping) and step.get("id") == current_step_id:
                return dict(step)
        return None

    def _runtime_task_brief(self, task_payload: Mapping[str, Any]) -> dict[str, Any]:
        snapshot = task_payload.get("environment_snapshot") if isinstance(task_payload.get("environment_snapshot"), Mapping) else {}
        return {
            "instruction": task_payload.get("instruction"),
            "goal": task_payload.get("goal"),
            "domain": task_payload.get("domain"),
            "plan_name": task_payload.get("plan_name"),
            "operator_notes": task_payload.get("notes"),
            "environment_snapshot": self._compact_snapshot(snapshot),
        }

    def _compact_snapshot(self, snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
        if not isinstance(snapshot, Mapping):
            return {}
        observed_entities = [item for item in list(snapshot.get("observed_entities") or []) if isinstance(item, Mapping)]
        affordances = [item for item in list(snapshot.get("affordances") or []) if isinstance(item, Mapping)]
        runtime_metadata = snapshot.get("runtime_metadata") if isinstance(snapshot.get("runtime_metadata"), Mapping) else {}
        candidates: list[dict[str, Any]] = []
        for entity in observed_entities:
            if str(entity.get("kind") or "") != "candidate_card":
                continue
            attributes = entity.get("attributes") if isinstance(entity.get("attributes"), Mapping) else {}
            candidates.append(
                {
                    "name": entity.get("label"),
                    "candidate_id": entity.get("entity_id"),
                    "summary": str(attributes.get("summary") or "")[:220] or None,
                }
            )
            if len(candidates) >= 4:
                break
        affordance_labels = [
            str(item.get("label") or item.get("action") or "").strip()
            for item in affordances[:8]
            if str(item.get("label") or item.get("action") or "").strip()
        ]
        return {
            "source": snapshot.get("source"),
            "url": snapshot.get("url"),
            "title": snapshot.get("title"),
            "page_type": snapshot.get("page_type"),
            "candidate_count": runtime_metadata.get("candidate_count") or len(candidates),
            "top_candidates": candidates,
            "affordances": affordance_labels,
            "page_excerpt": str(runtime_metadata.get("page_text_excerpt") or "")[:420] or None,
        }

    def _compact_approval_policy(self, approval_policy: Any) -> dict[str, Any]:
        if not isinstance(approval_policy, Mapping):
            return {}
        return {
            "mode": approval_policy.get("mode"),
            "trial_required": approval_policy.get("trial_required"),
            "requires_environment_snapshot": approval_policy.get("requires_environment_snapshot"),
            "approval_actions": list(approval_policy.get("approval_actions") or [])[:6],
            "requires_human_confirmation_before": list(approval_policy.get("requires_human_confirmation_before") or [])[:4],
            "allowed_without_additional_approval": list(approval_policy.get("allowed_without_additional_approval") or [])[:4],
        }

    def _compact_output_contract(self, output_contract: Any) -> dict[str, Any]:
        if not isinstance(output_contract, Mapping):
            return {}
        return {
            "kind": output_contract.get("kind"),
            "fields": list(output_contract.get("fields") or [])[:8],
            "final_summary": list((output_contract.get("final_summary") or {}).get("include") or [])[:6]
            if isinstance(output_contract.get("final_summary"), Mapping)
            else [],
        }

    def _compact_step(self, active_step: Mapping[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(active_step, Mapping):
            return None
        return {
            "id": active_step.get("id"),
            "capability": active_step.get("capability"),
            "summary": active_step.get("summary") or active_step.get("action"),
            "preferred_tools": list(active_step.get("preferred_tools") or []),
        }
