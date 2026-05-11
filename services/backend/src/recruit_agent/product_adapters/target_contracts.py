from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import urlparse


_WEB_URL_RE = re.compile(r"https?://[^\s<>'\"`，。；、！？）)】\]}]+", re.IGNORECASE)
_TRAILING_URL_PUNCTUATION = ".,;:!?，。；、！？)]}】"


def extract_first_web_url(text: Any) -> str | None:
    if not isinstance(text, str) or not text.strip():
        return None
    for match in _WEB_URL_RE.finditer(text):
        candidate = match.group(0).rstrip(_TRAILING_URL_PUNCTUATION)
        parsed = urlparse(candidate)
        if parsed.scheme.lower() in {"http", "https"} and parsed.netloc:
            return candidate
    return None


def derive_browser_target(
    *,
    existing: Any = None,
    structured_sources: Iterable[Any] = (),
    text_sources: Iterable[Any] = (),
) -> dict[str, Any]:
    target = _normalize_browser_target_shape(existing)
    for source in structured_sources:
        target = _merge_missing_target_fields(target, _browser_target_from_structured_source(source))
        if target.get("url") and target.get("host"):
            return _compact_target(target)

    if not target.get("url"):
        for text in text_sources:
            url = extract_first_web_url(text)
            if url:
                target["url"] = url
                break

    if target.get("url") and not target.get("host"):
        target["host"] = _host_from_url(target.get("url"))
    return _compact_target(target)


def merge_browser_target_into_scene_arguments(
    arguments: Mapping[str, Any] | None,
    *,
    structured_sources: Iterable[Any] = (),
    text_sources: Iterable[Any] = (),
) -> dict[str, Any]:
    payload = dict(arguments or {})
    environment_requirements = _as_dict(payload.get("environment_requirements"))
    context = _as_dict(payload.get("context"))
    existing = (
        payload.get("browser_target")
        or environment_requirements.get("browser_target")
        or context.get("browser_target")
    )
    target = derive_browser_target(
        existing=existing,
        structured_sources=(
            payload,
            environment_requirements,
            context,
            *tuple(structured_sources),
        ),
        text_sources=(
            payload.get("instruction"),
            payload.get("title"),
            *tuple(text_sources),
        ),
    )
    if not target:
        return payload

    payload["browser_target"] = target
    environment_requirements["browser_target"] = target
    context["browser_target"] = target
    payload["environment_requirements"] = environment_requirements
    payload["context"] = context
    return payload


def _browser_target_from_structured_source(source: Any) -> dict[str, Any]:
    payload = _as_dict(source)
    if not payload:
        return {}
    for key in ("browser_target", "browserTarget", "web_target", "webTarget"):
        candidate = _normalize_browser_target_shape(payload.get(key))
        if candidate:
            return candidate
    url = _optional_string(
        payload.get("target_url")
        or payload.get("targetUrl")
        or payload.get("browser_url")
        or payload.get("browserUrl")
    )
    if url:
        return _normalize_browser_target_shape({"url": url})
    return {}


def _normalize_browser_target_shape(value: Any) -> dict[str, Any]:
    payload = _as_dict(value)
    if not payload:
        return {}
    url = _optional_string(payload.get("url"))
    host = _optional_string(payload.get("host")) or _host_from_url(url)
    target = {
        "application": _optional_string(payload.get("application") or payload.get("app")),
        "window_title": _optional_string(payload.get("window_title") or payload.get("windowTitle") or payload.get("window")),
        "tab_id": _optional_int(payload.get("tab_id") or payload.get("tabId")),
        "host": host,
        "url": url,
        "url_pattern": _optional_string(payload.get("url_pattern") or payload.get("urlPattern")),
        "site_label": _optional_string(payload.get("site_label") or payload.get("siteLabel") or payload.get("site")),
    }
    return _compact_target(target)


def _merge_missing_target_fields(current: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    if not candidate:
        return dict(current)
    merged = dict(current)
    for key, value in candidate.items():
        if value not in (None, "", [], {}) and not merged.get(key):
            merged[key] = value
    if merged.get("url") and not merged.get("host"):
        merged["host"] = _host_from_url(merged.get("url"))
    return _compact_target(merged)


def _host_from_url(value: Any) -> str | None:
    url = _optional_string(value)
    if not url:
        return None
    parsed = urlparse(url)
    return parsed.netloc.lower() or None


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _optional_string(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _compact_target(target: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in target.items() if value not in (None, "", [], {})}
