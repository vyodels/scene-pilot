import React from "react";
import type { CSSProperties } from "react";
import { theme } from "../lib/theme";
import type { WorkspaceTab } from "../lib/types";
import { StatusBadge } from "./StatusBadge";

interface SidebarProps {
  active: WorkspaceTab;
  onChange(tab: WorkspaceTab): void;
  counts: Partial<Record<WorkspaceTab, number>>;
}

const tabs: Array<{ key: WorkspaceTab; label: string; detail: string }> = [
  { key: "dashboard", label: "Dashboard", detail: "Summary and health" },
  { key: "candidates", label: "Candidates", detail: "Pipeline and profiles" },
  { key: "workflows", label: "Workflows", detail: "Nodes and versions" },
  { key: "skills", label: "Skills", detail: "Approval and health" },
  { key: "approvals", label: "Approvals", detail: "Human gates" },
  { key: "monitor", label: "Monitor", detail: "Agent runtime" },
  { key: "settings", label: "Settings", detail: "Provider and sync" },
];

export function Sidebar({ active, onChange, counts }: SidebarProps): JSX.Element {
  return (
    <aside
      style={{
        width: "280px",
        padding: "18px",
        background: "rgba(8,12,26,0.82)",
        borderRight: `1px solid ${theme.colors.border}`,
        backdropFilter: "blur(16px)",
      }}
    >
      <div style={{ marginBottom: "18px" }}>
        <div style={{ color: theme.colors.accent, textTransform: "uppercase", letterSpacing: "0.2em", fontSize: "11px" }}>Recruit Agent</div>
        <h1 style={{ margin: "10px 0 6px", fontSize: "28px", lineHeight: 1.05 }}>Desktop Operator</h1>
        <p style={{ margin: 0, color: theme.colors.muted, fontSize: "14px", lineHeight: 1.5 }}>
          Local-first recruiting automation with human review gates and serialized browser control.
        </p>
      </div>
      <div style={{ display: "grid", gap: "10px" }}>
        {tabs.map((tab) => {
          const selected = tab.key === active;
          return (
            <button
              key={tab.key}
              type="button"
              onClick={() => onChange(tab.key)}
              style={{
                cursor: "pointer",
                textAlign: "left",
                padding: "14px",
                borderRadius: theme.radius.lg,
                border: `1px solid ${selected ? "rgba(122,167,255,0.36)" : theme.colors.border}`,
                background: selected ? "rgba(122,167,255,0.12)" : "rgba(255,255,255,0.02)",
                color: theme.colors.text,
                display: "grid",
                gap: "4px",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "8px" }}>
                <span style={{ fontWeight: 700 }}>{tab.label}</span>
                {counts[tab.key] ? <StatusBadge tone={selected ? "positive" : "neutral"}>{counts[tab.key]}</StatusBadge> : null}
              </div>
              <span style={{ color: theme.colors.muted, fontSize: "12px" }}>{tab.detail}</span>
            </button>
          );
        })}
      </div>
    </aside>
  );
}

