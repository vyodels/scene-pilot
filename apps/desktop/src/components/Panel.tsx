import React from "react";
import type { CSSProperties, ReactNode } from "react";
import { theme } from "../lib/theme";

interface PanelProps {
  title?: string;
  eyebrow?: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
  dense?: boolean;
}

const shellStyle: CSSProperties = {
  background: `linear-gradient(180deg, ${theme.colors.panelElevated}, ${theme.colors.panel})`,
  border: `1px solid ${theme.colors.border}`,
  borderRadius: theme.radius.xl,
  boxShadow: theme.shadow,
  padding: "18px",
};

export function Panel({ title, eyebrow, description, actions, children, dense }: PanelProps): JSX.Element {
  return (
    <section style={{ ...shellStyle, padding: dense ? "16px" : shellStyle.padding }}>
      {(title || eyebrow || description || actions) && (
        <header style={{ display: "flex", alignItems: "start", justifyContent: "space-between", gap: "16px", marginBottom: "14px" }}>
          <div>
            {eyebrow ? <div style={{ color: theme.colors.accent, fontSize: "11px", letterSpacing: "0.12em", textTransform: "uppercase" }}>{eyebrow}</div> : null}
            {title ? <h2 style={{ margin: "6px 0 4px", fontSize: "18px", lineHeight: 1.2 }}>{title}</h2> : null}
            {description ? <p style={{ margin: 0, color: theme.colors.muted, fontSize: "14px", lineHeight: 1.5 }}>{description}</p> : null}
          </div>
          {actions ? <div>{actions}</div> : null}
        </header>
      )}
      {children}
    </section>
  );
}
