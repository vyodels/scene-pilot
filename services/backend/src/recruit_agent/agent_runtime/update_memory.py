from __future__ import annotations

from typing import cast
from uuid import uuid4

from typing import Any

from recruit_agent.agent_runtime.models import Deliberation


def update_memory(
    deliberation: Deliberation,
    memory_service: Any | None = None,
    *,
    round_status: str | None = None,
    learning_writer: Any | None = None,
    scope_kind: str | None = None,
    scope_ref: str | None = None,
    agent_profile_id: str | None = None,
    run_pk: str | None = None,
    conversation_pk: str | None = None,
    source_kind: str = "autonomous",
    goal_kind: str | None = None,
    goal_title: str | None = None,
) -> list[dict[str, Any]]:
    if memory_service is None and learning_writer is None:
        return []
    if round_status == "cancelled":
        return []
    writings: list[dict[str, Any]] = []
    for result in deliberation.tool_results:
        if result.tool_name == "record_learning" and not result.is_error:
            arguments = dict(result.arguments or {})
            learning_payload = _record_learning(learning_writer, arguments)
            writings.append({"tool_name": result.tool_name, "arguments": arguments, "learning": learning_payload})
    if (
        memory_service is not None
        and scope_kind is not None
        and scope_ref is not None
        and agent_profile_id is not None
        and deliberation.final_content
    ):
        normalized_scope_kind = str(scope_kind).strip().lower()
        if normalized_scope_kind != "global":
            memory_item_id = f"{source_kind}-{uuid4().hex}"
            memory_summary = deliberation.final_content[:240]
            memory_content = {
                "text": deliberation.final_content,
                "tool_results": [result.output for result in deliberation.tool_results if not result.is_error],
                "run_pk": run_pk,
                "conversation_pk": conversation_pk,
                "source_kind": source_kind,
            }
            memory_record = memory_service.write(
                scope_kind=scope_kind,
                scope_ref=scope_ref,
                agent_profile_id=agent_profile_id,
                memory_item_id=memory_item_id,
                kind=f"{source_kind}_summary",
                index_name=f"{source_kind}_summary",
                index_description="Latest durable summary captured from the shared kernel outcome.",
                summary=memory_summary,
                content=memory_content,
                confidence=0.7,
                trust_level="agent_reported",
            )
            writings.append({"memory": memory_record})
    if learning_writer is not None and deliberation.final_content:
        payload = learning_writer.record_learning(
            content=deliberation.final_content,
            tags=[source_kind, scope_kind or "unknown"],
            promote=False,
        )
        writings.append({"summary_learning": payload})
    return writings


def _record_learning(learning_writer: Any | None, arguments: dict[str, Any]) -> dict[str, Any] | None:
    if learning_writer is None:
        return None
    payload = dict(arguments.get("payload") or {})
    content = str(payload.get("content") or arguments.get("kind") or "record_learning")
    tags = [str(tag) for tag in list(payload.get("tags") or []) if str(tag).strip()]
    result = learning_writer.record_learning(
        content=content,
        tags=tags or ["record_learning"],
        promote=bool(payload.get("promote") or False),
        skill_name=str(payload.get("skill_name") or "") or None,
        trial_metrics=dict(payload.get("trial_metrics") or {}),
        job_description_id=str(payload.get("job_description_id") or "") or None,
        artifact_kind=str(payload.get("artifact_kind") or "") or None,
    )
    return cast(dict[str, Any], result)
