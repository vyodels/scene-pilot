from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from recruit_agent.core.settings import load_settings
from recruit_agent.repositories.domain import CandidateApplicationRepository, CandidateRepository, JobDescriptionRepository
from recruit_agent.server import create_app


def test_job_description_crud_routes(tmp_path: Path) -> None:
    os.environ["RECRUIT_AGENT_DATA_DIR"] = str(tmp_path)
    load_settings.cache_clear()
    app = create_app()
    client = TestClient(app)
    client.__enter__()
    try:
        created = client.post(
            "/api/job-descriptions",
            json={
                "title": "销售工程师",
                "company_name": "联科科技",
                "department": "销售工程部",
                "location": "上海",
                "headcount": 2,
                "benefit_tags": ["企业服务", "SaaS"],
            },
        )
        assert created.status_code == 201
        job_description_id = created.json()["jobDescriptionId"]

        listed = client.get("/api/job-descriptions?limit=1&offset=0")
        assert listed.status_code == 200
        listed_body = listed.json()
        assert listed_body["total"] == 1
        assert listed_body["limit"] == 1
        assert listed_body["offset"] == 0
        assert listed_body["hasNext"] is False
        assert len(listed_body["items"]) == 1
        assert listed_body["items"][0]["jobDescriptionId"] == job_description_id

        detail = client.get(f"/api/job-descriptions/{job_description_id}")
        assert detail.status_code == 200
        assert detail.json()["title"] == "销售工程师"

        patched = client.patch(
            f"/api/job-descriptions/{job_description_id}",
            json={"status": "paused", "summary": "重点客户销售岗位"},
        )
        assert patched.status_code == 200
        assert patched.json()["status"] == "paused"
        assert patched.json()["summary"] == "重点客户销售岗位"

        deleted = client.delete(f"/api/job-descriptions/{job_description_id}")
        assert deleted.status_code == 204

        missing = client.get(f"/api/job-descriptions/{job_description_id}")
        assert missing.status_code == 404
    finally:
        client.__exit__(None, None, None)
        os.environ.pop("RECRUIT_AGENT_DATA_DIR", None)
        load_settings.cache_clear()


def test_job_description_list_pagination_metadata(tmp_path: Path) -> None:
    os.environ["RECRUIT_AGENT_DATA_DIR"] = str(tmp_path)
    load_settings.cache_clear()
    app = create_app()
    client = TestClient(app)
    client.__enter__()
    try:
        statuses = ["active", "paused", "closed"]
        for index, status in enumerate(statuses):
            created = client.post(
                "/api/job-descriptions",
                json={
                    "title": f"销售工程师 {index}",
                    "location": "上海",
                    "department": "销售工程部",
                    "status": status,
                },
            )
            assert created.status_code == 201

        listed = client.get("/api/job-descriptions?limit=2&offset=1")
        assert listed.status_code == 200
        body = listed.json()
        assert body["total"] == 3
        assert body["limit"] == 2
        assert body["offset"] == 1
        assert body["hasNext"] is False
        assert len(body["items"]) == 2

        first_page = client.get("/api/job-descriptions?limit=2&offset=0")
        assert first_page.status_code == 200
        assert first_page.json()["hasNext"] is True

        paused = client.get("/api/job-descriptions?limit=10&status=paused")
        assert paused.status_code == 200
        assert paused.json()["total"] == 1
        assert paused.json()["items"][0]["status"] == "paused"

        filtered = client.get("/api/job-descriptions?limit=10&keyword=销售工程师%202")
        assert filtered.status_code == 200
        assert filtered.json()["total"] == 1
        assert filtered.json()["items"][0]["title"] == "销售工程师 2"
    finally:
        client.__exit__(None, None, None)
        os.environ.pop("RECRUIT_AGENT_DATA_DIR", None)
        load_settings.cache_clear()


