from __future__ import annotations

import json
import os
import socket
import tempfile
import uuid
from dataclasses import dataclass, field
from typing import Any


class BrowserMcpError(RuntimeError):
    pass


def _default_socket_path() -> str:
    return os.environ.get("MCP_BROWSER_CHROME_SOCKET") or os.path.join(tempfile.gettempdir(), "browser-mcp.sock")


def _normalize_text(value: Any, *, limit: int | None = None) -> str:
    text = str(value or "")
    text = text.replace("\xa0", " ")
    text = "\n".join(part.strip() for part in text.splitlines() if part.strip())
    if limit is not None:
        return text[:limit]
    return text


@dataclass(slots=True)
class BrowserMcpClient:
    socket_path: str = field(default_factory=_default_socket_path)
    timeout_seconds: float = 8.0

    def call(self, command_name: str, arguments: dict[str, Any] | None = None) -> Any:
        request_id = uuid.uuid4().hex
        payload = {
            "id": request_id,
            "type": "browser_command",
            "command": {
                "name": command_name,
                "arguments": dict(arguments or {}),
            },
        }

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(self.timeout_seconds)
                connection.connect(self.socket_path)
                connection.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
                buffer = b""
                while True:
                    chunk = connection.recv(65536)
                    if not chunk:
                        break
                    buffer += chunk
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        line = line.strip()
                        if not line:
                            continue
                        response = json.loads(line.decode("utf-8"))
                        if response.get("id") != request_id:
                            continue
                        if not bool(response.get("ok", False)):
                            message = (
                                response.get("error", {}).get("message")
                                or response.get("error")
                                or f"browser command failed: {command_name}"
                            )
                            raise BrowserMcpError(str(message))
                        return response.get("result")
        except FileNotFoundError as exc:
            raise BrowserMcpError(f"browser-mcp socket not found: {self.socket_path}") from exc
        except socket.timeout as exc:
            raise BrowserMcpError(f"browser-mcp command timed out: {command_name}") from exc
        except OSError as exc:
            raise BrowserMcpError(f"browser-mcp unavailable at {self.socket_path}: {exc}") from exc
        raise BrowserMcpError(f"browser-mcp returned no response for {command_name}")

    def list_tabs(self) -> list[dict[str, Any]]:
        result = self.call("browser_list_tabs", {})
        if isinstance(result, dict):
            return [dict(item) for item in list(result.get("tabs") or []) if isinstance(item, dict)]
        if isinstance(result, list):
            return [dict(item) for item in result if isinstance(item, dict)]
        return []

    def execute_script(self, tab_id: int, script: str) -> Any:
        result = self.call("browser_execute_script", {"tabId": int(tab_id), "script": script})
        if isinstance(result, dict) and "result" in result and set(result.keys()).issubset({"success", "result"}):
            return result.get("result")
        return result

    def snapshot(self, tab_id: int, *, max_text_length: int = 4000) -> dict[str, Any]:
        result = self.call(
            "browser_snapshot",
            {
                "tabId": int(tab_id),
                "maxTextLength": int(max_text_length),
                "interactiveLimit": 50,
            },
        )
        return dict(result) if isinstance(result, dict) else {}

    def is_available(self) -> bool:
        try:
            self.list_tabs()
        except BrowserMcpError:
            return False
        return True

    def find_tab(self, *, url_contains: str | None = None, title_contains: str | None = None) -> dict[str, Any] | None:
        tabs = self.list_tabs()
        if not tabs:
            return None

        normalized_url = (url_contains or "").strip().lower()
        normalized_title = (title_contains or "").strip().lower()

        def _matches(tab: dict[str, Any]) -> bool:
            url = str(tab.get("url") or "").lower()
            title = str(tab.get("title") or "").lower()
            if normalized_url and normalized_url not in url:
                return False
            if normalized_title and normalized_title not in title:
                return False
            return True

        active_matches = [tab for tab in tabs if bool(tab.get("active")) and _matches(tab)]
        if active_matches:
            return dict(active_matches[0])

        matches = [tab for tab in tabs if _matches(tab)]
        if matches:
            return dict(matches[0])
        return None


