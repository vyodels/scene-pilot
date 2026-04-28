from __future__ import annotations

import re
from typing import Any


AGE_PATTERN = re.compile(r"(\d{2})\s*岁")
EXPERIENCE_PATTERN = re.compile(r"(\d{1,2})\s*年(?:以上)?")
EDUCATION_PATTERN = re.compile(r"博士|硕士|本科|大专|专科|高中|中专")
WORK_STATUS_PATTERN = re.compile(r"离职|在职|已到岗|应届")


def extract_resume_structured_facts(text: str | None, contact_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = str(text or "").strip()
    contact = dict(contact_snapshot or {})
    facts: dict[str, Any] = {}
    age_match = AGE_PATTERN.search(raw)
    if age_match:
        facts["age"] = int(age_match.group(1))
    experience_match = EXPERIENCE_PATTERN.search(raw)
    if experience_match:
        facts["experience_text"] = f"{experience_match.group(1)}年{'以上' if f'{experience_match.group(1)}年以上' in raw else ''}"
        facts["experience_years"] = int(experience_match.group(1))
    education_match = EDUCATION_PATTERN.search(raw)
    if education_match:
        facts["education"] = education_match.group(0)
    work_status_match = WORK_STATUS_PATTERN.search(raw)
    if work_status_match:
        facts["work_status"] = work_status_match.group(0)
    for source_key, target_key in (
        ("school", "school"),
        ("university", "school"),
        ("college", "school"),
        ("major", "major"),
        ("profession", "major"),
        ("phone", "phone"),
        ("mobile", "phone"),
        ("email", "email"),
    ):
        value = str(contact.get(source_key) or "").strip()
        if value and target_key not in facts:
            facts[target_key] = value
    return facts
