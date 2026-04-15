import React, { useEffect, useMemo, useState } from "react";
import { Panel, StatusBadge } from "../../components";
import { formatCompactDate } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { theme } from "../../lib/theme";
import { translateUiToken } from "../../lib/uiText";
import type {
  AgentEvent,
  ApprovalItem,
  EvolutionArtifactRecord,
  ExecutionGraphProjectionRecord,
  ExecutionTraceRecord,
  GoalSpecRecord,
  OperatorInteractionRecord,
  SkillRecord,
} from "../../lib/types";

type InboxFilter = "all" | "interactions" | "approvals" | "permissions" | "skills" | "artifacts";

type InboxItem =
  | {
      key: string;
      kind: "interaction";
      title: string;
      detail: string;
      at: string;
      tone: "positive" | "neutral" | "warning" | "critical";
      interaction: OperatorInteractionRecord;
      candidateId?: string | null;
    }
  | {
      key: string;
      kind: "approval";
      title: string;
      detail: string;
      at: string;
      tone: "positive" | "neutral" | "warning" | "critical";
      approval: ApprovalItem;
      candidateId?: string | null;
    }
  | {
      key: string;
      kind: "skill";
      title: string;
      detail: string;
      at: string;
      tone: "positive" | "neutral" | "warning" | "critical";
      skill: SkillRecord;
    }
  | {
      key: string;
      kind: "artifact";
      title: string;
      detail: string;
      at: string;
      tone: "positive" | "neutral" | "warning" | "critical";
      artifact: EvolutionArtifactRecord;
    };

type InteractionInboxItem = Extract<InboxItem, { kind: "interaction" }>;
type ApprovalInboxItem = Extract<InboxItem, { kind: "approval" }>;
type SkillInboxItem = Extract<InboxItem, { kind: "skill" }>;
type ArtifactInboxItem = Extract<InboxItem, { kind: "artifact" }>;

interface AgentInboxViewProps {
  interactions: OperatorInteractionRecord[];
  approvals: ApprovalItem[];
  skills: SkillRecord[];
  artifacts: EvolutionArtifactRecord[];
  events: AgentEvent[];
  goals: GoalSpecRecord[];
  traces: ExecutionTraceRecord[];
  graphs: ExecutionGraphProjectionRecord[];
  pendingActionId?: string;
  requestedFilter?: string;
  requestedItemId?: string;
  onApprove(id: string): Promise<void> | void;
  onReject(id: string): Promise<void> | void;
  onResolveInteraction(id: string, action: string, comment?: string): Promise<void> | void;
  onOpenCandidate(candidateId: string): void;
  onOpenEvolution(section?: string, itemId?: string): void;
}

const buttonStyle: React.CSSProperties = {
  border: `1px solid ${theme.colors.border}`,
  borderRadius: "10px",
  background: "rgba(255,255,255,0.04)",
  color: theme.colors.text,
  padding: "8px 10px",
  cursor: "pointer",
  fontWeight: 700,
};

function toneFromSkill(skill: SkillRecord): "positive" | "neutral" | "warning" | "critical" {
  if (skill.health === "critical" || skill.status === "degraded") {
    return "critical";
  }
  if (skill.health === "warning" || skill.status === "pending_review") {
    return "warning";
  }
  return "positive";
}

function toneFromArtifact(artifact: EvolutionArtifactRecord): "positive" | "neutral" | "warning" | "critical" {
  if (/(rejected|disabled|failed)/i.test(artifact.status)) {
    return "critical";
  }
  if (/(pending|draft|review)/i.test(artifact.status)) {
    return "warning";
  }
  if (/(approved|applied|active)/i.test(artifact.status)) {
    return "positive";
  }
  return "neutral";
}

function toneFromApproval(approval: ApprovalItem): "positive" | "neutral" | "warning" | "critical" {
  if (approval.status === "rejected") {
    return "critical";
  }
  if (approval.status === "approved") {
    return "positive";
  }
  return "warning";
}

