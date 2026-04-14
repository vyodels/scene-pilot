import React from "react";
import type { CSSProperties } from "react";
import { theme } from "../lib/theme";

interface StatusBadgeProps {
  tone: "positive" | "neutral" | "warning" | "critical";
  children: React.ReactNode;
}

export function StatusBadge({ tone, children }: StatusBadgeProps): JSX.Element {
  const palette: Record<StatusBadgeProps["tone"], CSSProperties> = {
    positive: { color: theme.colors.positive, background: "rgba(93, 216, 163, 0.12)" },
    neutral: { color: theme.colors.muted, background: "rgba(154, 167, 199, 0.12)" },
    warning: { color: theme.colors.warning, background: "rgba(244, 193, 93, 0.12)" },
    critical: { color: theme.colors.critical, background: "rgba(255, 122, 122, 0.12)" },
  };

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "6px 10px",
        borderRadius: "999px",
        fontSize: "12px",
        fontWeight: 700,
        letterSpacing: "0.03em",
        ...palette[tone],
      }}
    >
      {children}
    </span>
  );
}

