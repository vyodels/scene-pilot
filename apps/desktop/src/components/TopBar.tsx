import React from "react";
import type { ReactNode } from "react";
import { useI18n } from "../lib/i18n";
import { translateUiToken } from "../lib/uiText";
import type { AgentSnapshot, SettingsSnapshot } from "../lib/types";
import { StatusBadge } from "./StatusBadge";

interface TopBarProps {
  agent: AgentSnapshot;
  settings: SettingsSnapshot;
  transport: "http" | "offline";
  sectionEyebrow: string;
  sectionTitle: string;
  hideSectionSummary?: boolean;
  leadingContent?: ReactNode;
  onRefresh(): void;
  refreshing: boolean;
}

export function TopBar({
  agent,
  settings,
  transport,
  sectionEyebrow,
  sectionTitle,
  hideSectionSummary = false,
  leadingContent,
  onRefresh,
  refreshing,
}: TopBarProps): JSX.Element {
  const { language, setLanguage, copy } = useI18n();
  const summaryContent = !hideSectionSummary ? (
    <>
      <div className="workspace-topbar__eyebrow">{sectionEyebrow}</div>
      <div className="workspace-topbar__title-row">
        <h2 className="workspace-topbar__title">{sectionTitle}</h2>
        <StatusBadge tone={agent.health === "healthy" ? "positive" : agent.health === "warning" ? "warning" : "critical"}>
          {translateUiToken(agent.status, copy)}
        </StatusBadge>
      </div>
    </>
  ) : null;

  return (
    <header className="workspace-topbar" data-hide-summary={hideSectionSummary ? "true" : undefined}>
      {leadingContent || summaryContent ? (
        <div className="workspace-topbar__summary" data-mode={leadingContent ? "custom" : undefined}>
          {leadingContent ?? summaryContent}
        </div>
      ) : null}

      <div className="workspace-topbar__actions">
        <div className="workspace-topbar__meta">
          <StatusBadge tone={transport === "http" ? "positive" : "critical"}>
            {transport === "http" ? copy("backend connected", "后端已连接") : copy("backend unavailable", "后端不可用")}
          </StatusBadge>
          <StatusBadge tone="neutral">{settings.platform.account}</StatusBadge>
          <StatusBadge tone={settings.intranetEnabled ? "positive" : "neutral"}>
            {settings.intranetEnabled ? copy("intranet sync on", "内网同步开启") : copy("local only", "仅本地")}
          </StatusBadge>
          <StatusBadge tone={settings.desktopApprovalsOnly ? "warning" : "neutral"}>{copy("desktop approvals", "桌面确认")}</StatusBadge>
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

        <button type="button" className="workspace-topbar__button" onClick={onRefresh} disabled={refreshing}>
          {refreshing ? copy("Refreshing...", "刷新中...") : copy("Refresh", "刷新")}
        </button>
      </div>
    </header>
  );
}
