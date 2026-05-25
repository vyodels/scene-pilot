from __future__ import annotations

from recruit_station.services.jd_sync_contract import jd_sync_scene_output_contract, normalize_jd_sync_scene_result
from recruit_station.services.jd_sync_state import initial_jd_sync_state, reduce_jd_sync_scene_result


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
