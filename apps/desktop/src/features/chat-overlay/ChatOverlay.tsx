import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FormCheckbox, FormInput, FormSelect, FormTextarea, StatusBadge } from "../../components";
import { apiClient } from "../../lib/api";
import { formatDateTime } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import type {
  AgentConversationMessage,
  AgentConversationRecord,
  AgentConversationSummary,
  AgentKind,
  AgentMemorySummary,
  AgentRunRecord,
  AgentSnapshot,
  AgentToolSummary,
  AgentWorkspaceRecord,
  ApprovalItem,
  AssistantTurnStreamEvent,
  ChatOverlayPanelKey,
  JobDescriptionSummaryRecord,
  RecruitingPolicyConfig,
  SettingsSnapshot,
  SharedSceneTemplateRecord,
  SkillRecord,
} from "../../lib/types";
import { ChatComposer } from "./ChatComposer";
import { useChatOverlay } from "./ChatOverlayContext";
import { ChatMessageStream } from "./ChatMessageStream";

interface ChatOverlayProps {
  transport: "http" | "offline";
  workspaceAgent: AgentSnapshot;
  variant?: "overlay" | "page";
}

type PanelNoticeTone = "info" | "success" | "error";
type AgentListFilter = "all" | "running" | "waiting" | "done" | "failed";

interface PanelNotice {
  panel: ChatOverlayPanelKey;
  tone: PanelNoticeTone;
  message: string;
}

interface RunStatusText {
  badgeLabel: string;
  title: string;
  detail: string;
  metrics: string[];
  tone: "positive" | "neutral" | "warning" | "critical";
}

interface ConfigDraft {
  desktopApprovalsOnly: boolean;
  autonomyEnabled: boolean;
  skillHealthAutonomyEnabled: boolean;
  skillHealthAutonomyIntervalSeconds: string;
}

interface AgentConfigDraft {
  systemPrompt: string;
  goalTemplate: string;
  scoringRubric: string;
  recruitingPolicy: RecruitingPolicyDraft;
}

interface RecruitingPolicyDraft {
  jdStandards: string;
  perJdEvaluation: string;
  onlineResumeCriteria: string;
  offlineResumeCriteria: string;
  communicationEvidence: string;
  compositeScoring: string;
  screeningRules: string;
  interviewScheduling: string;
  offerHandoff: string;
  scoreWeights: Record<keyof RecruitingPolicyConfig["scoreWeights"], string>;
  thresholds: Record<keyof RecruitingPolicyConfig["thresholds"], string>;
}

interface AutonomousGoalDraft {
  sceneTemplateKey: string;
  title: string;
  jdId: string;
  candidateCountTarget: string;
  goalText: string;
}

interface ApprovalOption {
  key: string;
  label: string;
  description: string;
}

function formatTimelineTime(value: string): string {
  const numericValue = /^\d+$/.test(value.trim()) ? Number(value.trim()) : null;
  const date = numericValue == null
    ? new Date(value)
    : new Date(numericValue > 1_000_000_000_000 ? numericValue : numericValue * 1000);
  if (Number.isNaN(date.getTime())) {
    return formatDateTime(value);
  }
  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

const panelItems: Array<{ key: ChatOverlayPanelKey; label: string }> = [
  { key: "conversation", label: "运行台" },
  { key: "config", label: "配置" },
  { key: "runs", label: "任务" },
  { key: "memory", label: "Memory" },
  { key: "skills", label: "Skill" },
  { key: "tools", label: "工具" },
];

const assistantUserId = "desktop-user";

function agentDisplayName(kind: AgentKind): string {
  return kind === "assistant" ? "Assistant Agent" : "Automation Agent";
}

function normalizeAgentTitle(kind: AgentKind, title: string | null | undefined): string {
  const trimmed = title?.trim();
  if (kind === "autonomous" && (!trimmed || /^autonomous agent$/i.test(trimmed) || /^autonomous$/i.test(trimmed))) {
    return agentDisplayName(kind);
  }
  return trimmed || agentDisplayName(kind);
}

function agentModeLabel(kind: AgentKind): string {
  return kind === "assistant" ? "对话触发" : "事件/调度触发";
}

function agentModeSummary(kind: AgentKind): string {
  return kind === "assistant"
    ? "由用户消息驱动，适合解释、检索、局部操作和人工协作。"
    : "由外部事件、定时任务或手工创建的自动化任务驱动，适合后台持续推进招聘流程。";
}

function workspaceTemplate(): Record<AgentKind, AgentWorkspaceRecord | null> {
  return {
    assistant: null,
    autonomous: null,
  };
}

function conversationTemplate(): Record<AgentKind, string | undefined> {
  return {
    assistant: undefined,
    autonomous: undefined,
  };
}

function localConversationTemplate(): Record<AgentKind, AgentConversationSummary[]> {
  return {
    assistant: [],
    autonomous: [],
  };
}

function conversationKey(agentKind: AgentKind, conversationId: string): string {
  return `${agentKind}:${conversationId}`;
}

function conversationStatusSortRank(status: AgentConversationSummary["status"]): number {
  switch (status) {
    case "waiting_human":
      return 6;
    case "blocked":
      return 5;
    case "active":
      return 4;
    case "running":
    case "queued":
      return 3;
    case "draft":
      return 2;
    case "failed":
      return 1;
    case "idle":
      return 0;
    case "completed":
      return -1;
    default:
      return -2;
  }
}

function parseConversationSortTime(value: string | null | undefined): number {
  if (!value) {
    return 0;
  }

  const raw = String(value).trim();
  if (!raw) {
    return 0;
  }

  if (/^\d+$/.test(raw)) {
    const numeric = Number(raw);
    if (Number.isFinite(numeric)) {
      return numeric > 1_000_000_000_000 ? numeric : numeric * 1000;
    }
  }

  const direct = new Date(raw).getTime();
  if (Number.isFinite(direct)) {
    return direct;
  }

  const normalized = raw
    .replace(" ", "T")
    .replace(/(\.\d{3})\d+/, "$1");
  const fallback = new Date(normalized).getTime();
  return Number.isFinite(fallback) ? fallback : 0;
}

function formatSortTimestamp(value: number, fallback: string): string {
  if (value <= 0) {
    return fallback;
  }
  return new Date(value).toISOString();
}

function latestMessageSortTime(messages: AgentConversationMessage[]): number {
  return messages.reduce((latest, message) => Math.max(latest, parseConversationSortTime(message.createdAt)), 0);
}

function resolveConversationUpdatedAt(
  existing: AgentConversationSummary | undefined,
  incoming: AgentConversationSummary,
  messages: AgentConversationMessage[],
): string {
  const latestKnownActivity = Math.max(
    parseConversationSortTime(existing?.updatedAt),
    latestMessageSortTime(messages),
  );
  const incomingTime = parseConversationSortTime(incoming.updatedAt);
  const metadataChanged = existing == null
    || existing.status !== incoming.status
    || (existing.preview ?? null) !== (incoming.preview ?? null)
    || existing.title !== incoming.title;
  const resolvedTime = metadataChanged
    ? Math.max(latestKnownActivity, incomingTime)
    : latestKnownActivity || incomingTime;
  return formatSortTimestamp(resolvedTime, incoming.updatedAt);
}

function dedupeConversations(conversations: AgentConversationSummary[]): AgentConversationSummary[] {
  const map = new Map<string, AgentConversationSummary>();
  conversations.forEach((item) => {
    const existing = map.get(item.id);
    if (!existing || parseConversationSortTime(item.updatedAt) >= parseConversationSortTime(existing.updatedAt)) {
      map.set(item.id, item);
    }
  });
  return [...map.values()].sort((left, right) => {
    const updatedAtDiff = parseConversationSortTime(right.updatedAt) - parseConversationSortTime(left.updatedAt);
    if (updatedAtDiff !== 0) {
      return updatedAtDiff;
    }

    const statusDiff = conversationStatusSortRank(right.status) - conversationStatusSortRank(left.status);
    if (statusDiff !== 0) {
      return statusDiff;
    }

    const titleDiff = left.title.localeCompare(right.title, "zh-CN");
    if (titleDiff !== 0) {
      return titleDiff;
    }

    return left.id.localeCompare(right.id, "zh-CN");
  });
}

function mergeMessages(existing: AgentConversationMessage[], incoming: AgentConversationMessage[]): AgentConversationMessage[] {
  const map = new Map<string, AgentConversationMessage>();
  [...existing, ...incoming].forEach((message) => {
    map.set(message.id, message);
  });
  return [...map.values()].sort(
    (left, right) => new Date(left.createdAt).getTime() - new Date(right.createdAt).getTime(),
  );
}

function mergeConversationSummaries(
  existing: AgentConversationSummary[],
  incoming: AgentConversationSummary[],
  options?: { prependNew?: boolean },
): AgentConversationSummary[] {
  const next = [...existing];
  incoming.forEach((conversation) => {
    const existingIndex = next.findIndex((item) => item.id === conversation.id);
    if (existingIndex >= 0) {
      next[existingIndex] = conversation;
      return;
    }
    if (options?.prependNew) {
      next.unshift(conversation);
      return;
    }
    next.push(conversation);
  });
  return dedupeConversations(next);
}

function trimTitle(value: string): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (normalized.length <= 28) {
    return normalized || "New conversation";
  }
  return `${normalized.slice(0, 28)}…`;
}

function configDraftFromSettings(settings: SettingsSnapshot): ConfigDraft {
  return {
    desktopApprovalsOnly: settings.desktopApprovalsOnly,
    autonomyEnabled: settings.autonomyEnabled,
    skillHealthAutonomyEnabled: settings.skillHealthAutonomyEnabled,
    skillHealthAutonomyIntervalSeconds: String(settings.skillHealthAutonomyIntervalSeconds ?? 300),
  };
}

function recruitingPolicyDraftFromConfig(policy?: RecruitingPolicyConfig): RecruitingPolicyDraft {
  return {
    jdStandards: policy?.jdStandards ?? "",
    perJdEvaluation: policy?.perJdEvaluation ?? "",
    onlineResumeCriteria: policy?.onlineResumeCriteria ?? "",
    offlineResumeCriteria: policy?.offlineResumeCriteria ?? "",
    communicationEvidence: policy?.communicationEvidence ?? "",
    compositeScoring: policy?.compositeScoring ?? "",
    screeningRules: policy?.screeningRules ?? "",
    interviewScheduling: policy?.interviewScheduling ?? "",
    offerHandoff: policy?.offerHandoff ?? "",
    scoreWeights: {
      jdMatch: String(policy?.scoreWeights.jdMatch ?? 30),
      onlineResume: String(policy?.scoreWeights.onlineResume ?? 20),
      offlineResume: String(policy?.scoreWeights.offlineResume ?? 25),
      communication: String(policy?.scoreWeights.communication ?? 15),
      stability: String(policy?.scoreWeights.stability ?? 10),
    },
    thresholds: {
      onlinePass: String(policy?.thresholds.onlinePass ?? 70),
      offlinePass: String(policy?.thresholds.offlinePass ?? 72),
      compositePass: String(policy?.thresholds.compositePass ?? 75),
      manualReviewMin: String(policy?.thresholds.manualReviewMin ?? 60),
      interviewRecommend: String(policy?.thresholds.interviewRecommend ?? 80),
    },
  };
}

function numberConfigValue(value: string, fallback: number): number {
  const numeric = Number.parseFloat(value);
  return Number.isFinite(numeric) ? numeric : fallback;
}

function recruitingPolicyPayloadFromDraft(draft: RecruitingPolicyDraft): RecruitingPolicyConfig {
  return {
    jdStandards: draft.jdStandards,
    perJdEvaluation: draft.perJdEvaluation,
    onlineResumeCriteria: draft.onlineResumeCriteria,
    offlineResumeCriteria: draft.offlineResumeCriteria,
    communicationEvidence: draft.communicationEvidence,
    compositeScoring: draft.compositeScoring,
    screeningRules: draft.screeningRules,
    interviewScheduling: draft.interviewScheduling,
    offerHandoff: draft.offerHandoff,
    scoreWeights: {
      jdMatch: numberConfigValue(draft.scoreWeights.jdMatch, 30),
      onlineResume: numberConfigValue(draft.scoreWeights.onlineResume, 20),
      offlineResume: numberConfigValue(draft.scoreWeights.offlineResume, 25),
      communication: numberConfigValue(draft.scoreWeights.communication, 15),
      stability: numberConfigValue(draft.scoreWeights.stability, 10),
    },
    thresholds: {
      onlinePass: numberConfigValue(draft.thresholds.onlinePass, 70),
      offlinePass: numberConfigValue(draft.thresholds.offlinePass, 72),
      compositePass: numberConfigValue(draft.thresholds.compositePass, 75),
      manualReviewMin: numberConfigValue(draft.thresholds.manualReviewMin, 60),
      interviewRecommend: numberConfigValue(draft.thresholds.interviewRecommend, 80),
    },
  };
}

function agentConfigDraftTemplate(): Record<AgentKind, AgentConfigDraft> {
  return {
    assistant: {
      systemPrompt: "",
      goalTemplate: "",
      scoringRubric: "",
      recruitingPolicy: recruitingPolicyDraftFromConfig(),
    },
    autonomous: {
      systemPrompt: "",
      goalTemplate: "",
      scoringRubric: "",
      recruitingPolicy: recruitingPolicyDraftFromConfig(),
    },
  };
}

function agentConfigDraftFromWorkspace(workspace: AgentWorkspaceRecord | null): AgentConfigDraft {
  return {
    systemPrompt: workspace?.config.systemPrompt ?? "",
    goalTemplate: workspace?.config.goalTemplate ?? "",
    scoringRubric: workspace?.config.scoringRubric ?? "",
    recruitingPolicy: recruitingPolicyDraftFromConfig(workspace?.config.recruitingPolicy),
  };
}

function autonomousGoalDraftTemplate(defaultGoalText = ""): AutonomousGoalDraft {
  return {
    sceneTemplateKey: "",
    title: "",
    jdId: "",
    candidateCountTarget: "3",
    goalText: defaultGoalText,
  };
}

function cleanApprovalTitle(approval: ApprovalItem): string {
  return approval.title.replace(/^(Patch|Review|Promote)\s+/i, "").trim() || approval.title;
}

function describeApprovalIntent(approval: ApprovalItem, copy: ReturnType<typeof useI18n>["copy"]): string {
  const summary = typeof approval.payload?.summary === "string" ? approval.payload.summary : "";
  if (approval.targetType === "playbook_patch") {
    return copy(
      "Runtime found a repeatable divergence and wants to add a supervised checkpoint before continuing.",
      "运行中发现可复现分歧，需要先加入监督检查点后再继续。",
    );
  }
  if (approval.targetType === "skill_draft") {
    return copy(
      "A reusable skill draft is ready and needs review before promotion.",
      "已生成可复用技能草稿，需要确认后再提升为可用技能。",
    );
  }
  if (approval.targetType === "template_candidate") {
    return copy(
      "A reusable execution template candidate is ready and needs review.",
      "已生成可复用执行模板候选，需要确认是否保留。",
    );
  }
  if (/trial execution diverged/i.test(summary)) {
    return copy(
      "The trial run diverged from the expected scene and is waiting for your decision.",
      "试运行与预期场景不一致，正在等待你的下一步决策。",
    );
  }
  return approval.detail || summary || copy("This action needs human confirmation before the agent continues.", "该动作需要人工确认后 Agent 才会继续。");
}

function approvalOptionsFor(approval: ApprovalItem, copy: ReturnType<typeof useI18n>["copy"]): ApprovalOption[] {
  if (approval.targetType === "skill_draft") {
    return [
      {
        key: "promote",
        label: copy("Promote skill", "提升为技能"),
        description: copy("Approve this draft and make it available for future runs.", "确认草稿，让后续运行可以复用。"),
      },
      {
        key: "review",
        label: copy("Review first", "先复核内容"),
        description: copy("Open the approval panel and inspect details before deciding.", "先进入确认面板查看完整内容。"),
      },
      {
        key: "manual",
        label: copy("Keep manual", "保留人工处理"),
        description: copy("Do not promote this draft automatically.", "暂不自动提升该草稿。"),
      },
    ];
  }
  if (approval.targetType === "template_candidate") {
    return [
      {
        key: "keep",
        label: copy("Keep template", "保留模板"),
        description: copy("Accept this candidate as reusable execution knowledge.", "接受为可复用执行经验。"),
      },
      {
        key: "review",
        label: copy("Review first", "先复核方案"),
        description: copy("Inspect template scope and version impact before continuing.", "先查看模板范围和版本影响。"),
      },
      {
        key: "discard",
        label: copy("Do not keep", "不保留"),
        description: copy("Reject this candidate and keep the current runtime unchanged.", "拒绝候选，不改变当前运行配置。"),
      },
    ];
  }
  return [
    {
      key: "continue",
      label: copy("Continue", "继续执行"),
      description: copy("Apply the current supervised plan and continue this run.", "按当前监督方案继续，并推进当前运行。"),
    },
    {
      key: "preview",
      label: copy("Preview impact", "先预览影响"),
      description: copy("Review the plan impact before allowing the agent to continue.", "先展示影响范围，再决定是否继续。"),
    },
    {
      key: "manual",
      label: copy("Hand off", "转人工处理"),
      description: copy("Pause automation and hand this step to a human operator.", "暂停自动化流程，把这一步交给人工。"),
    },
    {
      key: "custom",
      label: copy("Custom rule", "自定义策略"),
      description: copy("Use the note below as an additional constraint.", "以下方补充说明作为额外约束。"),
    },
  ];
}