def test_job_description_list_filters_by_applicant_keyword(tmp_path: Path) -> None:
    os.environ["RECRUIT_AGENT_DATA_DIR"] = str(tmp_path)
    load_settings.cache_clear()
    app = create_app()
    client = TestClient(app)
    client.__enter__()
    try:
        session_factory = app.state.session_factory
        with session_factory() as session:
            sales_job = JobDescriptionRepository(session).create({"title": "销售工程师"})
            java_job = JobDescriptionRepository(session).create({"title": "Java 开发工程师"})
            person = CandidateRepository(session).create(
                {
                    "name": "李明宇",
                    "platform": "boss",
                    "platform_candidate_id": "boss-limingyu",
                    "contact_info": {"phone": "13800138123", "email": "limingyu@example.com"},
                }
            )
            other_person = CandidateRepository(session).create(
                {
                    "name": "王思雨",
                    "platform": "boss",
                    "platform_candidate_id": "boss-wangsiyu",
                }
            )
            CandidateApplicationRepository(session).create(
                {
                    "person_id": person.candidate_person_id,
                    "job_description_id": sales_job.job_description_id,
                    "platform": "boss",
                    "source_platform": "boss",
                    "current_status": "communicating",
                    "current_stage_key": "communicating",
                }
            )
            CandidateApplicationRepository(session).create(
                {
                    "person_id": other_person.candidate_person_id,
                    "job_description_id": java_job.job_description_id,
                    "platform": "boss",
                    "source_platform": "boss",
                    "current_status": "communicating",
                    "current_stage_key": "communicating",
                    "contact_snapshot": {"mobile": "13900139123"},
                }
            )

        by_name = client.get("/api/job-descriptions?limit=10&applicant_keyword=李明宇")
        assert by_name.status_code == 200
        assert by_name.json()["total"] == 1
        assert by_name.json()["items"][0]["title"] == "销售工程师"

        by_phone = client.get("/api/job-descriptions?limit=10&applicant_keyword=13900139123")
        assert by_phone.status_code == 200
        assert by_phone.json()["total"] == 1
        assert by_phone.json()["items"][0]["title"] == "Java 开发工程师"
    finally:
        client.__exit__(None, None, None)
        os.environ.pop("RECRUIT_AGENT_DATA_DIR", None)
        load_settings.cache_clear()


def test_job_description_funnel_stats_use_state_machine_milestones(tmp_path: Path) -> None:
    os.environ["RECRUIT_AGENT_DATA_DIR"] = str(tmp_path)
    load_settings.cache_clear()
    app = create_app()
    client = TestClient(app)
    client.__enter__()
    try:
        session_factory = app.state.session_factory
        with session_factory() as session:
            job = JobDescriptionRepository(session).create({"title": "销售工程师"})

            def create_application(index: int, status: str, milestone: str | None = None) -> None:
                candidate = CandidateRepository(session).create(
                    {
                        "name": f"投递人 {index}",
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
                        "contact_snapshot": {"phone": "13800138000"} if index == 3 else {},
                        "resume_snapshot": {"available": True, "file_path": "/tmp/resume.pdf"} if index == 4 else {},
                        "ai_scores": {"overall": 81} if index == 5 else {},
                    }
                )

            create_application(1, "discovered", "M01")
            create_application(2, "online_resume_passed", "M04")
            create_application(3, "profile_ready", "M13")
            create_application(4, "interview_scheduled", "M15")
            create_application(5, "offer_accepted", "M19")

        response = client.get(f"/api/job-descriptions/{job.job_description_id}/funnel-stats")
        assert response.status_code == 200
        payload = response.json()
        assert payload["jobDescriptionId"] == job.job_description_id
        assert payload["applications"] == 5
        assert payload["communicating"] == 4
        assert payload["interviewing"] == 2
        assert payload["offers"] == 1
        assert payload["hired"] == 1
        assert payload["withContact"] == 1
        assert payload["withResume"] == 1
        assert payload["withAiScore"] == 1
        assert payload["byStatus"]["offer_accepted"] == 1
        steps = {item["key"]: item for item in payload["steps"]}
        assert steps["communicating"]["label"] == "在线简历"
        assert steps["communicating"]["percent"] == 80.0
    finally:
        client.__exit__(None, None, None)
        os.environ.pop("RECRUIT_AGENT_DATA_DIR", None)
        load_settings.cache_clear()
