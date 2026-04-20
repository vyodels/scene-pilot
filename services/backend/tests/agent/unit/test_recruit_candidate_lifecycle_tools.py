from __future__ import annotations

from scene_pilot.core.settings import AppSettings
from scene_pilot.plugins.recruit.toolkit import (
    archive_candidate,
    attach_resume_artifact,
    create_candidate_review_decision,
    create_candidate_sync_record,
    delete_candidate,
    get_candidate_thread,
    get_goal_progress,
    list_candidates,
    record_outbound_message,
    score_candidate,
    upsert_candidate,
    upsert_job_description,
)
from scene_pilot.services.container import AppContainer


def _build_container(tmp_path) -> AppContainer:
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'recruit-candidate-tools.db'}",
        provider_config={},
    )
    return AppContainer.build(settings)


def test_candidate_lifecycle_tools_cover_writeback_scoring_thread_and_progress(tmp_path) -> None:
    container = _build_container(tmp_path)
    for tool_name in (
        "list_candidates",
        "upsert_candidate",
        "score_candidate",
        "record_outbound_message",
        "attach_resume_artifact",
        "create_candidate_review_decision",
        "create_candidate_sync_record",
        "get_candidate_thread",
        "get_goal_progress",
        "request_human_approval",
    ):
        assert tool_name in container.tool_registry.tools

    job = upsert_job_description(
        container.session_factory,
        title="国际销售工程师",
        platform="boss_mock",
        external_id="job-ai-sales-001",
        description="海外销售与售前协同",
    )["job_description"]

    candidate_result = upsert_candidate(
        container.session_factory,
        name="赵云龙",
        platform="boss_mock",
        platform_candidate_id="geek-zhao-yunlong-001",
        job_description_id=job["job_description_id"],
        current_status="discovered",
        source_observation={
            "viewed_count": 12,
            "communicated_count": 3,
            "interested_count": 1,
            "latest_status": "已看过",
        },
        online_resume_text="德国售前经理，英语沟通，海外项目推进。",
    )
    application = candidate_result["application"]
    assert application is not None
    assert application["source_observation"]["viewed_count"] == 12

    listed = list_candidates(
        container.session_factory,
        job_description_id=job["job_description_id"],
    )
    assert len(listed) == 1
    assert listed[0]["applications"][0]["source_observation"]["communicated_count"] == 3

    scoring = score_candidate(
        container.session_factory,
        application_id=application["application_id"],
        score=90,
        decision="advance",
        summary="海外销售与英语沟通经验匹配，建议推进。",
        dimension_scores={"english": 92, "solution_selling": 88},
        evidence_refs=["德国售前经理", "海外项目"],
    )
    assert scoring["application"]["ai_scores"]["overall"] == 90

    record_outbound_message(
        container.session_factory,
        application_id=application["application_id"],
        content="您好，方便补充联系方式和离线简历吗？",
        channel_hint="boss_chat",
        status="draft",
    )

    attach_resume_artifact(
        container.session_factory,
        application_id=application["application_id"],
        file_name="zhao-yunlong-resume.pdf",
        file_path="/tmp/zhao-yunlong-resume.pdf",
        extracted_text="离线简历：德国售前经理，海外销售解决方案经验。",
        contact_snapshot={"phone": "13800138000", "email": "zhao@example.com"},
    )

    create_candidate_review_decision(
        container.session_factory,
        application_id=application["application_id"],
        decision="proceed",
        rationale="评分达标且联系信息已补齐。",
        decision_source="agent",
    )

    create_candidate_sync_record(
        container.session_factory,
        application_id=application["application_id"],
        destination="talent_pool",
        status="synced",
        external_ref="pool-001",
        payload_snapshot={"candidate": "赵云龙"},
    )

    thread = get_candidate_thread(
        container.session_factory,
        application_id=application["application_id"],
    )
    assert len(thread["communicationLogs"]) == 1
    assert len(thread["assessments"]) == 1
    assert len(thread["resumeArtifacts"]) == 1
    assert len(thread["reviewDecisions"]) == 2
    assert len(thread["syncRecords"]) == 1
    assert thread["application"]["resumeAvailable"] is True
    assert thread["stateSnapshot"]["resume_status"] == "received"

    progress = get_goal_progress(
        container.session_factory,
        job_description_id=job["job_description_id"],
    )
    assert progress["candidate_count"] == 1
    assert progress["with_contact"] == 1
    assert progress["with_resume"] == 1
    assert progress["with_ai_score"] == 1


def test_candidate_lifecycle_tools_support_archive_and_delete(tmp_path) -> None:
    container = _build_container(tmp_path)
    job = upsert_job_description(container.session_factory, title="销售工程师")["job_description"]
    candidate_result = upsert_candidate(
        container.session_factory,
        name="邹燕琴",
        platform="boss_mock",
        platform_candidate_id="geek-zou-yanqin-001",
        job_description_id=job["job_description_id"],
        current_status="discovered",
    )
    application = candidate_result["application"]

    archived = archive_candidate(
        container.session_factory,
        application_id=application["application_id"],
        note="当前轮次归档验证",
    )
    assert archived["thread"]["application"]["currentStatus"] == "archived"

    deleted = delete_candidate(
        container.session_factory,
        candidate_person_id=candidate_result["candidate"]["candidate_person_id"],
    )
    assert deleted["deleted"] is True
    assert list_candidates(container.session_factory, job_description_id=job["job_description_id"]) == []
