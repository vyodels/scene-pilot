import React from "react";
import { useI18n } from "../lib/i18n";
import type { AgentSnapshot, WorkspaceTab } from "../lib/types";
import { StatusBadge } from "./StatusBadge";

interface SidebarProps {
  active: WorkspaceTab;
  onChange(tab: WorkspaceTab): void;
  counts: Partial<Record<WorkspaceTab, number>>;
  agentsOpen?: boolean;
  agentStatus?: AgentSnapshot["status"];
  agentCount?: number;
  onOpenAgents(): void;
}

const tabs: Array<{ key: WorkspaceTab; labelEn: string; labelZh: string; shortZh: string }> = [
  { key: "home", labelEn: "Home", labelZh: "首页", shortZh: "首页" },
  { key: "candidates", labelEn: "Candidates", labelZh: "候选人", shortZh: "工作台" },
  { key: "settings", labelEn: "Settings", labelZh: "设置", shortZh: "设置" },
];

function SidebarGlyph({ tab }: { tab: WorkspaceTab | "agents" }): JSX.Element {
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
    case "candidates":
      return (
        <svg {...shared}>
          <circle cx="9" cy="8" r="3" />
          <path d="M4.5 18c.9-2.4 2.8-4 4.5-4s3.6 1.6 4.5 4" />
          <path d="M16 10.5c1.7.4 3 1.8 3.5 3.5" />
          <path d="M16.5 6.5a2.5 2.5 0 0 1 0 5" />
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
    default:
      return (
        <svg {...shared}>
          <rect x="5" y="5" width="14" height="14" rx="4" />
          <path d="M9 9h6v6H9z" />
          <path d="M9 3.5v2" />
          <path d="M15 3.5v2" />
          <path d="M9 18.5v2" />
          <path d="M15 18.5v2" />
        </svg>
      );
  }
}

export function Sidebar({
  active,
  onChange,
  counts,
  agentsOpen = false,
  agentStatus = "idle",
  agentCount = 0,
  onOpenAgents,
}: SidebarProps): JSX.Element {
  const { copy } = useI18n();

  return (
    <aside className="workspace-sidebar">
      <div className="workspace-sidebar__brand">
        <div className="workspace-sidebar__logo">RA</div>
        <div className="workspace-sidebar__eyebrow">{copy("Smart recruiting", "智能招聘")}</div>
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
              <span className="workspace-sidebar__item-label">{copy(tab.labelEn, tab.shortZh)}</span>
              {count > 0 ? <span className="workspace-sidebar__count">{count > 9 ? "9+" : count}</span> : null}
            </button>
          );
        })}

        <button
          type="button"
          className="workspace-sidebar__item workspace-sidebar__item--agents"
          data-active={agentsOpen}
          data-status={agentStatus}
          aria-label={copy("Open Agents overlay", "打开 Agents 浮窗")}
          onClick={onOpenAgents}
        >
          <span className="workspace-sidebar__item-icon">
            <SidebarGlyph tab="agents" />
          </span>
          <span className="workspace-sidebar__item-label">{copy("Agents", "Agents")}</span>
          <span className="workspace-sidebar__status-dot" aria-hidden="true" />
          {agentCount > 0 ? <span className="workspace-sidebar__count">{agentCount > 9 ? "9+" : agentCount}</span> : null}
        </button>
      </nav>

      <div className="workspace-sidebar__footer">
        <StatusBadge tone="positive">{copy("local", "本地")}</StatusBadge>
      </div>
    </aside>
  );
}
