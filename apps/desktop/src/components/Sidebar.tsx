import React from "react";
import type { CSSProperties } from "react";
import { useI18n } from "../lib/i18n";
import { theme } from "../lib/theme";
import type { WorkspaceTab } from "../lib/types";
import { StatusBadge } from "./StatusBadge";

interface SidebarProps {
  active: WorkspaceTab;
  onChange(tab: WorkspaceTab): void;
  counts: Partial<Record<WorkspaceTab, number>>;
}

export function Sidebar({ active, onChange, counts }: SidebarProps): JSX.Element {
  const { copy } = useI18n();
  const tabs: Array<{ key: WorkspaceTab; label: string; detail: string }> = [
    { key: "dashboard", label: copy("Overview", "概览"), detail: copy("Global health and cross-workflow signals", "全局健康状态与跨工作流信号") },
    { key: "workflow-management", label: copy("Workflow Management", "工作流管理"), detail: copy("Create, trial, revise, and publish workflows", "创建、试跑、修正并发布工作流") },
    { key: "workbench", label: copy("Workbench", "工作台"), detail: copy("Inspect each workflow and its live instances", "查看每条工作流及其实时运行状况") },
    { key: "approvals", label: copy("Approvals", "审批中心"), detail: copy("Human gates and activation decisions", "人工关卡与生效决策") },
    { key: "skills", label: copy("Skills", "Skills"), detail: copy("Skill approvals, health, and evolution", "Skills 审批、健康与演进") },
    { key: "settings", label: copy("Settings", "设置"), detail: copy("Provider and sync", "Provider 与同步") },
  ];
  return (
    <aside
      style={{
        width: "248px",
        padding: "16px",
        background: "rgba(8,12,26,0.74)",
        borderRight: `1px solid ${theme.colors.border}`,
        backdropFilter: "blur(12px)",
      }}
    >
      <div style={{ marginBottom: "16px" }}>
        <div style={{ color: theme.colors.accent, textTransform: "uppercase", letterSpacing: "0.2em", fontSize: "11px" }}>
          {copy("ScenePilot", "ScenePilot")}
        </div>
        <h1 style={{ margin: "8px 0 6px", fontSize: "24px", lineHeight: 1.08 }}>{copy("Workflow Console", "工作流控制台")}</h1>
        <p style={{ margin: 0, color: theme.colors.muted, fontSize: "13px", lineHeight: 1.5 }}>
          {copy(
            "Local-first natural-language automation focused on workflow creation, supervised trial runs, workbench operations, approvals, and reusable scene knowledge.",
            "本地优先的自然语言自动化平台，聚焦工作流创建、受监督试跑、工作台运营、审批，以及可复用的场景知识。",
          )}
        </p>
      </div>
      <div style={{ display: "grid", gap: "8px" }}>
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
                padding: "12px 13px",
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
