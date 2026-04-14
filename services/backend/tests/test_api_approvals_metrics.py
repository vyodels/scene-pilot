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


def test_approvals_feed_metrics(tmp_path):
    with make_client(tmp_path) as client:
        approval_response = client.post(
            "/api/approvals",
            json={
                "target_type": "skill",
                "target_id": "screening-boss",
                "title": "Approve screening skill",
                "status": "pending",
                "requested_by": "agent",
                "payload": {"risk": "low"},
            },
        )
        assert approval_response.status_code == 201
        approval = approval_response.json()
        approval_id = approval["id"]

        metrics_response = client.get("/api/metrics")
        assert metrics_response.status_code == 200
        assert metrics_response.json()["approval_count"] == 1
        assert metrics_response.json()["pending_approval_count"] == 1

        approve_response = client.post(
            f"/api/approvals/{approval_id}/approve",
            json={"reviewed_by": "hr-admin", "notes": "ok"},
        )
        assert approve_response.status_code == 200
        assert approve_response.json()["status"] == "approved"

