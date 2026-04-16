import React, { useEffect, useMemo, useState } from "react";
import { MetricCard, Panel, StatusBadge } from "../../components";
import { formatCompactDate } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
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

const theme = {
  colors: {
    background: "var(--bg-page)",
    panel: "var(--bg-card)",
    border: "var(--border-line)",
    text: "var(--text-primary)",
    muted: "var(--text-secondary)",
    positive: "var(--success)",
    warning: "var(--warning)",
    critical: "var(--danger)",
    accent: "var(--brand-primary)",
    accentSoft: "var(--brand-primary-soft)",
  },
  radius: {
    xl: "var(--radius-lg)",
    lg: "var(--radius-md)",
    md: "var(--radius-sm)",
    sm: "var(--radius-xs)",
  },
  shadow: "var(--shadow-pop)",
} as const;

const buttonStyle: React.CSSProperties = {
  border: `1px solid ${theme.colors.border}`,
  borderRadius: theme.radius.sm,
  background: theme.colors.panel,
  color: theme.colors.text,
  minHeight: "var(--space-8)",
  padding: "0 var(--space-4)",
  cursor: "pointer",
  fontWeight: 600,
};

const dangerButtonStyle: React.CSSProperties = {
  ...buttonStyle,
  borderColor: theme.colors.critical,
  color: theme.colors.critical,
};

function listCardStyle(active: boolean): React.CSSProperties {
  return {
    display: "grid",
    gap: "var(--space-1)",
    textAlign: "left",
    padding: "var(--space-3)",
    borderRadius: theme.radius.lg,
    border: `1px solid ${active ? theme.colors.accent : theme.colors.border}`,
    background: active ? theme.colors.accentSoft : theme.colors.background,
    color: theme.colors.text,
    cursor: "pointer",
  };
}

function messageBubbleStyle(tone: "accent" | "neutral"): React.CSSProperties {
  return {
    maxWidth: "60%",
    borderRadius: theme.radius.xl,
    padding: "var(--space-3)",
    border: `1px solid ${tone === "accent" ? theme.colors.accent : theme.colors.border}`,
    background: tone === "accent" ? theme.colors.accentSoft : theme.colors.panel,
  };
}

const sectionLabelStyle: React.CSSProperties = {
  fontSize: "var(--font-size-xs)",
  color: theme.colors.muted,
  textTransform: "uppercase",
  letterSpacing: "0.12em",
};

