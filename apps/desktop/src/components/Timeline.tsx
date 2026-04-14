import React from "react";
import { useI18n } from "../lib/i18n";
import { theme } from "../lib/theme";
import { translateUiToken } from "../lib/uiText";
import type { TimelineEvent } from "../lib/types";
import { StatusBadge } from "./StatusBadge";

interface TimelineProps {
  events: TimelineEvent[];
}

export function Timeline({ events }: TimelineProps): JSX.Element {
  const { copy } = useI18n();

  return (
    <div style={{ display: "grid", gap: "12px" }}>
      {events.map((event) => (
        <article
          key={event.id}
          style={{
            display: "grid",
            gap: "6px",
            padding: "14px",
            borderRadius: theme.radius.lg,
            border: `1px solid ${theme.colors.border}`,
            background: "rgba(255,255,255,0.02)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "8px" }}>
            <strong>{event.label}</strong>
            <StatusBadge tone={event.tone}>{translateUiToken(event.at, copy)}</StatusBadge>
          </div>
          <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.5 }}>{event.detail}</div>
        </article>
      ))}
    </div>
  );
}
