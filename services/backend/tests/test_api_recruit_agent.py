from fastapi.testclient import TestClient

from scene_pilot.core.app import create_app
from scene_pilot.core.settings import AppSettings
from scene_pilot.repositories import GoalSpecRepository, OperatorInteractionRepository, RecruitAgentProfileRepository
from scene_pilot.services.application_window import make_application_window


def make_client(tmp_path):
    app = create_app(
        AppSettings(
            data_dir=str(tmp_path / "data"),
            database_url=f"sqlite:///{tmp_path / 'recruit-agent.db'}",
        )
    )
    return TestClient(app)


def create_person(client, **payload):
    response = client.post("/api/candidate-persons", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def create_application(
    client,
    *,
    person_id: str,
    platform: str = "site",
    current_status: str = "discovered",
    current_stage_key: str | None = None,
    deepest_milestone: str | None = None,
    state_snapshot: dict | None = None,
    ai_scores: dict | None = None,
    ai_reasoning: str | None = None,
    cooldown_until: str | None = None,
    last_contacted_at: str | None = None,
    job_description_id: str | None = None,
    platform_application_id: str | None = None,
    application_window: str | None = None,
):
    response = client.post(
        "/api/candidate-applications",
        json={
            "person_id": person_id,
            "job_description_id": job_description_id,
            "platform": platform,
            "platform_application_id": platform_application_id,
            "current_status": current_status,
            "current_stage_key": current_stage_key,
            "deepest_milestone": deepest_milestone,
            "state_snapshot": state_snapshot or {},
            "ai_scores": ai_scores or {},
            "ai_reasoning": ai_reasoning,
            "cooldown_until": cooldown_until,
            "last_contacted_at": last_contacted_at,
            "application_window": application_window or make_application_window(person_id, job_description_id or "job-unassigned"),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_subject(
    client,
    *,
    name: str,
    platform: str = "site",
    platform_candidate_id: str | None = None,
    contact_info: dict | None = None,
    current_status: str = "discovered",
    current_stage_key: str | None = None,
    deepest_milestone: str | None = None,
    state_snapshot: dict | None = None,
    ai_scores: dict | None = None,
    ai_reasoning: str | None = None,
    cooldown_until: str | None = None,
    last_contacted_at: str | None = None,
    job_description_id: str | None = None,
    platform_application_id: str | None = None,
    application_window: str | None = None,
):
    person = create_person(
        client,
        name=name,
        platform=platform,
        platform_candidate_id=platform_candidate_id,
        contact_info=contact_info or {},
    )
    application = create_application(
        client,
        person_id=person["id"],
        platform=platform,
        current_status=current_status,
        current_stage_key=current_stage_key,
        deepest_milestone=deepest_milestone,
        state_snapshot=state_snapshot,
        ai_scores=ai_scores,
        ai_reasoning=ai_reasoning,
        cooldown_until=cooldown_until,
        last_contacted_at=last_contacted_at,
        job_description_id=job_description_id,
        platform_application_id=platform_application_id,
        application_window=application_window,
    )
    return {"person": person, "application": application}


def test_recruit_agent_candidate_thread_state_and_memory(tmp_path):
    with make_client(tmp_path) as client:
        subject = create_subject(
            client,
            name="Ada Lovelace",
            platform="boss",
            platform_candidate_id="boss-123",
            contact_info={"location": "上海"},
            current_status="discovered",
            ai_scores={"overall": 91, "decision": "pass"},
            ai_reasoning="工程深度和 owner 意识都比较强。",
        )
        candidate_id = subject["person"]["id"]
        application_id = subject["application"]["id"]

        profile_response = client.get("/api/recruit-agent/profile")
        assert profile_response.status_code == 200
        assert "status_machine" in profile_response.json()["playbook_blueprint"]
        assert "context_policy" in profile_response.json()["prompt_config"]

        memory_response = client.get(f"/api/recruit-agent/candidate-memories/{candidate_id}")
        assert memory_response.status_code == 200
        assert "raw_content" in memory_response.json()
        assert "disclosure" in memory_response.json()

        entry_response = client.post(
            f"/api/candidate-applications/{application_id}/entries",
            json={
                "direction": "outbound",
                "content": "你好，我们想和你进一步沟通这个岗位。",
                "message_type": "text",
                "platform": "boss",
                "metadata": {"drafted_by": "desktop-user"},
            },
        )
        assert entry_response.status_code == 201
        assert entry_response.json()["application_id"] == application_id
        assert entry_response.json()["metadata"]["drafted_by"] == "desktop-user"

        entries_response = client.get(f"/api/candidate-applications/{application_id}/entries")
        assert entries_response.status_code == 200
        assert len(entries_response.json()) == 1
        assert entries_response.json()[0]["application_id"] == application_id

        transition_response = client.post(
            f"/api/candidate-applications/{application_id}/transitions",
            json={
                "to_status": "contact_acquired",
                "stage_key": "contact_acquired",
                "stage_label": "已拿到联系方式",
                "note": "已拿到手机号和微信。",
                "source": "operator",
                "override_reason": "测试中直接跳转到获取联系方式后的状态。",
                "contact_channels": ["phone", "wechat"],
            },
        )
        assert transition_response.status_code == 200
        thread_payload = transition_response.json()
        assert thread_payload["candidate"]["current_status"] == "contact_acquired"
        assert thread_payload["state_snapshot"]["contact_acquired"] is True
        assert "phone" in thread_payload["state_snapshot"]["contact_channels"]
        assert len(thread_payload["status_transitions"]) >= 1
        assert thread_payload["status_transitions"][-1]["is_override"] is True
        assert thread_payload["status_transitions"][-1]["application_id"] == application_id

        assessment_response = client.post(
            f"/api/candidate-applications/{application_id}/assessments",
            json={
                "candidate_id": candidate_id,
                "assessment_type": "manual",
                "stage_key": "resume_received",
                "status": "completed",
                "decision": "pass",
                "score": 88,
                "summary": "人工评估通过，可以继续推进到一面。",
                "evidence_refs": ["resume", "boss_profile"],
                "metadata": {"review_surface": "desktop"},
                "created_by": "desktop-user",
            },
        )
        assert assessment_response.status_code == 201
        assert assessment_response.json()["assessment_type"] == "manual"

        thread_response = client.get(f"/api/candidate-applications/{application_id}/thread")
        assert thread_response.status_code == 200
        assert thread_response.json()["application_id"] == application_id
        assert any(item["assessment_type"] == "manual" for item in thread_response.json()["assessments"])
        assert thread_response.json()["state_snapshot"]["human_assessment_status"] == "completed"
        assert len(thread_response.json()["scorecards"]) >= 1
        assert len(thread_response.json()["review_decisions"]) >= 1
        assert all(item["application_id"] == application_id for item in thread_response.json()["status_transitions"])
        assert all(item["application_id"] == application_id for item in thread_response.json()["communication_logs"])

        assignment_response = client.post(
            f"/api/candidate-applications/{application_id}/assignments",
            json={
                "candidate_id": candidate_id,
                "assignee": "recruit-ops",
                "owner_role": "operator",
                "status": "active",
                "metadata": {"surface": "desktop"},
            },
        )
        assert assignment_response.status_code == 201

        resume_response = client.post(
            f"/api/candidate-applications/{application_id}/resume-artifacts",
            json={
                "candidate_id": candidate_id,
                "source": "boss",
                "artifact_type": "resume",
                "file_name": "ada-lovelace.pdf",
                "metadata": {"collected_by": "desktop-user"},
            },
        )
        assert resume_response.status_code == 201

        sync_response = client.post(
            f"/api/candidate-applications/{application_id}/sync-records",
            json={
                "candidate_id": candidate_id,
                "destination": "talent_pool",
                "status": "pending",
                "payload_snapshot": {"candidate_id": candidate_id},
            },
        )
        assert sync_response.status_code == 201

        refreshed_thread_response = client.get(f"/api/candidate-applications/{application_id}/thread")
        assert refreshed_thread_response.status_code == 200
        assert refreshed_thread_response.json()["application_id"] == application_id
        refreshed_payload = refreshed_thread_response.json()
        assert len(refreshed_payload["assignments"]) == 1
        assert len(refreshed_payload["resume_artifacts"]) == 1
        assert len(refreshed_payload["sync_records"]) == 1
        assert refreshed_payload["state_snapshot"]["resume_status"] == "received"
        assert all(item["application_id"] == application_id for item in refreshed_payload["assignments"])
        assert all(item["application_id"] == application_id for item in refreshed_payload["resume_artifacts"])
        assert all(item["application_id"] == application_id for item in refreshed_payload["sync_records"])


def test_recruit_agent_evolution_artifacts(tmp_path):
    with make_client(tmp_path) as client:
        create_response = client.post(
            "/api/recruit-agent/evolution-artifacts",
            json={
                "artifact_kind": "prompt_patch",
                "title": "Tighten outreach tone",
                "summary": "收紧首轮外联语气。",
                "status": "pending_review",
                "artifact_body": {"before": "热情版", "after": "克制版"},
                "artifact_metadata": {"scope": "candidate_messaging"},
            },
        )
        assert create_response.status_code == 201
        artifact_id = create_response.json()["id"]

        update_response = client.patch(
            f"/api/recruit-agent/evolution-artifacts/{artifact_id}",
            json={"status": "approved", "reviewed_by": "desktop-user"},
        )
        assert update_response.status_code == 200
        assert update_response.json()["status"] == "approved"

        list_response = client.get("/api/recruit-agent/evolution-artifacts")
        assert list_response.status_code == 200
        assert len(list_response.json()) == 1


def test_resume_artifact_contact_snapshot_relinks_application_person(tmp_path):
    with make_client(tmp_path) as client:
        existing_id = create_person(
            client,
            name="Existing Person",
            platform="boss",
            platform_candidate_id="boss-existing-1",
            contact_info={"wechat": "ada_001"},
        )["id"]

        duplicate_subject = create_subject(
            client,
            name="Duplicate Intake",
            platform="boss",
            platform_candidate_id="boss-duplicate-1",
        )
        application_id = duplicate_subject["application"]["id"]

        artifact_response = client.post(
            f"/api/candidate-applications/{application_id}/resume-artifacts",
            json={
                "candidate_id": application_id,
                "source": "boss",
                "artifact_type": "resume",
                "file_name": "duplicate.pdf",
                "contact_snapshot": {"wechat": "ada_001", "phone": "138 0000 0000"},
            },
        )
        assert artifact_response.status_code == 201
        assert artifact_response.json()["person_id"] == existing_id
        assert artifact_response.json()["application_id"] == application_id

        application_response = client.get(f"/api/candidate-applications/{application_id}")
        assert application_response.status_code == 200
        assert application_response.json()["person_id"] == existing_id

        thread_response = client.get(f"/api/candidate-applications/{application_id}/thread")
        assert thread_response.status_code == 200
        assert thread_response.json()["candidate"]["id"] == existing_id
        assert thread_response.json()["candidate"]["contact_info"]["wechat"] == "ada_001"


def test_contact_channels_transition_does_not_merge_application_person(tmp_path):
    with make_client(tmp_path) as client:
        existing_id = create_person(
            client,
            name="Existing Person",
            platform="boss",
            platform_candidate_id="boss-existing-weak",
            contact_info={"wechat": "existing_wechat"},
        )["id"]

        duplicate_subject = create_subject(
            client,
            name="Weak Signal Candidate",
            platform="boss",
            platform_candidate_id="boss-weak-1",
        )
        application_id = duplicate_subject["application"]["id"]

        transition_response = client.post(
            f"/api/candidate-applications/{application_id}/transitions",
            json={
                "to_status": "contact_acquired",
                "stage_key": "contact_acquired",
                "stage_label": "已拿到联系方式",
                "source": "operator",
                "override_reason": "测试弱信号不会触发 merge。",
                "contact_channels": ["phone", "wechat"],
            },
        )
        assert transition_response.status_code == 200

        application_response = client.get(f"/api/candidate-applications/{application_id}")
        assert application_response.status_code == 200
        assert application_response.json()["person_id"] == duplicate_subject["person"]["id"]
        assert application_response.json()["person_id"] != existing_id

        thread_payload = transition_response.json()
        assert thread_payload["state_snapshot"]["contact_channels"] == ["phone", "wechat"]
        assert thread_payload["candidate"]["id"] == duplicate_subject["person"]["id"]


def test_recruit_agent_evolution_artifacts_validate_kind_schema(tmp_path):
    with make_client(tmp_path) as client:
        response = client.post(
            "/api/recruit-agent/evolution-artifacts",
            json={
                "artifact_kind": "skill_draft",
                "title": "Broken skill draft",
                "summary": "缺少必需字段。",
                "status": "pending_review",
                "artifact_body": {"before": "v1"},
                "artifact_metadata": {"scope": "skills"},
            },
        )
        assert response.status_code == 422


def test_recruit_agent_skill_draft_artifact_promotes_skill_idempotently(tmp_path):
    with make_client(tmp_path) as client:
        create_response = client.post(
            "/api/recruit-agent/evolution-artifacts",
            json={
                "artifact_kind": "skill_draft",
                "title": "Outreach skill draft",
                "summary": "沉淀一条更稳的首轮外联策略。",
                "status": "pending_review",
                "artifact_body": {
                    "skill_contract": {
                        "skill_id": "candidate_outreach_runtime",
                        "name": "Candidate Outreach Runtime",
                        "description": "更稳的候选人首轮外联。",
                        "category": "candidate_progression",
                        "platform": "runtime-scene",
                        "bound_to_stage": "candidate_outreach",
                        "strategy": {"instruction": "先确认 owner 证据，再索要简历。"},
                        "execution_hints": {"observed_outcomes": [{"status": "pass"}]},
                        "health_check_config": {"expected_result_status": "pass"},
                        "skill_metadata": {"artifact_origin": "candidate_progression"},
                    },
                    "decision_trace": {
                        "candidate_features": {"currentStatus": "outreach_pending"},
                        "action": [{"kind": "outbound_message"}],
                        "result": {"status": "pass", "success": True},
                    },
                },
                "artifact_metadata": {
                    "promotion_fallback_platform": "runtime-scene",
                    "promotion_fallback_stage": "candidate_outreach",
                },
            },
        )
        assert create_response.status_code == 201
        artifact_id = create_response.json()["id"]

        first_apply = client.patch(
            f"/api/recruit-agent/evolution-artifacts/{artifact_id}",
            json={
                "status": "approved",
                "reviewed_by": "desktop-user",
                "artifact_metadata": {"review_reason": "符合当前流程"},
            },
        )
        assert first_apply.status_code == 200
        first_payload = first_apply.json()
        assert first_payload["status"] == "applied"
        assert first_payload["related_skill_id"]
        promoted_skill = first_payload["artifact_metadata"]["promoted_skill"]
        first_skill_id = promoted_skill["id"]
        first_skill_key = promoted_skill["skill_id"]
        assert promoted_skill["version"] == 1

        skills_response = client.get("/api/skills")
        assert skills_response.status_code == 200
        promoted = next(item for item in skills_response.json() if item["id"] == first_payload["related_skill_id"])
        assert promoted["version"] == 1
        assert promoted["skill_metadata"]["promotion_source"] == "evolution_artifact"
        assert promoted["skill_metadata"]["promotion_source_kind"] == "evolution_artifact"
        assert promoted["skill_metadata"]["promotion_source_id"] == artifact_id

        second_apply = client.patch(
            f"/api/recruit-agent/evolution-artifacts/{artifact_id}",
            json={"status": "approved", "reviewed_by": "desktop-user-2"},
        )
        assert second_apply.status_code == 200
        second_payload = second_apply.json()
        assert second_payload["status"] == "applied"
        assert second_payload["related_skill_id"] == first_payload["related_skill_id"]
        assert second_payload["artifact_metadata"]["promoted_skill"]["version"] == 1
        assert second_payload["artifact_metadata"]["promoted_skill"]["id"] == first_skill_id
        assert second_payload["artifact_metadata"]["promoted_skill"]["skill_id"] == first_skill_key

        refreshed_skills = client.get("/api/skills")
        assert refreshed_skills.status_code == 200
        matching = [item for item in refreshed_skills.json() if item["skill_id"] == first_skill_key]
        assert len(matching) == 1
        promoted = matching[0]
        assert promoted["version"] == 1
        assert promoted["id"] == first_skill_id


def test_recruit_agent_context_policy_profile_persistence(tmp_path):
    with make_client(tmp_path) as client:
        update_response = client.patch(
            "/api/recruit-agent/profile",
            json={
                "prompt_config": {
                    "context_policy": {
                        "global": {
                            "token_budget_default": 3072,
                            "llm_rerank_enabled": True,
                            "llm_rerank_top_k": 4,
                            "llm_rerank_max_boost": 6,
                            "drop_order": ["global_memory", "platform_context"],
                        },
                        "lanes": {
                            "candidate": {
                                "must_include": ["task_brief", "candidate_progress", "recent_messages"],
                                "default_weights": {
                                    "recent_messages": 1.4,
                                    "candidate_memory": 1.3,
                                },
                            }
                        },
                        "run_type_overrides": {
                            "candidate_outreach": {
                                "prefer": ["recent_messages", "candidate_memory"],
                                "suppress": ["global_memory"],
                            }
                        },
                    }
                }
            },
        )
        assert update_response.status_code == 200
        payload = update_response.json()
        context_policy = payload["prompt_config"]["context_policy"]
        assert context_policy["global"]["token_budget_default"] == 3072
        assert context_policy["global"]["llm_rerank_enabled"] is True
        assert "recent_messages" in context_policy["lanes"]["candidate"]["must_include"]
        assert context_policy["run_type_overrides"]["candidate_outreach"]["prefer"][0] == "recent_messages"

        profile_response = client.get("/api/recruit-agent/profile")
        assert profile_response.status_code == 200
        persisted = profile_response.json()["prompt_config"]["context_policy"]
        assert persisted["global"]["llm_rerank_top_k"] == 4
        assert persisted["lanes"]["candidate"]["default_weights"]["candidate_memory"] == 1.3


def test_recruit_agent_goal_creation_and_operator_interaction_resolution(tmp_path):
    app = create_app(
        AppSettings(
            data_dir=str(tmp_path / "data"),
            database_url=f"sqlite:///{tmp_path / 'recruit-agent.db'}",
        )
    )
    with TestClient(app) as client:
        goal_response = client.post(
            "/api/recruit-agent/goals",
            json={
                "title": "筛选 Go 后端候选人",
                "goal_text": "先探索 Boss 上是否有更高效的筛选入口，再推进 3 个高匹配候选人到初次沟通。",
                "goal_kind": "recruiting",
                "constraints": {"platform": "boss"},
                "success_criteria": {"target_candidates": 3},
            },
        )
        assert goal_response.status_code == 201
        goal_payload = goal_response.json()
        assert goal_payload["status"] == "queued"
        assert goal_payload["title"] == "筛选 Go 后端候选人"

        goals_response = client.get("/api/recruit-agent/goals")
        assert goals_response.status_code == 200
        assert len(goals_response.json()) == 1

        runtime_session = client.get("/api/recruit-agent/runtime/session")
        assert runtime_session.status_code == 200
        session_id = runtime_session.json()["id"]

        with app.state.container.session_factory() as session:
            profile = RecruitAgentProfileRepository(session).primary()
            assert profile is not None
            goal = GoalSpecRepository(session).list_recent(agent_profile_id=profile.id, limit=1, offset=0)[0]
            interaction = OperatorInteractionRepository(session).create(
                {
                    "session_id": session_id,
                    "goal_spec_id": goal.id,
                    "lane": "agent",
                    "interaction_type": "confirm",
                    "status": "pending",
                    "title": "需要确认新的搜索路径",
                    "agent_prompt": "Boss 关键词搜索效果一般，是否改用平台筛选器继续？",
                    "suggested_options": [
                        {"id": "confirm", "label": "改用筛选器", "action": "confirm"},
                        {"id": "retry", "label": "原路径重试", "action": "retry"},
                    ],
                    "scope": "run_only",
                    "interaction_metadata": {"source": "test"},
                }
            )

        interactions_response = client.get("/api/recruit-agent/runtime/operator-interactions")
        assert interactions_response.status_code == 200
        assert len(interactions_response.json()) == 1

        resolve_response = client.post(
            f"/api/recruit-agent/runtime/operator-interactions/{interaction.id}/resolve",
            json={
                "action": "confirm",
                "comment": "优先看最近活跃候选人。",
                "operator": "desktop-user",
            },
        )
        assert resolve_response.status_code == 200
        resolved_payload = resolve_response.json()
        assert resolved_payload["status"] == "resolved"
        assert resolved_payload["operator_response"]["action"] == "confirm"
        assert "记录" in (resolved_payload["effect_summary"] or "")


def test_state_machine_version_history_endpoints(tmp_path):
    with make_client(tmp_path) as client:
        current_response = client.get("/api/state-machine")
        assert current_response.status_code == 200
        current_payload = current_response.json()
        current_version = current_payload["version"]

        list_response = client.get("/api/state-machine/versions")
        assert list_response.status_code == 200
        versions = list_response.json()
        assert len(versions) >= 1
        assert versions[0]["version"] == current_version

        updated_nodes = current_payload["nodes"]
        updated_nodes[0]["label"] = "已发现·待评估（测试版）"

        update_response = client.put(
            "/api/state-machine",
            json={
                "updated_by": "desktop-user",
                "change_summary": "测试版本历史",
                "nodes": updated_nodes,
                "transitions": current_payload["transitions"],
                "global_transitions": current_payload.get("globalTransitions", current_payload["global_transitions"]),
                "version_metadata": {"source": "pytest"},
            },
        )
        assert update_response.status_code == 200
        assert update_response.json()["version"] == current_version + 1

        latest_versions_response = client.get("/api/state-machine/versions")
        assert latest_versions_response.status_code == 200
        latest_versions = latest_versions_response.json()
        assert latest_versions[0]["version"] == current_version + 1
        assert latest_versions[0]["change_summary"] == "测试版本历史"

        detail_response = client.get(f"/api/state-machine/versions/{current_version + 1}")
        assert detail_response.status_code == 200
        assert detail_response.json()["nodes"][0]["label"] == "已发现·待评估（测试版）"

        missing_response = client.get("/api/state-machine/versions/999")
        assert missing_response.status_code == 404


def test_state_machine_criteria_suggestions_endpoint(tmp_path):
    with make_client(tmp_path) as client:
        current_skill = client.post(
            "/api/skills",
            json={
                "skill_id": "resume_scoring_v1",
                "name": "Resume Scoring V1",
                "status": "active",
                "platform": "runtime-scene",
                "bound_to_stage": "offline_scoring",
                "strategy": {"instruction": "Use the current resume scoring rubric."},
                "execution_hints": {"observed_outcomes": [{"status": "pass"}]},
                "health_check_config": {"expected_result_status": "pass"},
                "last_health_status": "degraded",
            },
        )
        assert current_skill.status_code == 201
        alternative_skill = client.post(
            "/api/skills",
            json={
                "skill_id": "resume_scoring_v2",
                "name": "Resume Scoring V2",
                "version": 2,
                "status": "active",
                "platform": "runtime-scene",
                "bound_to_stage": "offline_scoring",
                "strategy": {"instruction": "Use the revised resume scoring rubric."},
                "execution_hints": {"observed_outcomes": [{"status": "pass"}, {"status": "pass"}]},
                "health_check_config": {"expected_result_status": "pass"},
                "last_health_status": "healthy",
            },
        )
        assert alternative_skill.status_code == 201
        lower_ranked_alternative_skill = client.post(
            "/api/skills",
            json={
                "skill_id": "resume_scoring_v3",
                "name": "Resume Scoring V3",
                "version": 3,
                "status": "active",
                "platform": "runtime-scene",
                "bound_to_stage": "offline_scoring",
                "strategy": {"instruction": "Use the experimental resume scoring rubric."},
                "execution_hints": {"observed_outcomes": [{"status": "pass"}]},
                "health_check_config": {"expected_result_status": "pass"},
                "last_health_status": "warning",
            },
        )
        assert lower_ranked_alternative_skill.status_code == 201

        for index, payload in enumerate(
            (
                {"source": "agent", "to_status": "offline_score_passed", "note": "Agent passed candidate."},
                {"source": "agent", "to_status": "offline_score_passed", "note": "Agent passed another candidate."},
                {
                    "source": "operator",
                    "to_status": "offline_score_rejected",
                    "override_reason": "人工认为线下简历没有达到要求。",
                    "note": "Recruiter rejected after review.",
                },
                {
                    "source": "operator",
                    "to_status": "offline_score_rejected",
                    "override_reason": "人工补充判断后改为不通过。",
                    "note": "Recruiter rejected second candidate.",
                },
            ),
            start=1,
        ):
            candidate_response = client.post(
                "/api/candidate-applications",
                json={
                    "person_id": create_person(
                        client,
                        name=f"Criteria Candidate {index}",
                        platform="boss",
                    )["id"],
                    "platform": "boss",
                    "current_status": "offline_scoring",
                    "current_stage_key": "offline_scoring",
                    "application_window": f"criteria-{index}",
                },
            )
            assert candidate_response.status_code == 201
            candidate_id = candidate_response.json()["id"]
            transition_response = client.post(f"/api/candidate-applications/{candidate_id}/transitions", json=payload)
            assert transition_response.status_code == 200

        suggestions_response = client.get("/api/state-machine/criteria-suggestions")
        assert suggestions_response.status_code == 200
        reports = suggestions_response.json()
        offline_report = next(item for item in reports if item["node_id"] == "offline_scoring")
        assert offline_report["metrics"]["sample_size"] == 4
        assert offline_report["metrics"]["recruiter_override_count"] == 2
        assert offline_report["current_skill_id"] == "resume_scoring_v1"
        suggestion_kinds = {item["kind"] for item in offline_report["suggestions"]}
        assert "adjust_threshold" in suggestion_kinds
        assert "switch_skill" in suggestion_kinds

        threshold_suggestion = next(item for item in offline_report["suggestions"] if item["kind"] == "adjust_threshold")
        assert threshold_suggestion["proposed_criteria_ref"]["passThreshold"] == 75

        skill_suggestion = next(item for item in offline_report["suggestions"] if item["kind"] == "switch_skill")
        assert skill_suggestion["proposed_criteria_ref"]["skillId"] == "resume_scoring_v2"
        assert skill_suggestion["suggested_skill_id"] == "resume_scoring_v2"
        assert "health=healthy" in skill_suggestion["rationale"]
