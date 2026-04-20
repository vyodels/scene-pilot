from __future__ import annotations

from types import SimpleNamespace

from scene_pilot.services.state_machine import serialize_state_machine_version


def test_serialize_state_machine_version_accepts_legacy_datetime_strings() -> None:
    payload = serialize_state_machine_version(
        SimpleNamespace(
            version=1,
            updated_at="2026-04-16 16:48:41.419762",
            updated_by="system",
            change_summary="seed",
            nodes_json=[],
            transitions_json=[],
            global_transitions_json=[],
            version_metadata={},
            published_at="2026-04-16 16:48:41.419759",
            created_at="2026-04-16 16:48:41.419762",
        )
    )

    assert payload["updatedAt"] == 1776358121
    assert payload["publishedAt"] == 1776358121
    assert payload["createdAt"] == 1776358121
