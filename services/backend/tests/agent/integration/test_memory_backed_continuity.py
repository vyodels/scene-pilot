from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from scene_pilot.agents.autonomous import AutonomousAgent
from scene_pilot.core.settings import AppSettings
from scene_pilot.db.session import create_engine_from_settings, create_session_factory, initialize_database
from scene_pilot.kernel.kernel import AgentKernel
from scene_pilot.models.domain import AgentRun, AgentSession, Candidate, RecruitAgentProfile
from scene_pilot.plugins.host import PluginHost
from scene_pilot.runtime.models import LLMResponse, Message
from scene_pilot.runtime.providers import LLMProvider
from scene_pilot.runtime.tools import ToolRegistry, register_core_tools


class ContinuityProvider:
    provider_name = "continuity"

    def __init__(self) -> None:
        self.calls = 0

    def generate(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, object]] | None = None,
        task: dict[str, object] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        cancel_token=None,
    ) -> LLMResponse:
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(content="Candidate already replied and asked for a resume review.")
        payload = json.loads(messages[-1].content)
        serialized = json.dumps(payload, ensure_ascii=False)
        if "resume review" in serialized:
            return LLMResponse(content="continued")
        return LLMResponse(content="lost")


def _make_session(tmp_path: Path) -> Session:
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'memory-continuity.db'}",
    )
    engine = create_engine_from_settings(settings)
    initialize_database(engine)
    return create_session_factory(engine)()


def test_autonomous_memory_backed_continuity_across_turns(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    try:
        profile = RecruitAgentProfile(agent_key="primary", name="Primary", is_primary=True)
        candidate = Candidate(name="Alice")
        session.add_all([profile, candidate])
        session.flush()

        agent_session = AgentSession(agent_profile_id=profile.id)
        session.add(agent_session)
        session.flush()

        run = AgentRun(
            session_id=agent_session.id,
            run_id="run-memory",
            agent_kind="autonomous",
            status="queued",
            person_id=candidate.candidate_person_id,
        )
        session.add(run)
        session.commit()

        tools = ToolRegistry()
        register_core_tools(tools)
        provider = ContinuityProvider()
        kernel = AgentKernel(provider=provider, tool_registry=tools, plugin_host=PluginHost())
        agent = AutonomousAgent(session_factory=create_session_factory(session.get_bind()), kernel=kernel)

        first = agent.run_turn_from_envelope(
            {
                "run_pk": run.id,
                "scope_kind": "candidate",
                "scope_ref": candidate.candidate_person_id,
                "world_snapshot": {"candidate_stage": "replied"},
            }
        )
        second = agent.run_turn_from_envelope(
            {
                "run_pk": run.id,
                "scope_kind": "candidate",
                "scope_ref": candidate.candidate_person_id,
                "world_snapshot": {"candidate_stage": "follow_up"},
            }
        )

        assert first.final_output.startswith("Candidate already replied")
        assert second.final_output == "continued"
    finally:
        session.close()
