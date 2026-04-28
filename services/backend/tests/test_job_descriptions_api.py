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
