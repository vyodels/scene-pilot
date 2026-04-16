from fastapi.testclient import TestClient

from scene_pilot.core.app import create_app
from scene_pilot.core.settings import AppSettings


def make_client(tmp_path):
    app = create_app(
        AppSettings(
            data_dir=str(tmp_path / "data"),
            database_url=f"sqlite:///{tmp_path / 'recruit-agent.db'}",
        )
    )
    return TestClient(app)


def test_candidate_crud(tmp_path):
    with make_client(tmp_path) as client:
        create_response = client.post(
            "/api/candidates",
            json={
                "name": "Ada Lovelace",
                "platform": "boss",
                "platform_candidate_id": "boss-123",
                "current_status": "discovered",
                "jd_id": "jd-001",
                "contact_info": {"wechat": "ada"},
                "ai_scores": {"overall": 92},
            },
        )
        assert create_response.status_code == 201
        candidate = create_response.json()
        assert candidate["name"] == "Ada Lovelace"

        candidate_id = candidate["id"]
        get_response = client.get(f"/api/candidates/{candidate_id}")
        assert get_response.status_code == 200
        assert get_response.json()["platform_candidate_id"] == "boss-123"

        patch_response = client.patch(
            f"/api/candidates/{candidate_id}",
            json={"current_status": "screening", "last_contacted_at": "2026-04-14T00:00:00Z"},
        )
        assert patch_response.status_code == 200
        assert patch_response.json()["current_status"] == "screening"

        delete_response = client.delete(f"/api/candidates/{candidate_id}")
        assert delete_response.status_code == 204
