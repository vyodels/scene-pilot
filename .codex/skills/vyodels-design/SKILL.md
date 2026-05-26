---
name: vyodels-design
description: "Use for user-level execution governance: designing or executing complex plans, goals, migrations, multi-phase coding tasks, review-fix-verify loops, subagent coordination, completion audits, and deciding when work is actually done. Trigger when the user asks for plan design, goal contracts, complex task execution, implementation governance, or migration/architecture closure."
---

# Vyodels Design

This skill is the user's workflow for execution governance. It defines how to shape goals, design plans, run complex implementation batches, review work, close findings, and state completion.

It complements `karpathy-guidelines`: use `karpathy-guidelines` for baseline coding discipline, and use this skill when the task needs plan/goal governance, multi-step execution, or completion semantics.

## Quick Selection

- Goal definition, Plan mode, long-running goal, handoff, or completion semantics: read `references/generic-goal-contract.md`.
- Large plan, migration, architecture closure, legacy retirement, canonical source design, or adversarial plan review: read `references/plan-design-execution.md`.
- Multi-file implementation, runtime/schema/API/CLI/frontend workflow, high-risk coding, review-fix-verify loop, or subagent coordination: read `references/development-execution.md`.

For complex work, read the references in this order:

1. `references/generic-goal-contract.md`
2. `references/plan-design-execution.md`
3. `references/development-execution.md`

For narrow tasks, load only the matching reference.

## Operating Rules

- Current user instructions override this skill.
- Project `AGENTS.md`, specs, README, test instructions, and checked-in docs define project facts and technical constraints.
- This skill defines execution workflow; it is not a product fact source, task-state source, credential store, or substitute for project documentation.
- Do not declare a plan, slice, phase, task, or goal complete until the applicable reference's completion and review conditions are satisfied or the user explicitly accepts a deferral.
- If a required independent subagent review is unavailable, say so directly and do not label the affected work as accepted, passed, done, or complete unless the user explicitly waives that requirement for the current task.

## Reporting

When reporting progress, distinguish:

- focused check passed
- slice ready for review
- findings fixed and re-reviewed
- batch regression passed
- goal complete

Do not collapse these into a single "done" status unless the applicable completion criteria are actually met.
