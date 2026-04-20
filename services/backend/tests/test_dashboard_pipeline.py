from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from scene_pilot.core.settings import load_settings
from scene_pilot.repositories.domain import CandidateApplicationRepository, CandidateRepository, JobDescriptionRepository
from scene_pilot.server import create_app


def test_dashboard_pipeline_uses_cumulative_funnel_counts(tmp_path: Path) -> None:
    os.environ["RECRUIT_AGENT_DATA_DIR"] = str(tmp_path)
    load_settings.cache_clear()
    app = create_app()
    client = TestClient(app)
    client.__enter__()
    try:
        session_factory = app.state.session_factory
        with session_factory() as session:
            job = JobDescriptionRepository(session).create({"title": "Backend Engineer"})

            def create_application(*, index: int, status: str, milestone: str | None) -> None:
                candidate = CandidateRepository(session).create(
                    {
                        "name": f"Candidate {index}",
                        "platform": "boss",
                        "platform_candidate_id": f"boss-{index:03d}",
                    }
                )
                CandidateApplicationRepository(session).create(
                    {
                        "person_id": candidate.candidate_person_id,
                        "job_description_id": job.job_description_id,
                        "platform": "boss",
                        "source_platform": "boss",
                        "current_status": status,
                        "current_stage_key": status,
                        "deepest_milestone": milestone,
                        "state_snapshot": {
                            "current_status": status,
                            "current_stage_key": status,
                        },
                    }
                )

            create_application(index=1, status="discovered", milestone="M01")
            create_application(index=2, status="outreach_pending", milestone="M03")
            create_application(index=3, status="contact_acquired", milestone="M11")
            create_application(index=4, status="archived", milestone="M11")
            create_application(index=5, status="interview_scheduled", milestone="M12")
            session.commit()

        response = client.get("/api/dashboard")
        assert response.status_code == 200
        payload = response.json()
        assert {item["jobDescription"]["title"] for item in payload["applications"]} == {"Backend Engineer"}
        pipeline = {item["label"]: item["value"] for item in payload["pipeline"]}
        assert pipeline == {
            "发现与 AI 在线评估": 5,
            "发起沟通与建立对话": 4,
            "获取简历与评估": 3,
            "获取联系方式": 3,
            "面试与结果": 1,
        }
    finally:
        client.__exit__(None, None, None)
        os.environ.pop("RECRUIT_AGENT_DATA_DIR", None)
        load_settings.cache_clear()
