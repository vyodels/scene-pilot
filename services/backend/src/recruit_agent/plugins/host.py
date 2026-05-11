from __future__ import annotations

import inspect
from collections.abc import Awaitable, Iterable
from dataclasses import dataclass, field
from typing import Any, Callable, cast

from fastapi import APIRouter

from recruit_agent.capabilities.tools import ToolDefinition, ToolRegistry, run_awaitable_blocking


ContextEnricher = Callable[[dict[str, Any]], dict[str, Any] | Awaitable[dict[str, Any]]]
GuardCheck = Callable[[str, dict[str, Any], dict[str, Any]], dict[str, Any] | Awaitable[dict[str, Any]]]


@dataclass(slots=True)
class PluginHost:
    tool_registry: ToolRegistry = field(default_factory=ToolRegistry)
    routers: list[APIRouter] = field(default_factory=list)
    _context_enrichers: list[tuple[str, ContextEnricher]] = field(default_factory=list)
    _guard_checks: list[tuple[str, GuardCheck]] = field(default_factory=list)
    _persona_fragments: list[tuple[str, str, str]] = field(default_factory=list)

    def register_tools(self, namespace: str, toolkit: ToolRegistry | Iterable[ToolDefinition]) -> None:
        if isinstance(toolkit, ToolRegistry):
            self.tool_registry.merge(toolkit)
            return
        for tool in toolkit:
            self.tool_registry.register(tool)

    def register_context_enricher(self, namespace: str, fn: ContextEnricher) -> None:
        self._context_enrichers.append((namespace, fn))

    def register_guard_check(self, namespace: str, fn: GuardCheck) -> None:
        self._guard_checks.append((namespace, fn))

    def register_persona_fragment(self, namespace: str, label: str, text: str) -> None:
        self._persona_fragments.append((namespace, label, text))

    def register_router(self, namespace: str, router: APIRouter) -> None:
        self.routers.append(router)

    async def run_context_enrichers(self, context: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "world_snapshot": dict(context.get("world_snapshot") or {}),
            "scope_ref": context.get("scope_ref"),
            "scope_kind": context.get("scope_kind"),
            "recent_events": list(context.get("recent_events") or []),
            "available_tools": list(context.get("available_tools") or []),
            "available_mcps": list(context.get("available_mcps") or []),
            "hash": context.get("hash"),
            "input": context.get("input"),
        }
        world_snapshot = cast(dict[str, Any], payload["world_snapshot"])
        for namespace, enricher in self._context_enrichers:
            result = await _maybe_await(enricher(context))
            world_snapshot[f"plugin_{namespace}"] = dict(result or {})
        return payload

    def run_context_enrichers_sync(self, context: dict[str, Any]) -> dict[str, Any]:
        return run_awaitable_blocking(lambda: self.run_context_enrichers(context))

    async def run_guard_checks(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        verdicts: list[dict[str, Any]] = []
        for _namespace, check in self._guard_checks:
            verdict = await _maybe_await(check(tool_name, arguments, context))
            verdicts.append(dict(verdict or {}))
        return verdicts

    def run_guard_checks_sync(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return run_awaitable_blocking(lambda: self.run_guard_checks(tool_name, arguments, context))

    def collect_persona_fragments(self) -> list[str]:
        return [text for _namespace, _label, text in self._persona_fragments]


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value
