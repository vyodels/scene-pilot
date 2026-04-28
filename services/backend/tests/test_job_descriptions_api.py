from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from recruit_agent.core.settings import load_settings
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
