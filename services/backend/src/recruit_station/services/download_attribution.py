from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import unquote, urlparse


_INCOMPLETE_SUFFIXES = (".crdownload", ".download", ".part", ".tmp")


@dataclass(slots=True)
class _DownloadAttempt:
    download_attempt_id: str
    candidate: dict[str, Any]
    source_url: str | None
    href: str | None
    download: str | None
    expected_file_name: str | None
    started_at: datetime
    download_directory: Path
    before_snapshot: dict[str, dict[str, Any]]


class LocalDownloadAttributionService:
    def __init__(
        self,
        *,
        default_download_directory: Path | None = None,
        allowed_download_roots: list[Path] | tuple[Path, ...] | None = None,
    ) -> None:
        self.default_download_directory = _resolve_path(default_download_directory or (Path.home() / "Downloads"))
        self.allowed_download_roots = tuple(_resolve_path(item) for item in list(allowed_download_roots or []))
        self._lock = RLock()
        self._attempts: dict[str, _DownloadAttempt] = {}

    def create_attempt(self, arguments: dict[str, Any]) -> dict[str, Any]:
        download_directory = self._resolve_download_directory(arguments.get("download_directory") or arguments.get("downloadDirectory"))
        if isinstance(download_directory, dict):
            return download_directory
        started_at = _coerce_datetime(arguments.get("started_at") or arguments.get("startedAt")) or datetime.now(timezone.utc)
        source_url = _optional_string(arguments.get("source_url") or arguments.get("sourceUrl") or arguments.get("url"))
        href = _optional_string(arguments.get("href"))
        download = _optional_string(arguments.get("download"))
        expected_file_name = _expected_file_name(
            explicit=(
                arguments.get("expected_file_name")
                or arguments.get("expectedFileName")
                or arguments.get("file_name")
                or arguments.get("fileName")
                or download
            ),
            href=href,
            source_url=source_url,
        )
        attempt = _DownloadAttempt(
            download_attempt_id=str(arguments.get("downloadAttemptId") or arguments.get("download_attempt_id") or uuid.uuid4().hex),
            candidate=dict(arguments.get("candidate") or {}),
            source_url=source_url,
            href=href,
            download=download,
            expected_file_name=expected_file_name,
            started_at=started_at,
            download_directory=download_directory,
            before_snapshot=_snapshot_directory(download_directory),
        )
        with self._lock:
            self._attempts[attempt.download_attempt_id] = attempt
        return _attempt_payload(attempt)

    def attribute_attempt(self, arguments: dict[str, Any]) -> dict[str, Any]:
        attempt_id = str(arguments.get("downloadAttemptId") or arguments.get("download_attempt_id") or "").strip()
        if not attempt_id:
            return {"status": "timeout", "downloadAttemptId": "", "message": "downloadAttemptId is required"}
        with self._lock:
            attempt = self._attempts.get(attempt_id)
        if attempt is None:
            return {"status": "timeout", "downloadAttemptId": attempt_id, "message": "download attempt is unknown"}

        timeout_ms = _coerce_int(arguments.get("timeoutMs") or arguments.get("timeout_ms"), default=0)
        poll_ms = max(50, _coerce_int(arguments.get("pollIntervalMs") or arguments.get("poll_interval_ms"), default=200))
        deadline = time.monotonic() + max(0, timeout_ms) / 1000
        while True:
            result = self._attribute_now(attempt)
            if result["status"] != "timeout" or time.monotonic() >= deadline:
                return result
            time.sleep(poll_ms / 1000)

    def _resolve_download_directory(self, value: Any) -> Path | dict[str, Any]:
        text = _optional_string(value)
        directory = _resolve_path(text) if text else self.default_download_directory
        if _paths_equal_or_nested(directory, self.default_download_directory):
            return directory
        if any(_paths_equal_or_nested(directory, root) for root in self.allowed_download_roots):
            return directory
        return {
            "status": "blocked",
            "success": False,
            "error": "download_directory_not_allowed",
            "message": "downloadDirectory must be the default Downloads directory or a server-side allowed download root.",
            "downloadDirectory": str(directory),
            "defaultDownloadDirectory": str(self.default_download_directory),
            "allowedDownloadRoots": [str(item) for item in self.allowed_download_roots],
        }

    def _attribute_now(self, attempt: _DownloadAttempt) -> dict[str, Any]:
        after_snapshot = _snapshot_directory(attempt.download_directory)
        created = [
            item
            for path, item in after_snapshot.items()
            if path not in attempt.before_snapshot
            and not _is_incomplete_path(path)
            and _file_mtime_at_or_after_started_at(item, attempt.started_at)
        ]
        if attempt.expected_file_name:
            expected = attempt.expected_file_name.lower()
            matching = [item for item in created if str(item.get("file_name") or "").lower() == expected]
            if len(matching) == 1:
                return _completed_payload(attempt, matching[0], after_snapshot)
            if created:
                return {
                    **_attempt_payload(attempt),
                    "status": "ambiguous",
                    "message": "New files were found, but none uniquely matched the expected filename.",
                    "candidates": created,
                    "afterSnapshot": after_snapshot,
                }
        elif created:
            return {
                **_attempt_payload(attempt),
                "status": "ambiguous",
                "message": "New files were found, but no expected filename or source filename was available for attribution.",
                "candidates": created,
                "afterSnapshot": after_snapshot,
            }
        return {
            **_attempt_payload(attempt),
            "status": "timeout",
            "candidates": [],
            "afterSnapshot": after_snapshot,
        }


