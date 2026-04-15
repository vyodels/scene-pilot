import React from "react";
import { StatusBadge } from "../../components";
import { useI18n } from "../../lib/i18n";
import { theme } from "../../lib/theme";
import { translateUiToken } from "../../lib/uiText";
import type { ApprovalItem } from "../../lib/types";

interface HumanAssistDockProps {
  approvals: ApprovalItem[];
  pendingActionId?: string;
  isOpen: boolean;
  onToggle(): void;
  onApprove(id: string): void;
  onReject(id: string): void;
}

function stringifyPayload(payload: Record<string, unknown> | undefined): string {
  if (!payload || !Object.keys(payload).length) {
    return "";
  }
  return JSON.stringify(payload, null, 2);
}

const actionButtonBase = {
  borderRadius: "12px",
  padding: "10px 12px",
  fontSize: "13px",
  fontWeight: 700,
  cursor: "pointer",
  border: "1px solid transparent",
} as const;

export function HumanAssistDock({
  approvals,
  pendingActionId,
  isOpen,
  onToggle,
  onApprove,
  onReject,
}: HumanAssistDockProps): JSX.Element {
  const { copy } = useI18n();
  const pendingApprovals = approvals.filter((item) => item.status === "pending");
  const primaryApproval = pendingApprovals[0] ?? approvals[0] ?? null;

  return (
    <div
      style={{
        position: "fixed",
        right: "22px",
        bottom: "22px",
        zIndex: 60,
        display: "grid",
        justifyItems: "end",
        gap: "12px",
        pointerEvents: "none",
      }}
    >
      {isOpen ? (
        <section
          style={{
            width: "min(440px, calc(100vw - 28px))",
            maxHeight: "min(74vh, 760px)",
            overflow: "hidden",
            pointerEvents: "auto",
            display: "grid",
            gridTemplateRows: "auto 1fr",
            borderRadius: "24px",
            border: `1px solid ${theme.colors.border}`,
            background:
              "linear-gradient(180deg, rgba(10,16,26,0.98) 0%, rgba(16,23,38,0.98) 100%)",
            boxShadow: "0 32px 80px rgba(0, 0, 0, 0.42)",
            backdropFilter: "blur(22px)",
          }}
        >
          <header
            style={{
              padding: "16px 16px 14px",
              borderBottom: "1px solid rgba(255,255,255,0.08)",
              display: "flex",
              justifyContent: "space-between",
              gap: "14px",
              alignItems: "start",
            }}
          >
            <div>
              <div style={{ color: theme.colors.accent, fontSize: "11px", letterSpacing: "0.14em", textTransform: "uppercase" }}>
                {copy("Human assist", "人工协助")}
              </div>
              <div style={{ marginTop: "6px", fontSize: "19px", fontWeight: 800 }}>
                {copy("Approval inbox", "确认会话")}
              </div>
              <div style={{ marginTop: "4px", color: theme.colors.muted, fontSize: "13px", lineHeight: 1.5 }}>
                {copy(
                  "The runtime will pause here when it needs approval, context, or operator confirmation.",
                  "运行时在需要审批、上下文补充或操作员确认时会暂停在这里。",
                )}
              </div>
            </div>
            <button
              type="button"
              onClick={onToggle}
              style={{
                ...actionButtonBase,
                pointerEvents: "auto",
                background: "rgba(255,255,255,0.06)",
                borderColor: "rgba(255,255,255,0.1)",
                color: theme.colors.text,
              }}
            >
              {copy("Collapse", "收起")}
            </button>
          </header>
          <div style={{ overflow: "auto", padding: "14px", display: "grid", gap: "12px" }}>
            {pendingApprovals.length ? (
              pendingApprovals.map((approval, index) => {
                const payloadText = stringifyPayload(approval.payload);
                return (
                  <article
                    key={approval.id}
                    style={{
                      borderRadius: "18px",
                      border: "1px solid rgba(255,255,255,0.08)",
                      background: index === 0 ? "rgba(67, 198, 172, 0.08)" : "rgba(255,255,255,0.03)",
                      padding: "14px",
                      display: "grid",
                      gap: "10px",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", gap: "10px", alignItems: "start" }}>
                      <div>
                        <div style={{ fontSize: "12px", color: theme.colors.muted }}>
                          {copy("Awaiting confirmation", "等待确认")} · {translateUiToken(approval.kind, copy)}
                        </div>
                        <div style={{ marginTop: "4px", fontSize: "16px", fontWeight: 700 }}>{approval.title}</div>
                      </div>
                      <StatusBadge tone="warning">{copy("Pending", "待处理")}</StatusBadge>
                    </div>
                    <div
                      style={{
                        borderRadius: "14px",
                        background: "rgba(255,255,255,0.04)",
                        padding: "10px 12px",
                        color: theme.colors.text,
                        fontSize: "13px",
                        lineHeight: 1.6,
                      }}
                    >
                      {approval.detail}
                    </div>
                    <div style={{ color: theme.colors.muted, fontSize: "12px", lineHeight: 1.6 }}>
                      {copy("Requester", "提交方")}: {translateUiToken(approval.requester, copy)}
                      <br />
                      {copy("Target", "目标")}: {translateUiToken(approval.targetType ?? approval.kind, copy)}
                      {approval.targetId ? ` · ${approval.targetId}` : ""}
                      <br />
                      {copy("Created", "创建时间")}: {translateUiToken(approval.createdAt, copy)}
                    </div>
                    {approval.notes ? (
                      <div
                        style={{
                          borderLeft: "2px solid rgba(93, 216, 163, 0.5)",
                          paddingLeft: "10px",
                          fontSize: "12px",
                          color: theme.colors.muted,
                          lineHeight: 1.6,
                        }}
                      >
                        {copy("Background", "背景信息")}: {approval.notes}
                      </div>
                    ) : null}
                    {payloadText ? (
                      <details
                        open={index === 0}
                        style={{
                          borderRadius: "14px",
                          background: "rgba(6,10,18,0.7)",
                          padding: "10px 12px",
                        }}
                      >
                        <summary style={{ cursor: "pointer", fontSize: "12px", fontWeight: 700, color: theme.colors.text }}>
                          {copy("Context payload", "上下文载荷")}
                        </summary>
                        <pre
                          style={{
                            margin: "10px 0 0",
                            whiteSpace: "pre-wrap",
                            wordBreak: "break-word",
                            color: "#cdd7f7",
                            fontSize: "11px",
                            lineHeight: 1.6,
                            maxHeight: "220px",
                            overflow: "auto",
                          }}
                        >
                          {payloadText}
                        </pre>
                      </details>
                    ) : null}
                    <div style={{ display: "flex", gap: "10px" }}>
                      <button
                        type="button"
                        onClick={() => onApprove(approval.id)}
                        disabled={pendingActionId === approval.id}
                        style={{
                          ...actionButtonBase,
                          flex: 1,
                          background: "rgba(93, 216, 163, 0.16)",
                          borderColor: "rgba(93, 216, 163, 0.24)",
                          color: "#d7ffef",
                        }}
                      >
                        {pendingActionId === approval.id ? copy("Working...", "处理中...") : copy("Approve and continue", "批准并继续")}
                      </button>
                      <button
                        type="button"
                        onClick={() => onReject(approval.id)}
                        disabled={pendingActionId === approval.id}
                        style={{
                          ...actionButtonBase,
                          background: "rgba(255,122,122,0.14)",
                          borderColor: "rgba(255,122,122,0.18)",
                          color: "#ffd9d9",
                        }}
                      >
                        {copy("Reject", "拒绝")}
                      </button>
                    </div>
                  </article>
                );
              })
            ) : (
              <article
                style={{
                  borderRadius: "18px",
                  border: "1px solid rgba(255,255,255,0.08)",
                  background: "rgba(255,255,255,0.03)",
                  padding: "16px",
                  display: "grid",
                  gap: "10px",
                }}
              >
                <div style={{ fontSize: "16px", fontWeight: 700 }}>{copy("No pending approvals", "当前没有待处理确认")}</div>
                <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                  {primaryApproval
                    ? copy("Recent approval history remains available in the approvals center.", "最近的审批历史仍可在审批中心查看。")
                    : copy("The runtime can continue without operator intervention for now.", "当前运行时无需操作员介入。")}
                </div>
              </article>
            )}
          </div>
        </section>
      ) : null}
      <button
        type="button"
        onClick={onToggle}
        style={{
          pointerEvents: "auto",
          display: "inline-flex",
          alignItems: "center",
          gap: "10px",
          borderRadius: "999px",
          padding: "12px 16px",
          border: "1px solid rgba(255,255,255,0.1)",
          background: pendingApprovals.length
            ? "linear-gradient(135deg, rgba(67,198,172,0.22), rgba(244,193,93,0.22))"
            : "rgba(14,20,33,0.88)",
          color: theme.colors.text,
          boxShadow: "0 18px 40px rgba(0,0,0,0.28)",
          cursor: "pointer",
          fontWeight: 800,
        }}
      >
        <span>{copy("Assist", "协助")}</span>
        <StatusBadge tone={pendingApprovals.length ? "warning" : "neutral"}>
          {pendingApprovals.length ? copy(`${pendingApprovals.length} pending`, `${pendingApprovals.length} 个待处理`) : copy("Idle", "空闲")}
        </StatusBadge>
      </button>
    </div>
  );
}
