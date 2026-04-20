from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from scene_pilot.core.settings import load_settings
from scene_pilot.repositories.domain import CandidateApplicationRepository, CandidateRepository, JobDescriptionRepository
from scene_pilot.server import create_app


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
