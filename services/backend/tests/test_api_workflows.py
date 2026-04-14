from fastapi.testclient import TestClient

from scene_pilot.core.app import create_app
from scene_pilot.core.settings import AppSettings


def make_client(tmp_path):
    app = create_app(
        AppSettings(
            data_dir=str(tmp_path / "data"),
            database_url=f"sqlite:///{tmp_path / 'scene-pilot.db'}",
        )
    )
    return TestClient(app)


def test_workflow_crud(tmp_path):
    with make_client(tmp_path) as client:
        create_response = client.post(
            "/api/workflows",
            json={
                "name": "Initial Screening",
                "jd_id": "jd-001",
                "config": {"nodes": ["discover", "screen"]},
                "status": "draft",
                "version": 1,
            },
        )
        assert create_response.status_code == 201
        workflow = create_response.json()
        assert workflow["name"] == "Initial Screening"

        workflow_id = workflow["id"]
        list_response = client.get("/api/workflows")
        assert list_response.status_code == 200
        assert len(list_response.json()) == 1

        patch_response = client.patch(
            f"/api/workflows/{workflow_id}",
            json={"status": "active", "version": 2},
        )
        assert patch_response.status_code == 200
        assert patch_response.json()["status"] == "active"
        assert patch_response.json()["version"] == 2

        delete_response = client.delete(f"/api/workflows/{workflow_id}")
        assert delete_response.status_code == 204

