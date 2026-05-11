from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from time import sleep
from typing import Any
from uuid import uuid4

from recruit_agent.execution_units.models import EXECUTION_UNIT_STATES, ExecutionUnit
from recruit_agent.execution_units.store import ExecutionUnitStore
from recruit_agent.agent_runtime.models import CancellationToken, ExecutionUnitResult


class ExecutionUnitRunner:
    def __init__(self, *, store: ExecutionUnitStore, workers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]]) -> None:
        self.store = store
        self.workers = workers
        self._threads: dict[str, Thread] = {}
        self._tokens: dict[str, CancellationToken] = {}

    def create_execution_unit(
        self,
        worker_name: str,
        payload: dict[str, Any],
        *,
        cooldown_seconds: int = 0,
        timeout_seconds: float = 0,
    ) -> ExecutionUnit:
        created_at = datetime.now(UTC)
        unit = ExecutionUnit(
            unit_id=uuid4().hex,
            worker_name=worker_name,
            payload=dict(payload),
            metadata={
                "cooldown_seconds": cooldown_seconds,
                "timeout_seconds": timeout_seconds,
                "available_after": (created_at + timedelta(seconds=cooldown_seconds)).isoformat() if cooldown_seconds else None,
            },
            created_at=created_at,
        )
        self.store.add(unit)
        token = CancellationToken()
        self._tokens[unit.unit_id] = token
        worker = Thread(target=self._run_async, args=(unit.unit_id,), daemon=True)
        self._threads[unit.unit_id] = worker
        worker.start()
        return unit

    def wait_unit(
        self,
        unit_id: str,
        *,
        timeout_seconds: float | None = None,
        until_statuses: set[str] | None = None,
    ) -> ExecutionUnit:
        if timeout_seconds is None and until_statuses is None:
            unit = self.store.get(unit_id)
            if unit is None:
                raise KeyError(f"unknown execution unit: {unit_id}")
            return unit
        return self.store.wait(unit_id, timeout_seconds=timeout_seconds, until_statuses=until_statuses)

    def unit_result(self, unit_id: str) -> ExecutionUnitResult:
        unit = self.wait_unit(unit_id)
        return ExecutionUnitResult(
            unit_id=unit.unit_id,
            status=unit.status,
            output=dict(unit.output),
            error=unit.error,
            metadata=dict(unit.metadata),
        )

    def cancel_unit(self, unit_id: str) -> ExecutionUnit:
        unit = self.wait_unit(unit_id)
        if unit.status in {"succeeded", "failed", "timed_out", "cancelled"}:
            return unit
        token = self._tokens.get(unit_id)
        if token is not None:
            token.cancel("execution_unit_cancelled")
        cancelled = replace(
            unit,
            status="cancelled",
            error="execution unit cancelled",
            finished_at=datetime.now(UTC),
        )
        self.store.update(cancelled)
        self._tokens.pop(unit_id, None)
        return cancelled

    def _run_async(self, unit_id: str) -> None:
        unit = self.store.get(unit_id)
        if unit is None:
            return
        token = self._tokens.get(unit_id)
        self._wait_for_cooldown(unit, token=token)
        unit = self.store.get(unit_id)
        if unit is None:
            return
        if token is not None and token.cancelled:
            self.store.update(
                replace(
                    unit,
                    status="cancelled",
                    error=token.reason or "execution unit cancelled",
                    finished_at=datetime.now(UTC),
                )
            )
            self._tokens.pop(unit_id, None)
            self._threads.pop(unit_id, None)
            return
        worker = self.workers.get(unit.worker_name)
        if worker is None:
            self.store.update(
                replace(
                    unit,
                    status="failed",
                    error=f"unknown worker: {unit.worker_name}",
                    finished_at=datetime.now(UTC),
                )
            )
            self._tokens.pop(unit_id, None)
            return

        running = replace(unit, status="running", started_at=datetime.now(UTC))
        self.store.update(running)
        timeout_seconds = float(running.metadata.get("timeout_seconds") or 0)

        result_holder: dict[str, Any] = {}
        error_holder: dict[str, str] = {}
        finished = Event()

        def _invoke_worker_thread() -> None:
            try:
                result_holder["value"] = _call_worker(worker, dict(running.payload), cancel_token=token)
            except Exception as exc:  # pragma: no cover - defensive guard
                error_holder["error"] = str(exc)
            finally:
                finished.set()

        thread = Thread(target=_invoke_worker_thread, daemon=True)
        thread.start()
        if timeout_seconds > 0:
            thread.join(timeout_seconds)
            if thread.is_alive():
                if token is not None:
                    token.cancel("execution_unit_timed_out")
                timed_out = replace(
                    running,
                    status="timed_out",
                    error=f"execution unit exceeded timeout of {timeout_seconds}s",
                    finished_at=datetime.now(UTC),
                )
                self.store.update(timed_out)
                self._tokens.pop(unit_id, None)
                self._threads.pop(unit_id, None)
                return
        else:
            thread.join()

        if token is not None and token.cancelled:
            self.store.update(
                replace(
                    running,
                    status="cancelled",
                    error=token.reason or "execution unit cancelled",
                    finished_at=datetime.now(UTC),
                )
            )
            self._tokens.pop(unit_id, None)
            self._threads.pop(unit_id, None)
            return

        if "error" in error_holder:
            failed = replace(running, status="failed", error=error_holder["error"], finished_at=datetime.now(UTC))
            self.store.update(failed)
            self._tokens.pop(unit_id, None)
            self._threads.pop(unit_id, None)
            return

        transitioned = _transition_unit(running, result_holder.get("value"))
        self.store.update(transitioned)
        self._tokens.pop(unit_id, None)
        self._threads.pop(unit_id, None)

    def _wait_for_cooldown(self, unit: ExecutionUnit, *, token: CancellationToken | None) -> None:
        available_after_raw = unit.metadata.get("available_after")
        if not isinstance(available_after_raw, str) or not available_after_raw:
            return
        try:
            available_after = datetime.fromisoformat(available_after_raw)
        except ValueError:
            return
        while True:
            remaining = (available_after - datetime.now(UTC)).total_seconds()
            if remaining <= 0:
                return
            if token is not None and token.cancelled:
                return
            wait_window = min(remaining, 0.1)
            if token is not None and token.wait(wait_window):
                return
            if token is None:
                sleep(wait_window)


def _transition_unit(unit: ExecutionUnit, worker_result: Any) -> ExecutionUnit:
    finished_at = datetime.now(UTC)
    if isinstance(worker_result, dict):
        status = str(worker_result.get("status") or "succeeded")
        if status in EXECUTION_UNIT_STATES:
            output = worker_result.get("output", {})
            if not isinstance(output, dict):
                output = {"value": output}
            error = worker_result.get("error")
            metadata = dict(unit.metadata)
            metadata.update(dict(worker_result.get("metadata") or {}))
            return replace(
                unit,
                status=status,
                output=output,
                error=None if error is None else str(error),
                metadata=metadata,
                finished_at=finished_at,
            )
    output = worker_result if isinstance(worker_result, dict) else {"value": worker_result}
    return replace(unit, status="succeeded", output=output, finished_at=finished_at)


def _call_worker(
    worker: Callable[[dict[str, Any]], dict[str, Any]],
    payload: dict[str, Any],
    *,
    cancel_token: CancellationToken | None,
) -> Any:
    parameters = inspect.signature(worker).parameters
    if "cancel_token" in parameters:
        return worker(payload, cancel_token=cancel_token)
    return worker(payload)
