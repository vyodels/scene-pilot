from __future__ import annotations

import threading
import time

from fastapi.testclient import TestClient
from sqlalchemy import select

from agent_runtime.fixtures import LLMResponse, ScriptedProvider, ToolCall
from recruit_station.agents.autonomous import (
    _block_single_jd_probe_if_continuation_budget_exhausted,
    _complete_single_jd_probe_if_satisfied,
)
from recruit_station.agents.outcome import AgentTurnOutcome
from recruit_station.capabilities.tools import ToolDefinition
from recruit_station.core.settings import load_settings
from recruit_station.models.domain import (
    AgentPendingUserInput,
    AgentRun,
    AgentRunCheckpoint,
    AgentRuntimeEvent,
    ApprovalItem,
    JobDescription,
    OperatorInteraction,
    TaskQueueItem,
    utcnow,
)
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


def _force_start_workspace(client: TestClient) -> None:
    client.app.state.container.heartbeat.start(updated_by="api-test", reason="test start")


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


def _assert_keys_absent(value, forbidden_keys: set[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            assert key not in forbidden_keys
            _assert_keys_absent(item, forbidden_keys)
    elif isinstance(value, list):
        for item in value:
            _assert_keys_absent(item, forbidden_keys)


def _complete_job_strategy(*, online_pass: int = 70, offline_pass: int = 72, composite_pass: int = 75, review_min: int = 60) -> dict:
    return {
        "screeningCriteria": "必须匹配 JD 的硬性要求、核心技能和项目证据。",
        "resumeScoring": {
            "online": {"criteria": "在线简历按 JD 匹配、最近经验和项目深度评分。", "passThreshold": online_pass},
            "offline": {"criteria": "离线简历核查项目细节、职责边界和时间线一致性。", "passThreshold": offline_pass},
        },
        "compositeScoring": {
            "criteria": "综合 JD 匹配、在线简历、离线简历、沟通证据和风险项给出最终建议。",
            "passThreshold": composite_pass,
            "manualReviewMin": review_min,
        },
        "manualReviewRules": "证据冲突、分数处于复核区间或关键外联前必须进入人工复核。",
    }


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


def test_autonomous_run_endpoint_rejects_incomplete_recruiting_config(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "incomplete-recruiting-run")

    for payload in (
        {"title": "Free-form recruiting", "instruction": "Start recruiting from this prompt."},
        {"title": "Saved config required", "instruction": "Start all JD.", "kind": "multi_jd_recruiting"},
    ):
        response = client.post("/api/agents/autonomous/runs", json=payload)
        assert response.status_code == 409
        assert "automation_recruiting_config incomplete" in response.json()["detail"]
    assert client.get("/api/agents/autonomous/runs").json() == []
    assert client.get("/api/agents/queue").json() == []


def test_default_autonomous_sop_is_agent_config_not_runtime_hardcode(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "default-autonomous-sop-config")

    response = client.get("/api/agents/autonomous")

    assert response.status_code == 200, response.text
    automation_config = response.json()["productConfig"]["autonomous"]["automation_recruiting_config"]
    steps_text = automation_config["executionSop"]["stepsText"]
    assert "自动化招聘 Agent 的日常目标" in steps_text
    assert "沟通：最高优先级入口" in steps_text
    assert "推荐牛人、搜索" in steps_text
    assert "最终总结中的本地 record id" in steps_text


def test_jd_sync_run_requires_only_saved_entry_url(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "jd-sync-bootstrap")
    patched = client.patch(
        "/api/agents/jd_sync",
        json={
            "product_config": {
                "jd_sync": {
                    "jd_sync_config": {
                        "executionSop": {
                            "siteEntryUrl": "https://mock-recruiting.local/",
                            "siteAccessRulesText": "\n".join(
                                [
                                    "复用人工提前登录好的浏览器会话",
                                    "目标网页可以是招聘网站任意可访问页面，由 Agent 根据页面可见导航和内容找到职位列表与职位详情",
                                    "不处理登录、验证码、账号切换或绕过风控",
                                    "只处理职位信息，不处理候选人",
                                ]
                            ),
                        },
                        "syncPolicy": {
                            "jdSyncText": "发现招聘网站中的职位列表和详情，按 platform/external_id 或标题/部门/地点去重后调用 upsert_job_description 写入本地 JD 库；同步下架、更新和新增状态。"
                        },
                    }
                }
            }
        },
    )
    assert patched.status_code == 200, patched.text

    response = client.post(
        "/api/agents/jd_sync/runs",
        json={"title": "Sync JD", "requestMessage": "同步招聘站点 JD", "instruction": "sync jobs"},
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert (payload["run"].get("runType") or payload["run"]["run_type"]) == "jd_sync"
    assert (payload["run"].get("agentKind") or payload["run"]["agent_kind"]) == "jd_sync"
    assert payload["conversationId"] == "jd-sync-primary"
    runtime_metadata = payload["run"].get("runtimeMetadata") or payload["run"]["runtime_metadata"]
    constraints = runtime_metadata["constraints"]
    assert constraints["plan_kind"] == "jd_sync"
    assert constraints["target_recruiting_site"]["entry_url"] == "https://mock-recruiting.local/"
    assert runtime_metadata["jd_sync_state"]["version"] == 1
    assert runtime_metadata["jd_sync_state"]["jobs_by_key"] == {}
    assert runtime_metadata["jd_sync_state"]["pending_job_keys"] == []
    assert "任务范围：" in runtime_metadata["instruction"]
    assert "- 从配置的招聘网站目标网页出发，目标网页可以是该网站任意可访问页面。" in runtime_metadata["instruction"]
    assert "- 根据页面可见导航和内容自行找到职位列表与职位详情。" in runtime_metadata["instruction"]
    assert "- 如果页面动作失败但仍处于同源站点，应先恢复后继续：" in runtime_metadata["instruction"]
    assert "单次点击、返回、滚动或注入超时不是任务终局" in runtime_metadata["instruction"]
    assert "不得主动聚焦浏览器地址栏、输入 URL 或粘贴 URL" in runtime_metadata["instruction"]
    assert "BOSS/zhipin 恢复不得打开新标签/新窗口" in runtime_metadata["instruction"]
    assert "如果 browser-mcp/native host 无法观察已有 BOSS 页签或招聘管理页签，不得新建 BOSS/zhipin 页签" in runtime_metadata["instruction"]
    assert "Cmd+L 聚焦地址栏" not in runtime_metadata["instruction"]
    assert "BOSS/zhipin 主导航锚点与禁区：" in runtime_metadata["instruction"]
    assert "顶层页面入口只允许使用 BOSS 主导航可见入口：职位管理、推荐牛人、搜索、沟通" in runtime_metadata["instruction"]
    assert "BOSS/zhipin 恢复不得打开新标签/新窗口，不得使用地址栏输入 URL" in runtime_metadata["instruction"]
    assert "多个 zhipin.com 页签同时存在时，优先恢复到已打开的 BOSS 招聘管理工作台页签" in runtime_metadata["instruction"]
    assert "不要新开另一个 zhipin 页签" in runtime_metadata["instruction"]
    assert "如果只有公共首页存在，可以通过该页可见的同站点入口在同一页签内恢复到招聘管理工作台；不得打开新标签/新窗口" in runtime_metadata["instruction"]
    assert "公共首页上的求职职位列表、城市职位列表或搜索结果不得作为 employer JD sync 完成证据" in runtime_metadata["instruction"]
    assert "JD sync 只读取职位信息，不点击 发布职位、关闭、升级、曝光刷新" in runtime_metadata["instruction"]
    assert "打招呼 是外联动作，read-only 流程不得点击" in runtime_metadata["instruction"]
    assert "页签附近 + 和 新建分组 永远不要点击" in runtime_metadata["instruction"]
    assert "不得用“已完成部分同步”结束本轮" in runtime_metadata["instruction"]
    assert "- 只发现和同步 JD。" in runtime_metadata["instruction"]
    assert "- 不处理候选人筛选、评分、外联或投递推进。" in runtime_metadata["instruction"]
    assert "目标网页：" in runtime_metadata["instruction"]
    assert "站点访问规则：" in runtime_metadata["instruction"]
    assert "- 复用人工提前登录好的浏览器会话" in runtime_metadata["instruction"]
    assert "- 目标网页可以是招聘网站任意可访问页面，由 Agent 根据页面可见导航和内容找到职位列表与职位详情" in runtime_metadata["instruction"]
    assert "- 不处理登录、验证码、账号切换或绕过风控" in runtime_metadata["instruction"]
    assert "- 只处理职位信息，不处理候选人" in runtime_metadata["instruction"]
    assert "JD 同步策略：" in runtime_metadata["instruction"]
    assert "- 从配置的招聘网站目标网页出发，根据页面可见导航和内容自行找到职位列表与职位详情，识别新增、更新和下架职位；只有确认职位详情已完整采集且没有阻塞时，才同步到本地 JD 库，列表页摘要只能作为发现线索。同步过程只处理职位信息，不处理候选人；如果只完成部分职位详情读取，可以记录已确认的职位作为进度，但不能把本轮视为完成，必须继续恢复并完成全量同步，或明确说明还需要恢复的条件。" in runtime_metadata["instruction"]
    assert "提前打开特定列表页" not in runtime_metadata["instruction"]
    assert "upsert_job_description" not in runtime_metadata["instruction"]
    assert "platform/external_id" not in runtime_metadata["instruction"]
    assert "external_id" not in runtime_metadata["instruction"]
    assert runtime_metadata["instruction"].count("URL：https://mock-recruiting.local/") == 1
    assert "selected_job_description_ids" not in constraints
    conversation = client.get("/api/agents/jd_sync/conversations/jd-sync-primary")
    assert conversation.status_code == 200
    messages = conversation.json()["messages"]
    run_input = next(
        message
        for message in messages
        if message.get("metadata", {}).get("message_type") == "run_input"
        and message.get("metadata", {}).get("run_id") == payload["runId"]
    )
    assert run_input["role"] == "user"
    assert run_input["kind"] == "message"
    assert run_input["content"] == runtime_metadata["instruction"]
    assert run_input["title"] == "Sync JD"
    assert "站点访问规则：" in run_input["content"]
    assert "JD 同步策略：" in run_input["content"]
    assert "复用人工提前登录好的浏览器会话" in run_input["content"]
    assert "目标网页可以是招聘网站任意可访问页面" in run_input["content"]
    assert "不处理登录、验证码、账号切换或绕过风控" in run_input["content"]
    assert "只处理职位信息，不处理候选人" in run_input["content"]
    assert "upsert_job_description" not in run_input["content"]
    assert "platform/external_id" not in run_input["content"]
    assert "external_id" not in run_input["content"]
    assert run_input["content"].count("URL：https://mock-recruiting.local/") == 1


def test_jd_sync_single_probe_config_constrains_instruction_and_runtime(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "jd-sync-single-probe")
    patched = client.patch(
        "/api/agents/jd_sync",
        json={
            "product_config": {
                "jd_sync": {
                    "jd_sync_config": {
                        "executionSop": {
                            "siteEntryUrl": "https://mock-recruiting.local/",
                            "siteAccessRulesText": "复用人工提前登录好的浏览器会话",
                        },
                        "syncPolicy": {
                            "syncMode": "single_jd_probe",
                            "maxJobDescriptions": 1,
                            "jdSyncText": "单 JD 试跑：最多 1 个 JD，用于验证链路。",
                        },
                    }
                }
            }
        },
    )
    assert patched.status_code == 200, patched.text

    response = client.post(
        "/api/agents/jd_sync/runs",
        json={"title": "Single JD Probe", "requestMessage": "单 JD 试跑", "instruction": "单 JD 试跑"},
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    runtime_metadata = payload["run"].get("runtimeMetadata") or payload["run"]["runtime_metadata"]
    constraints = runtime_metadata["constraints"]
    assert constraints["sync_mode"] == "single_jd_probe"
    assert constraints["max_job_descriptions"] == 1
    assert constraints["sync_policy"]["syncMode"] == "single_jd_probe"
    assert constraints["sync_policy"]["maxJobDescriptions"] == 1
    assert "本次运行模式是单 JD 试跑：最多同步 1 个招聘中 JD" in runtime_metadata["instruction"]
    assert "如果已经完整写入 1 个 JD，应输出单 JD 试跑完成摘要" in runtime_metadata["instruction"]
    assert "不得用“已完成部分同步”结束本轮" not in runtime_metadata["instruction"]


def test_single_jd_probe_completion_uses_written_jd_as_terminal_evidence(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "jd-sync-single-probe-complete")
    container = client.app.state.container
    with container.session_factory() as session:
        session.add(JobDescription(title="Probe JD", source="jd_sync", status="active"))
        session.flush()
        outcome = _complete_single_jd_probe_if_satisfied(
            session,
            run=AgentRun(
                session_id="session",
                run_type="jd_sync",
                status="running",
                agent_kind="jd_sync",
                context_manifest={
                    "constraints": {
                        "sync_mode": "single_jd_probe",
                        "max_job_descriptions": 1,
                    }
                },
                runtime_metadata={},
            ),
            envelope={},
            outcome=AgentTurnOutcome(
                status="escalate",
                gate_signal="escalate",
                final_output="仍需继续全量扫描。",
            ),
        )

    assert outcome.status == "complete"
    assert outcome.gate_signal == "run_done"
    assert outcome.metadata["single_jd_probe_completed"] is True
    assert outcome.metadata["single_jd_probe_synced_count"] == 1
    assert "已写入 1 个 JD，目标 1 个" in (outcome.final_output or "")
    assert "不要求继续完成全量职位发现" in (outcome.final_output or "")


def test_single_jd_probe_rejects_completion_without_written_jd(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "jd-sync-single-probe-reject-empty-complete")
    container = client.app.state.container
    with container.session_factory() as session:
        outcome = _complete_single_jd_probe_if_satisfied(
            session,
            run=AgentRun(
                session_id="session",
                run_type="jd_sync",
                status="running",
                agent_kind="jd_sync",
                context_manifest={
                    "constraints": {
                        "sync_mode": "single_jd_probe",
                        "max_job_descriptions": 1,
                    }
                },
                runtime_metadata={},
            ),
            envelope={},
            outcome=AgentTurnOutcome(
                status="complete",
                gate_signal="run_done",
                final_output="已同步 1 个 JD。",
            ),
        )

    assert outcome.status == "escalate"
    assert outcome.gate_signal == "escalate"
    assert outcome.metadata["single_jd_probe_completion_rejected"] is True
    assert outcome.metadata["single_jd_probe_synced_count"] == 0
    assert "不能标记完成" in (outcome.final_output or "")


def test_single_jd_probe_blocks_after_continuation_budget_without_written_jd(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "jd-sync-single-probe-budget-block")
    container = client.app.state.container
    with container.session_factory() as session:
        outcome = _block_single_jd_probe_if_continuation_budget_exhausted(
            session,
            run=AgentRun(
                session_id="session",
                run_type="jd_sync",
                status="running",
                agent_kind="jd_sync",
                context_manifest={
                    "constraints": {
                        "sync_mode": "single_jd_probe",
                        "max_job_descriptions": 1,
                    }
                },
                runtime_metadata={},
            ),
            envelope={},
            outcome=AgentTurnOutcome(
                status="complete",
                gate_signal="run_done",
                final_output="仍在职位管理列表恢复。",
            ),
            continuation_attempts=5,
            max_attempts=5,
        )

    assert outcome.status == "escalate"
    assert outcome.gate_signal == "escalate"
    assert outcome.metadata["single_jd_probe_continuation_budget_exhausted"] is True
    assert "恢复尝试上限" in (outcome.final_output or "")
    assert "已发布/招聘中职位条目" in (outcome.final_output or "")


def test_single_jd_probe_process_next_completes_before_provider_when_target_already_met(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "jd-sync-single-probe-early-complete")
    _script_autonomous_provider(client)
    patched = client.patch(
        "/api/agents/jd_sync",
        json={
            "product_config": {
                "jd_sync": {
                    "jd_sync_config": {
                        "executionSop": {"siteEntryUrl": "https://mock-recruiting.local/jobs"},
                        "syncPolicy": {
                            "syncMode": "single_jd_probe",
                            "maxJobDescriptions": 1,
                            "jdSyncText": "单 JD 试跑：最多 1 个 JD。",
                        },
                    }
                }
            }
        },
    )
    assert patched.status_code == 200, patched.text
    created = client.post(
        "/api/agents/jd_sync/runs",
        json={"title": "Single JD Probe", "instruction": "单 JD 试跑"},
    )
    assert created.status_code == 201, created.text
    with client.app.state.container.session_factory() as session:
        session.add(JobDescription(title="Probe JD", source="jd_sync", status="active"))
        session.commit()

    processed = client.post("/api/agents/task-queue/process-next")

    assert processed.status_code == 200
    assert processed.json()["status"] == "processed"
    run_detail = client.get(f"/api/agents/jd_sync/runs/{created.json()['runId']}")
    assert run_detail.status_code == 200
    run = run_detail.json()["run"]
    assert run["status"] == "idle"
    turn = run_detail.json()["turns"][0]
    assert turn["status"] == "completed"
    assert turn["turn_metadata"]["early_completion"] is True
    assert "已写入 1 个 JD，目标 1 个" in turn["turn_metadata"]["final_output"]


def test_single_jd_probe_stops_after_first_successful_jd_write(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "jd-sync-single-probe-stop-after-write")
    _script_autonomous_provider(
        client,
        LLMResponse(
            tool_calls=[
                ToolCall(
                    id="write-jd",
                    name="upsert_job_description",
                    arguments={
                        "title": "交易策略产品经理",
                        "source": "jd_sync",
                        "platform": "zhipin",
                        "external_id": "job-strategy-pm",
                        "description": "负责交易策略产品设计。",
                        "requirements": "具备交易策略或 AI 产品经验。",
                        "sync_metadata": {
                            "detail_complete": True,
                            "observed_detail_url": "https://mock-recruiting.local/jobs/1",
                            "blockers": [],
                            "missing_fields": [],
                        },
                    },
                )
            ],
            finish_reason="tool_calls",
        ),
        LLMResponse(content="Should not be requested after the single JD target is reached."),
    )
    patched = client.patch(
        "/api/agents/jd_sync",
        json={
            "product_config": {
                "jd_sync": {
                    "jd_sync_config": {
                        "executionSop": {"siteEntryUrl": "https://mock-recruiting.local/jobs"},
                        "syncPolicy": {
                            "syncMode": "single_jd_probe",
                            "maxJobDescriptions": 1,
                            "jdSyncText": "单 JD 试跑：最多 1 个 JD。",
                        },
                    }
                }
            }
        },
    )
    assert patched.status_code == 200, patched.text
    created = client.post(
        "/api/agents/jd_sync/runs",
        json={"title": "Single JD Probe", "instruction": "single_jd_probe max_job_descriptions=1"},
    )
    assert created.status_code == 201, created.text

    processed = client.post("/api/agents/task-queue/process-next")

    assert processed.status_code == 200
    assert processed.json()["status"] == "processed"
    run_detail = client.get(f"/api/agents/jd_sync/runs/{created.json()['runId']}").json()
    assert run_detail["run"]["status"] == "idle"
    turn = run_detail["turns"][0]
    assert turn["status"] == "completed"
    assert turn["outcome_kind"] == "complete"
    assert "已写入 1 个 JD，目标 1 个" in turn["turn_metadata"]["final_output"]
    runtime_events = run_detail["events"]
    assert any(
        event["event_type"] == "turn_interrupted"
        and ((event.get("payload") or {}).get("data") or {}).get("reason") == "single_jd_probe_target_reached"
        for event in runtime_events
    )
    assert not any(
        event["event_type"] == "llm_invocation_started"
        and ((event.get("payload") or {}).get("data") or {}).get("index") == 1
        for event in runtime_events
    )
    with client.app.state.container.session_factory() as session:
        assert session.query(JobDescription).filter(JobDescription.source == "jd_sync").count() == 1


def test_jd_sync_run_dedupes_legacy_frontend_prompt_template(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "jd-sync-legacy-template")
    patched = client.patch(
        "/api/agents/jd_sync",
        json={
            "product_config": {
                "jd_sync": {
                    "jd_sync_config": {
                        "executionSop": {
                            "siteEntryUrl": "https://mock-recruiting.local/jobs",
                            "siteAccessRulesText": "复用已登录浏览器会话",
                        },
                    }
                }
            }
        },
    )
    assert patched.status_code == 200, patched.text

    legacy_frontend_instruction = "\n".join(
        [
            "从已保存的目标网页同步 JD。只发现和同步职位，不处理候选人筛选、评分、外联或投递推进。",
            "目标网页 URL：https://mock-recruiting.local/jobs",
            "同步完成后，再选择生效 JD 并配置 JD 策略、评分标准和完整执行 SOP。",
        ]
    )
    response = client.post(
        "/api/agents/jd_sync/runs",
        json={
            "title": "同步招聘站点 JD",
            "requestMessage": "同步招聘站点 JD",
            "instruction": legacy_frontend_instruction,
        },
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    runtime_metadata = payload["run"].get("runtimeMetadata") or payload["run"]["runtime_metadata"]
    instruction = runtime_metadata["instruction"]
    assert instruction.count("URL：https://mock-recruiting.local/jobs") == 1
    assert instruction.count("只发现和同步 JD") == 1
    assert "站点访问规则：" in instruction
    assert "再选择生效 JD" not in instruction


def test_jd_sync_process_next_task_when_autonomous_workspace_is_stopped(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "jd-sync-process-next-stopped")
    _script_autonomous_provider(
        client,
        LLMResponse(content="JD sync completed.", result_data={"execution_status": "completed"}),
    )
    patched = client.patch(
        "/api/agents/jd_sync",
        json={
            "product_config": {
                "jd_sync": {
                    "jd_sync_config": {
                        "executionSop": {
                            "siteEntryUrl": "https://mock-recruiting.local/jobs",
                            "siteAccessRulesText": "复用已登录浏览器会话",
                        },
                    }
                }
            }
        },
    )
    assert patched.status_code == 200, patched.text
    created = client.post(
        "/api/agents/jd_sync/runs",
        json={"title": "Sync JD", "instruction": "sync jobs"},
    )
    assert created.status_code == 201, created.text

    processed = client.post("/api/agents/task-queue/process-next")

    assert processed.status_code == 200
    assert processed.json()["status"] == "processed"
    run_id = created.json()["runId"]
    run_detail = client.get(f"/api/agents/jd_sync/runs/{run_id}")
    assert run_detail.status_code == 200
    assert run_detail.json()["turns"][0]["turn_metadata"]["final_output"] == "JD sync completed."


def test_jd_sync_resume_with_message_reuses_failed_run_and_injects_pending_input(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "jd-sync-resume-message")
    patched = client.patch(
        "/api/agents/jd_sync",
        json={
            "product_config": {
                "jd_sync": {
                    "jd_sync_config": {
                        "executionSop": {
                            "siteEntryUrl": "https://mock-recruiting.local/",
                            "siteAccessRulesText": "复用已登录浏览器会话",
                        },
                    }
                }
            }
        },
    )
    assert patched.status_code == 200, patched.text
    created = client.post(
        "/api/agents/jd_sync/runs",
        json={"title": "Sync JD", "requestMessage": "同步招聘站点 JD", "instruction": "sync jobs"},
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["runId"]

    with client.app.state.session_factory() as session:
        run = session.scalars(select(AgentRun).where(AgentRun.run_id == run_id)).one()
        first_task_id = run.queue_task_id
        run.status = "failed"
        run.finished_at = utcnow()
        run.last_error = "provider unavailable"
        session.commit()
        assert session.scalars(select(AgentRun).where(AgentRun.agent_kind == "jd_sync")).all() == [run]

    resumed = client.post(
        f"/api/agents/jd_sync/runs/{run_id}/resume",
        json={"reviewer": "api-test", "reason": "composer continue", "message": "继续", "priority": "next"},
    )

    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["run"]["runId"] == run_id
    assert resumed.json()["run"]["status"] == "queued"
    with client.app.state.session_factory() as session:
        runs = session.scalars(select(AgentRun).where(AgentRun.agent_kind == "jd_sync")).all()
        assert len(runs) == 1
        run = runs[0]
        assert run.run_id == run_id
        assert run.finished_at is None
        assert run.queue_task_id == first_task_id
        assert run.wakeup_state["resume_message"] == "继续"
        task = session.scalars(select(TaskQueueItem).where(TaskQueueItem.id == resumed.json()["task_id"])).one()
        assert task.id == first_task_id
        assert task.status == "pending"
        assert task.payload["trigger_type"] == "resume"
        assert task.payload["pending_input"] == [
            {"input_id": None, "priority": "next", "queued_by": "api-test", "message": "继续"}
        ]
        assert task.payload["world_snapshot"]["pending_input"] == task.payload["pending_input"]
    conversation = client.get("/api/agents/jd_sync/conversations/jd-sync-primary")
    assert conversation.status_code == 200
    messages = conversation.json()["messages"]
    run_inputs = [message for message in messages if message.get("metadata", {}).get("message_type") == "run_input"]
    assert len(run_inputs) == 1
    resumed_input = next(
        message
        for message in messages
        if message.get("metadata", {}).get("traceKind") == "user_message"
        and message["content"] == "继续"
    )
    assert resumed_input["role"] == "user"
    assert resumed_input["kind"] == "message"


def test_task_queue_process_next_processes_one_queued_task(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "scheduler-run-next")
    _script_autonomous_provider(
        client,
        LLMResponse(content="Processed through scheduler alias.", result_data={"execution_status": "completed"}),
    )
    _force_start_workspace(client)
    created = _start_autonomous_run(client)

    processed = client.post("/api/agents/task-queue/process-next")

    assert processed.status_code == 200
    assert processed.json()["status"] == "processed"
    run_detail = client.get(f"/api/agents/autonomous/runs/{created['runId']}").json()
    assert run_detail["turns"][0]["turn_metadata"]["final_output"] == "Processed through scheduler alias."


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


def test_agent_update_merges_automation_product_config_without_overwriting_other_kind(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "agent-product-config")
    configured = client.patch(
        "/api/agents/jd_sync",
        json={
            "product_config": {
                "jd_sync": {
                    "jd_sync_config": {
                        "executionSop": {
                            "siteEntryUrl": "https://mock-recruiting.local/jobs",
                            "siteAccessRulesText": "复用已登录浏览器会话",
                        },
                    }
                }
            }
        },
    )
    assert configured.status_code == 200, configured.text

    response = client.patch(
        "/api/agents/autonomous",
        json={
            "product_config": {
                "autonomous": {
                    "automation_recruiting_config": {
                        "defaultRunJobIds": ["jd-1"],
                        "jobStrategies": {"jd-1": {"screeningCriteria": "Must match JD"}},
                    }
                }
            }
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    product_config = payload["productConfig"]
    assert product_config["autonomous"]["automation_recruiting_config"]["defaultRunJobIds"] == ["jd-1"]
    assert product_config["autonomous"]["context_policy"]
    assert product_config["jd_sync"]["jd_sync_config"]["executionSop"]["siteEntryUrl"] == "https://mock-recruiting.local/jobs"
    assert product_config["assistant"]["memory_policy"]


def test_agent_update_preserves_existing_jd_sync_entry_url_on_empty_patch(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "jd-sync-entry-url-preserve")

    configured = client.patch(
        "/api/agents/jd_sync",
        json={
            "product_config": {
                "jd_sync": {
                    "jd_sync_config": {
                        "executionSop": {
                            "siteEntryUrl": "https://mock-recruiting.local/jobs",
                            "siteAccessRulesText": "复用已登录浏览器会话",
                        },
                    }
                }
            }
        },
    )
    assert configured.status_code == 200, configured.text

    response = client.patch(
        "/api/agents/jd_sync",
        json={
            "product_config": {
                "jd_sync": {
                    "jd_sync_config": {
                        "executionSop": {
                            "siteEntryUrl": "",
                            "siteAccessRulesText": "更新边界说明",
                        },
                    }
                }
            }
        },
    )

    assert response.status_code == 200, response.text
    jd_sync_config = response.json()["productConfig"]["jd_sync"]["jd_sync_config"]
    assert jd_sync_config["executionSop"]["siteEntryUrl"] == "https://mock-recruiting.local/jobs"
    assert jd_sync_config["executionSop"]["siteAccessRulesText"] == "更新边界说明"


def test_agent_update_deep_merges_nested_product_config(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "agent-product-config-deep-merge")

    configured = client.patch(
        "/api/agents/jd_sync",
        json={
            "product_config": {
                "jd_sync": {
                    "jd_sync_config": {
                        "executionSop": {
                            "siteEntryUrl": "https://mock-recruiting.local/jobs",
                            "siteAccessRulesText": "复用已登录浏览器会话",
                        },
                        "syncPolicy": {"jdSyncText": "同步 JD"},
                    }
                }
            }
        },
    )
    assert configured.status_code == 200, configured.text

    response = client.patch(
        "/api/agents/jd_sync",
        json={
            "product_config": {
                "jd_sync": {
                    "jd_sync_config": {
                        "executionSop": {
                            "siteAccessRulesText": "只更新边界",
                        },
                    }
                }
            }
        },
    )

    assert response.status_code == 200, response.text
    jd_sync_config = response.json()["productConfig"]["jd_sync"]["jd_sync_config"]
    assert jd_sync_config["executionSop"]["siteEntryUrl"] == "https://mock-recruiting.local/jobs"
    assert jd_sync_config["executionSop"]["siteAccessRulesText"] == "只更新边界"
    assert jd_sync_config["syncPolicy"]["jdSyncText"] == "同步 JD"


def test_workspace_start_blocks_incomplete_automation_config_without_starting_heartbeat(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "workspace-start-blocked")

    started = _start_workspace(client)

    assert started["state"] == "stopped"
    assert started["autonomousPaused"] is True
    assert "automation_recruiting_config incomplete" in started["runStartBlocked"]["reason"]
    assert client.get("/api/agents/autonomous/runs").json() == []
    assert client.post("/api/agents/task-queue/process-next").json()["status"] == "stopped"


def test_workspace_start_creates_run_from_saved_automation_config(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "saved-automation-start")
    patched = client.patch(
        "/api/agents/autonomous",
        json={
            "product_config": {
                "autonomous": {
                    "automation_recruiting_config": {
                        "defaultRunJobIds": ["jd-a", "jd-b"],
                        "executionSop": {
                            "siteEntryUrl": "https://www.zhipin.com/web/geek/job",
                            "siteAccessRulesText": "复用已登录浏览器会话\n不处理登录验证码或账号切换",
                            "stepsText": "score candidates",
                        },
                        "activationPolicy": {
                            "priorityPreset": "balanced",
                            "priority_preset": "urgent",
                            "startConditionsText": "每天早上开始",
                            "start_conditions_text": "每天早上开始",
                            "stopConditionsText": "没有候选人就停止",
                            "stop_conditions_text": "没有候选人就停止",
                            "priorityWeightsText": "优先未读消息",
                            "priority_weights_text": "优先未读消息",
                            "cooldownRulesText": "每小时冷却",
                            "cooldown_rules_text": "每小时冷却",
                            "manualStartEnabled": True,
                            "scheduledScanEnabled": True,
                            "scanIntervalMinutes": 30,
                            "jdPoolGapEnabled": True,
                            "candidatePoolTarget": 25,
                            "externalEventWakeEnabled": True,
                            "backlogWakeEnabled": True,
                            "backlogThreshold": 8,
                            "stopOnJdOffline": True,
                            "pauseOnLoginRequired": True,
                            "pauseOnEntryUnavailable": True,
                            "pauseOnApprovalPending": True,
                            "pauseOnNoProgress": True,
                            "priorityDiscoveryWeight": 35,
                            "priorityUnreadMessageWeight": 25,
                            "priorityScoringBacklogWeight": 20,
                            "priorityApprovalWeight": 10,
                            "priorityJdGapWeight": 10,
                            "messageSlaMinutes": 120,
                            "siteCooldownMinutes": 15,
                            "retryCooldownMinutes": 5,
                            "maxActionsPerHour": 40,
                            "maxConsecutiveErrors": 3,
                        },
                        "jobStrategies": {
                            "jd-a": _complete_job_strategy(),
                            "jd-b": _complete_job_strategy(online_pass=72, offline_pass=74, composite_pass=78, review_min=62),
                        },
                        "toolApprovalPolicy": {
                            "defaultMode": "auto",
                            "overrides": {"business:send_candidate_message": "approval"},
                        },
                    }
                }
            }
        },
    )
    assert patched.status_code == 200, patched.text

    started = _start_workspace(client)

    assert started["state"] == "running"
    assert (started["run"].get("runType") or started["run"]["run_type"]) == "multi_jd_recruiting"
    runtime_metadata = started["run"].get("runtimeMetadata") or started["run"]["runtime_metadata"]
    constraints = runtime_metadata["constraints"]
    assert constraints["selected_job_description_ids"] == ["jd-a", "jd-b"]
    assert constraints["target_recruiting_site"]["entry_url"] == "https://www.zhipin.com/web/geek/job"
    assert "site_label" not in constraints["target_recruiting_site"]
    assert "account_label" not in constraints["target_recruiting_site"]
    assert constraints["target_recruiting_site"]["access_rules"] == ["复用已登录浏览器会话", "不处理登录验证码或账号切换"]
    compiled_sop = constraints["execution_sop"]["compiledPrompt"]
    assert "招聘网站目标网页 URL：https://www.zhipin.com/web/geek/job" in compiled_sop
    assert "## BOSS/zhipin 主导航锚点与禁区" in compiled_sop
    assert "顶层页面入口只允许使用 BOSS 主导航可见入口：职位管理、推荐牛人、搜索、沟通" in compiled_sop
    assert "BOSS/zhipin 恢复不得打开新标签/新窗口，不得使用地址栏输入 URL" in compiled_sop
    assert "多个 zhipin.com 页签同时存在时，优先恢复到已打开的 BOSS 招聘管理工作台页签" in compiled_sop
    assert "不要新开另一个 zhipin 页签" in compiled_sop
    assert "如果只有公共首页存在，可以通过该页可见的同站点入口在同一页签内恢复到招聘管理工作台；不得打开新标签/新窗口" in compiled_sop
    assert "如果 browser-mcp/native host 不可用导致无法观察已有 BOSS 页签或招聘管理页签，不得新建 BOSS/zhipin 页签" in compiled_sop
    assert "公共首页上的求职职位列表、城市职位列表或搜索结果不得作为 employer JD sync 完成证据" in compiled_sop
    assert "招聘规范、我的客服、面试、招聘数据、账号权益、升级VIP" in compiled_sop
    assert "右上 JD 选择器示例如 产品实习生_北京 2-4K" in compiled_sop
    assert "实际职位标题、城市、薪资和关键词以本次启用/选中 JD 为准" in compiled_sop
    assert "不得为了匹配截图示例而跨 JD" in compiled_sop
    assert "沟通页 read-only 可读取候选人行、JD 标签" in compiled_sop
    assert "1. jd-a" in compiled_sop
    assert "2. jd-b" in compiled_sop
    assert "score candidates" in compiled_sop
    instruction = runtime_metadata["instruction"]
    assert "## 自动化招聘执行 SOP" in instruction
    assert "招聘网站目标网页 URL：https://www.zhipin.com/web/geek/job" in instruction
    assert "1. jd-a" in instruction
    assert "2. jd-b" in instruction
    assert "score candidates" in instruction
    assert "沟通页中的未读沟通和候选人主动打招呼记录优先级最高" not in instruction
    legacy_activation_keys = {
        "priorityPreset",
        "priority_preset",
        "startConditionsText",
        "start_conditions_text",
        "stopConditionsText",
        "stop_conditions_text",
        "priorityWeightsText",
        "priority_weights_text",
        "cooldownRulesText",
        "cooldown_rules_text",
    }
    _assert_keys_absent(constraints, legacy_activation_keys)
    activation_policy = constraints["activation_policy"]
    assert activation_policy["programmaticAuthority"] is True
    assert activation_policy["manualStartEnabled"] is True
    assert activation_policy["scheduledScanEnabled"] is True
    assert activation_policy["scanIntervalMinutes"] == 30
    assert activation_policy["jdPoolGapEnabled"] is True
    assert activation_policy["candidatePoolTarget"] == 25
    assert activation_policy["externalEventWakeEnabled"] is True
    assert activation_policy["backlogWakeEnabled"] is True
    assert activation_policy["backlogThreshold"] == 8
    assert activation_policy["stopOnJdOffline"] is True
    assert activation_policy["pauseOnLoginRequired"] is True
    assert activation_policy["pauseOnEntryUnavailable"] is True
    assert activation_policy["pauseOnApprovalPending"] is True
    assert activation_policy["pauseOnNoProgress"] is True
    assert activation_policy["priorityDiscoveryWeight"] == 35
    assert activation_policy["priorityUnreadMessageWeight"] == 25
    assert activation_policy["priorityScoringBacklogWeight"] == 20
    assert activation_policy["priorityApprovalWeight"] == 10
    assert activation_policy["priorityJdGapWeight"] == 10
    assert activation_policy["messageSlaMinutes"] == 120
    assert activation_policy["siteCooldownMinutes"] == 15
    assert activation_policy["retryCooldownMinutes"] == 5
    assert activation_policy["maxActionsPerHour"] == 40
    assert activation_policy["maxConsecutiveErrors"] == 3
    assert constraints["runtime_controls"]["decision_authority"] == "programmatic_thresholds_and_approval_gates"
    assert constraints["runtime_controls"]["activation_policy"] == activation_policy
    assert constraints["tool_approval_policy"]["overrides"]["business:send_candidate_message"] == "approval"
    queue = client.get("/api/agents/queue").json()
    queue_constraints = queue[0]["payload"]["metadata"]["constraints"]
    assert queue_constraints["plan_kind"] == "multi_jd_recruiting"
    _assert_keys_absent(queue_constraints, legacy_activation_keys)
    assert queue_constraints["runtime_controls"]["activation_policy"]["scanIntervalMinutes"] == 30


def test_direct_recruiting_run_merges_saved_automation_config(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "direct-recruiting-saved-config")
    patched = client.patch(
        "/api/agents/autonomous",
        json={
            "product_config": {
                "autonomous": {
                    "automation_recruiting_config": {
                        "defaultRunJobIds": ["jd-a", "jd-b"],
                        "executionSop": {
                            "siteEntryUrl": "https://www.zhipin.com/web/chat/index",
                            "siteAccessRulesText": "复用已登录浏览器会话",
                            "stepsText": "先处理沟通未读，再进入推荐牛人或搜索。",
                        },
                        "activationPolicy": {
                            "manualStartEnabled": True,
                            "scheduledScanEnabled": True,
                            "scanIntervalMinutes": 30,
                            "jdPoolGapEnabled": True,
                            "candidatePoolTarget": 25,
                            "externalEventWakeEnabled": True,
                            "backlogWakeEnabled": True,
                            "backlogThreshold": 8,
                            "stopOnJdOffline": True,
                            "pauseOnLoginRequired": True,
                            "pauseOnEntryUnavailable": True,
                            "pauseOnApprovalPending": True,
                            "pauseOnNoProgress": True,
                            "priorityDiscoveryWeight": 35,
                            "priorityUnreadMessageWeight": 25,
                            "priorityScoringBacklogWeight": 20,
                            "priorityApprovalWeight": 10,
                            "priorityJdGapWeight": 10,
                            "messageSlaMinutes": 120,
                            "siteCooldownMinutes": 15,
                            "retryCooldownMinutes": 5,
                            "maxActionsPerHour": 40,
                            "maxConsecutiveErrors": 3,
                        },
                        "jobStrategies": {
                            "jd-a": _complete_job_strategy(),
                            "jd-b": _complete_job_strategy(online_pass=72),
                        },
                        "toolApprovalPolicy": {"defaultMode": "approval"},
                    }
                }
            }
        },
    )
    assert patched.status_code == 200, patched.text

    created = client.post(
        "/api/agents/autonomous/runs",
        json={
            "title": "单候选人只读阶段",
            "instruction": "read_only_candidate_probe max_candidates=1",
            "kind": "recruiting",
            "constraints": {
                "read_only": True,
                "max_candidates": 1,
                "max_new_candidates": 0,
                "selected_job_description_ids": ["jd-a"],
                "execution_sop": {"stepsText": "caller override must not run"},
                "browser_target": {"url": "https://evil.example.test"},
            },
        },
    )

    assert created.status_code == 201, created.text
    run_payload = created.json()["run"]
    runtime_metadata = run_payload.get("runtimeMetadata") or run_payload["runtime_metadata"]
    constraints = runtime_metadata["constraints"]
    assert constraints["read_only"] is True
    assert constraints["selected_job_description_ids"] == ["jd-a"]
    assert constraints["enabled_job_description_ids"] == ["jd-a"]
    assert constraints["execution_sop"]["stepsText"] == "先处理沟通未读，再进入推荐牛人或搜索。"
    assert constraints["execution_sop"]["compiledPrompt"].count("jd-a") == 1
    assert "caller override must not run" not in constraints["execution_sop"]["compiledPrompt"]
    assert constraints["target_recruiting_site"]["entry_url"] == "https://www.zhipin.com/web/chat/index"
    assert constraints["browser_target"]["url"] == "https://www.zhipin.com/web/chat/index"
    assert constraints["business_policy_overlay"]["job_plans"] == [
        {"job_description_id": "jd-a", "strategy": _complete_job_strategy()}
    ]
    assert constraints["tool_approval_policy"]["defaultMode"] == "approval"
    instruction = runtime_metadata["instruction"]
    assert "## 自动化招聘执行 SOP" in instruction
    assert "本地 JD 状态 active 表示可用于本次运行" in instruction
    assert "先处理沟通未读，再进入推荐牛人或搜索。" in instruction
    assert "caller override must not run" not in instruction
    assert runtime_metadata["browser_target"]["url"] == "https://www.zhipin.com/web/chat/index"
    queue = client.get("/api/agents/queue").json()
    assert queue[0]["payload"]["world_snapshot"]["browser_target"]["url"] == "https://www.zhipin.com/web/chat/index"


def test_direct_recruiting_run_rejects_unconfigured_selected_jd(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "direct-recruiting-unknown-jd")
    patched = client.patch(
        "/api/agents/autonomous",
        json={
            "product_config": {
                "autonomous": {
                    "automation_recruiting_config": {
                        "defaultRunJobIds": ["jd-a"],
                        "executionSop": {
                            "siteEntryUrl": "https://www.zhipin.com/web/chat/index",
                            "stepsText": "score candidates",
                        },
                        "activationPolicy": {
                            "manualStartEnabled": True,
                            "scheduledScanEnabled": True,
                            "scanIntervalMinutes": 30,
                            "jdPoolGapEnabled": True,
                            "candidatePoolTarget": 25,
                            "externalEventWakeEnabled": True,
                            "backlogWakeEnabled": True,
                            "backlogThreshold": 8,
                            "stopOnJdOffline": True,
                            "pauseOnLoginRequired": True,
                            "pauseOnEntryUnavailable": True,
                            "pauseOnApprovalPending": True,
                            "pauseOnNoProgress": True,
                            "priorityDiscoveryWeight": 35,
                            "priorityUnreadMessageWeight": 25,
                            "priorityScoringBacklogWeight": 20,
                            "priorityApprovalWeight": 10,
                            "priorityJdGapWeight": 10,
                            "messageSlaMinutes": 120,
                            "siteCooldownMinutes": 15,
                            "retryCooldownMinutes": 5,
                            "maxActionsPerHour": 40,
                            "maxConsecutiveErrors": 3,
                        },
                        "jobStrategies": {"jd-a": _complete_job_strategy()},
                    }
                }
            }
        },
    )
    assert patched.status_code == 200, patched.text

    response = client.post(
        "/api/agents/autonomous/runs",
        json={
            "title": "Unknown JD",
            "instruction": "read_only_candidate_probe",
            "kind": "recruiting",
            "constraints": {"selected_job_description_ids": ["jd-x"]},
        },
    )

    assert response.status_code == 409
    assert "selected_job_description_ids must be configured" in response.json()["detail"]


def test_runtime_agents_cannot_have_open_runs_at_the_same_time(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "runtime-mutual-exclusion")
    automation_patch = client.patch(
        "/api/agents/autonomous",
        json={
            "product_config": {
                "autonomous": {
                    "automation_recruiting_config": {
                        "defaultRunJobIds": ["jd-a"],
                        "executionSop": {
                            "siteEntryUrl": "https://www.zhipin.com/web/geek/job",
                            "stepsText": "score candidates",
                        },
                        "activationPolicy": {
                            "manualStartEnabled": True,
                            "scheduledScanEnabled": True,
                            "scanIntervalMinutes": 30,
                            "jdPoolGapEnabled": True,
                            "candidatePoolTarget": 25,
                            "externalEventWakeEnabled": True,
                            "backlogWakeEnabled": True,
                            "backlogThreshold": 8,
                            "stopOnJdOffline": True,
                            "pauseOnLoginRequired": True,
                            "pauseOnEntryUnavailable": True,
                            "pauseOnApprovalPending": True,
                            "pauseOnNoProgress": True,
                            "priorityDiscoveryWeight": 35,
                            "priorityUnreadMessageWeight": 25,
                            "priorityScoringBacklogWeight": 20,
                            "priorityApprovalWeight": 10,
                            "priorityJdGapWeight": 10,
                            "messageSlaMinutes": 120,
                            "siteCooldownMinutes": 15,
                            "retryCooldownMinutes": 5,
                            "maxActionsPerHour": 40,
                            "maxConsecutiveErrors": 3,
                        },
                        "jobStrategies": {"jd-a": _complete_job_strategy()},
                    }
                },
                "jd_sync": {
                    "jd_sync_config": {
                        "executionSop": {"siteEntryUrl": "https://www.zhipin.com/web/chat/index"},
                        "syncPolicy": {"jdSyncText": "同步 JD"},
                    }
                },
            }
        },
    )
    assert automation_patch.status_code == 200, automation_patch.text

    jd_sync = client.post("/api/agents/jd_sync/runs", json={"title": "Sync JD", "instruction": "sync jobs"})
    assert jd_sync.status_code == 201, jd_sync.text

    blocked_start = _start_workspace(client)
    assert blocked_start["state"] == "stopped"
    assert "JD Sync and automation recruiting cannot run at the same time" in blocked_start["runStartBlocked"]["reason"]

    blocked_run = client.post(
        "/api/agents/autonomous/runs",
        json={"title": "Automation", "instruction": "start", "kind": "multi_jd_recruiting"},
    )
    assert blocked_run.status_code == 409
    assert "JD Sync and automation recruiting cannot run at the same time" in blocked_run.json()["detail"]


def test_jd_sync_run_is_blocked_when_automation_run_is_open(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "jd-sync-blocked-by-automation")
    patched = client.patch(
        "/api/agents/jd_sync",
        json={
            "product_config": {
                "jd_sync": {
                    "jd_sync_config": {
                        "executionSop": {"siteEntryUrl": "https://www.zhipin.com/web/chat/index"},
                        "syncPolicy": {"jdSyncText": "同步 JD"},
                    }
                }
            }
        },
    )
    assert patched.status_code == 200, patched.text
    _start_autonomous_run(client)

    blocked = client.post("/api/agents/jd_sync/runs", json={"title": "Sync JD", "instruction": "sync jobs"})

    assert blocked.status_code == 409
    assert "JD Sync and automation recruiting cannot run at the same time" in blocked.json()["detail"]


def test_autonomous_process_next_task_completes_run_and_projects_primary_conversation(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "process-next")
    _script_autonomous_provider(
        client,
        LLMResponse(
            content="Completed candidate search.",
            result_data={"execution_status": "completed"},
        ),
        LLMResponse(
            content="Second task completed after clear.",
            result_data={"execution_status": "completed"},
        ),
    )
    _force_start_workspace(client)
    created = _start_autonomous_run(client)

    processed = client.post("/api/agents/task-queue/process-next")

    assert processed.status_code == 200
    assert processed.json()["status"] == "processed"
    run_detail = client.get(f"/api/agents/autonomous/runs/{created['runId']}")
    assert run_detail.status_code == 200
    run_payload = run_detail.json()
    assert run_payload["run"]["status"] == "idle"
    assert run_payload["turns"][0]["status"] == "completed"
    assert run_payload["turns"][0]["turn_metadata"]["final_output"] == "Completed candidate search."
    assert {event["event_type"] for event in run_payload["events"]} >= {"adapter_turn_started", "turn_completed"}
    assert all("goal" not in str(item).lower() for item in (run_payload["run"], *run_payload["turns"], *run_payload["events"]))

    conversation = client.get("/api/agents/autonomous/conversations/autonomous-primary")
    assert conversation.status_code == 200
    assert conversation.json()["conversation"]["id"] == "autonomous-primary"
    messages = conversation.json()["messages"]
    run_input = next(
        message
        for message in messages
        if message.get("metadata", {}).get("message_type") == "run_input"
        and message.get("metadata", {}).get("run_id") == created["runId"]
    )
    run_status = next(message for message in messages if message.get("metadata", {}).get("message_type") == "run")
    final_output = next(message for message in messages if message["content"] == "Completed candidate search.")
    assert run_input["role"] == "user"
    assert run_input["kind"] == "message"
    assert run_input["content"] == "Find one candidate and stop for approval before external action."
    assert run_input["title"] == "Find one candidate"
    assert final_output["role"] == "assistant"
    assert final_output["kind"] == "message"
    assert messages.index(run_input) < messages.index(run_status) < messages.index(final_output)


def test_assistant_conversation_clear_removes_turn_history(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "assistant-clear")
    created = client.post(
        "/api/agents/assistant/conversations",
        json={"user_id": "api-test", "title": "Clear me"},
    )
    assert created.status_code == 201, created.text
    conversation_id = created.json()["conversationId"]
    client.app.state.container.assistant_adapter.session_store.append_turn(
        conversation_id,
        role="user",
        content={"text": "hello"},
    )
    before = client.get(f"/api/agents/assistant/conversations/{conversation_id}")
    assert before.status_code == 200
    assert len(before.json()["messages"]) == 1

    cleared = client.post(
        f"/api/agents/assistant/conversations/{conversation_id}/clear",
        json={"reviewer": "api-test", "reason": "reset chat"},
    )

    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["cleared"] is True
    assert cleared.json()["messages"] == []
    after = client.get(f"/api/agents/assistant/conversations/{conversation_id}")
    assert after.status_code == 200
    assert after.json()["messages"] == []


def test_autonomous_primary_conversation_clear_resets_projected_history(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "autonomous-clear")
    _script_autonomous_provider(
        client,
        LLMResponse(
            content="Completed candidate search.",
            result_data={"execution_status": "completed"},
        ),
        LLMResponse(
            content="Second task completed after clear.",
            result_data={"execution_status": "completed"},
        ),
    )
    _force_start_workspace(client)
    created = _start_autonomous_run(client)
    processed = client.post("/api/agents/task-queue/process-next")
    assert processed.status_code == 200
    before = client.get("/api/agents/autonomous/conversations/autonomous-primary")
    assert any(message["content"] == "Completed candidate search." for message in before.json()["messages"])

    cleared = client.post(
        "/api/agents/autonomous/conversations/autonomous-primary/clear",
        json={"reviewer": "api-test", "reason": "reset agent conversation"},
    )

    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["cleared"] is True
    assert cleared.json()["messages"] == []
    after = client.get("/api/agents/autonomous/conversations/autonomous-primary")
    assert after.status_code == 200
    assert after.json()["messages"] == []
    workspace = client.get("/api/agents/autonomous/workspace")
    assert workspace.status_code == 200
    assert workspace.json()["runs"] == []
    run_detail = client.get(f"/api/agents/autonomous/runs/{created['runId']}")
    assert run_detail.status_code == 200

    next_run = _start_autonomous_run(client, title="After clear", instruction="Run after clear.")
    assert next_run["status"] == "queued"
    workspace_after_start = client.get("/api/agents/autonomous/workspace")
    assert workspace_after_start.status_code == 200
    assert [run["runId"] for run in workspace_after_start.json()["runs"]] == [next_run["runId"]]

    processed_again = client.post("/api/agents/task-queue/process-next")
    assert processed_again.status_code == 200
    after_second_run = client.get("/api/agents/autonomous/conversations/autonomous-primary")
    assert any(message["content"] == "Second task completed after clear." for message in after_second_run.json()["messages"])
    assert all(message["content"] != "Completed candidate search." for message in after_second_run.json()["messages"])


def test_runtime_message_enqueues_pending_user_input_after_next_tool_call_for_open_run(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "runtime-message-queue")
    _force_start_workspace(client)
    created = _start_autonomous_run(client)

    response = client.post(
        "/api/agents/autonomous/conversations/autonomous-primary/pending-user-input-after-next-tool-call",
        json={"message": "Narrow this run to backend candidates only.", "priority": "next"},
    )

    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["conversationId"] == "autonomous-primary"
    assert payload["runId"] == created["runId"]
    assert payload["inputId"]
    assert payload["pending_user_input"]["delivery"] == "after_next_tool_call"
    with client.app.state.session_factory() as session:
        pending_user_input = session.scalars(select(AgentPendingUserInput)).one()
        assert pending_user_input.agent_kind == "autonomous"
        assert pending_user_input.conversation_id == "autonomous-primary"
        assert pending_user_input.run_id == created["runId"]
        assert pending_user_input.message == "Narrow this run to backend candidates only."
        assert pending_user_input.status == "pending"


def test_runtime_pending_user_input_after_next_tool_call_is_injected_before_next_model_step(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "runtime-message-consume")
    provider = _script_autonomous_provider(
        client,
        LLMResponse(
            tool_calls=[ToolCall(id="observe-1", name="test.observe", arguments={"scope": "jobs"})],
            finish_reason="tool_calls",
        ),
        LLMResponse(content="Input processed after tool call.", result_data={"execution_status": "completed"}),
    )
    client.app.state.container.tool_registry.register(
        ToolDefinition(
            name="test.observe",
            description="Observe a test page.",
            parameters={"type": "object", "additionalProperties": True},
            handler=lambda arguments: {"observed": arguments.get("scope")},
            category="core",
            external_target=False,
        )
    )
    _force_start_workspace(client)
    created = _start_autonomous_run(client)
    queued = client.post(
        "/api/agents/autonomous/conversations/autonomous-primary/pending-user-input-after-next-tool-call",
        json={"message": "Narrow this run to backend candidates only.", "priority": "next"},
    )
    assert queued.status_code == 202, queued.text

    processed = client.post("/api/agents/task-queue/process-next")

    assert processed.status_code == 200
    assert processed.json()["status"] == "processed"
    with client.app.state.session_factory() as session:
        pending_user_input = session.scalars(select(AgentPendingUserInput)).one()
        run = session.scalars(select(AgentRun).where(AgentRun.run_id == created["runId"])).one()
        assert pending_user_input.status == "consumed"
        assert pending_user_input.claimed_by == "pending_user_input_after_next_tool_call"
        assert pending_user_input.input_metadata["turn_id"]
        assert pending_user_input.input_metadata["tool_name"] == "test.observe"
        assert run.status == "idle"
    injected_contexts = [
        "\n".join(str(message.content) for message in request.messages)
        for request in provider.captured_requests
        if any("Pending user input after next tool call" in str(message.content) for message in request.messages)
    ]
    assert injected_contexts
    assert "Narrow this run to backend candidates only." in injected_contexts[-1]
    run_detail = client.get(f"/api/agents/autonomous/runs/{created['runId']}").json()
    assert run_detail["run"]["status"] == "idle"
    assert [turn["trigger_type"] for turn in run_detail["turns"]] == ["run_triggered"]
    assert run_detail["turns"][-1]["turn_metadata"]["final_output"] == "Input processed after tool call."
    assert any(
        event["event_type"] == "runtime_event"
        and ((event.get("payload") or {}).get("data") or {}).get("kind") == "pending_user_input_after_next_tool_call_injected"
        for event in run_detail["events"]
    )
    conversation = client.get("/api/agents/autonomous/conversations/autonomous-primary")
    assert conversation.status_code == 200
    messages = conversation.json()["messages"]
    injected_input = next(
        message
        for message in messages
        if message.get("metadata", {}).get("traceKind") == "user_message"
        and message["content"] == "Narrow this run to backend candidates only."
    )
    assert injected_input["role"] == "user"
    assert "Pending user input after next tool call" not in injected_input["content"]


def test_runtime_primary_conversation_projects_assistant_delta_as_streaming_message(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "conversation-assistant-delta")
    _force_start_workspace(client)
    created = _start_autonomous_run(client, title="Stream answer", instruction="Explain progress.")

    with client.app.state.session_factory() as session:
        run = session.scalars(select(AgentRun).where(AgentRun.run_id == created["runId"])).one()
        session.add(
            AgentRuntimeEvent(
                session_id=run.session_id,
                run_id=run.id,
                source="autonomous",
                event_type="assistant_message_delta",
                message="assistant_message_delta",
                seq=1,
                payload={
                    "type": "assistant_message_delta",
                    "data": {"delta": "正在", "invocation_id": "inv-stream"},
                },
            )
        )
        session.add(
            AgentRuntimeEvent(
                session_id=run.session_id,
                run_id=run.id,
                source="autonomous",
                event_type="assistant_message_delta",
                message="assistant_message_delta",
                seq=2,
                payload={
                    "type": "assistant_message_delta",
                    "data": {"delta": "处理", "invocation_id": "inv-stream"},
                },
            )
        )
        session.commit()

    conversation = client.get("/api/agents/autonomous/conversations/autonomous-primary")

    assert conversation.status_code == 200
    messages = conversation.json()["messages"]
    streaming = next(
        message
        for message in messages
        if message.get("metadata", {}).get("traceKind") == "assistant_message"
    )
    assert streaming["role"] == "assistant"
    assert streaming["kind"] == "message"
    assert streaming["status"] == "streaming"
    assert streaming["content"] == "正在处理"


def test_runtime_primary_conversation_projects_provider_retry_and_failure_events(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "conversation-provider-retry")
    _force_start_workspace(client)
    created = _start_autonomous_run(client, title="Retry provider", instruction="Run with transient provider issue.")

    with client.app.state.session_factory() as session:
        run = session.scalars(select(AgentRun).where(AgentRun.run_id == created["runId"])).one()
        session.add(
            AgentRuntimeEvent(
                session_id=run.session_id,
                run_id=run.id,
                source="autonomous",
                event_type="runtime_event",
                message="provider_retry_scheduled",
                seq=1,
                payload={
                    "type": "runtime_event",
                    "data": {
                        "kind": "provider_retry_scheduled",
                        "invocation_id": "inv-provider",
                        "attempt": 1,
                        "max_attempts": 3,
                        "delay_seconds": 0,
                        "error": "HTTP 500 calling provider",
                        "error_kind": "provider_http_error",
                        "status_code": 500,
                        "retryable": True,
                    },
                },
            )
        )
        session.add(
            AgentRuntimeEvent(
                session_id=run.session_id,
                run_id=run.id,
                source="autonomous",
                event_type="turn_failed",
                message="HTTP 500 calling provider",
                seq=2,
                payload={
                    "type": "turn_failed",
                    "data": {
                        "error": "HTTP 500 calling provider",
                        "error_kind": "provider_http_error",
                        "status_code": 500,
                        "retryable": True,
                    },
                },
            )
        )
        session.commit()

    conversation = client.get("/api/agents/autonomous/conversations/autonomous-primary")

    assert conversation.status_code == 200
    messages = conversation.json()["messages"]
    retry = next(message for message in messages if message.get("metadata", {}).get("traceKind") == "provider_retry_scheduled")
    failure = next(message for message in messages if message.get("metadata", {}).get("traceKind") == "turn_failed")
    assert retry["title"] == "模型调用重试"
    assert "准备重试" in retry["content"]
    assert retry["status"] == "active"
    assert failure["title"] == "运行失败"
    assert failure["status"] == "failed"
    assert failure["metadata"]["payload"]["data"]["status_code"] == 500


def test_autonomous_primary_conversation_projects_tool_call_and_result_events(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "conversation-tool-events")
    _script_autonomous_provider(
        client,
        LLMResponse(
            tool_calls=[ToolCall(id="observe-jobs", name="browser_snapshot", arguments={"capture": "jobs"})],
            finish_reason="tool_calls",
        ),
        LLMResponse(content="JD sync observation completed.", result_data={"execution_status": "completed"}),
    )
    client.app.state.container.tool_registry.register(
        ToolDefinition(
            name="browser_snapshot",
            description="Observe the recruiting page.",
            parameters={"type": "object", "additionalProperties": True},
            handler=lambda arguments: {"semantic_mapping": {"jobs": [{"title": "Backend Engineer"}]}, "arguments": arguments},
            category="plugin",
            external_target=False,
        )
    )
    _force_start_workspace(client)
    created = _start_autonomous_run(client, title="Observe recruiting jobs", instruction="Observe jobs.")

    processed = client.post("/api/agents/task-queue/process-next")

    assert processed.status_code == 200
    assert processed.json()["status"] == "processed"
    conversation = client.get("/api/agents/autonomous/conversations/autonomous-primary")
    assert conversation.status_code == 200
    messages = conversation.json()["messages"]
    tool_call = next(
        message
        for message in messages
        if message.get("metadata", {}).get("traceKind") == "tool_call"
        and message.get("metadata", {}).get("toolName") == "browser_snapshot"
    )
    tool_result = next(
        message
        for message in messages
        if message.get("metadata", {}).get("traceKind") == "tool_result"
        and message.get("metadata", {}).get("toolName") == "browser_snapshot"
    )
    final_output = next(message for message in messages if message["content"] == "JD sync observation completed.")
    assert "参数" in tool_call["content"]
    assert "Backend Engineer" in tool_result["content"]
    assert messages.index(tool_call) < messages.index(tool_result) < messages.index(final_output)
    assert created["runId"] in {message.get("metadata", {}).get("run_id") for message in messages}


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


def test_autonomous_cancelled_run_envelope_does_not_start_turn(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "cancel-before-start")
    provider = _script_autonomous_provider(
        client,
        LLMResponse(content="Should not run.", result_data={"execution_status": "completed"}),
    )
    created = _start_autonomous_run(client)
    queued = client.get("/api/agents/queue").json()[0]

    cancelled = client.post(
        f"/api/agents/autonomous/runs/{created['runId']}/cancel",
        json={"reviewer": "api-test", "reason": "cancel before worker starts"},
    )
    outcome = client.app.state.container.autonomous_adapter.run_turn_from_envelope(dict(queued["payload"]))

    assert cancelled.status_code == 200
    assert cancelled.json()["run"]["status"] == "cancelled"
    assert outcome.status == "cancelled"
    assert outcome.metadata["interrupted_before_start"] is True
    assert provider.captured_requests == []

    run_detail = client.get(f"/api/agents/autonomous/runs/{created['runId']}").json()
    assert run_detail["run"]["status"] == "cancelled"
    assert run_detail["turns"] == []


def test_autonomous_run_cancel_interrupts_live_engine_and_preserves_cancelled_status(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "cancel-live-run")
    _script_autonomous_provider(
        client,
        LLMResponse(
            tool_calls=[ToolCall(id="slow-1", name="slow.wait", arguments={"seconds": 1})],
            finish_reason="tool_calls",
        ),
        LLMResponse(content="Fresh run completed.", result_data={"execution_status": "completed"}),
    )

    def _slow_wait(arguments: dict[str, object]) -> dict[str, object]:
        for _ in range(6):
            time.sleep(0.03)
        return {"done": True, "seconds": arguments.get("seconds")}

    client.app.state.container.tool_registry.register(
        ToolDefinition(
            name="slow.wait",
            description="Wait long enough for API cancellation.",
            parameters={"type": "object", "additionalProperties": True},
            handler=_slow_wait,
            category="core",
            external_target=False,
        )
    )
    _force_start_workspace(client)
    created = _start_autonomous_run(client)
    run_id = created["runId"]
    adapter = client.app.state.container.autonomous_adapter
    response_box: dict[str, dict] = {}

    worker = threading.Thread(target=lambda: response_box.setdefault("process_next", client.post("/api/agents/task-queue/process-next").json()), daemon=True)
    worker.start()
    deadline = time.time() + 3
    while time.time() < deadline:
        active = adapter.active_turns.get(run_id)
        if active is not None and active.engine is not None:
            break
        time.sleep(0.02)
    assert run_id in adapter.active_turns
    while time.time() < deadline:
        events = client.get(f"/api/agents/autonomous/runs/{run_id}").json()["events"]
        if any(event["event_type"] == "tool_event" for event in events):
            break
        time.sleep(0.02)

    cancelled = client.post(
        f"/api/agents/autonomous/runs/{run_id}/cancel",
        json={"reviewer": "api-test", "reason": "operator cancelled live run"},
    )
    worker.join(timeout=5)

    assert cancelled.status_code == 200
    assert response_box["process_next"]["status"] == "interrupted"
    assert cancelled.json()["run"]["status"] == "cancelled"
    assert run_id not in adapter.active_turns
    run_detail = client.get(f"/api/agents/autonomous/runs/{run_id}").json()
    assert run_detail["run"]["status"] == "cancelled"
    assert run_detail["turns"][0]["status"] == "cancelled"
    assert {event["event_type"] for event in run_detail["events"]} >= {"tool_event", "turn_interrupted"}

    next_run = _start_autonomous_run(client, title="Next after live cancel", instruction="Run after cancellation.")
    processed = client.post("/api/agents/task-queue/process-next")
    assert processed.status_code == 200
    assert processed.json()["status"] == "processed"
    next_detail = client.get(f"/api/agents/autonomous/runs/{next_run['runId']}").json()
    assert next_detail["run"]["status"] == "idle"
    assert {event["event_type"] for event in next_detail["events"]} >= {"turn_completed"}
    assert "turn_interrupted" not in {event["event_type"] for event in next_detail["events"]}


def test_autonomous_wait_human_resume_resolves_gate_and_requeues_run(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "resume-run")
    _script_autonomous_provider(
        client,
        LLMResponse(
            content="Need approval before continuing.",
            result_data={"execution_status": "waiting_human"},
        ),
    )
    _force_start_workspace(client)
    created = _start_autonomous_run(client)

    processed = client.post("/api/agents/task-queue/process-next")
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


def test_autonomous_resume_with_message_reuses_failed_run_and_injects_pending_input(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "autonomous-resume-message")
    created = _start_autonomous_run(client, instruction="Review candidates and stop before external action.")
    run_id = created["runId"]

    with client.app.state.session_factory() as session:
        run = session.scalars(select(AgentRun).where(AgentRun.run_id == run_id)).one()
        first_task_id = run.queue_task_id
        run.status = "failed"
        run.finished_at = utcnow()
        run.last_error = "provider unavailable"
        session.commit()
        assert session.scalars(select(AgentRun).where(AgentRun.agent_kind == "autonomous")).all() == [run]

    resumed = client.post(
        f"/api/agents/autonomous/runs/{run_id}/resume",
        json={"reviewer": "api-test", "reason": "composer continue", "message": "继续", "priority": "next"},
    )

    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["run"]["runId"] == run_id
    assert resumed.json()["run"]["status"] == "queued"
    with client.app.state.session_factory() as session:
        runs = session.scalars(select(AgentRun).where(AgentRun.agent_kind == "autonomous")).all()
        assert len(runs) == 1
        run = runs[0]
        assert run.finished_at is None
        assert run.queue_task_id == first_task_id
        assert run.wakeup_state["resume_message"] == "继续"
        task = session.scalars(select(TaskQueueItem).where(TaskQueueItem.id == resumed.json()["task_id"])).one()
        assert task.id == first_task_id
        assert task.status == "pending"
        assert task.payload["trigger_type"] == "resume"
        assert task.payload["pending_input"] == [
            {"input_id": None, "priority": "next", "queued_by": "api-test", "message": "继续"}
        ]
        assert task.payload["world_snapshot"]["pending_input"] == task.payload["pending_input"]
    conversation = client.get("/api/agents/autonomous/conversations/autonomous-primary")
    assert conversation.status_code == 200
    messages = conversation.json()["messages"]
    run_inputs = [message for message in messages if message.get("metadata", {}).get("message_type") == "run_input"]
    assert len(run_inputs) == 1
    resumed_input = next(
        message
        for message in messages
        if message.get("metadata", {}).get("traceKind") == "user_message"
        and message["content"] == "继续"
    )
    assert resumed_input["role"] == "user"
    assert resumed_input["kind"] == "message"


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
    _force_start_workspace(client)
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

    processed = client.post("/api/agents/task-queue/process-next")

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

    processed_after_resume = client.post("/api/agents/task-queue/process-next")

    assert processed_after_resume.status_code == 200
    assert processed_after_resume.json()["status"] == "processed"
    run_detail = client.get(f"/api/agents/autonomous/runs/{created['runId']}").json()
    assert run_detail["run"]["status"] == "idle"
    assert run_detail["turns"][-1]["turn_metadata"]["final_output"] == "External action completed."
    assert provider.captured_requests[1].turn_id == provider.captured_requests[0].turn_id
    assert provider.captured_requests[1].messages[-1].role == "tool"
    assert "hello" in str(provider.captured_requests[1].messages[-1].content)


def test_autonomous_permission_resume_preserves_same_response_read_tool_output(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "durable-permission-sibling-tools")
    provider = _script_autonomous_provider(
        client,
        LLMResponse(
            tool_calls=[
                ToolCall(id="call-list-jds", name="list_job_descriptions", arguments={"limit": 10}),
                ToolCall(id="call-read-memory", name="read_memory", arguments={"query": "zhipin recruiting"}),
            ],
            finish_reason="tool_calls",
        ),
        LLMResponse(
            content="Read-only context and JD list are available.",
            result_data={"status": "pass", "execution_status": "completed"},
        ),
    )
    _force_start_workspace(client)
    created = _start_autonomous_run(
        client,
        instruction="Read local JD list and memory before continuing.",
        constraints={
            "tool_approval_policy": {
                "defaultMode": "approval",
                "overrides": {"read_memory": "auto"},
            }
        },
    )

    processed = client.post("/api/agents/task-queue/process-next")

    assert processed.status_code == 200
    assert processed.json()["status"] == "processed"
    with client.app.state.session_factory() as session:
        run = session.scalars(select(AgentRun).where(AgentRun.run_id == created["runId"])).one()
        checkpoint = session.scalars(select(AgentRunCheckpoint).where(AgentRunCheckpoint.run_id == run.id)).one()
        checkpoint_payload = dict(checkpoint.payload or {})
        runtime_checkpoint = dict(checkpoint_payload["runtime_checkpoint"])
        pending_permission = runtime_checkpoint["pending_permissions"][0]
        assert run.status == "waiting_human"
        assert checkpoint_payload["pending_tool_calls"][0]["tool_name"] == "list_job_descriptions"
        assert pending_permission["tool_call"]["name"] == "list_job_descriptions"
        assert pending_permission["remaining_tool_calls"][0]["name"] == "read_memory"
        assert checkpoint_payload["resume_task"]["payload"]["runtime_checkpoint"]["pending_permissions"][0]["remaining_tool_calls"][0]["name"] == "read_memory"

    client.app.state.container.autonomous_adapter.pending_permission_engines.clear()
    resumed = client.post(
        f"/api/agents/autonomous/runs/{created['runId']}/resume",
        json={"reviewer": "api-test", "reason": "approved"},
    )
    assert resumed.status_code == 200

    processed_after_resume = client.post("/api/agents/task-queue/process-next")

    assert processed_after_resume.status_code == 200
    assert processed_after_resume.json()["status"] == "processed"
    assert provider.captured_requests[1].turn_id == provider.captured_requests[0].turn_id
    assert [message.role for message in provider.captured_requests[1].messages[-3:]] == ["assistant", "tool", "tool"]
    assert [message.tool_use_id for message in provider.captured_requests[1].messages[-2:]] == [
        "call-list-jds",
        "call-read-memory",
    ]


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

    blocked = client.post("/api/agents/task-queue/process-next")
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
    assert client.post("/api/agents/task-queue/process-next").json()["status"] == "paused"

    resumed = client.post(
        "/api/agents/autonomous/workspace-control/continue",
        json={"reviewer": "api-test", "reason": "resume queue"},
    )
    assert resumed.status_code == 200
    assert resumed.json()["state"] == "running"
    assert client.post("/api/agents/task-queue/process-next").json()["status"] == "processed"

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


def test_autonomous_workspace_terminate_interrupts_live_turn_and_reports_terminated_run(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, "workspace-terminate-live")
    _script_autonomous_provider(
        client,
        LLMResponse(
            tool_calls=[ToolCall(id="slow-terminate", name="slow.wait", arguments={"seconds": 1})],
            finish_reason="tool_calls",
        ),
        LLMResponse(content="Should not complete after terminate.", result_data={"execution_status": "completed"}),
    )

    def _slow_wait(arguments: dict[str, object]) -> dict[str, object]:
        for _ in range(20):
            time.sleep(0.05)
        return {"done": True}

    client.app.state.container.tool_registry.register(
        ToolDefinition(
            name="slow.wait",
            description="Wait long enough for workspace terminate.",
            parameters={"type": "object", "additionalProperties": True},
            handler=_slow_wait,
            category="core",
            external_target=False,
        )
    )
    _force_start_workspace(client)
    created = _start_autonomous_run(client, title="Terminate active", instruction="Start and wait.")
    run_id = created["runId"]
    adapter = client.app.state.container.autonomous_adapter

    response_box: dict[str, dict] = {}
    worker = threading.Thread(target=lambda: response_box.setdefault("process_next", client.post("/api/agents/task-queue/process-next").json()), daemon=True)
    worker.start()
    deadline = time.time() + 3
    while time.time() < deadline:
        active = adapter.active_turns.get(run_id)
        if active is not None and active.engine is not None:
            break
        time.sleep(0.02)
    assert run_id in adapter.active_turns

    terminated = client.post(
        "/api/agents/autonomous/workspace-control/terminate",
        json={"reviewer": "api-test", "reason": "operator terminate active"},
    )
    assert terminated.status_code == 200
    assert terminated.json()["state"] == "stopped"
    assert run_id in terminated.json()["terminatedRunIds"]
    queue_after_terminate = client.get("/api/agents/queue").json()
    assert any(item["payload"].get("run_id") == run_id and item["status"] == "failed" for item in queue_after_terminate)

    worker.join(timeout=5)
    assert response_box["process_next"]["status"] == "interrupted"
    assert run_id not in adapter.active_turns
    run_detail = client.get(f"/api/agents/autonomous/runs/{run_id}").json()
    assert run_detail["run"]["status"] == "cancelled"
    assert run_detail["turns"][0]["status"] == "cancelled"
    assert "turn_interrupted" in {event["event_type"] for event in run_detail["events"]}
    queue_after_worker = client.get("/api/agents/queue").json()
    assert any(item["payload"].get("run_id") == run_id and item["status"] == "failed" for item in queue_after_worker)
