from __future__ import annotations

from time import sleep
from typing import Any

from recruit_agent.agent_runtime.models import CancellationToken


def run_browser_worker(
    payload: dict[str, Any],
    *,
    cancel_token: CancellationToken | None = None,
) -> dict[str, Any]:
    action = str(payload.get("action") or "inspect").strip() or "inspect"
    url = str(payload.get("url") or "").strip()
    selector = str(payload.get("selector") or "").strip() or None
    step_delay_ms = max(int(payload.get("step_delay_ms") or 30), 0)
    steps = [
        {"name": "open_context", "detail": url or "current_tab"},
        {"name": "locate_target", "detail": selector or action},
        {"name": "perform_action", "detail": action},
    ]
    trace: list[dict[str, Any]] = []

    if payload.get("requires_human") or payload.get("human_checkpoint"):
        return {
            "status": "blocked_human",
            "output": {
                "reason": str(payload.get("human_reason") or "human confirmation required"),
                "action": action,
                "url": url or None,
            },
            "metadata": {"trace": trace},
        }

    if payload.get("requires_environment") or (action == "navigate" and not url):
        return {
            "status": "blocked_environment",
            "output": {
                "reason": str(payload.get("environment_reason") or "browser environment is not ready"),
                "action": action,
                "url": url or None,
            },
            "metadata": {"trace": trace},
        }

    if payload.get("force_failure"):
        raise RuntimeError(str(payload.get("failure_message") or "browser worker failed"))

    for index, step in enumerate(steps, start=1):
        if cancel_token is not None and cancel_token.cancelled:
            return {
                "status": "cancelled",
                "error": cancel_token.reason or "execution unit cancelled",
                "output": {"trace": trace},
                "metadata": {"trace": trace},
            }
        _sleep_with_cancellation(step_delay_ms / 1000, cancel_token)
        if cancel_token is not None and cancel_token.cancelled:
            return {
                "status": "cancelled",
                "error": cancel_token.reason or "execution unit cancelled",
                "output": {"trace": trace},
                "metadata": {"trace": trace},
            }
        trace.append(
            {
                "step": index,
                "name": step["name"],
                "detail": step["detail"],
                "status": "completed",
            }
        )

    return {
        "status": "succeeded",
        "output": {
            "action": action,
            "url": url or None,
            "selector": selector,
            "trace": trace,
            "result": {
                "page_title": str(payload.get("page_title") or "Simulated Browser Context"),
                "observed_text": str(payload.get("observed_text") or f"browser action {action} completed"),
            },
        },
        "metadata": {
            "trace": trace,
            "step_count": len(trace),
        },
    }


def _sleep_with_cancellation(seconds: float, cancel_token: CancellationToken | None) -> None:
    if seconds <= 0:
        return
    remaining = seconds
    while remaining > 0:
        window = min(remaining, 0.05)
        if cancel_token is not None and cancel_token.wait(window):
            return
        if cancel_token is None:
            sleep(window)
        remaining -= window
