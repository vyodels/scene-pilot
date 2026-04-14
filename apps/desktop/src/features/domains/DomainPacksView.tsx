import React from "react";
import { Panel, StatusBadge } from "../../components";
import { theme } from "../../lib/theme";
import type { DomainPackRecord } from "../../lib/types";

interface DomainPacksViewProps {
  domainPacks: DomainPackRecord[];
}

export function DomainPacksView({ domainPacks }: DomainPacksViewProps): JSX.Element {
  return (
    <div style={{ display: "grid", gap: "18px", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))" }}>
      {domainPacks.map((pack) => (
        <Panel
          key={pack.key}
          title={pack.name}
          eyebrow={pack.key}
          description={pack.description}
          actions={<StatusBadge tone="neutral">{pack.templateKeys.length} templates</StatusBadge>}
        >
          <div style={{ display: "grid", gap: "12px" }}>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              {pack.defaultCapabilities.map((capability) => (
                <StatusBadge key={capability} tone="neutral">
                  {capability}
                </StatusBadge>
              ))}
            </div>
            <div>
              <div style={{ color: theme.colors.muted, fontSize: "12px", textTransform: "uppercase", letterSpacing: "0.14em" }}>Sample tasks</div>
              <div style={{ display: "grid", gap: "8px", marginTop: "10px" }}>
                {pack.sampleTasks.map((task) => (
                  <div key={task} style={{ color: "rgba(233,239,255,0.76)", fontSize: "13px", lineHeight: 1.5 }}>
                    {task}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </Panel>
      ))}
    </div>
  );
}
