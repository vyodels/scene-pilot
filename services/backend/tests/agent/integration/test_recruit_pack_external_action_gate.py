from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from recruit_agent.core.settings import AppSettings
from recruit_agent.db.session import create_engine_from_settings, create_session_factory, initialize_database
from recruit_agent.models.domain import AgentGlobalState, Candidate
from recruit_agent.plugins.host import PluginHost
from recruit_agent.plugins.loader import install_manifest
from recruit_agent.plugins.recruit.manifest import RecruitPluginManifest


def _make_session(tmp_path: Path) -> Session:
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'recruit-pack-guard.db'}",
    )
    engine = create_engine_from_settings(settings)
    initialize_database(engine)
    return create_session_factory(engine)()


def test_recruit_pack_requires_global_pause_before_assistant_external_action(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    try:
        candidate = Candidate(name="Alice")
        session.add(candidate)
        session.commit()

        session_factory = create_session_factory(session.get_bind())
        host = PluginHost()
        install_manifest(host, RecruitPluginManifest(session_factory))
        context = {
            "world_snapshot": {},
            "scope_kind": "candidate",
            "scope_ref": candidate.candidate_person_id,
            "recent_events": [],
            "available_tools": [],
            "available_mcps": [],
            "hash": "ctx-1",
        }

        blocked = host.run_guard_checks_sync(
            "send_external_message",
            {
                "candidate_person_id": candidate.candidate_person_id,
                "actor_kind": "assistant",
                "external_target": True,
            },
            context,
        )
        assert blocked[0]["allowed"] is False

        session.add(AgentGlobalState(id="singleton", autonomous_paused=True, pause_reason="manual"))
        session.commit()

        allowed = host.run_guard_checks_sync(
            "send_external_message",
            {
                "candidate_person_id": candidate.candidate_person_id,
                "actor_kind": "assistant",
                "external_target": True,
            },
            context,
        )
        assert allowed[0]["allowed"] is True
    finally:
        session.close()


def test_recruit_pack_requests_human_approval_once_then_allows_seeded_resume(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    try:
        session_factory = create_session_factory(session.get_bind())
        host = PluginHost()
        install_manifest(host, RecruitPluginManifest(session_factory))

        blocked_context = {
            "world_snapshot": {},
            "scope_kind": "global",
            "scope_ref": "workspace:shared",
            "recent_events": [],
            "available_tools": [],
            "available_mcps": [],
            "hash": "ctx-approval",
            "input": {},
        }

        blocked = host.run_guard_checks_sync(
            "request_human_approval",
            {"title": "联系候选人索要联系方式", "application_id": "app-1"},
            blocked_context,
        )
        assert blocked[0]["allowed"] is False
        assert blocked[0]["severity"] == "waiting_human"

        resumed_context = {
            "world_snapshot": {},
            "scope_kind": "global",
            "scope_ref": "workspace:shared",
            "recent_events": [],
            "available_tools": [],
            "available_mcps": [],
            "hash": "ctx-approval-resume",
            "input": {},
        }
        allowed = host.run_guard_checks_sync(
            "request_human_approval",
            {"title": "联系候选人索要联系方式", "application_id": "app-1", "approved_by_operator": True},
            resumed_context,
        )
        assert allowed[0]["allowed"] is True
    finally:
        session.close()
