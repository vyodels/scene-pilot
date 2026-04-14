from fastapi.testclient import TestClient

from recruit_agent.core.app import create_app
from recruit_agent.core.settings import AppSettings


def make_client(tmp_path):
    app = create_app(
        AppSettings(
            data_dir=str(tmp_path / "data"),
            database_url=f"sqlite:///{tmp_path / 'recruit-agent.db'}",
        )
    )
    return TestClient(app)


def test_skill_health_check_and_learning_drafts(tmp_path):
    with make_client(tmp_path) as client:
        skill_response = client.post(
            "/api/skills",
            json={
                "skill_id": "resume-health",
                "name": "Resume Health",
                "version": 1,
                "status": "approved",
                "platform": "boss",
                "strategy": {"prompt": "screen"},
                "health_check_config": {"required_strategy_keys": ["prompt", "rubric"]},
            },
        )
        assert skill_response.status_code == 201
        skill_id = skill_response.json()["id"]

        health_response = client.post(
            f"/api/skills/{skill_id}/health-check",
            json={"observed_result": {"status": "pass", "overall": 88}},
        )
        assert health_response.status_code == 200
        assert health_response.json()["health"] == "warning"
        assert "missing_strategy_key:rubric" in health_response.json()["issues"]

        learning_response = client.post(
            "/api/skills/learnings",
            json={
                "content": "Need a better rubric for frontend architecture signals.",
                "tags": ["screening", "boss"],
                "source_task_id": "task-123",
            },
        )
        assert learning_response.status_code == 201
        learning_id = learning_response.json()["id"]
        assert learning_response.json()["is_active"] is True

        list_response = client.get("/api/skills/learnings")
        assert list_response.status_code == 200
        assert any(item["id"] == learning_id for item in list_response.json())

        deactivate_response = client.post(f"/api/skills/learnings/{learning_id}/deactivate")
        assert deactivate_response.status_code == 200
        assert deactivate_response.json()["is_active"] is False

        activate_response = client.post(f"/api/skills/learnings/{learning_id}/activate")
        assert activate_response.status_code == 200
        assert activate_response.json()["is_active"] is True

        dashboard_response = client.get("/api/dashboard")
        assert dashboard_response.status_code == 200
        alert_labels = [item["label"] for item in dashboard_response.json()["alerts"]]
        assert "Learning draft available" in alert_labels


def test_skill_health_check_sweep_targets_active_and_approved_skills(tmp_path):
    with make_client(tmp_path) as client:
        active_response = client.post(
            "/api/skills",
            json={
                "skill_id": "active-skill",
                "name": "Active Skill",
                "version": 1,
                "status": "active",
                "platform": "site",
                "strategy": {"prompt": "screen"},
                "health_check_config": {"required_strategy_keys": ["prompt", "rubric"]},
            },
        )
        approved_response = client.post(
            "/api/skills",
            json={
                "skill_id": "approved-skill",
                "name": "Approved Skill",
                "version": 1,
                "status": "approved",
                "platform": "site",
                "strategy": {"prompt": "score", "rubric": "v1"},
                "health_check_config": {"required_strategy_keys": ["prompt", "rubric"]},
            },
        )
        draft_response = client.post(
            "/api/skills",
            json={
                "skill_id": "draft-skill",
                "name": "Draft Skill",
                "version": 1,
                "status": "draft",
                "platform": "site",
                "strategy": {},
                "health_check_config": {"required_strategy_keys": ["prompt"]},
            },
        )

        assert active_response.status_code == 201
        assert approved_response.status_code == 201
        assert draft_response.status_code == 201

        active_id = active_response.json()["id"]
        approved_id = approved_response.json()["id"]
        draft_id = draft_response.json()["id"]

        sweep_response = client.post("/api/skills/health-checks/sweep", json={})
        assert sweep_response.status_code == 200

        payload = sweep_response.json()
        assert payload["checked_count"] == 2
        assert payload["degraded_count"] == 1
        assert payload["statuses"] == ["active", "approved"]

        result_by_id = {item["skill_id"]: item for item in payload["results"]}
        assert set(result_by_id) == {active_id, approved_id}
        assert result_by_id[active_id]["degraded"] is True
        assert result_by_id[active_id]["health"] == "warning"
        assert "missing_strategy_key:rubric" in result_by_id[active_id]["issues"]
        assert result_by_id[approved_id]["degraded"] is False
        assert result_by_id[approved_id]["health"] == "healthy"

        active_skill = client.get(f"/api/skills/{active_id}")
        approved_skill = client.get(f"/api/skills/{approved_id}")
        draft_skill = client.get(f"/api/skills/{draft_id}")

        assert active_skill.status_code == 200
        assert approved_skill.status_code == 200
        assert draft_skill.status_code == 200
        assert active_skill.json()["status"] == "degraded"
        assert active_skill.json()["last_health_status"] == "warning"
        assert approved_skill.json()["status"] == "approved"
        assert approved_skill.json()["last_health_status"] == "healthy"
        assert draft_skill.json()["status"] == "draft"


def test_skill_health_check_sweep_supports_explicit_skill_selection(tmp_path):
    with make_client(tmp_path) as client:
        first_response = client.post(
            "/api/skills",
            json={
                "skill_id": "selected-skill",
                "name": "Selected Skill",
                "version": 1,
                "status": "approved",
                "platform": "site",
                "strategy": {"prompt": "screen"},
                "health_check_config": {"required_strategy_keys": ["prompt"]},
            },
        )
        second_response = client.post(
            "/api/skills",
            json={
                "skill_id": "other-skill",
                "name": "Other Skill",
                "version": 1,
                "status": "active",
                "platform": "site",
                "strategy": {"prompt": "screen"},
                "health_check_config": {"required_strategy_keys": ["prompt"]},
            },
        )

        assert first_response.status_code == 201
        assert second_response.status_code == 201

        first_id = first_response.json()["id"]
        second_id = second_response.json()["id"]

        sweep_response = client.post(
            "/api/skills/health-checks/sweep",
            json={
                "skill_ids": [first_id],
                "statuses": ["approved", "active"],
                "observed_results_by_skill": {
                    first_id: {"status": "pass", "overall": 91},
                    second_id: {"status": "fail", "overall": 12},
                },
            },
        )
        assert sweep_response.status_code == 200
        payload = sweep_response.json()
        assert payload["checked_count"] == 1
        assert payload["degraded_count"] == 0
        assert [item["skill_id"] for item in payload["results"]] == [first_id]

        untouched_skill = client.get(f"/api/skills/{second_id}")
        assert untouched_skill.status_code == 200
        assert untouched_skill.json()["status"] == "active"
        assert untouched_skill.json()["last_health_check"] is None
