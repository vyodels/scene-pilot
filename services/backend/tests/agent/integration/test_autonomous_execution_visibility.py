from __future__ import annotations

from pathlib import Path
from threading import Event, Thread

from sqlalchemy import select
from sqlalchemy.orm import Session

from recruit_agent.agents.autonomous import AutonomousAgent
from recruit_agent.agents.heartbeat import Heartbeat
from recruit_agent.agent_runtime.types import LLMInvocationResult, LLMMessage, LLMRequest, LLMResponse as RuntimeLLMResponse
from recruit_agent.core.settings import AppSettings
from recruit_agent.db.session import create_engine_from_settings, create_session_factory, initialize_database
from recruit_agent.agent_runtime.kernel import AgentKernel
from recruit_agent.models.domain import (
    AgentRun,
    AgentRunCheckpoint,
    AgentRuntimeEvent,
    AgentSession,
    AgentTurnRecord,
    ApprovalItem,
    Candidate,
    CandidateApplication,
    GoalSpec,
    OperatorInteraction,
    RecruitAgentProfile,
)
from recruit_agent.plugins.host import PluginHost
from recruit_agent.repositories.domain import TaskQueueRepository
from recruit_agent.agent_runtime.models import GuardVerdict, LLMResponse, ToolCall
from recruit_agent.runtime.tools import ToolRegistry, register_core_tools
from agent_runtime.fixtures import ScriptedProvider
from recruit_agent.runtime.tools import ToolDefinition


class BlockingProvider:
    provider_name = "blocking"

    def __init__(self) -> None:
        self.entered = Event()
        self.release = Event()

    def invoke(
        self,
        request: LLMRequest,
    ) -> LLMInvocationResult:
        self.entered.set()
        assert self.release.wait(timeout=5.0), "provider release was not signalled in time"
        return LLMInvocationResult(
            events=[],
            response=RuntimeLLMResponse(
                id="resp-blocking",
                request_id=request.id,
                invocation_id=request.invocation_id,
                assistant_message=LLMMessage(role="assistant", content="completed"),
            ),
        )


def _make_session(tmp_path: Path) -> Session:
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'autonomous-visibility.db'}",
    )
    engine = create_engine_from_settings(settings)
    initialize_database(engine)
    return create_session_factory(engine)()


