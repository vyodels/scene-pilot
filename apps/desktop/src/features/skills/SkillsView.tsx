import React from "react";
import { Panel, StatusBadge } from "../../components";
import { formatCompactDate } from "../../lib/format";
import type { SkillRecord } from "../../lib/types";

interface SkillsViewProps {
  skills: SkillRecord[];
}

export function SkillsView({ skills }: SkillsViewProps): JSX.Element {
  return (
    <div style={{ display: "grid", gap: "18px", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))" }}>
      {skills.map((skill) => (
        <Panel
          key={skill.id}
          title={skill.name}
          eyebrow={`Bound to ${skill.boundNode}`}
          description={skill.summary}
          actions={<StatusBadge tone={skill.health === "healthy" ? "positive" : skill.health === "warning" ? "warning" : "critical"}>{skill.status}</StatusBadge>}
        >
          <div style={{ display: "grid", gap: "10px" }}>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
              <StatusBadge tone={skill.health === "healthy" ? "positive" : skill.health === "warning" ? "warning" : "critical"}>{skill.health}</StatusBadge>
              <StatusBadge tone="neutral">{skill.platform}</StatusBadge>
              <StatusBadge tone="neutral">v{skill.version}</StatusBadge>
            </div>
            <div style={{ color: "rgba(233,239,255,0.7)", fontSize: "13px" }}>Last checked {formatCompactDate(skill.lastCheckedAt)}</div>
          </div>
        </Panel>
      ))}
    </div>
  );
}

