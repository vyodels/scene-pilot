import React from "react";
import { useI18n } from "../lib/i18n";
import type { AgentSnapshot, WorkspaceTab } from "../lib/types";

interface SidebarProps {
  active: WorkspaceTab;
  onChange(tab: WorkspaceTab): void;
  counts: Partial<Record<WorkspaceTab, number>>;
  expanded?: boolean;
  onExpandedChange?(expanded: boolean): void;
  agentStatus?: AgentSnapshot["status"];
  agentCount?: number;
  onOpenAgents(): void;
}

const tabs: Array<{ key: WorkspaceTab; labelEn: string; labelZh: string; shortZh: string }> = [
  { key: "home", labelEn: "Home", labelZh: "首页", shortZh: "首页" },
  { key: "jdManagement", labelEn: "Position management", labelZh: "职位管理", shortZh: "职位" },
  { key: "applicationFollowUp", labelEn: "Application records", labelZh: "投递记录", shortZh: "投递" },
  { key: "applicationFunnel", labelEn: "Funnel board", labelZh: "漏斗看板", shortZh: "漏斗" },
];

const settingsTab = { key: "settings" as const, labelEn: "Settings", labelZh: "设置", shortZh: "设置" };

function SidebarGlyph({ tab, expanded = false }: { tab: WorkspaceTab | "agents" | "toggle"; expanded?: boolean }): JSX.Element {
  const shared = {
    width: 22,
    height: 22,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.75,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };

  switch (tab) {
    case "home":
      return (
        <svg {...shared}>
          <path d="M4 11.5 12 5l8 6.5" />
          <path d="M6.5 10.5V19h11v-8.5" />
        </svg>
      );
    case "applicationFunnel":
      return (
        <svg {...shared}>
          <path d="M4 5h16" />
          <path d="M7 10h10" />
          <path d="M10 15h4" />
          <path d="M12 15v4" />
        </svg>
      );
    case "applicationFollowUp":
      return (
        <svg {...shared}>
          <path d="m4.5 12 15-7-4.6 14-3.1-5.8L4.5 12Z" />
          <path d="m11.8 13.2 3.1-3.1" />
        </svg>
      );
    case "jdManagement":
      return (
        <svg {...shared}>
          <rect x="4.5" y="7" width="15" height="12" rx="2" />
          <path d="M9 7V5.8C9 4.8 9.8 4 10.8 4h2.4C14.2 4 15 4.8 15 5.8V7" />
          <path d="M4.5 12h15" />
          <path d="M10 12v1.2h4V12" />
        </svg>
      );
    case "settings":
      return (
        <svg {...shared}>
          <circle cx="12" cy="12" r="3" />
          <path d="M12 4.5v2" />
          <path d="M12 17.5v2" />
          <path d="m18.4 6.6-1.4 1.4" />
          <path d="m7 18-1.4 1.4" />
          <path d="M19.5 12h-2" />
          <path d="M6.5 12h-2" />
          <path d="m18.4 17.4-1.4-1.4" />
          <path d="M7 6l-1.4-1.4" />
        </svg>
      );
    case "toggle":
      return expanded ? (
        <svg {...shared}>
          <path d="m15 6-6 6 6 6" />
        </svg>
      ) : (
        <svg {...shared}>
          <path d="m9 6 6 6-6 6" />
        </svg>
      );
    default:
      return (
        <svg {...shared}>
          <rect x="6" y="8" width="12" height="10" rx="3" />
          <path d="M12 5v3" />
          <path d="M9.5 13h.01" />
          <path d="M14.5 13h.01" />
          <path d="M9.5 16h5" />
          <path d="M4 12.5h2" />
          <path d="M18 12.5h2" />
        </svg>
      );
  }
}

export function Sidebar({
  active,
  onChange,
  counts,
  expanded = false,
  onExpandedChange,
  agentStatus = "idle",
  agentCount = 0,
  onOpenAgents,
}: SidebarProps): JSX.Element {
  const { copy } = useI18n();

  return (
    <aside className="workspace-sidebar" data-expanded={expanded ? "true" : undefined}>
      <div className="workspace-sidebar__brand">
        <div className="workspace-sidebar__logo">RA</div>
        <div className="workspace-sidebar__eyebrow">{copy("Smart recruiting hub", "智能招聘中台")}</div>
      </div>

      <nav className="workspace-sidebar__nav" aria-label={copy("Workspace sections", "工作区分区")}>
        {tabs.map((tab) => {
          const selected = tab.key === active;
          const count = counts[tab.key] ?? 0;

          return (
            <button
              key={tab.key}
              type="button"
              className="workspace-sidebar__item"
              data-active={selected}
              aria-label={copy(tab.labelEn, tab.labelZh)}
              onClick={() => onChange(tab.key)}
            >
              <span className="workspace-sidebar__item-icon">
                <SidebarGlyph tab={tab.key} />
              </span>
              <span className="workspace-sidebar__item-label">{copy(tab.labelEn, expanded ? tab.labelZh : tab.shortZh)}</span>
              {count > 0 ? <span className="workspace-sidebar__count">{count > 9 ? "9+" : count}</span> : null}
            </button>
          );
        })}

        <button
          type="button"
          className="workspace-sidebar__item workspace-sidebar__item--agents"
          data-active={active === "agents"}
          data-status={agentStatus}
          aria-label={copy("Agent management", "Agent 管理")}
          onClick={onOpenAgents}
        >
          <span className="workspace-sidebar__item-icon">
            <SidebarGlyph tab="agents" />
          </span>
          <span className="workspace-sidebar__item-label">{copy("Agent management", "Agent 管理")}</span>
          <span className="workspace-sidebar__status-dot" aria-hidden="true" />
          {agentCount > 0 ? <span className="workspace-sidebar__count">{agentCount > 9 ? "9+" : agentCount}</span> : null}
        </button>

        <button
          type="button"
          className="workspace-sidebar__item workspace-sidebar__item--settings"
          data-active={active === settingsTab.key}
          aria-label={copy(settingsTab.labelEn, settingsTab.labelZh)}
          onClick={() => onChange(settingsTab.key)}
        >
          <span className="workspace-sidebar__item-icon">
            <SidebarGlyph tab={settingsTab.key} />
          </span>
          <span className="workspace-sidebar__item-label">{copy(settingsTab.labelEn, expanded ? settingsTab.labelZh : settingsTab.shortZh)}</span>
        </button>

        <button
          type="button"
          className="workspace-sidebar__item workspace-sidebar__item--toggle"
          onClick={() => onExpandedChange?.(!expanded)}
          aria-label={expanded ? copy("Collapse sidebar", "收起菜单") : copy("Expand sidebar", "展开菜单")}
          aria-expanded={expanded}
        >
          <span className="workspace-sidebar__item-icon">
            <SidebarGlyph tab="toggle" expanded={expanded} />
          </span>
          <span className="workspace-sidebar__item-label">{expanded ? copy("Collapse menu", "收起菜单") : copy("Expand menu", "展开菜单")}</span>
        </button>
      </nav>
    </aside>
  );
}
