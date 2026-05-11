from __future__ import annotations

from recruit_agent.asset_paths import prompt_path
from recruit_agent.agent_runtime.assemble import assemble_messages
from recruit_agent.agent_runtime.models import GoalRef, Observation
from recruit_agent.services.scene_templates import infer_source_surface, source_surface_markers


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
    assert "browser_locate_download" in content
    assert "in_progress" in content
    assert "page JS" in content
    assert "mock DOM flags" in content
    assert "browser-originated evidence" in content
    assert "source URL" in content
    assert "href" in content
    assert "filename" in content
    assert "startedAfter" in content
    assert "waitMs" in content
    assert "5000" in content
    assert "business_writeback" in content
    assert "browser_download" in content
    assert "file_path" in content
    assert "finalUrl" in content
    assert "hid_action.target.host" in content
    assert "skill distillation" in content


def test_job_and_candidate_prompts_require_business_level_scene_results() -> None:
    cases = [
        (
            "sync_jd_incremental",
            "job_description",
            "同步 JD（增量）",
            "delegate_scene_context",
            "upsert_job_description",
        ),
        (
            "candidate_discovery",
            "candidate",
            "发现候选人",
            "delegate_scene_context",
            "upsert_candidate",
        ),
    ]

    for goal_kind, target_entity, title, scene_marker, write_marker in cases:
        messages = assemble_messages(
            GoalRef(
                goal_id=f"goal-{goal_kind}",
                scope_kind="job",
                scope_ref="job-1",
                title=title,
                goal_text=title,
                constraints={"goal_kind": goal_kind, "target_entity": target_entity},
            ),
            Observation(scope_kind="job", scope_ref="job-1"),
        )
        system_content = messages[0].content
        assert scene_marker in system_content
        assert write_marker in system_content
        assert "业务级" in system_content
        assert "tool surface" in system_content.lower()
        assert "browser_target" in system_content
        assert "target_regions" in system_content
        assert "action_plan" in system_content
        assert "skill" in system_content.lower()


def test_resume_collection_prompt_requires_artifact_verification_and_workspace_attach() -> None:
    messages = assemble_messages(
        GoalRef(
            goal_id="goal-resume-1",
            scope_kind="job",
            scope_ref="job-1",
            title="收集简历",
            goal_text="收集当前候选人的简历并完成归档。",
            constraints={"goal_kind": "resume_collection", "target_entity": "resume_artifact"},
        ),
        Observation(scope_kind="job", scope_ref="job-1"),
    )

    system_content = messages[0].content
    assert "delegate_scene_context" in system_content
    assert "tool-surface payload" in system_content
    assert "browser_target" in system_content
    assert "computer_target" in system_content
    assert "target_regions" in system_content
    assert "action_plan" in system_content
    assert "artifact_expectations" in system_content
    assert "browser_locate_download" in system_content
    assert "in_progress" in system_content
    assert "page JS" in system_content
    assert "mock DOM flags" in system_content
    assert "browser-originated evidence" in system_content
    assert "source URL" in system_content
    assert "href" in system_content
    assert "filename" in system_content
    assert "startedAfter" in system_content
    assert "waitMs" in system_content
    assert "5000" in system_content
    assert "business_writeback" in system_content
    assert "browser_download" in system_content
    assert "file_path" in system_content
    assert "finalUrl" in system_content
    assert "target.host" in system_content
    assert "attach_resume_artifact" in system_content
    assert "path" in system_content
    assert "format" in system_content
    assert "skill" in system_content.lower()


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