const detailTextStyle: React.CSSProperties = {
  color: theme.colors.muted,
  fontSize: "var(--font-size-sm)",
  lineHeight: 1.6,
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

function presentRecruitingText(text: string, copy: (en: string, zh: string) => string): string {
  const cleaned = text
    .trim()
    .replace(/^Promote\s+/i, copy("Review ", "复核 "))
    .replace(/^Patch\s+/i, copy("Change request: ", "变更请求："))
    .replace(/^Resume blocked task:\s*/i, copy("Blocked workflow: ", "受阻流程："))
    .replace(/^Review template candidate for\s*/i, copy("Candidate review: ", "候选人待复核："))
    .replace(/^Goal intake failed to compile an executable plan:\s*/i, copy("Plan generation failed: ", "计划生成失败："))
    .replace(/^Trial execution diverged while handling web_scene\.?\s*/i, copy("Needs a manual review before reuse. ", "本次尝试需要人工复核后再复用。"))
    .replace(/^Skill strategy managed by Recruit Agent\.?\s*/i, copy("Managed by the workspace strategy. ", "由工作台策略统一管理。"))
    .replace(/\bresolved\b/gi, copy("reviewed", "已处理"))
    .replace(/\bapproved\b/gi, copy("approved", "已批准"))
    .replace(/\bPlan:\s*[a-f0-9-]+/gi, "")
    .replace(/\bEpisode:\s*[a-f0-9-]+/gi, "")
    .replace(/\s*·\s*/g, " · ")
    .replace(/\s+/g, " ")
    .trim();
  return cleaned || copy("System update", "系统更新");
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
          title: presentRecruitingText(interaction.title, copy),
          detail: presentRecruitingText(interaction.agentPrompt, copy),
          at: interaction.updatedAt ?? interaction.surfacedAt,
          tone: toneFromInteraction(interaction),
          interaction,
          candidateId: interaction.candidateId,
        })),
    [copy, interactions],
  );

  const runtimeItems = useMemo<ApprovalInboxItem[]>(
    () =>
      approvals
        .filter((item) => !item.relatedCandidateId)
        .map<ApprovalInboxItem>((approval) => ({
          key: `approval:${approval.id}`,
          kind: "approval",
          title: presentRecruitingText(approval.title, copy),
          detail: presentRecruitingText(approval.detail, copy),
          at: approval.updatedAt ?? approval.createdAt,
          tone: toneFromApproval(approval),
          approval,
          candidateId: approval.relatedCandidateId,
        })),
    [approvals, copy],
  );

  const skillItems = useMemo<SkillInboxItem[]>(
    () =>
      skills
        .filter((skill) => skill.status !== "active" || skill.health !== "healthy")
        .map<SkillInboxItem>((skill) => ({
          key: `skill:${skill.id}`,
          kind: "skill",
          title: presentRecruitingText(skill.name, copy),
          detail: presentRecruitingText(skill.summary, copy),
          at: skill.lastCheckedAt,
          tone: toneFromSkill(skill),
          skill,
        })),
    [copy, skills],
  );

  const artifactItems = useMemo<ArtifactInboxItem[]>(
    () =>
      artifacts
        .filter((artifact) => !/(applied|archived)/i.test(artifact.status))
        .map<ArtifactInboxItem>((artifact) => ({
          key: `artifact:${artifact.id}`,
          kind: "artifact",
          title: presentRecruitingText(artifact.title, copy),
          detail: presentRecruitingText(artifact.summary ?? artifact.artifactKind, copy),
          at: artifact.updatedAt,
          tone: toneFromArtifact(artifact),
          artifact,
        })),
    [artifacts, copy],
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
  const summaryMetrics: Array<{
    label: string;
    value: number;
    note: string;
    tone: "positive" | "warning";
  }> = [
    { label: copy("Candidate actions", "候选人动作"), value: pendingInteractions, note: copy("Pending confirmations or follow-ups that need a decision.", "需要决策的待确认或待跟进事项。"), tone: pendingInteractions ? "warning" : "positive" },
    { label: copy("Review requests", "审查请求"), value: pendingApprovals, note: copy("Items ready to approve, reject, or route onward.", "可批准、拒绝或转交的事项。"), tone: pendingApprovals ? "warning" : "positive" },
    { label: copy("Skill health", "Skill 健康"), value: degradedSkills, note: copy("Skills that need a closer look before the next run.", "下一轮运行前需要再看一眼的 skill。"), tone: degradedSkills ? "warning" : "positive" },
    { label: copy("Artifacts", "产物"), value: pendingArtifacts, note: copy("Drafts and review items waiting to be finalized.", "等待定稿的草稿和审查项。"), tone: pendingArtifacts ? "warning" : "positive" },
  ];

  return (
    <div style={{ display: "grid", gap: "var(--space-5)", minWidth: 0, background: theme.colors.background, padding: "var(--space-5)", borderRadius: theme.radius.xl }}>
      <Panel
        title={copy("AI Review Center", "AI 审查中心")}
        eyebrow={copy("Recruiter-facing review", "招聘侧审查")}
        description={copy("Pending confirmations, candidate notes, and strategy artifacts stay in one review surface.", "待确认事项、候选人备注和策略产物都留在同一个审查面里。")}
      >
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: "var(--space-3)" }}>
          {summaryMetrics.map((metric) => (
            <MetricCard
              key={metric.label}
              label={metric.label}
              value={String(metric.value)}
              delta={String(metric.value)}
              tone={metric.tone}
              caption={metric.note}
            />
          ))}
        </div>
      </Panel>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "var(--layout-left-list-width) minmax(0, 1fr) var(--layout-right-panel-width)",
          gap: "var(--space-4)",
          minWidth: 0,
        }}
      >
      <Panel
        dense
        title={copy("Review queue", "审查队列")}
        eyebrow={copy("Queue and filters", "队列与筛选")}
        description={copy("Use this list to route confirmations, approvals, skills, and artifacts without leaving the review surface.", "通过这里分流确认、审批、skill 和产物，不必离开审查面。")}
      >
        <div style={{ display: "grid", gap: "var(--space-2)" }}>
          {[
            { key: "all", label: copy("All", "全部"), count: items.length },
            { key: "interactions", label: copy("Candidate actions", "候选人动作"), count: pendingInteractions },
            { key: "approvals", label: copy("Policy exceptions", "策略例外"), count: pendingApprovals },
            { key: "permissions", label: copy("System permissions", "系统权限"), count: runtimeItems.filter((item) => /(system_command|permission|command)/i.test(item.approval.targetType ?? item.approval.kind ?? "")).length },
            { key: "skills", label: copy("Skill rules", "Skill 规则"), count: degradedSkills },
            { key: "artifacts", label: copy("Review artifacts", "审查产物"), count: pendingArtifacts },
          ].map((entry) => (
            <button
              key={entry.key}
              type="button"
              onClick={() => setFilter(entry.key as InboxFilter)}
              style={{
                display: "grid",
                gridTemplateColumns: "1fr auto",
                alignItems: "center",
                gap: "var(--space-2)",
                ...listCardStyle(filter === entry.key),
              }}
            >
              <span style={{ fontWeight: 600 }}>{entry.label}</span>
              <StatusBadge tone={entry.count ? "warning" : "neutral"}>{entry.count}</StatusBadge>
            </button>
          ))}
        </div>
        <div style={{ marginTop: "var(--space-4)", display: "grid", gap: "var(--space-2)", maxHeight: "62vh", overflowY: "auto" }}>
          {items.map((item) => (
            <button
              key={item.key}
              type="button"
              onClick={() => setSelectedKey(item.key)}
              style={listCardStyle(selected?.key === item.key)}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--space-2)", alignItems: "start" }}>
                <strong style={{ fontSize: "var(--font-size-sm)", lineHeight: 1.4, fontWeight: 600 }}>{item.title}</strong>
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
              <div style={detailTextStyle}>{item.detail}</div>
              <div style={{ color: theme.colors.muted, fontSize: "var(--font-size-xs)" }}>{formatCompactDate(item.at)}</div>
            </button>
          ))}
        </div>
      </Panel>

      <Panel
        dense
        title={selected?.title ?? copy("Review detail", "审查详情")}
        eyebrow={copy("Decision surface", "决策面")}
        description={
          selected
            ? copy("Approve, reject, resolve, or route the item from the same screen.", "你可以在同一屏里批准、拒绝、处理或转交。")
            : copy("Select an item from the queue.", "从队列中选择一项。")
        }
      >
        {selected ? (
          <div style={{ display: "grid", gap: "var(--space-4)", minWidth: 0 }}>
            <div style={{ display: "grid", gap: "var(--space-3)" }}>
              <div
                style={{
                  justifySelf: "start",
                  ...messageBubbleStyle("accent"),
                }}
              >
                <div style={{ ...sectionLabelStyle, marginBottom: "var(--space-2)" }}>{copy("AI Review Center", "AI 审查中心")} · {formatCompactDate(selected.at)}</div>
                <div style={{ lineHeight: 1.65 }}>{presentRecruitingText(selected.detail, copy)}</div>
              </div>
              <div
                style={{
                  justifySelf: "end",
                  ...messageBubbleStyle("neutral"),
                }}
              >
                <div style={{ ...sectionLabelStyle, marginBottom: "var(--space-2)" }}>{copy("Operator options", "操作选项")}</div>
                <div style={{ lineHeight: 1.65 }}>
                  {selected.kind === "interaction"
                    ? copy("These options are generated for the current review context. Confirm one here, or add your own comment to steer the next attempt.", "这些选项是当前审查上下文下生成的可执行选择。你可以直接确认，也可以补充意见来纠偏下一次尝试。")
                    : selected.kind === "approval"
                    ? copy("This request can be resolved directly here. Use Evolution only when you need the underlying strategy details or history.", "这条请求可以直接在这里处理。只有需要查看底层策略细节或历史记录时才进入 Evolution。")
                    : selected.kind === "skill"
                      ? copy("The skill is visible and manageable, but structural edits belong in Evolution.", "这个 skill 的状态已经暴露出来，但结构化修改仍建议在 Evolution 中完成。")
                      : copy("This evolution artifact can be reviewed in detail inside Evolution, but you do not have to leave the current IM surface just to see why it appeared.", "这个演进产物可以在 Evolution 中细审，但你不需要为了知道它为什么出现而离开当前 IM 面。")}
                </div>
              </div>
            </div>

            {selected.kind === "interaction" ? (
              <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
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
              <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
                <button type="button" onClick={() => void onApprove(selected.approval.id)} disabled={pendingActionId === selected.approval.id} style={buttonStyle}>
                  {pendingActionId === selected.approval.id ? copy("Working...", "处理中...") : copy("Approve here", "直接批准")}
                </button>
                <button type="button" onClick={() => void onReject(selected.approval.id)} disabled={pendingActionId === selected.approval.id} style={dangerButtonStyle}>
                  {copy("Reject here", "直接拒绝")}
                </button>
                <button type="button" onClick={() => onOpenEvolution("approvals", selected.approval.id)} style={buttonStyle}>
                  {copy("Open strategy view", "打开策略视图")}
                </button>
              </div>
            ) : null}

            {selected.kind === "artifact" ? (
              <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
                <button type="button" onClick={() => onOpenEvolution("inbox", selected.artifact.id)} style={buttonStyle}>
                  {copy("Review in strategy view", "在策略视图中审查")}
                </button>
                {selected.artifact.relatedCandidateId ? (
                  <button type="button" onClick={() => onOpenCandidate(selected.artifact.relatedCandidateId!)} style={buttonStyle}>
                    {copy("Open candidate", "打开候选人")}
                  </button>
                ) : null}
              </div>
            ) : null}

            {selected.kind === "skill" ? (
              <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
                <button type="button" onClick={() => onOpenEvolution("skills", selected.skill.id)} style={buttonStyle}>
                  {copy("Manage in strategy view", "在策略视图中管理")}
                </button>
              </div>
            ) : null}

            <div style={{ borderTop: `1px solid ${theme.colors.border}`, paddingTop: "var(--space-3)", display: "grid", gap: "var(--space-2)" }}>
              <div style={sectionLabelStyle}>{copy("Context", "上下文")}</div>
              {selected.kind === "interaction" ? (
                <div style={{ display: "grid", gap: "var(--space-2)", fontSize: "var(--font-size-sm)", lineHeight: 1.6 }}>
                  <div>{copy("Lane", "执行通道")}: {translateUiToken(selected.interaction.lane, copy)}</div>
                  <div>{copy("Type", "类型")}: {translateUiToken(selected.interaction.interactionType, copy)}</div>
                  <div>{copy("Scope", "影响范围")}: {translateUiToken(selected.interaction.scope, copy)}</div>
                </div>
              ) : null}
              {selected.kind === "approval"
                ? summarizePayload(selected.approval.payload).map((line) => (
                    <div key={line} style={{ fontSize: "var(--font-size-sm)", lineHeight: 1.6 }}>
                      {line}
                    </div>
                  ))
                : null}
              {selected.kind === "skill" ? (
                <div style={{ display: "grid", gap: "var(--space-2)", fontSize: "var(--font-size-sm)" }}>
                  <div>{copy("Bound stage", "绑定阶段")}: {selected.skill.boundStage}</div>
                  <div>{copy("Version", "版本")}: {selected.skill.version}</div>
                  <div>{copy("Risk", "风险")}: {selected.skill.riskLevel ?? "medium"}</div>
                </div>
              ) : null}
              {selected.kind === "artifact" ? (
                <div style={{ display: "grid", gap: "var(--space-2)", fontSize: "var(--font-size-sm)" }}>
                  <div>{copy("Kind", "类型")}: {selected.artifact.artifactKind}</div>
                  <div>{copy("Status", "状态")}: {translateUiToken(selected.artifact.status, copy)}</div>
                  <div>{copy("Source", "来源")}: {String(selected.artifact.artifactMetadata.source ?? "unknown")}</div>
                </div>
              ) : null}
            </div>
          </div>
        ) : (
          <div style={{ color: theme.colors.muted }}>{copy("No pending review items.", "当前没有待处理的审查项。")}</div>
        )}
      </Panel>

      <Panel dense title={copy("Context rail", "上下文侧栏")} eyebrow={copy("Recent context", "最近上下文")} description={copy("Keep the right rail short: scope, risk, recent goals, and the latest trace snapshot.", "右侧只保留范围、风险、最近目标和最新 trace 快照。")}>
        <div style={{ display: "grid", gap: "var(--space-3)" }}>
          {latestGoal ? (
            <div style={{ display: "grid", gap: "var(--space-2)", fontSize: "var(--font-size-sm)" }}>
              <div style={sectionLabelStyle}>{copy("Latest goal", "最近目标")}</div>
              <strong>{presentRecruitingText(latestGoal.title, copy)}</strong>
              <div style={{ color: theme.colors.muted, lineHeight: 1.5 }}>{presentRecruitingText(latestGoal.summary ?? latestGoal.goalText, copy)}</div>
            </div>
          ) : null}
          {latestTrace ? (
            <div style={{ display: "grid", gap: "var(--space-2)", fontSize: "var(--font-size-sm)" }}>
              <div style={sectionLabelStyle}>{copy("Latest trace", "最近轨迹")}</div>
              <div>{presentRecruitingText(latestTrace.summary ?? latestTrace.status, copy)}</div>
            </div>
          ) : null}
          {latestGraph?.renderedText ? (
            <div style={{ display: "grid", gap: "var(--space-2)", fontSize: "var(--font-size-xs)" }}>
              <div style={sectionLabelStyle}>{copy("Graph projection", "执行图投影")}</div>
              <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: "var(--font-size-xs)", lineHeight: 1.5, color: theme.colors.text }}>
                {latestGraph.renderedText}
              </pre>
            </div>
          ) : null}
          {selected?.kind === "approval" ? (
            <>
              <div style={{ display: "grid", gap: "var(--space-2)", fontSize: "var(--font-size-sm)" }}>
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
            <div style={{ display: "grid", gap: "var(--space-2)", fontSize: "var(--font-size-sm)" }}>
              <div>{copy("Status", "状态")}: {translateUiToken(selected.interaction.status, copy)}</div>
              <div>{copy("Suggested actions", "建议操作数")}: {selected.interaction.suggestedOptions.length}</div>
            </div>
          ) : null}

          <div style={{ borderTop: `1px solid ${theme.colors.border}`, paddingTop: "var(--space-3)", display: "grid", gap: "var(--space-2)" }}>
            <div style={sectionLabelStyle}>{copy("Recent signals", "最近信号")}</div>
            {recentSignals.map((event) => (
              <div key={event.id} style={{ display: "grid", gap: "var(--space-1)", fontSize: "var(--font-size-sm)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--space-2)" }}>
                  <strong style={{ fontWeight: 600 }}>{translateUiToken(event.source, copy)}</strong>
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
    </div>
  );
}
