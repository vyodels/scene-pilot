from __future__ import annotations


ADAPTIVE_STAGES: tuple[str, ...] = (
    "instruction_intake",
    "exploration_trial",
    "candidate_discovery",
    "candidate_probe",
    "candidate_outreach",
    "resume_collection",
    "candidate_scoring",
    "strategy_distill",
    "scale_execution",
    "candidate_archive",
)

ADAPTIVE_STAGE_SET = frozenset(ADAPTIVE_STAGES)
DEFAULT_ADAPTIVE_STAGE = "candidate_probe"


def resolve_adaptive_stage(*, task_type: str | None, explicit_stage: str | None = None) -> str:
    candidate = str(explicit_stage or "").strip() or str(task_type or "").strip()
    if candidate in ADAPTIVE_STAGE_SET:
        return candidate
    allowed = ", ".join(ADAPTIVE_STAGES)
    raise ValueError(f"Unsupported task_type/adaptive_stage: {candidate or '<empty>'}. Allowed stages: {allowed}")
