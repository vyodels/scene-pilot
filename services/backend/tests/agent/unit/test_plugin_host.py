from __future__ import annotations

import asyncio

from fastapi import APIRouter

from recruit_agent.plugins.host import PluginHost
from recruit_agent.plugins.loader import install_manifest
from recruit_agent.runtime.tools import ToolDefinition
from recruit_agent.agent_runtime.models import GuardVerdict, Observation


def test_plugin_host_registers_and_runs_extensions() -> None:
    host = PluginHost()
    router = APIRouter()

    host.register_tools(
        "demo",
        [
            ToolDefinition(
                name="demo.echo",
                description="Echo a value.",
                parameters={"type": "object"},
                handler=lambda args: {"echo": args},
            )
        ],
    )
    host.register_persona_fragment("demo", "operator", "Keep updates concise.")
    host.register_router("demo", router)

    async def _enricher(observation: Observation) -> dict[str, object]:
        return {"plugin": "demo", "scope": observation.scope_ref}

    async def _guard(tool_name: str, arguments: dict[str, object], observation: Observation) -> GuardVerdict:
        return GuardVerdict(
            allowed=tool_name != "demo.blocked",
            reason="blocked" if tool_name == "demo.blocked" else None,
            metadata={"scope": observation.scope_ref, "arguments": arguments},
        )

    host.register_observation_enricher("demo", _enricher)
    host.register_guard_check("demo", _guard)

    observation = Observation(
        world_snapshot={"seed": True},
        scope_ref="candidate-1",
        scope_kind="candidate",
        recent_events=[],
        available_tools=[],
        available_skills=[],
        available_mcps=[],
        hash="obs-1",
    )

    enriched = host.run_observation_enrichers_sync(observation)
    verdicts = host.run_guard_checks_sync("demo.echo", {"note": "hi"}, observation)

    assert "demo.echo" in host.tool_registry.tools
    assert host.collect_persona_fragments() == ["Keep updates concise."]
    assert enriched["world_snapshot"]["plugin_demo"] == {"plugin": "demo", "scope": "candidate-1"}
    assert verdicts[0].allowed is True
    assert host.routers == [router]


def test_plugin_host_sync_helpers_work_inside_running_event_loop() -> None:
    host = PluginHost()

    async def _enricher(observation: Observation) -> dict[str, object]:
        return {"scope": observation.scope_ref}

    async def _guard(tool_name: str, arguments: dict[str, object], observation: Observation) -> GuardVerdict:
        return GuardVerdict(allowed=True, metadata={"tool": tool_name, "scope": observation.scope_ref})

    host.register_observation_enricher("demo", _enricher)
    host.register_guard_check("demo", _guard)
    observation = Observation(scope_ref="candidate-1", scope_kind="candidate")

    async def _scenario():
        return (
            host.run_observation_enrichers_sync(observation),
            host.run_guard_checks_sync("demo.echo", {}, observation),
        )

    enriched, verdicts = asyncio.run(_scenario())

    assert enriched["world_snapshot"]["plugin_demo"] == {"scope": "candidate-1"}
    assert verdicts[0].allowed is True
    assert verdicts[0].metadata == {"tool": "demo.echo", "scope": "candidate-1"}


def test_plugin_loader_calls_manifest_install() -> None:
    host = PluginHost()
    installed: list[str] = []

    class DemoManifest:
        namespace = "demo"

        def install(self, plugin_host: PluginHost) -> None:
            installed.append(self.namespace)
            plugin_host.register_persona_fragment(self.namespace, "summary", "Installed.")

    install_manifest(host, DemoManifest())

    assert installed == ["demo"]
    assert host.collect_persona_fragments() == ["Installed."]
