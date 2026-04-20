from __future__ import annotations

from pathlib import Path
from threading import Event, Thread

from sqlalchemy import select
from sqlalchemy.orm import Session

from scene_pilot.agents.autonomous import AutonomousAgent
from scene_pilot.agents.heartbeat import Heartbeat
from scene_pilot.core.settings import AppSettings
from scene_pilot.db.session import create_engine_from_settings, create_session_factory, initialize_database
from scene_pilot.kernel.kernel import AgentKernel
from scene_pilot.models.domain import AgentRun, AgentRuntimeEvent, AgentSession, AgentTurnRecord, GoalSpec, RecruitAgentProfile
from scene_pilot.plugins.host import PluginHost
from scene_pilot.repositories.domain import TaskQueueRepository
from scene_pilot.runtime.models import LLMResponse, Message
from scene_pilot.runtime.tools import ToolRegistry, register_core_tools


class BlockingProvider:
    provider_name = "blocking"

    def __init__(self) -> None:
        self.entered = Event()
        self.release = Event()

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
        self.entered.set()
        assert self.release.wait(timeout=5.0), "provider release was not signalled in time"
        return LLMResponse(content="completed")


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
