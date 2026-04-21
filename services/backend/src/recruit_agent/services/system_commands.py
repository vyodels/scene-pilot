from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import subprocess
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from recruit_agent.models import ApprovalItem
from recruit_agent.repositories import ApprovalRepository
from recruit_agent.services.events import EventStreamService
from recruit_agent.services.feature_flags import FeatureFlagService

DEFAULT_SYSTEM_COMMAND_WHITELIST: tuple[tuple[str, ...], ...] = (
    ("python3", "-m", "pytest"),
    ("npm", "run", "desktop:typecheck"),
    ("npm", "run", "desktop:build"),
    ("node", "scripts/prepare-desktop-package.mjs"),
)


class SystemCommandError(RuntimeError):
    pass


class SystemCommandDisabledError(SystemCommandError):
    pass


class SystemCommandPolicyError(SystemCommandError):
    pass


class SystemCommandApprovalError(SystemCommandError):
    pass


@dataclass(slots=True)
class SystemCommandService:
    session_factory: sessionmaker[Session]
    flags: FeatureFlagService
    events: EventStreamService
    whitelist: tuple[tuple[str, ...], ...] = DEFAULT_SYSTEM_COMMAND_WHITELIST
    execution_enabled: bool = False
    default_timeout_seconds: int = 300

    def policy_snapshot(self) -> dict[str, Any]:
        return {
            "enabled": self.flags.is_enabled("skills.system_command"),
            "approvalRequired": True,
            "executionEnabled": self.execution_enabled,
            "whitelist": [list(prefix) for prefix in self.whitelist],
        }

    def request_command(
        self,
        *,
        command: list[str],
        rationale: str | None = None,
        requested_by: str = "agent",
        metadata: dict[str, Any] | None = None,
    ) -> ApprovalItem:
        self._require_enabled()
        normalized = self._normalize_command(command)
        self._require_whitelisted(normalized)

        approval_payload = {
            "mode": "approval_only",
            "execution_enabled": self.execution_enabled,
            "command": normalized,
            "rationale": rationale,
            "metadata": dict(metadata or {}),
        }

        with self.session_factory() as session:
            approval = ApprovalRepository(session).create(
                {
                    "target_type": "system_command",
                    "target_id": self._target_id(normalized),
                    "title": f"Approve system command: {' '.join(normalized)}",
                    "status": "pending",
                    "requested_by": requested_by,
                    "payload": approval_payload,
                    "notes": "Execution requires explicit enablement after approval.",
                }
            )

        self.events.publish(
            "warning",
            "system_command",
            "System command approval requested.",
            approval_id=approval.id,
            command=normalized,
        )
        return approval

    def request_tool_command(self, arguments: dict[str, Any]) -> dict[str, Any]:
        approval = self.request_command(
            command=[str(part) for part in arguments.get("command", [])],
            rationale=str(arguments["rationale"]) if arguments.get("rationale") is not None else None,
            requested_by=str(arguments.get("requested_by") or "agent"),
            metadata=dict(arguments.get("metadata") or {}),
        )
        return {
            "status": "pending_approval",
            "approval_id": approval.id,
            "command": list(approval.payload.get("command", [])),
            "execution_enabled": self.execution_enabled,
        }

    def apply_resolution(
        self,
        approval: ApprovalItem,
        *,
        status: str,
        reviewer: str,
        notes: str | None,
    ) -> ApprovalItem:
        payload = dict(approval.payload or {})
        command = [str(part) for part in payload.get("command", [])]
        payload["resolution"] = {
            "status": status,
            "reviewer": reviewer,
            "reason": notes,
            "approved": status == "approved",
            "execution_enabled": self.execution_enabled,
        }
        execution_status = "approved_ready" if status == "approved" and self.execution_enabled else "approved_but_disabled" if status == "approved" else "rejected"
        payload["execution_status"] = execution_status
        payload["approved_command"] = command if status == "approved" else None
        payload["command_resolution"] = {
            "command": command,
            "execution_status": "approved_ready" if status == "approved" and self.execution_enabled else "approved_not_executed" if status == "approved" else "rejected",
            "execution_enabled": self.execution_enabled,
            "approved_at": datetime.now(timezone.utc).isoformat() if status == "approved" else None,
            "reviewed_by": reviewer,
        }
        approval.payload = payload

        self.events.publish(
            "warning" if status == "approved" else "info",
            "system_command",
            "System command approval resolved.",
            approval_id=approval.id,
            command=command,
            status=status,
        )
        return approval

    def execute_approval(self, approval_id: str, *, requested_by: str = "desktop-user") -> ApprovalItem:
        self._require_enabled()
        self._require_execution_enabled()

        with self.session_factory() as session:
            repo = ApprovalRepository(session)
            approval = repo.get(approval_id)
            if approval is None:
                raise SystemCommandApprovalError("System command approval was not found.")
            if approval.target_type != "system_command":
                raise SystemCommandApprovalError("Approval is not a system command request.")
            if approval.status != "approved":
                raise SystemCommandApprovalError("System command must be approved before execution.")

            payload = dict(approval.payload or {})
            existing_execution = payload.get("execution")
            if isinstance(existing_execution, dict) and str(existing_execution.get("status") or "") in {"completed", "failed", "timeout"}:
                return approval

            command = self._normalize_command([str(part) for part in payload.get("command", [])])
            self._require_whitelisted(command)

            execution = self._run_command(command, requested_by=requested_by)
            payload["execution"] = execution
            payload["execution_status"] = execution["status"]
            payload["execution_enabled"] = self.execution_enabled
            payload["command_resolution"] = {
                "command": command,
                "execution_status": execution["status"],
                "execution_enabled": self.execution_enabled,
                "approved_at": ((payload.get("command_resolution") or {}).get("approved_at") if isinstance(payload.get("command_resolution"), dict) else None),
                "executed_at": execution["finished_at"],
                "reviewed_by": ((payload.get("command_resolution") or {}).get("reviewed_by") if isinstance(payload.get("command_resolution"), dict) else None),
            }
            approval.payload = payload
            updated = repo.update(approval, {"payload": payload})

        self.events.publish(
            "info" if execution["status"] == "completed" else "warning",
            "system_command",
            "System command execution finished.",
            approval_id=approval_id,
            command=command,
            execution_status=execution["status"],
            returncode=execution["returncode"],
        )
        return updated

    def _require_enabled(self) -> None:
        if self.flags.is_enabled("skills.system_command"):
            return
        self.events.publish(
            "warning",
            "system_command",
            "Blocked system command request because the feature flag is disabled.",
        )
        raise SystemCommandDisabledError("System command extension is disabled.")

    def _require_execution_enabled(self) -> None:
        if self.execution_enabled:
            return
        self.events.publish(
            "warning",
            "system_command",
            "Blocked system command execution because execution is disabled.",
        )
        raise SystemCommandDisabledError("System command execution is disabled.")

    def _require_whitelisted(self, command: list[str]) -> None:
        if any(self._matches_prefix(command, prefix) for prefix in self.whitelist):
            return
        self.events.publish(
            "warning",
            "system_command",
            "Rejected system command outside the approved whitelist.",
            command=command,
        )
        raise SystemCommandPolicyError("System command is not in the approved whitelist.")

    def _normalize_command(self, command: list[str]) -> list[str]:
        normalized = [str(part).strip() for part in command if str(part).strip()]
        if normalized:
            return normalized
        raise SystemCommandPolicyError("System command cannot be empty.")

    def _matches_prefix(self, command: list[str], prefix: tuple[str, ...]) -> bool:
        return len(command) >= len(prefix) and tuple(command[: len(prefix)]) == prefix

    def _target_id(self, command: list[str]) -> str:
        return " ".join(command)

    def _run_command(self, command: list[str], *, requested_by: str) -> dict[str, Any]:
        started_at = datetime.now(timezone.utc).isoformat()
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.default_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "status": "timeout",
                "requested_by": requested_by,
                "started_at": started_at,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "returncode": None,
                "stdout": exc.stdout or "",
                "stderr": exc.stderr or "",
                "timed_out": True,
            }

        return {
            "status": "completed" if completed.returncode == 0 else "failed",
            "requested_by": requested_by,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "timed_out": False,
        }