def _boss_scene_script(*, limit: int = 8) -> str:
    return f"""
(() => {{
  const iframe = document.querySelector('iframe[name="recommendFrame"]');
  const doc = iframe && iframe.contentDocument ? iframe.contentDocument : document;
  const win = iframe && iframe.contentWindow ? iframe.contentWindow : window;
  const clean = (value, limit) => {{
    const text = String(value || '')
      .replace(/\\u00a0/g, ' ')
      .replace(/\\r/g, '\\n')
      .replace(/\\n+/g, '\\n')
      .split('\\n')
      .map((item) => item.trim())
      .filter(Boolean)
      .join('\\n');
    return typeof limit === 'number' ? text.slice(0, limit) : text;
  }};
  const cardRoots = Array.from(
    doc.querySelectorAll('.candidate-card-wrap .card-inner, .card-inner.common-wrap, [data-geekid]')
  )
    .map((item) => item.closest('[data-geekid]') || item)
    .filter((item, index, items) => items.indexOf(item) === index)
    .slice(0, {int(limit)});
  const cards = cardRoots.map((root, index) => {{
    const candidateId = root.getAttribute('data-geekid') || root.getAttribute('data-geek') || `candidate_${{index + 1}}`;
    const buttonTexts = Array.from(root.querySelectorAll('button, .btn'))
      .map((node) => clean(node.textContent, 64))
      .filter(Boolean);
    const links = Array.from(root.querySelectorAll('a'))
      .map((node) => ({{
        text: clean(node.textContent, 96),
        href: node.getAttribute('href'),
      }}))
      .filter((item) => item.text);
    const text = clean(root.innerText || root.textContent, 1400);
    const lines = text.split('\\n').map((item) => item.trim()).filter(Boolean);
    const nameNode =
      root.querySelector('.name') ||
      root.querySelector('.geek-name') ||
      Array.from(root.querySelectorAll('*')).find((node) => /name/i.test(node.className || ''));
    const name = clean(nameNode ? nameNode.textContent : lines[1] || lines[0] || '', 80) || candidateId;
    return {{
      candidate_id: candidateId,
      platform_candidate_id: candidateId,
      name,
      summary: lines.slice(0, 6).join(' | '),
      profile_text: text,
      lines: lines.slice(0, 32),
      buttons: buttonTexts.slice(0, 8),
      links: links.slice(0, 8),
      locator: {{
        data_geekid: candidateId,
        frame: iframe ? iframe.getAttribute('name') || 'recommendFrame' : null,
      }},
    }};
  }});
  const searchInputs = Array.from(doc.querySelectorAll('input, textarea'))
    .map((node) => ({{
      label: clean(node.getAttribute('placeholder') || node.getAttribute('aria-label') || node.name || node.className, 80),
      value: clean(node.value || '', 80),
      type: node.type || node.tagName.toLowerCase(),
    }}))
    .filter((item) => item.label || item.value)
    .slice(0, 8);
  const pageButtons = Array.from(doc.querySelectorAll('button, a'))
    .map((node) => clean(node.textContent, 64))
    .filter(Boolean)
    .slice(0, 24);
  return {{
    ok: true,
    iframe_name: iframe ? iframe.getAttribute('name') || 'recommendFrame' : null,
    page_title: clean(doc.title || document.title, 120),
    page_url: clean(win.location && win.location.href ? win.location.href : location.href, 400),
    page_text_excerpt: clean(doc.body ? doc.body.innerText : document.body ? document.body.innerText : '', 1800),
    candidate_cards: cards,
    search_inputs: searchInputs,
    page_buttons: pageButtons,
  }};
}})()
""".strip()


def find_boss_tab(client: BrowserMcpClient) -> dict[str, Any] | None:
    return client.find_tab(url_contains="zhipin.com") or client.find_tab(title_contains="boss")


