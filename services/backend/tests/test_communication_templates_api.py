from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from recruit_agent.core.settings import load_settings
from recruit_agent.repositories.domain import CandidateApplicationRepository, CandidateRepository, JobDescriptionRepository
from recruit_agent.server import create_app


def test_communication_template_render_uses_application_context(tmp_path: Path) -> None:
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
                    "name": "李明宇",
                    "platform": "boss",
                    "platform_candidate_id": "boss-001",
                    "contact_info": {"title": "SaaS 销售", "tags": ["企业服务", "SaaS"]},
                }
            )
            job = JobDescriptionRepository(session).create(
                {
                    "title": "销售工程师",
                    "company_name": "联科科技",
                    "location": "上海",
                    "compensation_text": "25K-30K",
                }
            )
            application = CandidateApplicationRepository(session).create(
                {
                    "person_id": candidate.candidate_person_id,
                    "job_description_id": job.job_description_id,
                    "platform": "boss",
                    "source_platform": "boss",
                    "current_status": "in_conversation",
                }
            )

        templates = client.get("/api/communication-templates")
        assert templates.status_code == 200
        assert {item["templateId"] for item in templates.json()} >= {"application_greeting", "job_share", "wechat_request"}

        rendered = client.post(
            "/api/communication-templates/job_share/render",
            json={"applicationId": application.candidate_application_id},
        )
        assert rendered.status_code == 200
        payload = rendered.json()
        assert payload["templateId"] == "job_share"
        assert payload["messageType"] == "job_share"
        assert payload["missingVariables"] == []
        assert "销售工程师" in payload["content"]
        assert "联科科技" in payload["content"]
        assert "25K-30K" in payload["content"]
    finally:
        client.__exit__(None, None, None)
        os.environ.pop("RECRUIT_AGENT_DATA_DIR", None)
        load_settings.cache_clear()
