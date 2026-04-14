import React from "react";
import { Panel, StatusBadge } from "../../components";
import { formatCompactDate } from "../../lib/format";
import type { RuntimePatch } from "../../lib/types";

interface PatchReviewViewProps {
  patches: RuntimePatch[];
  busyPatchId?: string;
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

export function PatchReviewView({ patches, busyPatchId, onApprove, onReject }: PatchReviewViewProps): JSX.Element {
  return (
    <Panel
      title="Workflow patches"
      eyebrow="Divergence review"
      description="When a trial diverges from the current plan, the runtime proposes a patch. Review it here before rollout."
    >
      <div style={{ display: "grid", gap: "12px" }}>
        {patches.map((patch) => {
          const busy = busyPatchId === patch.id;
          return (
            <article
              key={patch.id}
              style={{
                padding: "16px",
                borderRadius: "18px",
                background: "rgba(255,255,255,0.03)",
                border: "1px solid rgba(255,255,255,0.08)",
                display: "grid",
                gap: "10px",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: "8px", flexWrap: "wrap" }}>
                <div>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                    <strong>{patch.title}</strong>
                    <StatusBadge tone={patch.status === "pending_review" ? "warning" : patch.status === "applied" ? "positive" : "critical"}>
                      {patch.status}
                    </StatusBadge>
                  </div>
                  <div style={{ marginTop: "6px", color: "rgba(233,239,255,0.7)", fontSize: "13px", lineHeight: 1.5 }}>
                    {patch.divergenceSummary ?? patch.rationale ?? "No patch summary provided."}
                  </div>
                </div>
                <div style={{ color: "rgba(233,239,255,0.56)", fontSize: "12px" }}>
                  {patch.reviewedAt ? `Reviewed ${formatCompactDate(patch.reviewedAt)}` : `Raised ${formatCompactDate(patch.createdAt)}`}
                </div>
              </div>
              <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                <StatusBadge tone="neutral">{patch.patchKind}</StatusBadge>
                {patch.templateId ? <StatusBadge tone="neutral">template {patch.templateId.slice(0, 8)}</StatusBadge> : null}
                {patch.executionEpisodeId ? <StatusBadge tone="neutral">episode {patch.executionEpisodeId.slice(0, 8)}</StatusBadge> : null}
              </div>
              {patch.status === "pending_review" ? (
                <div style={{ display: "flex", gap: "10px", marginTop: "2px" }}>
                  <button
                    type="button"
                    onClick={() => onApprove(patch.id)}
                    disabled={busy}
                    style={{ ...buttonStyle, background: "rgba(93,216,163,0.14)", color: "#d7ffef" }}
                  >
                    {busy ? "Working..." : "Approve and apply"}
                  </button>
                  <button
                    type="button"
                    onClick={() => onReject(patch.id)}
                    disabled={busy}
                    style={{ ...buttonStyle, background: "rgba(255,122,122,0.12)", color: "#ffd9d9" }}
                  >
                    Reject
                  </button>
                </div>
              ) : null}
            </article>
          );
        })}
      </div>
    </Panel>
  );
}
