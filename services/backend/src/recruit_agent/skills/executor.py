from __future__ import annotations

import inspect
import json
import math
import re
import statistics
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from recruit_agent.models.domain import Skill
from recruit_agent.skills.registry import SkillRegistry
from recruit_agent.skills.sandbox import run_in_sandbox

_SAFE_BUILTINS: dict[str, Any] = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "float": float,
    "int": int,
    "len": len,
    "list": list,
    "max": max,
    "min": min,
    "range": range,
    "round": round,
    "set": set,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
}

_PYTHON_INLINE_GLOBALS: dict[str, Any] = {
    "__builtins__": _SAFE_BUILTINS,
    "json": json,
    "math": math,
    "re": re,
    "statistics": statistics,
    "datetime": datetime,
    "date": date,
    "timedelta": timedelta,
}


def build_invoke_skill_handler(session_factory: sessionmaker[Session]):
    registry = SkillRegistry(session_factory)

    def _handler(arguments: dict[str, Any]) -> dict[str, Any]:
        skill_id = str(arguments.get("skill_id") or "").strip()
        if not skill_id:
            raise ValueError("skill_id is required")
        skill = registry.get_skill(skill_id)
        if skill is None:
            raise ValueError(f"unknown skill: {skill_id}")
        payload = dict(arguments.get("input") or {})
        return execute_skill(skill, payload)

    return _handler


def _skill_context(skill: Skill) -> dict[str, Any]:
    return {
        "skill_id": skill.skill_id,
        "name": skill.name,
        "description": skill.description,
        "category": skill.category,
        "platform": skill.platform,
        "strategy": dict(skill.strategy or {}),
        "execution_hints": dict(skill.execution_hints or {}),
        "skill_metadata": dict(skill.skill_metadata or {}),
        "body": dict(skill.body or {}),
    }


def _python_inline_artifact(skill: Skill) -> dict[str, Any] | None:
    body = dict(skill.body or {})
    artifacts = body.get("artifacts")
    if not isinstance(artifacts, dict):
        return None
    python_inline = artifacts.get("python_inline")
    if not isinstance(python_inline, dict):
        return None
    return dict(python_inline)


def _call_entrypoint(entrypoint: Any, payload: dict[str, Any], context: dict[str, Any]) -> Any:
    parameters = inspect.signature(entrypoint).parameters
    if len(parameters) <= 1:
        return entrypoint(payload)
    return entrypoint(payload, context)


def _execute_python_inline(skill: Skill, payload: dict[str, Any], artifact: dict[str, Any]) -> dict[str, Any]:
    entrypoint_name = str(artifact.get("entrypoint") or "run").strip() or "run"
    code = str(artifact.get("code") or "").strip()
    if not code:
        raise ValueError("python_inline artifact is missing code")

    context = _skill_context(skill)

    def _run() -> Any:
        namespace = dict(_PYTHON_INLINE_GLOBALS)
        exec(code, namespace, namespace)
        entrypoint = namespace.get(entrypoint_name)
        if not callable(entrypoint):
            raise ValueError(f"python_inline entrypoint not found: {entrypoint_name}")
        return _call_entrypoint(entrypoint, payload, context)

    result = run_in_sandbox(_run)
    return {
        "skill_id": skill.skill_id,
        "executor_mode": "python_inline",
        "entrypoint": entrypoint_name,
        "result": result,
    }


def execute_skill(skill: Skill, payload: dict[str, Any]) -> dict[str, Any]:
    artifact = _python_inline_artifact(skill)
    if artifact is not None:
        return _execute_python_inline(skill, payload, artifact)

    return {
        "skill_id": skill.skill_id,
        "executor_mode": str(dict(skill.execution_hints or {}).get("executor_mode") or "tool_or_llm"),
        "payload": payload,
        "strategy": dict(skill.strategy or {}),
    }
