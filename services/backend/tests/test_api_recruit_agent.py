from fastapi.testclient import TestClient

from scene_pilot.core.app import create_app
from scene_pilot.core.settings import AppSettings
from scene_pilot.repositories import GoalSpecRepository, OperatorInteractionRepository, RecruitAgentProfileRepository


def make_client(tmp_path):
    app = create_app(
        AppSettings(
            data_dir=str(tmp_path / "data"),
            database_url=f"sqlite:///{tmp_path / 'recruit-agent.db'}",
        )
    )
    return TestClient(app)


def test_recruit_agent_candidate_thread_state_and_memory(tmp_path):
    with make_client(tmp_path) as client:
        candidate_response = client.post(
            "/api/candidates",
            json={
                "name": "Ada Lovelace",
                "platform": "boss",
                "platform_candidate_id": "boss-123",
                "status": "discovered",
                "jd_id": "jd-frontend",
                "contact_info": {"location": "上海"},
                "ai_scores": {"overall": 91, "decision": "pass"},
                "ai_reasoning": "工程深度和 owner 意识都比较强。",
            },
        )
        assert candidate_response.status_code == 201
        candidate_id = candidate_response.json()["id"]

        profile_response = client.get("/api/recruit-agent/profile")
        assert profile_response.status_code == 200
        assert "status_machine" in profile_response.json()["workflow_definition"]
        assert "context_policy" in profile_response.json()["prompt_config"]

        memory_response = client.get(f"/api/recruit-agent/candidate-memories/{candidate_id}")
        assert memory_response.status_code == 200
        assert "raw_content" in memory_response.json()
        assert "disclosure" in memory_response.json()

        entry_response = client.post(
            f"/api/recruit-agent/candidate-threads/{candidate_id}/entries",
            json={
                "direction": "outbound",
                "content": "你好，我们想和你进一步沟通这个岗位。",
                "message_type": "text",
                "platform": "boss",
                "metadata": {"drafted_by": "desktop-user"},
            },
        )
        assert entry_response.status_code == 201
        assert entry_response.json()["metadata"]["drafted_by"] == "desktop-user"

        transition_response = client.post(
            f"/api/recruit-agent/candidates/{candidate_id}/transition",
            json={
                "to_status": "contact_acquired",
                "stage_key": "contact_acquired",
                "stage_label": "已拿到联系方式",
                "note": "已拿到手机号和微信。",
                "source": "operator",
                "contact_channels": ["phone", "wechat"],
            },
        )
        assert transition_response.status_code == 200
        thread_payload = transition_response.json()
        assert thread_payload["candidate"]["status"] == "contact_acquired"
        assert thread_payload["state_snapshot"]["contact_acquired"] is True
        assert "phone" in thread_payload["state_snapshot"]["contact_channels"]
        assert len(thread_payload["stage_events"]) >= 1

        assessment_response = client.post(
            f"/api/recruit-agent/candidates/{candidate_id}/assessments",
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

        thread_response = client.get(f"/api/recruit-agent/candidate-threads/{candidate_id}")
        assert thread_response.status_code == 200
        assert any(item["assessment_type"] == "manual" for item in thread_response.json()["assessments"])
        assert thread_response.json()["state_snapshot"]["human_assessment_status"] == "completed"
        assert len(thread_response.json()["scorecards"]) >= 1
        assert len(thread_response.json()["review_decisions"]) >= 1

        assignment_response = client.post(
            f"/api/recruit-agent/candidates/{candidate_id}/assignments",
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
            f"/api/recruit-agent/candidates/{candidate_id}/resume-artifacts",
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
            f"/api/recruit-agent/candidates/{candidate_id}/sync-records",
            json={
                "candidate_id": candidate_id,
                "destination": "talent_pool",
                "status": "pending",
                "payload_snapshot": {"candidate_id": candidate_id},
            },
        )
        assert sync_response.status_code == 201

        refreshed_thread_response = client.get(f"/api/recruit-agent/candidate-threads/{candidate_id}")
        assert refreshed_thread_response.status_code == 200
        refreshed_payload = refreshed_thread_response.json()
        assert len(refreshed_payload["assignments"]) == 1
        assert len(refreshed_payload["resume_artifacts"]) == 1
        assert len(refreshed_payload["sync_records"]) == 1
        assert refreshed_payload["state_snapshot"]["resume_status"] == "received"


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
                            "initiate_communication": {
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
        assert context_policy["run_type_overrides"]["initiate_communication"]["prefer"][0] == "recent_messages"

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
