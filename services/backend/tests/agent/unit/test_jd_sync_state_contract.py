from __future__ import annotations

from recruit_station.services.jd_sync_contract import jd_sync_scene_output_contract, normalize_jd_sync_scene_result
from recruit_station.models.domain import AgentRun
from recruit_station.services.jd_sync_state import initial_jd_sync_state, reduce_agent_run_jd_sync_state, reduce_jd_sync_scene_result


def test_jd_sync_scene_output_normalizer_fills_partial_contract_fields() -> None:
    contract = jd_sync_scene_output_contract()

    result = normalize_jd_sync_scene_result(
        {
            "status": "in_progress",
            "summary": "职位管理列表已打开，仍需进入详情。",
        },
        contract,
    )

    assert result["status"] == "in_progress"
    assert result["scene_status"] == "in_progress"
    for field in (
        "observed_jobs",
        "pending_jobs",
        "completed_job_details",
        "inactive_or_closed_jobs",
        "action_candidates",
        "terminal_blockers",
        "policy_violations",
        "evidence_refs",
        "writeback_candidates",
        "blockers",
        "limitations",
        "evidence",
    ):
        assert result[field] == []
    assert result["recovery"] == {}


def test_jd_sync_state_reducer_retains_observed_pending_and_completed_jobs() -> None:
    state = initial_jd_sync_state(target={"domain": "zhipin.com"})

    state = reduce_jd_sync_scene_result(
        state,
        {
            "result_data": {
                "status": "partial",
                "observed_jobs": [
                    {"external_id": "boss-jd-1", "title": "产品实习生"},
                    {"external_id": "boss-jd-2", "title": "销售工程师"},
                ],
                "pending_jobs": [
                    {"external_id": "boss-jd-1", "title": "产品实习生"},
                    {"external_id": "boss-jd-2", "title": "销售工程师"},
                ],
                "recovery": {"selected_tab": {"tabId": 9, "url": "https://www.zhipin.com/web/chat/job/list"}},
                "evidence_refs": ["snapshot-1"],
            }
        },
    )
    state = reduce_jd_sync_scene_result(
        state,
        {
            "result_data": {
                "status": "partial",
                "completed_job_details": [
                    {
                        "external_id": "boss-jd-1",
                        "title": "产品实习生",
                        "description": "负责产品需求分析和跨团队协作。",
                        "requirements": "要求本科以上，具备产品实习经验。",
                    }
                ],
                "evidence_refs": ["detail-1"],
            }
        },
    )

    assert state["selected_tab"]["tabId"] == 9
    assert sorted(state["jobs_by_key"]) == ["boss-jd-1", "boss-jd-2"]
    assert state["completed_job_keys"] == ["boss-jd-1"]
    assert state["pending_job_keys"] == ["boss-jd-2"]
    assert state["evidence_refs"] == ["snapshot-1", "detail-1"]


def test_jd_sync_normalizer_does_not_complete_with_pending_jobs() -> None:
    result = normalize_jd_sync_scene_result(
        {
            "status": "completed",
            "observed_jobs": [{"external_id": "boss-jd-1"}, {"external_id": "boss-jd-2"}],
            "completed_job_details": [{"external_id": "boss-jd-1", "description": "负责客户拓展。", "requirements": "要求销售经验。"}],
            "pending_jobs": [{"external_id": "boss-jd-2"}],
        },
        {"contract_kind": "jd_sync"},
    )

    assert result["status"] == "partial"
    assert result["scene_status"] == "partial"
    assert result["reported_status"] == "completed"


def test_jd_sync_normalizer_downgrades_recoverable_blocked_status() -> None:
    result = normalize_jd_sync_scene_result(
        {
            "status": "blocked",
            "pending_jobs": [{"external_id": "boss-jd-2"}],
            "recovery": {"next_action": {"tool_name": "hid_action"}},
            "terminal_blockers": [],
        },
        {"contract_kind": "jd_sync"},
    )

    assert result["status"] == "in_progress"
    assert result["scene_status"] == "in_progress"
    assert result["reported_status"] == "blocked"


