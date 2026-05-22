from __future__ import annotations

import ast
from typing import Any


class SkillContractError(ValueError):
    pass


_BLOCKED_IMPORT_ROOTS = {
    "asyncio",
    "ftplib",
    "http",
    "httpx",
    "os",
    "pathlib",
    "requests",
    "shutil",
    "socket",
    "subprocess",
    "sys",
    "urllib",
}
_BLOCKED_CALL_NAMES = {"compile", "eval", "exec", "globals", "input", "locals", "open", "__import__"}


def validate_skill_contract(contract: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(contract or {})
    body = dict(normalized.get("body") or {})
    artifacts = dict(body.get("artifacts") or {})
    python_inline = artifacts.get("python_inline")
    if python_inline is not None:
        if not isinstance(python_inline, dict):
            raise SkillContractError("body.artifacts.python_inline must be an object")
        _validate_python_inline_asset(python_inline)
        execution_hints = dict(normalized.get("execution_hints") or {})
        execution_hints.setdefault("executor_mode", "python_inline")
        normalized["execution_hints"] = execution_hints
    health_check_config = dict(normalized.get("health_check_config") or {})
    if health_check_config:
        _validate_health_check_config(health_check_config)
        normalized["health_check_config"] = health_check_config
    return normalized


def skill_asset_manifest(body: dict[str, Any], execution_hints: dict[str, Any]) -> dict[str, Any]:
    artifacts = dict((body or {}).get("artifacts") or {})
    asset_kinds = sorted(str(key) for key, value in artifacts.items() if value not in (None, {}, []))
    manifest: dict[str, Any] = {}
    executor_mode = str((execution_hints or {}).get("executor_mode") or "").strip()
    if executor_mode:
        manifest["executor_mode"] = executor_mode
    if asset_kinds:
        manifest["asset_kinds"] = asset_kinds
        manifest["tool_name"] = "execute_skill_asset"
    python_inline = artifacts.get("python_inline")
    if isinstance(python_inline, dict):
        manifest["python_inline"] = {
            "entrypoint": str(python_inline.get("entrypoint") or "run"),
            "input_contract": dict(python_inline.get("input_contract") or {}),
            "output_contract": dict(python_inline.get("output_contract") or {}),
        }
    return manifest


def _validate_python_inline_asset(asset: dict[str, Any]) -> None:
    entrypoint = str(asset.get("entrypoint") or "run").strip()
    code = asset.get("code")
    if not entrypoint:
        raise SkillContractError("python_inline.entrypoint is required")
    if not isinstance(code, str) or not code.strip():
        raise SkillContractError("python_inline.code is required")
    for key in ("input_contract", "output_contract"):
        if key in asset and not isinstance(asset.get(key), dict):
            raise SkillContractError(f"python_inline.{key} must be an object")
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise SkillContractError(f"python_inline.code syntax error: {exc.msg}") from exc
    function_names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    if entrypoint not in function_names:
        raise SkillContractError(f"python_inline.entrypoint function not found: {entrypoint}")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _reject_blocked_import(alias.name)
        elif isinstance(node, ast.ImportFrom):
            _reject_blocked_import(node.module or "")
        elif isinstance(node, ast.Call):
            name = _call_name(node.func)
            if name in _BLOCKED_CALL_NAMES:
                raise SkillContractError(f"python_inline.code uses blocked call: {name}")


def _validate_health_check_config(config: dict[str, Any]) -> None:
    for key in ("preflight", "postconditions"):
        value = config.get(key)
        if value is not None and not isinstance(value, dict):
            raise SkillContractError(f"health_check_config.{key} must be an object")


def _reject_blocked_import(name: str) -> None:
    root = str(name or "").split(".", 1)[0]
    if root in _BLOCKED_IMPORT_ROOTS:
        raise SkillContractError(f"python_inline.code imports blocked module: {root}")


def _call_name(func: ast.AST) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""
