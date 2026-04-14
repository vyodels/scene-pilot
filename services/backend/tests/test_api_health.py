from fastapi.testclient import TestClient

from scene_pilot.core.app import create_app
from scene_pilot.core.settings import AppSettings


def test_health_endpoint_reports_ready(tmp_path):
    app = create_app(
        AppSettings(
            data_dir=str(tmp_path / "data"),
            database_url=f"sqlite:///{tmp_path / 'scene-pilot.db'}",
        )
    )

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}

