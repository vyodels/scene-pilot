from __future__ import annotations

from recruit_agent.product_adapters.mcp_resource_context import (
    build_mcp_resource_context,
    extract_mcp_resource_context_policy,
)


class FakeMcpRegistry:
    def read_mcp_resource(self, *, uri: str, server_key: str = "", server_id: str = "") -> dict[str, object]:
        return {
            "server_id": server_id or "srv-1",
            "server_key": server_key or "docs",
            "name": "Docs",
            "uri": uri,
            "resource": {"text": "A" * 300},
        }


def test_extract_mcp_resource_context_policy_requires_explicit_resources() -> None:
    policy = extract_mcp_resource_context_policy(
        {"context_hints": {"mcp_resource_context": {"resources": [{"server_key": "docs", "uri": "memo://one"}]}}}
    )

    assert policy["resources"] == [{"server_key": "docs", "server_id": "", "uri": "memo://one"}]


def test_build_mcp_resource_context_reads_allowlisted_resources_and_truncates() -> None:
    contexts = build_mcp_resource_context(
        FakeMcpRegistry(),
        {"resources": [{"server_key": "docs", "uri": "memo://one"}], "max_chars_per_resource": 200},
    )

    assert contexts[0]["uri"] == "memo://one"
    assert contexts[0]["content"] == "A" * 200
    assert contexts[0]["truncated"] is True


def test_build_mcp_resource_context_does_not_auto_read_without_policy() -> None:
    assert build_mcp_resource_context(FakeMcpRegistry(), {"resources": []}) == []
