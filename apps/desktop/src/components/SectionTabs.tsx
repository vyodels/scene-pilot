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
  variant?: "card" | "topbar";
}

export function SectionTabs({ items, active, onChange, variant = "card" }: SectionTabsProps): JSX.Element {
  const topbar = variant === "topbar";

  return (
    <div
      style={{
        display: "flex",
        gap: topbar ? "2px" : "10px",
        flexWrap: topbar ? "nowrap" : "wrap",
        alignItems: topbar ? "center" : "stretch",
        overflowX: topbar ? "auto" : "visible",
        padding: topbar ? "0 20px" : "0",
        margin: topbar ? "0 -2px" : "0",
        borderBottom: topbar ? `1px solid ${theme.colors.border}` : "none",
        background: topbar ? "rgba(12, 18, 30, 0.92)" : "transparent",
        backdropFilter: topbar ? "blur(14px)" : "none",
        minHeight: topbar ? "52px" : undefined,
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
              minWidth: topbar ? "auto" : item.detail ? "180px" : "140px",
              padding: topbar ? "12px 14px 11px" : "12px 14px",
              borderRadius: topbar ? 0 : theme.radius.lg,
              border: "none",
              borderBottom: topbar ? `2px solid ${selected ? "rgba(122,167,255,0.9)" : "transparent"}` : `1px solid ${selected ? "rgba(122,167,255,0.36)" : theme.colors.border}`,
              background: topbar ? "transparent" : selected ? "rgba(122,167,255,0.12)" : "rgba(255,255,255,0.03)",
              color: theme.colors.text,
              display: "flex",
              alignItems: "center",
              gap: "8px",
              flexShrink: 0,
              alignSelf: topbar ? "center" : "stretch",
            }}
          >
            <span style={{ fontWeight: selected || topbar ? 700 : 600, whiteSpace: "nowrap" }}>{item.label}</span>
            {item.count ? <StatusBadge tone={selected ? "positive" : "neutral"}>{item.count}</StatusBadge> : null}
            {!topbar && item.detail ? <span style={{ color: theme.colors.muted, fontSize: "12px", lineHeight: 1.4 }}>{item.detail}</span> : null}
          </button>
        );
      })}
    </div>
  );
}
