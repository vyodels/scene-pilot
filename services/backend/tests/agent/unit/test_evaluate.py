from __future__ import annotations

import pytest

from recruit_agent.agent_runtime.evaluate import evaluate
from recruit_agent.runtime.limits import RoundLimits
from recruit_agent.agent_runtime.models import Deliberation, Effects, LLMUsage


@pytest.mark.parametrize(
    ("final_content", "expected_status", "expected_gate_signal"),
    [
        ('{"status":"blocked","next_step":"等待继续条件满足"}', "escalate", "escalate"),
        ("status=wait_human", "wait_human", "wait_human"),
        ('{"status":"failed","error":"boom"}', "error", "escalate"),
        ("status=error", "error", "escalate"),
    ],
)
def test_evaluate_uses_explicit_non_success_final_content(
    final_content: str,
    expected_status: str,
    expected_gate_signal: str,
) -> None:
    outcome = evaluate(
        Deliberation(
            final_content=final_content,
            usage=LLMUsage(),
        ),
        Effects(),
    )

    assert outcome.status == expected_status
    assert outcome.gate_signal == expected_gate_signal
    assert outcome.final_output == final_content


def test_evaluate_keeps_explicit_success_payload_complete() -> None:
    outcome = evaluate(
        Deliberation(
            final_content='{"status":"completed","created":1}',
            usage=LLMUsage(),
        ),
        Effects(),
    )

    assert outcome.status == "complete"
    assert outcome.gate_signal == "goal_done"


def test_evaluate_default_token_budget_is_unlimited() -> None:
    outcome = evaluate(
        Deliberation(
            final_content='{"status":"completed","created":1}',
            usage=LLMUsage(total_tokens=99_999_999),
        ),
        Effects(),
    )

    assert outcome.status == "complete"
    assert outcome.gate_signal == "goal_done"


def test_evaluate_explicit_token_budget_still_gates_round() -> None:
    outcome = evaluate(
        Deliberation(
            final_content='{"status":"completed","created":1}',
            usage=LLMUsage(total_tokens=101),
        ),
        Effects(),
        limits=RoundLimits(token_budget=100),
    )

    assert outcome.status == "continue"
    assert outcome.gate_signal == "budget_exhausted"
