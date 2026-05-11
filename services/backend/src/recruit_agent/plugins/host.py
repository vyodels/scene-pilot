from __future__ import annotations

import inspect
from collections.abc import Awaitable, Iterable
from dataclasses import dataclass, field
from typing import Any, Callable, cast

from fastapi import APIRouter

from recruit_agent.agent_runtime.models import GuardVerdict, Observation
from recruit_agent.runtime.tools import ToolDefinition, ToolRegistry, run_awaitable_blocking


ObservationEnricher = Callable[[Observation], dict[str, Any] | Awaitable[dict[str, Any]]]
GuardCheck = Callable[[str, dict[str, Any], Observation], GuardVerdict | Awaitable[GuardVerdict]]


@dataclass(slots=True)
class PluginHost:
    tool_registry: ToolRegistry = field(default_factory=ToolRegistry)
    routers: list[APIRouter] = field(default_factory=list)
    _observation_enrichers: list[tuple[str, ObservationEnricher]] = field(default_factory=list)
    _guard_checks: list[tuple[str, GuardCheck]] = field(default_factory=list)
    _persona_fragments: list[tuple[str, str, str]] = field(default_factory=list)

    def register_tools(self, namespace: str, toolkit: ToolRegistry | Iterable[ToolDefinition]) -> None:
        if isinstance(toolkit, ToolRegistry):
            self.tool_registry.merge(toolkit)
            return
        for tool in toolkit:
            self.tool_registry.register(tool)

    def register_observation_enricher(self, namespace: str, fn: ObservationEnricher) -> None:
        self._observation_enrichers.append((namespace, fn))

    def register_guard_check(self, namespace: str, fn: GuardCheck) -> None:
        self._guard_checks.append((namespace, fn))

    def register_persona_fragment(self, namespace: str, label: str, text: str) -> None:
        self._persona_fragments.append((namespace, label, text))

    def register_router(self, namespace: str, router: APIRouter) -> None:
        self.routers.append(router)

    async def run_observation_enrichers(self, observation: Observation) -> dict[str, Any]:
        payload = {
            "world_snapshot": dict(observation.world_snapshot),
            "scope_ref": observation.scope_ref,
            "scope_kind": observation.scope_kind,
            "recent_events": list(observation.recent_events),
            "available_tools": list(observation.available_tools),
            "available_skills": list(observation.available_skills),
            "available_mcps": list(observation.available_mcps),
            "hash": observation.hash,
            "input": observation.input,
        }
        world_snapshot = cast(dict[str, Any], payload["world_snapshot"])
        for namespace, enricher in self._observation_enrichers:
            result = await _maybe_await(enricher(observation))
            world_snapshot[f"plugin_{namespace}"] = dict(result or {})
        return payload

    def run_observation_enrichers_sync(self, observation: Observation) -> dict[str, Any]:
        return run_awaitable_blocking(lambda: self.run_observation_enrichers(observation))

    async def run_guard_checks(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        observation: Observation,
    ) -> list[GuardVerdict]:
        verdicts: list[GuardVerdict] = []
        for _namespace, check in self._guard_checks:
            verdicts.append(await _maybe_await(check(tool_name, arguments, observation)))
        return verdicts

    def run_guard_checks_sync(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        observation: Observation,
    ) -> list[GuardVerdict]:
        return run_awaitable_blocking(lambda: self.run_guard_checks(tool_name, arguments, observation))

    def collect_persona_fragments(self) -> list[str]:
        return [text for _namespace, _label, text in self._persona_fragments]


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value
