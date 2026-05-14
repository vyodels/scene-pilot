# Desktop Frontend Component Reuse Spec

## Purpose

This spec defines the long-term frontend reuse rules for the Electron desktop app. The goal is to keep shared UI behavior, spacing, height, and interaction states in one place so future UI changes do not require page-by-page edits.

## Scope

Applies to `apps/desktop/src/**`, especially page-level navigation, top bars, toolbars, filters, search fields, refresh actions, and primary page actions.

## Component Ownership

Shared UI primitives live under `apps/desktop/src/components/`.

Page and feature modules may compose these primitives, but must not create parallel copies of the same visual role unless the new component is promoted to `components/` first.

Required shared primitives:

- `AppLayout`: owns the global sidebar, global topbar slot, and page content shell.
- `Sidebar`: owns workspace navigation and sidebar expand/collapse behavior.
- `TopBar`: owns the global workspace topbar content.
- `PageToolbar`: owns every page-level toolbar row, including pages that hide the global `TopBar`.
- `PageToolbarGroup`: owns toolbar grouping and left/right alignment.
- `ToolbarField`, `ToolbarInput`, `ToolbarSelect`, `ToolbarButton`, `ToolbarRefreshButton`: own toolbar control sizing, focus, hover, disabled, and refresh states.
- `StatusBadge`: owns compact status display.

## Topbar And Page Toolbar Rules

All topbar-like rows must share `--layout-topnav-height`.

Use `TopBar` only for the global `AppLayout` topbar slot. Use `PageToolbar` for page-level top rows inside feature pages, including:

- dashboard action rows;
- pages that hide the global topbar but still show filters, search, refresh, or create actions;
- management pages with top filter bars;
- Agent management top controls.

Do not hand-write page-specific topbar containers with independent height, padding, borders, or button sizing. Classes such as `*-topbar`, `*-toolbar`, and `*-filterbar` may exist only as layout modifiers on top of `PageToolbar`.

## Toolbar Control Rules

Toolbar controls must use shared components:

- select filters use `ToolbarField` plus `ToolbarSelect`;
- search fields use `ToolbarField` plus `ToolbarInput`, or a feature-specific wrapper around `ToolbarInput`;
- refresh actions use `ToolbarRefreshButton`;
- normal actions use `ToolbarButton`;
- status labels use `StatusBadge`.

Do not introduce raw `<select>`, `<input>`, or `<button>` in a page toolbar unless native semantics require a custom wrapper, and that wrapper must still use shared toolbar classes internally.

## CSS Rules

Global sizing and state styles belong to shared classes:

- `.page-toolbar`
- `.page-toolbar__group`
- `.toolbar-field`
- `.toolbar-input`
- `.toolbar-select`
- `.toolbar-button`
- `.toolbar-button--primary`
- `.toolbar-button__icon`

Feature CSS may set grid columns, widths, overflow behavior, or local alignment for a toolbar, but must not redefine core control height, border radius, focus ring, hover state, disabled state, or refresh icon behavior.

## Sidebar Rules

Sidebar entries must share one structural pattern: `workspace-sidebar__item` with `workspace-sidebar__item-icon` and `workspace-sidebar__item-label`.

Agent management, Settings, and collapse/expand controls are sidebar items, not separate footer or header button variants. Navigation item clicks must not implicitly expand or collapse the sidebar; only the explicit sidebar toggle may change expanded state.

## Review Checklist

Before merging any desktop UI change:

1. Check whether the UI role already exists in `components/`.
2. Reuse the shared primitive instead of copying markup and CSS.
3. Keep page-specific CSS to layout modifiers only.
4. Verify all topbar and page toolbar rows have the same height.
5. Run `npm run desktop:typecheck`.
