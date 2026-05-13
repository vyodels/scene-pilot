from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any


@dataclass(frozen=True, slots=True)
class MemoryFileStore:
    root_dir: Path

    def __post_init__(self) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def list_files(
        self,
        *,
        scope_kind: str,
        scope_ref: str,
        agent_definition_id: str | None = None,
    ) -> list[dict[str, Any]]:
        scope_dir = self._scope_dir(scope_kind=scope_kind, scope_ref=scope_ref, agent_definition_id=agent_definition_id)
        if not scope_dir.exists():
            return []
        files: list[dict[str, Any]] = []
        for path in sorted(scope_dir.rglob("*.md")):
            if not path.is_file():
                continue
            stat = path.stat()
            files.append(
                {
                    "path": path.relative_to(scope_dir).as_posix(),
                    "size": stat.st_size,
                    "updated_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                }
            )
        return files

    def list_scope_files(
        self,
        *,
        scope_kind: str,
        agent_definition_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        agent = _safe_segment(agent_definition_id or "default")
        kind = _safe_segment(scope_kind or "global")
        scope_root = self.root_dir / agent / kind
        if not scope_root.exists():
            return []
        files: list[dict[str, Any]] = []
        for path in sorted(scope_root.glob("*/*.md")):
            if not path.is_file():
                continue
            stat = path.stat()
            preview = _markdown_preview(path)
            scope_ref = path.parent.name
            files.append(
                {
                    "scope_kind": scope_kind,
                    "scope_ref": scope_ref,
                    "path": path.relative_to(path.parent).as_posix(),
                    "preview": preview,
                    "size": stat.st_size,
                    "updated_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                }
            )
        return files[offset : offset + limit]

    def read_file(
        self,
        *,
        scope_kind: str,
        scope_ref: str,
        path: str = "MEMORY.md",
        agent_definition_id: str | None = None,
    ) -> dict[str, Any]:
        resolved = self._resolve_file(scope_kind=scope_kind, scope_ref=scope_ref, path=path, agent_definition_id=agent_definition_id)
        if not resolved.absolute_path.exists():
            return {"path": resolved.relative_path, "exists": False, "content": ""}
        return {"path": resolved.relative_path, "exists": True, "content": resolved.absolute_path.read_text(encoding="utf-8")}

    def write_file(
        self,
        *,
        scope_kind: str,
        scope_ref: str,
        content: str,
        path: str = "MEMORY.md",
        agent_definition_id: str | None = None,
        mode: str = "overwrite",
    ) -> dict[str, Any]:
        resolved = self._resolve_file(scope_kind=scope_kind, scope_ref=scope_ref, path=path, agent_definition_id=agent_definition_id)
        resolved.absolute_path.parent.mkdir(parents=True, exist_ok=True)
        normalized_mode = str(mode or "overwrite").strip().lower()
        if normalized_mode == "append":
            with resolved.absolute_path.open("a", encoding="utf-8") as handle:
                handle.write(str(content or ""))
        elif normalized_mode == "overwrite":
            resolved.absolute_path.write_text(str(content or ""), encoding="utf-8")
        else:
            raise ValueError("memory file mode must be overwrite or append")
        stat = resolved.absolute_path.stat()
        return {
            "path": resolved.relative_path,
            "size": stat.st_size,
            "updated_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        }

    def delete_file(
        self,
        *,
        scope_kind: str,
        scope_ref: str,
        path: str,
        agent_definition_id: str | None = None,
    ) -> dict[str, Any]:
        resolved = self._resolve_file(scope_kind=scope_kind, scope_ref=scope_ref, path=path, agent_definition_id=agent_definition_id)
        existed = resolved.absolute_path.exists()
        if existed:
            resolved.absolute_path.unlink()
        return {"path": resolved.relative_path, "deleted": existed}

    def _scope_dir(self, *, scope_kind: str, scope_ref: str, agent_definition_id: str | None) -> Path:
        agent = _safe_segment(agent_definition_id or "default")
        kind = _safe_segment(scope_kind or "global")
        ref = _safe_segment(scope_ref or "default")
        return self.root_dir / agent / kind / ref

    def _resolve_file(
        self,
        *,
        scope_kind: str,
        scope_ref: str,
        path: str,
        agent_definition_id: str | None,
    ) -> "_ResolvedMemoryFile":
        scope_dir = self._scope_dir(scope_kind=scope_kind, scope_ref=scope_ref, agent_definition_id=agent_definition_id)
        relative = _safe_relative_markdown_path(path or "MEMORY.md")
        absolute = (scope_dir / relative).resolve()
        scope_root = scope_dir.resolve()
        if scope_root != absolute and scope_root not in absolute.parents:
            raise ValueError("memory file path escapes memory scope")
        return _ResolvedMemoryFile(absolute_path=absolute, relative_path=relative.as_posix())


@dataclass(frozen=True, slots=True)
class _ResolvedMemoryFile:
    absolute_path: Path
    relative_path: str


def _safe_segment(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "default"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text)[:120] or "default"


def _safe_relative_markdown_path(path: str) -> Path:
    normalized = str(path or "MEMORY.md").replace("\\", "/").strip().lstrip("/")
    candidate = Path(normalized)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise ValueError("memory file path must be a relative path inside the memory scope")
    if candidate.suffix.lower() != ".md":
        raise ValueError("memory file path must end with .md")
    return candidate


def _markdown_preview(path: Path, *, limit: int = 160) -> str:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    for line in content.splitlines():
        text = line.strip()
        if text:
            return text[:limit]
    return ""
