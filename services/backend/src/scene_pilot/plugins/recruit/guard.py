from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.orm import Session, sessionmaker

from scene_pilot.models.domain import AgentGlobalState
from scene_pilot.plugins.recruit.toolkit import _active_lock, _resolve_application
from scene_pilot.runtime.models import GuardVerdict, Observation


def build_guard_check(
    session_factory: sessionmaker[Session],
) -> Callable[[str, dict[str, object], Observation], Awaitable[GuardVerdict]]:
    async def _guard(tool_name: str, arguments: dict[str, object], observation: Observation) -> GuardVerdict:
        if tool_name == "request_human_approval":
            seed_tool_calls = list(observation.input.seed_tool_calls) if observation.input is not None else []
            seeded_confirmation = any(
                call.name == tool_name and dict(call.arguments or {}) == dict(arguments or {})
                for call in seed_tool_calls
            )
            if not seeded_confirmation:
                return GuardVerdict(
                    allowed=False,
                    reason="pending_human_approval",
                    severity="waiting_human",
                )
        application_id = str(arguments.get("application_id") or "").strip()
        if not application_id and observation.scope_kind == "application":
            application_id = str(observation.scope_ref or "").strip()
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
                    return GuardVerdict(
                        allowed=False,
                        reason="candidate_locked_by_human",
                        severity="warning",
                        metadata={
                            "application_id": lock.application_id,
                            "candidate_person_id": lock.candidate_person_id,
                            "locked_by": lock.locked_by,
                        },
                    )

        external_target = bool(arguments.get("external_target"))
        actor_kind = str(arguments.get("actor_kind") or "").strip()
        if external_target and actor_kind == "assistant":
            with session_factory() as session:
                state = session.get(AgentGlobalState, "singleton")
                if state is None or not state.autonomous_paused:
                    return GuardVerdict(
                        allowed=False,
                        reason="assistant_external_requires_global_pause",
                        severity="warning",
                    )
        return GuardVerdict(allowed=True)

    return _guard