def test_heartbeat_persists_running_state_and_progress_events_before_completion(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    try:
        profile = RecruitAgentProfile(agent_key="autonomous", name="Autonomous", is_primary=True)
        session.add(profile)
        session.flush()

        agent_session = AgentSession(agent_profile_id=profile.id, session_key="primary")
        session.add(agent_session)
        session.flush()

        goal = GoalSpec(
            agent_profile_id=profile.id,
            title="同步 JD（初始）",
            goal_text="同步全部 JD。",
            goal_kind="sync_jd_initial",
            status="queued",
            source="operator",
            source_text="同步全部 JD。",
            requested_by="test-user",
            constraints={
                "scope_kind": "global",
                "memory_scope_kind": "global",
                "memory_scope_ref": profile.id,
                "global_scope_ref": profile.id,
            },
        )
        session.add(goal)
        session.flush()

        run = AgentRun(
            session_id=agent_session.id,
            goal_spec_id=goal.id,
            run_id="run-visible-1",
            agent_kind="autonomous",
            status="queued",
            checkpoint_status="none",
            context_manifest={"goal": goal.goal_text, "title": goal.title},
            runtime_metadata={"goal_title": goal.title, "conversation_id": goal.id},
        )
        session.add(run)
        session.commit()

        TaskQueueRepository(session).enqueue(
            task_id="task-visible-1",
            task_type="autonomous_turn",
            payload={
                "run_pk": run.id,
                "run_id": run.run_id,
                "trigger_type": "heartbeat",
                "scope_kind": "global",
                "scope_ref": profile.id,
                "world_snapshot": {"goal": goal.title},
            },
        )

        provider = BlockingProvider()
        tools = ToolRegistry()
        register_core_tools(tools)
        kernel = AgentKernel(provider=provider, tool_registry=tools, plugin_host=PluginHost())
        session_factory = create_session_factory(session.get_bind())
        agent = AutonomousAgent(session_factory=session_factory, kernel=kernel)
        heartbeat = Heartbeat(session_factory=session_factory, autonomous_agent=agent)

        result_holder: dict[str, object] = {}

        def _run_once() -> None:
            result_holder["result"] = heartbeat.run_once()

        worker = Thread(target=_run_once, daemon=True)
        worker.start()

        assert provider.entered.wait(timeout=2.0), "provider did not start in time"
        with session_factory() as observe:
            observe_run = observe.get(AgentRun, run.id)
            assert observe_run is not None
            assert observe_run.status == "running"
            assert observe_run.started_at is not None

            observe_goal = observe.get(GoalSpec, goal.id)
            assert observe_goal is not None
            assert observe_goal.status == "running"

            turns = observe.scalars(
                select(AgentTurnRecord)
                .where(AgentTurnRecord.run_pk == run.id)
                .order_by(AgentTurnRecord.seq.asc(), AgentTurnRecord.id.asc())
            ).all()
            assert len(turns) == 1
            assert turns[0].status == "started"

            event_types = [
                item.event_type
                for item in observe.scalars(
                    select(AgentRuntimeEvent)
                    .where(AgentRuntimeEvent.run_id == run.id)
                    .order_by(AgentRuntimeEvent.occurred_at.asc(), AgentRuntimeEvent.id.asc())
                ).all()
            ]
            assert "turn.started" in event_types
            assert "round.started" in event_types
            assert "provider.started" in event_types

        provider.release.set()
        worker.join(timeout=2.0)
        assert not worker.is_alive()

        session.expire_all()
        assert result_holder["result"] == {"status": "processed", "task_id": "task-visible-1"}
        assert session.get(AgentRun, run.id).status == "completed"
        assert TaskQueueRepository(session).get("task-visible-1").status == "completed"
    finally:
        session.close()


def test_wait_human_records_keep_application_subject_when_run_has_application_scope(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    try:
        profile = RecruitAgentProfile(agent_key="autonomous", name="Autonomous", is_primary=True)
        session.add(profile)
        session.flush()

        candidate = Candidate(
            name="Visibility Test Candidate",
            platform="site",
            platform_candidate_id="visibility-test-candidate",
        )
        session.add(candidate)
        session.flush()

        application = CandidateApplication(
            candidate_application_id="app-123",
            person_id=candidate.id,
            platform="site",
            source_platform="site",
            application_window="visibility-test-window",
            current_status="discovered",
        )
        session.add(application)
        session.flush()

        agent_session = AgentSession(agent_profile_id=profile.id, session_key="primary")
        session.add(agent_session)
        session.flush()

        goal = GoalSpec(
            agent_profile_id=profile.id,
            title="Follow one application",
            goal_text="Continue one application follow-up and wait for approval before outreach.",
            goal_kind="candidate_outreach",
            status="queued",
            source="operator",
            source_text="Continue one application follow-up.",
            requested_by="test-user",
            constraints={"application_id": "app-123"},
        )
        session.add(goal)
        session.flush()

        run = AgentRun(
            session_id=agent_session.id,
            goal_spec_id=goal.id,
            run_id="run-wait-human-app",
            agent_kind="autonomous",
            status="queued",
            checkpoint_status="none",
            person_id=None,
            context_manifest={"goal": goal.goal_text, "title": goal.title, "application_id": "app-123"},
            runtime_metadata={"goal_title": goal.title, "application_id": "app-123"},
        )
        session.add(run)
        session.commit()

        tools = ToolRegistry()
        register_core_tools(tools)
        tools.register(
            ToolDefinition(
                name="needs.approval",
                description="Tool that requires operator confirmation.",
                parameters={"type": "object", "additionalProperties": True},
                handler=lambda arguments: {"ok": arguments["value"]},
                category="plugin",
                external_target=False,
                resource_target_kind="application",
            )
        )
        plugin_host = PluginHost()
        plugin_host.register_guard_check(
            "test-wait-human-app-scope",
            lambda tool_name, _arguments, _observation: GuardVerdict(
                allowed=tool_name != "needs.approval",
                reason="requires_operator_confirmation",
                severity="waiting_human",
            ),
        )
        provider = ScriptedProvider(
            provider_name="scripted",
            responses=[
                LLMResponse(
                    tool_calls=[ToolCall(id="tool-1", name="needs.approval", arguments={"value": "hello"})],
                    finish_reason="tool_calls",
                )
            ],
        )
        kernel = AgentKernel(provider=provider, tool_registry=tools, plugin_host=plugin_host)
        agent = AutonomousAgent(session_factory=create_session_factory(session.get_bind()), kernel=kernel)

        outcome = agent.run_turn_from_envelope(
            {
                "run_pk": run.id,
                "scope_kind": "application",
                "scope_ref": "app-123",
                "application_id": "app-123",
                "world_snapshot": {"application_id": "app-123"},
            }
        )

        assert outcome.status == "wait_human"
        session.expire_all()
        refreshed_run = session.get(AgentRun, run.id)
        assert refreshed_run is not None
        assert refreshed_run.application_id == "app-123"
        assert refreshed_run.runtime_metadata["application_id"] == "app-123"

        approval = session.query(ApprovalItem).filter_by(run_pk=run.id, status="pending").one()
        checkpoint = session.query(AgentRunCheckpoint).filter_by(run_id=run.id, status="open").one()
        interaction = session.query(OperatorInteraction).filter_by(run_id=run.id, status="pending").one()
        events = session.scalars(
            select(AgentRuntimeEvent)
            .where(AgentRuntimeEvent.run_id == run.id)
            .order_by(AgentRuntimeEvent.occurred_at.asc(), AgentRuntimeEvent.id.asc())
        ).all()

        assert approval.payload["application_id"] == "app-123"
        assert approval.payload["resume_task"]["application_id"] == "app-123"
        assert approval.payload["resume_task"]["payload"]["application_id"] == "app-123"
        assert checkpoint.application_id == "app-123"
        assert checkpoint.payload["application_id"] == "app-123"
        assert interaction.application_id == "app-123"
        assert interaction.interaction_metadata["application_id"] == "app-123"
        assert all(item.payload.get("application_id") == "app-123" for item in events)
    finally:
        session.close()
