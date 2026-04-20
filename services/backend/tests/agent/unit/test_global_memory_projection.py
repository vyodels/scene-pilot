from __future__ import annotations

import json
import re
from pathlib import Path

from sqlalchemy.orm import Session

from scene_pilot.core.settings import AppSettings
from scene_pilot.db.session import create_engine_from_settings, create_session_factory, initialize_database
from scene_pilot.kernel.update_memory import update_memory
from scene_pilot.memory.global_memory_projection import (
    GLOBAL_MEMORY_PROJECTION_SIGNATURE,
    GLOBAL_MEMORY_SCHEMA_VERSION,
    empty_agent_global_memory_payload,
    project_agent_global_memory,
)
from scene_pilot.models.domain import AgentGlobalMemory, AgentRun, AgentSession, GoalSpec, RecruitAgentProfile
from scene_pilot.runtime.models import Deliberation
from scene_pilot.services.recruit_agent import ensure_global_memory


class CaptureMemoryService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def write(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(dict(kwargs))
        return dict(kwargs)


def _make_session(tmp_path: Path) -> Session:
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'agent-global-memory.db'}",
    )
    engine = create_engine_from_settings(settings)
    initialize_database(engine)
    return create_session_factory(engine)()


def test_update_memory_does_not_project_round_summary_into_global_scope() -> None:
    memory_service = CaptureMemoryService()
    deliberation = Deliberation(
        final_content=json.dumps(
            {
                "status": "blocked",
                "evidence": [
                    "当前浏览器仅有 1 个标签页：CLI Proxy API Management Center",
                    "活动页 URL: http://127.0.0.1:8317/management.html#/auth-files",
                ],
                "next_step": "请先在浏览器中打开并切换到招聘平台的职位列表页。",
            },
            ensure_ascii=False,
        ),
        tool_results=[],
    )

    updates = update_memory(
        deliberation,
        memory_service,
        round_status="blocked",
        scope_kind="global",
        scope_ref="workspace:shared",
        agent_profile_id="agent-1",
        source_kind="autonomous",
        goal_kind="sync_jd_incremental",
        goal_title="同步 JD（增量）",
    )

    assert updates == []
    assert memory_service.calls == []


def test_project_global_memory_only_keeps_long_term_knowledge_fields() -> None:
    projected = project_agent_global_memory(
        summary="已沉淀长期可复用的招聘协作约束。",
        content={
            "facts": ["优先走增量同步，避免全量重复扫描。"],
            "decisions": ["发现高风险外呼前必须先审批。"],
            "open_questions": ["是否需要新增候选人来源白名单。"],
            "risk_flags": ["招聘外链登录态可能周期性失效。"],
            "evidence_refs": [{"source": "operator_note", "id": "note-1"}],
            "confidence": "high",
            "business_snapshot": {"status": "blocked"},
            "next_actions": ["请先在浏览器中打开招聘页面。"],
        },
    )

    assert re.fullmatch(r"agent-global-memory-long-term-[0-9a-f]{12}", GLOBAL_MEMORY_SCHEMA_VERSION)
    assert projected["memory_schema_version"] == GLOBAL_MEMORY_SCHEMA_VERSION
    assert projected["memory_metadata"]["projection_signature"] == GLOBAL_MEMORY_PROJECTION_SIGNATURE
    assert projected["summary"] == "已沉淀长期可复用的招聘协作约束。"
    assert projected["content"] == {
        "facts": ["优先走增量同步，避免全量重复扫描。"],
        "decisions": ["发现高风险外呼前必须先审批。"],
        "open_questions": ["是否需要新增候选人来源白名单。"],
        "next_actions": [],
        "risk_flags": ["招聘外链登录态可能周期性失效。"],
        "evidence_refs": [{"source": "operator_note", "id": "note-1"}],
        "confidence": "high",
    }


def test_project_global_memory_drops_legacy_runtime_projection_payload() -> None:
    projected = project_agent_global_memory(
        content={
            "business_snapshot": {
                "business_action": {
                    "kind": "sync_jd_incremental",
                    "label": "同步 JD（增量）",
                    "status": "blocked",
                },
                "external_platforms": [
                    {
                        "platform": "recruiting_platform",
                        "status": "attention_required",
                        "detail": "当前缺少可用的招聘页面，需要 human 打开正确页面后继续。",
                    }
                ],
            },
            "next_actions": [
                "请先在浏览器中打开并切换到招聘平台的职位列表或职位详情页面，然后继续同步。"
            ],
        }
    )

    assert projected["summary"] == "尚未沉淀长期可复用的全局业务知识。"
    assert projected["content"] == empty_agent_global_memory_payload()["content"]


