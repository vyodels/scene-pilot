# Recruiting Business Skill Rubric

## Purpose
Use this rubric when creating or reviewing recruiting skills in this repo.

## A good recruiting skill must satisfy all of these
- The unit is a recruiting business action, not a browser action.
- The name is meaningful without webpage context.
- The input and output are structured.
- The skill can be reused across multiple UI paths.
- The summary and strategy stay at business level.

## Preferred business units
- Active JD incremental sync
- JD detail enrichment
- Recommendation page location
- Recommended candidate list extraction
- Online resume retrieval
- Conversation history extraction
- Greeting generation
- Ask-for-resume generation
- Ask-for-phone generation
- Ask-for-WeChat generation
- Candidate reply signal classification
- AI screening input normalization
- Candidate archive or cooldown decision

## When to add Python inline
Add `body.artifacts.python_inline` when:
- the action can run on structured input only
- the logic is deterministic
- the output shape is stable
- one call can finish the core business action

Typical examples:
- normalize candidate cards into canonical records
- diff remote JD list vs local JD list
- classify a reply as resume / phone / WeChat / decline / cooldown
- render outreach copy from candidate + JD facts

## When not to add Python inline
Do not add Python inline when the logic depends on:
- selector-level DOM operations
- fixed tab or route logic
- shell / filesystem / network side effects
- site-specific UI wording

## Review questions
1. If the site changed its UI, would this skill still make sense?
2. Can the core logic be run as one deterministic function?
3. Is the skill too broad and actually two or more business actions?
4. Did the draft accidentally leak browser-detail language?
