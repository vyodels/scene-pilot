from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from recruit_agent.agents.autonomous import AutonomousAdapter
from recruit_agent.agent_runtime.types import LLMInvocationResult, LLMMessage, LLMRequest, LLMResponse as RuntimeLLMResponse
from recruit_agent.core.settings import AppSettings
from recruit_agent.db.session import create_engine_from_settings, create_session_factory, initialize_database
from recruit_agent.memory.filesystem import MemoryFileStore
from recruit_agent.models.domain import AgentRun, AgentSession, Candidate, RecruitAgentProfile
from recruit_agent.plugins.host import PluginHost
from recruit_agent.agent_runtime.providers import LLMProvider
from recruit_agent.capabilities.tools import ToolRegistry, register_core_tools


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
            content = json.dumps(
                {
                    "status": "completed",
                    "summary": "Candidate already replied and asked for a resume review.",
                },
                ensure_ascii=False,
            )
        elif self.calls == 2:
            content = json.dumps(
                {
                    "stable_facts": [
                        {
                            "summary": "Candidate already replied and asked for a resume review.",
                            "content": {"fact": "Candidate already replied and asked for a resume review."},
                            "confidence": 0.8,
                        }
                    ],
                },
                ensure_ascii=False,
            )
        elif self.calls == 3:
            payload = json.loads(str(request.messages[-1].content))
            serialized = json.dumps(payload, ensure_ascii=False)
            content = "continued" if "resume review" in serialized else "lost"
        else:
            content = '{"stable_facts":[]}'
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
        memory_store = MemoryFileStore(tmp_path / "memory-files")
        agent = AutonomousAdapter(
            session_factory=create_session_factory(session.get_bind()),
            provider=provider,
            tool_registry=tools,
            plugin_host=PluginHost(),
            memory_file_store=memory_store,
        )

        first = agent.run_turn_from_envelope(
            {
                "run_pk": run.id,
                "scope_kind": "candidate",
                "scope_ref": candidate.candidate_person_id,
                "world_snapshot": {"candidate_stage": "replied"},
                "memory_writeback": {"force": True},
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

        assert "Candidate already replied" in first.final_output
        assert second.final_output == "continued"
    finally:
        session.close()


def test_autonomous_memory_writeback_does_not_call_llm_on_every_completed_turn(tmp_path: Path) -> None:
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
            run_id="run-memory-gated",
            agent_kind="autonomous",
            status="queued",
            person_id=candidate.candidate_person_id,
        )
        session.add(run)
        session.commit()

        tools = ToolRegistry()
        register_core_tools(tools)
        provider = ContinuityProvider()
        memory_store = MemoryFileStore(tmp_path / "memory-files")
        agent = AutonomousAdapter(
            session_factory=create_session_factory(session.get_bind()),
            provider=provider,
            tool_registry=tools,
            plugin_host=PluginHost(),
            memory_file_store=memory_store,
        )

        first = agent.run_turn_from_envelope(
            {
                "run_pk": run.id,
                "scope_kind": "candidate",
                "scope_ref": candidate.candidate_person_id,
                "world_snapshot": {"candidate_stage": "replied"},
            }
        )

        assert "Candidate already replied" in first.final_output
        assert provider.calls == 1
        assert memory_store.list_files(
            scope_kind="candidate",
            scope_ref=candidate.candidate_person_id,
            agent_profile_id=profile.id,
        ) == []
    finally:
        session.close()
