from __future__ import annotations

import os
from pathlib import Path
import time

from fastapi.testclient import TestClient

from scene_pilot.api.routers.agent import AUTONOMOUS_PRIMARY_CONVERSATION_ID
from scene_pilot.core.settings import load_settings
from scene_pilot.models.domain import (
    AgentGlobalMemory,
    AgentRun,
    AgentRunCheckpoint,
    AgentRuntimeEvent,
    AgentSession,
    AgentTurnRecord,
    ApprovalItem,
    Candidate,
    CandidatePersonMemory,
    ConversationSession,
    ConversationTurn,
    GoalSpec,
    JobDescription,
    JobDescriptionMemory,
    McpServer,
    OperatorInteraction,
    RecruitAgentProfile,
    Skill,
)
from scene_pilot.runtime.models import GuardVerdict, LLMResponse, ToolCall
from scene_pilot.runtime.providers import ScriptedProvider
from scene_pilot.runtime.tools import ToolDefinition
from scene_pilot.server import create_app


def _build_client(tmp_path: Path) -> tuple[TestClient, object]:
    os.environ["RECRUIT_AGENT_DATA_DIR"] = str(tmp_path)
    load_settings.cache_clear()
    app = create_app()
    client = TestClient(app)
    return client, app


def test_agents_routes_expose_builtin_profiles_and_runtime_collections(tmp_path: Path) -> None:
    client, app = _build_client(tmp_path)
    client.__enter__()
    try:
        expected_global_memory_summary = "尚未沉淀长期可复用的全局业务知识。"
        autonomous_global_memory_seed = (
            '{"status":"blocked","created":0,"updated":0,"skipped":0,"blocked":1,'
            '"evidence":["当前浏览器仅有 1 个标签页：\'CLI Proxy API Management Center\'",'
            '"活动页 URL: http://127.0.0.1:8317/management.html#/auth-files"],'
            '"next_step":"Agent 应先复用现有页面或自行打开招聘平台页面，再继续同步。"}'
        )
        assistant_agent = app.state.container.assistant_agent
        conversation = assistant_agent.create_conversation(user_id="desktop-user", title="Desk chat")
        assistant_agent.session_store.append_turn(
            conversation.conversation_id,
            role="assistant",
            content={"text": "Workspace ready."},
            status="completed",
        )

        session_factory = app.state.session_factory
        with session_factory() as session:
            autonomous = session.query(RecruitAgentProfile).filter_by(agent_key="autonomous").one()
            assistant = session.query(RecruitAgentProfile).filter_by(agent_key="assistant").one()

            candidate = Candidate(name="Alice")
            job = JobDescription(title="Backend Engineer")
            session.add_all([candidate, job])
            session.flush()

            session.add_all(
                [
                    CandidatePersonMemory(
                        agent_profile_id=autonomous.id,
                        person_id=candidate.id,
                        summary="autonomous candidate memory",
                        content={"owner": "autonomous"},
                        raw_content={"owner": "autonomous"},
                    ),
                    CandidatePersonMemory(
                        agent_profile_id=assistant.id,
                        person_id=candidate.id,
                        summary="assistant candidate memory",
                        content={"owner": "assistant"},
                        raw_content={"owner": "assistant"},
                    ),
                    JobDescriptionMemory(
                        agent_profile_id=autonomous.id,
                        job_description_id=job.id,
                        summary="autonomous job memory",
                        content={"owner": "autonomous"},
                        raw_content={"owner": "autonomous"},
                    ),
                    AgentGlobalMemory(
                        agent_profile_id=autonomous.id,
                        summary=autonomous_global_memory_seed,
                        content={"text": autonomous_global_memory_seed},
                        raw_content={"text": autonomous_global_memory_seed},
                    ),
                    AgentGlobalMemory(
                        agent_profile_id=assistant.id,
                        summary="assistant global memory",
                        content={"owner": "assistant"},
                        raw_content={"owner": "assistant"},
                    ),
                ]
            )

            agent_session = AgentSession(agent_profile_id=autonomous.id, session_key="primary")
            session.add(agent_session)
            session.flush()

            goal = GoalSpec(
                agent_profile_id=autonomous.id,
                title="Fetch one candidate",
                goal_text="Find one candidate and stop for approval before external action.",
                status="waiting_human",
                source="operator",
                source_text="Find one candidate and stop for approval before external action.",
                requested_by="api-test",
                summary="Autonomous goal waiting for approval.",
            )
            session.add(goal)
            session.flush()

            run = AgentRun(
                session_id=agent_session.id,
                goal_spec_id=goal.id,
                run_id="run-autonomous-1",
                agent_kind="autonomous",
                status="waiting_human",
                checkpoint_status="open",
                context_manifest={"goal": goal.goal_text, "title": goal.title},
                runtime_metadata={"goal_title": goal.title, "conversation_id": AUTONOMOUS_PRIMARY_CONVERSATION_ID},
            )
            session.add(run)
            session.flush()
            goal.latest_run_id = run.run_id
            goal.last_activity_at = run.updated_at
            session.add(
                AgentTurnRecord(
                    run_pk=run.id,
                    seq=1,
                    trigger_type="goal_created",
                    status="waiting_human",
                    phase="evaluate",
                    outcome_kind="wait_human",
                    turn_metadata={"final_output": "Waiting for approval before external action."},
                )
            )
            session.add(
                AgentRuntimeEvent(
                    session_id=agent_session.id,
                    run_id=run.id,
                    source="autonomous",
                    event_type="turn.waiting_human",
                    message="waiting for approval",
                    turn_id="turn-1",
                    seq=1,
                )
            )
            session.add_all(
                [
                    ApprovalItem(
                        target_type="blocked_task",
                        target_id=run.run_id,
                        title="Autonomous approval",
                        source_kind="autonomous",
                        status="pending",
                        run_pk=run.id,
                        payload={"run_id": run.run_id},
                    ),
                    ApprovalItem(
                        target_type="conversation_turn",
                        target_id="conv-1",
                        title="Assistant approval",
                        source_kind="assistant",
                        status="pending",
                        payload={"source_kind": "assistant"},
                    ),
                    Skill(skill_id="skill-active", name="Active skill", status="active"),
                    Skill(skill_id="skill-draft", name="Draft skill", status="draft"),
                    McpServer(
                        server_key="browser",
                        name="Browser MCP",
                        endpoint="http://127.0.0.1:7777",
                        enabled=True,
                    ),
                    McpServer(
                        server_key="disabled",
                        name="Disabled MCP",
                        endpoint="http://127.0.0.1:9999",
                        enabled=False,
                    ),
                ]
            )
            session.commit()

        listed = client.get("/api/agents")
        assert listed.status_code == 200
        assert {item["kind"] for item in listed.json()} == {"assistant", "autonomous"}

        assistant_profile = client.get("/api/agents/assistant")
        assert assistant_profile.status_code == 200
        assert assistant_profile.json()["kind"] == "assistant"

        assistant_workspace = client.get("/api/agents/assistant/workspace")
        assert assistant_workspace.status_code == 200
        assert assistant_workspace.json()["agent"]["kind"] == "assistant"
        assert assistant_workspace.json()["conversations"][0]["id"] == conversation.conversation_id
        assert assistant_workspace.json()["skills"][0]["status"] == "active"
        assert assistant_workspace.json()["tools"][0]["name"]

        created_conversation = client.post("/api/agents/assistant/conversations", json={"title": "Fresh chat"})
        assert created_conversation.status_code == 201
        assert created_conversation.json()["title"] == "Fresh chat"

        assistant_conversation = client.get(f"/api/agents/assistant/conversations/{conversation.conversation_id}")
        assert assistant_conversation.status_code == 200
        assert assistant_conversation.json()["conversation"]["id"] == conversation.conversation_id
        assert assistant_conversation.json()["messages"][0]["content"] == "Workspace ready."

        patched = client.patch("/api/agents/assistant", json={"description": "chat-first"})
        assert patched.status_code == 200
        assert patched.json()["description"] == "chat-first"
        assert patched.json()["agent_key"] == "assistant"

        patched_prompt = client.patch(
            "/api/agents/autonomous",
            json={"prompt_config": {"systemPrompt": "Autonomous UI config prompt."}},
        )
        assert patched_prompt.status_code == 200
        assert patched_prompt.json()["agent_key"] == "autonomous"
        assert patched_prompt.json()["is_primary"] is True
        assert patched_prompt.json()["prompt_config"]["systemPrompt"] == "Autonomous UI config prompt."
        assert patched_prompt.json()["prompt_config"]["context_policy"]["global"]["token_budget_default"] >= 1

        immutable_primary = client.patch("/api/agents/autonomous", json={"is_primary": False})
        assert immutable_primary.status_code == 400

        autonomous_workspace = client.get("/api/agents/autonomous/workspace")
        assert autonomous_workspace.status_code == 200
        assert autonomous_workspace.json()["agent"]["kind"] == "autonomous"
        tool_names = {item["name"] for item in autonomous_workspace.json()["tools"]}
        assert "list_candidates" in tool_names
        assert "upsert_candidate" in tool_names
        assert "request_human_approval" in tool_names
        recruit_tool = next(item for item in autonomous_workspace.json()["tools"] if item["name"] == "list_candidates")
        assert recruit_tool["serverName"] == "Recruit Plugin"
        assert autonomous_workspace.json()["agent"]["memory_policy"]["agent_global_memory"]["schema"] == [
            "facts",
            "decisions",
            "open_questions",
            "next_actions",
            "risk_flags",
            "evidence_refs",
            "confidence",
        ]
        assert autonomous_workspace.json()["agent"]["activeTask"] == "Fetch one candidate：等待人工处理后继续。"
        assert autonomous_workspace.json()["conversations"][0]["id"] == AUTONOMOUS_PRIMARY_CONVERSATION_ID
        assert autonomous_workspace.json()["conversations"][0]["preview"] == "Fetch one candidate：等待人工处理后继续。"
        assert autonomous_workspace.json()["runs"][0]["runId"] == "run-autonomous-1"
        assert autonomous_workspace.json()["runs"][0]["summary"] == "Fetch one candidate：等待人工处理后继续。"
        workspace_global_memory = next(item for item in autonomous_workspace.json()["memories"] if item["scope"] == "global")
        assert "标签页" not in workspace_global_memory["summary"]
        assert "http://" not in workspace_global_memory["summary"]
        assert "请先在浏览器中打开并切换到招聘平台" not in workspace_global_memory["summary"]
        assert workspace_global_memory["summary"] == expected_global_memory_summary
        scene_templates = client.get("/api/agents/shared-scene-templates")
        assert scene_templates.status_code == 200
        assert [item["key"] for item in scene_templates.json()] == [
            "sync_jd_initial",
            "sync_jd_incremental",
            "candidate_discovery",
            "candidate_scoring",
        ]
        sync_incremental_template = next(item for item in scene_templates.json() if item["key"] == "sync_jd_incremental")
        assert "zhipin.com" not in sync_incremental_template["summary"]
        assert "招聘平台 JD 页面" in sync_incremental_template["summary"]
        assert "普通浏览器" in sync_incremental_template["summary"]
        assert "非 AI 模式浏览器" in sync_incremental_template["summary"]
        assert "共享工作区" in sync_incremental_template["summary"]
        assert "差异对比" in sync_incremental_template["defaultGoalText"]
        assert "活跃岗位" in sync_incremental_template["defaultGoalText"]
        assert "可确认详情" in sync_incremental_template["defaultGoalText"]

        autonomous_conversation = client.get(
            f"/api/agents/autonomous/conversations/{AUTONOMOUS_PRIMARY_CONVERSATION_ID}"
        )
        assert autonomous_conversation.status_code == 200
        assert autonomous_conversation.json()["conversation"]["id"] == AUTONOMOUS_PRIMARY_CONVERSATION_ID
        assert autonomous_conversation.json()["messages"][0]["content"] == "Fetch one candidate：等待人工处理后继续。"
        assert len(autonomous_conversation.json()["messages"]) == 2

        runs = client.get("/api/agents/autonomous/runs")
        assert runs.status_code == 200
        assert runs.json()[0]["run_id"] == "run-autonomous-1"

        run_detail = client.get("/api/agents/autonomous/runs/run-autonomous-1")
        assert run_detail.status_code == 200
        assert run_detail.json()["run"]["status"] == "waiting_human"
        assert run_detail.json()["turns"][0]["seq"] == 1
        assert run_detail.json()["events"][0]["event_type"] == "turn.waiting_human"

        approvals = client.get("/api/agents/autonomous/approvals")
        assert approvals.status_code == 200
        assert [item["source_kind"] for item in approvals.json()] == ["autonomous"]

        assistant_approvals = client.get("/api/agents/assistant/approvals")
        assert assistant_approvals.status_code == 200
        assert [item["source_kind"] for item in assistant_approvals.json()] == ["assistant"]

        candidate_memory = client.get("/api/agents/autonomous/memory/candidate")
        assert candidate_memory.status_code == 200
        assert [item["summary"] for item in candidate_memory.json()] == ["autonomous candidate memory"]

        assistant_global_memory = client.get("/api/agents/assistant/memory/global")
        assert assistant_global_memory.status_code == 200
        assert [item["summary"] for item in assistant_global_memory.json()] == ["assistant global memory"]

        autonomous_global_memory = client.get("/api/agents/autonomous/memory/global")
        assert autonomous_global_memory.status_code == 200
        assert "标签页" not in autonomous_global_memory.json()[0]["summary"]
        assert "http://" not in autonomous_global_memory.json()[0]["summary"]
        assert "请先在浏览器中打开并切换到招聘平台" not in autonomous_global_memory.json()[0]["summary"]
        assert autonomous_global_memory.json()[0]["summary"] == expected_global_memory_summary
        assert workspace_global_memory["summary"] == autonomous_global_memory.json()[0]["summary"]

        skills = client.get("/api/agents/autonomous/skills")
        assert skills.status_code == 200
        assert [item["status"] for item in skills.json()] == ["active"]

        assistant_skills = client.get("/api/agents/assistant/skills")
        assert assistant_skills.status_code == 200
        assert [item["status"] for item in assistant_skills.json()] == ["active"]

        mcps = client.get("/api/agents/autonomous/mcp")
        assert mcps.status_code == 200
        assert [item["server_key"] for item in mcps.json()] == ["browser"]

        assistant_mcps = client.get("/api/agents/assistant/mcp")
        assert assistant_mcps.status_code == 200
        assert [item["server_key"] for item in assistant_mcps.json()] == ["browser"]
    finally:
        client.__exit__(None, None, None)
        os.environ.pop("RECRUIT_AGENT_DATA_DIR", None)
        load_settings.cache_clear()


