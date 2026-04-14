from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from uuid import uuid4

from .base import CandidateSnapshot


Handler = Callable[..., Any]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    return None


def _lower_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.lower()
    return str(value).lower()


def _extract_overall_score(scores: dict[str, Any]) -> float:
    for key in ("overall", "score", "match_score", "total"):
        value = scores.get(key)
        if isinstance(value, (int, float)):
            return float(value)

    numeric_values = [float(value) for value in scores.values() if isinstance(value, (int, float))]
    return max(numeric_values) if numeric_values else 0.0


def _copy_record(record: dict[str, Any]) -> dict[str, Any]:
    copied = dict(record)
    for key, value in list(copied.items()):
        if isinstance(value, dict):
            copied[key] = dict(value)
        elif isinstance(value, list):
            copied[key] = list(value)
    return copied


def _candidate_store_from_source(source: Any) -> dict[str, dict[str, Any]]:
    if source is None:
        return {}
    if isinstance(source, dict):
        store: dict[str, dict[str, Any]] = {}
        for candidate_id, payload in source.items():
            if isinstance(payload, CandidateSnapshot):
                store[candidate_id] = _copy_record(payload.raw)
                store[candidate_id].setdefault("candidate_id", payload.candidate_id)
                store[candidate_id].setdefault("name", payload.name)
                store[candidate_id].setdefault("status", payload.status)
                continue
            if isinstance(payload, dict):
                record = _copy_record(payload)
                record.setdefault("candidate_id", candidate_id)
                store[str(candidate_id)] = record
        return store
    if isinstance(source, list):
        store = {}
        for item in source:
            if isinstance(item, CandidateSnapshot):
                record = _copy_record(item.raw)
                record.setdefault("candidate_id", item.candidate_id)
                store[item.candidate_id] = record
            elif isinstance(item, dict):
                snapshot = CandidateSnapshot.from_payload(item)
                store[snapshot.candidate_id] = _copy_record(snapshot.raw)
        return store
    return {}


