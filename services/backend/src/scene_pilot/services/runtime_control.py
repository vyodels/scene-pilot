from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from scene_pilot.core.settings import AppSettings
from scene_pilot.repositories import (
    AgentRunCheckpointRepository,
    AgentRunRepository,
    AgentRuntimeEventRepository,
    AgentSessionRepository,
    AgentWorkItemRepository,
    CandidateRepository,
    RecruitAgentProfileRepository,
    TaskQueueRepository,
)
from scene_pilot.scheduler.queue import TaskEnvelope
from scene_pilot.scheduler.scheduler import TaskDeferred
from scene_pilot.services.events import EventStreamService
from scene_pilot.services.recruit_agent import ensure_primary_recruit_agent_profile


TERMINAL_RUN_STATUSES = {"completed", "failed", "cancelled", "rejected"}


class RuntimeControlService:
    def __init__(
        self,
        session: Session,
        *,
        settings: AppSettings,
        live_events: EventStreamService | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.live_events = live_events

    def ensure_run_for_task(self, task: TaskEnvelope) -> dict[str, Any]:
        session_record = self._ensure_session()
        lane = self.resolve_lane(task)
        goal_spec_id = str(task.metadata.get("goal_spec_id") or task.payload.get("goal_id") or "").strip() or None
        candidate = CandidateRepository(self.session).resolve(task.candidate_id) if task.candidate_id else None
        run_repo = AgentRunRepository(self.session)
        work_item_repo = AgentWorkItemRepository(self.session)

        existing_run_id = str(task.metadata.get("agent_run_id") or "").strip()
        run = run_repo.get(existing_run_id) if existing_run_id else None
        if run is None and candidate is not None and lane == "candidate":
            run = run_repo.latest_open_for_candidate(session_id=session_record.id, candidate_id=candidate.id, lane=lane)
        if run is None:
            run = run_repo.create(
                {
                    "session_id": session_record.id,
                    "goal_spec_id": goal_spec_id,
                    "candidate_id": candidate.id if candidate is not None else None,
                    "jd_id": candidate.jd_id if candidate is not None else None,
                    "platform": task.platform or (candidate.platform if candidate is not None else "site"),
                    "lane": lane,
                    "run_type": task.task_type,
                    "status": "queued",
                    "priority": task.priority,
                    "queue_task_id": task.task_id,
                    "runtime_metadata": {
                        "task_ids": [task.task_id],
                        "task_types": [task.task_type],
                        "requested_by": task.metadata.get("requested_by"),
                    },
                }
            )
        else:
            metadata = dict(run.runtime_metadata or {})
            metadata["task_ids"] = list(dict.fromkeys([*list(metadata.get("task_ids") or []), task.task_id]))
            metadata["task_types"] = list(dict.fromkeys([*list(metadata.get("task_types") or []), task.task_type]))
            metadata["requested_by"] = task.metadata.get("requested_by") or metadata.get("requested_by")
            run = run_repo.update(
                run,
                {
                    "priority": max(int(run.priority or 0), int(task.priority or 0)),
                    "queue_task_id": task.task_id,
                    "goal_spec_id": goal_spec_id or run.goal_spec_id,
                    "runtime_metadata": metadata,
                },
            )

        work_item = work_item_repo.by_queue_task_id(task.task_id)
        if work_item is None:
            work_item = work_item_repo.create(
                {
                    "session_id": session_record.id,
                    "run_id": run.id,
                    "queue_task_id": task.task_id,
                    "goal_spec_id": goal_spec_id,
                    "candidate_id": candidate.id if candidate is not None else None,
                    "platform": task.platform or (candidate.platform if candidate is not None else "site"),
                    "lane": lane,
                    "item_type": task.task_type,
                    "status": "queued",
                    "priority": task.priority,
                    "dedupe_key": self._work_item_dedupe_key(task=task, candidate_id=candidate.id if candidate is not None else None, lane=lane),
                    "payload": {
                        "task_snapshot": self._task_snapshot(task),
                        "payload": dict(task.payload or {}),
                        "metadata": dict(task.metadata or {}),
                    },
                    "scheduled_for": task.due_at,
                }
            )
        else:
            payload = dict(work_item.payload or {})
            if not isinstance(payload.get("task_snapshot"), dict):
                payload["task_snapshot"] = self._task_snapshot(task)
                work_item = work_item_repo.update(work_item, {"payload": payload})

        task.metadata["agent_session_id"] = session_record.id
        task.metadata["agent_run_id"] = run.id
        task.metadata["agent_work_item_id"] = work_item.id
        if goal_spec_id:
            task.metadata["goal_spec_id"] = goal_spec_id
            session_record.current_goal_id = goal_spec_id
            self.session.commit()
        self.publish_event(
            session_id=session_record.id,
            run_id=run.id,
            candidate_id=candidate.id if candidate is not None else None,
            level="info",
            source="runtime_control",
            event_type="task_enqueued",
            message=f"Queued {task.task_type} into {lane} lane.",
            payload={"task_id": task.task_id, "work_item_id": work_item.id},
        )
        return {"session_id": session_record.id, "run_id": run.id, "work_item_id": work_item.id, "lane": lane}

    def begin_run(self, task: TaskEnvelope) -> dict[str, Any]:
        run_id = str(task.metadata.get("agent_run_id") or "").strip()
        if not run_id:
            raise TaskDeferred("Runtime run metadata missing.")
        run_repo = AgentRunRepository(self.session)
        work_item_repo = AgentWorkItemRepository(self.session)
        run = run_repo.get(run_id)
        if run is None:
            raise TaskDeferred("Runtime run not found.")

        session_id = run.session_id
        session_record = AgentSessionRepository(self.session).get(session_id)
        if session_record is None:
            raise TaskDeferred("Runtime session not found.")

        candidate_id = run.candidate_id
        if candidate_id:
            conflict = run_repo.conflicting_candidate_run(session_id=session_id, candidate_id=candidate_id, exclude_run_id=run.id)
            if conflict is not None:
                raise TaskDeferred(f"Candidate {candidate_id} already has an active run.")

        max_concurrent = self._resolve_concurrent_limit(platform=run.platform)
        running_count = run_repo.running_count(session_id=session_id, platform=None)
        if running_count >= max_concurrent and run.status != "running":
            raise TaskDeferred(f"Concurrent run limit reached for {run.platform}.")

        now = datetime.now(timezone.utc)
        run_repo.update(
            run,
            {
                "status": "running",
                "started_at": run.started_at or now,
                "finished_at": None,
                "blocked_reason": None,
                "last_error": None,
                "checkpoint_status": "none",
            },
        )
        session_record.status = "active"
        session_record.current_lane = run.lane
        session_record.last_active_at = now
        session_record.last_run_at = now
        self.session.commit()

        work_item_id = str(task.metadata.get("agent_work_item_id") or "").strip()
        work_item = work_item_repo.get(work_item_id) if work_item_id else None
        if work_item is not None:
            work_item_repo.update(work_item, {"status": "running", "claimed_at": now, "last_error": None})

        self.publish_event(
            session_id=session_id,
            run_id=run.id,
            candidate_id=run.candidate_id,
            level="info",
            source="runtime_control",
            event_type="run_started",
            message=f"Started {run.run_type} run.",
            payload={"task_id": task.task_id, "lane": run.lane},
        )
        return {"session_id": session_id, "run_id": run.id, "lane": run.lane}

    def attach_context_manifest(self, *, run_id: str, context_manifest: dict[str, Any]) -> None:
        run = AgentRunRepository(self.session).get(run_id)
        if run is None:
            return
        AgentRunRepository(self.session).update(run, {"context_manifest": context_manifest})

    def finalize_run(
        self,
        *,
        task: TaskEnvelope,
        status: str,
        success: bool,
        blocked_reason: str | None = None,
        last_error: str | None = None,
        runtime_metadata_patch: dict[str, Any] | None = None,
    ) -> None:
        run_id = str(task.metadata.get("agent_run_id") or "").strip()
        if not run_id:
            return
        run_repo = AgentRunRepository(self.session)
        work_item_repo = AgentWorkItemRepository(self.session)
        run = run_repo.get(run_id)
        if run is None:
            return
        now = datetime.now(timezone.utc)
        final_status = status
        checkpoint_status = run.checkpoint_status
        if status == "waiting_human":
            final_status = "waiting_human"
            checkpoint_status = "open"
        elif status in {"rejected", "cancelled"}:
            checkpoint_status = "resolved"
        elif success:
            final_status = "completed"
            checkpoint_status = "none"

        metadata = dict(run.runtime_metadata or {})
        if runtime_metadata_patch:
            metadata.update(runtime_metadata_patch)
        updated = run_repo.update(
            run,
            {
                "status": final_status,
                "finished_at": None if final_status in {"running", "queued", "waiting_human", "waiting_candidate"} else now,
                "blocked_reason": blocked_reason,
                "last_error": last_error,
                "checkpoint_status": checkpoint_status,
                "runtime_metadata": metadata,
            },
        )

        work_item_id = str(task.metadata.get("agent_work_item_id") or "").strip()
        work_item = work_item_repo.get(work_item_id) if work_item_id else None
        if work_item is not None:
            work_item_repo.update(
                work_item,
                {
                    "status": final_status if final_status in {"waiting_human", "waiting_candidate"} else ("completed" if success else "failed"),
                    "completed_at": now if final_status not in {"waiting_human", "waiting_candidate"} else None,
                    "last_error": last_error or blocked_reason,
                },
            )

        self.publish_event(
            session_id=updated.session_id,
            run_id=updated.id,
            candidate_id=updated.candidate_id,
            level="info" if success else "warning",
            source="runtime_control",
            event_type="run_finalized",
            message=f"Run finished with status {final_status}.",
            payload={"task_id": task.task_id, "blocked_reason": blocked_reason, "last_error": last_error},
        )

    def create_checkpoint(
        self,
        *,
        task: TaskEnvelope,
        checkpoint_kind: str,
        title: str,
        summary: str | None,
        payload: dict[str, Any],
        approval_id: str | None = None,
    ) -> None:
        run_id = str(task.metadata.get("agent_run_id") or "").strip()
        session_id = str(task.metadata.get("agent_session_id") or "").strip()
        if not run_id or not session_id:
            return
        checkpoint_repo = AgentRunCheckpointRepository(self.session)
        existing = checkpoint_repo.open_for_run(run_id)
        if existing is None:
            checkpoint_repo.create(
                {
                    "session_id": session_id,
                    "run_id": run_id,
                    "candidate_id": task.candidate_id,
                    "approval_id": approval_id,
                    "checkpoint_kind": checkpoint_kind,
                    "status": "open",
                    "title": title,
                    "summary": summary,
                    "payload": payload,
                }
            )
        run = AgentRunRepository(self.session).get(run_id)
        if run is not None:
            AgentRunRepository(self.session).update(
                run,
                {
                    "status": "waiting_human" if checkpoint_kind == "approval" else "blocked",
                    "checkpoint_status": "open",
                    "blocked_reason": summary,
                },
            )

    def resolve_checkpoint_for_approval(self, *, approval_id: str, status: str, reviewer: str, notes: str | None) -> None:
        checkpoint_repo = AgentRunCheckpointRepository(self.session)
        checkpoint = checkpoint_repo.by_approval(approval_id)
        if checkpoint is None:
            return
        checkpoint_repo.update(
            checkpoint,
            {
                "status": "resolved" if status == "approved" else "rejected",
                "resolved_by": reviewer,
                "resolved_at": datetime.now(timezone.utc),
            },
        )
        run = AgentRunRepository(self.session).get(checkpoint.run_id)
        if run is None:
            return
        AgentRunRepository(self.session).update(
            run,
            {
                "status": "queued" if status == "approved" else "rejected",
                "checkpoint_status": "resolved",
                "blocked_reason": None if status == "approved" else (notes or checkpoint.summary),
                "last_error": None if status == "approved" else (notes or checkpoint.summary),
            },
        )
        self.publish_event(
            session_id=checkpoint.session_id,
            run_id=checkpoint.run_id,
            candidate_id=checkpoint.candidate_id,
            level="info",
            source="approval",
            event_type="checkpoint_resolved",
            message=f"Checkpoint resolved with status {status}.",
            payload={"approval_id": approval_id, "reviewer": reviewer},
        )

    def publish_event(
        self,
        *,
        session_id: str,
        run_id: str | None,
        candidate_id: str | None,
        level: str,
        source: str,
        event_type: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        AgentRuntimeEventRepository(self.session).create(
            {
                "session_id": session_id,
                "run_id": run_id,
                "candidate_id": candidate_id,
                "level": level,
                "source": source,
                "event_type": event_type,
                "message": message,
                "payload": dict(payload or {}),
            }
        )
        if self.live_events is not None:
            self.live_events.publish(level, source, message, session_id=session_id, run_id=run_id, candidate_id=candidate_id, event_type=event_type, **dict(payload or {}))

    def recover_running_runs(self) -> int:
        repo = AgentRunRepository(self.session)
        work_item_repo = AgentWorkItemRepository(self.session)
        queue_repo = TaskQueueRepository(self.session)
        runs = repo.list_recoverable(limit=5000)
        recovered = 0
        for run in runs:
            work_items = work_item_repo.list_for_run(run.id, limit=200, offset=0)
            queue_task_id = str(run.queue_task_id or "").strip()
            queue_record = queue_repo.get(queue_task_id) if queue_task_id else None
            recovery_mode = "requeued"

            if queue_record is None or queue_record.status in {"completed", "failed"}:
                restored = self._restore_queue_task_for_run(run=run, work_items=work_items)
                if restored is None:
                    recovery_mode = "manual_recovery_required"
                else:
                    queue_task_id = restored
                    recovery_mode = "rebuilt_queue_task"
                    queue_record = queue_repo.get(queue_task_id)

            next_status = "queued" if queue_record is not None and queue_record.status in {"pending", "running"} else "resumable"
            recovery_message = (
                "Recovered after local runtime restart and returned to queue."
                if next_status == "queued"
                else "Recovered after local runtime restart; manual resume may be required."
            )
            metadata = dict(run.runtime_metadata or {})
            recovery_history = list(metadata.get("recovery_history") or [])
            recovery_history.append(
                {
                    "at": datetime.now(timezone.utc).isoformat(),
                    "previous_status": run.status,
                    "status": next_status,
                    "queue_task_id": queue_task_id or None,
                    "queue_status": queue_record.status if queue_record is not None else None,
                    "mode": recovery_mode,
                }
            )
            metadata["recovery_history"] = recovery_history[-20:]
            metadata["recovery_required"] = next_status == "resumable"
            metadata["recovery_mode"] = recovery_mode

            repo.update(
                run,
                {
                    "status": next_status,
                    "queue_task_id": queue_task_id or run.queue_task_id,
                    "finished_at": None,
                    "blocked_reason": None,
                    "last_error": recovery_message,
                    "runtime_metadata": metadata,
                },
            )
            for work_item in work_items:
                if work_item.status not in {"completed", "failed", "rejected"}:
                    work_item_repo.update(
                        work_item,
                        {
                            "status": "queued" if next_status == "queued" else "resumable",
                            "claimed_at": None,
                            "completed_at": None,
                            "last_error": recovery_message,
                        },
                    )

            self.publish_event(
                session_id=run.session_id,
                run_id=run.id,
                candidate_id=run.candidate_id,
                level="warning",
                source="runtime_recovery",
                event_type="run_recovered",
                message=recovery_message,
                payload={
                    "queue_task_id": queue_task_id or None,
                    "queue_status": queue_record.status if queue_record is not None else None,
                    "mode": recovery_mode,
                },
            )
            recovered += 1
        return recovered

    def _ensure_session(self):
        profile = RecruitAgentProfileRepository(self.session).primary() or ensure_primary_recruit_agent_profile(self.session)
        repo = AgentSessionRepository(self.session)
        existing = repo.by_agent_and_key(agent_profile_id=profile.id, session_key="primary")
        if existing is not None:
            return existing
        return repo.create(
            {
                "agent_profile_id": profile.id,
                "session_key": "primary",
                "status": "active",
                "runtime_metadata": {"agent_key": profile.agent_key},
            }
        )

    def resolve_lane(self, task: TaskEnvelope) -> str:
        explicit = str(task.metadata.get("lane") or task.payload.get("lane") or "").strip().lower()
        if explicit in {"agent", "candidate"}:
            return explicit
        return "candidate" if task.candidate_id else "agent"

    def _resolve_concurrent_limit(self, *, platform: str) -> int:
        config = self.settings.provider_config or {}
        _ = platform
        return max(1, int(config.get("max_concurrent_runs", 1) or 1))

    def _work_item_dedupe_key(self, *, task: TaskEnvelope, candidate_id: str | None, lane: str) -> str:
        parts = [lane, task.task_type, task.workflow_node_id or "", candidate_id or ""]
        return ":".join(part for part in parts if part)

    def _task_snapshot(self, task: TaskEnvelope) -> dict[str, Any]:
        return {
            "task_id": task.task_id,
            "task_type": task.task_type,
            "priority": task.priority,
            "payload": dict(task.payload or {}),
            "metadata": dict(task.metadata or {}),
            "candidate_id": task.candidate_id,
            "workflow_id": task.workflow_id,
            "workflow_node_id": task.workflow_node_id,
            "platform": task.platform,
            "attempts": task.attempts,
            "due_at": task.due_at.isoformat() if task.due_at else None,
            "created_at": task.created_at.isoformat(),
        }

    def _restore_queue_task_for_run(self, *, run, work_items: list[Any]) -> str | None:
        queue_repo = TaskQueueRepository(self.session)
        for work_item in work_items:
            payload = dict(work_item.payload or {})
            snapshot = dict(payload.get("task_snapshot") or {})
            task_id = str(snapshot.get("task_id") or work_item.queue_task_id or run.queue_task_id or "").strip()
            task_type = str(snapshot.get("task_type") or work_item.item_type or run.run_type or "").strip()
            if not task_id or not task_type:
                continue
            queue_payload = self._queue_payload_from_snapshot(snapshot=snapshot, run=run, work_item=work_item)
            queue_repo.enqueue(
                task_id=task_id,
                task_type=task_type,
                priority=int(snapshot.get("priority") or work_item.priority or run.priority or 100),
                payload=queue_payload,
                status="pending",
                scheduled_for=work_item.scheduled_for,
                attempts=int(snapshot.get("attempts") or 0),
            )
            return task_id
        return None

    def _queue_payload_from_snapshot(self, *, snapshot: dict[str, Any], run, work_item) -> dict[str, Any]:
        metadata = dict(snapshot.get("metadata") or {})
        metadata.setdefault("agent_session_id", run.session_id)
        metadata.setdefault("agent_run_id", run.id)
        metadata.setdefault("agent_work_item_id", work_item.id)
        return {
            "payload": dict(snapshot.get("payload") or {}),
            "platform": str(snapshot.get("platform") or work_item.platform or run.platform or "site"),
            "workflow_id": snapshot.get("workflow_id"),
            "workflow_node_id": snapshot.get("workflow_node_id"),
            "candidate_id": snapshot.get("candidate_id") or work_item.candidate_id or run.candidate_id,
            "due_at": snapshot.get("due_at"),
            "created_at": snapshot.get("created_at") or datetime.now(timezone.utc).isoformat(),
            "metadata": metadata,
        }
