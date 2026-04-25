# docs/plan

`docs/plan/` is the new home for implementation plans.

## Directory contract

- `active/`: plans that still guide ongoing implementation
- `completed/`: plans that are substantially implemented and may still be mined for stable conclusions
- `archive/`: plans that were superseded or kept only for historical reference

## Authority

Plans are not long-term truth.
Long-term design truth lives in `docs/specs/`.

When documents conflict, use this order:

1. `docs/specs/`
2. user-confirmed distilled conclusions from completed plans
3. the newest same-topic active plan
4. older plans and historical docs
5. current implementation details

## Migration note

Legacy plan content has been migrated into `docs/plan/`.
New entrypoints should prefer `docs/plan/`; old `docs/superpowers/plans/` paths are historical only and should no longer be used as entrypoints.

## Project asset note

Plans should use the same project wording:

- `.recruit-agent/` is the unified root for repo-level Agent assets, including `prompts/`, `skills/`, and plugin assets/config/metadata
- `services/backend/src/recruit_agent/plugins/**` refers to backend thin runtime shell / mount code that loads and mounts those plugin assets; it is not the canonical home for project-level plugin assets

## Current index

### active
- [`active/2026-04-19-autonomous-e2e-and-chat-overlay-plan.md`](./active/2026-04-19-autonomous-e2e-and-chat-overlay-plan.md)
- [`active/2026-04-19-autonomous-ui-e2e-test-plan.md`](./active/2026-04-19-autonomous-ui-e2e-test-plan.md)
- [`active/2026-04-24-recruit-agent-browser-computer-runtime-follow-up-plan.md`](./active/2026-04-24-recruit-agent-browser-computer-runtime-follow-up-plan.md)

### completed
- [`completed/2026-04-17-canonical-entity-naming-and-schema-plan.md`](./completed/2026-04-17-canonical-entity-naming-and-schema-plan.md)
- [`completed/2026-04-19-agent-v2-direct-cutover-plan.md`](./completed/2026-04-19-agent-v2-direct-cutover-plan.md)
- [`completed/2026-04-19-agent-v2-terminology-convergence-plan.md`](./completed/2026-04-19-agent-v2-terminology-convergence-plan.md)
- [`completed/2026-04-20-autonomous-scene-context-delegation-plan.md`](./completed/2026-04-20-autonomous-scene-context-delegation-plan.md)

### archive
- [`archive/2026-04-16-candidate-target-model-unification.md`](./archive/2026-04-16-candidate-target-model-unification.md)
- [`archive/2026-04-20-recruiting-workspace-information-architecture-draft.md`](./archive/2026-04-20-recruiting-workspace-information-architecture-draft.md)
- [`archive/agent-v2-design-summary.md`](./archive/agent-v2-design-summary.md)
- [`archive/agent-v2-implementation-spec.md`](./archive/agent-v2-implementation-spec.md)
- [`archive/agent架构设计.md`](./archive/agent架构设计.md)
- [`archive/autonomous-agent-improvement-plan.md`](./archive/autonomous-agent-improvement-plan.md)
- [`archive/general-automation-runtime.md`](./archive/general-automation-runtime.md)
- [`archive/recruiting-workflow-ux-redesign-plan.md`](./archive/recruiting-workflow-ux-redesign-plan.md)
- [`archive/recruiting-workflow-ux-redesign-plan_cn.md`](./archive/recruiting-workflow-ux-redesign-plan_cn.md)
- [`archive/2026-04-20-agents-claude-shared-standard-draft.md`](./archive/2026-04-20-agents-claude-shared-standard-draft.md)
- [`archive/2026-04-16-recruitment-kanban-design.md`](./archive/2026-04-16-recruitment-kanban-design.md)