@dataclass(slots=True)
class BossPlatformAdapter:
    """Legacy recruiting-site adapter kept as a compatibility seed for runtime environment handling."""
    base_url: str = "https://www.zhipin.com"
    browser_context: dict[str, Any] = field(default_factory=dict)
    candidate_store: dict[str, dict[str, Any]] = field(default_factory=dict)
    action_handlers: dict[str, Handler] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.candidate_store:
            source = self.browser_context.get("candidate_store") or self.browser_context.get("candidates")
            self.candidate_store = _candidate_store_from_source(source)

        if not self.action_handlers:
            handlers = self.browser_context.get("handlers")
            if isinstance(handlers, dict):
                self.action_handlers = {name: handler for name, handler in handlers.items() if callable(handler)}

    @property
    def platform_name(self) -> str:
        return "boss"

    def healthcheck(self) -> bool:
        handler = self._get_handler("healthcheck")
        if handler is not None:
            return bool(handler())
        return bool(self.base_url)

    def discover_candidates(self, query: dict[str, Any]) -> list[CandidateSnapshot]:
        handler = self._get_handler("discover_candidates")
        if handler is not None:
            return [CandidateSnapshot.from_payload(item) for item in handler(dict(query))]

        search_terms = _lower_text(query.get("search") or query.get("keyword") or query.get("q"))
        required_status = _lower_text(query.get("status"))
        required_platform = _lower_text(query.get("platform") or "boss")
        required_location = _lower_text(query.get("location"))
        required_tag = _lower_text(query.get("tag") or query.get("tag_name"))
        limit = int(query.get("limit") or 50)
        min_score = query.get("min_score")
        include_cooldown = bool(query.get("include_cooldown", True))

        matches: list[CandidateSnapshot] = []
        for candidate_id, candidate in self.candidate_store.items():
            if not self._candidate_matches(
                candidate_id,
                candidate,
                search_terms=search_terms,
                required_status=required_status,
                required_platform=required_platform,
                required_location=required_location,
                required_tag=required_tag,
                min_score=min_score,
                include_cooldown=include_cooldown,
            ):
                continue
            snapshot = self._snapshot(candidate_id, candidate)
            matches.append(snapshot)

        matches.sort(key=self._discover_sort_key, reverse=True)
        return matches[:limit]

    def inspect_candidate(self, candidate_id: str) -> CandidateSnapshot:
        handler = self._get_handler("inspect_candidate")
        if handler is not None:
            return CandidateSnapshot.from_payload(handler(candidate_id))

        candidate = self._resolve_candidate(candidate_id)
        return self._snapshot(candidate_id, candidate)

    def send_message(self, candidate_id: str, message: str) -> dict[str, Any]:
        handler = self._get_handler("send_message")
        if handler is not None:
            return dict(handler(candidate_id, message))

        candidate = self._resolve_candidate(candidate_id)
        timestamp = _utcnow()
        message_record = {
            "message_id": uuid4().hex,
            "candidate_id": candidate_id,
            "message": message,
            "channel": "boss",
            "status": "sent",
            "sent_at": timestamp.isoformat(),
        }
        candidate.setdefault("communications", []).append(message_record)
        candidate["status"] = "pending_reply"
        candidate["last_contacted_at"] = timestamp.isoformat()
        self._append_log("message_log", message_record)
        return message_record

    def request_resume(self, candidate_id: str) -> dict[str, Any]:
        handler = self._get_handler("request_resume")
        if handler is not None:
            return dict(handler(candidate_id))

        candidate = self._resolve_candidate(candidate_id)
        timestamp = _utcnow()
        request = {
            "request_id": uuid4().hex,
            "candidate_id": candidate_id,
            "status": "requested",
            "requested_at": timestamp.isoformat(),
        }
        candidate["status"] = "awaiting_resume"
        candidate["resume_requested_at"] = timestamp.isoformat()
        self._append_log("resume_requests", request)
        return request

    def score_candidate(self, candidate_id: str, scores: dict[str, Any]) -> dict[str, Any]:
        handler = self._get_handler("score_candidate")
        if handler is not None:
            return dict(handler(candidate_id, scores))

        candidate = self._resolve_candidate(candidate_id)
        timestamp = _utcnow()
        existing_scores = candidate.setdefault("ai_scores", {})
        if isinstance(existing_scores, dict):
            existing_scores.update(scores)
        else:
            candidate["ai_scores"] = dict(scores)

        overall_score = _extract_overall_score(scores)
        threshold = float(self.browser_context.get("score_threshold", 70))
        recommendation = "advance" if overall_score >= threshold else "hold"
        if recommendation == "advance":
            candidate["status"] = "screening"
        candidate["last_scored_at"] = timestamp.isoformat()

        result = {
            "candidate_id": candidate_id,
            "status": candidate.get("status"),
            "overall_score": overall_score,
            "recommendation": recommendation,
            "scored_at": timestamp.isoformat(),
            "scores": dict(scores),
        }
        self._append_log("score_log", result)
        return result

    def archive_candidate(self, candidate_id: str, reason: str) -> dict[str, Any]:
        handler = self._get_handler("archive_candidate")
        if handler is not None:
            return dict(handler(candidate_id, reason))

        candidate = self._resolve_candidate(candidate_id)
        timestamp = _utcnow()
        candidate["status"] = "archived"
        candidate["archive_reason"] = reason
        candidate["archived_at"] = timestamp.isoformat()
        record = {
            "candidate_id": candidate_id,
            "status": "archived",
            "reason": reason,
            "archived_at": timestamp.isoformat(),
        }
        self._append_log("archive_log", record)
        return record

    def check_cooldown(self, candidate_id: str) -> bool:
        handler = self._get_handler("check_cooldown")
        if handler is not None:
            return bool(handler(candidate_id))

        candidate = self._resolve_candidate(candidate_id)
        now = _utcnow()
        cooldown_until = _parse_datetime(candidate.get("cooldown_until"))
        if cooldown_until is not None:
            return cooldown_until > now

        last_contacted_at = _parse_datetime(candidate.get("last_contacted_at"))
        if last_contacted_at is None:
            return False

        cooldown_days = int(
            candidate.get("cooldown_days")
            or candidate.get("contact_info", {}).get("cooldown_days")
            or self.browser_context.get("cooldown_days", 30)
        )
        return last_contacted_at + timedelta(days=cooldown_days) > now

    def _get_handler(self, name: str) -> Handler | None:
        handler = self.action_handlers.get(name)
        if handler is not None:
            return handler

        browser_handler = self.browser_context.get(f"{name}_handler") or self.browser_context.get(name)
        return browser_handler if callable(browser_handler) else None

    def _resolve_candidate(self, candidate_id: str) -> dict[str, Any]:
        candidate = self.candidate_store.get(candidate_id)
        if candidate is not None:
            return candidate

        for stored_candidate_id, stored_candidate in self.candidate_store.items():
            if stored_candidate.get("platform_candidate_id") == candidate_id or stored_candidate.get("candidate_id") == candidate_id:
                return stored_candidate

        raise KeyError(f"Unknown recruiting-site candidate: {candidate_id}")

    def _snapshot(self, candidate_id: str, candidate: dict[str, Any]) -> CandidateSnapshot:
        raw = _copy_record(candidate)
        raw.setdefault("candidate_id", candidate_id)
        raw.setdefault("source", self.platform_name)
        return CandidateSnapshot.from_payload(raw, default_source=self.platform_name)

    def _candidate_matches(
        self,
        candidate_id: str,
        candidate: dict[str, Any],
        *,
        search_terms: str,
        required_status: str,
        required_platform: str,
        required_location: str,
        required_tag: str,
        min_score: Any,
        include_cooldown: bool,
    ) -> bool:
        if required_status and _lower_text(candidate.get("status")) != required_status:
            return False

        platform = _lower_text(candidate.get("platform") or self.platform_name)
        if required_platform and platform != required_platform:
            return False

        if not include_cooldown and self.check_cooldown(candidate_id):
            return False

        contact_info = candidate.get("contact_info") if isinstance(candidate.get("contact_info"), dict) else {}
        if required_location:
            location = _lower_text(contact_info.get("location") or candidate.get("location"))
            if required_location not in location:
                return False

        if required_tag:
            tags = contact_info.get("tags") or candidate.get("tags") or []
            tag_values = [_lower_text(tag) for tag in tags if tag is not None]
            if required_tag not in tag_values:
                return False

        if min_score is not None:
            overall = candidate.get("ai_scores", {}).get("overall")
            if overall is None:
                overall = candidate.get("match_score")
            if overall is None or float(overall) < float(min_score):
                return False

        if search_terms:
            searchable_bits = [
                candidate.get("name"),
                candidate.get("status"),
                candidate.get("platform"),
                candidate.get("platform_candidate_id"),
                candidate.get("jd_id"),
                candidate.get("ai_reasoning"),
                contact_info.get("title"),
                contact_info.get("summary"),
                contact_info.get("location"),
                " ".join(str(tag) for tag in contact_info.get("tags", [])),
            ]
            haystack = " ".join(_lower_text(bit) for bit in searchable_bits)
            if search_terms not in haystack:
                return False

        return True

    def _discover_sort_key(self, snapshot: CandidateSnapshot) -> tuple[float, str]:
        raw = snapshot.raw
        score = raw.get("match_score")
        if score is None and isinstance(raw.get("ai_scores"), dict):
            score = raw["ai_scores"].get("overall")
        try:
            numeric_score = float(score) if score is not None else 0.0
        except (TypeError, ValueError):
            numeric_score = 0.0
        return numeric_score, snapshot.candidate_id

    def _append_log(self, key: str, entry: dict[str, Any]) -> None:
        bucket = self.browser_context.setdefault(key, [])
        if isinstance(bucket, list):
            bucket.append(dict(entry))