function toneFromInteraction(item: OperatorInteractionRecord): "positive" | "neutral" | "warning" | "critical" {
  if (item.status === "resolved") {
    return "positive";
  }
  if (/(handoff|stop)/i.test(item.interactionType)) {
    return "critical";
  }
  return "warning";
}

function summarizePayload(payload: Record<string, unknown> | undefined): string[] {
  if (!payload || !Object.keys(payload).length) {
    return [];
  }
  const entries = Object.entries(payload).slice(0, 4);
  return entries.map(([key, value]) => `${key}: ${typeof value === "string" ? value : JSON.stringify(value)}`);
}

function humanizeLabel(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export function AgentInboxView({
  interactions,
  approvals,
  skills,
  artifacts,
  events,
  goals,
  traces,
  graphs,
  pendingActionId,
  requestedFilter,
  requestedItemId,
  onApprove,
  onReject,
  onResolveInteraction,
  onOpenCandidate,
  onOpenEvolution,
}: AgentInboxViewProps): JSX.Element {
  const { copy } = useI18n();
  const [filter, setFilter] = useState<InboxFilter>("all");
  const [selectedKey, setSelectedKey] = useState<string>();

  const interactionItems = useMemo<InteractionInboxItem[]>(
    () =>
      interactions
        .filter((item) => !item.candidateId)
        .map<InteractionInboxItem>((interaction) => ({
          key: `interaction:${interaction.id}`,
          kind: "interaction",
          title: interaction.title,
          detail: interaction.agentPrompt,
          at: interaction.updatedAt ?? interaction.surfacedAt,
          tone: toneFromInteraction(interaction),
          interaction,
          candidateId: interaction.candidateId,
        })),
    [interactions],
  );

  const runtimeItems = useMemo<ApprovalInboxItem[]>(
    () =>
      approvals
        .filter((item) => !item.relatedCandidateId)
        .map<ApprovalInboxItem>((approval) => ({
          key: `approval:${approval.id}`,
          kind: "approval",
          title: approval.title,
          detail: approval.detail,
          at: approval.updatedAt ?? approval.createdAt,
          tone: toneFromApproval(approval),
          approval,
          candidateId: approval.relatedCandidateId,
        })),
    [approvals],
  );

  const skillItems = useMemo<SkillInboxItem[]>(
    () =>
      skills
        .filter((skill) => skill.status !== "active" || skill.health !== "healthy")
        .map<SkillInboxItem>((skill) => ({
          key: `skill:${skill.id}`,
          kind: "skill",
          title: skill.name,
          detail: skill.summary,
          at: skill.lastCheckedAt,
          tone: toneFromSkill(skill),
          skill,
        })),
    [skills],
  );

  const artifactItems = useMemo<ArtifactInboxItem[]>(
    () =>
      artifacts
        .filter((artifact) => !/(applied|archived)/i.test(artifact.status))
        .map<ArtifactInboxItem>((artifact) => ({
          key: `artifact:${artifact.id}`,
          kind: "artifact",
          title: artifact.title,
          detail: artifact.summary ?? artifact.artifactKind,
          at: artifact.updatedAt,
          tone: toneFromArtifact(artifact),
          artifact,
        })),
    [artifacts],
  );

  const items = useMemo(() => {
    const merged = [...interactionItems, ...runtimeItems, ...skillItems, ...artifactItems].sort((left, right) => right.at.localeCompare(left.at));
    switch (filter) {
      case "interactions":
        return merged.filter((item) => item.kind === "interaction");
      case "approvals":
        return merged.filter((item) => item.kind === "approval");
      case "permissions":
        return merged.filter(
          (item) =>
            item.kind === "approval" &&
            /(system_command|permission|command)/i.test(item.approval.targetType ?? item.approval.kind ?? ""),
        );
      case "skills":
        return merged.filter((item) => item.kind === "skill");
      case "artifacts":
        return merged.filter((item) => item.kind === "artifact");
      default:
        return merged;
    }
  }, [artifactItems, filter, interactionItems, runtimeItems, skillItems]);

  useEffect(() => {
    if (requestedFilter === "interactions" || requestedFilter === "approvals" || requestedFilter === "permissions" || requestedFilter === "skills" || requestedFilter === "artifacts" || requestedFilter === "all") {
      setFilter(requestedFilter);
    }
  }, [requestedFilter]);

  useEffect(() => {
    if (requestedItemId) {
      const directKey = items.find((item) => item.key === requestedItemId || item.key.endsWith(`:${requestedItemId}`))?.key;
      if (directKey) {
        setSelectedKey(directKey);
        return;
      }
    }
    if (!items.length) {
      setSelectedKey(undefined);
      return;
    }
    if (!selectedKey || !items.some((item) => item.key === selectedKey)) {
      setSelectedKey(items[0].key);
    }
  }, [items, requestedItemId, selectedKey]);

  const selected = items.find((item) => item.key === selectedKey) ?? null;
  const pendingInteractions = interactionItems.filter((item) => item.interaction.status === "pending").length;
  const pendingApprovals = runtimeItems.filter((item) => item.approval.status === "pending").length;
  const degradedSkills = skillItems.filter((item) => item.skill.health !== "healthy" || item.skill.status !== "active").length;
  const pendingArtifacts = artifactItems.filter((item) => /(pending|draft|review)/i.test(item.artifact.status)).length;
  const recentSignals = events.filter((event) => event.level !== "info").slice(-6).reverse();
  const latestGoal = goals[0] ?? null;
  const latestTrace = traces[0] ?? null;
  const latestGraph = graphs[0] ?? null;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "280px minmax(0, 1fr) 320px", gap: "16px", minWidth: 0 }}>
      <Panel
        dense
        title={copy("Agent IM", "Agent IM")}
        eyebrow={copy("Runtime orchestration", "运行编排")}
        description={copy("Run-time confirmations, degraded skills, and evolution drafts are handled here without mixing candidate chat.", "这里处理运行时确认、skill 异常和演进草稿，不混入候选人聊天。")}
      >
        <div style={{ display: "grid", gap: "8px" }}>
          {[
            { key: "all", label: copy("All", "全部"), count: items.length },
            { key: "interactions", label: copy("Interactions", "确认/介入"), count: pendingInteractions },
            { key: "approvals", label: copy("Legacy approvals", "兼容审批"), count: pendingApprovals },
            { key: "permissions", label: copy("Permissions", "权限"), count: runtimeItems.filter((item) => /(system_command|permission|command)/i.test(item.approval.targetType ?? item.approval.kind ?? "")).length },
            { key: "skills", label: copy("Skills", "Skills"), count: degradedSkills },
            { key: "artifacts", label: copy("Artifacts", "演进产物"), count: pendingArtifacts },
          ].map((entry) => (
            <button
              key={entry.key}
              type="button"
              onClick={() => setFilter(entry.key as InboxFilter)}
              style={{
                display: "grid",
                gridTemplateColumns: "1fr auto",
                alignItems: "center",
                gap: "8px",
                textAlign: "left",
                padding: "9px 10px",
                borderRadius: "10px",
                border: `1px solid ${filter === entry.key ? "rgba(122,167,255,0.34)" : theme.colors.border}`,
                background: filter === entry.key ? "rgba(122,167,255,0.10)" : "rgba(255,255,255,0.02)",
                color: theme.colors.text,
                cursor: "pointer",
              }}
            >
              <span style={{ fontWeight: 700 }}>{entry.label}</span>
              <StatusBadge tone={entry.count ? "warning" : "neutral"}>{entry.count}</StatusBadge>
            </button>
          ))}
        </div>
        <div style={{ marginTop: "14px", display: "grid", gap: "6px", maxHeight: "62vh", overflowY: "auto" }}>
          {items.map((item) => (
            <button
              key={item.key}
              type="button"
              onClick={() => setSelectedKey(item.key)}
              style={{
                display: "grid",
                gap: "4px",
                textAlign: "left",
                padding: "10px 11px",
                borderRadius: "10px",
                border: `1px solid ${selected?.key === item.key ? "rgba(122,167,255,0.34)" : theme.colors.border}`,
                background: selected?.key === item.key ? "rgba(122,167,255,0.10)" : "rgba(255,255,255,0.02)",
                color: theme.colors.text,
                cursor: "pointer",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: "8px", alignItems: "start" }}>
                <strong style={{ fontSize: "13px", lineHeight: 1.4 }}>{item.title}</strong>
                <StatusBadge tone={item.tone}>
                  {item.kind === "interaction"
                    ? translateUiToken(item.interaction.status, copy)
                    : item.kind === "approval"
                      ? translateUiToken(item.approval.status, copy)
                      : item.kind === "skill"
                        ? item.skill.health
                        : translateUiToken(item.artifact.status, copy)}
                </StatusBadge>
              </div>
              <div style={{ color: theme.colors.muted, fontSize: "12px", lineHeight: 1.5 }}>{item.detail}</div>
              <div style={{ color: theme.colors.muted, fontSize: "11px" }}>{formatCompactDate(item.at)}</div>
            </button>
          ))}
        </div>
      </Panel>

      <Panel
        dense
        title={selected?.title ?? copy("Inbox detail", "收件箱详情")}
        eyebrow={copy("Operator chat", "操作员会话")}
        description={
          selected
            ? copy("You can approve, reject, or route the issue without leaving this chat surface.", "你可以直接在这个会话面里批准、拒绝或跳转处理，而不用离开当前页面。")
            : copy("Select an item from the left list.", "从左侧列表选择一项。")
        }
      >
        {selected ? (
          <div style={{ display: "grid", gap: "14px", minWidth: 0 }}>
            <div style={{ display: "grid", gap: "10px" }}>
              <div
                style={{
                  maxWidth: "78%",
                  borderRadius: "16px",
                  padding: "12px 13px",
                  border: "1px solid rgba(122,167,255,0.18)",
                  background: "rgba(122,167,255,0.12)",
                  justifySelf: "start",
                }}
              >
                <div style={{ color: theme.colors.muted, fontSize: "12px", marginBottom: "6px" }}>{copy("Recruit Agent", "Recruit Agent")} · {formatCompactDate(selected.at)}</div>
                <div style={{ lineHeight: 1.65 }}>{selected.detail}</div>
              </div>
              <div
                style={{
                  maxWidth: "74%",
                  borderRadius: "16px",
                  padding: "12px 13px",
                  border: `1px solid ${theme.colors.border}`,
                  background: "rgba(255,255,255,0.03)",
                  justifySelf: "end",
                }}
              >
                <div style={{ color: theme.colors.muted, fontSize: "12px", marginBottom: "6px" }}>{copy("Operator options", "操作选项")}</div>
                <div style={{ lineHeight: 1.65 }}>
                  {selected.kind === "interaction"
                    ? copy("These options are generated for the current runtime block. Confirm one here, or add your own comment to steer the next attempt.", "这些选项是当前运行时阻塞下生成的可执行选择。你可以直接确认，也可以补充意见来纠偏下一次尝试。")
                    : selected.kind === "approval"
                    ? copy("This request can be resolved directly here. Use Evolution only when you need a full diff or history.", "这条请求可以直接在这里处理。只有需要查看完整 diff 或历史版本时才进入 Evolution。")
                    : selected.kind === "skill"
                      ? copy("The skill is visible and manageable, but structural edits belong in Evolution.", "这个 skill 的状态已经暴露出来，但结构化修改仍建议在 Evolution 中完成。")
                      : copy("This evolution artifact can be reviewed in detail inside Evolution, but you do not have to leave the current IM surface just to see why it appeared.", "这个演进产物可以在 Evolution 中细审，但你不需要为了知道它为什么出现而离开当前 IM 面。")}
                </div>
              </div>
            </div>

            {selected.kind === "interaction" ? (
              <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                {(selected.interaction.suggestedOptions.length ? selected.interaction.suggestedOptions : [{ id: "confirm", label: copy("Continue", "继续执行"), action: "confirm" }]).map((option) => {
                  const action = String(option.action ?? option.id ?? "confirm");
                  return (
                    <button
                      key={String(option.id ?? action)}
                      type="button"
                      onClick={() => void onResolveInteraction(selected.interaction.id, action)}
                      disabled={pendingActionId === selected.interaction.id}
                      style={buttonStyle}
                    >
                      {String(option.label ?? humanizeLabel(action))}
                    </button>
                  );
                })}
                {selected.interaction.candidateId ? (
                  <button type="button" onClick={() => onOpenCandidate(selected.interaction.candidateId!)} style={buttonStyle}>
                    {copy("Open candidate", "打开候选人")}
                  </button>
                ) : null}
              </div>
            ) : null}

            {selected.kind === "approval" && selected.approval.status === "pending" ? (
              <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                <button type="button" onClick={() => void onApprove(selected.approval.id)} disabled={pendingActionId === selected.approval.id} style={buttonStyle}>
                  {pendingActionId === selected.approval.id ? copy("Working...", "处理中...") : copy("Approve here", "直接批准")}
                </button>
                <button type="button" onClick={() => void onReject(selected.approval.id)} disabled={pendingActionId === selected.approval.id} style={{ ...buttonStyle, background: "rgba(255,122,122,0.10)", color: "#ffdede" }}>
                  {copy("Reject here", "直接拒绝")}
                </button>
                <button type="button" onClick={() => onOpenEvolution("approvals", selected.approval.id)} style={buttonStyle}>
                  {copy("Open in Evolution", "去 Evolution 审查")}
                </button>
              </div>
            ) : null}

            {selected.kind === "artifact" ? (
              <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                <button type="button" onClick={() => onOpenEvolution("inbox", selected.artifact.id)} style={buttonStyle}>
                  {copy("Review in Evolution", "去 Evolution 审查")}
                </button>
                {selected.artifact.relatedCandidateId ? (
                  <button type="button" onClick={() => onOpenCandidate(selected.artifact.relatedCandidateId!)} style={buttonStyle}>
                    {copy("Open candidate", "打开候选人")}
                  </button>
                ) : null}
              </div>
            ) : null}

            {selected.kind === "skill" ? (
              <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                <button type="button" onClick={() => onOpenEvolution("skills", selected.skill.id)} style={buttonStyle}>
                  {copy("Manage in Evolution", "去 Evolution 管理")}
                </button>
              </div>
            ) : null}

            <div style={{ borderTop: `1px solid ${theme.colors.border}`, paddingTop: "12px", display: "grid", gap: "8px" }}>
              <div style={{ fontSize: "12px", color: theme.colors.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>{copy("Context", "上下文")}</div>
              {selected.kind === "interaction" ? (
                <div style={{ display: "grid", gap: "6px", fontSize: "13px", lineHeight: 1.6 }}>
                  <div>{copy("Lane", "执行通道")}: {translateUiToken(selected.interaction.lane, copy)}</div>
                  <div>{copy("Type", "类型")}: {translateUiToken(selected.interaction.interactionType, copy)}</div>
                  <div>{copy("Scope", "影响范围")}: {translateUiToken(selected.interaction.scope, copy)}</div>
                </div>
              ) : null}
              {selected.kind === "approval"
                ? summarizePayload(selected.approval.payload).map((line) => (
                    <div key={line} style={{ fontSize: "13px", lineHeight: 1.6 }}>
                      {line}
                    </div>
                  ))
                : null}
              {selected.kind === "skill" ? (
                <div style={{ display: "grid", gap: "6px", fontSize: "13px" }}>
                  <div>{copy("Bound node", "绑定节点")}: {selected.skill.boundNode}</div>
                  <div>{copy("Version", "版本")}: {selected.skill.version}</div>
                  <div>{copy("Risk", "风险")}: {selected.skill.riskLevel ?? "medium"}</div>
                </div>
              ) : null}
              {selected.kind === "artifact" ? (
                <div style={{ display: "grid", gap: "6px", fontSize: "13px" }}>
                  <div>{copy("Kind", "类型")}: {selected.artifact.artifactKind}</div>
                  <div>{copy("Status", "状态")}: {translateUiToken(selected.artifact.status, copy)}</div>
                  <div>{copy("Source", "来源")}: {String(selected.artifact.artifactMetadata.source ?? "unknown")}</div>
                </div>
              ) : null}
            </div>
          </div>
        ) : (
          <div style={{ color: theme.colors.muted }}>{copy("No pending Agent IM items.", "当前没有待处理的 Agent IM 项。")}</div>
        )}
      </Panel>

      <Panel dense title={copy("Signals", "旁路信号")} eyebrow={copy("Recent context", "最近上下文")} description={copy("Signals stay dense. The right rail is for scope, risk, and fast routing, not for a pile of large cards.", "右侧只放范围、风险和快速跳转，不堆大卡片。")}>
        <div style={{ display: "grid", gap: "10px" }}>
          {latestGoal ? (
            <div style={{ display: "grid", gap: "6px", fontSize: "13px" }}>
              <div style={{ fontSize: "12px", color: theme.colors.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>{copy("Latest goal", "最近目标")}</div>
              <strong>{latestGoal.title}</strong>
              <div style={{ color: theme.colors.muted, lineHeight: 1.5 }}>{latestGoal.summary ?? latestGoal.goalText}</div>
            </div>
          ) : null}
          {latestTrace ? (
            <div style={{ display: "grid", gap: "6px", fontSize: "13px" }}>
              <div style={{ fontSize: "12px", color: theme.colors.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>{copy("Latest trace", "最近轨迹")}</div>
              <div>{latestTrace.summary ?? latestTrace.status}</div>
            </div>
          ) : null}
          {latestGraph?.renderedText ? (
            <div style={{ display: "grid", gap: "6px", fontSize: "12px" }}>
              <div style={{ fontSize: "12px", color: theme.colors.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>{copy("Graph projection", "执行图投影")}</div>
              <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: "12px", lineHeight: 1.5, color: "rgba(233,239,255,0.78)" }}>
                {latestGraph.renderedText}
              </pre>
            </div>
          ) : null}
          {selected?.kind === "approval" ? (
            <>
              <div style={{ display: "grid", gap: "6px", fontSize: "13px" }}>
                <div>{copy("Requester", "请求方")}: {selected.approval.requester}</div>
                <div>{copy("Target", "目标")}: {selected.approval.targetType ?? selected.approval.kind}</div>
                <div>{copy("Status", "状态")}: {translateUiToken(selected.approval.status, copy)}</div>
              </div>
              {selected.approval.relatedCandidateId ? (
                <button type="button" onClick={() => onOpenCandidate(selected.approval.relatedCandidateId!)} style={buttonStyle}>
                  {copy("Open candidate thread", "打开候选人线程")}
                </button>
              ) : null}
            </>
          ) : null}
          {selected?.kind === "interaction" ? (
            <div style={{ display: "grid", gap: "6px", fontSize: "13px" }}>
              <div>{copy("Status", "状态")}: {translateUiToken(selected.interaction.status, copy)}</div>
              <div>{copy("Suggested actions", "建议操作数")}: {selected.interaction.suggestedOptions.length}</div>
            </div>
          ) : null}

          <div style={{ borderTop: `1px solid ${theme.colors.border}`, paddingTop: "10px", display: "grid", gap: "8px" }}>
            <div style={{ fontSize: "12px", color: theme.colors.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>{copy("Recent signals", "最近信号")}</div>
            {recentSignals.map((event) => (
              <div key={event.id} style={{ display: "grid", gap: "4px", fontSize: "13px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "8px" }}>
                  <strong>{translateUiToken(event.source, copy)}</strong>
                  <StatusBadge tone={event.level === "error" ? "critical" : event.level === "warning" ? "warning" : "positive"}>
                    {translateUiToken(event.level, copy)}
                  </StatusBadge>
                </div>
                <div style={{ color: theme.colors.muted, lineHeight: 1.5 }}>{event.message}</div>
              </div>
            ))}
          </div>
        </div>
      </Panel>
    </div>
  );
}
