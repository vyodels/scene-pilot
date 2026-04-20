from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from scene_pilot.core.settings import load_settings
from scene_pilot.repositories.domain import (
    AgentSessionRepository,
    ApprovalRepository,
    CandidateApplicationRepository,
    CandidateRepository,
    JobDescriptionRepository,
    OperatorInteractionRepository,
)
from scene_pilot.server import create_app
from scene_pilot.services.recruit_agent import ensure_primary_recruit_agent_profile


def test_resume_artifact_updates_candidate_projection(tmp_path: Path) -> None:
    os.environ["RECRUIT_AGENT_DATA_DIR"] = str(tmp_path)
    load_settings.cache_clear()
    app = create_app()
    client = TestClient(app)
    client.__enter__()
    try:
        session_factory = app.state.session_factory
        with session_factory() as session:
            candidate = CandidateRepository(session).create(
                {
                    "name": "Alice",
                    "platform": "boss",
                    "platform_candidate_id": "boss-001",
                }
            )
            job = JobDescriptionRepository(session).create({"title": "Backend Engineer"})
            application = CandidateApplicationRepository(session).create(
                {
                    "person_id": candidate.candidate_person_id,
                    "job_description_id": job.job_description_id,
                    "platform": "boss",
                    "source_platform": "boss",
                    "current_status": "discovered",
                }
            )

        created = client.post(
            f"/api/candidate-applications/{application.candidate_application_id}/resume-artifacts",
            json={
                "source": "boss",
                "artifactType": "resume",
                "fileName": "alice-resume.pdf",
                "filePath": "/tmp/alice-resume.pdf",
                "extractedText": "Alice has 8 years of backend experience.",
                "contactSnapshot": {
                    "phone": "13800138000",
                    "email": "alice@example.com",
                },
                "artifactMetadata": {
                    "source": "boss",
                    "channel": "resume_download",
                },
            },
        )
        assert created.status_code == 201

        application_read = client.get(f"/api/candidate-applications/{application.candidate_application_id}")
        assert application_read.status_code == 200
        payload = application_read.json()
        assert payload["resumeAvailable"] is True
        assert payload["contactInfo"]["phone"] == "13800138000"
        assert payload["resumePath"] == "/tmp/alice-resume.pdf"
        assert payload["onlineResumeText"] == "Alice has 8 years of backend experience."
        assert payload["contactSnapshot"]["phone"] == "13800138000"
        assert payload["resumeSnapshot"]["file_path"] == "/tmp/alice-resume.pdf"

        thread = client.get(f"/api/candidate-applications/{application.candidate_application_id}/thread")
        assert thread.status_code == 200
        thread_payload = thread.json()
        assert thread_payload["application"]["person"]["resumePath"] == "/tmp/alice-resume.pdf"
        assert thread_payload["application"]["person"]["onlineResumeText"] == "Alice has 8 years of backend experience."
        assert thread_payload["application"]["contactSnapshot"]["email"] == "alice@example.com"
        assert thread_payload["application"]["resumeSnapshot"]["status"] == "received"
        assert len(thread_payload["resumeArtifacts"]) == 1
    finally:
        client.__exit__(None, None, None)
        os.environ.pop("RECRUIT_AGENT_DATA_DIR", None)
        load_settings.cache_clear()


def test_application_thread_runtime_records_are_isolated_by_application_id(tmp_path: Path) -> None:
    os.environ["RECRUIT_AGENT_DATA_DIR"] = str(tmp_path)
    load_settings.cache_clear()
    app = create_app()
    client = TestClient(app)
    client.__enter__()
    try:
        session_factory = app.state.session_factory
        with session_factory() as session:
            candidate = CandidateRepository(session).create(
                {
                    "name": "Bob",
                    "platform": "boss",
                    "platform_candidate_id": "boss-002",
                }
            )
            job = JobDescriptionRepository(session).create({"title": "Staff Engineer"})
            other_job = JobDescriptionRepository(session).create({"title": "Principal Engineer"})
            application_a = CandidateApplicationRepository(session).create(
                {
                    "person_id": candidate.candidate_person_id,
                    "job_description_id": job.job_description_id,
                    "platform": "boss",
                    "source_platform": "boss",
                    "current_status": "discovered",
                }
            )
            application_b = CandidateApplicationRepository(session).create(
                {
                    "person_id": candidate.candidate_person_id,
                    "job_description_id": other_job.job_description_id,
                    "platform": "boss",
                    "source_platform": "boss",
                    "current_status": "contacting",
                }
            )
            profile = ensure_primary_recruit_agent_profile(session)
            runtime_session = AgentSessionRepository(session).create(
                {
                    "agent_profile_id": profile.id,
                    "session_key": "primary",
                    "status": "active",
                    "runtime_metadata": {"agent_key": profile.agent_key},
                }
            )

            approval_a = ApprovalRepository(session).create(
                {
                    "target_type": "candidate_application",
                    "target_id": application_a.id,
                    "title": "Approve application A outreach",
                    "payload": {"application_id": application_a.candidate_application_id},
                }
            )
            approval_b = ApprovalRepository(session).create(
                {
                    "target_type": "candidate_application",
                    "target_id": application_b.candidate_application_id,
                    "title": "Approve application B outreach",
                    "payload": {"application_id": application_b.candidate_application_id},
                }
            )
            ApprovalRepository(session).create(
                {
                    "target_type": "candidate_person",
                    "target_id": candidate.candidate_person_id,
                    "title": "Generic person approval",
                    "payload": {"candidate_id": candidate.candidate_person_id},
                }
            )

            OperatorInteractionRepository(session).create(
                {
                    "session_id": runtime_session.id,
                    "person_id": candidate.candidate_person_id,
                    "application_id": application_a.candidate_application_id,
                    "approval_id": approval_a.id,
                    "title": "Resolve application A approval",
                    "agent_prompt": "只处理 application A",
                    "interaction_type": "confirm",
                    "interaction_metadata": {},
                }
            )
            OperatorInteractionRepository(session).create(
                {
                    "session_id": runtime_session.id,
                    "person_id": candidate.candidate_person_id,
                    "application_id": application_b.candidate_application_id,
                    "approval_id": approval_b.id,
                    "title": "Resolve application B approval",
                    "agent_prompt": "只处理 application B",
                    "interaction_type": "confirm",
                    "interaction_metadata": {},
                }
            )
            OperatorInteractionRepository(session).create(
                {
                    "session_id": runtime_session.id,
                    "person_id": candidate.candidate_person_id,
                    "application_id": application_a.candidate_application_id,
                    "title": "Application A direct interaction",
                    "agent_prompt": "metadata points to application A",
                    "interaction_type": "confirm",
                    "interaction_metadata": {"application_id": application_a.candidate_application_id},
                }
            )
            OperatorInteractionRepository(session).create(
                {
                    "session_id": runtime_session.id,
                    "person_id": candidate.candidate_person_id,
                    "title": "Generic person interaction",
                    "agent_prompt": "person-level only",
                    "interaction_type": "confirm",
                    "interaction_metadata": {},
                }
            )

        thread = client.get(f"/api/candidate-applications/{application_a.candidate_application_id}/thread")
        assert thread.status_code == 200
        payload = thread.json()

        assert [item["title"] for item in payload["runtimeApprovals"]] == ["Approve application A outreach"]
        assert {item["title"] for item in payload["runtimeInteractions"]} == {
            "Resolve application A approval",
            "Application A direct interaction",
        }
    finally:
        client.__exit__(None, None, None)
        os.environ.pop("RECRUIT_AGENT_DATA_DIR", None)
        load_settings.cache_clear()
