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


def test_settings_and_skill_lifecycle(tmp_path):
    with make_client(tmp_path) as client:
        get_response = client.get("/api/settings")
        assert get_response.status_code == 200
        assert get_response.json()["approval_source"] == "desktop_app"

        update_response = client.put(
            "/api/settings",
            json={
                "approval_source": "desktop_app",
                "feature_flags": {"enable_autonomy": True, "enable_skill_health_autonomy": True},
                "skill_health_autonomy_interval_seconds": 30,
            },
        )
        assert update_response.status_code == 200
        assert update_response.json()["feature_flags"]["enable_autonomy"] is True
        assert update_response.json()["feature_flags"]["enable_skill_health_autonomy"] is True
        assert update_response.json()["skill_health_autonomy_interval_seconds"] == 30

        skill_response = client.post(
            "/api/skills",
            json={
                "skill_id": "screening-boss",
                "name": "Boss Screening",
                "version": 1,
                "status": "draft",
                "platform": "boss",
                "strategy": {"steps": ["open", "inspect"]},
            },
        )
        assert skill_response.status_code == 201
        skill_id = skill_response.json()["id"]

        submit_review_response = client.post(f"/api/skills/{skill_id}/submit-review")
        assert submit_review_response.status_code == 200
        assert submit_review_response.json()["status"] == "pending_review"

        approve_response = client.post(
            f"/api/skills/{skill_id}/approve",
            json={"reviewed_by": "human-reviewer", "notes": "validated"},
        )
        assert approve_response.status_code == 200
        assert approve_response.json()["status"] == "approved"
        assert approve_response.json()["confirmed_by"] == "human-reviewer"

        activate_response = client.post(
            f"/api/skills/{skill_id}/activate",
            json={"reviewed_by": "human-reviewer"},
        )
        assert activate_response.status_code == 200
        assert activate_response.json()["status"] == "active"


def test_settings_reload_runtime_provider_config(tmp_path):
    with make_client(tmp_path) as client:
        container = client.app.state.container
        runtime_provider = container.agent_control.agent_loop.provider

        assert runtime_provider.preferred_provider is None
        assert "openai_compatible" not in container.providers.providers

        update_response = client.patch(
            "/api/settings",
            json={
                "provider_config": {
                    "openai_model": "gpt-5.4",
                    "openai_base_url": "http://127.0.0.1:8317/v1",
                    "openai_api_key": "test-openai-compatible-key",
                    "intranet_base_url": "http://intranet.example/api",
                }
            },
        )
        assert update_response.status_code == 200

        reloaded_provider = container.agent_control.agent_loop.provider
        assert reloaded_provider.preferred_provider == "openai_compatible"
        assert "openai_compatible" in container.providers.providers
        assert container.providers.providers["openai_compatible"].config.base_url == "http://127.0.0.1:8317/v1"
        assert container.providers.providers["openai_compatible"].config.api_key == "test-openai-compatible-key"
        assert container.sync.target["base_url"] == "http://intranet.example/api"
