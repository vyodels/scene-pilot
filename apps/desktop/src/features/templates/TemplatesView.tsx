import React from "react";
import { Panel, StatusBadge } from "../../components";
import { formatCompactDate } from "../../lib/format";
import { theme } from "../../lib/theme";
import type { RuntimeTemplate } from "../../lib/types";

interface TemplatesViewProps {
  templates: RuntimeTemplate[];
}

export function TemplatesView({ templates }: TemplatesViewProps): JSX.Element {
  return (
    <Panel
      title="Template library"
      eyebrow="Reusable workflows"
      description="Validated runs are promoted here as reusable templates. Draft templates stay approval-gated until they are confirmed."
    >
      <div style={{ display: "grid", gap: "12px" }}>
        {templates.map((template) => {
          const steps = Array.isArray(template.templateBody.steps) ? template.templateBody.steps : [];
          return (
            <article
              key={template.id}
              style={{
                borderRadius: "18px",
                border: `1px solid ${theme.colors.border}`,
                background: "rgba(255,255,255,0.03)",
                padding: "16px",
                display: "grid",
                gap: "10px",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: "10px", flexWrap: "wrap" }}>
                <div>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                    <strong>{template.name}</strong>
                    <StatusBadge tone="neutral">{template.domain}</StatusBadge>
                    <StatusBadge tone={template.status === "active" ? "positive" : template.status === "draft" ? "warning" : "neutral"}>
                      {template.status}
                    </StatusBadge>
                  </div>
                  <div style={{ marginTop: "6px", color: theme.colors.muted, fontSize: "13px" }}>{template.templateKey}</div>
                </div>
                <div style={{ color: "rgba(233,239,255,0.56)", fontSize: "12px" }}>Updated {formatCompactDate(template.updatedAt)}</div>
              </div>
              <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                <StatusBadge tone="neutral">v{template.version}</StatusBadge>
                <StatusBadge tone="neutral">{steps.length} steps</StatusBadge>
                {template.lastValidatedAt ? <StatusBadge tone="neutral">Validated {formatCompactDate(template.lastValidatedAt)}</StatusBadge> : null}
              </div>
              {template.validationSummary ? (
                <div style={{ color: "rgba(233,239,255,0.74)", fontSize: "13px", lineHeight: 1.5 }}>{template.validationSummary}</div>
              ) : null}
            </article>
          );
        })}
      </div>
    </Panel>
  );
}
