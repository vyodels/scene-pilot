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
  borderRadius: 10,
  background: "rgba(255,255,255,0.04)",
  color: theme.colors.text,
  padding: "8px 12px",
  cursor: "pointer",
  fontWeight: 600,
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
        display: "grid",
        gridTemplateColumns: "minmax(0, 1fr) auto",
        alignItems: "center",
        gap: "14px",
        padding: "12px 20px",
        borderBottom: `1px solid ${theme.colors.border}`,
        background: "rgba(12,18,30,0.9)",
        backdropFilter: "blur(14px)",
        position: "sticky",
        top: 0,
        zIndex: 20,
      }}
    >
      <div>
        <div style={{ color: theme.colors.muted, fontSize: "11px", letterSpacing: "0.12em", textTransform: "uppercase" }}>{sectionEyebrow}</div>
        <div style={{ display: "flex", alignItems: "baseline", gap: "10px", marginTop: "4px", flexWrap: "wrap" }}>
          <h2 style={{ margin: 0, fontSize: "24px", lineHeight: 1.1 }}>{sectionTitle}</h2>
          <div style={{ color: theme.colors.muted, fontSize: "12px", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: "720px" }}>
            {sectionDescription}
          </div>
          <StatusBadge tone={agent.health === "healthy" ? "positive" : agent.health === "warning" ? "warning" : "critical"}>{translateUiToken(agent.status, copy)}</StatusBadge>
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap", justifyContent: "end" }}>
        <div style={{ display: "inline-flex", border: `1px solid ${theme.colors.border}`, borderRadius: 10, overflow: "hidden" }}>
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
                  background: active ? "rgba(122,167,255,0.14)" : "transparent",
                  color: theme.colors.text,
                  padding: "7px 12px",
                  cursor: "pointer",
                  fontWeight: 600,
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
