from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True)
class CandidateSnapshot:
    candidate_id: str
    name: str | None = None
    status: str | None = None
    source: str = "site"
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | "CandidateSnapshot", *, default_source: str = "site") -> "CandidateSnapshot":
        if isinstance(payload, cls):
            return payload

        record = dict(payload)
        candidate_id = str(
            record.get("candidate_id")
            or record.get("id")
            or record.get("platform_candidate_id")
            or record.get("candidateId")
            or ""
        )
        if not candidate_id:
            raise ValueError("Candidate payload is missing a candidate identifier")

        name = record.get("name")
        status = record.get("status")
        source = str(record.get("source") or default_source)
        return cls(
            candidate_id=candidate_id,
            name=str(name) if name is not None else None,
            status=str(status) if status is not None else None,
            source=source,
            raw=record,
        )


class SiteEnvironmentAdapter(Protocol):
    platform_name: str

    def healthcheck(self) -> bool: ...

    def discover_candidates(self, query: dict[str, Any]) -> list[CandidateSnapshot]: ...

    def inspect_candidate(self, candidate_id: str) -> CandidateSnapshot: ...

    def send_message(self, candidate_id: str, message: str) -> dict[str, Any]: ...

    def request_resume(self, candidate_id: str) -> dict[str, Any]: ...

    def score_candidate(self, candidate_id: str, scores: dict[str, Any]) -> dict[str, Any]: ...

    def archive_candidate(self, candidate_id: str, reason: str) -> dict[str, Any]: ...

    def check_cooldown(self, candidate_id: str) -> bool: ...


PlatformAdapter = SiteEnvironmentAdapter
