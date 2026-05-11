from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from recruit_agent.core.settings import AppSettings
from recruit_agent.db.session import create_engine_from_settings, create_session_factory, initialize_database
from recruit_agent.models.domain import Candidate, CandidateApplication, JobDescription
from recruit_agent.plugins.host import PluginHost
from recruit_agent.plugins.loader import install_manifest
from recruit_agent.plugins.recruit.manifest import RecruitPluginManifest
from recruit_agent.agent_runtime.models import Observation
from recruit_agent.services.application_window import make_application_window


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
        job_primary = JobDescription(title="AE")
        job_secondary = JobDescription(title="CSM")
        session.add_all([job_primary, job_secondary])
        session.commit()
        primary_application = CandidateApplication(
            person_id=candidate.id,
            job_description_id=job_primary.id,
            application_window=make_application_window(candidate.candidate_person_id, job_primary.job_description_id),
            platform="boss_mock",
            source_platform="boss_mock",
        )
        secondary_application = CandidateApplication(
            person_id=candidate.id,
            job_description_id=job_secondary.id,
            application_window=make_application_window(candidate.candidate_person_id, job_secondary.job_description_id),
            platform="boss_mock",
            source_platform="boss_mock",
        )
        session.add_all([primary_application, secondary_application])
        session.commit()

        session_factory = create_session_factory(session.get_bind())
        host = PluginHost()
        install_manifest(host, RecruitPluginManifest(session_factory))

        tool_result = host.tool_registry.execute(
            "take_over_candidate",
            {
                "application_id": primary_application.candidate_application_id,
                "locked_by": "human-a",
                "reason": "manual follow-up",
            },
        )
        assert tool_result.is_error is False

        observation = Observation(
            world_snapshot={},
            scope_kind="application",
            scope_ref=primary_application.candidate_application_id,
            recent_events=[],
            available_tools=[],
            available_skills=[],
            available_mcps=[],
            hash="obs-1",
        )
        enriched = host.run_observation_enrichers_sync(observation)
        verdicts = host.run_guard_checks_sync(
            "transition_application",
            {"application_id": primary_application.candidate_application_id, "actor_kind": "autonomous", "to_status": "outreach_pending"},
            observation,
        )
        second_application_verdicts = host.run_guard_checks_sync(
            "transition_application",
            {
                "candidate_person_id": candidate.candidate_person_id,
                "job_description_id": job_secondary.job_description_id,
                "actor_kind": "autonomous",
                "to_status": "outreach_pending",
            },
            Observation(
                world_snapshot={},
                scope_kind="application",
                scope_ref=secondary_application.candidate_application_id,
                recent_events=[],
                available_tools=[],
                available_skills=[],
                available_mcps=[],
                hash="obs-2",
            ),
        )

        assert enriched["world_snapshot"]["plugin_recruit"]["human_locked"] is True
        assert enriched["world_snapshot"]["plugin_recruit"]["lock_meta"]["application_id"] == primary_application.candidate_application_id
        assert verdicts[0].allowed is False
        assert verdicts[0].metadata["application_id"] == primary_application.candidate_application_id
        assert second_application_verdicts[0].allowed is True
        assert "人工接管" in host.collect_persona_fragments()[0]

        app = FastAPI()
        for router in host.routers:
            app.include_router(router)
        client = TestClient(app)

        locks_response = client.get("/api/recruit/applications/locks")
        assert locks_response.status_code == 200
        assert locks_response.json()[0]["application_id"] == primary_application.candidate_application_id

        release_response = client.post(
            f"/api/recruit/applications/{primary_application.candidate_application_id}/release",
            json={"released_by": "human-a", "handover_note": "done"},
        )
        assert release_response.status_code == 200
        assert release_response.json()["released_by"] == "human-a"
        assert release_response.json()["application_id"] == primary_application.candidate_application_id
    finally:
        session.close()
