from __future__ import annotations

from recruit_agent.product_adapters.business_state_projection import project_runtime_business_state


def test_sync_jd_blocked_summary_uses_run_fields() -> None:
    projected = project_runtime_business_state(
        run_kind="sync_jd_incremental",
        run_title="同步 JD（增量）",
        content={
            "status": "blocked",
            "next_step": "请先在浏览器中打开并切换到招聘平台的职位列表或职位详情页面，然后继续同步。",
        },
    )

    assert projected["action_label"] == "同步 JD（增量）"
    assert projected["status"] == "blocked"
    assert projected["summary"] == "同步 JD（增量）：当前受阻，等待继续执行条件满足。"


def test_candidate_discovery_waiting_human_summary_uses_status() -> None:
    projected = project_runtime_business_state(
        run_title="发现候选人",
        content={
            "run_kind": "candidate_discovery",
            "status": "waiting_human",
            "next_step": "需要先完成登录验证后再继续。",
        },
    )

    assert projected["action_label"] == "发现候选人"
    assert projected["summary"] == "发现候选人：等待人工处理后继续。"


def test_sync_jd_success_summary_uses_structured_counts() -> None:
    projected = project_runtime_business_state(
        run_title="同步 JD（增量）",
        content={
            "run_kind": "sync_jd_incremental",
            "status": "completed",
            "created": 2,
            "updated": 1,
            "skipped": 3,
        },
    )

    assert projected["summary"] == "同步 JD（增量）：新增 2，更新 1，跳过 3。"
