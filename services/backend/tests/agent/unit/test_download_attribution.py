from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from recruit_station.services.download_attribution import LocalDownloadAttributionService


def test_local_download_attribution_completed(tmp_path: Path) -> None:
    service = LocalDownloadAttributionService(default_download_directory=tmp_path)
    attempt = service.create_attempt(
        {
            "candidate": {"candidate_id": "c-1"},
            "sourceUrl": "https://recruit.example.test/resume.pdf",
            "href": "https://recruit.example.test/resume.pdf",
            "download": "resume.pdf",
        }
    )
    (tmp_path / "resume.pdf").write_bytes(b"%PDF")

    result = service.attribute_attempt({"downloadAttemptId": attempt["downloadAttemptId"]})

    assert result["status"] == "completed"
    assert result["candidate"] == {"candidate_id": "c-1"}
    assert result["sourceUrl"] == "https://recruit.example.test/resume.pdf"
    assert result["file_name"] == "resume.pdf"
    assert result["file_path"] == str(tmp_path / "resume.pdf")


def test_local_download_attribution_timeout(tmp_path: Path) -> None:
    service = LocalDownloadAttributionService(default_download_directory=tmp_path)
    attempt = service.create_attempt({"candidate": {"candidate_id": "c-1"}})

    result = service.attribute_attempt({"downloadAttemptId": attempt["downloadAttemptId"], "timeoutMs": 0})

    assert result["status"] == "timeout"
    assert result["candidates"] == []


def test_local_download_attribution_ambiguous(tmp_path: Path) -> None:
    service = LocalDownloadAttributionService(default_download_directory=tmp_path)
    attempt = service.create_attempt({"candidate": {"candidate_id": "c-1"}, "expectedFileName": "resume.pdf"})
    (tmp_path / "resume-a.pdf").write_bytes(b"a")
    (tmp_path / "resume-b.pdf").write_bytes(b"b")

    result = service.attribute_attempt({"downloadAttemptId": attempt["downloadAttemptId"]})

    assert result["status"] == "ambiguous"
    assert {item["file_name"] for item in result["candidates"]} == {"resume-a.pdf", "resume-b.pdf"}


def test_local_download_attribution_rejects_arbitrary_download_directory(tmp_path: Path) -> None:
    service = LocalDownloadAttributionService(default_download_directory=tmp_path / "Downloads")

    result = service.create_attempt({"downloadDirectory": str(tmp_path / "agent-workspace")})

    assert result["status"] == "blocked"
    assert result["error"] == "download_directory_not_allowed"


def test_local_download_attribution_allows_server_side_download_root(tmp_path: Path) -> None:
    allowed_root = tmp_path / "server-downloads"
    service = LocalDownloadAttributionService(
        default_download_directory=tmp_path / "Downloads",
        allowed_download_roots=(allowed_root,),
    )

    result = service.create_attempt({"downloadDirectory": str(allowed_root / "scene-1")})

    assert result["status"] == "recorded"
    assert result["downloadDirectory"] == str(allowed_root / "scene-1")


def test_local_download_attribution_single_uncorrelated_file_is_ambiguous(tmp_path: Path) -> None:
    service = LocalDownloadAttributionService(default_download_directory=tmp_path)
    attempt = service.create_attempt({"candidate": {"candidate_id": "c-1"}})
    (tmp_path / "single.pdf").write_bytes(b"%PDF")

    result = service.attribute_attempt({"downloadAttemptId": attempt["downloadAttemptId"]})

    assert result["status"] == "ambiguous"
    assert [item["file_name"] for item in result["candidates"]] == ["single.pdf"]


def test_local_download_attribution_filters_files_older_than_started_at(tmp_path: Path) -> None:
    service = LocalDownloadAttributionService(default_download_directory=tmp_path)
    started_at = datetime.now(timezone.utc)
    attempt = service.create_attempt({"startedAt": started_at.isoformat(), "expectedFileName": "resume.pdf"})
    file_path = tmp_path / "resume.pdf"
    file_path.write_bytes(b"%PDF")
    old_mtime = (started_at - timedelta(seconds=5)).timestamp()
    os.utime(file_path, (old_mtime, old_mtime))

    result = service.attribute_attempt({"downloadAttemptId": attempt["downloadAttemptId"], "timeoutMs": 0})

    assert result["status"] == "timeout"
