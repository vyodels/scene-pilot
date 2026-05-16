from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from recruit_station.core.settings import AppSettings
from recruit_station.server import create_app


def test_settings_maps_platform_runtime_policies(tmp_path: Path) -> None:
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'settings.db'}",
    )
    with TestClient(create_app(settings)) as client:
        initial = client.get("/api/settings")
        assert initial.status_code == 200, initial.text
        assert initial.json()["platform"]["behaviorBudget"]["max_candidates_per_hour"] == 20
        assert initial.json()["platform"]["antiDetectionPolicy"]["mode"] == "generic_human_paced"

        patched = client.patch(
            "/api/settings",
            json={
                "platform": {
                    "behaviorBudget": {
                        "max_candidates_per_hour": 3,
                        "max_candidates_per_day": 9,
                    },
                    "antiDetectionPolicy": {
                        "mode": "single_account_manual_paced",
                        "require_browser_hid_preflight": True,
                    },
                }
            },
        )
        assert patched.status_code == 200, patched.text

        body = patched.json()
        assert body["platform"]["behaviorBudget"]["max_candidates_per_hour"] == 3
        assert body["platform"]["behaviorBudget"]["max_candidates_per_day"] == 9
        assert body["platform"]["antiDetectionPolicy"]["mode"] == "single_account_manual_paced"
        assert client.app.state.container.autonomous_adapter.behavior_budget["max_candidates_per_hour"] == 3
        assert client.app.state.container.autonomous_adapter.anti_detection_policy["mode"] == "single_account_manual_paced"
