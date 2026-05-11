from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.orm import Session, sessionmaker

from recruit_agent.models.domain import AgentGlobalState
from recruit_agent.plugins.recruit.toolkit import _active_lock, _resolve_application


def build_guard_check(
    session_factory: sessionmaker[Session],
) -> Callable[[str, dict[str, object], dict[str, object]], Awaitable[dict[str, object]]]:
    async def _guard(tool_name: str, arguments: dict[str, object], context: dict[str, object]) -> dict[str, object]:
        if tool_name == "request_human_approval":
            if not bool(arguments.get("approved_by_operator") or arguments.get("approved")):
                return {"allowed": False, "reason": "pending_human_approval", "severity": "waiting_human"}
        application_id = str(arguments.get("application_id") or "").strip()
        if not application_id and context.get("scope_kind") == "application":
            application_id = str(context.get("scope_ref") or "").strip()
        if not application_id:
            candidate_person_id = str(arguments.get("candidate_person_id") or "").strip()
            job_description_id = str(arguments.get("job_description_id") or "").strip()
            if candidate_person_id and job_description_id:
                with session_factory() as session:
                    try:
                        application = _resolve_application(
                            session,
                            candidate_person_id=candidate_person_id,
                            job_description_id=job_description_id,
                        )
                    except (KeyError, ValueError):
                        application = None
                    if application is not None:
                        application_id = str(application.candidate_application_id or "").strip()
        if tool_name not in {"release_candidate", "list_locked_candidates"} and application_id:
            with session_factory() as session:
                lock = _active_lock(session, application_id)
                if lock is not None:
                    return {
                        "allowed": False,
                        "reason": "candidate_locked_by_human",
                        "severity": "warning",
                        "metadata": {
                            "application_id": lock.application_id,
                            "candidate_person_id": lock.candidate_person_id,
                            "locked_by": lock.locked_by,
                        },
                    }

        external_target = bool(arguments.get("external_target"))
        actor_kind = str(arguments.get("actor_kind") or "").strip()
        if external_target and actor_kind == "assistant":
            with session_factory() as session:
                state = session.get(AgentGlobalState, "singleton")
                if state is None or not state.autonomous_paused:
                    return {
                        "allowed": False,
                        "reason": "assistant_external_requires_global_pause",
                        "severity": "warning",
                    }
        return {"allowed": True}

    return _guard