def capture_boss_scene(client: BrowserMcpClient, *, limit: int = 8) -> dict[str, Any] | None:
    tab = find_boss_tab(client)
    if tab is None:
        return None

    raw = client.execute_script(int(tab["id"]), _boss_scene_script(limit=limit))
    if not isinstance(raw, dict) or not bool(raw.get("ok", True)):
        return None

    cards = [dict(item) for item in list(raw.get("candidate_cards") or []) if isinstance(item, dict)]
    page_url = str(raw.get("page_url") or tab.get("url") or "")
    page_title = str(raw.get("page_title") or tab.get("title") or "BOSS直聘")
    search_inputs = [dict(item) for item in list(raw.get("search_inputs") or []) if isinstance(item, dict)]
    page_buttons = [str(item) for item in list(raw.get("page_buttons") or []) if str(item).strip()]
    page_excerpt = _normalize_text(raw.get("page_text_excerpt"), limit=1800)

    observed_entities: list[dict[str, Any]] = [
        {
            "kind": "workspace",
            "label": page_title,
            "interactive": True,
            "signals": ["listing_surface", "boss_workspace"],
            "locator": {"tab_id": tab.get("id")},
            "attributes": {
                "url": page_url,
                "iframe_name": raw.get("iframe_name"),
            },
        }
    ]
    affordances: list[dict[str, Any]] = []

    for search_input in search_inputs[:3]:
        affordances.append(
            {
                "kind": "input",
                "label": str(search_input.get("label") or "搜索输入"),
                "action": "fill",
                "enabled": True,
                "signals": ["search_surface", "input_surface"],
                "metadata": dict(search_input),
            }
        )

    for index, card in enumerate(cards):
        candidate_id = str(card.get("candidate_id") or card.get("platform_candidate_id") or f"candidate_{index + 1}")
        name = str(card.get("name") or candidate_id)
        profile_text = _normalize_text(card.get("profile_text"), limit=1400)
        summary = _normalize_text(card.get("summary"), limit=320)
        lines = [str(item) for item in list(card.get("lines") or []) if str(item).strip()]
        buttons = [str(item) for item in list(card.get("buttons") or []) if str(item).strip()]
        links = [dict(item) for item in list(card.get("links") or []) if isinstance(item, dict)]

        observed_entities.append(
            {
                "kind": "candidate_card",
                "label": name,
                "entity_id": candidate_id,
                "role": "candidate",
                "interactive": True,
                "signals": ["listing_surface", "candidate_profile", "boss_candidate"],
                "locator": {
                    "tab_id": tab.get("id"),
                    "frame": raw.get("iframe_name"),
                    "data_geekid": candidate_id,
                },
                "attributes": {
                    "summary": summary,
                    "profile_text": profile_text,
                    "lines": lines[:24],
                    "buttons": buttons[:6],
                    "links": links[:4],
                },
            }
        )
        if profile_text:
            observed_entities.append(
                {
                    "kind": "candidate_detail",
                    "label": f"{name} 档案摘录",
                    "entity_id": f"{candidate_id}:detail",
                    "interactive": False,
                    "signals": ["detail_surface", "embedded_profile"],
                    "locator": {
                        "tab_id": tab.get("id"),
                        "frame": raw.get("iframe_name"),
                        "data_geekid": candidate_id,
                    },
                    "attributes": {
                        "profile_text": profile_text,
                    },
                }
            )
        affordances.append(
            {
                "kind": "candidate_card",
                "label": f"查看 {name}",
                "action": "open",
                "target": candidate_id,
                "enabled": True,
                "signals": ["listing_surface", "detail_surface"],
                "locator": {
                    "tab_id": tab.get("id"),
                    "frame": raw.get("iframe_name"),
                    "data_geekid": candidate_id,
                },
                "metadata": {
                    "candidate_name": name,
                },
            }
        )
        if any("招呼" in text for text in buttons):
            affordances.append(
                {
                    "kind": "button",
                    "label": f"向 {name} 打招呼",
                    "action": "send",
                    "target": candidate_id,
                    "enabled": True,
                    "requires_confirmation": True,
                    "signals": ["write_surface", "approval_sensitive"],
                    "locator": {
                        "tab_id": tab.get("id"),
                        "frame": raw.get("iframe_name"),
                        "data_geekid": candidate_id,
                        "button_text": "打招呼",
                    },
                }
            )

    if not affordances and page_buttons:
        affordances.extend(
            {
                "kind": "button",
                "label": button_text,
                "action": "click",
                "enabled": True,
                "signals": ["browser_surface"],
            }
            for button_text in page_buttons[:4]
        )

    return {
        "source": "browser",
        "environment_key": "recruiting:boss_recommend_candidates",
        "status": "captured",
        "url": page_url,
        "title": page_title,
        "page_type": "listing_surface",
        "capability_hints": ["browser", "search", "document", "approval"],
        "observed_entities": observed_entities,
        "affordances": affordances,
        "runtime_metadata": {
            "browser_mcp": True,
            "browser_tab_id": tab.get("id"),
            "browser_window_id": tab.get("windowId"),
            "browser_tab_title": tab.get("title"),
            "browser_tab_url": tab.get("url"),
            "iframe_name": raw.get("iframe_name"),
            "candidate_count": len(cards),
            "candidate_cards": cards,
            "search_inputs": search_inputs,
            "page_buttons": page_buttons[:12],
            "page_text_excerpt": page_excerpt,
        },
    }