function buildApprovalDecisionReason(
  approval: ApprovalItem,
  options: ApprovalOption[],
  selectedKey: string | undefined,
  note: string | undefined,
): string | undefined {
  const selected = options.find((option) => option.key === selectedKey);
  const lines = [
    selected ? `Decision: ${selected.label} - ${selected.description}` : null,
    note?.trim() ? `Note: ${note.trim()}` : null,
  ].filter((line): line is string => Boolean(line));
  if (!lines.length) {
    return undefined;
  }
  return `${cleanApprovalTitle(approval)}\n${lines.join("\n")}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringField(record: Record<string, unknown> | undefined, ...keys: string[]): string | null {
  if (!record) {
    return null;
  }
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
    if (typeof value === "number" && Number.isFinite(value)) {
      return String(value);
    }
  }
  return null;
}

function approvalAssociationValues(approval: ApprovalItem): Set<string> {
  const payload = isRecord(approval.payload) ? approval.payload : {};
  return new Set(
    [
      approval.targetId,
      approval.runPk,
      approval.turnPk,
      stringField(payload, "run_id", "runId"),
      stringField(payload, "turn_id", "turnId"),
      stringField(payload, "run_pk", "runPk"),
      stringField(payload, "turn_pk", "turnPk"),
      stringField(payload, "approval_id", "approvalId"),
      stringField(payload, "call_id", "callId"),
    ].filter((value): value is string => Boolean(value)),
  );
}

function messageAssociationValues(message: AgentConversationMessage): Set<string> {
  const metadata = isRecord(message.metadata) ? message.metadata : {};
  return new Set(
    [
      message.id,
      stringField(metadata, "run_id", "runId"),
      stringField(metadata, "turn_id", "turnId"),
      stringField(metadata, "run_pk", "runPk"),
      stringField(metadata, "turn_pk", "turnPk"),
      stringField(metadata, "approval_id", "approvalId"),
      stringField(metadata, "call_id", "callId"),
    ].filter((value): value is string => Boolean(value)),
  );
}

function isApprovalAnchorMessage(message: AgentConversationMessage): boolean {
  const metadata = isRecord(message.metadata) ? message.metadata : {};
  const tokens = [
    message.kind,
    message.status,
    stringField(metadata, "eventKind", "event_kind"),
    stringField(metadata, "itemType", "item_type"),
    stringField(metadata, "traceKind", "trace_kind"),
  ]
    .filter((value): value is string => Boolean(value))
    .map((value) => value.toLowerCase());
  return tokens.some((value) =>
    value.includes("approval") ||
    value.includes("confirm") ||
    value.includes("permission") ||
    value.includes("waiting_human") ||
    value.includes("tool_blocked") ||
    value.includes("blocked"),
  );
}

function approvalMatchesTimelineMessage(approval: ApprovalItem, message: AgentConversationMessage): boolean {
  if (!isApprovalAnchorMessage(message)) {
    return false;
  }
  const approvalValues = approvalAssociationValues(approval);
  if (!approvalValues.size) {
    return false;
  }
  for (const value of messageAssociationValues(message)) {
    if (approvalValues.has(value)) {
      return true;
    }
  }
  return false;
}

function approvalStatusTone(status: ApprovalItem["status"]): "positive" | "neutral" | "warning" | "critical" {
  if (status === "approved") {
    return "positive";
  }
  if (status === "rejected") {
    return "critical";
  }
  return "warning";
}

function approvalStatusLabel(status: ApprovalItem["status"], copy: ReturnType<typeof useI18n>["copy"]): string {
  if (status === "approved") {
    return copy("Approved", "已确认");
  }
  if (status === "rejected") {
    return copy("Rejected", "已拒绝");
  }
  return copy("Waiting", "待确认");
}

function formatStreamMessage(event: AssistantTurnStreamEvent): string | null {
  switch (event.event) {
    case "tool_call":
      return `调用工具 ${String(event.data.name ?? "unknown")}`;
    case "tool_result":
      return `工具 ${String(event.data.tool_name ?? "unknown")} 已返回结果`;
    case "tool_blocked":
      return `工具 ${String(event.data.tool_name ?? "unknown")} 被阻止：${String(event.data.reason ?? "需要人工处理")}`;
    case "turn.waiting_human":
      return "Assistant 正在等待人工审批后继续。";
    case "turn.cancelled":
      return `Assistant 已取消：${String(event.data.reason ?? "cancelled")}`;
    case "turn.failed":
      return `Assistant 运行失败：${String(event.data.error ?? event.data.reason ?? "unknown error")}`;
    default:
      return null;
  }
}

function extractAssistantText(event: AssistantTurnStreamEvent): string {
  if (typeof event.data.content === "string") {
    return event.data.content;
  }
  if (typeof event.data.delta === "string") {
    return event.data.delta;
  }
  if (typeof event.data.message === "string") {
    return event.data.message;
  }
  return "";
}

function streamEventTimelineMetadata(event: AssistantTurnStreamEvent): Record<string, unknown> {
  const eventKind =
    event.event === "tool_call"
      ? "tool_call"
      : event.event === "tool_result"
        ? "execution_result"
        : event.event === "tool_blocked" || event.event === "turn.waiting_human"
          ? "confirmation"
          : event.event === "llm_delta" || event.event === "llm_final"
            ? "thinking"
            : "execution_result";

  return {
    ...event.data,
    eventKind,
    itemType: event.event,
  };
}

function mergeStreamText(previous: string, nextChunk: string): string {
  if (!previous) {
    return nextChunk;
  }
  if (!nextChunk) {
    return previous;
  }
  if (nextChunk.startsWith(previous)) {
    return nextChunk;
  }
  if (previous.endsWith(nextChunk)) {
    return previous;
  }
  return `${previous}${nextChunk}`;
}

function toneForHealth(health: string): "positive" | "warning" | "critical" {
  if (health === "healthy") {
    return "positive";
  }
  if (health === "warning") {
    return "warning";
  }
  return "critical";
}

function toneForRunStatus(status: string): "positive" | "neutral" | "warning" | "critical" {
  const normalized = status.trim().toLowerCase();
  if (normalized === "completed" || normalized === "succeeded") {
    return "positive";
  }
  if (normalized === "failed" || normalized === "cancelled" || normalized === "timed_out") {
    return "critical";
  }
  if (
    normalized === "waiting_human"
    || normalized === "blocked"
    || normalized === "blocked_human"
    || normalized === "blocked_environment"
  ) {
    return "warning";
  }
  return "neutral";
}

function isTerminalRunStatus(status: string): boolean {
  const normalized = status.trim().toLowerCase();
  return normalized === "completed"
    || normalized === "failed"
    || normalized === "cancelled"
    || normalized === "interrupted"
    || normalized === "succeeded"
    || normalized === "timed_out"
    || normalized === "rejected"
    || normalized === "idle";
}

function isOpenRunStatus(status: string): boolean {
  return !isTerminalRunStatus(status);
}

function isActivelyExecutingRunStatus(status: string): boolean {
  const normalized = status.trim().toLowerCase();
  return normalized === "queued" || normalized === "running" || normalized === "active";
}

function isResumableRunStatus(status: string): boolean {
  const normalized = status.trim().toLowerCase();
  return normalized === "waiting_human"
    || normalized === "blocked"
    || normalized === "blocked_human"
    || normalized === "blocked_environment"
    || normalized === "failed"
    || normalized === "cancelled"
    || normalized === "timed_out";
}

function noticeStyle(tone: PanelNoticeTone): React.CSSProperties {
  if (tone === "success") {
    return {
      borderRadius: 12,
      border: "1px solid color-mix(in srgb, var(--success) 32%, white)",
      background: "color-mix(in srgb, var(--success) 10%, white)",
      color: "var(--success)",
      padding: "var(--space-3) var(--space-4)",
      fontSize: "var(--font-size-sm)",
      lineHeight: "var(--line-height-base)",
    };
  }
  if (tone === "info") {
    return {
      borderRadius: 12,
      border: "1px solid color-mix(in srgb, var(--info) 28%, white)",
      background: "color-mix(in srgb, var(--info) 8%, white)",
      color: "var(--info)",
      padding: "var(--space-3) var(--space-4)",
      fontSize: "var(--font-size-sm)",
      lineHeight: "var(--line-height-base)",
    };
  }
  return {
    borderRadius: 12,
    border: "1px solid color-mix(in srgb, var(--danger) 32%, white)",
    background: "var(--danger-soft)",
    color: "var(--danger)",
    padding: "var(--space-3) var(--space-4)",
    fontSize: "var(--font-size-sm)",
    lineHeight: "var(--line-height-base)",
  };
}

function panelEmptyStyle(): React.CSSProperties {
  return {
    display: "grid",
    gap: "var(--space-2)",
    justifyItems: "center",
    alignContent: "center",
    minHeight: "100%",
    padding: "var(--space-6)",
    textAlign: "center",
    color: "var(--chat-text-secondary)",
    fontSize: "var(--font-size-sm)",
    lineHeight: "var(--line-height-base)",
  };
}

export function ChatOverlay({ transport, workspaceAgent, variant = "overlay" }: ChatOverlayProps): JSX.Element {
  const { copy } = useI18n();
  const {
    activeAgent,
    activePanel,
    close,
    focusAgent,
    isOpen,
    overlayRect,
    setActivePanel,
    setOverlayRect,
  } = useChatOverlay();
  const pageMode = variant === "page";
  const visible = pageMode || isOpen;
  const workspacePollMs = pageMode ? 10000 : 1500;
  const conversationPollMs = pageMode ? 5000 : 1500;

  const [workspaces, setWorkspaces] = useState<Record<AgentKind, AgentWorkspaceRecord | null>>(workspaceTemplate);
  const [localConversations, setLocalConversations] = useState<Record<AgentKind, AgentConversationSummary[]>>(
    localConversationTemplate,
  );
  const [selectedConversation, setSelectedConversation] = useState<Record<AgentKind, string | undefined>>(
    conversationTemplate,
  );
  const [conversationCache, setConversationCache] = useState<Record<string, AgentConversationRecord>>({});
  const [composerValue, setComposerValue] = useState("");
  const [draftComposerValues, setDraftComposerValues] = useState<Record<string, string>>({});
  const [loadingWorkspace, setLoadingWorkspace] = useState(false);
  const [loadingConversation, setLoadingConversation] = useState(false);
  const [sending, setSending] = useState(false);
  const [railCollapsed, setRailCollapsed] = useState(false);
  const [collapsedGroups, setCollapsedGroups] = useState<Record<AgentKind, boolean>>({
    assistant: false,
    autonomous: false,
  });
  const [errorMessage, setErrorMessage] = useState<string>();
  const [settingsSnapshot, setSettingsSnapshot] = useState<SettingsSnapshot | null>(null);
  const [configDraft, setConfigDraft] = useState<ConfigDraft | null>(null);
  const [agentConfigDrafts, setAgentConfigDrafts] = useState<Record<AgentKind, AgentConfigDraft>>(agentConfigDraftTemplate);
  const [jobDescriptionOptions, setJobDescriptionOptions] = useState<JobDescriptionSummaryRecord[]>([]);
  const [sceneTemplates, setSceneTemplates] = useState<SharedSceneTemplateRecord[]>([]);
  const [autonomousGoalDraft, setAutonomousGoalDraft] = useState<AutonomousGoalDraft>(autonomousGoalDraftTemplate);
  const [loadingSettings, setLoadingSettings] = useState(false);
  const [savingConfig, setSavingConfig] = useState(false);
  const [panelNotice, setPanelNotice] = useState<PanelNotice | null>(null);
  const [approvalNotes, setApprovalNotes] = useState<Record<string, string>>({});
  const [approvalSelections, setApprovalSelections] = useState<Record<string, string>>({});
  const [approvalActionId, setApprovalActionId] = useState<string | null>(null);
  const [runActionBusyId, setRunActionBusyId] = useState<string | null>(null);
  const [toolActionBusyKey, setToolActionBusyKey] = useState<string | null>(null);
  const [agentListFilter, setAgentListFilter] = useState<AgentListFilter>("all");
  const [agentSearchQuery, setAgentSearchQuery] = useState("");
  const headerDragRef = useRef<{
    pointerX: number;
    pointerY: number;
    x: number;
    y: number;
  } | null>(null);
  const resizeRef = useRef<{
    pointerX: number;
    pointerY: number;
    width: number;
    height: number;
  } | null>(null);
  const streamShellRef = useRef<HTMLDivElement | null>(null);
  const streamShouldFollowRef = useRef(true);
  const streamLastMessageSignatureRef = useRef<string>("");
  const assistantAbortRef = useRef<AbortController | null>(null);
  const assistantStreamContentRef = useRef<Record<string, string>>({});
  const conversationLookupRef = useRef<Map<string, AgentConversationSummary>>(new Map());

  const loadWorkspaces = useCallback(async (markLoading = true) => {
    if (markLoading) {
      setLoadingWorkspace(true);
    }
    try {
      const [assistant, autonomous] = await Promise.all([
        apiClient.getAgentWorkspace("assistant"),
        apiClient.getAgentWorkspace("autonomous"),
      ]);
      setWorkspaces({
        assistant,
        autonomous,
      });
      setErrorMessage(undefined);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : copy("Failed to load agent overlay.", "加载 Agent Overlay 失败。"));
    } finally {
      if (markLoading) {
        setLoadingWorkspace(false);
      }
    }
  }, [copy]);

  const loadSettings = useCallback(async () => {
    setLoadingSettings(true);
    try {
      const settings = await apiClient.getSettings();
      setSettingsSnapshot(settings);
      setConfigDraft(configDraftFromSettings(settings));
    } catch (error) {
      setPanelNotice({
        panel: "config",
        tone: "error",
        message: error instanceof Error ? error.message : copy("Failed to load settings.", "加载设置失败。"),
      });
    } finally {
      setLoadingSettings(false);
    }
  }, [copy]);

  const loadJobDescriptions = useCallback(async () => {
    try {
      const jobs = await apiClient.listJobDescriptions();
      setJobDescriptionOptions(jobs);
    } catch (error) {
      setPanelNotice({
        panel: "runs",
        tone: "error",
        message: error instanceof Error ? error.message : copy("Failed to load job descriptions.", "加载 JD 列表失败。"),
      });
    }
  }, [copy]);

  const loadSceneTemplates = useCallback(async () => {
    try {
      const templates = await apiClient.listSharedSceneTemplates();
      setSceneTemplates(templates);
    } catch (error) {
      setPanelNotice({
        panel: "tools",
        tone: "error",
        message: error instanceof Error ? error.message : copy("Failed to load scene templates.", "加载共享场景模板失败。"),
      });
    }
  }, [copy]);

  useEffect(() => {
    if (!visible) {
      return;
    }
    void loadWorkspaces();
    void loadSettings();
    void loadJobDescriptions();
    void loadSceneTemplates();
  }, [visible, loadJobDescriptions, loadSceneTemplates, loadSettings, loadWorkspaces]);

  useEffect(() => {
    if (!visible) {
      return;
    }

    const intervalId = window.setInterval(() => {
      void loadWorkspaces(false);
    }, workspacePollMs);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [visible, loadWorkspaces, workspacePollMs]);

  useEffect(() => {
    setAgentConfigDrafts({
      assistant: agentConfigDraftFromWorkspace(workspaces.assistant),
      autonomous: agentConfigDraftFromWorkspace(workspaces.autonomous),
    });
  }, [workspaces.assistant, workspaces.autonomous]);

  useEffect(() => {
    setAutonomousGoalDraft((current) => {
      const defaultGoalText = workspaces.autonomous?.config.goalTemplate?.trim() ?? "";
      const hasUserInput =
        current.sceneTemplateKey.trim().length > 0
        || current.title.trim().length > 0
        || current.jdId.trim().length > 0
        || current.goalText.trim().length > 0
        || current.candidateCountTarget.trim() !== "3";
      if (hasUserInput) {
        return current;
      }
      return autonomousGoalDraftTemplate(defaultGoalText);
    });
  }, [workspaces.autonomous?.config.goalTemplate]);

  useEffect(() => {
    if (visible) {
      return;
    }
    assistantAbortRef.current?.abort();
    assistantAbortRef.current = null;
    assistantStreamContentRef.current = {};
    setSending(false);
  }, [visible]);

  const conversationsByAgent = useMemo<Record<AgentKind, AgentConversationSummary[]>>(
    () => ({
      assistant: dedupeConversations([
        ...(localConversations.assistant ?? []),
        ...(workspaces.assistant?.conversations ?? []),
      ]),
      autonomous: dedupeConversations([
        ...(localConversations.autonomous ?? []),
        ...(workspaces.autonomous?.conversations ?? []),
      ]),
    }),
    [localConversations, workspaces],
  );

  const conversationLookup = useMemo(() => {
    const lookup = new Map<string, AgentConversationSummary>();
    (["assistant", "autonomous"] as AgentKind[]).forEach((kind) => {
      conversationsByAgent[kind].forEach((conversation) => {
        lookup.set(conversationKey(kind, conversation.id), conversation);
      });
    });
    return lookup;
  }, [conversationsByAgent]);

  useEffect(() => {
    conversationLookupRef.current = conversationLookup;
  }, [conversationLookup]);

  useEffect(() => {
    if (!visible) {
      return;
    }
    setSelectedConversation((current) => {
      const next = { ...current };
      (["assistant", "autonomous"] as AgentKind[]).forEach((kind) => {
        if (!next[kind]) {
          next[kind] = conversationsByAgent[kind][0]?.id;
        }
      });
      return next;
    });
  }, [conversationsByAgent, visible]);

  const activeConversationId = selectedConversation[activeAgent] ?? conversationsByAgent[activeAgent][0]?.id;
  const activeConversationSummary =
    activeConversationId != null ? conversationLookup.get(conversationKey(activeAgent, activeConversationId)) : undefined;
  const activeConversationCacheKey =
    activeConversationId != null ? conversationKey(activeAgent, activeConversationId) : undefined;
  const activeDraftComposerKey =
    activeConversationId != null
    && activeConversationCacheKey != null
    && activeConversationId.startsWith("draft-")
      ? activeConversationCacheKey
      : null;
  const activeConversation =
    activeConversationCacheKey != null ? conversationCache[activeConversationCacheKey] : undefined;
  const activeWorkspace = workspaces[activeAgent];
  const autonomousWorkspace = workspaces.autonomous;
  const sceneTemplateLookup = useMemo(
    () => new Map(sceneTemplates.map((template) => [template.key, template])),
    [sceneTemplates],
  );
  const autonomousDefaultGoalTemplate = useMemo(
    () => autonomousWorkspace?.config.goalTemplate?.trim() ?? "",
    [autonomousWorkspace?.config.goalTemplate],
  );
  const autonomousActiveRun = useMemo(
    () => autonomousWorkspace?.runs.find((run) => isOpenRunStatus(run.status)) ?? null,
    [autonomousWorkspace],
  );
  const autonomousStartBlocked = activeAgent === "autonomous" && autonomousActiveRun != null;
  const autonomousDraftEditable =
    activeAgent === "autonomous" && autonomousStartBlocked && activeDraftComposerKey != null;
  const composerInputValue = activeDraftComposerKey != null ? draftComposerValues[activeDraftComposerKey] ?? "" : composerValue;

  useEffect(() => {
    setCollapsedGroups((current) => ({
      ...current,
      [activeAgent]: false,
    }));
  }, [activeAgent]);

  const upsertConversationSummary = useCallback(
    (agentKind: AgentKind, patch: Partial<AgentConversationSummary> & { id: string }) => {
      const existing = conversationLookup.get(conversationKey(agentKind, patch.id));
      const nextConversation: AgentConversationSummary = {
        id: patch.id,
        agentKind,
        title: patch.title ?? existing?.title ?? copy("New conversation", "新会话"),
        preview: patch.preview ?? existing?.preview ?? null,
        status: patch.status ?? existing?.status ?? "active",
        unreadCount: patch.unreadCount ?? existing?.unreadCount ?? 0,
        updatedAt: patch.updatedAt ?? existing?.updatedAt ?? new Date().toISOString(),
        refId: patch.refId ?? existing?.refId ?? null,
      };
      setLocalConversations((current) => ({
        ...current,
        [agentKind]: mergeConversationSummaries(current[agentKind] ?? [], [nextConversation]),
      }));
    },
    [conversationLookup, copy],
  );

  const appendMessage = useCallback(
    (agentKind: AgentKind, conversationId: string, message: AgentConversationMessage) => {
      const cacheKey = conversationKey(agentKind, conversationId);
      const summary = conversationLookup.get(cacheKey) ?? {
        id: conversationId,
        agentKind,
        title: trimTitle(message.title ?? message.content),
        preview: message.content,
        status: "active" as const,
        unreadCount: 0,
        updatedAt: message.createdAt,
        refId: null,
      };
      setConversationCache((current) => ({
        ...current,
        [cacheKey]: {
          conversation: summary,
          messages: mergeMessages(current[cacheKey]?.messages ?? [], [message]),
        },
      }));
    },
    [conversationLookup],
  );

  const syncConversationPreview = useCallback(
    (agentKind: AgentKind, conversationId: string, message: string, title?: string) => {
      const existing = conversationLookup.get(conversationKey(agentKind, conversationId));
      upsertConversationSummary(agentKind, {
        id: conversationId,
        title: existing == null || existing.status === "draft" ? title ?? undefined : undefined,
        preview: message,
        updatedAt: new Date().toISOString(),
      });
    },
    [conversationLookup, upsertConversationSummary],
  );

  const removeDraftConversation = useCallback((agentKind: AgentKind, conversationId: string) => {
    setLocalConversations((current) => ({
      ...current,
      [agentKind]: (current[agentKind] ?? []).filter((conversation) => conversation.id !== conversationId),
    }));
    setDraftComposerValues((current) => {
      const next = { ...current };
      delete next[conversationKey(agentKind, conversationId)];
      return next;
    });
    setConversationCache((current) => {
      const next = { ...current };
      delete next[conversationKey(agentKind, conversationId)];
      return next;
    });
  }, []);

  const createDraftConversation = useCallback(
    (kind: AgentKind): string => {
      const id = `draft-${kind}-${Date.now()}`;
      const title = kind === "assistant"
        ? copy("New assistant chat", "新 Assistant 会话")
        : copy("New automation task", "新自动化任务");
      upsertConversationSummary(kind, {
        id,
        title,
        preview: null,
        status: "draft",
        updatedAt: new Date().toISOString(),
        refId: null,
      });
      setSelectedConversation((current) => ({
        ...current,
        [kind]: id,
      }));
      focusAgent(kind, "conversation");
      return id;
    },
    [copy, focusAgent, upsertConversationSummary],
  );

  const handleComposerChange = useCallback(
    (nextValue: string) => {
      if (activeDraftComposerKey != null && activeConversationId != null) {
        setDraftComposerValues((current) => ({
          ...current,
          [activeDraftComposerKey]: nextValue,
        }));
        upsertConversationSummary(activeAgent, {
          id: activeConversationId,
          title: nextValue.trim()
            ? trimTitle(nextValue)
            : activeAgent === "assistant"
              ? copy("New assistant chat", "新 Assistant 会话")
              : copy("New automation task", "新自动化任务"),
          preview: nextValue.trim() ? nextValue.trim() : null,
          status: "draft",
        });
        return;
      }
      setComposerValue(nextValue);
    },
    [activeAgent, activeConversationId, activeDraftComposerKey, copy, upsertConversationSummary],
  );

  const toggleConversationGroup = useCallback(
    (kind: AgentKind) => {
      setCollapsedGroups((current) => {
        const nextCollapsed = kind === activeAgent ? !current[kind] : false;
        return {
          ...current,
          [kind]: nextCollapsed,
        };
      });
      focusAgent(kind, activePanel);
    },
    [activeAgent, activePanel, focusAgent],
  );

  const describeConversationStatus = useCallback(
    (status: string) => {
      switch (status) {
        case "draft":
          return copy("Draft", "草稿");
        case "running":
          return copy("Running", "运行中");
        case "queued":
          return copy("Queued", "排队中");
        case "waiting_human":
          return copy("Waiting", "待审批");
        case "blocked":
          return copy("Blocked", "受阻");
        case "paused":
          return copy("Paused", "已暂停");
        case "idle":
          return copy("Idle", "空闲");
        case "completed":
          return copy("Completed", "已完成");
        case "failed":
          return copy("Failed", "失败");
        case "cancelled":
          return copy("Cancelled", "已取消");
        case "active":
          return copy("Active", "活跃");
        default:
          return status;
      }
    },
    [copy],
  );

  const activeRunStatusText = useMemo((): RunStatusText | null => {
    if (!activeWorkspace) {
      return null;
    }

    const sortedRuns = [...activeWorkspace.runs].sort(
      (left, right) => parseConversationSortTime(right.updatedAt) - parseConversationSortTime(left.updatedAt),
    );
    const latestOpenRun = sortedRuns.find((run) => isOpenRunStatus(run.status)) ?? null;
    const activeRun = sortedRuns.find((run) => isActivelyExecutingRunStatus(run.status)) ?? null;
    const openRuns = sortedRuns.filter((run) => isOpenRunStatus(run.status));
    const activeRuns = sortedRuns.filter((run) => isActivelyExecutingRunStatus(run.status));

    if (!latestOpenRun && !sortedRuns.length) {
      return {
        badgeLabel: describeConversationStatus(activeWorkspace.agent.status),
        title: copy("No active run", "当前没有运行中的任务"),
        detail: copy("Create a new session from the composer to start.", "可以通过下方输入框新建会话后启动。"),
        metrics: [
          `${copy("Sessions", "会话")} · ${activeWorkspace.conversations.length}`,
          `${copy("Runs", "运行总数")} · ${sortedRuns.length}`,
        ],
        tone: "neutral" as const,
      };
    }

    if (!latestOpenRun) {
      const latestRun = sortedRuns[0];
      const detailParts = [
        latestRun?.summary,
        latestRun ? `${copy("Last run", "最近一次")}：${describeConversationStatus(latestRun.status)}` : null,
        activeWorkspace.agent.activeTask ? `${copy("Task", "当前任务")}：${activeWorkspace.agent.activeTask}` : null,
      ].filter((value): value is string => Boolean(value && value.trim()));

      return {
        badgeLabel: describeConversationStatus(activeWorkspace.agent.status),
        title: latestRun?.title || copy("No active run", "当前没有运行中的任务"),
        detail:
          detailParts.join(" · ")
          || copy("The latest workspace state is idle. Start a new session when ready.", "当前工作区处于空闲状态，准备好后可以发起新会话。"),
        metrics: [
          latestRun ? `${copy("Updated", "最近更新")} · ${formatDateTime(latestRun.updatedAt)}` : null,
          `${copy("Runs", "运行总数")} · ${sortedRuns.length}`,
        ].filter((value): value is string => Boolean(value)),
        tone: toneForRunStatus(latestRun?.status ?? activeWorkspace.agent.status),
      };
    }

    const highlightedRun = activeRun ?? latestOpenRun;
    const detailParts = [
      highlightedRun.summary,
      activeWorkspace.agent.activeTask ? `${copy("Task", "当前任务")}：${activeWorkspace.agent.activeTask}` : null,
      highlightedRun.status === "waiting_human"
        ? copy("Waiting for manual approval before the run can continue.", "当前等待人工审批，审批通过后才会继续。")
        : null,
      highlightedRun.status === "blocked"
        ? copy("The run hit a blocker and needs investigation or a resume action.", "本轮执行遇到阻塞，需要排查后再恢复。")
        : null,
      highlightedRun.status === "queued"
        ? copy("Queued and waiting for an execution slot.", "当前已入队，正在等待执行槽位。")
        : null,
      highlightedRun.status === "running" || highlightedRun.status === "active"
        ? copy("Execution is still producing messages or tool updates.", "执行仍在继续，后续会补充消息或工具更新。")
        : null,
    ].filter((value): value is string => Boolean(value && value.trim()));

    return {
      badgeLabel: describeConversationStatus(highlightedRun.status),
      title: highlightedRun.title,
      detail: detailParts.join(" · ") || copy("No execution summary yet.", "当前还没有执行摘要。"),
      metrics: [
        `${copy("Updated", "最近更新")} · ${formatDateTime(highlightedRun.updatedAt)}`,
        highlightedRun.startedAt ? `${copy("Started", "开始时间")} · ${formatDateTime(highlightedRun.startedAt)}` : null,
        `${copy("Active runs", "活跃运行")} · ${activeRuns.length}`,
        `${copy("Open runs", "待处理运行")} · ${openRuns.length}`,
      ].filter((value): value is string => Boolean(value)),
      tone: toneForRunStatus(highlightedRun.status),
    };
  }, [activeWorkspace, copy, describeConversationStatus]);

  const shouldShowRunStatusStrip = activePanel === "conversation" || activePanel === "runs";

  const describeConversationPreview = useCallback(
    (conversation: AgentConversationSummary) => {
      const preview = conversation.preview?.trim();
      if (preview) {
        return preview;
      }

      const status = String(conversation.status).trim().toLowerCase();
      switch (status) {
        case "draft":
          return copy("Draft only. Use the start button below when ready.", "当前仅为草稿，准备好后再点击下方启动。");
        case "waiting_human":
          return copy("Waiting for manual review before continuing.", "等待人工审批后继续。");
        case "blocked":
          return copy("Run is blocked. Open the session to inspect the latest failure or blocker.", "本轮执行受阻，打开会话查看最近一次失败或阻塞原因。");
        case "queued":
          return copy("Queued and waiting for backend execution.", "当前已入队，等待后端开始执行。");
        case "running":
        case "active":
          return copy("Waiting for the next execution update.", "等待下一条执行进展回传。");
        case "completed":
          return copy("Run completed. Open the session to inspect the final exchange.", "本轮已完成，打开会话查看最终结果。");
        case "failed":
          return copy("Run stopped after an error. Open the session for details.", "本轮因错误停止，打开会话查看详情。");
        default:
          return copy("No preview yet", "暂无预览");
      }
    },
    [copy],
  );

  const summarizeConversationGroup = useCallback(
    (conversations: AgentConversationSummary[]) => {
      const waitingCount = conversations.filter((conversation) => conversation.status === "waiting_human").length;
      if (waitingCount > 0) {
        return {
          summary: copy(
            `${waitingCount} session${waitingCount > 1 ? "s" : ""} waiting for approval`,
            `${waitingCount} 个会话待审批`,
          ),
          tone: "warning" as const,
        };
      }

      const activeCount = conversations.filter((conversation) => {
        const status = String(conversation.status).trim().toLowerCase();
        return status === "active" || status === "running" || status === "queued" || status === "blocked";
      }).length;
      if (activeCount > 0) {
        return {
          summary: copy(
            `${activeCount} live session${activeCount > 1 ? "s" : ""}`,
            `${activeCount} 个会话进行中`,
          ),
          tone: "positive" as const,
        };
      }

      const draftCount = conversations.filter((conversation) => conversation.status === "draft").length;
      if (draftCount > 0) {
        return {
          summary: copy(
            `${draftCount} draft session${draftCount > 1 ? "s" : ""}`,
            `${draftCount} 个草稿会话`,
          ),
          tone: "neutral" as const,
        };
      }

      const latestConversation = conversations[0];
      if (latestConversation) {
        return {
          summary: `${copy("Last update", "最近更新")} · ${formatDateTime(latestConversation.updatedAt)}`,
          tone: "neutral" as const,
        };
      }

      return {
        summary: copy("No sessions yet", "还没有会话"),
        tone: "neutral" as const,
      };
    },
    [copy],
  );

  useEffect(() => {
    if (!visible || !activeConversationId || !activeConversationCacheKey) {
      setLoadingConversation(false);
      return;
    }
    if (activeConversationId.startsWith("draft-")) {
      setLoadingConversation(false);
      return;
    }

    let active = true;
    setLoadingConversation(true);
    const syncConversation = async (markLoading: boolean) => {
      if (markLoading) {
        setLoadingConversation(true);
      }
      try {
        const record = await apiClient.getAgentConversation(activeAgent, activeConversationId);
        if (!active) {
          return;
        }
        const existingSummary = conversationLookupRef.current.get(activeConversationCacheKey);
        const nextConversation = {
          ...record.conversation,
          updatedAt: resolveConversationUpdatedAt(existingSummary, record.conversation, record.messages),
        };
        setLocalConversations((current) => ({
          ...current,
          [activeAgent]: mergeConversationSummaries(current[activeAgent] ?? [], [nextConversation]),
        }));
        setConversationCache((current) => ({
          ...current,
          [activeConversationCacheKey]: {
            conversation: nextConversation,
            messages: mergeMessages(current[activeConversationCacheKey]?.messages ?? [], record.messages),
          },
        }));
      } catch (error) {
        if (active) {
          setErrorMessage(error instanceof Error ? error.message : copy("Failed to load conversation.", "加载会话失败。"));
        }
      } finally {
        if (active && markLoading) {
          setLoadingConversation(false);
        }
      }
    };
    void syncConversation(true);

    if (activeAgent !== "autonomous") {
      return () => {
        active = false;
      };
    }

    const intervalId = window.setInterval(() => {
      void syncConversation(false);
    }, conversationPollMs);

    return () => {
      active = false;
      window.clearInterval(intervalId);
    };
  }, [activeAgent, activeConversationCacheKey, activeConversationId, conversationPollMs, copy, visible]);

  useEffect(() => {
    if (!visible || pageMode) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        close();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [close, pageMode, visible]);

  useEffect(() => {
    streamShouldFollowRef.current = true;
    streamLastMessageSignatureRef.current = "";
  }, [activeConversationId]);

  useEffect(() => {
    if (activePanel !== "conversation") {
      return;
    }
    const shell = streamShellRef.current;
    if (!shell) {
      return;
    }
    const messages = activeConversation?.messages ?? [];
    const lastMessage = messages[messages.length - 1];
    const nextSignature = lastMessage
      ? `${activeConversationId ?? ""}:${lastMessage.id}:${lastMessage.status ?? ""}:${lastMessage.content.length}`
      : `${activeConversationId ?? ""}:empty`;
    const previousSignature = streamLastMessageSignatureRef.current;
    streamLastMessageSignatureRef.current = nextSignature;
    if (previousSignature === nextSignature) {
      return;
    }
    if (previousSignature && !streamShouldFollowRef.current) {
      return;
    }
    shell.scrollTop = shell.scrollHeight;
  }, [activePanel, activeConversation?.messages, activeConversationId]);

  const handleStreamScroll = useCallback(() => {
    const shell = streamShellRef.current;
    if (!shell) {
      return;
    }
    const distanceToBottom = shell.scrollHeight - shell.scrollTop - shell.clientHeight;
    streamShouldFollowRef.current = distanceToBottom < 80;
  }, []);

  const createAssistantConversationIfNeeded = useCallback(
    async (message: string): Promise<string> => {
      if (activeConversationId && !activeConversationId.startsWith("draft-")) {
        return activeConversationId;
      }

      const draftConversationId = activeConversationId;
      const created = await apiClient.createAssistantConversation({
        userId: assistantUserId,
        title: trimTitle(message),
      });
      if (draftConversationId) {
        removeDraftConversation("assistant", draftConversationId);
      }
      upsertConversationSummary("assistant", {
        id: created.conversationId,
        title: created.title || trimTitle(message),
        preview: null,
        status: "active",
        updatedAt: new Date().toISOString(),
        refId: null,
      });
      setSelectedConversation((current) => ({
        ...current,
        assistant: created.conversationId,
      }));
      return created.conversationId;
    },
    [activeConversationId, removeDraftConversation, upsertConversationSummary],
  );

  const handleAssistantEvent = useCallback(
    (
      conversationId: string,
      streamMessageId: string,
      userInput: string,
      event: AssistantTurnStreamEvent,
    ) => {
      if (event.event === "llm_delta" || event.event === "llm_final") {
        const nextChunk = extractAssistantText(event);
        const previous = assistantStreamContentRef.current[streamMessageId] ?? "";
        const merged = mergeStreamText(previous, nextChunk);
        assistantStreamContentRef.current[streamMessageId] = merged;
        appendMessage("assistant", conversationId, {
          id: streamMessageId,
          conversationId,
          role: "assistant",
          kind: "message",
          content: merged,
          createdAt: event.receivedAt,
          status: event.event === "llm_final" ? "sent" : "streaming",
          metadata: streamEventTimelineMetadata(event),
        });
        if (merged.trim()) {
          syncConversationPreview("assistant", conversationId, merged, trimTitle(userInput));
        }
        return;
      }

      const detail = formatStreamMessage(event);
      if (!detail) {
        return;
      }

      appendMessage("assistant", conversationId, {
        id: `${streamMessageId}-${event.event}-${event.receivedAt}`,
        conversationId,
        role: event.event.startsWith("tool_") ? "tool" : "system",
        kind: event.event === "tool_call" ? "tool_use" : event.event.startsWith("tool_") ? "tool_result" : "status",
        content: detail,
        createdAt: event.receivedAt,
        status: event.event === "turn.failed" ? "failed" : "sent",
        metadata: streamEventTimelineMetadata(event),
      });
    },
    [appendMessage, syncConversationPreview],
  );

  const handleSubmit = async () => {
    const text = composerInputValue.trim();
    if (!text) {
      return;
    }

    if (activeAgent === "autonomous" && autonomousActiveRun) {
      setPanelNotice({
        panel: "conversation",
        tone: "info",
        message: copy(
          "Automation already has an open run. Wait for the current run to finish before starting the next task.",
          "Automation 当前已有未结束的运行，请等待当前 run 结束后再启动下一轮任务。",
        ),
      });
      return;
    }

    setPanelNotice(null);
    setErrorMessage(undefined);
    setSending(true);
    if (activeDraftComposerKey != null) {
      setDraftComposerValues((current) => ({
        ...current,
        [activeDraftComposerKey]: "",
      }));
    } else {
      setComposerValue("");
    }

    try {
      if (activeAgent === "assistant") {
        const conversationId = await createAssistantConversationIfNeeded(text);
        const timestamp = new Date().toISOString();
        const streamMessageId = `assistant-stream-${Date.now()}`;

        appendMessage("assistant", conversationId, {
          id: `assistant-user-${timestamp}`,
          conversationId,
          role: "user",
          kind: "message",
          content: text,
          createdAt: timestamp,
          status: "sent",
          metadata: {
            eventKind: "human",
          },
        });
        syncConversationPreview("assistant", conversationId, text, trimTitle(text));

        appendMessage("assistant", conversationId, {
          id: streamMessageId,
          conversationId,
          role: "assistant",
          kind: "message",
          content: "",
          createdAt: timestamp,
          status: "streaming",
          metadata: {
            eventKind: "thinking",
            itemType: "agent_message",
          },
        });

        assistantStreamContentRef.current[streamMessageId] = "";
        assistantAbortRef.current?.abort();
        const controller = new AbortController();
        assistantAbortRef.current = controller;
        let receivedStreamEvent = false;

        try {
          await apiClient.streamAssistantTurn(
            {
              conversationId,
              message: text,
              signal: controller.signal,
            },
            (event) => {
              receivedStreamEvent = true;
              handleAssistantEvent(conversationId, streamMessageId, text, event);
            },
          );
          const finalText = assistantStreamContentRef.current[streamMessageId] ?? "";
          appendMessage("assistant", conversationId, {
            id: streamMessageId,
            conversationId,
            role: "assistant",
            kind: "message",
            content: finalText || copy("No textual output returned.", "这一轮没有返回文本内容。"),
            createdAt: new Date().toISOString(),
            status: "sent",
            metadata: {
              eventKind: "thinking",
              itemType: "agent_message",
            },
          });
        } catch (error) {
          const message = error instanceof Error ? error.message : copy("Assistant request failed.", "Assistant 请求失败。");
          if (!receivedStreamEvent && /:\s*(404|405)\b/.test(message)) {
            const result = await apiClient.sendAssistantMessage({ conversationId, message: text });
            appendMessage("assistant", conversationId, {
              id: streamMessageId,
              conversationId,
              role: "system",
              kind: "status",
              content:
                result.status === "queued"
                  ? copy("Assistant SSE endpoint is unavailable. The request has been queued instead.", "Assistant SSE 接口不可用，已改为排队提交。")
                  : copy("Assistant accepted the request, but live streaming is unavailable.", "Assistant 已接收请求，但当前环境不支持实时流式展示。"),
              createdAt: new Date().toISOString(),
              status: "sent",
              metadata: {
                eventKind: "execution_result",
              },
            });
            setPanelNotice({
              panel: "conversation",
              tone: "info",
              message: copy(
                "Fell back to queued delivery because the live Assistant stream is unavailable.",
                "当前环境没有可用的 Assistant 实时流，已自动降级为排队提交。",
              ),
            });
          } else if (!receivedStreamEvent && /aborted|abort/i.test(message)) {
            appendMessage("assistant", conversationId, {
              id: streamMessageId,
              conversationId,
              role: "system",
              kind: "status",
              content: copy("Assistant stream was cancelled.", "Assistant 流已取消。"),
              createdAt: new Date().toISOString(),
              status: "failed",
              metadata: {
                eventKind: "execution_result",
              },
            });
          } else {
            appendMessage("assistant", conversationId, {
              id: streamMessageId,
              conversationId,
              role: "system",
              kind: "status",
              content: message,
              createdAt: new Date().toISOString(),
              status: "failed",
              metadata: {
                eventKind: "execution_result",
              },
            });
            setErrorMessage(message);
          }
        } finally {
          assistantAbortRef.current = null;
          delete assistantStreamContentRef.current[streamMessageId];
        }
      } else {
        let conversationId = activeConversationId;
        if (!conversationId) {
          conversationId = createDraftConversation(activeAgent);
        }

        const timestamp = new Date().toISOString();
        appendMessage(activeAgent, conversationId, {
          id: `local-user-${timestamp}`,
          conversationId,
          role: "user",
          kind: "message",
          content: text,
          createdAt: timestamp,
          status: "sent",
          metadata: {
            eventKind: "human",
          },
        });
        syncConversationPreview(activeAgent, conversationId, text, trimTitle(text));

        const draftConversationId = conversationId;
        const result = await apiClient.startAutonomousGoal({
          title: trimTitle(text),
          goalText: text,
          conversationId: conversationId.startsWith("draft-") ? null : conversationId,
        });
        removeDraftConversation("autonomous", draftConversationId);
        await loadWorkspaces();
        setSelectedConversation((current) => ({
          ...current,
          autonomous: result.conversationId,
        }));
        appendMessage("autonomous", result.conversationId, {
          id: `autonomous-status-${result.runId ?? Date.now()}`,
          conversationId: result.conversationId,
          role: "system",
          kind: "status",
          content: copy("Automation task has been submitted to the backend.", "自动化任务已提交到后端。"),
          createdAt: new Date().toISOString(),
          status: "sent",
          metadata: {
            eventKind: "thinking",
          },
        });
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : copy("Request failed.", "请求失败。");
      if (activeConversationId) {
        appendMessage(activeAgent, activeConversationId, {
          id: `error-${Date.now()}`,
          conversationId: activeConversationId,
          role: "system",
          kind: "status",
          content: message,
          createdAt: new Date().toISOString(),
          status: "failed",
          metadata: {
            eventKind: "execution_result",
          },
        });
      }
      setErrorMessage(message);
    } finally {
      setSending(false);
    }
  };

  const handleSaveConfig = async () => {
    if (!configDraft || !settingsSnapshot) {
      setPanelNotice({
        panel: "config",
        tone: "error",
        message: copy("Settings are not loaded yet.", "设置尚未加载完成。"),
      });
      return;
    }

    const interval = Number.parseInt(configDraft.skillHealthAutonomyIntervalSeconds, 10);
    if (!Number.isFinite(interval) || interval <= 0) {
      setPanelNotice({
        panel: "config",
        tone: "error",
        message: copy("Skill health interval must be a positive integer.", "技能巡检间隔必须是正整数。"),
      });
      return;
    }

    setSavingConfig(true);
    try {
      const activeAgentConfig = agentConfigDrafts[activeAgent];
      const [nextSettings] = await Promise.all([
        apiClient.updateSettings({
          desktopApprovalsOnly: configDraft.desktopApprovalsOnly,
          autonomyEnabled: configDraft.autonomyEnabled,
          skillHealthAutonomyEnabled: configDraft.skillHealthAutonomyEnabled,
          skillHealthAutonomyIntervalSeconds: interval,
        }),
        apiClient.updateAgentProfile(activeAgent, {
          promptConfig: {
            systemPrompt: activeAgentConfig.systemPrompt,
            goalTemplate: activeAgentConfig.goalTemplate,
            scoringRubric: activeAgentConfig.scoringRubric,
            recruitingPolicy: recruitingPolicyPayloadFromDraft(activeAgentConfig.recruitingPolicy),
          },
        }),
      ]);
      setSettingsSnapshot(nextSettings);
      setConfigDraft(configDraftFromSettings(nextSettings));
      await loadWorkspaces();
      setPanelNotice({
        panel: "config",
        tone: "success",
        message: copy("Configuration and agent prompt saved.", "配置与 Agent 提示词已保存。"),
      });
    } catch (error) {
      setPanelNotice({
        panel: "config",
        tone: "error",
        message: error instanceof Error ? error.message : copy("Failed to save settings.", "保存设置失败。"),
      });
    } finally {
      setSavingConfig(false);
    }
  };

  const updateRecruitingPolicyText = (field: keyof Omit<RecruitingPolicyDraft, "scoreWeights" | "thresholds">, value: string) => {
    setAgentConfigDrafts((current) => ({
      ...current,
      [activeAgent]: {
        ...current[activeAgent],
        recruitingPolicy: {
          ...current[activeAgent].recruitingPolicy,
          [field]: value,
        },
      },
    }));
  };

  const updateRecruitingPolicyNumber = (
    group: "scoreWeights" | "thresholds",
    field: string,
    value: string,
  ) => {
    setAgentConfigDrafts((current) => ({
      ...current,
      [activeAgent]: {
        ...current[activeAgent],
        recruitingPolicy: {
          ...current[activeAgent].recruitingPolicy,
          [group]: {
            ...current[activeAgent].recruitingPolicy[group],
            [field]: value,
          },
        },
      },
    }));
  };

  const handleApprovalAction = async (approval: ApprovalItem, action: "approve" | "reject") => {
    setApprovalActionId(approval.id);
    try {
      const options = approvalOptionsFor(approval, copy);
      const selectedKey = approvalSelections[approval.id] ?? options[0]?.key;
      const decisionReason = buildApprovalDecisionReason(approval, options, selectedKey, approvalNotes[approval.id]);
      if (action === "approve") {
        await apiClient.approveItem(approval.id, decisionReason);
      } else {
        await apiClient.rejectItem(approval.id, decisionReason ?? (approvalNotes[approval.id]?.trim() || undefined));
      }
      await loadWorkspaces();
      setApprovalNotes((current) => {
        const next = { ...current };
        delete next[approval.id];
        return next;
      });
      setApprovalSelections((current) => {
        const next = { ...current };
        delete next[approval.id];
        return next;
      });
      setPanelNotice({
        panel: "conversation",
        tone: "success",
        message:
          action === "approve"
            ? copy("Approval has been confirmed.", "审批已通过。")
            : copy("Approval has been rejected.", "审批已拒绝。"),
      });
    } catch (error) {
      setPanelNotice({
        panel: "conversation",
        tone: "error",
        message: error instanceof Error ? error.message : copy("Approval action failed.", "审批动作失败。"),
      });
    } finally {
      setApprovalActionId(null);
    }
  };

  const handleRunAction = async (run: AgentRunRecord, action: "cancel" | "resume") => {
    setRunActionBusyId(run.id);
    try {
      if (action === "cancel") {
        await apiClient.cancelAutonomousRun(run.id, copy("Cancelled from agent management page.", "在 Agent 管理页中手动中止。"));
      } else {
        await apiClient.resumeAutonomousRun(run.id, copy("Resumed from agent management page.", "在 Agent 管理页中手动恢复。"));
      }
      await loadWorkspaces();
      setPanelNotice({
        panel: "runs",
        tone: "success",
        message:
          action === "cancel"
            ? copy("Run cancelled.", "运行已中止。")
            : copy("Run resumed.", "运行已恢复。"),
      });
    } catch (error) {
      setPanelNotice({
        panel: "runs",
        tone: "error",
        message: error instanceof Error ? error.message : copy("Run action failed.", "运行控制失败。"),
      });
    } finally {
      setRunActionBusyId(null);
    }
  };

  const handleSeedGoalFromTemplate = useCallback(
    (template: SharedSceneTemplateRecord) => {
      setAutonomousGoalDraft((current) => ({
        sceneTemplateKey: template.key,
        title: template.title,
        jdId: template.requiresJd ? current.jdId : "",
        candidateCountTarget: template.supportsCandidateCountTarget
          ? String(template.defaultCandidateCountTarget ?? 3)
          : "",
        goalText: template.defaultGoalText,
      }));
      focusAgent("autonomous", "runs");
      setPanelNotice({
        panel: "runs",
        tone: "info",
        message: copy(
          `${template.title} template is now in the task form. Review the JD and task objective before starting.`,
          `${template.title} 模板已填入任务表单，启动前请确认 JD 与任务描述。`,
        ),
      });
    },
    [copy, focusAgent],
  );

  const handleInsertComposerFromTemplate = useCallback(
    (template: SharedSceneTemplateRecord) => {
      focusAgent("assistant", "conversation");
      if (activeDraftComposerKey != null) {
        setDraftComposerValues((current) => ({
          ...current,
          [activeDraftComposerKey]: template.defaultGoalText,
        }));
      } else {
        setComposerValue(template.defaultGoalText);
      }
      setPanelNotice({
        panel: "conversation",
        tone: "info",
        message: copy(
          `${template.title} template has been inserted into the composer.`,
          `${template.title} 模板已插入到对话输入框。`,
        ),
      });
    },
    [activeDraftComposerKey, copy, focusAgent],
  );

  const handleCreateGoalFromRuns = async () => {
    const title = autonomousGoalDraft.title.trim();
    const goalText = autonomousGoalDraft.goalText.trim();
    const candidateCountTarget = Number.parseInt(autonomousGoalDraft.candidateCountTarget, 10);
    const selectedTemplate = autonomousGoalDraft.sceneTemplateKey
      ? sceneTemplateLookup.get(autonomousGoalDraft.sceneTemplateKey)
      : undefined;
    if (!title || !goalText) {
      setPanelNotice({
        panel: "runs",
        tone: "error",
        message: copy("Title and task objective are required.", "标题和任务目标不能为空。"),
      });
      return;
    }
    if (selectedTemplate?.requiresJd && !autonomousGoalDraft.jdId.trim()) {
      setPanelNotice({
        panel: "runs",
        tone: "error",
        message: copy("This action requires selecting a JD first.", "该动作需要先选择一个 JD。"),
      });
      return;
    }
    if (
      selectedTemplate?.supportsCandidateCountTarget
      && (!Number.isFinite(candidateCountTarget) || candidateCountTarget <= 0)
    ) {
      setPanelNotice({
        panel: "runs",
        tone: "error",
        message: copy("Candidate target must be a positive integer.", "候选人数目标必须是正整数。"),
      });
      return;
    }
    if (autonomousActiveRun) {
      setPanelNotice({
        panel: "runs",
        tone: "info",
        message: copy(
          "Automation already has an active run. Wait for it to finish before starting the next task.",
          "Automation 当前已有运行中的任务，请等待当前运行结束后再启动下一轮任务。",
        ),
      });
      return;
    }

    setRunActionBusyId("create-goal");
    try {
      const result = await apiClient.startAutonomousGoal({
        title,
        goalText,
        goalKind: selectedTemplate?.goalKind,
        jdId: autonomousGoalDraft.jdId.trim() || null,
        candidateCountTarget:
          selectedTemplate == null
            ? (Number.isFinite(candidateCountTarget) && candidateCountTarget > 0 ? candidateCountTarget : null)
            : (selectedTemplate.supportsCandidateCountTarget ? candidateCountTarget : null),
        constraints: selectedTemplate?.constraints,
        successCriteria: selectedTemplate?.successCriteria,
        contextHints: selectedTemplate?.contextHints,
      });
      await loadWorkspaces();
      setSelectedConversation((current) => ({
        ...current,
        autonomous: result.conversationId,
      }));
      setAutonomousGoalDraft(autonomousGoalDraftTemplate(autonomousDefaultGoalTemplate));
      setPanelNotice({
        panel: "runs",
        tone: "success",
        message: copy(
          selectedTemplate ? `${selectedTemplate.title} created and queued.` : "Automation task created and queued.",
          selectedTemplate ? `${selectedTemplate.title} 已创建并进入队列。` : "自动化任务已创建并进入队列。",
        ),
      });
    } catch (error) {
      setPanelNotice({
        panel: "runs",
        tone: "error",
        message: error instanceof Error ? error.message : copy("Failed to create automation task.", "创建自动化任务失败。"),
      });
    } finally {
      setRunActionBusyId(null);
    }
  };

  const handleRunTemplateNow = async (template: SharedSceneTemplateRecord) => {
    if (autonomousActiveRun) {
      setPanelNotice({
        panel: "tools",
        tone: "info",
        message: copy(
          "Automation already has an open run. Wait for it to finish before queueing another template.",
          "Automation 当前已有未结束的运行，请等待其结束后再触发新的模板。",
        ),
      });
      return;
    }
    setToolActionBusyKey(template.key);
    try {
      const result = await apiClient.runSceneTemplate(template.key, {
        title: template.title,
        goalText: template.defaultGoalText,
        contextHints: template.contextHints,
        constraints: template.constraints,
        successCriteria: template.successCriteria,
      });
      await loadWorkspaces();
      await loadJobDescriptions();
      setSelectedConversation((current) => ({
        ...current,
        autonomous: result.conversationId,
      }));
      setPanelNotice({
        panel: "tools",
        tone: "success",
        message: copy(
          `${template.title} has been queued.`,
          `${template.title} 已加入队列。`,
        ),
      });
    } catch (error) {
      setPanelNotice({
        panel: "tools",
        tone: "error",
        message: error instanceof Error ? error.message : copy("Failed to queue scene template.", "触发共享场景模板失败。"),
      });
    } finally {
      setToolActionBusyKey(null);
    }
  };

  const startHeaderDrag = (event: React.MouseEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    if (target.closest("button")) {
      return;
    }
    headerDragRef.current = {
      pointerX: event.clientX,
      pointerY: event.clientY,
      x: overlayRect.x,
      y: overlayRect.y,
    };
    const handleMove = (moveEvent: MouseEvent) => {
      const current = headerDragRef.current;
      if (!current) {
        return;
      }
      setOverlayRect({
        ...overlayRect,
        x: current.x + moveEvent.clientX - current.pointerX,
        y: current.y + moveEvent.clientY - current.pointerY,
      });
    };
    const handleUp = () => {
      headerDragRef.current = null;
      window.removeEventListener("mousemove", handleMove);
      window.removeEventListener("mouseup", handleUp);
    };
    window.addEventListener("mousemove", handleMove);
    window.addEventListener("mouseup", handleUp);
  };

  const startResize = (event: React.MouseEvent<HTMLDivElement>) => {
    event.preventDefault();
    resizeRef.current = {
      pointerX: event.clientX,
      pointerY: event.clientY,
      width: overlayRect.width,
      height: overlayRect.height,
    };
    const handleMove = (moveEvent: MouseEvent) => {
      const current = resizeRef.current;
      if (!current) {
        return;
      }
      setOverlayRect({
        ...overlayRect,
        width: current.width + moveEvent.clientX - current.pointerX,
        height: current.height + moveEvent.clientY - current.pointerY,
      });
    };
    const handleUp = () => {
      resizeRef.current = null;
      window.removeEventListener("mousemove", handleMove);
      window.removeEventListener("mouseup", handleUp);
    };
    window.addEventListener("mousemove", handleMove);
    window.addEventListener("mouseup", handleUp);
  };

  const renderEmptyPanel = (title: string, body: string) => (
    <div style={panelEmptyStyle()}>
      <div style={{ fontSize: "var(--font-size-base)", color: "var(--chat-text-primary)", fontWeight: 500 }}>{title}</div>
      <div>{body}</div>
    </div>
  );

  const renderRunsPanel = (runs: AgentRunRecord[]) => {
    const selectedTemplate = autonomousGoalDraft.sceneTemplateKey
      ? sceneTemplateLookup.get(autonomousGoalDraft.sceneTemplateKey)
      : undefined;
    return (
      <div className="chat-stream">
        {activeAgent === "autonomous" ? (
          <section className="chat-card">
            <div className="chat-card__eyebrow">{copy("New automation task", "新建自动化任务")}</div>
            <div style={{ display: "grid", gap: "var(--space-3)" }}>
              {selectedTemplate ? (
                <div
                  style={{
                    display: "grid",
                    gap: "var(--space-2)",
                    padding: "var(--space-3)",
                    borderRadius: 12,
                    border: "1px solid color-mix(in srgb, var(--info) 24%, var(--border-line))",
                    background: "color-mix(in srgb, var(--info) 6%, white)",
                  }}
                >
                  <div className="chat-list-item__title">{selectedTemplate.title}</div>
                  <div className="chat-list-item__summary">{selectedTemplate.summary}</div>
                  <div className="chat-card__meta-list">
                    <span>{copy("Task kind", "任务类型")} · {selectedTemplate.goalKind}</span>
                    <span>{copy("Requires JD", "需要 JD")} · {selectedTemplate.requiresJd ? copy("yes", "是") : copy("no", "否")}</span>
                    {selectedTemplate.supportsCandidateCountTarget ? (
                      <span>{copy("Supports target", "支持人数目标")} · {copy("yes", "是")}</span>
                    ) : null}
                  </div>
                </div>
              ) : null}
              <div style={{ display: "grid", gap: "var(--space-1)" }}>
                <span className="chat-list-item__title">{copy("Title", "标题")}</span>
                <FormInput
                  type="text"
                  value={autonomousGoalDraft.title}
                  onChange={(event) =>
                    setAutonomousGoalDraft((current) => ({
                      ...current,
                      title: event.target.value,
                    }))
                  }
                  placeholder={copy("JD-xxx recruit 3 candidates", "例如：JD-xxx 找够 3 名候选人")}
                />
              </div>
              <div style={{ display: "grid", gap: "var(--space-1)" }}>
                <span className="chat-list-item__title">{copy("JD", "JD")}</span>
                <FormSelect
                  value={autonomousGoalDraft.jdId}
                  onChange={(event) =>
                    setAutonomousGoalDraft((current) => ({
                      ...current,
                      jdId: event.target.value,
                    }))
                  }
                >
                  <option value="">{copy("Select a JD (optional)", "选择一个 JD（可选）")}</option>
                  {jobDescriptionOptions.map((job) => (
                    <option key={job.jobDescriptionId ?? job.title} value={job.jobDescriptionId ?? ""}>
                      {job.title}
                    </option>
                  ))}
                </FormSelect>
              </div>
              {selectedTemplate?.supportsCandidateCountTarget ?? true ? (
                <div style={{ display: "grid", gap: "var(--space-1)" }}>
                  <span className="chat-list-item__title">{copy("Candidate target", "候选人数目标")}</span>
                  <FormInput
                    type="number"
                    min={1}
                    value={autonomousGoalDraft.candidateCountTarget}
                    onChange={(event) =>
                      setAutonomousGoalDraft((current) => ({
                        ...current,
                        candidateCountTarget: event.target.value,
                      }))
                    }
                  />
                </div>
              ) : null}
              <div style={{ display: "grid", gap: "var(--space-1)" }}>
                <span className="chat-list-item__title">{copy("Task objective", "任务目标")}</span>
                <FormTextarea
                  value={autonomousGoalDraft.goalText}
                  onChange={(event) =>
                    setAutonomousGoalDraft((current) => ({
                      ...current,
                      goalText: event.target.value,
                    }))
                  }
                  placeholder={copy("Describe the automation task, constraints, and success criteria…", "描述本轮自动化任务、约束和完成标准…")}
                  className="chat-overlay-form-textarea--medium"
                />
              </div>
              <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
                <button
                  type="button"
                  className="chat-composer__submit"
                  disabled={runActionBusyId === "create-goal" || autonomousActiveRun != null}
                  onClick={() => void handleCreateGoalFromRuns()}
                >
                  {runActionBusyId === "create-goal"
                    ? copy("Creating…", "创建中…")
                    : autonomousActiveRun
                      ? copy("Already running", "已有运行中")
                      : copy("Create and start", "创建并启动")}
                </button>
                <button
                  type="button"
                  className="chat-overlay__header-button"
                  disabled={runActionBusyId === "create-goal"}
                  onClick={() => setAutonomousGoalDraft(autonomousGoalDraftTemplate(autonomousDefaultGoalTemplate))}
                >
                  {copy("Reset form", "重置表单")}
                </button>
              </div>
            </div>
          </section>
        ) : null}

        {!runs.length ? (
          <section className="chat-card">
            <div className="chat-list-item__summary">
              {copy("The backend has not reported any runs for this agent yet.", "当前 Agent 还没有返回运行记录。")}
            </div>
          </section>
        ) : null}
        {runs.map((run) => (
          <section key={run.id} className="chat-card">
            <div className="chat-card__title-row">
              <div>
                <div className="chat-list-item__title">{run.title}</div>
                <div className="chat-list-item__meta">
                  {copy("Updated", "更新时间")} · {formatDateTime(run.updatedAt)}
                </div>
              </div>
              <StatusBadge tone={run.status === "completed" ? "positive" : run.status === "failed" ? "critical" : "warning"}>
                {run.status}
              </StatusBadge>
            </div>
            {run.summary ? <div className="chat-list-item__summary">{run.summary}</div> : null}
            {run.startedAt ? (
              <div className="chat-card__meta-list">
                <span>{copy("Started", "开始于")} · {formatDateTime(run.startedAt)}</span>
              </div>
            ) : null}
            {activeAgent === "autonomous" ? (
              <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
                {run.refId ? (
                  <button
                    type="button"
                    className="chat-overlay__header-button"
                    onClick={() => {
                      const conversationId = activeWorkspace?.conversations.find((conversation) =>
                        conversation.id === run.refId
                        || conversation.id === run.id
                        || conversation.refId === run.refId
                        || conversation.refId === run.id,
                      )?.id ?? run.refId ?? run.id;
                      focusAgent("autonomous", "conversation");
                      setSelectedConversation((current) => ({
                        ...current,
                        autonomous: conversationId ?? current.autonomous,
                      }));
                    }}
                  >
                    {copy("Open session", "打开会话")}
                  </button>
                ) : null}
                {isOpenRunStatus(run.status) ? (
                  <button
                    type="button"
                    className="chat-overlay__header-button"
                    disabled={runActionBusyId === run.id}
                    onClick={() => void handleRunAction(run, "cancel")}
                  >
                    {runActionBusyId === run.id ? copy("Working…", "处理中…") : copy("Cancel run", "中止运行")}
                  </button>
                ) : null}
                {isResumableRunStatus(run.status) ? (
                  <button
                    type="button"
                    className="chat-composer__submit"
                    disabled={runActionBusyId === run.id}
                    onClick={() => void handleRunAction(run, "resume")}
                  >
                    {runActionBusyId === run.id ? copy("Working…", "处理中…") : copy("Resume run", "恢复运行")}
                  </button>
                ) : null}
              </div>
            ) : null}
          </section>
        ))}
      </div>
    );
  };

  const renderMemoryPanel = (memories: AgentMemorySummary[]) => {
    if (!memories.length) {
      return renderEmptyPanel(copy("No memory snapshot", "暂无记忆快照"), copy("This agent has not exposed memory summaries yet.", "当前 Agent 还没有暴露可展示的记忆摘要。"));
    }
    return (
      <div className="chat-stream">
        {memories.map((memory) => (
          <section key={memory.id} className="chat-card">
            <div className="chat-card__title-row">
              <div className="chat-list-item__title">{memory.title}</div>
              <StatusBadge tone="neutral">{memory.scope}</StatusBadge>
            </div>
            <div className="chat-list-item__summary">{memory.summary}</div>
            <div className="chat-list-item__meta">
              {copy("Status", "状态")} · {memory.status} · {copy("Updated", "更新时间")} · {formatDateTime(memory.updatedAt)}
            </div>
          </section>
        ))}
      </div>
    );
  };

  const renderSkillsPanel = (skills: SkillRecord[]) => {
    if (!skills.length) {
      return renderEmptyPanel(copy("No skills returned", "暂无技能数据"), copy("The backend has not exposed skill snapshots for this agent.", "后端暂未返回该 Agent 的技能快照。"));
    }
    return (
      <div className="chat-stream">
        {skills.map((skill) => (
          <section key={skill.id} className="chat-card">
            <div className="chat-card__title-row">
              <div className="chat-list-item__title">{skill.name}</div>
              <StatusBadge tone={toneForHealth(skill.health)}>{skill.health}</StatusBadge>
            </div>
            <div className="chat-list-item__summary">{skill.summary || skill.description || copy("No summary yet.", "暂无摘要。")}</div>
            <div className="chat-card__meta-list">
              <span>{copy("Version", "版本")} · {skill.version}</span>
              <span>{copy("Stage", "阶段")} · {skill.boundStage}</span>
              <span>{copy("Status", "状态")} · {skill.status}</span>
            </div>
          </section>
        ))}
      </div>
    );
  };

  const renderToolsPanel = (tools: AgentToolSummary[], templates: SharedSceneTemplateRecord[]) => {
    return (
      <div className="chat-stream">
        {templates.length ? (
          <section className="chat-card">
            <div className="chat-card__eyebrow">{copy("Scene templates", "共享场景模板")}</div>
            <div style={{ display: "grid", gap: "var(--space-3)" }}>
              {templates.map((action) => {
                return (
                  <div
                    key={action.key}
                    style={{
                      display: "grid",
                      gap: "var(--space-2)",
                      padding: "var(--space-3)",
                      borderRadius: 12,
                      border: "1px solid var(--border-line)",
                      background: "color-mix(in srgb, var(--bg-subtle) 72%, white)",
                    }}
                  >
                    <div className="chat-card__title-row">
                      <div className="chat-list-item__title">{action.title}</div>
                      <StatusBadge tone={action.directRunnable ? "positive" : "neutral"}>
                        {action.goalKind}
                      </StatusBadge>
                    </div>
                    <div className="chat-list-item__summary">{action.summary}</div>
                    <div className="chat-card__meta-list">
                      <span>{copy("Requires JD", "需要 JD")} · {action.requiresJd ? copy("yes", "是") : copy("no", "否")}</span>
                      <span>{copy("Direct run", "可直接执行")} · {action.directRunnable ? copy("yes", "是") : copy("no", "否")}</span>
                      {action.supportsCandidateCountTarget ? (
                        <span>{copy("Candidate target", "人数目标")} · {action.defaultCandidateCountTarget ?? 3}</span>
                      ) : null}
                    </div>
                    <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
                      <button
                        type="button"
                        className="chat-composer__submit"
                        onClick={() => {
                          if (activeAgent === "assistant") {
                            handleInsertComposerFromTemplate(action);
                            return;
                          }
                          handleSeedGoalFromTemplate(action);
                        }}
                      >
                        {activeAgent === "assistant"
                          ? copy("Insert in chat", "插入对话")
                          : copy("Use template", "使用模板")}
                      </button>
                      {activeAgent === "autonomous" && action.directRunnable ? (
                        <button
                          type="button"
                          className="chat-overlay__header-button"
                          disabled={toolActionBusyKey != null}
                          onClick={() => void handleRunTemplateNow(action)}
                        >
                          {toolActionBusyKey === action.key
                            ? copy("Queueing…", "排队中…")
                            : copy("Run now", "立即执行")}
                        </button>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        ) : null}

        {!tools.length ? (
          <section className="chat-card">
            <div className="chat-list-item__summary">
              {copy("The backend has not returned tools for this agent.", "后端暂未返回该 Agent 的工具列表。")}
            </div>
          </section>
        ) : null}
        {tools.map((tool) => (
          <section key={tool.id} className="chat-card">
            <div className="chat-card__title-row">
              <div className="chat-list-item__title">{tool.name}</div>
              <StatusBadge tone={tool.enabled ? "positive" : "neutral"}>{tool.riskLevel}</StatusBadge>
            </div>
            <div className="chat-card__meta-list">
              <span>{copy("Server", "服务端")} · {tool.serverName}</span>
              <span>{copy("Enabled", "启用状态")} · {tool.enabled ? copy("yes", "是") : copy("no", "否")}</span>
              {tool.endpoint ? <span>{copy("Endpoint", "地址")} · {tool.endpoint}</span> : null}
            </div>
          </section>
        ))}
      </div>
    );
  };

  const renderConfigPanel = () => {
    if (loadingSettings && !configDraft) {
      return renderEmptyPanel(copy("Loading settings…", "正在加载设置…"), copy("Preparing editable desktop settings.", "正在准备可编辑的桌面设置。"));
    }

    if (!configDraft || !settingsSnapshot) {
      return renderEmptyPanel(copy("Settings unavailable", "设置暂不可用"), copy("The current environment did not return `/api/settings`. Saving is disabled.", "当前环境没有返回 `/api/settings`，因此暂时无法保存配置。"));
    }

    const activeAgentConfig = agentConfigDrafts[activeAgent];
    const policy = activeAgentConfig.recruitingPolicy;
    const weightItems: Array<{ key: keyof RecruitingPolicyConfig["scoreWeights"]; label: string; help: string }> = [
      { key: "jdMatch", label: copy("JD match", "JD 匹配"), help: copy("Hard requirements and role relevance.", "硬性门槛与岗位相关性。") },
      { key: "onlineResume", label: copy("Online resume", "在线简历"), help: copy("Public profile and platform resume evidence.", "平台资料与在线简历证据。") },
      { key: "offlineResume", label: copy("Offline resume", "离线简历"), help: copy("Uploaded PDF or attachment depth.", "PDF 或附件简历深度。") },
      { key: "communication", label: copy("Communication", "沟通记录"), help: copy("Intent, contactability, and constraints.", "意向、可联系性与约束。") },
      { key: "stability", label: copy("Stability", "稳定性"), help: copy("Timeline consistency and job-hopping risk.", "时间线一致性与稳定性风险。") },
    ];
    const thresholdItems: Array<{ key: keyof RecruitingPolicyConfig["thresholds"]; label: string }> = [
      { key: "onlinePass", label: copy("Online pass", "在线通过") },
      { key: "offlinePass", label: copy("Offline pass", "离线通过") },
      { key: "compositePass", label: copy("Composite pass", "综合通过") },
      { key: "manualReviewMin", label: copy("Manual review", "人工复核") },
      { key: "interviewRecommend", label: copy("Interview", "推荐面试") },
    ];
    const totalWeight = weightItems.reduce((sum, item) => sum + numberConfigValue(policy.scoreWeights[item.key], 0), 0);

    return (
      <div className="agent-config">
        <section className="agent-config__header">
          <div>
            <span className="agent-config__eyebrow">{copy("Agent configuration", "Agent 配置")}</span>
            <h3>{activeAgent === "autonomous" ? copy("Automation recruiting policy", "自动化招聘策略") : copy("Assistant recruiting policy", "普通 Agent 招聘策略")}</h3>
            <p>{copy("Product-layer rules for JD standards, resume evaluation, scoring, and human checkpoints. Runtime stays generic.", "这里配置 JD 标准、简历评估、评分和人工节点，runtime 保持通用边界。")}</p>
          </div>
          <div className="agent-config__actions">
            <button
              type="button"
              className="chat-overlay__header-button"
              disabled={savingConfig}
              onClick={() => {
                setConfigDraft(configDraftFromSettings(settingsSnapshot));
                setAgentConfigDrafts((current) => ({
                  ...current,
                  [activeAgent]: agentConfigDraftFromWorkspace(workspaces[activeAgent]),
                }));
              }}
            >
              {copy("Reset", "重置")}
            </button>
            <button type="button" className="chat-composer__submit" disabled={savingConfig} onClick={() => void handleSaveConfig()}>
              {savingConfig ? copy("Saving…", "保存中…") : copy("Save", "保存")}
            </button>
          </div>
        </section>

        <section className="agent-config-card">
          <div className="agent-config-card__head">
            <div><span>1</span><h4>{copy("Execution boundaries", "执行边界")}</h4></div>
            <p>{copy("Controls when automation can continue and when human approval remains in the loop.", "控制自动化何时可继续，以及哪些场景保留人工确认。")}</p>
          </div>
          <div className="agent-config-grid agent-config-grid--four">
            <label className="agent-config-check">
              <FormCheckbox
                type="checkbox"
                checked={configDraft.desktopApprovalsOnly}
                onChange={(event) =>
                  setConfigDraft((current) => current ? { ...current, desktopApprovalsOnly: event.target.checked } : current)
                }
              />
              <span>{copy("Desktop approvals only", "仅桌面审批")}</span>
            </label>
            <label className="agent-config-check">
              <FormCheckbox
                type="checkbox"
                checked={configDraft.autonomyEnabled}
                onChange={(event) =>
                  setConfigDraft((current) => current ? { ...current, autonomyEnabled: event.target.checked } : current)
                }
              />
              <span>{copy("Background execution", "后台执行")}</span>
            </label>
            <label className="agent-config-check">
              <FormCheckbox
                type="checkbox"
                checked={configDraft.skillHealthAutonomyEnabled}
                onChange={(event) =>
                  setConfigDraft((current) => current ? { ...current, skillHealthAutonomyEnabled: event.target.checked } : current)
                }
              />
              <span>{copy("Skill health checks", "技能巡检")}</span>
            </label>
            <label className="agent-config-field">
              <span>{copy("Interval seconds", "巡检间隔")}</span>
              <FormInput
                type="number"
                min={1}
                value={configDraft.skillHealthAutonomyIntervalSeconds}
                onChange={(event) =>
                  setConfigDraft((current) => current ? { ...current, skillHealthAutonomyIntervalSeconds: event.target.value } : current)
                }
              />
            </label>
          </div>
        </section>

        <section className="agent-config-card">
          <div className="agent-config-card__head">
            <div><span>2</span><h4>{copy("Instruction source", "指令来源")}</h4></div>
            <p>{copy("Assistant and automation share the same product instruction; automation only adds external triggers.", "Assistant 与自动化复用同一产品指令，自动化只增加外部触发。")}</p>
          </div>
          <div className="agent-config-grid agent-config-grid--two">
            <label className="agent-config-field">
              <span>{copy("System prompt", "System Prompt")}</span>
              <FormTextarea
                value={activeAgentConfig.systemPrompt}
                onChange={(event) =>
                  setAgentConfigDrafts((current) => ({
                    ...current,
                    [activeAgent]: { ...current[activeAgent], systemPrompt: event.target.value },
                  }))
                }
                className="chat-overlay-form-textarea--medium"
              />
            </label>
            <label className="agent-config-field">
              <span>{copy("Automation task instruction", "自动化任务指令模板")}</span>
              <FormTextarea
                value={activeAgentConfig.goalTemplate}
                onChange={(event) =>
                  setAgentConfigDrafts((current) => ({
                    ...current,
                    [activeAgent]: { ...current[activeAgent], goalTemplate: event.target.value },
                  }))
                }
                placeholder={copy("Reusable instructions for event, schedule, or manual automation runs…", "事件、调度或人工创建自动化任务时复用的指令…")}
                className="chat-overlay-form-textarea--medium"
              />
            </label>
          </div>
        </section>

        <section className="agent-config-card">
          <div className="agent-config-card__head">
            <div><span>3</span><h4>{copy("JD standards", "JD 与岗位标准")}</h4></div>
            <p>{copy("Role-specific standards are product configuration, not runtime mechanics.", "岗位标准属于产品配置，不进入 runtime 机制。")}</p>
          </div>
          <div className="agent-config-grid agent-config-grid--two">
            <label className="agent-config-field">
              <span>{copy("JD parsing standard", "JD 拆解标准")}</span>
              <FormTextarea value={policy.jdStandards} onChange={(event) => updateRecruitingPolicyText("jdStandards", event.target.value)} />
            </label>
            <label className="agent-config-field">
              <span>{copy("Per-JD override policy", "不同 JD 评估差异")}</span>
              <FormTextarea value={policy.perJdEvaluation} onChange={(event) => updateRecruitingPolicyText("perJdEvaluation", event.target.value)} />
            </label>
          </div>
        </section>

        <section className="agent-config-card">
          <div className="agent-config-card__head">
            <div><span>4</span><h4>{copy("Candidate evaluation", "候选人评估")}</h4></div>
            <p>{copy("Online resume, offline resume, communication evidence, and composite score remain separate inputs.", "在线简历、离线简历、沟通证据和综合评分分别作为输入。")}</p>
          </div>
          <div className="agent-config-grid agent-config-grid--two">
            <label className="agent-config-field">
              <span>{copy("Online resume criteria", "在线简历标准")}</span>
              <FormTextarea value={policy.onlineResumeCriteria} onChange={(event) => updateRecruitingPolicyText("onlineResumeCriteria", event.target.value)} />
            </label>
            <label className="agent-config-field">
              <span>{copy("Offline resume criteria", "离线简历标准")}</span>
              <FormTextarea value={policy.offlineResumeCriteria} onChange={(event) => updateRecruitingPolicyText("offlineResumeCriteria", event.target.value)} />
            </label>
            <label className="agent-config-field">
              <span>{copy("Communication evidence", "沟通证据")}</span>
              <FormTextarea value={policy.communicationEvidence} onChange={(event) => updateRecruitingPolicyText("communicationEvidence", event.target.value)} />
            </label>
            <label className="agent-config-field">
              <span>{copy("Composite scoring", "AI 综合评分")}</span>
              <FormTextarea value={policy.compositeScoring} onChange={(event) => updateRecruitingPolicyText("compositeScoring", event.target.value)} />
            </label>
          </div>
        </section>

        <section className="agent-config-card">
          <div className="agent-config-card__head">
            <div><span>5</span><h4>{copy("Scoring weights and gates", "评分权重与阈值")}</h4></div>
            <p>{copy("Weights guide the rubric; thresholds decide pass, manual review, and interview recommendation.", "权重指导 rubric，阈值决定通过、人工复核和面试建议。")}</p>
          </div>
          <div className="agent-config-score-grid">
            {weightItems.map((item) => (
              <label key={item.key} className="agent-config-score">
                <span>{item.label}</span>
                <FormInput
                  type="number"
                  min={0}
                  max={100}
                  value={policy.scoreWeights[item.key]}
                  onChange={(event) => updateRecruitingPolicyNumber("scoreWeights", item.key, event.target.value)}
                />
                <small>{item.help}</small>
              </label>
            ))}
          </div>
          <div className="agent-config-threshold-grid">
            {thresholdItems.map((item) => (
              <label key={item.key} className="agent-config-field">
                <span>{item.label}</span>
                <FormInput
                  type="number"
                  min={0}
                  max={100}
                  value={policy.thresholds[item.key]}
                  onChange={(event) => updateRecruitingPolicyNumber("thresholds", item.key, event.target.value)}
                />
              </label>
            ))}
          </div>
          <div className="agent-config-note" data-tone={totalWeight === 100 ? "positive" : "warning"}>
            {copy("Weight total", "权重合计")} · {totalWeight}
          </div>
          <label className="agent-config-field">
            <span>{copy("Detailed scoring rubric", "评分 Rubric")}</span>
            <FormTextarea
              value={activeAgentConfig.scoringRubric}
              onChange={(event) =>
                setAgentConfigDrafts((current) => ({
                  ...current,
                  [activeAgent]: { ...current[activeAgent], scoringRubric: event.target.value },
                }))
              }
              placeholder={copy("Detailed rubric for dimensions, evidence refs, and verdict wording…", "填写维度、证据引用和结论表述规则…")}
              className="chat-overlay-form-textarea--medium"
            />
          </label>
        </section>

        <section className="agent-config-card">
          <div className="agent-config-card__head">
            <div><span>6</span><h4>{copy("Human workflow", "人工节点与交接")}</h4></div>
            <p>{copy("Connects AI scoring, manual screening, interview scheduling, and offer handoff.", "定义 AI 评分、人工筛选、面试安排与 Offer 交接如何衔接。")}</p>
          </div>
          <div className="agent-config-grid agent-config-grid--three">
            <label className="agent-config-field">
              <span>{copy("Manual screening", "人工筛选")}</span>
              <FormTextarea value={policy.screeningRules} onChange={(event) => updateRecruitingPolicyText("screeningRules", event.target.value)} />
            </label>
            <label className="agent-config-field">
              <span>{copy("Interview scheduling", "面试安排")}</span>
              <FormTextarea value={policy.interviewScheduling} onChange={(event) => updateRecruitingPolicyText("interviewScheduling", event.target.value)} />
            </label>
            <label className="agent-config-field">
              <span>{copy("Offer handoff", "Offer 交接")}</span>
              <FormTextarea value={policy.offerHandoff} onChange={(event) => updateRecruitingPolicyText("offerHandoff", event.target.value)} />
            </label>
          </div>
        </section>

        <section className="agent-config-card agent-config-card--compact">
          <div className="agent-config-card__head">
            <div><span>7</span><h4>{copy("Runtime and environment snapshot", "运行与环境快照")}</h4></div>
            <p>{copy("Read-only view of provider, model, account, and product boundaries.", "只读展示 provider、模型、账号与产品边界。")}</p>
          </div>
          <div className="agent-config-summary-grid">
            <div><span>{copy("Provider", "Provider")}</span><strong>{activeWorkspace?.config.providerLabel || "-"}</strong></div>
            <div><span>{copy("Model", "模型")}</span><strong>{activeWorkspace?.config.modelLabel || activeWorkspace?.agent.defaultModel || "-"}</strong></div>
            <div><span>{copy("Locale", "语言")}</span><strong>{settingsSnapshot.locale}</strong></div>
            <div><span>{copy("Timezone", "时区")}</span><strong>{settingsSnapshot.timezone}</strong></div>
            <div><span>{copy("Active account", "当前账户")}</span><strong>{settingsSnapshot.platform.account}</strong></div>
            <div><span>{copy("Intranet sync", "内网同步")}</span><strong>{settingsSnapshot.intranetEnabled ? copy("enabled", "已启用") : copy("disabled", "已关闭")}</strong></div>
          </div>
          {activeWorkspace?.config.boundaries?.length ? (
            <div className="agent-config-boundaries">
              {activeWorkspace.config.boundaries.map((boundary) => (
                <span key={boundary}>{boundary}</span>
              ))}
            </div>
          ) : null}
        </section>
      </div>
    );
  };

  const renderRailContent = () => {
    if (!activeWorkspace) {
      return null;
    }

    if (pageMode) {
      const openRuns = activeWorkspace.runs.filter((run) => isOpenRunStatus(run.status)).length;
      const completedRuns = activeWorkspace.runs.filter((run) => run.status === "completed").length;
      const failedRuns = activeWorkspace.runs.filter((run) => run.status === "failed" || run.status === "cancelled").length;
      const totalRuns = activeWorkspace.runs.length;
      const successRate = totalRuns > 0 ? Math.round((completedRuns / totalRuns) * 1000) / 10 : 0;
      const progressPercent = totalRuns > 0 ? Math.min(100, Math.round(((completedRuns + failedRuns) / totalRuns) * 100)) : 0;
      const enabledTools = activeWorkspace.tools.filter((tool) => tool.enabled).length;
      const healthySkills = activeWorkspace.skills.filter((skill) => skill.health === "healthy").length;
      return (
        <div className="agent-runtime-stack">
          <section className="agent-runtime-card agent-runtime-card--hero">
            <div className="agent-runtime-card__top">
              <span className="agent-runtime-avatar" aria-hidden="true">AG</span>
              <div>
                <h3>{normalizeAgentTitle(activeAgent, activeWorkspace.agent.name)}</h3>
                <p>{agentModeLabel(activeAgent)}</p>
              </div>
              <StatusBadge tone={toneForHealth(activeWorkspace.agent.health)}>
                {describeConversationStatus(activeWorkspace.agent.status)}
              </StatusBadge>
            </div>
            <button type="button" onClick={() => setActivePanel("config")}>
              {copy("Manage Agent", "管理 Agent")}
            </button>
          </section>

          <section className="agent-runtime-card">
            <div className="agent-runtime-card__eyebrow">{copy("Runtime summary", "运行时摘要")}</div>
            <div className="agent-runtime-grid">
              <div><span>{copy("Type", "类型")}</span><strong>{activeAgent === "assistant" ? "Assistant" : "Automation"}</strong></div>
              <div><span>{copy("Model", "模型")}</span><strong>{activeWorkspace.config.modelLabel || activeWorkspace.agent.defaultModel || "-"}</strong></div>
              <div><span>{copy("Tools", "工具")}</span><strong>{enabledTools}</strong></div>
              <div><span>{copy("Skills", "技能")}</span><strong>{healthySkills}</strong></div>
            </div>
          </section>

          <section className="agent-runtime-card">
            <div className="agent-runtime-card__eyebrow">{copy("Current task", "当前任务")}</div>
            <div className="agent-runtime-list">
              <span>{copy("Task", "任务")} · {activeWorkspace.agent.activeTask || activeRunStatusText?.title || "-"}</span>
              <span>{copy("Open runs", "待处理运行")} · {openRuns}</span>
              <span>{copy("Completed", "已完成")} · {completedRuns}</span>
              <span>{copy("Failed", "失败")} · {failedRuns}</span>
            </div>
            <div className="agent-runtime-actions">
              <button type="button" onClick={() => setActivePanel("runs")}>{copy("View tasks", "查看任务")}</button>
              <button type="button" onClick={() => setActivePanel("conversation")}>{copy("Open timeline", "查看时间线")}</button>
            </div>
          </section>

          <section className="agent-runtime-card">
            <div className="agent-runtime-card__title-row">
              <div className="agent-runtime-card__eyebrow">{copy("Today usage", "今日运行数据")}</div>
              <span>{copy("Live", "实时")}</span>
            </div>
            <div className="agent-runtime-metrics">
              <div><span>{copy("Runs", "执行任务")}</span><strong>{totalRuns}</strong></div>
              <div><span>{copy("Success", "成功率")}</span><strong>{successRate}%</strong></div>
              <div><span>{copy("Open", "进行中")}</span><strong>{openRuns}</strong></div>
              <div><span>{copy("Failed", "失败")}</span><strong>{failedRuns}</strong></div>
            </div>
          </section>

          <section className="agent-runtime-card">
            <div className="agent-runtime-card__eyebrow">{copy("Current progress", "当前任务进度")}</div>
            <div className="agent-runtime-progress">
              <div>
                <span>{copy("Resolved steps", "已处理步骤")}</span>
                <strong>{progressPercent}%</strong>
              </div>
              <span><i style={{ width: `${progressPercent}%` }} /></span>
              <p>{completedRuns + failedRuns} / {totalRuns || 0} {copy("runs resolved", "个运行已结束")}</p>
            </div>
          </section>

          <section className="agent-runtime-card">
            <div className="agent-runtime-card__title-row">
              <div className="agent-runtime-card__eyebrow">{copy("Recent runs", "最近运行")}</div>
              <button type="button" onClick={() => setActivePanel("runs")}>{copy("All", "全部")}</button>
            </div>
            <div className="agent-runtime-feed">
              {activeWorkspace.runs.slice(0, 5).map((run) => (
                <button key={run.id} type="button" onClick={() => setActivePanel("runs")}>
                  <strong>{run.title}</strong>
                  <span>{describeConversationStatus(run.status)} · {formatDateTime(run.updatedAt)}</span>
                </button>
              ))}
              {!activeWorkspace.runs.length ? <p>{copy("No recent runs", "暂无运行记录")}</p> : null}
            </div>
          </section>
        </div>
      );
    }

    switch (activePanel) {
      case "conversation":
        return (
          <div className="chat-rail__stack">
            <section className="chat-card">
              <div className="chat-card__eyebrow">{copy("Agent summary", "Agent 摘要")}</div>
              <div className="chat-card__title-row">
                <h4>{normalizeAgentTitle(activeAgent, activeWorkspace.agent.name)}</h4>
                <StatusBadge tone={toneForHealth(activeWorkspace.agent.health)}>
                  {activeWorkspace.agent.status}
                </StatusBadge>
              </div>
              <p>{activeWorkspace.agent.description}</p>
              <div className="chat-card__meta-list">
                <span>{copy("Task", "当前任务")} · {activeWorkspace.agent.activeTask || "-"}</span>
                <span>{copy("Model", "模型")} · {activeWorkspace.agent.defaultModel || activeWorkspace.config.modelLabel || "-"}</span>
                <span>{copy("Approvals", "审批")} · {activeWorkspace.agent.pendingApprovals}</span>
              </div>
              {activeRunStatusText ? <p>{activeRunStatusText.detail}</p> : null}
            </section>
            <section className="chat-card">
              <div className="chat-card__eyebrow">{copy("Recent runs", "最近运行")}</div>
              <div className="chat-card__list">
                {activeWorkspace.runs.slice(0, 4).map((run) => (
                  <div key={run.id} className="chat-list-item">
                    <div className="chat-list-item__title">{run.title}</div>
                    <div className="chat-list-item__meta">{describeConversationStatus(run.status)} · {formatDateTime(run.updatedAt)}</div>
                  </div>
                ))}
                {!activeWorkspace.runs.length ? <div className="chat-empty-inline">{copy("No recent runs", "暂无运行记录")}</div> : null}
              </div>
            </section>
          </div>
        );
      case "config":
        return (
          <section className="chat-card">
            <div className="chat-card__eyebrow">{copy("Current provider", "当前 Provider")}</div>
            <div className="chat-card__meta-list">
              <span>{copy("Provider", "Provider")} · {activeWorkspace.config.providerLabel || "-"}</span>
              <span>{copy("Model", "模型")} · {activeWorkspace.config.modelLabel || activeWorkspace.agent.defaultModel || "-"}</span>
              <span>{copy("Boundaries", "边界")} · {activeWorkspace.config.boundaries.length}</span>
            </div>
          </section>
        );
      case "runs":
        return (
          <section className="chat-card">
            <div className="chat-card__eyebrow">{copy("Run stats", "运行统计")}</div>
            <div className="chat-card__meta-list">
              <span>{copy("Total", "总数")} · {activeWorkspace.runs.length}</span>
              <span>{copy("Pending", "待处理")} · {activeWorkspace.runs.filter((run) => isOpenRunStatus(run.status)).length}</span>
            </div>
          </section>
        );
      case "memory":
        return (
          <section className="chat-card">
            <div className="chat-card__eyebrow">{copy("Memory scopes", "记忆范围")}</div>
            <div className="chat-card__meta-list">
              <span>{copy("Candidate", "候选人")} · {activeWorkspace.memories.filter((memory) => memory.scope === "candidate").length}</span>
              <span>{copy("Job", "职位")} · {activeWorkspace.memories.filter((memory) => memory.scope === "job").length}</span>
              <span>{copy("Global", "全局")} · {activeWorkspace.memories.filter((memory) => memory.scope === "global").length}</span>
            </div>
          </section>
        );
      case "skills":
        return (
          <section className="chat-card">
            <div className="chat-card__eyebrow">{copy("Skill health", "技能健康")}</div>
            <div className="chat-card__meta-list">
              <span>{copy("Healthy", "健康")} · {activeWorkspace.skills.filter((skill) => skill.health === "healthy").length}</span>
              <span>{copy("Warning", "警告")} · {activeWorkspace.skills.filter((skill) => skill.health === "warning").length}</span>
              <span>{copy("Critical", "严重")} · {activeWorkspace.skills.filter((skill) => skill.health === "critical").length}</span>
            </div>
          </section>
        );
      case "tools":
        return (
          <section className="chat-card">
            <div className="chat-card__eyebrow">{copy("Tool inventory", "工具清单")}</div>
            <div className="chat-card__meta-list">
              <span>{copy("Enabled", "已启用")} · {activeWorkspace.tools.filter((tool) => tool.enabled).length}</span>
              <span>{copy("High risk", "高风险")} · {activeWorkspace.tools.filter((tool) => tool.riskLevel === "high").length}</span>
              <span>{copy("Templates", "模板")} · {sceneTemplates.length}</span>
            </div>
          </section>
        );
      default:
        return null;
    }
  };

  const renderAgentCommandCenter = () => {
    if (!activeWorkspace) {
      return null;
    }
    const openRuns = activeWorkspace.runs.filter((run) => isOpenRunStatus(run.status)).length;
    const completedRuns = activeWorkspace.runs.filter((run) => run.status === "completed").length;
    const enabledTools = activeWorkspace.tools.filter((tool) => tool.enabled).length;
    const healthySkills = activeWorkspace.skills.filter((skill) => skill.health === "healthy").length;
    const triggerSources = activeAgent === "assistant"
      ? [copy("User message", "用户消息"), copy("Dashboard shortcut", "工作台快捷入口"), copy("Manual command", "手工指令")]
      : [copy("External event", "外部事件"), copy("Schedule", "定时调度"), copy("Manual task", "手工任务"), copy("Sync feed", "同步数据流")];

    return (
      <section className="agent-management-overview">
        <div className="agent-management-overview__head">
          <div>
            <div className="chat-card__eyebrow">{copy("Operating model", "运行模型")}</div>
            <h3>{agentDisplayName(activeAgent)}</h3>
            <p>{agentModeSummary(activeAgent)}</p>
          </div>
          <StatusBadge tone={toneForHealth(activeWorkspace.agent.health)}>
            {describeConversationStatus(activeWorkspace.agent.status)}
          </StatusBadge>
        </div>

        <div className="agent-management-overview__metrics">
          <div>
            <span>{copy("Mode", "模式")}</span>
            <strong>{agentModeLabel(activeAgent)}</strong>
          </div>
          <div>
            <span>{copy("Open runs", "待处理运行")}</span>
            <strong>{openRuns}</strong>
          </div>
          <div>
            <span>{copy("Completed", "已完成")}</span>
            <strong>{completedRuns}</strong>
          </div>
          <div>
            <span>{copy("Tools", "可用工具")}</span>
            <strong>{enabledTools}</strong>
          </div>
          <div>
            <span>{copy("Skills", "健康技能")}</span>
            <strong>{healthySkills}</strong>
          </div>
        </div>

        <div className="agent-management-overview__grid">
          <div className="agent-management-overview__card">
            <div className="chat-list-item__title">{copy("Trigger sources", "触发来源")}</div>
            <div className="agent-management-overview__chips">
              {triggerSources.map((source) => (
                <span key={source} className="chat-chip">{source}</span>
              ))}
            </div>
          </div>
          <div className="agent-management-overview__card">
            <div className="chat-list-item__title">{copy("Runtime boundary", "Runtime 边界")}</div>
            <p>
              {copy(
                "Runtime only owns turns, tools, permissions, and transcript. Product semantics stay in adapters, prompts, and business tools.",
                "Runtime 只负责 turn、工具、权限和 transcript；产品语义保留在 adapter、prompt 和业务工具中。",
              )}
            </p>
          </div>
        </div>

        {activeRunStatusText ? (
          <div className="agent-management-overview__current">
            <StatusBadge tone={activeRunStatusText.tone}>{activeRunStatusText.badgeLabel}</StatusBadge>
            <div>
              <strong>{activeRunStatusText.title}</strong>
              <span>{activeRunStatusText.detail}</span>
            </div>
          </div>
        ) : null}
      </section>
    );
  };

  const renderAgentListPane = () => {
    const activeConversations = conversationsByAgent[activeAgent];
    const normalizedSearchQuery = agentSearchQuery.trim().toLowerCase();
    const filteredConversations = activeConversations.filter((conversation) => {
      const statusMatches =
        agentListFilter === "all"
        || (agentListFilter === "running" && ["running", "active", "queued"].includes(conversation.status))
        || (agentListFilter === "waiting" && conversation.status === "waiting_human")
        || (agentListFilter === "done" && conversation.status === "completed")
        || (agentListFilter === "failed" && (conversation.status === "failed" || conversation.status === "blocked"));
      if (!statusMatches) {
        return false;
      }
      if (!normalizedSearchQuery) {
        return true;
      }
      return [
        conversation.title,
        conversation.preview ?? "",
        conversation.id,
        conversation.refId ?? "",
      ].some((value) => value.toLowerCase().includes(normalizedSearchQuery));
    });
    const statusFilters = [
      { key: "all", label: copy("All", "全部"), count: activeConversations.length },
      { key: "running", label: copy("Running", "进行中"), count: activeConversations.filter((item) => ["running", "active", "queued"].includes(item.status)).length },
      { key: "waiting", label: copy("Waiting", "待确认"), count: activeConversations.filter((item) => item.status === "waiting_human").length },
      { key: "done", label: copy("Done", "已完成"), count: activeConversations.filter((item) => item.status === "completed").length },
      { key: "failed", label: copy("Failed", "失败"), count: activeConversations.filter((item) => item.status === "failed" || item.status === "blocked").length },
    ];

    return (
      <>
        <div className="agent-management-list__title-row">
          <h3>{copy("Session list", "会话列表")}</h3>
          <button
            type="button"
            onClick={() => {
              if (activeAgent === "assistant") {
                createDraftConversation("assistant");
                return;
              }
              focusAgent("autonomous", "runs");
              setAutonomousGoalDraft(autonomousGoalDraftTemplate(autonomousDefaultGoalTemplate));
            }}
          >
            + {copy("New", "新建")}
          </button>
        </div>

        <div className="agent-management-list__agent-tabs">
          {(["autonomous", "assistant"] as AgentKind[]).map((kind) => (
            <button
              key={kind}
              type="button"
              data-active={kind === activeAgent}
              onClick={() => focusAgent(kind, activePanel)}
            >
              {kind === "assistant" ? copy("Normal Agent", "普通 Agent") : copy("Automation Agent", "自动化招聘 Agent")}
            </button>
          ))}
        </div>

        <div className="agent-management-list__filters">
          {statusFilters.map((filter) => (
            <button
              key={filter.key}
              type="button"
              data-active={filter.key === agentListFilter}
              onClick={() => setAgentListFilter(filter.key as AgentListFilter)}
            >
              {filter.label} <span>{filter.count}</span>
            </button>
          ))}
        </div>

        <div className="agent-management-list__cards">
          {filteredConversations.map((conversation) => (
            <button
              key={conversation.id}
              type="button"
              className="agent-management-list__card"
              data-active={conversation.id === activeConversationId}
              data-status={conversation.status}
              onClick={() => {
                focusAgent(activeAgent, "conversation");
                setSelectedConversation((current) => ({
                  ...current,
                  [activeAgent]: conversation.id,
                }));
              }}
            >
              <div className="agent-management-list__card-main">
                <span className="agent-management-list__bot" aria-hidden="true">●</span>
                <div>
                  <strong>{normalizeAgentTitle(activeAgent, conversation.title)}</strong>
                  <span>{copy("Instance ID", "实例 ID")}：{conversation.refId || conversation.id}</span>
                </div>
              </div>
              <StatusBadge tone={toneForRunStatus(conversation.status)}>{describeConversationStatus(conversation.status)}</StatusBadge>
              <p>{describeConversationPreview(conversation)}</p>
              <div className="agent-management-list__meta">
                <span>{copy("Updated", "更新于")} {formatDateTime(conversation.updatedAt)}</span>
                {conversation.unreadCount > 0 ? <span>{copy("Unread", "未读")} {conversation.unreadCount}</span> : null}
              </div>
            </button>
          ))}
          {!filteredConversations.length ? (
            <div className="agent-management-list__empty">{copy("No sessions yet", "还没有实例")}</div>
          ) : null}
        </div>
      </>
    );
  };

  const renderTimelineApprovalAttachment = useCallback(
    (message: AgentConversationMessage): React.ReactNode => {
      const matches = (activeWorkspace?.approvals ?? [])
        .filter((approval) => approvalMatchesTimelineMessage(approval, message))
        .sort((left, right) => {
          if (left.status === "pending" && right.status !== "pending") {
            return -1;
          }
          if (right.status === "pending" && left.status !== "pending") {
            return 1;
          }
          return (
            parseConversationSortTime(right.updatedAt ?? right.reviewedAt ?? right.createdAt) -
            parseConversationSortTime(left.updatedAt ?? left.reviewedAt ?? left.createdAt)
          );
        });
      const approval = matches[0] ?? null;
      if (!approval) {
        return null;
      }

      const options = approvalOptionsFor(approval, copy);
      const selected = approvalSelections[approval.id] ?? options[0]?.key;
      const isBusy = approvalActionId === approval.id;
      const resolvedAt = approval.reviewedAt ?? approval.updatedAt ?? approval.createdAt;

      if (approval.status !== "pending") {
        return (
          <section className="agent-inline-approval agent-inline-approval--resolved" data-status={approval.status}>
            <div className="agent-inline-approval__head">
              <div>
                <strong>{cleanApprovalTitle(approval)}</strong>
                <span>{formatDateTime(resolvedAt)}</span>
              </div>
              <StatusBadge tone={approvalStatusTone(approval.status)}>{approvalStatusLabel(approval.status, copy)}</StatusBadge>
            </div>
            <p>{approval.notes || describeApprovalIntent(approval, copy)}</p>
          </section>
        );
      }

      return (
        <section className="agent-inline-approval" data-pending={isBusy ? "true" : undefined}>
          <div className="agent-inline-approval__head">
            <div>
              <strong>{cleanApprovalTitle(approval)}</strong>
              <span>{copy("Requested by", "发起方")}：{approval.requester}</span>
            </div>
            <StatusBadge tone="warning">{approvalStatusLabel(approval.status, copy)}</StatusBadge>
          </div>
          <p>{describeApprovalIntent(approval, copy)}</p>
          <div className="agent-inline-approval__options">
            {options.map((option) => (
              <label key={option.key} data-active={option.key === selected}>
                <input
                  type="radio"
                  name={`approval-${approval.id}`}
                  checked={option.key === selected}
                  onChange={() =>
                    setApprovalSelections((current) => ({
                      ...current,
                      [approval.id]: option.key,
                    }))
                  }
                />
                <span>{option.label}</span>
                <small>{option.description}</small>
              </label>
            ))}
          </div>
          <FormTextarea
            value={approvalNotes[approval.id] ?? ""}
            onChange={(event) =>
              setApprovalNotes((current) => ({
                ...current,
                [approval.id]: event.target.value,
              }))
            }
            placeholder={copy("Optional execution constraint or rejection reason…", "输入补充要求，例如：只处理高优先级候选人，或先预览影响范围…")}
          />
          <div className="agent-inline-approval__actions">
            <button type="button" onClick={() => void handleApprovalAction(approval, "approve")} disabled={isBusy}>
              {copy("Continue", "确认执行")}
            </button>
            <button type="button" onClick={() => void handleApprovalAction(approval, "reject")} disabled={isBusy}>
              {copy("Reject", "拒绝")}
            </button>
          </div>
        </section>
      );
    },
    [activeWorkspace?.approvals, approvalActionId, approvalNotes, approvalSelections, copy],
  );

  const renderPanelContent = () => {
    if (activePanel === "conversation") {
      return (
        <div className="chat-stream chat-stream--management">
          {pageMode ? null : renderAgentCommandCenter()}
          <ChatMessageStream
            loading={loadingWorkspace || loadingConversation}
            messages={activeConversation?.messages ?? []}
            renderTimelineAttachment={pageMode ? renderTimelineApprovalAttachment : undefined}
            variant={pageMode ? "timeline" : "cards"}
          />
        </div>
      );
    }

    if (!activeWorkspace) {
      return renderEmptyPanel(copy("Loading…", "加载中…"), copy("The overlay is still waiting for workspace data.", "Overlay 仍在等待工作区数据。"));
    }

    switch (activePanel) {
      case "config":
        return renderConfigPanel();
      case "runs":
        return renderRunsPanel(activeWorkspace.runs);
      case "memory":
        return renderMemoryPanel(activeWorkspace.memories);
      case "skills":
        return renderSkillsPanel(activeWorkspace.skills);
      case "tools":
        return renderToolsPanel(activeWorkspace.tools, sceneTemplates);
      default:
        return null;
    }
  };

  if (!visible) {
    return <></>;
  }

  return (
    <div className={pageMode ? "agent-management-page" : "chat-overlay-shell"}>
      <section className={pageMode ? "agent-management-surface" : "chat-overlay chat-overlay--drawer"}>
        {pageMode ? (
          <header className="agent-management-topbar">
            <label>
              <span>{copy("Agent type", "Agent 类型")}</span>
              <select value={activeAgent} onChange={(event) => focusAgent(event.target.value as AgentKind, activePanel)}>
                <option value="autonomous">{copy("Automation recruiting Agent", "自动化招聘 Agent")}</option>
                <option value="assistant">{copy("Normal Agent", "普通 Agent")}</option>
              </select>
            </label>
            <label>
              <span>{copy("Instance/status", "实例/状态")}</span>
              <select value="all" onChange={() => undefined}>
                <option value="all">{copy("All instances", "全部实例")}</option>
              </select>
            </label>
            <label>
              <span>{copy("Status", "状态")}</span>
              <select value={agentListFilter} onChange={(event) => setAgentListFilter(event.target.value as AgentListFilter)}>
                <option value="all">{copy("All", "全部")}</option>
                <option value="running">{copy("Running", "运行中")}</option>
                <option value="waiting">{copy("Waiting", "待确认")}</option>
                <option value="done">{copy("Done", "已完成")}</option>
                <option value="failed">{copy("Failed", "失败")}</option>
              </select>
            </label>
            <label>
              <span>{copy("Time range", "时间范围")}</span>
              <select value="all" onChange={() => undefined}>
                <option value="all">{copy("All", "全部")}</option>
              </select>
            </label>
            <div className="agent-management-search">
              <span aria-hidden="true">⌕</span>
              <input
                value={agentSearchQuery}
                onChange={(event) => setAgentSearchQuery(event.target.value)}
                placeholder={copy("Search sessions, task ID, candidate, or action", "搜索会话、任务 ID、候选人或操作")}
              />
            </div>
            <button type="button" className="agent-management-icon-button" onClick={() => void loadWorkspaces()}>
              ↻
            </button>
          </header>
        ) : (
          <header className="chat-overlay__header">
            <div className="chat-overlay__brand">
              <span className="chat-overlay__logo">AG</span>
              <div>
                <div className="chat-overlay__eyebrow">{agentDisplayName(activeAgent)} · {agentModeLabel(activeAgent)}</div>
                <div className="chat-overlay__title">
                  {copy("Agent management", "Agent 管理")}
                </div>
              </div>
            </div>
            <div className="chat-overlay__header-actions">
              {transport !== "http" ? <StatusBadge tone="critical">{copy("offline", "离线")}</StatusBadge> : null}
              {(["assistant", "autonomous"] as AgentKind[]).map((kind) => (
                <button
                  key={kind}
                  type="button"
                  className="chat-overlay__header-button"
                  data-active={kind === activeAgent}
                  onClick={() => focusAgent(kind, activePanel)}
                >
                  {kind === "assistant" ? "Assistant" : "Automation"}
                </button>
              ))}
              <button type="button" className="chat-overlay__header-button" onClick={() => setRailCollapsed((current) => !current)}>
                {railCollapsed ? copy("Show rail", "展开侧栏") : copy("Hide rail", "收起侧栏")}
              </button>
              <button type="button" className="chat-overlay__header-button" onClick={close}>
                {copy("Close", "关闭")}
              </button>
            </div>
          </header>
        )}

        <div className={pageMode ? "agent-management-layout" : "chat-overlay__body"}>
          <aside className={pageMode ? "agent-management-list-pane" : "chat-overlay__sidebar"}>
            {pageMode ? renderAgentListPane() : (
              <>
                <button
                  type="button"
                  className="chat-overlay__new"
                  onClick={() => {
                    if (activeAgent === "assistant") {
                      createDraftConversation("assistant");
                      return;
                    }
                    focusAgent("autonomous", "runs");
                    setAutonomousGoalDraft(autonomousGoalDraftTemplate(autonomousDefaultGoalTemplate));
                  }}
                >
                  + {activeAgent === "assistant" ? copy("New session", "新会话") : copy("New automation task", "新自动化任务")}
                </button>

            {(["assistant", "autonomous"] as AgentKind[]).map((kind) => {
              const groupSummary = summarizeConversationGroup(conversationsByAgent[kind]);
              return (
                <section key={kind} className="chat-overlay__section" data-agent-kind={kind}>
                  <button
                    type="button"
                    className="chat-overlay__section-header"
                    data-active={kind === activeAgent}
                    data-agent-kind={kind}
                    onClick={() => toggleConversationGroup(kind)}
                  >
                    <span className="chat-overlay__section-header-main">
                      <span className="chat-overlay__section-caret" data-collapsed={collapsedGroups[kind] ? "true" : "false"}>
                        ▾
                      </span>
                      <span className="chat-overlay__section-copy">
                        <span className="chat-overlay__section-label">
                          {kind === "assistant" ? copy("Assistant", "Assistant") : copy("Automation", "Automation")}
                        </span>
                        <span className="chat-overlay__section-summary">{groupSummary.summary}</span>
                      </span>
                    </span>
                    <span className="chat-overlay__section-header-side">
                      <StatusBadge tone={groupSummary.tone}>{conversationsByAgent[kind].length}</StatusBadge>
                    </span>
                  </button>
                  {!collapsedGroups[kind] ? (
                    <div className="chat-overlay__conversation-list" data-agent-kind={kind}>
                      {conversationsByAgent[kind].map((conversation) => (
                        <button
                          key={conversation.id}
                          type="button"
                          className="chat-overlay__conversation-item"
                          data-active={kind === activeAgent && conversation.id === activeConversationId}
                          data-agent-kind={kind}
                          data-status={conversation.status}
                          onClick={() => {
                            focusAgent(kind, "conversation");
                            setSelectedConversation((current) => ({
                              ...current,
                              [kind]: conversation.id,
                            }));
                          }}
                        >
                          <div className="chat-overlay__conversation-row">
                            <div className="chat-overlay__conversation-title">{normalizeAgentTitle(kind, conversation.title)}</div>
                            <StatusBadge tone={toneForRunStatus(conversation.status)}>
                              {describeConversationStatus(conversation.status)}
                            </StatusBadge>
                          </div>
                          <div className="chat-overlay__conversation-meta">
                            <span>{copy("Updated", "最近更新")} · {formatDateTime(conversation.updatedAt)}</span>
                            {conversation.unreadCount > 0 ? (
                              <span>{copy("Unread", "未读")} · {conversation.unreadCount}</span>
                            ) : null}
                          </div>
                          <div className="chat-overlay__conversation-preview">{describeConversationPreview(conversation)}</div>
                        </button>
                      ))}
                      {!conversationsByAgent[kind].length ? (
                        <div className="chat-empty-inline">{copy("No sessions yet", "还没有会话")}</div>
                      ) : null}
                    </div>
                  ) : null}
                </section>
              );
            })}
              </>
            )}
          </aside>

          <main className={pageMode ? "agent-management-main-pane" : "chat-overlay__main"}>
            {pageMode ? (
              <div className="agent-management-task-head">
                <div>
                  <div className="agent-management-task-head__title-row">
                    <h2>{activeConversationSummary ? normalizeAgentTitle(activeAgent, activeConversationSummary.title) : agentDisplayName(activeAgent)}</h2>
                    <StatusBadge tone={toneForRunStatus(activeConversationSummary?.status ?? activeWorkspace?.agent.status ?? "idle")}>
                      {describeConversationStatus(activeConversationSummary?.status ?? activeWorkspace?.agent.status ?? "idle")}
                    </StatusBadge>
                    {activeAgent === "autonomous" ? <span className="agent-management-priority">高优先级</span> : null}
                  </div>
                  <div className="agent-management-task-head__meta">
                    <span>{copy("Task ID", "任务 ID")}：{activeConversationSummary?.refId || activeConversationId || "-"}</span>
                    <span>{copy("Owner", "创建人")}：张晨曦</span>
                    <span>{copy("Updated", "更新于")}：{activeConversationSummary ? formatDateTime(activeConversationSummary.updatedAt) : "-"}</span>
                  </div>
                </div>
                <div className="agent-management-task-head__actions">
                  <button type="button" onClick={() => setActivePanel("conversation")}>▦</button>
                  <button type="button" onClick={() => setActivePanel("runs")}>{copy("View flow", "查看流程图")}</button>
                  <button type="button" onClick={() => setActivePanel("tools")}>{copy("More", "更多操作")}⌄</button>
                </div>
              </div>
            ) : null}
            <div className="chat-overlay__tabs">
              {panelItems.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  className="chat-overlay__tab"
                  data-active={item.key === activePanel}
                  onClick={() => setActivePanel(item.key)}
                >
                  {item.label}
                </button>
              ))}
            </div>

            {!pageMode && activeWorkspace && activeRunStatusText && shouldShowRunStatusStrip ? (
              <section className="chat-overlay__status-strip">
                <div className="chat-overlay__status-strip-head">
                  <StatusBadge tone={activeRunStatusText.tone}>{activeRunStatusText.badgeLabel}</StatusBadge>
                  <span>{activeRunStatusText.title}</span>
                </div>
                <div className="chat-overlay__status-strip-body">{activeRunStatusText.detail}</div>
                {activeRunStatusText.metrics.length ? (
                  <div className="chat-overlay__status-strip-meta">
                    {activeRunStatusText.metrics.map((metric) => (
                      <span key={metric} className="chat-overlay__status-chip">
                        {metric}
                      </span>
                    ))}
                  </div>
                ) : null}
              </section>
            ) : null}

            {errorMessage ? <div className="chat-overlay__error">{errorMessage}</div> : null}
            {panelNotice?.panel === activePanel ? <div style={noticeStyle(panelNotice.tone)}>{panelNotice.message}</div> : null}

            <div ref={streamShellRef} className="chat-overlay__stream-shell" onScroll={handleStreamScroll}>
              {renderPanelContent()}
            </div>

            {activePanel === "conversation" ? (
              <ChatComposer
                agentKind={activeAgent}
                inputDisabled={sending || loadingWorkspace || (autonomousStartBlocked && !autonomousDraftEditable)}
                submitDisabled={sending || loadingWorkspace || (activeAgent === "autonomous" && autonomousStartBlocked)}
                modelLabel={activeWorkspace?.config.modelLabel ?? activeWorkspace?.agent.defaultModel}
                contextLabel={
                  activeAgent === "autonomous"
                    ? copy("Automation task", "自动化任务")
                    : copy("Workspace context", "工作区上下文")
                }
                submitLabel={
                  activeAgent === "autonomous"
                    ? autonomousStartBlocked
                      ? copy("Running…", "已有运行中")
                      : copy("Start", "启动")
                    : copy("Send", "发送")
                }
                value={composerInputValue}
                onChange={handleComposerChange}
                onSubmit={() => void handleSubmit()}
              />
            ) : null}
          </main>

          {!railCollapsed ? <aside className={pageMode ? "agent-management-runtime-pane" : "chat-overlay__rail"}>{renderRailContent()}</aside> : null}
        </div>
      </section>

      {!pageMode && workspaceAgent.status === "waiting_human" ? (
        <div className="chat-overlay__toast">{copy("Agent is waiting for desktop approval.", "Agent 正在等待桌面审批。")}</div>
      ) : null}
    </div>
  );
}