def test_jd_sync_normalizer_and_reducer_drop_boss_navigation_entries() -> None:
    result = normalize_jd_sync_scene_result(
        {
            "status": "blocked",
            "observed_jobs": [
                {
                    "title": "职位管理",
                    "job_key": "https://www.zhipin.com/web/chat/job/list?ka=menu-manager-job",
                    "source_url": "https://www.zhipin.com/web/chat/job/list?ka=menu-manager-job",
                }
            ],
            "pending_jobs": [
                {
                    "title": "职位管理",
                    "job_key": "https://www.zhipin.com/web/chat/job/list?ka=menu-manager-job",
                }
            ],
            "action_candidates": [
                {
                    "kind": "open_job_detail_or_safe_edit",
                    "tool_name": "hid_action",
                    "label": "职位管理",
                    "ref": "e14",
                    "source_url": "https://www.zhipin.com/web/chat/job/list?ka=menu-manager-job",
                }
            ],
            "terminal_blockers": [{"kind": "ambiguous_click_target"}],
        },
        {"contract_kind": "jd_sync"},
    )

    assert result["observed_jobs"] == []
    assert result["pending_jobs"] == []
    assert result["action_candidates"] == []
    assert result["contract_normalization"]["filtered_non_jd_items"] == {
        "observed_jobs": 1,
        "pending_jobs": 1,
        "action_candidates": 1,
    }

    state = reduce_jd_sync_scene_result(initial_jd_sync_state(), {"result_data": result})
    assert state["jobs_by_key"] == {}
    assert state["pending_job_keys"] == []


def test_jd_sync_normalizer_filters_forbidden_boss_and_candidate_actions_but_keeps_real_jobs() -> None:
    result = normalize_jd_sync_scene_result(
        {
            "status": "in_progress",
            "observed_jobs": [
                {
                    "external_id": "boss-product",
                    "title": "产品实习生",
                    "raw_text": "产品实习生 北京 2-4K 开放中 看过我 沟通过 感兴趣",
                },
                {"external_id": "candidate-card", "title": "候选人 张三 本科", "raw_text": "候选人 张三 打招呼"},
            ],
            "pending_jobs": [{"external_id": "boss-product", "title": "产品实习生"}],
            "action_candidates": [
                {"label": "编辑", "ref": "edit-product", "bound_ref": "boss-product"},
                {"label": "查看详情", "ref": "detail-product", "bound_ref": "boss-product"},
                {"label": "招聘规范", "ref": "top-rules"},
                {"label": "+", "kind": "group_action", "ref": "chat-plus"},
                {"label": "打招呼", "ref": "greet"},
                {"label": "关闭", "ref": "close-product"},
                {"label": "更多", "ref": "more-product"},
            ],
            "writeback_candidates": [
                {
                    "title": "产品实习生",
                    "description": "负责产品需求分析和跨团队协作。",
                    "requirements": "要求本科以上，具备产品实习经验。",
                },
                {"title": "候选人 张三", "description": "候选人简历内容", "requirements": "打招呼"},
            ],
        },
        {"contract_kind": "jd_sync"},
    )

    assert [item["title"] for item in result["observed_jobs"]] == ["产品实习生"]
    assert [item["label"] for item in result["action_candidates"]] == ["编辑", "查看详情"]
    assert [item["title"] for item in result["writeback_candidates"]] == ["产品实习生"]


def test_jd_sync_run_state_reducer_reads_projected_scene_content_business_result() -> None:
    run = AgentRun(agent_kind="jd_sync", runtime_metadata={})

    state = reduce_agent_run_jd_sync_state(
        run,
        tool_results=[
            {
                "tool_name": "delegate_scene_context",
                "content": {
                    "status": "incomplete",
                    "business_result": {
                        "status": "applied",
                        "observed_jobs": [{"external_id": "e23", "title": "产品实习生"}],
                        "pending_jobs": [{"external_id": "e23", "title": "产品实习生"}],
                        "action_candidates": [
                            {
                                "kind": "open_job_detail_or_safe_edit",
                                "tool_name": "hid_action",
                                "ref": "e23",
                                "label": "产品实习生",
                            }
                        ],
                        "evidence_refs": ["episode:scene-1"],
                        "jd_sync_evidence_extraction": {"status": "applied"},
                    },
                },
            }
        ],
    )

    assert state["jobs_by_key"]["e23"]["title"] == "产品实习生"
    assert state["pending_job_keys"] == ["e23"]
    assert state["evidence_refs"] == ["episode:scene-1"]
    assert state["action_candidates"][0]["ref"] == "e23"
    assert state["last_safe_action_candidates"][0]["ref"] == "e23"
    assert state["pending_actions_by_job_key"]["e23"][0]["label"] == "产品实习生"
    assert run.runtime_metadata["jd_sync_state"] == state
