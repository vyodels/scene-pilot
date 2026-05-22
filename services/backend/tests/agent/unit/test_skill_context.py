from __future__ import annotations

from recruit_station.models.domain import Skill
from recruit_station.skills.context import build_skill_context_injections


def test_build_skill_context_injections_uses_active_and_trial_skills_only() -> None:
    active = Skill(
        skill_id="candidate-summary",
        name="Candidate summary",
        status="active",
        description="Summarize candidate signals.",
        trigger_hint="Use when candidate conversation needs summarizing.",
        body={"instructions": "Extract stable candidate signals only."},
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        skill_metadata={"environment_scope": "real_site_verified", "ignored": True},
    )
    trial = Skill(
        skill_id="resume-parser",
        name="Resume parser",
        status="trial",
        body={"summary": "Parse resume facts."},
    )
    draft = Skill(
        skill_id="draft-only",
        name="Draft only",
        status="draft",
        body={"instructions": "Do not inject."},
    )

    injections = build_skill_context_injections([draft, trial, active])

    assert [item.skill_id for item in injections] == ["candidate-summary", "resume-parser"]
    payload = injections[0].to_prompt_payload()
    assert payload["instructions"] == "Extract stable candidate signals only."
    assert payload["metadata"] == {"environment_scope": "real_site_verified"}


def test_build_skill_context_injections_respects_limit() -> None:
    skills = [
        Skill(skill_id=f"skill-{index}", name=f"Skill {index}", status="active")
        for index in range(3)
    ]

    injections = build_skill_context_injections(skills, limit=2)

    assert [item.skill_id for item in injections] == ["skill-0", "skill-1"]


def test_build_skill_context_injections_prioritizes_explicit_skill_ids() -> None:
    candidate_summary = Skill(
        skill_id="candidate-summary",
        name="Candidate summary",
        status="active",
    )
    resume_parser = Skill(
        skill_id="resume-parser",
        name="Resume parser",
        status="trial",
    )
    archived = Skill(
        skill_id="archive-candidate",
        name="Archive candidate",
        status="disabled",
    )

    injections = build_skill_context_injections(
        [candidate_summary, resume_parser, archived],
        explicit_skill_ids=["resume-parser", "archive-candidate"],
    )

    assert [item.skill_id for item in injections] == ["resume-parser", "candidate-summary"]


def test_build_skill_context_injections_uses_trigger_relevance_for_selection() -> None:
    unrelated = Skill(
        skill_id="calendar-coordination",
        name="Calendar coordination",
        status="active",
        trigger_hint="Use when arranging interview times.",
    )
    resume_parser = Skill(
        skill_id="resume-parser",
        name="Resume parser",
        status="active",
        description="Extract resume facts.",
        trigger_hint="Use when parsing resume documents.",
        body={"summary": "Parse work history, education, and candidate signals."},
        skill_metadata={"trigger_examples": ["Parse a PDF resume into structured facts."]},
    )

    injections = build_skill_context_injections(
        [unrelated, resume_parser],
        query="Need to parse a resume PDF into candidate facts.",
        limit=1,
    )

    assert [item.skill_id for item in injections] == ["resume-parser"]


def test_build_skill_context_injections_exposes_asset_manifest_without_code() -> None:
    skill = Skill(
        skill_id="jd-diff",
        name="JD diff",
        status="active",
        body={
            "summary": "Diff remote and local JDs.",
            "artifacts": {
                "python_inline": {
                    "entrypoint": "run",
                    "code": "def run(payload, context):\n    return {'status': 'completed'}\n",
                    "input_contract": {"type": "object"},
                    "output_contract": {"type": "object"},
                }
            },
        },
        execution_hints={"executor_mode": "python_inline"},
        last_health_status="healthy",
    )

    payload = build_skill_context_injections([skill])[0].to_prompt_payload()

    assert payload["execution"] == {
        "executor_mode": "python_inline",
        "asset_kinds": ["python_inline"],
        "tool_name": "execute_skill_asset",
        "python_inline": {
            "entrypoint": "run",
            "input_contract": {"type": "object"},
            "output_contract": {"type": "object"},
        },
        "last_health_status": "healthy",
    }
    assert "def run" not in str(payload)


def test_build_skill_context_injections_uses_category_relevance_for_ordering() -> None:
    outreach = Skill(
        skill_id="outreach-draft",
        name="Outreach draft",
        status="active",
        category="outreach",
    )
    screening = Skill(
        skill_id="screening-score",
        name="Screening score",
        status="active",
        category="screening",
    )

    injections = build_skill_context_injections(
        [outreach, screening],
        category="screening",
    )

    assert [item.skill_id for item in injections] == ["screening-score", "outreach-draft"]


def test_build_skill_context_injections_matches_explicit_name_and_alias() -> None:
    alias_skill = Skill(
        skill_id="resume-parser",
        name="Resume parser",
        status="active",
        skill_metadata={"aliases": ["cv parser"]},
    )
    named_skill = Skill(
        skill_id="candidate-summary",
        name="Candidate summary",
        status="active",
    )

    injections = build_skill_context_injections(
        [named_skill, alias_skill],
        explicit_skill_ids=["cv parser", "Candidate summary"],
    )

    assert [item.skill_id for item in injections] == ["resume-parser", "candidate-summary"]


def test_build_skill_context_injections_applies_token_budget_and_truncation() -> None:
    large = Skill(
        skill_id="large-skill",
        name="Large Skill",
        status="active",
        body={"instructions": "A" * 5000},
        input_schema={"type": "object", "description": "B" * 5000},
    )
    small = Skill(
        skill_id="small-skill",
        name="Small Skill",
        status="active",
        body={"instructions": "small"},
    )

    injections = build_skill_context_injections(
        [large, small],
        token_budget=80,
        max_instruction_chars=100,
        max_schema_chars=100,
    )

    assert injections
    assert injections[0].skill_id == "large-skill"
    payload = injections[0].to_prompt_payload()
    assert "[truncated]" in payload["instructions"]
    assert payload["input_schema"]["_truncated"] is True
