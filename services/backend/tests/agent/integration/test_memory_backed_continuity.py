from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from recruit_agent.agents.autonomous import AutonomousAgent
from recruit_agent.agent_runtime.types import LLMInvocationResult, LLMMessage, LLMRequest, LLMResponse as RuntimeLLMResponse
from recruit_agent.core.settings import AppSettings
from recruit_agent.db.session import create_engine_from_settings, create_session_factory, initialize_database
from recruit_agent.agent_runtime.kernel import AgentKernel
from recruit_agent.models.domain import AgentRun, AgentSession, Candidate, RecruitAgentProfile
from recruit_agent.plugins.host import PluginHost
from recruit_agent.agent_runtime.providers import LLMProvider
from recruit_agent.runtime.tools import ToolRegistry, register_core_tools


class ContinuityProvider:
    provider_name = "continuity"

    def __init__(self) -> None:
        self.calls = 0

    def invoke(
        self,
        request: LLMRequest,
    ) -> LLMInvocationResult:
        self.calls += 1
        if self.calls == 1:
            content = "Candidate already replied and asked for a resume review."
        else:
            payload = json.loads(str(request.messages[-1].content))
            serialized = json.dumps(payload, ensure_ascii=False)
            content = "continued" if "resume review" in serialized else "lost"
        return LLMInvocationResult(
            events=[],
            response=RuntimeLLMResponse(
                id=f"resp-{self.calls}",
                request_id=request.id,
                invocation_id=request.invocation_id,
                assistant_message=LLMMessage(role="assistant", content=content),
            ),
        )


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