def _snapshot_directory(directory: Path) -> dict[str, dict[str, Any]]:
    if not directory.exists() or not directory.is_dir():
        return {}
    snapshot: dict[str, dict[str, Any]] = {}
    for item in directory.iterdir():
        if not item.is_file():
            continue
        try:
            stat = item.stat()
        except OSError:
            continue
        snapshot[str(item)] = {
            "file_path": str(item),
            "file_name": item.name,
            "size": stat.st_size,
            "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            "mtimeEpoch": stat.st_mtime,
        }
    return snapshot


def _attempt_payload(attempt: _DownloadAttempt) -> dict[str, Any]:
    return {
        "status": "recorded",
        "downloadAttemptId": attempt.download_attempt_id,
        "candidate": dict(attempt.candidate),
        "sourceUrl": attempt.source_url,
        "href": attempt.href,
        "download": attempt.download,
        "expectedFileName": attempt.expected_file_name,
        "startedAt": attempt.started_at.isoformat(),
        "downloadDirectory": str(attempt.download_directory),
        "beforeSnapshot": attempt.before_snapshot,
    }


def _completed_payload(attempt: _DownloadAttempt, file_payload: dict[str, Any], after_snapshot: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        **_attempt_payload(attempt),
        "status": "completed",
        "file": dict(file_payload),
        "file_path": file_payload.get("file_path"),
        "file_name": file_payload.get("file_name"),
        "afterSnapshot": after_snapshot,
    }


def _is_incomplete_path(path: str) -> bool:
    return path.lower().endswith(_INCOMPLETE_SUFFIXES)


def _file_mtime_at_or_after_started_at(item: dict[str, Any], started_at: datetime) -> bool:
    try:
        mtime = float(item.get("mtimeEpoch"))
    except (TypeError, ValueError):
        parsed = _coerce_datetime(item.get("mtime"))
        if parsed is None:
            return False
        mtime = parsed.timestamp()
    return mtime >= started_at.timestamp() - 0.001


def _optional_string(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _coerce_datetime(value: Any) -> datetime | None:
    text = _optional_string(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _coerce_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _resolve_path(value: Path | str) -> Path:
    return Path(value).expanduser().resolve(strict=False)


def _paths_equal_or_nested(path: Path, root: Path) -> bool:
    return path == root or path.is_relative_to(root)


def _expected_file_name(*, explicit: Any, href: str | None, source_url: str | None) -> str | None:
    for candidate in (explicit, _file_name_from_url(href), _file_name_from_url(source_url)):
        file_name = _safe_file_name(candidate)
        if file_name:
            return file_name
    return None


def _file_name_from_url(value: Any) -> str | None:
    text = _optional_string(value)
    if not text:
        return None
    parsed = urlparse(text)
    path = unquote(parsed.path or "")
    return _safe_file_name(Path(path).name)


def _safe_file_name(value: Any) -> str | None:
    text = _optional_string(value)
    if not text:
        return None
    name = Path(text).name.strip()
    if name in {"", ".", ".."}:
        return None
    return name