def discover_boss_candidates(client: BrowserMcpClient, query: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    scene = capture_boss_scene(client, limit=int((query or {}).get("limit") or 12))
    if scene is None:
        return []

    search_terms = _normalize_text(
        (query or {}).get("search") or (query or {}).get("keyword") or (query or {}).get("q"),
        limit=160,
    ).lower()
    cards = [dict(item) for item in list((scene.get("runtime_metadata") or {}).get("candidate_cards") or []) if isinstance(item, dict)]
    results: list[dict[str, Any]] = []
    for card in cards:
        name = str(card.get("name") or card.get("candidate_id") or "候选人")
        summary = _normalize_text(card.get("summary"), limit=400)
        profile_text = _normalize_text(card.get("profile_text"), limit=1400)
        searchable_text = " ".join(
            [
                str(card.get("candidate_id") or ""),
                name,
                summary,
                profile_text,
            ]
        ).lower()
        if search_terms and search_terms not in searchable_text:
            continue
        results.append(
            {
                "candidate_id": str(card.get("candidate_id") or ""),
                "platform_candidate_id": str(card.get("platform_candidate_id") or card.get("candidate_id") or ""),
                "name": name,
                "platform": "boss",
                "status": "discovered",
                "contact_info": {
                    "summary": summary,
                    "title": summary.split("|")[0].strip() if summary else None,
                    "location": next((line for line in list(card.get("lines") or []) if "北京" in str(line)), None),
                    "tags": [item for item in list(card.get("buttons") or []) if isinstance(item, str)],
                },
                "online_resume_text": profile_text,
                "source_scene": {
                    "url": scene.get("url"),
                    "title": scene.get("title"),
                    "page_type": scene.get("page_type"),
                },
                "profile_or_resume_evidence": {
                    "kind": "embedded_profile_card",
                    "candidate_id": card.get("candidate_id"),
                    "summary": summary,
                    "text_excerpt": profile_text[:900],
                },
                "resume_artifact_status": "profile_evidence_available",
                "upload_status": "not_started",
                "raw_scene_locator": dict(card.get("locator") or {}),
            }
        )
    return results


def inspect_boss_candidate(client: BrowserMcpClient, candidate_id: str) -> dict[str, Any]:
    candidates = discover_boss_candidates(client, {"limit": 12})
    for candidate in candidates:
        if str(candidate.get("candidate_id")) == candidate_id or str(candidate.get("platform_candidate_id")) == candidate_id:
            return candidate
    raise KeyError(f"Unknown live Boss candidate: {candidate_id}")
