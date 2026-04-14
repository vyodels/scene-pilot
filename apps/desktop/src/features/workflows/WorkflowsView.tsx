import React from "react";
import { Panel, StatusBadge } from "../../components";
import { formatCompactDate } from "../../lib/format";
import type { WorkflowDefinition } from "../../lib/types";

interface WorkflowsViewProps {
  workflows: WorkflowDefinition[];
}

export function WorkflowsView({ workflows }: WorkflowsViewProps): JSX.Element {
  return (
    <div style={{ display: "grid", gap: "18px" }}>
      {workflows.map((workflow) => (
        <Panel
          key={workflow.id}
          title={workflow.name}
          eyebrow={workflow.jdTitle}
          description={`Version ${workflow.version} · Updated ${formatCompactDate(workflow.updatedAt)}`}
          actions={<StatusBadge tone={workflow.status === "active" ? "positive" : workflow.status === "draft" ? "warning" : "neutral"}>{workflow.status}</StatusBadge>}
        >
          <div style={{ display: "grid", gap: "10px" }}>
            {workflow.nodes.map((node, index) => (
              <div
                key={node.id}
                style={{
                  display: "grid",
                  gridTemplateColumns: "52px minmax(0, 1fr) auto",
                  gap: "12px",
                  alignItems: "start",
                  padding: "14px",
                  borderRadius: "16px",
                  background: "rgba(255,255,255,0.03)",
                  border: "1px solid rgba(255,255,255,0.08)",
                }}
              >
                <StatusBadge tone={node.status === "approved" ? "positive" : node.status === "running" ? "warning" : node.status === "blocked" ? "critical" : "neutral"}>
                  {index + 1}
                </StatusBadge>
                <div>
                  <div style={{ fontWeight: 700 }}>{node.name}</div>
                  <div style={{ color: "rgba(233,239,255,0.72)", fontSize: "13px", lineHeight: 1.5 }}>{node.description}</div>
                  <div style={{ color: "rgba(233,239,255,0.55)", fontSize: "12px", marginTop: "4px" }}>
                    Node {node.id} · Owner {node.owner}
                  </div>
                </div>
                <StatusBadge tone={node.status === "approved" ? "positive" : node.status === "running" ? "warning" : node.status === "blocked" ? "critical" : "neutral"}>
                  {node.kind}
                </StatusBadge>
              </div>
            ))}
          </div>
        </Panel>
      ))}
    </div>
  );
}

