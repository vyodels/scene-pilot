import React from "react";
import { Panel, StatusBadge } from "../../components";
import type { ApprovalItem } from "../../lib/types";

interface ApprovalsViewProps {
  approvals: ApprovalItem[];
  pendingActionId?: string;
  onApprove(id: string): void;
  onReject(id: string): void;
}

const buttonStyle = {
  border: "1px solid rgba(255,255,255,0.12)",
  borderRadius: "12px",
  padding: "8px 12px",
  cursor: "pointer",
  fontWeight: 700,
} as const;

export function ApprovalsView({ approvals, pendingActionId, onApprove, onReject }: ApprovalsViewProps): JSX.Element {
  return (
    <Panel title="Approval queue" eyebrow="Human gates" description="Every item here blocks automation until it is explicitly accepted or rejected.">
      <div style={{ display: "grid", gap: "12px" }}>
        {approvals.map((approval) => (
          <article key={approval.id} style={{ padding: "14px", borderRadius: "16px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: "10px", alignItems: "start" }}>
              <div>
                <div style={{ fontWeight: 700 }}>{approval.title}</div>
                <div style={{ color: "rgba(233,239,255,0.68)", fontSize: "13px", marginTop: "4px", lineHeight: 1.5 }}>{approval.detail}</div>
              </div>
              <StatusBadge tone={approval.status === "pending" ? "warning" : approval.status === "approved" ? "positive" : "critical"}>{approval.status}</StatusBadge>
            </div>
            <div style={{ marginTop: "10px", color: "rgba(233,239,255,0.56)", fontSize: "12px" }}>
              Requester {approval.requester} · {approval.kind} · {approval.createdAt}
            </div>
            {approval.status === "pending" ? (
              <div style={{ display: "flex", gap: "10px", marginTop: "12px" }}>
                <button
                  type="button"
                  onClick={() => onApprove(approval.id)}
                  disabled={pendingActionId === approval.id}
                  style={{ ...buttonStyle, background: "rgba(93,216,163,0.14)", color: "#d7ffef" }}
                >
                  {pendingActionId === approval.id ? "Working..." : "Approve"}
                </button>
                <button
                  type="button"
                  onClick={() => onReject(approval.id)}
                  disabled={pendingActionId === approval.id}
                  style={{ ...buttonStyle, background: "rgba(255,122,122,0.12)", color: "#ffd9d9" }}
                >
                  Reject
                </button>
              </div>
            ) : null}
          </article>
        ))}
      </div>
    </Panel>
  );
}
