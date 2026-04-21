from __future__ import annotations

from recruit_agent.core.settings import AppSettings
from recruit_agent.plugins.recruit.toolkit import list_job_descriptions, upsert_job_description
from recruit_agent.services.container import AppContainer


def _build_container(tmp_path) -> AppContainer:
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'recruit-job-tools.db'}",
        provider_config={},
    )
    return AppContainer.build(settings)


def test_upsert_job_description_creates_and_updates_same_platform_identity(tmp_path) -> None:
    container = _build_container(tmp_path)
    assert "list_job_descriptions" in container.tool_registry.tools
    assert "upsert_job_description" in container.tool_registry.tools
    tool = container.tool_registry.tools["upsert_job_description"]
    assert {"company_name", "employment_type", "experience_requirement", "education_requirement"} <= set(
        tool.parameters["properties"]
    )
    assert {"compensation_text", "summary", "benefit_tags", "detail_metadata"} <= set(tool.parameters["properties"])

    created = upsert_job_description(
        container.session_factory,
        title="Backend Engineer",
        company_name="Recruit Agent",
        department="Platform",
        location="Shanghai",
        employment_type="full_time",
        compensation_text="30k-45k x 14",
        experience_requirement="5+ years in backend or platform engineering.",
        education_requirement="Bachelor degree or above.",
        summary="Own the backend foundation for recruiting workflows.",
        platform="generic_recruiting_site",
        external_id="job-001",
        external_url="https://example.test/jobs/001",
        description="Build agent runtime services.",
        requirements="Strong Python and distributed systems fundamentals.",
        benefit_tags=["Lunch", "Remote-friendly", "Lunch"],
        detail_metadata={"language": "zh-CN", "team_size": "12"},
        sync_metadata={"detail_sync": "full"},
    )

    updated = upsert_job_description(
        container.session_factory,
        title="Backend Engineer",
        platform="generic_recruiting_site",
        external_id="job-001",
        summary="Own the backend foundation for recruiting and agent workflows.",
        description="Build agent runtime services and APIs.",
    )

    assert created["action"] == "created"
    assert updated["action"] == "updated"
    assert created["job_description"]["job_description_id"] == updated["job_description"]["job_description_id"]
    assert updated["job_description"]["company_name"] == "Recruit Agent"
    assert updated["job_description"]["employment_type"] == "full_time"
    assert updated["job_description"]["compensation_text"] == "30k-45k x 14"
    assert updated["job_description"]["experience_requirement"] == "5+ years in backend or platform engineering."
    assert updated["job_description"]["education_requirement"] == "Bachelor degree or above."
    assert updated["job_description"]["benefit_tags"] == ["Lunch", "Remote-friendly"]
    assert updated["job_description"]["detail_metadata"] == {"language": "zh-CN", "team_size": "12"}
    assert updated["job_description"]["summary"] == "Own the backend foundation for recruiting and agent workflows."
    assert updated["job_description"]["description"] == "Build agent runtime services and APIs."
    assert updated["platform_identity"]["sync_metadata"] == {"detail_sync": "full"}

    listed = list_job_descriptions(container.session_factory)
    assert len(listed) == 1
    assert listed[0]["title"] == "Backend Engineer"
    assert listed[0]["platform_identities"][0]["external_id"] == "job-001"
    assert listed[0]["platform_identities"][0]["sync_metadata"] == {"detail_sync": "full"}
