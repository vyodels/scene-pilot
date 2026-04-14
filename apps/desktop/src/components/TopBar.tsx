import React from "react";
import { theme } from "../lib/theme";
import type { AgentSnapshot, SettingsSnapshot } from "../lib/types";
import { StatusBadge } from "./StatusBadge";

interface TopBarProps {
  agent: AgentSnapshot;
  settings: SettingsSnapshot;
  transport: "mock" | "http";
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

export function TopBar({ agent, settings, transport, onRefresh, refreshing }: TopBarProps): JSX.Element {
  return (
    <header
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: "16px",
        padding: "18px 22px",
        borderBottom: `1px solid ${theme.colors.border}`,
        background: "rgba(14,18,36,0.65)",
        backdropFilter: "blur(16px)",
      }}
    >
      <div>
        <div style={{ color: theme.colors.muted, fontSize: "12px" }}>Workspace</div>
        <div style={{ display: "flex", alignItems: "center", gap: "10px", marginTop: "4px" }}>
          <h2 style={{ margin: 0, fontSize: "18px" }}>General automation runtime</h2>
          <StatusBadge tone={agent.health === "healthy" ? "positive" : agent.health === "warning" ? "warning" : "critical"}>{agent.status}</StatusBadge>
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: "12px", flexWrap: "wrap", justifyContent: "end" }}>
        <StatusBadge tone={transport === "http" ? "positive" : "warning"}>
          {transport === "http" ? "backend connected" : "mock fallback"}
        </StatusBadge>
        <StatusBadge tone="neutral">{settings.platform.account}</StatusBadge>
        <StatusBadge tone={settings.intranetEnabled ? "positive" : "neutral"}>{settings.intranetEnabled ? "intranet sync on" : "local only"}</StatusBadge>
        <StatusBadge tone={settings.desktopApprovalsOnly ? "warning" : "neutral"}>desktop approvals</StatusBadge>
        <button type="button" onClick={onRefresh} disabled={refreshing} style={actionButtonStyle}>
          {refreshing ? "Refreshing..." : "Refresh"}
        </button>
      </div>
    </header>
  );
}
