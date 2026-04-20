---
name: recruiting-skill-authoring
description: Create or update recruiting-domain skills, skill distillation prompts, and skill contracts that must stay at business-semantic granularity. Use when Codex needs to turn recruiting workflows such as JD sync, candidate discovery, outreach, resume collection, conversation parsing, scoring, or archive decisions into reusable skills, especially when those skills should prefer Python inline assets over repeated LLM tool loops.
---

# Recruiting Skill Authoring

## Overview

Use this skill to create or revise recruiting skills that remain business-semantic, reusable, and low-cost to execute.

Read [`docs/specs/2026-04-20-recruiting-skill-distillation-standard.md`](../../../docs/specs/2026-04-20-recruiting-skill-distillation-standard.md) first. That spec is the project truth for skill granularity, Python asset priority, and anti-patterns.

## Workflow

### 1. Pick the right business unit

Start from the business action, not from the webpage action.

Prefer units like:
- active JD incremental sync
- recommendation page location
- recommended candidate list extraction
- online resume retrieval
- conversation history retrieval
- first-touch greeting
- ask for resume
- ask for phone
- ask for WeChat
- candidate response signal classification
- AI screening input normalization
- candidate archive or cooldown

Reject units like:
- click the second tab
- read a specific button
- navigate a fixed route
- scrape one site-specific DOM fragment

If the draft spans multiple business outcomes, split it before writing.

### 2. Decide whether Python inline is appropriate

Prefer Python inline when the skill can be expressed as:
- structured input
- deterministic business logic
- structured output

Good Python inline candidates:
- diff active JD lists against local records
- normalize candidate list payloads
- classify online resume retrieval paths
- parse conversation history into signals
- render first-touch or follow-up messages
- aggregate scoring inputs
- classify candidate reply intent

Do not use Python inline for:
- selector-driven browser flows
- fixed page routing
- file system, shell, or network side effects
- logic that only works for one site layout

If Python inline is not stable enough, keep the skill textual and set `execution_hints.executor_mode` to `tool_or_llm`.

### 3. Write the contract

Use existing project fields only:
- `strategy`
- `body`
- `execution_hints`
- `skill_metadata`

When Python inline is present, prefer this shape:

```json
{
  "body": {
    "summary": "One-sentence business summary",
    "checklist": ["Key checks"],
    "anti_patterns": ["What not to do"],
    "artifacts": {
      "python_inline": {
        "entrypoint": "run",
        "code": "def run(payload, context):\n    return {'status': 'completed'}",
        "input_contract": {},
        "output_contract": {}
      }
    }
  },
  "execution_hints": {
    "executor_mode": "python_inline"
  }
}
```

Keep `strategy.instruction` and `body.summary` at business level even when code is included.

### 4. Run the anti-pattern check

Before finalizing, ask:
- Did I write a recruiting business action or a webpage action?
- Can another site with a different UI still reuse this skill?
- Should this be split into two skills?
- Could the core logic be one Python inline call?
- Did I leak DOM, selector, URL, button text, or tab logic into the skill?

## References

- Read [`references/recruiting-business-skill-rubric.md`](./references/recruiting-business-skill-rubric.md) for the recruiting skill rubric and examples.
- Use [`scripts/render_python_inline_stub.py`](./scripts/render_python_inline_stub.py) when you need a deterministic starter for `body.artifacts.python_inline`.

## Output Standard

Deliver:
- a business-semantic skill contract or SKILL.md update
- an explicit decision on whether Python inline is included
- any remaining blocker if the skill cannot yet be made reusable
