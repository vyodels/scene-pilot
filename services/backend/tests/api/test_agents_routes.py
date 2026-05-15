from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from agent_runtime.fixtures import LLMResponse, ScriptedProvider, ToolCall
from recruit_station.capabilities.tools import ToolDefinition
from recruit_station.core.settings import load_settings
from recruit_station.models.domain import AgentRun, AgentRunCheckpoint, ApprovalItem, OperatorInteraction, TaskQueueItem
from recruit_station.server import create_app


def _client(tmp_path, monkeypatch, db_name: str) -> TestClient:
    monkeypatch.setenv("RECRUIT_STATION_DATA_DIR", str(tmp_path / f"{db_name}-data"))
    monkeypatch.setenv("RECRUIT_STATION_DATABASE_URL", f"sqlite:///{tmp_path / f'{db_name}.db'}")
    load_settings.cache_clear()
    return TestClient(create_app())


def _script_autonomous_provider(client: TestClient, *responses: LLMResponse) -> ScriptedProvider:
    provider = ScriptedProvider(provider_name="scripted", responses=list(responses))
    container = client.app.state.container
    container.provider = provider
    container.autonomous_adapter.provider = provider
    return provider


def _start_workspace(client: TestClient) -> dict:
    response = client.post(
        "/api/agents/autonomous/workspace-control/start",
        json={"reviewer": "api-test", "reason": "test start"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _start_autonomous_run(
    client: TestClient,
    *,
    instruction: str = "Find one candidate and stop for approval before external action.",
    title: str = "Find one candidate",
    kind: str = "candidate_discovery",
    **extra,
) -> dict:
    response = client.post(
        "/api/agents/autonomous/runs",
        json={
            "title": title,
            "instruction": instruction,
            "kind": kind,
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_autonomous_run_endpoint_creates_run_and_queue_envelope(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "runs")

    payload = _start_autonomous_run(
        client,
        instruction="Inspect https://example.test/candidates/1 and stop before external action.",
        context_hints={"browser_target": {"url": "https://example.test/candidates/1"}},
    )

    assert payload["status"] == "queued"
    assert payload["runId"]
    context_manifest = payload["run"].get("contextManifest") or payload["run"]["context_manifest"]
    runtime_metadata = payload["run"].get("runtimeMetadata") or payload["run"]["runtime_metadata"]
    assert context_manifest["instruction"] == "Inspect https://example.test/candidates/1 and stop before external action."
    assert runtime_metadata["instruction"] == "Inspect https://example.test/candidates/1 and stop before external action."
    assert context_manifest["browser_target"]["url"] == "https://example.test/candidates/1"
    assert context_manifest["browser_target"]["host"] == "example.test"
    assert "goal" not in str(payload).lower()

    runs = client.get("/api/agents/autonomous/runs")
    assert runs.status_code == 200
    assert runs.json()[0]["runId"] == payload["runId"]

    queue = client.get("/api/agents/queue")
    assert queue.status_code == 200
    task = queue.json()[0]
    assert task["task_type"] == "autonomous_turn"
    assert task["payload"]["run_id"] == payload["runId"]
    assert task["payload"]["world_snapshot"]["instruction"] == context_manifest["instruction"]
    assert task["payload"]["world_snapshot"]["browser_target"]["url"] == "https://example.test/candidates/1"
    assert "goal" not in str(task).lower()


def test_autonomous_run_endpoint_rejects_second_open_run(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "open-run-conflict")
    first = _start_autonomous_run(client)

    response = client.post(
        "/api/agents/autonomous/runs",
        json={"title": "Second", "instruction": "Run another instruction.", "kind": "candidate_discovery"},
    )

    assert response.status_code == 409
    assert first["runId"] in {item["runId"] for item in client.get("/api/agents/autonomous/runs").json()}


def test_autonomous_run_endpoint_rejects_empty_instruction(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "empty-instruction")

    response = client.post(
        "/api/agents/autonomous/runs",
        json={"title": "No instruction", "instruction": "   ", "kind": "candidate_discovery"},
    )

    assert response.status_code in {400, 422}


def test_autonomous_run_endpoint_rejects_legacy_instruction_aliases(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "legacy-run-aliases")

    for payload in (
        {"title": "Legacy", "objective": "Find candidates."},
        {"title": "Legacy", "message": "Find candidates."},
        {"title": "Legacy", "instruction_text": "Find candidates."},
        {"title": "Legacy", "instructionText": "Find candidates."},
    ):
        response = client.post("/api/agents/autonomous/runs", json=payload)
        assert response.status_code == 422


def test_autonomous_run_once_completes_run_and_projects_primary_conversation(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "run-once")
    _script_autonomous_provider(
        client,
        LLMResponse(
            content="Completed candidate search.",
            result_data={"execution_status": "completed"},
        ),
    )
    _start_workspace(client)
    created = _start_autonomous_run(client)

    processed = client.post("/api/agents/run-once")

    assert processed.status_code == 200
    assert processed.json()["status"] == "processed"
    run_detail = client.get(f"/api/agents/autonomous/runs/{created['runId']}")
    assert run_detail.status_code == 200
    run_payload = run_detail.json()
    assert run_payload["run"]["status"] == "completed"
    assert run_payload["turns"][0]["status"] == "completed"
    assert run_payload["turns"][0]["turn_metadata"]["final_output"] == "Completed candidate search."
    assert {event["event_type"] for event in run_payload["events"]} >= {"adapter_turn_started", "turn_completed"}
    assert all("goal" not in str(item).lower() for item in (run_payload["run"], *run_payload["turns"], *run_payload["events"]))

    conversation = client.get("/api/agents/autonomous/conversations/autonomous-primary")
    assert conversation.status_code == 200
    assert conversation.json()["conversation"]["id"] == "autonomous-primary"
    assert any(message["content"] == "Completed candidate search." for message in conversation.json()["messages"])


def test_autonomous_run_cancel_updates_run_queue_and_allows_new_run(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "cancel-run")
    created = _start_autonomous_run(client)

    cancelled = client.post(
        f"/api/agents/autonomous/runs/{created['runId']}/cancel",
        json={"reviewer": "api-test", "reason": "stop current run"},
    )

    assert cancelled.status_code == 200
    assert cancelled.json()["run"]["status"] == "cancelled"
    queue = client.get("/api/agents/queue").json()
    assert queue[0]["status"] == "failed"
    assert queue[0]["payload"]["queue_audit"]["last_event"] == "cancelled"

    next_run = _start_autonomous_run(client, title="Next run", instruction="Start after cancel.")
    assert next_run["status"] == "queued"


def test_autonomous_wait_human_resume_resolves_gate_and_requeues_run(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "resume-run")
    _script_autonomous_provider(
        client,
        LLMResponse(
            content="Need approval before continuing.",
            result_data={"execution_status": "waiting_human"},
        ),
    )
    _start_workspace(client)
    created = _start_autonomous_run(client)

    processed = client.post("/api/agents/run-once")
    assert processed.status_code == 200
    assert processed.json()["status"] == "processed"

    with client.app.state.session_factory() as session:
        run = session.scalars(select(AgentRun).where(AgentRun.run_id == created["runId"])).one()
        checkpoint = session.scalars(select(AgentRunCheckpoint).where(AgentRunCheckpoint.run_id == run.id)).one()
        approval = session.scalars(select(ApprovalItem).where(ApprovalItem.run_pk == run.id)).one()
        interaction = session.scalars(select(OperatorInteraction).where(OperatorInteraction.checkpoint_id == checkpoint.id)).one()
        assert run.status == "waiting_human"
        assert run.checkpoint_status == "open"
        assert checkpoint.status == "open"
        assert approval.status == "pending"
        assert interaction.status == "pending"

    resumed = client.post(
        f"/api/agents/autonomous/runs/{created['runId']}/resume",
        json={"reviewer": "api-test", "reason": "approved"},
    )

    assert resumed.status_code == 200
    assert resumed.json()["run"]["status"] == "queued"
    assert resumed.json()["run"]["checkpoint_status"] == "resolved"
    with client.app.state.session_factory() as session:
        run = session.scalars(select(AgentRun).where(AgentRun.run_id == created["runId"])).one()
        checkpoint = session.scalars(select(AgentRunCheckpoint).where(AgentRunCheckpoint.run_id == run.id)).one()
        approval = session.scalars(select(ApprovalItem).where(ApprovalItem.run_pk == run.id)).one()
        interaction = session.scalars(select(OperatorInteraction).where(OperatorInteraction.checkpoint_id == checkpoint.id)).one()
        task = session.scalars(select(TaskQueueItem).where(TaskQueueItem.id == run.queue_task_id)).one()
        assert checkpoint.status == "resolved"
        assert approval.status == "approved"
        assert interaction.status == "resolved"
        assert task.status == "pending"
        assert task.payload["trigger_type"] == "resume"


def test_autonomous_permission_checkpoint_resumes_after_adapter_rebuild(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "durable-permission-resume")
    provider = _script_autonomous_provider(
        client,
        LLMResponse(
            tool_calls=[ToolCall(id="tool-approval", name="external.send", arguments={"text": "hello"})],
            finish_reason="tool_calls",
        ),
        LLMResponse(
            content="External action completed.",
            result_data={"status": "pass", "execution_status": "completed"},
        ),
    )
    _start_workspace(client)
    client.app.state.container.tool_registry.register(
        ToolDefinition(
            name="external.send",
            description="External send requiring approval.",
            parameters={"type": "object", "additionalProperties": True},
            handler=lambda arguments: {"sent": arguments["text"]},
            category="plugin",
            external_target=True,
        )
    )
    created = _start_autonomous_run(client)

    processed = client.post("/api/agents/run-once")

    assert processed.status_code == 200
    assert processed.json()["status"] == "processed"
    with client.app.state.session_factory() as session:
        run = session.scalars(select(AgentRun).where(AgentRun.run_id == created["runId"])).one()
        checkpoint = session.scalars(select(AgentRunCheckpoint).where(AgentRunCheckpoint.run_id == run.id)).one()
        checkpoint_payload = dict(checkpoint.payload or {})
        runtime_checkpoint = dict(checkpoint_payload["runtime_checkpoint"])
        resume_payload = checkpoint_payload["resume_task"]["payload"]
        assert run.status == "waiting_human"
        assert checkpoint.status == "open"
        assert checkpoint_payload["pending_tool_calls"][0]["tool_name"] == "external.send"
        assert runtime_checkpoint["pending_permissions"]
        assert resume_payload["runtime_checkpoint"]["pending_permissions"]

    client.app.state.container.autonomous_adapter.pending_permission_engines.clear()
    resumed = client.post(
        f"/api/agents/autonomous/runs/{created['runId']}/resume",
        json={"reviewer": "api-test", "reason": "approved"},
    )
    assert resumed.status_code == 200

    processed_after_resume = client.post("/api/agents/run-once")

    assert processed_after_resume.status_code == 200
    assert processed_after_resume.json()["status"] == "processed"
    run_detail = client.get(f"/api/agents/autonomous/runs/{created['runId']}").json()
    assert run_detail["run"]["status"] == "completed"
    assert run_detail["turns"][-1]["turn_metadata"]["final_output"] == "External action completed."
    assert provider.captured_requests[1].turn_id == provider.captured_requests[0].turn_id
    assert provider.captured_requests[1].messages[-1].role == "tool"
    assert "hello" in str(provider.captured_requests[1].messages[-1].content)


def test_legacy_autonomous_goal_routes_are_absent(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "missing-goal-routes")

    assert client.get("/api/agents/autonomous/goals").status_code == 404
    assert client.post("/api/agents/autonomous/goals", json={"instruction": "Find one candidate"}).status_code == 404


def test_autonomous_workspace_control_gates_queue_and_terminates_open_run(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "workspace-control")
    _script_autonomous_provider(
        client,
        LLMResponse(content="Should only run after workspace start.", result_data={"execution_status": "completed"}),
    )
    created = _start_autonomous_run(client)

    stopped = client.get("/api/agents/autonomous/workspace-control")
    assert stopped.status_code == 200
    assert stopped.json()["state"] == "stopped"
    assert stopped.json()["autonomousPaused"] is True

    blocked = client.post("/api/agents/run-once")
    assert blocked.status_code == 200
    assert blocked.json()["status"] == "stopped"

    running = _start_workspace(client)
    assert running["state"] == "running"

    paused = client.post(
        "/api/agents/autonomous/workspace-control/pause",
        json={"reviewer": "api-test", "reason": "hold for review"},
    )
    assert paused.status_code == 200
    assert paused.json()["state"] == "paused"
    assert client.post("/api/agents/run-once").json()["status"] == "paused"

    resumed = client.post(
        "/api/agents/autonomous/workspace-control/continue",
        json={"reviewer": "api-test", "reason": "resume queue"},
    )
    assert resumed.status_code == 200
    assert resumed.json()["state"] == "running"
    assert client.post("/api/agents/run-once").json()["status"] == "processed"

    second = _start_autonomous_run(client, title="Terminate me", instruction="Wait in queue.")
    terminated = client.post(
        "/api/agents/autonomous/workspace-control/terminate",
        json={"reviewer": "api-test", "reason": "operator stop"},
    )
    assert terminated.status_code == 200
    assert terminated.json()["state"] == "stopped"
    assert second["runId"] in terminated.json()["terminatedRunIds"]

    run_detail = client.get(f"/api/agents/autonomous/runs/{second['runId']}").json()
    assert run_detail["run"]["status"] == "cancelled"
    queue = client.get("/api/agents/queue").json()
    assert any(item["payload"].get("run_id") == second["runId"] and item["status"] == "failed" for item in queue)