def test_ensure_global_memory_normalizes_legacy_runtime_detail_payload(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    try:
        profile = RecruitAgentProfile(agent_key="primary", name="Primary", is_primary=True)
        session.add(profile)
        session.flush()
        session.add(
            AgentGlobalMemory(
                agent_profile_id=profile.id,
                memory_schema_version="agent-global-memory-v1",
                summary=json.dumps(
                    {
                        "status": "blocked",
                        "evidence": [
                            "当前浏览器仅有 1 个标签页：CLI Proxy API Management Center",
                            "活动页 URL: http://127.0.0.1:8317/management.html#/auth-files",
                        ],
                        "next_step": "请先在浏览器中打开招聘平台页面。",
                    },
                    ensure_ascii=False,
                ),
                content={
                    "text": json.dumps(
                        {
                            "status": "blocked",
                            "evidence": [
                                "当前浏览器仅有 1 个标签页：CLI Proxy API Management Center",
                                "活动页 URL: http://127.0.0.1:8317/management.html#/auth-files",
                            ],
                            "next_step": "请先在浏览器中打开招聘平台页面。",
                        },
                        ensure_ascii=False,
                    )
                },
                raw_content={
                    "text": json.dumps(
                        {
                            "status": "blocked",
                            "evidence": [
                                "当前浏览器仅有 1 个标签页：CLI Proxy API Management Center",
                                "活动页 URL: http://127.0.0.1:8317/management.html#/auth-files",
                            ],
                            "next_step": "请先在浏览器中打开招聘平台页面。",
                        },
                        ensure_ascii=False,
                    ),
                    "run_pk": "run-1",
                },
            )
        )
        session.commit()

        memory = ensure_global_memory(session, agent_profile_id=profile.id)

        assert memory.memory_schema_version == GLOBAL_MEMORY_SCHEMA_VERSION
        assert memory.summary == "尚未沉淀长期可复用的全局业务知识。"
        assert memory.memory_metadata["projection_signature"] == GLOBAL_MEMORY_PROJECTION_SIGNATURE
        serialized = json.dumps(memory.content, ensure_ascii=False)
        assert "标签页" not in serialized
        assert "management.html" not in serialized
        assert "请先在浏览器中打开招聘平台页面" not in serialized
        assert memory.content == empty_agent_global_memory_payload()["content"]
    finally:
        session.close()


def test_ensure_global_memory_reprojects_degraded_current_version_payload_from_run_context(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    try:
        profile = RecruitAgentProfile(agent_key="primary", name="Primary", is_primary=True)
        session.add(profile)
        session.flush()

        agent_session = AgentSession(agent_profile_id=profile.id, session_key="primary")
        session.add(agent_session)
        session.flush()

        goal = GoalSpec(
            agent_profile_id=profile.id,
            title="同步 JD（增量）",
            goal_text="继续执行 JD 增量同步",
            goal_kind="sync_jd_incremental",
            status="active",
        )
        session.add(goal)
        session.flush()

        run = AgentRun(
            session_id=agent_session.id,
            goal_spec_id=goal.id,
            run_type="sync_jd_incremental",
            status="blocked",
            runtime_metadata={"conversation_id": "conv-1"},
        )
        session.add(run)
        session.flush()

        payload = empty_agent_global_memory_payload()
        payload["summary"] = "业务动作状态：unknown。"
        payload["content"]["facts"] = ["最近一次业务动作：业务动作，状态 unknown。"]
        payload["content"]["confidence"] = "medium"

        session.add(
            AgentGlobalMemory(
                agent_profile_id=profile.id,
                memory_schema_version=GLOBAL_MEMORY_SCHEMA_VERSION,
                summary=payload["summary"],
                content=payload["content"],
                raw_content={
                    **dict(payload["raw_content"] or {}),
                    "run_pk": run.id,
                    "conversation_pk": "conv-1",
                    "facts": ["最近一次业务动作：业务动作，状态 unknown。"],
                },
                memory_metadata={
                    "scope": "agent_global",
                    "projection_kind": "long_term_memory",
                    "abstraction_level": "long_term_business",
                    "schema_namespace": "agent-global-memory-long-term",
                    "projection_signature": GLOBAL_MEMORY_PROJECTION_SIGNATURE,
                    "source_kind": "autonomous_summary",
                    "run_pk": run.id,
                    "conversation_pk": "conv-1",
                    "normalized_from": "agent-global-memory-business-legacy",
                    "last_business_action": "unknown",
                    "last_business_status": "unknown",
                },
            )
        )
        session.commit()

        memory = ensure_global_memory(session, agent_profile_id=profile.id)

        assert memory.memory_schema_version == GLOBAL_MEMORY_SCHEMA_VERSION
        assert memory.summary == "尚未沉淀长期可复用的全局业务知识。"
        assert memory.content == empty_agent_global_memory_payload()["content"]
        assert memory.memory_metadata["normalized_from"] == GLOBAL_MEMORY_SCHEMA_VERSION
    finally:
        session.close()
