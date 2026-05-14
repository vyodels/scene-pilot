import React from "react";
import type { ReactNode } from "react";
import { useI18n } from "../lib/i18n";
import type { AgentSnapshot } from "../lib/types";
import { PageToolbar, PageToolbarGroup } from "./PageToolbar";
import { StatusBadge } from "./StatusBadge";
import { ToolbarRefreshButton } from "./ToolbarControls";

interface TopBarProps {
  transport: "http" | "offline";
  sectionEyebrow: string;
  sectionTitle: string;
  agentStatus: AgentSnapshot["status"];
  hideSectionSummary?: boolean;
  leadingContent?: ReactNode;
  onRefresh(): void;
  refreshing: boolean;
}

export function TopBar({
  transport,
  sectionEyebrow,
  sectionTitle,
  agentStatus,
  hideSectionSummary = false,
  leadingContent,
  onRefresh,
  refreshing,
}: TopBarProps): JSX.Element {
  const { language, setLanguage, copy } = useI18n();
  const agentRunning = agentStatus === "running";
  const summaryContent = !hideSectionSummary ? (
    <div className="workspace-topbar__title-row" aria-label={sectionEyebrow}>
      <h2 className="workspace-topbar__title">{sectionTitle}</h2>
    </div>
  ) : null;

  return (
    <PageToolbar className="workspace-topbar" data-hide-summary={hideSectionSummary ? "true" : undefined}>
      {leadingContent || summaryContent ? (
        <PageToolbarGroup className="workspace-topbar__summary" data-mode={leadingContent ? "custom" : undefined}>
          {leadingContent ?? summaryContent}
        </PageToolbarGroup>
      ) : null}

      <PageToolbarGroup className="workspace-topbar__actions" align="end">
        <div className="workspace-topbar__meta">
          <StatusBadge tone={transport === "http" ? "positive" : "critical"}>
            {transport === "http" ? copy("backend connected", "后端已连接") : copy("backend unavailable", "后端不可用")}
          </StatusBadge>
          <StatusBadge tone={agentRunning ? "positive" : "neutral"}>
            {agentRunning ? copy("Agent running", "Agent 运行中") : copy("Agent idle", "Agent 未运行")}
          </StatusBadge>
        </div>
        <div className="workspace-topbar__switch" aria-label={copy("Language switch", "语言切换")}>
          {[
            { key: "en", label: "EN" },
            { key: "zh-CN", label: "中文" },
          ].map((option) => {
            const active = language === option.key;

            return (
              <button
                key={option.key}
                type="button"
                className="workspace-topbar__switch-button"
                data-active={active}
                onClick={() => setLanguage(option.key as "en" | "zh-CN")}
              >
                {option.label}
              </button>
            );
          })}
        </div>

        <ToolbarRefreshButton
          onClick={onRefresh}
          refreshing={refreshing}
          label={copy("Refresh", "刷新")}
          refreshingLabel={copy("Refreshing...", "刷新中...")}
        />
      </PageToolbarGroup>
    </PageToolbar>
  );
}