def test_autonomous_goal_materializes_run_and_closes_wait_human_loop(tmp_path: Path) -> None:
    client, app = _build_client(tmp_path)
    client.__enter__()
    try:
        container = app.state.container
        provider = ScriptedProvider(
            provider_name="scripted",
            responses=[
                LLMResponse(
                    tool_calls=[ToolCall(id="tool-1", name="needs.approval", arguments={"value": "hello"})],
                    finish_reason="tool_calls",
                ),
                LLMResponse(content="approved path completed"),
            ],
        )
        container.provider = provider
        container.kernel.provider = provider
        container.tool_registry.register(
            ToolDefinition(
                name="needs.approval",
                description="Tool that requires operator confirmation.",
                parameters={"type": "object", "additionalProperties": True},
                handler=lambda arguments: {"ok": arguments["value"]},
                category="plugin",
                external_target=False,
                resource_target_kind="candidate",
            )
        )
        container.plugin_host.register_guard_check(
            "test_wait_human",
            lambda tool_name, _arguments, _observation: GuardVerdict(
                allowed=tool_name != "needs.approval",
                reason="requires_operator_confirmation",
                severity="waiting_human",
            ),
        )

        created = client.post(
            "/api/agents/autonomous/goals",
            json={
                "title": "Fetch one candidate",
                "goal_text": "Find one candidate and stop for approval before external action.",
                "requested_by": "api-test",
            },
        )
        assert created.status_code == 201
        assert created.json()["conversationId"]
        assert created.json()["runId"]
        assert created.json()["status"] == "queued"
        run_id = created.json()["run"]["run_id"]
        task_id = created.json()["task_id"]
        assert run_id
        assert task_id.startswith("run-")

        first_tick = client.post("/api/agents/run-once")
        assert first_tick.status_code == 200
        assert first_tick.json()["status"] == "processed"

        run_after_wait = client.get(f"/api/agents/autonomous/runs/{run_id}")
        assert run_after_wait.status_code == 200
        assert run_after_wait.json()["run"]["status"] == "waiting_human"

        approvals = client.get("/api/agents/autonomous/approvals")
        assert approvals.status_code == 200
        assert len(approvals.json()) == 1
        approval_id = approvals.json()[0]["id"]

        session_factory = app.state.session_factory
        with session_factory() as session:
            checkpoint_count = session.query(AgentRun).filter_by(run_id=run_id).one().checkpoint_status
            assert checkpoint_count == "open"
            assert session.query(ApprovalItem).filter_by(id=approval_id, status="pending").count() == 1
            assert session.query(AgentRunCheckpoint).filter_by(status="open").count() == 1
            assert session.query(OperatorInteraction).filter_by(status="pending").count() == 1

        approved = client.post(
            f"/api/approvals/{approval_id}/approve",
            json={"reviewer": "api-test", "reason": "continue"},
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved"

        second_tick = client.post("/api/agents/run-once")
        assert second_tick.status_code == 200
        assert second_tick.json()["status"] == "processed"

        finished = client.get(f"/api/agents/autonomous/runs/{run_id}")
        assert finished.status_code == 200
        assert finished.json()["run"]["status"] == "completed"
    finally:
        client.__exit__(None, None, None)
        os.environ.pop("RECRUIT_AGENT_DATA_DIR", None)
        load_settings.cache_clear()


def test_autonomy_loop_processes_goal_without_manual_run_once(tmp_path: Path) -> None:
    client, app = _build_client(tmp_path)
    client.__enter__()
    try:
        container = app.state.container
        assert app.state.autonomy_loop.is_running() is True

        settings = client.get("/api/settings")
        assert settings.status_code == 200
        assert settings.json()["autonomyEnabled"] is False

        provider = ScriptedProvider(
            provider_name="scripted",
            responses=[LLMResponse(content="Autonomy loop completed the goal.")],
        )
        container.provider = provider
        container.kernel.provider = provider

        created = client.post(
            "/api/agents/autonomous/goals",
            json={
                "title": "Run in background",
                "goal_text": "Complete this goal without calling run-once.",
                "requested_by": "api-test",
            },
        )
        assert created.status_code == 201
        run_id = created.json()["runId"]

        final_status = None
        for _ in range(80):
            detail = client.get(f"/api/agents/autonomous/runs/{run_id}")
            assert detail.status_code == 200
            final_status = detail.json()["run"]["status"]
            if final_status == "completed":
                break
            time.sleep(0.05)

        assert final_status == "completed"
        goals = client.get("/api/agents/autonomous/goals")
        assert goals.status_code == 200
        assert goals.json()[0]["status"] == "completed"
    finally:
        client.__exit__(None, None, None)
        os.environ.pop("RECRUIT_AGENT_DATA_DIR", None)
        load_settings.cache_clear()


def test_autonomous_goal_with_structured_blocked_result_stays_blocked(tmp_path: Path) -> None:
    client, app = _build_client(tmp_path)
    client.__enter__()
    try:
        container = app.state.container
        provider = ScriptedProvider(
            provider_name="scripted",
            responses=[
                LLMResponse(
                    content=(
                        '{"status":"blocked","created":0,"updated":0,"skipped":0,"blocked":1,'
                        '"unfinished_reason":"当前浏览器读取链路异常，无法安全写入 JD 库。"}'
                    )
                )
            ],
        )
        container.provider = provider
        container.kernel.provider = provider

        created = client.post(
            "/api/agents/autonomous/goals",
            json={
                "title": "同步 JD（初始）",
                "goal_text": "尝试同步全部活跃 JD，并在无法确认页面内容时返回 blocked 结果。",
                "requested_by": "api-test",
            },
        )
        assert created.status_code == 201
        run_id = created.json()["runId"]

        tick = client.post("/api/agents/run-once")
        assert tick.status_code == 200
        assert tick.json()["status"] == "processed"

        detail = client.get(f"/api/agents/autonomous/runs/{run_id}")
        assert detail.status_code == 200
        assert detail.json()["run"]["status"] == "blocked"

        session_factory = app.state.session_factory
        with session_factory() as session:
            run = session.query(AgentRun).filter_by(run_id=run_id).one()
            goal = session.get(GoalSpec, run.goal_spec_id)
            turn = session.query(AgentTurnRecord).filter_by(run_pk=run.id).one()
            runtime_events = session.query(AgentRuntimeEvent).filter_by(run_id=run.id).all()

            assert run.status == "blocked"
            assert run.finished_at is not None
            assert goal is not None
            assert goal.status == "blocked"
            assert turn.status == "failed"
            assert turn.outcome_kind == "escalate"
            assert any(event.event_type == "turn.failed" for event in runtime_events)
            assert all(event.event_type != "turn.completed" for event in runtime_events if event.turn_id == turn.turn_id)
    finally:
        client.__exit__(None, None, None)
        os.environ.pop("RECRUIT_AGENT_DATA_DIR", None)
        load_settings.cache_clear()


def test_app_startup_recovers_stale_autonomous_runs(tmp_path: Path) -> None:
    os.environ["RECRUIT_AGENT_DATA_DIR"] = str(tmp_path)
    load_settings.cache_clear()
    app = create_app()

    with app.state.session_factory() as session:
        autonomous = session.query(RecruitAgentProfile).filter_by(agent_key="autonomous").one()
        agent_session = AgentSession(agent_profile_id=autonomous.id, session_key="primary")
        session.add(agent_session)
        session.flush()

        goal = GoalSpec(
            agent_profile_id=autonomous.id,
            title="Recover stale run",
            goal_text="A stale run should be marked interrupted on startup.",
            status="running",
            source="operator",
            requested_by="api-test",
        )
        session.add(goal)
        session.flush()

        run = AgentRun(
            session_id=agent_session.id,
            goal_spec_id=goal.id,
            run_id="run-stale-1",
            agent_kind="autonomous",
            status="running",
            context_manifest={"goal": goal.goal_text, "title": goal.title},
            runtime_metadata={"goal_title": goal.title, "conversation_id": AUTONOMOUS_PRIMARY_CONVERSATION_ID},
        )
        session.add(run)
        session.commit()
        stale_run_id = run.id
        stale_goal_id = goal.id

    client = TestClient(app)
    client.__enter__()
    try:
        with app.state.session_factory() as session:
            recovered_run = session.get(AgentRun, stale_run_id)
            recovered_goal = session.get(GoalSpec, stale_goal_id)
            assert recovered_run is not None
            assert recovered_goal is not None
            assert recovered_run.status == "interrupted"
            assert recovered_run.finished_at is not None
            assert recovered_goal.status == "interrupted"
    finally:
        client.__exit__(None, None, None)
        os.environ.pop("RECRUIT_AGENT_DATA_DIR", None)
        load_settings.cache_clear()


def test_app_startup_keeps_only_latest_open_autonomous_run(tmp_path: Path) -> None:
    os.environ["RECRUIT_AGENT_DATA_DIR"] = str(tmp_path)
    load_settings.cache_clear()
    app = create_app()

    with app.state.session_factory() as session:
        autonomous = session.query(RecruitAgentProfile).filter_by(agent_key="autonomous").one()
        agent_session = AgentSession(agent_profile_id=autonomous.id, session_key="primary")
        session.add(agent_session)
        session.flush()

        older_goal = GoalSpec(
            agent_profile_id=autonomous.id,
            title="Older blocked run",
            goal_text="This older open run should be superseded on startup.",
            status="blocked",
            source="operator",
            requested_by="api-test",
        )
        latest_goal = GoalSpec(
            agent_profile_id=autonomous.id,
            title="Latest blocked run",
            goal_text="This latest open run should remain resumable on startup.",
            status="blocked",
            source="operator",
            requested_by="api-test",
        )
        session.add_all([older_goal, latest_goal])
        session.flush()

        older_run = AgentRun(
            session_id=agent_session.id,
            goal_spec_id=older_goal.id,
            run_id="run-open-older",
            agent_kind="autonomous",
            status="blocked",
            context_manifest={"goal": older_goal.goal_text, "title": older_goal.title},
        )
        latest_run = AgentRun(
            session_id=agent_session.id,
            goal_spec_id=latest_goal.id,
            run_id="run-open-latest",
            agent_kind="autonomous",
            status="blocked",
            context_manifest={"goal": latest_goal.goal_text, "title": latest_goal.title},
        )
        session.add_all([older_run, latest_run])
        session.commit()
        older_run_id = older_run.id
        latest_run_id = latest_run.id

    client = TestClient(app)
    client.__enter__()
    try:
        with app.state.session_factory() as session:
            older = session.get(AgentRun, older_run_id)
            latest = session.get(AgentRun, latest_run_id)
            assert older is not None
            assert latest is not None
            assert older.status == "interrupted"
            assert older.finished_at is not None
            assert latest.status == "blocked"
    finally:
        client.__exit__(None, None, None)
        os.environ.pop("RECRUIT_AGENT_DATA_DIR", None)
        load_settings.cache_clear()


def test_autonomous_goal_creation_rejects_when_open_run_exists(tmp_path: Path) -> None:
    client, app = _build_client(tmp_path)
    client.__enter__()
    try:
        session_factory = app.state.session_factory
        with session_factory() as session:
            autonomous = session.query(RecruitAgentProfile).filter_by(agent_key="autonomous").one()
            agent_session = AgentSession(agent_profile_id=autonomous.id, session_key="primary")
            session.add(agent_session)
            session.flush()
            goal = GoalSpec(
                agent_profile_id=autonomous.id,
                title="Existing goal",
                goal_text="Already queued",
                status="queued",
                source="operator",
                source_text="Already queued",
                requested_by="api-test",
            )
            session.add(goal)
            session.flush()
            session.add(
                AgentRun(
                    session_id=agent_session.id,
                    goal_spec_id=goal.id,
                    run_id="run-open-1",
                    agent_kind="autonomous",
                    status="queued",
                    checkpoint_status="none",
                    context_manifest={"goal": goal.goal_text, "conversation_id": AUTONOMOUS_PRIMARY_CONVERSATION_ID},
                    runtime_metadata={"goal_title": goal.title, "conversation_id": AUTONOMOUS_PRIMARY_CONVERSATION_ID},
                )
            )
            session.commit()

        created = client.post(
            "/api/agents/autonomous/goals",
            json={
                "title": "Blocked by open run",
                "goal_text": "Should be rejected while another run is open.",
                "requested_by": "api-test",
            },
        )
        assert created.status_code == 409
        assert created.json()["detail"] == (
            "Autonomous already has an open run. Wait for it to finish or resume it before creating a new goal."
        )
    finally:
        client.__exit__(None, None, None)
        os.environ.pop("RECRUIT_AGENT_DATA_DIR", None)
        load_settings.cache_clear()


def test_sync_jds_action_enqueues_generic_autonomous_goal(tmp_path: Path) -> None:
    client, app = _build_client(tmp_path)
    client.__enter__()
    try:
        created = client.post(
            "/api/agents/scene-templates/sync_jd_incremental/runs",
            json={"requested_by": "ui-test"},
        )
        assert created.status_code == 202
        payload = created.json()
        assert payload["conversationId"]
        assert payload["runId"]
        assert payload["status"] == "queued"
        assert payload["goal"]["goal_kind"] == "sync_jd_incremental"
        assert payload["goal"]["constraints"]["sync_mode"] == "incremental"
        assert payload["goal"]["constraints"]["source_surface"] == "browser_accessible_recruiting_pages"
        assert payload["goal"]["constraints"]["target_store"] == "shared_workspace_job_descriptions"
        assert payload["goal"]["constraints"]["sync_strategy"] == "compare_remote_roles_with_workspace_then_upsert_deltas"
        assert payload["goal"]["constraints"]["missing_remote_role_policy"] == "no_delete_without_explicit_instruction"
        assert payload["goal"]["context_hints"]["trigger"] == "scene_template_panel"

        session_factory = app.state.session_factory
        with session_factory() as session:
            goal = session.query(GoalSpec).filter_by(id=payload["goalId"]).one()
            run = session.query(AgentRun).filter_by(run_id=payload["runId"]).one()
            assert goal.goal_kind == "sync_jd_incremental"
            assert "zhipin.com" not in goal.goal_text
            assert "招聘平台 JD 页面" in goal.goal_text
            assert "活跃岗位" in goal.goal_text
            assert "可确认详情" in goal.goal_text
            assert goal.summary == goal.goal_text
            assert goal.constraints["scope_kind"] == "global"
            assert goal.constraints["scope_ref"] == "workspace:shared"
            assert goal.constraints["memory_scope_kind"] == "global"
            assert goal.constraints["memory_scope_ref"] == "workspace:shared"
            assert goal.constraints["global_scope_ref"] == "workspace:shared"
            assert goal.constraints["target_entity"] == "job_description"
            assert goal.constraints["source_surface"] == "browser_accessible_recruiting_pages"
            assert goal.constraints["target_store"] == "shared_workspace_job_descriptions"
            assert goal.constraints["sync_strategy"] == "compare_remote_roles_with_workspace_then_upsert_deltas"
            assert goal.constraints["missing_remote_role_policy"] == "no_delete_without_explicit_instruction"
            assert goal.success_criteria["mode"] == "incremental"
            assert goal.success_criteria["entity"] == "job_description"
            assert goal.success_criteria["source"] == "browser_accessible_recruiting_pages"
            assert goal.success_criteria["target"] == "shared_workspace_job_descriptions"
            assert goal.success_criteria["write_policy"] == "upsert_changed_active_roles_skip_unchanged"
            assert goal.context_hints["trigger"] == "scene_template_panel"
            assert goal.context_hints["scene_template_key"] == "sync_jd_incremental"
            assert run.context_manifest["conversation_id"] == AUTONOMOUS_PRIMARY_CONVERSATION_ID
            assert run.context_manifest["goal"] == goal.goal_text
            assert run.goal_spec_id == goal.id
    finally:
        client.__exit__(None, None, None)
        os.environ.pop("RECRUIT_AGENT_DATA_DIR", None)
        load_settings.cache_clear()


def test_autonomous_goal_creation_accepts_action_style_metadata(tmp_path: Path) -> None:
    client, app = _build_client(tmp_path)
    client.__enter__()
    try:
        session_factory = app.state.session_factory
        with session_factory() as session:
            job = JobDescription(title="Action seeded JD")
            session.add(job)
            session.commit()
            job_id = job.id

        created = client.post(
            "/api/agents/autonomous/goals",
            json={
                "title": "发现候选人",
                "goal_text": "围绕指定 JD 发现候选人，将有效候选人写入工作区，并补齐基础联系信息。",
                "goal_kind": "candidate_discovery",
                "requested_by": "ui-test",
                "jd_id": job_id,
                "candidate_count_target": 5,
                "constraints": {
                    "scope_kind": "job",
                    "memory_scope_kind": "job",
                    "target_entity": "candidate",
                },
                "success_criteria": {
                    "entity": "candidate",
                    "outcome": "candidate_discovery",
                },
                "context_hints": {
                    "trigger": "scene_template_panel",
                },
            },
        )
        assert created.status_code == 201
        payload = created.json()
        assert payload["goal"]["goal_kind"] == "candidate_discovery"
        assert payload["run"]["run_type"] == "candidate_discovery"

        with session_factory() as session:
            goal = session.query(GoalSpec).filter_by(id=payload["goalId"]).one()
            run = session.query(AgentRun).filter_by(run_id=payload["runId"]).one()
            assert goal.goal_kind == "candidate_discovery"
            assert goal.constraints["jd_id"] == job_id
            assert goal.constraints["target_entity"] == "candidate"
            assert goal.success_criteria["outcome"] == "candidate_discovery"
            assert goal.context_hints["trigger"] == "scene_template_panel"
            assert run.job_description_id == job_id
            assert run.context_manifest["candidate_count_target"] == 5
            assert run.runtime_metadata["jd_id"] == job_id
    finally:
        client.__exit__(None, None, None)
        os.environ.pop("RECRUIT_AGENT_DATA_DIR", None)
        load_settings.cache_clear()


def test_scene_template_route_materializes_autonomous_goal(tmp_path: Path) -> None:
    client, app = _build_client(tmp_path)
    client.__enter__()
    try:
        session_factory = app.state.session_factory
        with session_factory() as session:
            job = JobDescription(title="Template route JD")
            session.add(job)
            session.commit()
            job_id = job.id

        created = client.post(
            "/api/agents/scene-templates/candidate_discovery/runs",
            json={
                "requested_by": "ui-test",
                "jd_id": job_id,
                "candidate_count_target": 4,
            },
        )
        assert created.status_code == 202
        payload = created.json()
        assert payload["goal"]["goal_kind"] == "candidate_discovery"

        with session_factory() as session:
            goal = session.query(GoalSpec).filter_by(id=payload["goalId"]).one()
            run = session.query(AgentRun).filter_by(run_id=payload["runId"]).one()
            assert goal.goal_kind == "candidate_discovery"
            assert "普通浏览器" in goal.goal_text
            assert "招聘平台" in goal.goal_text
            assert "zhipin.com" not in goal.goal_text
            assert goal.summary == goal.goal_text
            assert goal.constraints["target_entity"] == "candidate"
            assert goal.context_hints["scene_template_key"] == "candidate_discovery"
            assert run.context_manifest["goal"] == goal.goal_text
            assert run.job_description_id == job_id
            assert run.context_manifest["candidate_count_target"] == 4
    finally:
        client.__exit__(None, None, None)
        os.environ.pop("RECRUIT_AGENT_DATA_DIR", None)
        load_settings.cache_clear()


def test_autonomous_goal_execution_honors_persisted_memory_scope_constraints(tmp_path: Path) -> None:
    client, app = _build_client(tmp_path)
    client.__enter__()
    try:
        container = app.state.container
        provider = ScriptedProvider(
            provider_name="scripted",
            responses=[LLMResponse(content="Remember this candidate-scoped summary.")],
        )
        container.provider = provider
        container.kernel.provider = provider

        session_factory = app.state.session_factory
        with session_factory() as session:
            candidate = Candidate(name="Scoped memory candidate")
            session.add(candidate)
            session.commit()
            candidate_id = candidate.id

        created = client.post(
            "/api/agents/autonomous/goals",
            json={
                "title": "Candidate-scoped memory goal",
                "goal_text": "Persist the final summary into candidate memory.",
                "requested_by": "api-test",
                "constraints": {
                    "memory_scope_kind": "candidate",
                    "memory_scope_ref": candidate_id,
                },
            },
        )
        assert created.status_code == 201

        tick = client.post("/api/agents/run-once")
        assert tick.status_code == 200
        assert tick.json()["status"] == "processed"

        with session_factory() as session:
            candidate_memories = session.query(CandidatePersonMemory).filter_by(person_id=candidate_id).all()
            autonomous = session.query(RecruitAgentProfile).filter_by(agent_key="autonomous").one()
            global_memories = session.query(AgentGlobalMemory).filter_by(agent_profile_id=autonomous.id).all()
            assert len(candidate_memories) == 1
            assert candidate_memories[0].summary == "Remember this candidate-scoped summary."
            assert global_memories == []
    finally:
        client.__exit__(None, None, None)
        os.environ.pop("RECRUIT_AGENT_DATA_DIR", None)
        load_settings.cache_clear()


def test_profile_patch_merges_role_definition_for_overlay_routes(tmp_path: Path) -> None:
    client, app = _build_client(tmp_path)
    client.__enter__()
    try:
        session_factory = app.state.session_factory
        with session_factory() as session:
            autonomous = session.query(RecruitAgentProfile).filter_by(agent_key="autonomous").one()
            autonomous.role_definition = {
                "goalTemplate": "legacy-template",
                "boundaries": ["no_external_write"],
                "rubricVersion": "v1",
            }
            session.commit()

        routed = client.patch(
            "/api/agents/autonomous",
            json={
                "role_definition": {
                    "goalTemplate": "new-template",
                }
            },
        )
        assert routed.status_code == 200
        assert routed.json()["role_definition"]["goalTemplate"] == "new-template"
        assert routed.json()["role_definition"]["boundaries"] == ["no_external_write"]
        assert routed.json()["role_definition"]["rubricVersion"] == "v1"

        profile = client.patch(
            "/api/recruit-agent/profile",
            json={
                "role_definition": {
                    "goalTemplate": "profile-template",
                }
            },
        )
        assert profile.status_code == 200
        assert profile.json()["role_definition"]["goalTemplate"] == "profile-template"
        assert profile.json()["role_definition"]["boundaries"] == ["no_external_write"]
        assert profile.json()["role_definition"]["rubricVersion"] == "v1"
    finally:
        client.__exit__(None, None, None)
        os.environ.pop("RECRUIT_AGENT_DATA_DIR", None)
        load_settings.cache_clear()


def test_resume_rejects_active_autonomous_run(tmp_path: Path) -> None:
    client, app = _build_client(tmp_path)
    client.__enter__()
    try:
        session_factory = app.state.session_factory
        with session_factory() as session:
            autonomous = session.query(RecruitAgentProfile).filter_by(agent_key="autonomous").one()
            agent_session = AgentSession(agent_profile_id=autonomous.id, session_key="primary")
            session.add(agent_session)
            session.flush()
            goal = GoalSpec(
                agent_profile_id=autonomous.id,
                title="Active goal",
                goal_text="Already running",
                status="running",
                source="operator",
                source_text="Already running",
                requested_by="api-test",
            )
            session.add(goal)
            session.flush()
            run = AgentRun(
                session_id=agent_session.id,
                goal_spec_id=goal.id,
                run_id="run-active-resume",
                agent_kind="autonomous",
                status="running",
                checkpoint_status="none",
            )
            session.add(run)
            session.commit()

        resumed = client.post(
            "/api/agents/autonomous/runs/run-active-resume/resume",
            json={"reviewer": "api-test", "reason": "duplicate click"},
        )
        assert resumed.status_code == 409
        assert resumed.json()["detail"] == "Active run does not need resume."
    finally:
        client.__exit__(None, None, None)
        os.environ.pop("RECRUIT_AGENT_DATA_DIR", None)
        load_settings.cache_clear()


def test_autonomous_conversation_keeps_blocked_status_and_runtime_events(tmp_path: Path) -> None:
    client, app = _build_client(tmp_path)
    client.__enter__()
    try:
        session_factory = app.state.session_factory
        with session_factory() as session:
            autonomous = session.query(RecruitAgentProfile).filter_by(agent_key="autonomous").one()
            agent_session = AgentSession(agent_profile_id=autonomous.id, session_key="primary")
            session.add(agent_session)
            session.flush()

            goal = GoalSpec(
                agent_profile_id=autonomous.id,
                title="同步 JD（初始）",
                goal_text="同步全部 JD。",
                goal_kind="sync_jd_initial",
                status="blocked",
                source="operator",
                source_text="同步全部 JD。",
                requested_by="ui-test",
                constraints={"scope_kind": "global"},
                summary="同步 JD（初始） 已从工具面板触发。",
            )
            session.add(goal)
            session.flush()

            run = AgentRun(
                session_id=agent_session.id,
                goal_spec_id=goal.id,
                run_id="run-blocked-1",
                agent_kind="autonomous",
                status="blocked",
                checkpoint_status="none",
                context_manifest={"goal": goal.goal_text, "title": goal.title},
                runtime_metadata={"goal_title": goal.title, "conversation_id": AUTONOMOUS_PRIMARY_CONVERSATION_ID},
            )
            session.add(run)
            session.flush()
            goal.latest_run_id = run.run_id
            goal.last_activity_at = run.updated_at

            turn = AgentTurnRecord(
                run_pk=run.id,
                seq=1,
                trigger_type="goal_created",
                status="failed",
                phase="evaluate",
                outcome_kind="continue",
                turn_metadata={"gate_signal": "budget_exhausted", "round_count": 3},
            )
            session.add(turn)
            session.flush()

            session.add(
                AgentRuntimeEvent(
                    session_id=agent_session.id,
                    run_id=run.id,
                    source="autonomous",
                    event_type="provider.started",
                    message="calling model",
                    turn_id=turn.turn_id,
                    seq=1,
                    payload={"message_count": 2},
                )
            )
            session.add(
                AgentRuntimeEvent(
                    session_id=agent_session.id,
                    run_id=run.id,
                    source="autonomous",
                    event_type="turn.completed",
                    message="turn completed",
                    turn_id=turn.turn_id,
                    seq=1,
                    payload={"status": "continue", "gate_signal": "budget_exhausted"},
                )
            )
            session.commit()

        response = client.get(f"/api/agents/autonomous/conversations/{AUTONOMOUS_PRIMARY_CONVERSATION_ID}")
        assert response.status_code == 200
        payload = response.json()
        assert payload["conversation"]["status"] == "blocked"
        assert all((item.get("metadata") or {}).get("message_type") != "event" for item in payload["messages"])
        assert payload["messages"][0]["content"] == "同步 JD（初始）：当前受阻，等待继续执行条件满足。"
        run_detail = client.get("/api/agents/autonomous/runs/run-blocked-1")
        assert run_detail.status_code == 200
        runtime_events = run_detail.json()["events"]
        provider_started = next(item for item in runtime_events if item["event_type"] == "provider.started")
        turn_completed = next(item for item in runtime_events if item["event_type"] == "turn.completed")
        assert provider_started["message"] == "calling model"
        assert turn_completed["event_type"] == "turn.completed"
    finally:
        client.__exit__(None, None, None)
        os.environ.pop("RECRUIT_AGENT_DATA_DIR", None)
        load_settings.cache_clear()


def test_assistant_overlay_message_wrapper_accepts_draft_conversation_ids(tmp_path: Path) -> None:
    client, app = _build_client(tmp_path)
    client.__enter__()
    try:
        container = app.state.container
        provider = ScriptedProvider(
            provider_name="scripted",
            responses=[LLMResponse(content="Assistant wrapper reply")],
        )
        container.provider = provider
        container.kernel.provider = provider

        conversation_id = "draft-assistant-overlay"
        posted = client.post(
            f"/api/agents/assistant/conversations/{conversation_id}/messages",
            json={"message": "Summarize the workspace."},
        )
        assert posted.status_code == 202
        assert posted.json()["conversationId"] == conversation_id
        assert posted.json()["status"] == "accepted"

        detail_payload: dict[str, object] | None = None
        for _ in range(60):
            detail = client.get(f"/api/agents/assistant/conversations/{conversation_id}")
            if detail.status_code == 200 and len(detail.json()["messages"]) >= 2:
                detail_payload = detail.json()
                if any(message["content"] == "Assistant wrapper reply" for message in detail_payload["messages"]):
                    break
            time.sleep(0.05)

        assert detail_payload is not None
        assert detail_payload["conversation"]["id"] == conversation_id
        assert [message["role"] for message in detail_payload["messages"][:2]] == ["user", "assistant"]
        assert any(message["content"] == "Assistant wrapper reply" for message in detail_payload["messages"])
    finally:
        client.__exit__(None, None, None)
        os.environ.pop("RECRUIT_AGENT_DATA_DIR", None)
        load_settings.cache_clear()
