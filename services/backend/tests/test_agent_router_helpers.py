from __future__ import annotations

from types import SimpleNamespace

from recruit_agent.api.routers.agent import _serialize_profile


def test_serialize_profile_accepts_legacy_datetime_strings() -> None:
    payload = _serialize_profile(
        SimpleNamespace(
            id="profile-1",
            agent_key="autonomous",
            name="Autonomous",
            status="active",
            description="desc",
            is_primary=True,
            role_definition={},
            prompt_config={},
            playbook_blueprint={},
            memory_policy={},
            dashboard_config={},
            channel_config={},
            agent_metadata={},
            created_at="2026-04-16 16:48:41.396084",
            updated_at="2026-04-16 16:48:41.396084",
        )
    )

    assert payload["created_at"] == 1776329321
    assert payload["updated_at"] == 1776329321
    assert payload["kind"] == "autonomous"
