import React from "react";
import { Panel, StatusBadge } from "../../components";
import { formatCompactDate } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { translateUiToken } from "../../lib/uiText";
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
  const { copy } = useI18n();

  return (
    <Panel
      title={copy("Revision suggestions", "修订建议")}
      eyebrow={copy("Divergence review", "偏差审查")}
      description={copy("When a trial diverges from the current plan, the runtime proposes a revision suggestion. Review it here before rollout.", "当试跑偏离当前计划时，运行时会提出修订建议。请在正式生效前在这里审查。")}
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
                      {translateUiToken(patch.status, copy)}
                    </StatusBadge>
                  </div>
                  <div style={{ marginTop: "6px", color: "rgba(233,239,255,0.7)", fontSize: "13px", lineHeight: 1.5 }}>
                    {patch.divergenceSummary ?? patch.rationale ?? copy("No revision summary provided.", "未提供修订摘要。")}
                  </div>
                </div>
                <div style={{ color: "rgba(233,239,255,0.56)", fontSize: "12px" }}>
                  {patch.reviewedAt ? copy(`Reviewed ${formatCompactDate(patch.reviewedAt)}`, `审查于 ${formatCompactDate(patch.reviewedAt)}`) : copy(`Raised ${formatCompactDate(patch.createdAt)}`, `提出于 ${formatCompactDate(patch.createdAt)}`)}
                </div>
              </div>
              <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                <StatusBadge tone="neutral">{translateUiToken(patch.patchKind, copy)}</StatusBadge>
                {patch.templateId ? <StatusBadge tone="neutral">{copy(`template ${patch.templateId.slice(0, 8)}`, `模板 ${patch.templateId.slice(0, 8)}`)}</StatusBadge> : null}
                {patch.executionEpisodeId ? <StatusBadge tone="neutral">{copy(`instance ${patch.executionEpisodeId.slice(0, 8)}`, `实例 ${patch.executionEpisodeId.slice(0, 8)}`)}</StatusBadge> : null}
                {patch.runtimeMetadata?.apply_result && typeof patch.runtimeMetadata.apply_result === "object" ? (
                  <StatusBadge tone="positive">
                    {copy(`plan ${String((patch.runtimeMetadata.apply_result as Record<string, unknown>).execution_plan_version ?? "applied")}`, `计划 ${String((patch.runtimeMetadata.apply_result as Record<string, unknown>).execution_plan_version ?? "applied")}`)}
                  </StatusBadge>
                ) : null}
              </div>
              {patch.runtimeMetadata?.apply_result && typeof patch.runtimeMetadata.apply_result === "object" ? (
                <div style={{ color: "rgba(233,239,255,0.68)", fontSize: "13px", lineHeight: 1.6 }}>
                  {copy("Applied artifacts", "已应用产物")}:
                  {(() => {
                    const result = patch.runtimeMetadata.apply_result as Record<string, unknown>;
                    const parts = [
                      result.execution_plan_id ? copy(` plan ${String(result.execution_plan_id).slice(0, 8)}`, ` 计划 ${String(result.execution_plan_id).slice(0, 8)}`) : "",
                      result.template_id ? copy(` template ${String(result.template_id).slice(0, 8)}`, ` 模板 ${String(result.template_id).slice(0, 8)}`) : "",
                      result.previous_plan_id ? copy(` from ${String(result.previous_plan_id).slice(0, 8)}`, ` 来自 ${String(result.previous_plan_id).slice(0, 8)}`) : "",
                    ].filter(Boolean);
                    return parts.length ? parts.join(" ·") : copy(" no persisted artifacts recorded.", " 未记录持久化产物。");
                  })()}
                </div>
              ) : null}
              {patch.status === "pending_review" ? (
                <div style={{ display: "flex", gap: "10px", marginTop: "2px" }}>
                  <button
                    type="button"
                    onClick={() => onApprove(patch.id)}
                    disabled={busy}
                    style={{ ...buttonStyle, background: "rgba(93,216,163,0.14)", color: "#d7ffef" }}
                  >
                    {busy ? copy("Working...", "处理中...") : copy("Approve and apply", "批准并应用")}
                  </button>
                  <button
                    type="button"
                    onClick={() => onReject(patch.id)}
                    disabled={busy}
                    style={{ ...buttonStyle, background: "rgba(255,122,122,0.12)", color: "#ffd9d9" }}
                  >
                    {copy("Reject", "拒绝")}
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
