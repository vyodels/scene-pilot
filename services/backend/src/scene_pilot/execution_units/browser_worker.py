from __future__ import annotations

from typing import Any


def run_browser_worker(payload: dict[str, Any]) -> dict[str, Any]:
    return {"accepted": True, "payload": dict(payload)}
