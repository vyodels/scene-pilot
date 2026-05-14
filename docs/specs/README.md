# docs/specs

This directory contains long-term normative documents only. It must stay small.

## Active Specs

1. `2026-04-20-repo-agent-collaboration-standard.md`
   Shared repository entry rules. `AGENTS.md` is the only entry body; `CLAUDE.md` is a symlink to it.

2. `2026-05-11-agent-runtime-product-boundary-spec.md`
   Agent runtime, product adapter, Assistant / Autonomous, capability evolution, permission, and business isolation boundaries.

3. `2026-05-11-recruiting-business-capability-data-spec.md`
   Recruiting business capability, skill, business fact, candidate/JD/application data, memory, and UI/API field governance.

4. `2026-05-14-desktop-frontend-component-reuse-spec.md`
   Desktop frontend shared component, topbar, toolbar, sidebar, and CSS ownership rules.

## Hard Boundary

`services/backend/src/recruit_agent/agent_runtime/**` must remain business-agnostic.

Business enters Agent execution only through adapter-built context, prompt assets, tool schemas, tool results, skills, plugins, MCP capabilities, and product-layer state mapping.
