from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from scene_pilot.core.settings import AppSettings
from scene_pilot.db.session import create_engine_from_settings, create_session_factory, initialize_database
from scene_pilot.memory.service import MemoryService, MemoryVersionConflict
from scene_pilot.models.domain import Candidate, RecruitAgentProfile


def _make_session(tmp_path: Path) -> Session:
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'agent-memory-conflict.db'}",
    )
    engine = create_engine_from_settings(settings)
    initialize_database(engine)
    return create_session_factory(engine)()


def test_memory_service_detects_expected_version_conflicts(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    try:
        profile = RecruitAgentProfile(agent_key="primary", name="Primary", is_primary=True)
        candidate = Candidate(name="Alice")
        session.add_all([profile, candidate])
        session.commit()

        service = MemoryService(session)
        first = service.write(
            scope_kind="candidate",
            scope_ref=candidate.id,
            agent_profile_id=profile.id,
            memory_item_id="cand-1",
            kind="candidate_fact",
            index_name="candidate-status",
            index_description="Candidate replied",
            summary="Initial",
            content={"status": "new"},
        )
        updated = service.write(
            scope_kind="candidate",
            scope_ref=candidate.id,
            agent_profile_id=profile.id,
            memory_item_id="cand-1",
            kind="candidate_fact",
            index_name="candidate-status",
            index_description="Candidate replied",
            summary="Updated",
            content={"status": "replied"},
            expected_version=first["version"],
        )

        assert updated["version"] == 2
        assert updated["summary"] == "Updated"

        with pytest.raises(MemoryVersionConflict):
            service.write(
                scope_kind="candidate",
                scope_ref=candidate.id,
                agent_profile_id=profile.id,
                memory_item_id="cand-1",
                kind="candidate_fact",
                index_name="candidate-status",
                index_description="Candidate replied",
                summary="Stale",
                content={"status": "stale"},
                expected_version=1,
            )
    finally:
        session.close()
