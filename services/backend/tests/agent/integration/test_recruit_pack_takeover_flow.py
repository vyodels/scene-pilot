from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from scene_pilot.core.settings import AppSettings
from scene_pilot.db.session import create_engine_from_settings, create_session_factory, initialize_database
from scene_pilot.models.domain import Candidate
from scene_pilot.plugins.host import PluginHost
from scene_pilot.plugins.loader import install_manifest
from scene_pilot.plugins.recruit.manifest import RecruitPluginManifest
from scene_pilot.runtime.models import Observation


def _make_session(tmp_path: Path) -> Session:
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'recruit-pack.db'}",
    )
    engine = create_engine_from_settings(settings)
    initialize_database(engine)
    return create_session_factory(engine)()


def test_recruit_pack_takeover_flow_exposes_tools_observation_and_router(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    try:
        candidate = Candidate(name="Alice")
        session.add(candidate)
        session.commit()

        session_factory = create_session_factory(session.get_bind())
        host = PluginHost()
        install_manifest(host, RecruitPluginManifest(session_factory))

        tool_result = host.tool_registry.execute(
            "take_over_candidate",
            {
                "candidate_person_id": candidate.candidate_person_id,
                "locked_by": "human-a",
                "reason": "manual follow-up",
            },
        )
        assert tool_result.is_error is False

        observation = Observation(
            world_snapshot={},
            scope_kind="candidate",
            scope_ref=candidate.candidate_person_id,
            recent_events=[],
            available_tools=[],
            available_skills=[],
            available_mcps=[],
            hash="obs-1",
        )
        enriched = host.run_observation_enrichers_sync(observation)
        verdicts = host.run_guard_checks_sync(
            "send_message",
            {"candidate_person_id": candidate.candidate_person_id, "actor_kind": "autonomous"},
            observation,
        )

        assert enriched["world_snapshot"]["plugin_recruit"]["human_locked"] is True
        assert verdicts[0].allowed is False
        assert "人工接管" in host.collect_persona_fragments()[0]

        app = FastAPI()
        for router in host.routers:
            app.include_router(router)
        client = TestClient(app)

        locks_response = client.get("/api/recruit/candidates/locks")
        assert locks_response.status_code == 200
        assert locks_response.json()[0]["candidate_person_id"] == candidate.candidate_person_id

        release_response = client.post(
            f"/api/recruit/candidates/{candidate.candidate_person_id}/release",
            json={"released_by": "human-a", "handover_note": "done"},
        )
        assert release_response.status_code == 200
        assert release_response.json()["released_by"] == "human-a"
    finally:
        session.close()
