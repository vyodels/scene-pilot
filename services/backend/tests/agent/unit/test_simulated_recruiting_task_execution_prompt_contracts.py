from __future__ import annotations

from recruit_station.asset_paths import prompt_path
from recruit_station.services.scene_templates import infer_source_surface, source_surface_markers


def test_runtime_task_compiler_prompt_mentions_scene_contract_and_skill_distillation_for_agent_tasks() -> None:
    content = prompt_path("tasks/runtime_task_compiler").read_text(encoding="utf-8")

    assert "scene contract" in content
    assert "tool-surface contract fields" in content
    assert "delegate_scene_context" in content
    assert "browser_target" in content
    assert "computer_target" in content
    assert "target_regions" in content
    assert "action_plan" in content
    assert "artifact_expectations" in content
    assert "local_download_create_attempt" in content
    assert "local_download_attribute" in content
    assert "completed" in content
    assert "timeout" in content
    assert "ambiguous" in content
    assert "page JS" in content
    assert "mock DOM flags" in content
    assert "browser-originated evidence" in content
    assert "source URL" in content
    assert "href" in content
    assert "filename" in content
    assert "startedAt" in content
    assert "business_writeback" in content
    assert "download_attribution" in content
    assert "file_path" in content
    assert "finalUrl" in content
    assert "hid_action.target.host" in content
    assert "skill distillation" in content


def test_resume_collection_prompt_uses_task_execution_terms() -> None:
    content = prompt_path("tasks/resume_collection").read_text(encoding="utf-8")
    legacy_fixed_flow_term = "work" + "flow"

    assert legacy_fixed_flow_term not in content.lower()
    assert "task execution" in content


def test_source_surface_inference_does_not_depend_on_site_specific_markers() -> None:
    markers = tuple(marker.lower() for marker in source_surface_markers("browser_accessible_recruiting_pages"))

    assert "zhipin" not in markers
    assert "boss直聘" not in markers
    assert "boss 直聘" not in markers
    assert infer_source_surface("请打开 BOSS 直聘继续同步。") is None
    assert infer_source_surface("zhipin.com 上有岗位。") is None
    assert infer_source_surface("请从当前招聘平台 JD 页面同步活跃岗位。") == "browser_accessible_recruiting_pages"
