from fastapi.testclient import TestClient

from scene_pilot.core.app import create_app
from scene_pilot.core.settings import AppSettings
from scene_pilot.services.application_window import make_application_window


def make_client(tmp_path):
    app = create_app(
        AppSettings(
            data_dir=str(tmp_path / "data"),
            database_url=f"sqlite:///{tmp_path / 'recruit-agent.db'}",
        )
    )
    return TestClient(app)


def test_candidate_crud(tmp_path):
    with make_client(tmp_path) as client:
        create_response = client.post(
            "/api/candidate-persons",
            json={
                "name": "Ada Lovelace",
                "platform": "boss",
                "platform_candidate_id": "boss-123",
                "contact_info": {"wechat": "ada"},
                "resume_path": "/resumes/ada.pdf",
            },
        )
        assert create_response.status_code == 201
        candidate = create_response.json()
        assert candidate["name"] == "Ada Lovelace"
        assert candidate["resume_path"] == "/resumes/ada.pdf"

        candidate_id = candidate["id"]
        shadow_application = client.get(f"/api/candidate-applications/{candidate_id}")
        assert shadow_application.status_code == 404

        get_response = client.get(f"/api/candidate-persons/{candidate_id}")
        assert get_response.status_code == 200
        assert get_response.json()["platform_candidate_id"] == "boss-123"

        patch_response = client.patch(
            f"/api/candidate-persons/{candidate_id}",
            json={"contact_info": {"wechat": "ada", "email": "ada@example.com"}},
        )
        assert patch_response.status_code == 200
        assert patch_response.json()["contact_info"]["email"] == "ada@example.com"

        delete_response = client.delete(f"/api/candidate-persons/{candidate_id}")
        assert delete_response.status_code == 204


def test_job_description_and_application_crud(tmp_path):
    with make_client(tmp_path) as client:
        person_response = client.post(
            "/api/candidate-persons",
            json={
                "name": "Grace Hopper",
                "platform": "boss",
                "platform_candidate_id": "boss-person-1",
            },
        )
        assert person_response.status_code == 201
        person_id = person_response.json()["id"]

        job_response = client.post(
            "/api/job-descriptions",
            json={
                "title": "后端工程师",
                "department": "平台研发",
                "location": "上海",
                "description": "负责招聘系统后端能力建设。",
                "requirements": "熟悉 Python/FastAPI。",
                "status": "active",
                "source": "boss",
            },
        )
        assert job_response.status_code == 201
        job_description = job_response.json()
        assert job_description["title"] == "后端工程师"
        job_description_id = job_description["id"]

        application_response = client.post(
            "/api/candidate-applications",
            json={
                "person_id": person_id,
                "job_description_id": job_description_id,
                "platform": "boss",
                "platform_application_id": "boss-app-1",
                "current_status": "discovered",
                "application_window": make_application_window(person_id, job_description_id),
            },
        )
        assert application_response.status_code == 201
        application = application_response.json()
        assert application["person_id"] == person_id
        assert application["job_description_id"] == job_description_id

        application_id = application["id"]
        get_application = client.get(f"/api/candidate-applications/{application_id}")
        assert get_application.status_code == 200
        assert get_application.json()["platform_application_id"] == "boss-app-1"

        patch_application = client.patch(
            f"/api/candidate-applications/{application_id}",
            json={"current_status": "screening_passed"},
        )
        assert patch_application.status_code == 200
        assert patch_application.json()["current_status"] == "screening_passed"
