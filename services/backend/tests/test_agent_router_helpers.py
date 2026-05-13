from __future__ import annotations

from types import SimpleNamespace

from recruit_agent.api.routers.agent import _serialize_agent_projection


def test_serialize_agent_projection_accepts_legacy_datetime_strings() -> None:
    payload = _serialize_agent_projection(
        SimpleNamespace(
            id="definition-1",
            definition_key="recruit-agent",
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
            product_bindings={"autonomous": {"session_key": "autonomous"}},
            product_config={},
            product_projections={"autonomous": {"name": "Autonomous"}},
            agent_metadata={},
            created_at="2026-04-16 16:48:41.396084",
            updated_at="2026-04-16 16:48:41.396084",
        ),
        kind="autonomous",
    )

    assert payload["created_at"] == 1776329321
    assert payload["updated_at"] == 1776329321
    assert payload["kind"] == "autonomous"
    assert payload["agentDefinitionId"] == "definition-1"
