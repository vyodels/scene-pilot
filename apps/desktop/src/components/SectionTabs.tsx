import React from "react";
import { theme } from "../lib/theme";
import { StatusBadge } from "./StatusBadge";

export interface SectionTabItem {
  key: string;
  label: string;
  detail?: string;
  count?: number;
}

interface SectionTabsProps {
  items: SectionTabItem[];
  active: string;
  onChange(key: string): void;
}

export function SectionTabs({ items, active, onChange }: SectionTabsProps): JSX.Element {
  return (
    <div
      style={{
        display: "flex",
        gap: "10px",
        flexWrap: "wrap",
        alignItems: "stretch",
      }}
    >
      {items.map((item) => {
        const selected = item.key === active;
        return (
          <button
            key={item.key}
            type="button"
            onClick={() => onChange(item.key)}
            style={{
              cursor: "pointer",
              textAlign: "left",
              minWidth: item.detail ? "180px" : "140px",
              padding: "12px 14px",
              borderRadius: theme.radius.lg,
              border: `1px solid ${selected ? "rgba(122,167,255,0.36)" : theme.colors.border}`,
              background: selected ? "rgba(122,167,255,0.12)" : "rgba(255,255,255,0.03)",
              color: theme.colors.text,
              display: "grid",
              gap: "4px",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "8px" }}>
              <span style={{ fontWeight: 700 }}>{item.label}</span>
              {item.count ? <StatusBadge tone={selected ? "positive" : "neutral"}>{item.count}</StatusBadge> : null}
            </div>
            {item.detail ? <span style={{ color: theme.colors.muted, fontSize: "12px", lineHeight: 1.4 }}>{item.detail}</span> : null}
          </button>
        );
      })}
    </div>
  );
}
