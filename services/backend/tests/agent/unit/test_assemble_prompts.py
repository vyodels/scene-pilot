from __future__ import annotations

from scene_pilot.kernel.assemble import assemble_messages
from scene_pilot.runtime.models import GoalRef, Observation


def test_assemble_messages_includes_job_description_sync_prompt() -> None:
    goal = GoalRef(
        goal_id="goal-sync-jd",
        scope_kind="global",
        scope_ref="agent-1",
        title="同步 JD（初始）",
        goal_text="同步当前招聘平台上的岗位信息到本地工作区。",
        constraints={
            "goal_kind": "sync_jd_initial",
            "target_entity": "job_description",
        },
    )
    observation = Observation(
        world_snapshot={"page": "jobs"},
        scope_kind="global",
        scope_ref="agent-1",
        recent_events=[],
        available_tools=["list_job_descriptions", "upsert_job_description"],
        available_skills=[],
        available_mcps=[],
        hash="obs-sync-jd",
    )

    messages = assemble_messages(goal, observation)

    assert messages[0].role == "system"
    assert "任务：同步 JD" in messages[0].content
    assert "upsert_job_description" in messages[0].content
    assert "只同步当前仍处于活跃招聘中的 JD" in messages[0].content
    assert "同步时应尽量获取 JD 详细信息" in messages[0].content
    assert "普通浏览器（非 AI 模式浏览器）" in messages[0].content
    assert "当前目标" in messages[0].content
    assert "同步当前招聘平台上的岗位信息到本地工作区" in messages[0].content
    assert '"goal_kind": "sync_jd_initial"' in messages[-1].content
