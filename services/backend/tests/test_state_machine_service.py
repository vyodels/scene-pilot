from __future__ import annotations

from types import SimpleNamespace

from recruit_agent.services.state_machine import load_default_state_machine_payload, serialize_state_machine_version


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


def test_default_state_machine_is_code_defined_and_valid() -> None:
    payload = load_default_state_machine_payload()
    node_ids = {str(node["id"]) for node in payload["nodes"]}
    terminal_ids = {str(node["id"]) for node in payload["nodes"] if node["isTerminal"]}

    assert payload["version"] == 2
    assert "online_resume_fetching" in node_ids
    assert "offline_resume_acquired" in node_ids
    assert "human_screening" in node_ids
    assert "exception_closed" in node_ids
    assert payload["globalTransitions"] == []

    for transition in payload["transitions"]:
        assert transition["fromState"] in node_ids
        assert transition["toState"] in node_ids
        assert not (
            transition["toState"] == "exception_closed"
            and transition["fromState"] in terminal_ids
        )
