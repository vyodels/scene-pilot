from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from recruit_station.agents.autonomous import AutonomousAdapter
from recruit_station.agents.heartbeat import Heartbeat
from recruit_station.core.settings import AppSettings
from recruit_station.db.base import utcnow
from recruit_station.db.session import create_engine_from_settings, create_session_factory, initialize_database
from recruit_station.models.domain import AgentGlobalState, AgentRun, AgentSession, Candidate, AgentDefinition
from recruit_station.plugins.host import PluginHost
from recruit_station.repositories.domain import TaskQueueRepository
from agent_runtime.fixtures import LLMResponse
from agent_runtime.fixtures import ScriptedProvider
from recruit_station.capabilities.tools import ToolRegistry, register_core_tools


def _make_session(tmp_path: Path) -> Session:
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'heartbeat.db'}",
    )
    engine = create_engine_from_settings(settings)
    initialize_database(engine)
    return create_session_factory(engine)()


def test_heartbeat_claims_task_and_runs_autonomous_turn(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    try:
        definition = AgentDefinition(definition_key="primary", name="Primary", is_primary=True)
        candidate = Candidate(name="Alice")
        session.add_all([definition, candidate])
        session.flush()

        agent_session = AgentSession(agent_definition_id=definition.id)
        session.add(agent_session)
        session.flush()

        run = AgentRun(
            session_id=agent_session.id,
            run_id="run-1",
            agent_kind="autonomous",
            status="queued",
            person_id=candidate.candidate_person_id,
        )
        session.add(run)
        session.commit()

        TaskQueueRepository(session).enqueue(
            task_id="task-1",
            task_type="autonomous_turn",
            payload={
                "run_pk": run.id,
                "trigger_type": "heartbeat",
                "scope_kind": "candidate",
                "scope_ref": candidate.candidate_person_id,
                "world_snapshot": {"candidate": "ready"},
            },
        )

        provider = ScriptedProvider(provider_name="scripted", responses=[LLMResponse(content="completed")])
        tools = ToolRegistry()
        register_core_tools(tools)
        agent = AutonomousAdapter(
            session_factory=create_session_factory(session.get_bind()),
            provider=provider,
            tool_registry=tools,
            plugin_host=PluginHost(),
        )
        heartbeat = Heartbeat(session_factory=create_session_factory(session.get_bind()), autonomous_adapter=agent)
        heartbeat.start(updated_by="api-test", reason="test start")

        result = heartbeat.run_once()

        session.expire_all()
        assert result["status"] == "processed"
        assert TaskQueueRepository(session).get("task-1").status == "completed"
        assert session.get(AgentRun, run.id).status == "idle"
    finally:
        session.close()


def test_heartbeat_honors_global_pause(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    try:
        session.add(AgentGlobalState(id="singleton", autonomous_paused=True, pause_reason="human"))
        session.commit()

        provider = ScriptedProvider(provider_name="scripted", responses=[LLMResponse(content="completed")])
        tools = ToolRegistry()
        register_core_tools(tools)
        agent = AutonomousAdapter(
            session_factory=create_session_factory(session.get_bind()),
            provider=provider,
            tool_registry=tools,
            plugin_host=PluginHost(),
        )
        heartbeat = Heartbeat(session_factory=create_session_factory(session.get_bind()), autonomous_adapter=agent)

        result = heartbeat.run_once()

        assert result["status"] == "paused"
        assert result["reason"] == "human"
    finally:
        session.close()


def test_heartbeat_does_not_claim_jd_sync_task_while_paused(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    try:
        definition = AgentDefinition(definition_key="primary", name="Primary", is_primary=True)
        session.add(definition)
        session.flush()
        agent_session = AgentSession(agent_definition_id=definition.id)
        session.add(agent_session)
        session.flush()
        run = AgentRun(
            session_id=agent_session.id,
            run_id="jd-run-paused",
            agent_kind="jd_sync",
            status="queued",
        )
        session.add(run)
        session.add(
            AgentGlobalState(
                id="singleton",
                autonomous_paused=True,
                pause_reason="operator pause",
                state_metadata={"workspace_control": {"state": "paused", "reason": "operator pause"}},
            )
        )
        session.commit()
        TaskQueueRepository(session).enqueue(
            task_id="jd-task-paused",
            task_type="autonomous_turn",
            payload={"run_pk": run.id, "run_id": run.run_id, "agent_kind": "jd_sync"},
        )

        agent = AutonomousAdapter(
            session_factory=create_session_factory(session.get_bind()),
            provider=ScriptedProvider(provider_name="scripted", responses=[LLMResponse(content="should not run")]),
            tool_registry=ToolRegistry(),
            plugin_host=PluginHost(),
        )
        heartbeat = Heartbeat(session_factory=create_session_factory(session.get_bind()), autonomous_adapter=agent)

        result = heartbeat.run_once()

        session.expire_all()
        task = TaskQueueRepository(session).get("jd-task-paused")
        assert result == {"status": "paused", "reason": "operator pause"}
        assert task is not None
        assert task.status == "pending"
        assert task.locked_by is None
        assert session.get(AgentRun, run.id).status == "queued"
    finally:
        session.close()


def test_autonomous_recover_stale_interrupts_run_and_clears_running_queue_task(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    try:
        definition = AgentDefinition(definition_key="primary", name="Primary", is_primary=True)
        session.add(definition)
        session.flush()
        agent_session = AgentSession(agent_definition_id=definition.id)
        session.add(agent_session)
        session.flush()
        run = AgentRun(
            session_id=agent_session.id,
            run_id="run-stale",
            agent_kind="jd_sync",
            status="running",
            queue_task_id="task-stale",
        )
        session.add(run)
        session.commit()
        task = TaskQueueRepository(session).enqueue(
            task_id="task-stale",
            task_type="autonomous_turn",
            payload={"run_pk": run.id, "run_id": run.run_id},
            status="running",
        )
        task.locked_by = "heartbeat"
        task.locked_at = utcnow() - timedelta(minutes=10)
        session.commit()

        agent = AutonomousAdapter(
            session_factory=create_session_factory(session.get_bind()),
            provider=ScriptedProvider(provider_name="scripted", responses=[]),
            tool_registry=ToolRegistry(),
            plugin_host=PluginHost(),
        )

        assert agent.recover_stale() == 1

        session.expire_all()
        refreshed_run = session.get(AgentRun, run.id)
        refreshed_task = TaskQueueRepository(session).get("task-stale")
        assert refreshed_run is not None
        assert refreshed_task is not None
        assert refreshed_run.status == "interrupted"
        assert refreshed_run.last_error == "Recovered stale autonomous run during startup."
        assert refreshed_task.status == "failed"
        assert refreshed_task.locked_by is None
        assert refreshed_task.locked_at is None
    finally:
        session.close()


def test_heartbeat_records_browser_hid_readiness_and_still_runs_agent(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    try:
        definition = AgentDefinition(definition_key="primary", name="Primary", is_primary=True)
        session.add(definition)
        session.flush()
        agent_session = AgentSession(agent_definition_id=definition.id)
        session.add(agent_session)
        session.flush()
        run = AgentRun(
            session_id=agent_session.id,
            run_id="run-preflight",
            agent_kind="autonomous",
            status="queued",
        )
        session.add(run)
        session.commit()

        TaskQueueRepository(session).enqueue(
            task_id="task-preflight",
            task_type="autonomous_turn",
            payload={
                "run_pk": run.id,
                "preferred_capabilities": ["browser", "computer"],
                "browser_target": {"url": "https://recruit.example.test/jobs"},
            },
        )

        class FakeRegistry:
            def browser_hid_preflight(self) -> dict[str, object]:
                return {"ok": False, "status": "blocked", "missing": ["browser-mcp"], "checks": []}

        captured_payloads: list[dict[str, object]] = []

        class FakeAdapter:
            mcp_registry = FakeRegistry()

            def run_turn_from_envelope(self, payload: dict[str, object]) -> None:
                captured_payloads.append(dict(payload))

        heartbeat = Heartbeat(session_factory=create_session_factory(session.get_bind()), autonomous_adapter=FakeAdapter())  # type: ignore[arg-type]
        heartbeat.start(updated_by="api-test", reason="test start")

        result = heartbeat.run_once()

        session.expire_all()
        assert result["status"] == "processed"
        assert TaskQueueRepository(session).get("task-preflight").status == "completed"
        blocked_run = session.get(AgentRun, run.id)
        assert blocked_run.status == "queued"
        assert blocked_run.blocked_reason is None
        assert blocked_run.runtime_metadata["mcp_readiness"]["missing"] == ["browser-mcp"]
        assert captured_payloads
        assert captured_payloads[0]["metadata"]["mcp_readiness"]["missing"] == ["browser-mcp"]
        assert captured_payloads[0]["constraints"]["mcp_readiness"]["missing"] == ["browser-mcp"]
    finally:
        session.close()


def test_heartbeat_defers_when_hourly_unique_candidate_budget_is_exhausted(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    try:
        definition = AgentDefinition(definition_key="primary", name="Primary", is_primary=True)
        candidate_1 = Candidate(name="Alice")
        candidate_2 = Candidate(name="Bob")
        session.add_all([definition, candidate_1, candidate_2])
        session.flush()
        agent_session = AgentSession(agent_definition_id=definition.id)
        session.add(agent_session)
        session.flush()
        now = utcnow()
        historical = AgentRun(
            session_id=agent_session.id,
            run_id="run-hourly-used",
            agent_kind="autonomous",
            status="completed",
            person_id=candidate_1.candidate_person_id,
            started_at=now - timedelta(minutes=20),
            finished_at=now - timedelta(minutes=19),
        )
        run = AgentRun(
            session_id=agent_session.id,
            run_id="run-hourly-current",
            agent_kind="autonomous",
            status="queued",
            person_id=candidate_2.candidate_person_id,
        )
        session.add_all([historical, run])
        session.commit()
        TaskQueueRepository(session).enqueue(
            task_id="task-hourly-budget",
            task_type="autonomous_turn",
            payload={"run_pk": run.id, "scope_kind": "candidate", "scope_ref": candidate_2.candidate_person_id},
        )

        class FakeAdapter:
            behavior_budget = {"max_candidates_per_hour": 1, "max_candidates_per_day": 100}

            def run_turn_from_envelope(self, _payload: dict[str, object]) -> None:
                raise AssertionError("autonomous turn must not run when hourly candidate budget is exhausted")

        heartbeat = Heartbeat(session_factory=create_session_factory(session.get_bind()), autonomous_adapter=FakeAdapter())  # type: ignore[arg-type]
        heartbeat.start(updated_by="api-test", reason="test start")

        result = heartbeat.run_once()

        session.expire_all()
        task = TaskQueueRepository(session).get("task-hourly-budget")
        marker = session.get(AgentRun, run.id).runtime_metadata["behavior_budget_defer"]
        assert result["status"] == "deferred"
        assert result["reason"] == "behavior_budget_defer"
        assert task.status == "pending"
        assert task.scheduled_for is not None
        assert task.scheduled_for > int(now.timestamp())
        assert marker["window"] == "hourly"
        assert marker["limit"] == 1
        assert marker["candidate_ref"] == candidate_2.candidate_person_id
    finally:
        session.close()


def test_heartbeat_defers_when_daily_unique_application_budget_is_exhausted(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    try:
        definition = AgentDefinition(definition_key="primary", name="Primary", is_primary=True)
        session.add(definition)
        session.flush()
        agent_session = AgentSession(agent_definition_id=definition.id)
        session.add(agent_session)
        session.flush()
        now = utcnow()
        historical = AgentRun(
            session_id=agent_session.id,
            run_id="run-daily-used",
            agent_kind="autonomous",
            status="completed",
            runtime_metadata={"application_id": "app-used"},
            started_at=now - timedelta(hours=2),
            finished_at=now - timedelta(hours=2),
        )
        run = AgentRun(
            session_id=agent_session.id,
            run_id="run-daily-current",
            agent_kind="autonomous",
            status="queued",
            runtime_metadata={"application_id": "app-current"},
        )
        session.add_all([historical, run])
        session.commit()
        TaskQueueRepository(session).enqueue(
            task_id="task-daily-budget",
            task_type="autonomous_turn",
            payload={"run_pk": run.id, "application_id": "app-current"},
        )

        class FakeAdapter:
            behavior_budget = {"max_candidates_per_hour": 100, "max_candidates_per_day": 1}

            def run_turn_from_envelope(self, _payload: dict[str, object]) -> None:
                raise AssertionError("autonomous turn must not run when daily candidate budget is exhausted")

        heartbeat = Heartbeat(session_factory=create_session_factory(session.get_bind()), autonomous_adapter=FakeAdapter())  # type: ignore[arg-type]
        heartbeat.start(updated_by="api-test", reason="test start")

        result = heartbeat.run_once()

        session.expire_all()
        task = TaskQueueRepository(session).get("task-daily-budget")
        marker = session.get(AgentRun, run.id).runtime_metadata["behavior_budget_defer"]
        assert result["status"] == "deferred"
        assert result["reason"] == "behavior_budget_defer"
        assert task.status == "pending"
        assert task.scheduled_for is not None
        assert task.scheduled_for > int(now.timestamp())
        assert marker["window"] == "daily"
        assert marker["limit"] == 1
        assert marker["candidate_ref_kind"] == "application"
        assert marker["candidate_ref"] == "app-current"
    finally:
        session.close()
