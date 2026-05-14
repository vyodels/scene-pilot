# Desktop UI Commercialization And Component Reuse Handoff

Date: 2026-05-14
Repo: `/Users/didi/AgentProjects/recruit-agent`

## Current State

This handoff replaces the previous AgentDefinition unification handoff as the current completed UI/product continuity entry.

The desktop UI pass implemented three connected changes:

- Funnel board commercialization: the funnel page now focuses on recruiting conversion analysis, KPI cards, success-path funnel analytics, stage conversion, job comparison, diagnostics, and data-driven candidate details.
- Dashboard responsibility convergence: the home page now behaves as an operations command center, keeping action queues and replacing deep conversion detail with a recruiting analysis entry.
- Navigation and toolbar reuse: sidebar items, global topbars, and page-level toolbars now share common primitives so future spacing/height/control changes are centralized.

## Important New / Updated Frontend Primitives

- `apps/desktop/src/components/PageToolbar.tsx`
- `apps/desktop/src/components/ToolbarControls.tsx`
- `apps/desktop/src/components/TopBar.tsx`
- `apps/desktop/src/components/Sidebar.tsx`
- `apps/desktop/src/components/AppLayout.tsx`

Rules are now documented in:

```text
docs/specs/2026-05-14-desktop-frontend-component-reuse-spec.md
```

The core rule: topbar-like rows use `TopBar` or `PageToolbar`; toolbar controls use `ToolbarField`, `ToolbarInput`, `ToolbarSelect`, `ToolbarButton`, and `ToolbarRefreshButton`. Feature CSS may adjust layout only, not redefine core height, hover, focus, disabled, or refresh styles.

## Sidebar Changes

- Removed the top sidebar expand/collapse button.
- Removed the old sidebar footer area.
- Settings now appears directly below Agent management.
- Agent management, Settings, and expand/collapse use the same `workspace-sidebar__item` structure as normal navigation items.
- Clicking `职位管理` no longer expands the sidebar.
- The explicit sidebar toggle remains in the lower nav group and uses the same item styling as the rest of the sidebar.
- Sidebar width is driven from `AppLayout` through `--workspace-sidebar-width` so layout and sidebar width share the same source.

## Toolbar / Topbar Changes

Topbar and page-level toolbar heights are standardized on `--layout-topnav-height`.

Converted to shared toolbar primitives:

- global workspace topbar
- dashboard action row
- Agent management top controls
- JD management filter/action rows
- application follow-up toolbar
- funnel refresh action

## Funnel / Dashboard Changes

New analytics helper:

```text
apps/desktop/src/features/kanban-shared/funnelAnalytics.ts
```

Main funnel success path remains state-machine driven:

```text
M01 -> M04 -> M08 -> M11 -> M13 -> M14 -> M18 -> M19
```

Recruiting success is `M19 / Offer accepted`.

Dashboard now keeps action-oriented queues and uses a compact recruiting analysis entry instead of duplicating the full funnel analysis.

## Startup / Build Notes

Vite/Electron development startup was adjusted in:

- `scripts/dev-desktop.mjs`
- `apps/desktop/electron/main.ts`
- `apps/desktop/index.html`

The dev server target remains `127.0.0.1:5174`.

## Settings / Profile Notes

The settings surface now includes recruiter identity fields used by candidate communication:

- frontend settings contracts in `apps/desktop/src/lib/types.ts`
- API client updates in `apps/desktop/src/lib/api.ts`
- backend settings schema/router/migration updates under `services/backend/src/recruit_agent/**`

## Validation Already Run

These passed after the UI/component reuse changes:

```bash
npm run desktop:typecheck
npm run desktop:build
```

Runtime spot checks were also performed against the running Electron renderer for:

- sidebar old toggle/footer removal;
- `职位管理` click not expanding the sidebar;
- page toolbar heights reporting 48px on home, JD management, application follow-up, and Agent management.

## Follow-Up Risks

- `npm run desktop:build` still reports the existing Vite large chunk warning around the main renderer bundle. This is a warning, not a failed build.
- The working tree includes broad UI and settings changes; future UI work should start from the component reuse spec and avoid creating page-local toolbar/topbar copies.

## Resume Instructions

For future desktop UI changes:

1. Read `apps/desktop/DESIGN_GUIDELINES.md`.
2. Read `docs/specs/2026-05-14-desktop-frontend-component-reuse-spec.md`.
3. Reuse `PageToolbar` / `Toolbar*` / `Sidebar` / `TopBar` before adding feature-local controls.
4. Run:

```bash
npm run desktop:typecheck
npm run desktop:build
```
