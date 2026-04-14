import React from "react";
import { useI18n } from "../lib/i18n";
import { theme } from "../lib/theme";
import { translateUiToken } from "../lib/uiText";
import type { AgentSnapshot, SettingsSnapshot } from "../lib/types";
import { StatusBadge } from "./StatusBadge";

interface TopBarProps {
  agent: AgentSnapshot;
  settings: SettingsSnapshot;
  transport: "mock" | "http";
  sectionEyebrow: string;
  sectionTitle: string;
  sectionDescription: string;
  onRefresh(): void;
  refreshing: boolean;
}

const actionButtonStyle = {
  border: `1px solid ${theme.colors.border}`,
  borderRadius: theme.radius.md,
  background: theme.colors.accentSoft,
  color: theme.colors.text,
  padding: "10px 12px",
  cursor: "pointer",
  fontWeight: 700,
} as const;

export function TopBar({
  agent,
  settings,
  transport,
  sectionEyebrow,
  sectionTitle,
  sectionDescription,
  onRefresh,
  refreshing,
}: TopBarProps): JSX.Element {
  const { language, setLanguage, copy } = useI18n();
  return (
    <header
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: "16px",
        padding: "14px 18px",
        borderBottom: `1px solid ${theme.colors.border}`,
        background: "rgba(14,18,36,0.58)",
        backdropFilter: "blur(12px)",
      }}
    >
      <div>
        <div style={{ color: theme.colors.muted, fontSize: "11px" }}>{sectionEyebrow}</div>
        <div style={{ display: "flex", alignItems: "center", gap: "10px", marginTop: "4px" }}>
          <h2 style={{ margin: 0, fontSize: "16px" }}>{sectionTitle}</h2>
          <StatusBadge tone={agent.health === "healthy" ? "positive" : agent.health === "warning" ? "warning" : "critical"}>{translateUiToken(agent.status, copy)}</StatusBadge>
        </div>
        <div style={{ color: theme.colors.muted, fontSize: "12px", marginTop: "4px", lineHeight: 1.5 }}>{sectionDescription}</div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: "12px", flexWrap: "wrap", justifyContent: "end" }}>
        <div style={{ display: "inline-flex", border: `1px solid ${theme.colors.border}`, borderRadius: theme.radius.md, overflow: "hidden" }}>
          {[
            { key: "en", label: "EN" },
            { key: "zh-CN", label: "中文" },
          ].map((option) => {
            const active = language === option.key;
            return (
              <button
                key={option.key}
                type="button"
                onClick={() => setLanguage(option.key as "en" | "zh-CN")}
                style={{
                  border: "none",
                  background: active ? "rgba(122,167,255,0.18)" : "transparent",
                  color: theme.colors.text,
                  padding: "8px 12px",
                  cursor: "pointer",
                  fontWeight: 700,
                }}
              >
                {option.label}
              </button>
            );
          })}
        </div>
        <StatusBadge tone={transport === "http" ? "positive" : "warning"}>
          {transport === "http" ? copy("backend connected", "后端已连接") : copy("mock fallback", "降级为本地 mock")}
        </StatusBadge>
        <StatusBadge tone="neutral">{settings.platform.account}</StatusBadge>
        <StatusBadge tone={settings.intranetEnabled ? "positive" : "neutral"}>
          {settings.intranetEnabled ? copy("intranet sync on", "内网同步开启") : copy("local only", "仅本地")}
        </StatusBadge>
        <StatusBadge tone={settings.desktopApprovalsOnly ? "warning" : "neutral"}>{copy("desktop approvals", "桌面审批")}</StatusBadge>
        <button type="button" onClick={onRefresh} disabled={refreshing} style={actionButtonStyle}>
          {refreshing ? copy("Refreshing...", "刷新中...") : copy("Refresh", "刷新")}
        </button>
      </div>
    </header>
  );
}
