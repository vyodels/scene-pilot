# docs/specs

This directory contains the repository's long-term normative documents.

## Reading order
1. `2026-04-20-repo-agent-collaboration-standard.md` — shared entry rules for `AGENTS.md` / `CLAUDE.md` / `CLAUDE_cn.md`
2. `2026-04-20-agent-product-design-principles.md` — product-level design principles
3. `2026-04-20-dual-agent-product-architecture.md` — Assistant / Autonomous product architecture
4. `2026-04-20-autonomous-agent-runtime-constraints.md` — runtime, memory, prompt, tool, and UI boundary constraints
5. `2026-04-20-agent-intelligence-boundary-and-capability-evolution.md` — intelligence boundary and capability evolution rules
6. `2026-04-20-agent-system-and-recruiting-capability-architecture.md` — long-term skeleton for the overall Agent system and recruiting capability construction
7. `2026-04-20-candidate-target-data-model-spec.md` — canonical target data model for candidate, application, and JD entities
8. `2026-04-29-business-fact-contract-governance.md` — business fact contract governance across backend, shared contracts, and desktop UI

## Contract
- `docs/specs/` holds long-term truth only
- plans, handoffs, migration steps, and historical notes do not belong here
- new spec documents must be user-confirmed before becoming canonical
- repo-level Agent assets should use `.recruit-agent/` as the unified root: `prompts/`, `skills/`, and plugin assets/config/metadata belong there
- `services/backend/src/recruit_agent/plugins/**` refers to backend thin runtime shell / mount code, not the canonical home for project-level plugin assets
