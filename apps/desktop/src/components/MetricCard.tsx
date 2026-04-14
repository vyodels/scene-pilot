import React from "react";
import { theme } from "../lib/theme";
import { StatusBadge } from "./StatusBadge";

interface MetricCardProps {
  label: string;
  value: string;
  delta: string;
  tone: "positive" | "neutral" | "warning";
  caption: string;
}

export function MetricCard({ label, value, delta, tone, caption }: MetricCardProps): JSX.Element {
  return (
    <article
      style={{
        background: "rgba(255,255,255,0.03)",
        border: `1px solid ${theme.colors.border}`,
        borderRadius: theme.radius.lg,
        padding: "16px",
        minWidth: 0,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", alignItems: "start" }}>
        <div>
          <div style={{ color: theme.colors.muted, fontSize: "13px" }}>{label}</div>
          <div style={{ marginTop: "6px", fontSize: "30px", fontWeight: 800, letterSpacing: "-0.04em" }}>{value}</div>
        </div>
        <StatusBadge tone={tone === "positive" ? "positive" : tone === "warning" ? "warning" : "neutral"}>{delta}</StatusBadge>
      </div>
      <div style={{ marginTop: "10px", color: theme.colors.muted, fontSize: "13px" }}>{caption}</div>
    </article>
  );
}

