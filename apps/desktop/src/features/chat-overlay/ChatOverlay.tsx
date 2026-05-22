import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  FormCheckbox,
  FormInput,
  FormTextarea,
  PageToolbar,
  PageToolbarGroup,
  StatusBadge,
  ToolbarButton,
  ToolbarInput,
} from "../../components";
import { apiClient } from "../../lib/api";
import { formatDateTime } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import type {
  AgentConversationMessage,
  AgentConversationRecord,
  AgentConversationSummary,
  AgentKind,
  AgentMemorySummary,
  McpServerRecord,
  AgentRunRecord,
  AgentSnapshot,
  AgentToolSummary,
  AgentWorkspaceRecord,
  ApprovalItem,
  AutonomousRunStartRequest,
  AssistantTurnStreamEvent,
  ChatOverlayPanelKey,
  JobDescriptionSummaryRecord,
  RecruitingPolicyConfig,
  SettingsSnapshot,
  SkillRecord,
} from "../../lib/types";
import { ChatComposer, type ChatComposerCommand } from "./ChatComposer";
import { useChatOverlay } from "./ChatOverlayContext";
import { ChatMessageStream } from "./ChatMessageStream";

interface ChatOverlayProps {
  transport: "http" | "offline";
  workspaceAgent: AgentSnapshot;
  jobDescriptions?: JobDescriptionSummaryRecord[];
  variant?: "overlay" | "page";
}

type PanelNoticeTone = "info" | "success" | "error";
type AgentListFilter = "all" | "running" | "waiting" | "done" | "failed";
type AgentRailTab = "details" | "businessActions";
type BusinessActionFilter =
  | "all"
  | "jd"
  | "candidate"
  | "resume"
  | "communication"
  | "application"
  | "evaluation"
  | "sync"
  | "approval"
  | "state";
type CapabilityCategoryKey = "business" | "system" | "skills" | "mcp" | "memory";
type CapabilityItemKind = "tool" | "skill" | "memory" | "mcp";
type AgentConfigSectionKey =
  | "identity"
  | "responsibilities"
  | "boundaries"
  | "tools"
  | "memory"
  | "output"
  | "governance"
  | "basePrompt";

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
  identityStatement: string;
  dutiesText: string;
  successCriteriaText: string;
  boundariesText: string;
  toolScopeJson: string;
  permissionPolicyJson: string;
  outputPolicyJson: string;
  budgetPolicyJson: string;
  modelConfigJson: string;
  contextPolicyJson: string;
  memoryPolicyJson: string;
  scoringRubric: string;
  recruitingPolicy: RecruitingPolicyDraft;
}

interface CapabilityItem {
  key: string;
  kind: CapabilityItemKind;
  category: CapabilityCategoryKey;
  label: string;
  description: string;
  metaLabel: string;
  meta: string;
  status: string;
  tone: "positive" | "neutral" | "warning" | "critical";
  tool?: AgentToolSummary;
  skill?: SkillRecord;
  memory?: AgentMemorySummary;
  mcp?: McpServerRecord;
}

interface BusinessActionTimelineItem {
  key: string;
  category: "jd" | "candidate" | "resume" | "communication" | "application" | "evaluation" | "sync" | "approval" | "state";
  label: string;
  title: string;
  detail: string;
  time: string;
  status: "running" | "success" | "warning" | "error" | "neutral";
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

type AutomationToolApprovalMode = "auto" | "approval";
type AutomationConfigPageKey = "entry" | "jd" | "sop" | "activation" | "tools" | "base";
const AGENT_KINDS: AgentKind[] = ["jd_sync", "autonomous", "assistant"];

function isRuntimeAgentKind(kind: AgentKind): boolean {
  return kind === "autonomous" || kind === "jd_sync";
}

interface AutomationJobStrategyDraft {
  screeningCriteria: string;
  onlineResumeCriteria: string;
  offlineResumeCriteria: string;
  compositeScoring: string;
  manualReviewRules: string;
  onlineResumePass: string;
  offlineResumePass: string;
  compositePass: string;
  manualReviewMin: string;
}

interface AutomationExecutionSopDraft {
  siteEntryUrl: string;
  siteAccessRulesText: string;
  stepsText: string;
  stopRulesText: string;
}

interface AutomationActivationPolicyDraft {
  manualStartEnabled: boolean;
  scheduledScanEnabled: boolean;
  scanIntervalMinutes: string;
  jdPoolGapEnabled: boolean;
  candidatePoolTarget: string;
  externalEventWakeEnabled: boolean;
  backlogWakeEnabled: boolean;
  backlogThreshold: string;
  stopOnJdOffline: boolean;
  pauseOnLoginRequired: boolean;
  pauseOnEntryUnavailable: boolean;
  pauseOnApprovalPending: boolean;
  pauseOnNoProgress: boolean;
  priorityDiscoveryWeight: string;
  priorityUnreadMessageWeight: string;
  priorityScoringBacklogWeight: string;
  priorityApprovalWeight: string;
  priorityJdGapWeight: string;
  messageSlaMinutes: string;
  siteCooldownMinutes: string;
  retryCooldownMinutes: string;
  maxActionsPerHour: string;
  maxConsecutiveErrors: string;
}

type AutomationActivationBooleanField = {
  [K in keyof AutomationActivationPolicyDraft]: AutomationActivationPolicyDraft[K] extends boolean ? K : never;
}[keyof AutomationActivationPolicyDraft];

type AutomationActivationNumberField = {
  [K in keyof AutomationActivationPolicyDraft]: AutomationActivationPolicyDraft[K] extends string ? K : never;
}[keyof AutomationActivationPolicyDraft];

interface AutomationResumePolicyDraft {
  resumeSourcesText: string;
  runtimeInputPreviewText: string;
}

interface AutomationSyncPolicyDraft {
  jdSyncText: string;
  imSyncText: string;
  resumeContactSyncText: string;
}

interface AutomationConfigDraft {
  selectedRunJobIds: string[];
  jobStrategies: Record<string, AutomationJobStrategyDraft>;
  executionSop: AutomationExecutionSopDraft;
  activationPolicy: AutomationActivationPolicyDraft;
  resumePolicy: AutomationResumePolicyDraft;
  syncPolicy: AutomationSyncPolicyDraft;
  toolApprovalModes: Record<string, AutomationToolApprovalMode>;
}

interface BaseCapabilityRow {
  label: string;
  detail: string;
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
  { key: "conversation", label: "工作区" },
  { key: "config", label: "配置" },
  { key: "capabilities", label: "能力" },
  { key: "outputs", label: "工作产出" },
  { key: "runs", label: "运行记录" },
];

const assistantUserId = "desktop-user";

function agentDisplayName(kind: AgentKind): string {
  if (kind === "assistant") {
    return "AI助手";
  }
  return kind === "jd_sync" ? "JD 同步" : "自动化招聘";
}

function agentTabLabel(kind: AgentKind): string {
  return agentDisplayName(kind);
}

function normalizeAgentTitle(kind: AgentKind, title: string | null | undefined): string {
  const trimmed = title?.trim();
  if (kind !== "assistant" && (!trimmed || /^autonomous agent$/i.test(trimmed) || /^autonomous$/i.test(trimmed) || /^jd sync$/i.test(trimmed))) {
    return agentDisplayName(kind);
  }
  return trimmed || agentDisplayName(kind);
}

function agentModeLabel(kind: AgentKind): string {
  if (kind === "assistant") {
    return "对话触发";
  }
  return kind === "jd_sync" ? "手动同步" : "事件/调度触发";
}

function agentModeSummary(kind: AgentKind): string {
  return kind === "assistant"
    ? "由用户消息驱动，适合解释、检索、局部操作和人工协作。"
    : kind === "jd_sync"
      ? "由人工手动启动，专门同步招聘网站 JD，不处理候选人。"
    : "由外部事件、定时调度或手工创建的自动化运行驱动，适合后台持续推进招聘流程。";
}

function workspaceTemplate(): Record<AgentKind, AgentWorkspaceRecord | null> {
  return {
    assistant: null,
    autonomous: null,
    jd_sync: null,
  };
}

function conversationTemplate(): Record<AgentKind, string | undefined> {
  return {
    assistant: undefined,
    autonomous: undefined,
    jd_sync: undefined,
  };
}

function localConversationTemplate(): Record<AgentKind, AgentConversationSummary[]> {
  return {
    assistant: [],
    autonomous: [],
    jd_sync: [],
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

function isClearConversationCommand(value: string): boolean {
  const normalized = value.trim().toLowerCase();
  return normalized === "clear" || normalized === "/clear";
}

function slashCommandQuery(value: string): string | null {
  const trimmed = value.trimStart();
  if (!trimmed.startsWith("/") || trimmed.includes("\n")) {
    return null;
  }
  const command = trimmed.slice(1);
  if (/\s/.test(command)) {
    return null;
  }
  return command.toLowerCase();
}

function slashCommandMatches(command: ChatComposerCommand, query: string): boolean {
  return !query
    || command.command.toLowerCase().startsWith(query)
    || command.title.toLowerCase().includes(query)
    || command.description.toLowerCase().includes(query);
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

function nullableNumberConfigValue(value: string): number | null {
  const numeric = Number.parseFloat(value);
  return Number.isFinite(numeric) ? numeric : null;
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

const DEFAULT_AUTOMATION_RESUME_SOURCES = [
  "当前运行进度、最近一次已完成动作和下一步待办。",
  "选中 JD 的招聘目标、硬性要求、候选人池水位和下架状态。",
  "候选人的在线简历、离线简历、沟通记录、联系方式和评分记录。",
  "已提交但未处理的人工审批、待补材料和异常阻塞。",
  "最近同步到的新消息、新简历、新联系方式和外部状态变化。",
].join("\n");

const DEFAULT_AUTOMATION_RUNTIME_INPUT_PREVIEW = [
  "恢复后先核对上次动作是否已经写入业务记录，避免重复外联、重复归档或重复推进状态。",
  "继续执行前必须确认当前 JD 仍启用、候选人未被淘汰、审批未被拒绝。",
  "恢复摘要需要说明本轮为什么继续、继续处理哪个 JD/候选人、预计产出和阻塞条件。",
].join("\n");

const DEFAULT_AUTOMATION_SOP_PROMPT = [
  "你是自动化招聘 Agent。每次运行必须围绕已选 JD、已配置招聘网站目标网页 URL、JD 策略、评分标准、工具权限和人工审批规则执行，不得让临时用户说明覆盖这些业务策略。",
  "",
  "目标网页与浏览器会话：",
  "- 从配置的招聘网站目标网页 URL 出发，并复用人工提前登录好的浏览器会话；目标网页可以是该网站任意可访问页面。",
  "- 不处理登录、验证码、账号切换、绕过风控或新建账号；遇到这些情况立即暂停并交给人工。",
  "- 站点页面、字段、按钮、路径和正确业务页面必须以当前页面可见证据为准，不依赖产品代码内置的站点专属选择器或解析器。",
  "",
  "执行流程：",
  "- 确认本次运行启用的 JD、候选人目标数量与对应策略版本。",
  "- 根据页面可见导航进入职位或候选人页面，按 JD 策略发现候选人，先写入候选人事实与来源证据。",
  "- 完成在线简历事实采集，并按在线简历评分标准给出阶段结论。",
  "- 对在线通过或需复核的候选人索取离线简历，附件到位后按离线简历标准评分。",
  "- 汇总 JD 匹配、在线简历、离线简历、沟通证据和风险项，形成综合评分与建议动作。",
  "",
  "恢复、同步与停止：",
  "- 恢复后先核对上次动作是否已经写入业务记录，避免重复外联、重复归档或重复推进状态。",
  "- 同步新消息、简历附件、联系方式和状态变化，并保留证据来源。",
  "- JD 被下架、候选人缺少关键证据、目标网页不可访问、页面证据不足、触发审批节点或无可推进动作时，暂停并交给人工。",
].join("\n");

function automationConfigDraftTemplate(): AutomationConfigDraft {
  return {
    selectedRunJobIds: [],
    jobStrategies: {},
    executionSop: {
      siteEntryUrl: "",
      siteAccessRulesText: [
        "从配置的招聘网站目标网页出发，并复用当前已登录浏览器会话；目标网页可以是该网站任意可访问页面。",
        "登录、验证码、账号切换和风控处理都由人工提前完成；Agent 不处理这些环节。",
        "需要进入职位列表、候选人列表、候选人详情、消息或简历页面时，由 Agent 根据页面可见导航和内容自行判断。",
        "站点字段、页面名称和导航路径可由 Agent 观察判断；不得依赖产品代码内置的站点专属选择器或解析器。",
      ].join("\n"),
      stepsText: DEFAULT_AUTOMATION_SOP_PROMPT,
      stopRulesText: "",
    },
    activationPolicy: {
      manualStartEnabled: true,
      scheduledScanEnabled: true,
      scanIntervalMinutes: "30",
      jdPoolGapEnabled: true,
      candidatePoolTarget: "20",
      externalEventWakeEnabled: true,
      backlogWakeEnabled: true,
      backlogThreshold: "5",
      stopOnJdOffline: true,
      pauseOnLoginRequired: true,
      pauseOnEntryUnavailable: true,
      pauseOnApprovalPending: true,
      pauseOnNoProgress: true,
      priorityDiscoveryWeight: "40",
      priorityUnreadMessageWeight: "55",
      priorityScoringBacklogWeight: "45",
      priorityApprovalWeight: "70",
      priorityJdGapWeight: "2",
      messageSlaMinutes: "60",
      siteCooldownMinutes: "30",
      retryCooldownMinutes: "15",
      maxActionsPerHour: "120",
      maxConsecutiveErrors: "3",
    },
    resumePolicy: {
      resumeSourcesText: DEFAULT_AUTOMATION_RESUME_SOURCES,
      runtimeInputPreviewText: DEFAULT_AUTOMATION_RUNTIME_INPUT_PREVIEW,
    },
    syncPolicy: {
      jdSyncText: "从配置的招聘网站目标网页出发，根据页面可见导航和内容自行找到职位列表与职位详情，识别新增、更新和下架职位，并同步到本地 JD 库；同步过程只处理职位信息，不处理候选人。",
      imSyncText: "IM 消息双向同步：外部新消息写入本系统，本系统 outbound 消息需要同步确认记录。",
      resumeContactSyncText: "离线简历、联系方式、附件和沟通证据必须归档到候选人投递事实中，供评分和恢复上下文使用。",
    },
    toolApprovalModes: {},
  };
}

function automationJobId(job: JobDescriptionSummaryRecord): string | null {
  const id = job.jobDescriptionId?.trim();
  return id || null;
}

function automationJobSubtitle(job: JobDescriptionSummaryRecord): string {
  return [job.companyName, job.department, job.location].filter(Boolean).join(" · ") || job.status || "未标注";
}

function stringFromUnknown(value: unknown, fallback = ""): string {
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(value);
  }
  return fallback;
}

function booleanFromUnknown(value: unknown, fallback = false): boolean {
  if (typeof value === "boolean") {
    return value;
  }
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (["true", "1", "yes", "on"].includes(normalized)) {
      return true;
    }
    if (["false", "0", "no", "off"].includes(normalized)) {
      return false;
    }
  }
  if (typeof value === "number") {
    return value !== 0;
  }
  return fallback;
}

function linesFromText(value: string): string[] {
  return value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
}

function textFromLines(lines: string[]): string {
  return lines.map((line) => line.trim()).filter(Boolean).join("\n");
}

function readableUrlHost(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    return "";
  }
  try {
    const parsed = new URL(/^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`);
    return parsed.hostname || trimmed;
  } catch {
    return trimmed.length > 32 ? `${trimmed.slice(0, 29)}...` : trimmed;
  }
}

function recordField(record: Record<string, unknown>, ...keys: string[]): Record<string, unknown> | undefined {
  for (const key of keys) {
    const value = record[key];
    if (isRecord(value)) {
      return value;
    }
  }
  return undefined;
}

function arrayStringField(record: Record<string, unknown>, ...keys: string[]): string[] {
  for (const key of keys) {
    const value = record[key];
    if (Array.isArray(value)) {
      return value.map(String).filter((item) => item.trim());
    }
  }
  return [];
}

function automationJobStrategyFromRaw(
  raw: Record<string, unknown> | undefined,
): AutomationJobStrategyDraft {
  const record = raw ?? {};
  const resumeScoring = recordField(record, "resumeScoring", "resume_scoring") ?? {};
  const onlineResume = recordField(resumeScoring, "online", "onlineResume", "online_resume") ?? {};
  const offlineResume = recordField(resumeScoring, "offline", "offlineResume", "offline_resume") ?? {};
  const compositeScoring = recordField(record, "compositeScoring", "composite_scoring") ?? {};
  const compositeScoringText = typeof record.compositeScoring === "string"
    ? record.compositeScoring
    : typeof record.composite_scoring === "string"
      ? record.composite_scoring
      : undefined;
  return {
    screeningCriteria: stringFromUnknown(
      record.screeningCriteria ?? record.screening_criteria,
    ),
    onlineResumeCriteria: stringFromUnknown(
      record.onlineResumeCriteria ?? record.online_resume_criteria ?? onlineResume.criteria,
    ),
    offlineResumeCriteria: stringFromUnknown(
      record.offlineResumeCriteria ?? record.offline_resume_criteria ?? offlineResume.criteria,
    ),
    compositeScoring: stringFromUnknown(
      record.compositeScoringText ?? record.composite_scoring_text ?? compositeScoringText ?? compositeScoring.criteria,
    ),
    manualReviewRules: stringFromUnknown(
      record.manualReviewRules ?? record.manual_review_rules,
    ),
    onlineResumePass: stringFromUnknown(record.onlineResumePass ?? record.online_resume_pass ?? onlineResume.passThreshold ?? onlineResume.pass_threshold),
    offlineResumePass: stringFromUnknown(record.offlineResumePass ?? record.offline_resume_pass ?? offlineResume.passThreshold ?? offlineResume.pass_threshold),
    compositePass: stringFromUnknown(record.compositePass ?? record.composite_pass ?? compositeScoring.passThreshold ?? compositeScoring.pass_threshold),
    manualReviewMin: stringFromUnknown(record.manualReviewMin ?? record.manual_review_min ?? compositeScoring.manualReviewMin ?? compositeScoring.manual_review_min),
  };
}

function recommendedAutomationJobStrategy(
  job: JobDescriptionSummaryRecord,
  fallbackPolicy?: RecruitingPolicyConfig,
): AutomationJobStrategyDraft {
  return {
    screeningCriteria: fallbackPolicy?.jdStandards || job.requirements || job.summary || "围绕该 JD 的岗位目标、核心职责、硬性门槛、加分项和排除项筛选候选人；所有判断必须引用 JD 要求或候选人证据。",
    onlineResumeCriteria: fallbackPolicy?.onlineResumeCriteria || "在线简历优先判断 JD 匹配度、最近岗位相关性、核心技能证据、项目深度、稳定性和明显风险；不足以判断时进入补充材料环节。",
    offlineResumeCriteria: fallbackPolicy?.offlineResumeCriteria || "离线简历用于补齐在线资料缺失的信息，重点检查项目细节、影响指标、职责边界、联系方式和时间线一致性。",
    compositeScoring: fallbackPolicy?.compositeScoring || "综合评分基于 JD 匹配、在线简历、离线简历、沟通记录和风险项生成，必须输出维度分、证据引用、通过/淘汰建议和下一步动作。",
    manualReviewRules: fallbackPolicy?.screeningRules || "硬性条件不完整、证据冲突、综合分处于人工复核区间、或涉及关键外联/状态流转时进入人工复核。",
    onlineResumePass: String(fallbackPolicy?.thresholds.onlinePass ?? 70),
    offlineResumePass: String(fallbackPolicy?.thresholds.offlinePass ?? 72),
    compositePass: String(fallbackPolicy?.thresholds.compositePass ?? 75),
    manualReviewMin: String(fallbackPolicy?.thresholds.manualReviewMin ?? 60),
  };
}

function automationConfigDraftFromWorkspace(
  workspace: AgentWorkspaceRecord | null,
  jobs: JobDescriptionSummaryRecord[],
  productKind: "autonomous" | "jd_sync" = "autonomous",
): AutomationConfigDraft {
  const template = automationConfigDraftTemplate();
  const runtimeMetadata = isRecord(workspace?.agentDefinition.config.runtimeMetadata)
    ? workspace?.agentDefinition.config.runtimeMetadata
    : {};
  const productConfig = isRecord(workspace?.agentDefinition.productConfig)
    ? workspace?.agentDefinition.productConfig
    : {};
  const autonomousProductConfig = recordField(productConfig, productKind) ?? {};
  const rawConfig =
    recordField(
      autonomousProductConfig,
      productKind === "jd_sync" ? "jdSyncConfig" : "automationRecruitingConfig",
      productKind === "jd_sync" ? "jd_sync_config" : "automation_recruiting_config",
      "automationConfig",
      "automation_config",
    ) ??
    recordField(runtimeMetadata, "automationRecruitingConfig", "automation_recruiting_config", "automationConfig") ??
    {};
  const rawSop = recordField(rawConfig, "executionSop", "execution_sop") ?? {};
  const rawActivation = recordField(rawConfig, "activationPolicy", "activation_policy") ?? {};
  const rawResume = recordField(rawConfig, "resumePolicy", "resume_policy") ?? {};
  const rawSync = recordField(rawConfig, "syncPolicy", "sync_policy") ?? {};
  const rawStrategies = recordField(rawConfig, "jobStrategies", "job_strategies") ?? {};
  const rawToolPolicy = recordField(rawConfig, "toolApprovalPolicy", "tool_approval_policy") ?? {};
  const rawToolOverrides = recordField(rawToolPolicy, "overrides") ?? {};
  const jobStrategies: Record<string, AutomationJobStrategyDraft> = {};

  jobs.forEach((job) => {
    const id = automationJobId(job);
    if (!id) {
      return;
    }
    const rawStrategy = isRecord(rawStrategies[id]) ? rawStrategies[id] : undefined;
    jobStrategies[id] = automationJobStrategyFromRaw(rawStrategy);
  });

  const knownJobIds = new Set(Object.keys(jobStrategies));
  const configuredSelection = arrayStringField(rawConfig, "defaultRunJobIds", "default_run_job_ids", "selectedRunJobIds", "selected_run_job_ids")
    .filter((id) => knownJobIds.has(id));
  const toolApprovalModes = Object.fromEntries(
    Object.entries(rawToolOverrides).map(([toolId, value]) => [
      toolId,
      value === "approval" ? "approval" : "auto",
    ]),
  ) as Record<string, AutomationToolApprovalMode>;

  return {
    selectedRunJobIds: configuredSelection,
    jobStrategies,
    executionSop: {
      siteEntryUrl: stringFromUnknown(rawSop.siteEntryUrl ?? rawSop.site_entry_url ?? rawSop.entryUrl ?? rawSop.entry_url, template.executionSop.siteEntryUrl),
      siteAccessRulesText: stringFromUnknown(rawSop.siteAccessRulesText ?? rawSop.site_access_rules_text ?? rawSop.siteAccessRules ?? rawSop.site_access_rules, template.executionSop.siteAccessRulesText),
      stepsText: stringFromUnknown(rawSop.stepsText ?? rawSop.steps_text, template.executionSop.stepsText),
      stopRulesText: stringFromUnknown(rawSop.stopRulesText ?? rawSop.stop_rules_text, template.executionSop.stopRulesText),
    },
    activationPolicy: {
      manualStartEnabled: booleanFromUnknown(rawActivation.manualStartEnabled ?? rawActivation.manual_start_enabled, template.activationPolicy.manualStartEnabled),
      scheduledScanEnabled: booleanFromUnknown(rawActivation.scheduledScanEnabled ?? rawActivation.scheduled_scan_enabled, template.activationPolicy.scheduledScanEnabled),
      scanIntervalMinutes: stringFromUnknown(rawActivation.scanIntervalMinutes ?? rawActivation.scan_interval_minutes, template.activationPolicy.scanIntervalMinutes),
      jdPoolGapEnabled: booleanFromUnknown(rawActivation.jdPoolGapEnabled ?? rawActivation.jd_pool_gap_enabled, template.activationPolicy.jdPoolGapEnabled),
      candidatePoolTarget: stringFromUnknown(rawActivation.candidatePoolTarget ?? rawActivation.candidate_pool_target, template.activationPolicy.candidatePoolTarget),
      externalEventWakeEnabled: booleanFromUnknown(rawActivation.externalEventWakeEnabled ?? rawActivation.external_event_wake_enabled, template.activationPolicy.externalEventWakeEnabled),
      backlogWakeEnabled: booleanFromUnknown(rawActivation.backlogWakeEnabled ?? rawActivation.backlog_wake_enabled, template.activationPolicy.backlogWakeEnabled),
      backlogThreshold: stringFromUnknown(rawActivation.backlogThreshold ?? rawActivation.backlog_threshold, template.activationPolicy.backlogThreshold),
      stopOnJdOffline: booleanFromUnknown(rawActivation.stopOnJdOffline ?? rawActivation.stop_on_jd_offline, template.activationPolicy.stopOnJdOffline),
      pauseOnLoginRequired: booleanFromUnknown(rawActivation.pauseOnLoginRequired ?? rawActivation.pause_on_login_required, template.activationPolicy.pauseOnLoginRequired),
      pauseOnEntryUnavailable: booleanFromUnknown(rawActivation.pauseOnEntryUnavailable ?? rawActivation.pause_on_entry_unavailable, template.activationPolicy.pauseOnEntryUnavailable),
      pauseOnApprovalPending: booleanFromUnknown(rawActivation.pauseOnApprovalPending ?? rawActivation.pause_on_approval_pending, template.activationPolicy.pauseOnApprovalPending),
      pauseOnNoProgress: booleanFromUnknown(rawActivation.pauseOnNoProgress ?? rawActivation.pause_on_no_progress, template.activationPolicy.pauseOnNoProgress),
      priorityDiscoveryWeight: stringFromUnknown(rawActivation.priorityDiscoveryWeight ?? rawActivation.priority_discovery_weight, template.activationPolicy.priorityDiscoveryWeight),
      priorityUnreadMessageWeight: stringFromUnknown(rawActivation.priorityUnreadMessageWeight ?? rawActivation.priority_unread_message_weight, template.activationPolicy.priorityUnreadMessageWeight),
      priorityScoringBacklogWeight: stringFromUnknown(rawActivation.priorityScoringBacklogWeight ?? rawActivation.priority_scoring_backlog_weight, template.activationPolicy.priorityScoringBacklogWeight),
      priorityApprovalWeight: stringFromUnknown(rawActivation.priorityApprovalWeight ?? rawActivation.priority_approval_weight, template.activationPolicy.priorityApprovalWeight),
      priorityJdGapWeight: stringFromUnknown(rawActivation.priorityJdGapWeight ?? rawActivation.priority_jd_gap_weight, template.activationPolicy.priorityJdGapWeight),
      messageSlaMinutes: stringFromUnknown(rawActivation.messageSlaMinutes ?? rawActivation.message_sla_minutes, template.activationPolicy.messageSlaMinutes),
      siteCooldownMinutes: stringFromUnknown(rawActivation.siteCooldownMinutes ?? rawActivation.site_cooldown_minutes, template.activationPolicy.siteCooldownMinutes),
      retryCooldownMinutes: stringFromUnknown(rawActivation.retryCooldownMinutes ?? rawActivation.retry_cooldown_minutes, template.activationPolicy.retryCooldownMinutes),
      maxActionsPerHour: stringFromUnknown(rawActivation.maxActionsPerHour ?? rawActivation.max_actions_per_hour, template.activationPolicy.maxActionsPerHour),
      maxConsecutiveErrors: stringFromUnknown(rawActivation.maxConsecutiveErrors ?? rawActivation.max_consecutive_errors, template.activationPolicy.maxConsecutiveErrors),
    },
    resumePolicy: {
      resumeSourcesText: stringFromUnknown(rawResume.resumeSourcesText ?? rawResume.resume_sources_text, template.resumePolicy.resumeSourcesText),
      runtimeInputPreviewText: stringFromUnknown(rawResume.runtimeInputPreviewText ?? rawResume.runtime_input_preview_text, template.resumePolicy.runtimeInputPreviewText),
    },
    syncPolicy: {
      jdSyncText: stringFromUnknown(rawSync.jdSyncText ?? rawSync.jd_sync_text, template.syncPolicy.jdSyncText),
      imSyncText: stringFromUnknown(rawSync.imSyncText ?? rawSync.im_sync_text, template.syncPolicy.imSyncText),
      resumeContactSyncText: stringFromUnknown(rawSync.resumeContactSyncText ?? rawSync.resume_contact_sync_text, template.syncPolicy.resumeContactSyncText),
    },
    toolApprovalModes,
  };
}

function automationConfigPayloadFromDraft(
  draft: AutomationConfigDraft,
  jobs: JobDescriptionSummaryRecord[],
  tools: AgentToolSummary[],
): Record<string, unknown> {
  const knownJobIds = new Set(jobs.map(automationJobId).filter((id): id is string => Boolean(id)));
  const jobStrategies = Object.fromEntries(
    Object.entries(draft.jobStrategies)
      .filter(([jobId]) => knownJobIds.has(jobId))
      .map(([jobId, strategy]) => [
        jobId,
        {
          screeningCriteria: strategy.screeningCriteria,
          resumeScoring: {
            online: {
              criteria: strategy.onlineResumeCriteria,
              passThreshold: nullableNumberConfigValue(strategy.onlineResumePass),
            },
            offline: {
              criteria: strategy.offlineResumeCriteria,
              passThreshold: nullableNumberConfigValue(strategy.offlineResumePass),
            },
          },
          compositeScoring: {
            criteria: strategy.compositeScoring,
            passThreshold: nullableNumberConfigValue(strategy.compositePass),
            manualReviewMin: nullableNumberConfigValue(strategy.manualReviewMin),
          },
          manualReviewRules: strategy.manualReviewRules,
        },
      ]),
  );
  const businessToolIds = new Set(tools.filter((tool) => tool.businessTool).map((tool) => tool.id));
  const overrides = Object.fromEntries(
    Object.entries(draft.toolApprovalModes)
      .filter(([toolId]) => businessToolIds.has(toolId))
      .map(([toolId, mode]) => [toolId, mode]),
  );
  return {
    schemaVersion: 1,
    configKind: "multi_jd_recruiting_agent",
    defaultRunJobIds: draft.selectedRunJobIds.filter((jobId) => knownJobIds.has(jobId)),
    executionSop: {
      siteEntryUrl: draft.executionSop.siteEntryUrl,
      siteAccessRulesText: draft.executionSop.siteAccessRulesText,
      stepsText: draft.executionSop.stepsText,
      stopRulesText: draft.executionSop.stopRulesText,
    },
    activationPolicy: {
      manualStartEnabled: draft.activationPolicy.manualStartEnabled,
      scheduledScanEnabled: draft.activationPolicy.scheduledScanEnabled,
      scanIntervalMinutes: draft.activationPolicy.scanIntervalMinutes,
      jdPoolGapEnabled: draft.activationPolicy.jdPoolGapEnabled,
      candidatePoolTarget: draft.activationPolicy.candidatePoolTarget,
      externalEventWakeEnabled: draft.activationPolicy.externalEventWakeEnabled,
      backlogWakeEnabled: draft.activationPolicy.backlogWakeEnabled,
      backlogThreshold: draft.activationPolicy.backlogThreshold,
      stopOnJdOffline: draft.activationPolicy.stopOnJdOffline,
      pauseOnLoginRequired: draft.activationPolicy.pauseOnLoginRequired,
      pauseOnEntryUnavailable: draft.activationPolicy.pauseOnEntryUnavailable,
      pauseOnApprovalPending: draft.activationPolicy.pauseOnApprovalPending,
      pauseOnNoProgress: draft.activationPolicy.pauseOnNoProgress,
      priorityDiscoveryWeight: draft.activationPolicy.priorityDiscoveryWeight,
      priorityUnreadMessageWeight: draft.activationPolicy.priorityUnreadMessageWeight,
      priorityScoringBacklogWeight: draft.activationPolicy.priorityScoringBacklogWeight,
      priorityApprovalWeight: draft.activationPolicy.priorityApprovalWeight,
      priorityJdGapWeight: draft.activationPolicy.priorityJdGapWeight,
      messageSlaMinutes: draft.activationPolicy.messageSlaMinutes,
      siteCooldownMinutes: draft.activationPolicy.siteCooldownMinutes,
      retryCooldownMinutes: draft.activationPolicy.retryCooldownMinutes,
      maxActionsPerHour: draft.activationPolicy.maxActionsPerHour,
      maxConsecutiveErrors: draft.activationPolicy.maxConsecutiveErrors,
      programmaticAuthority: true,
    },
    resumePolicy: {
      resumeSourcesText: draft.resumePolicy.resumeSourcesText,
      runtimeInputPreviewText: draft.resumePolicy.runtimeInputPreviewText,
      resumeMode: "state_resume_plus_summary_resume",
    },
    syncPolicy: {
      jdSyncText: draft.syncPolicy.jdSyncText,
      imSyncText: draft.syncPolicy.imSyncText,
      resumeContactSyncText: draft.syncPolicy.resumeContactSyncText,
    },
    jobStrategies,
    toolApprovalPolicy: {
      defaultMode: "auto",
      overrides,
      approvalToolIds: Object.entries(overrides)
        .filter(([, mode]) => mode === "approval")
        .map(([toolId]) => toolId),
    },
  };
}

function buildJdSyncLaunchPayload(draft: AutomationConfigDraft): AutonomousRunStartRequest | null {
  const configuredEntryUrl = draft.executionSop.siteEntryUrl.trim();
  if (!configuredEntryUrl) {
    return null;
  }
  return {
    title: "同步招聘站点 JD",
    requestMessage: "同步招聘站点 JD",
    instruction: "同步招聘站点 JD",
    kind: "jd_sync",
    jdId: null,
    candidateCountTarget: null,
    constraints: {
      scope_kind: "global",
      plan_kind: "jd_sync",
      target_recruiting_site: {
        entry_url: configuredEntryUrl,
        access_rules: linesFromText(draft.executionSop.siteAccessRulesText),
      },
      execution_sop: {
        siteEntryUrl: configuredEntryUrl,
        siteAccessRulesText: draft.executionSop.siteAccessRulesText,
      },
      sync_policy: draft.syncPolicy,
    },
    successCriteria: {
      jobDescriptionsSyncedFromObservedSite: true,
      noCandidateScreening: true,
      noCandidateOutreach: true,
    },
    contextHints: {
      launch_plan: {
        plan_kind: "jd_sync",
        targetEntryUrl: configuredEntryUrl,
        nextStepAfterSuccess: "select_synced_jd_and_configure_strategy",
      },
    },
  };
}

function jdSyncConfigPayloadFromDraft(draft: AutomationConfigDraft): Record<string, unknown> {
  return {
    schemaVersion: 1,
    configKind: "job_description_sync_agent",
    executionSop: {
      siteEntryUrl: draft.executionSop.siteEntryUrl,
      siteAccessRulesText: draft.executionSop.siteAccessRulesText,
    },
    syncPolicy: {
      jdSyncText: draft.syncPolicy.jdSyncText,
    },
  };
}

function validateAutomationLaunchReadiness(
  draft: AutomationConfigDraft,
  jobs: JobDescriptionSummaryRecord[],
): string[] {
  const blockers: string[] = [];
  const entryUrl = draft.executionSop.siteEntryUrl.trim();
  if (!entryUrl) {
    blockers.push("配置招聘网站目标网页 URL");
  } else {
    try {
      new URL(entryUrl);
    } catch {
      blockers.push("招聘网站目标网页 URL 必须是有效 URL");
    }
  }
  if (!jobs.length) {
    blockers.push("先同步 JD");
  }
  const jobById = new Map(jobs.map((job) => [automationJobId(job), job] as const).filter((entry): entry is [string, JobDescriptionSummaryRecord] => Boolean(entry[0])));
  const selectedJobs = draft.selectedRunJobIds.filter((jobId) => jobById.has(jobId));
  if (!selectedJobs.length) {
    blockers.push("选择至少一个生效 JD");
  }
  selectedJobs.forEach((jobId) => {
    const strategy = draft.jobStrategies[jobId];
    if (
      !strategy
      || !strategy.screeningCriteria.trim()
      || !strategy.onlineResumeCriteria.trim()
      || !strategy.offlineResumeCriteria.trim()
      || !strategy.compositeScoring.trim()
      || !strategy.manualReviewRules.trim()
      || !strategy.onlineResumePass.trim()
      || !strategy.offlineResumePass.trim()
      || !strategy.compositePass.trim()
      || !strategy.manualReviewMin.trim()
    ) {
      blockers.push(`补全 JD 策略：${jobById.get(jobId)?.title ?? jobId}`);
    }
  });
  if (!draft.executionSop.stepsText.trim()) {
    blockers.push("配置执行 SOP");
  }
  const schedulerFields: Array<[keyof AutomationActivationPolicyDraft, string]> = [
    ["scanIntervalMinutes", "扫描间隔"],
    ["candidatePoolTarget", "候选人池目标"],
    ["backlogThreshold", "积压阈值"],
    ["priorityDiscoveryWeight", "发现候选人权重"],
    ["priorityUnreadMessageWeight", "未读消息权重"],
    ["priorityScoringBacklogWeight", "评分积压权重"],
    ["priorityApprovalWeight", "审批权重"],
    ["priorityJdGapWeight", "JD 缺口系数"],
    ["messageSlaMinutes", "消息 SLA"],
    ["siteCooldownMinutes", "站点冷却"],
    ["retryCooldownMinutes", "重试冷却"],
    ["maxActionsPerHour", "每小时动作上限"],
    ["maxConsecutiveErrors", "连续错误上限"],
  ];
  schedulerFields.forEach(([field, label]) => {
    const value = Number.parseFloat(String(draft.activationPolicy[field] ?? ""));
    if (!Number.isFinite(value) || value < 0) {
      blockers.push(`配置调度规则：${label}`);
    }
  });
  return Array.from(new Set(blockers));
}

function validateJdSyncLaunchReadiness(draft: AutomationConfigDraft): string[] {
  const blockers: string[] = [];
  const entryUrl = draft.executionSop.siteEntryUrl.trim();
  if (!entryUrl) {
    blockers.push("配置招聘网站目标网页 URL");
  } else {
    try {
      new URL(entryUrl);
    } catch {
      blockers.push("招聘网站目标网页 URL 必须是有效 URL");
    }
  }
  if (!draft.syncPolicy.jdSyncText.trim()) {
    blockers.push("配置 JD 同步策略");
  }
  return blockers;
}

function linesFromList(values: string[] | undefined): string {
  return (values ?? []).filter((value) => value.trim()).join("\n");
}

function listFromLines(value: string): string[] {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

function prettyJson(value: Record<string, unknown> | undefined): string {
  if (!value || !Object.keys(value).length) {
    return "{}";
  }
  return JSON.stringify(value, null, 2);
}

function parseJsonRecordDraft(value: string, label: string): { record: Record<string, unknown>; error?: string } {
  const trimmed = value.trim();
  if (!trimmed || trimmed === "{}") {
    return { record: {} };
  }
  try {
    const parsed: unknown = JSON.parse(trimmed);
    if (!isRecord(parsed)) {
      return { record: {}, error: `${label} must be a structured policy object.` };
    }
    return { record: parsed };
  } catch (error) {
    const message = error instanceof Error ? error.message : "Invalid structured policy";
    return { record: {}, error: `${label}: ${message}` };
  }
}

function identityStatementFromConfig(identity: Record<string, unknown> | undefined): string {
  return stringField(identity, "statement", "persona", "role", "description") ?? "";
}

function textFieldFromJsonDraft(value: string, ...keys: string[]): string {
  const parsed = parseJsonRecordDraft(value, "");
  if (parsed.error) {
    return "";
  }
  return stringField(parsed.record, ...keys) ?? "";
}

function jsonDraftReadableSummary(value: string, fallback: string, ...preferredKeys: string[]): string {
  const preferred = textFieldFromJsonDraft(value, ...preferredKeys).trim();
  if (preferred) {
    return preferred;
  }
  const parsed = parseJsonRecordDraft(value, "");
  if (parsed.error) {
    return fallback;
  }
  return metadataSummary(parsed.record, fallback);
}

function firstReadableText(fallback: string, ...values: Array<string | null | undefined>): string {
  for (const value of values) {
    const trimmed = value?.trim();
    if (trimmed) {
      return trimmed;
    }
  }
  return fallback;
}

function updateJsonDraftTextField(value: string, key: string, nextValue: string): string {
  const parsed = parseJsonRecordDraft(value, "");
  return prettyJson({
    ...(parsed.error ? {} : parsed.record),
    [key]: nextValue,
  });
}

function agentConfigDraftTemplate(): Record<AgentKind, AgentConfigDraft> {
  return {
    assistant: {
      systemPrompt: "",
      identityStatement: "",
      dutiesText: "",
      successCriteriaText: "",
      boundariesText: "",
      toolScopeJson: "{}",
      permissionPolicyJson: "{}",
      outputPolicyJson: "{}",
      budgetPolicyJson: "{}",
      modelConfigJson: "{}",
      contextPolicyJson: "{}",
      memoryPolicyJson: "{}",
      scoringRubric: "",
      recruitingPolicy: recruitingPolicyDraftFromConfig(),
    },
    autonomous: {
      systemPrompt: "",
      identityStatement: "",
      dutiesText: "",
      successCriteriaText: "",
      boundariesText: "",
      toolScopeJson: "{}",
      permissionPolicyJson: "{}",
      outputPolicyJson: "{}",
      budgetPolicyJson: "{}",
      modelConfigJson: "{}",
      contextPolicyJson: "{}",
      memoryPolicyJson: "{}",
      scoringRubric: "",
      recruitingPolicy: recruitingPolicyDraftFromConfig(),
    },
    jd_sync: {
      systemPrompt: "",
      identityStatement: "",
      dutiesText: "",
      successCriteriaText: "",
      boundariesText: "",
      toolScopeJson: "{}",
      permissionPolicyJson: "{}",
      outputPolicyJson: "{}",
      budgetPolicyJson: "{}",
      modelConfigJson: "{}",
      contextPolicyJson: "{}",
      memoryPolicyJson: "{}",
      scoringRubric: "",
      recruitingPolicy: recruitingPolicyDraftFromConfig(),
    },
  };
}

function agentConfigDraftFromWorkspace(workspace: AgentWorkspaceRecord | null): AgentConfigDraft {
  const definitionConfig = workspace?.definitionConfig;
  const runtimeMetadata = isRecord(definitionConfig?.runtimeMetadata) ? definitionConfig.runtimeMetadata : {};
  return {
    systemPrompt: definitionConfig?.systemPrompt ?? "",
    identityStatement: identityStatementFromConfig(definitionConfig?.identity),
    dutiesText: linesFromList(definitionConfig?.duties),
    successCriteriaText: linesFromList(definitionConfig?.successCriteria),
    boundariesText: linesFromList(definitionConfig?.boundaries),
    toolScopeJson: prettyJson(definitionConfig?.toolScope),
    permissionPolicyJson: prettyJson(definitionConfig?.permissionPolicy),
    outputPolicyJson: prettyJson(definitionConfig?.outputPolicy),
    budgetPolicyJson: prettyJson(definitionConfig?.budgetPolicy),
    modelConfigJson: prettyJson(definitionConfig?.modelConfig),
    contextPolicyJson: prettyJson(workspace?.productAdapterConfig.contextPolicy ?? (isRecord(runtimeMetadata.contextPolicy) ? runtimeMetadata.contextPolicy : undefined)),
    memoryPolicyJson: prettyJson(workspace?.productAdapterConfig.memoryPolicy ?? (isRecord(runtimeMetadata.memoryPolicy) ? runtimeMetadata.memoryPolicy : undefined)),
    scoringRubric: workspace?.productAdapterConfig.scoringRubric ?? "",
    recruitingPolicy: recruitingPolicyDraftFromConfig(workspace?.productAdapterConfig.recruitingPolicy),
  };
}

function cleanApprovalTitle(approval: ApprovalItem): string {
  return approval.title.replace(/^(Patch|Review|Promote)\s+/i, "").trim() || approval.title;
}

function describeApprovalIntent(approval: ApprovalItem, copy: ReturnType<typeof useI18n>["copy"]): string {
  const summary = typeof approval.payload?.summary === "string" ? approval.payload.summary : "";
  if (approval.targetType === "playbook_patch") {
    return copy(
      "The agent found a repeatable divergence and wants to add a supervised checkpoint before continuing.",
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
      "Reusable run knowledge is ready and needs review.",
      "已生成可复用运行经验，需要确认是否保留。",
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
        label: copy("Keep run knowledge", "保留运行经验"),
        description: copy("Accept this candidate as reusable operating knowledge.", "接受为可复用运行经验。"),
      },
      {
        key: "review",
        label: copy("Review first", "先复核方案"),
        description: copy("Inspect reusable scope and version impact before continuing.", "先查看复用范围和版本影响。"),
      },
      {
        key: "discard",
        label: copy("Do not keep", "不保留"),
        description: copy("Reject this candidate and keep the current operating configuration unchanged.", "拒绝候选，不改变当前运行配置。"),
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

function recordFrom(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

function payloadDataFromMessage(message: AgentConversationMessage): Record<string, unknown> {
  const metadata = recordFrom(message.metadata);
  const payload = recordFrom(metadata.payload);
  return recordFrom(payload.data);
}

function compactBusinessActionText(value: unknown, maxLength = 150): string {
  const raw = typeof value === "string"
    ? value
    : value == null
      ? ""
      : JSON.stringify(value, null, 0);
  const normalized = raw
    .split(/\n+/)
    .map((line) => line.replace(/^[-*]\s+/, "").trim())
    .filter(Boolean)
    .join(" · ");
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength)}...` : normalized;
}

function businessActionStatus(message: AgentConversationMessage): BusinessActionTimelineItem["status"] {
  const source = `${message.status ?? ""} ${message.kind} ${message.title ?? ""} ${message.content}`.toLowerCase();
  const data = payloadDataFromMessage(message);
  if (data.is_error === true || /failed|error|异常|失败/.test(source)) {
    return "error";
  }
  if (/blocked|waiting_human|permission|approval|待审批|等待确认|阻塞/.test(source)) {
    return "warning";
  }
  if (/running|started|调用中|执行中|同步中|下载中/.test(source)) {
    return "running";
  }
  if (/completed|success|ready|done|已完成|完成|成功|已写入|已更新|已发送|已同步/.test(source)) {
    return "success";
  }
  return "neutral";
}

function classifyBusinessActionCategory(source: string): BusinessActionTimelineItem["category"] | null {
  const text = source.toLowerCase();
  if (/approval|permission|waiting_human|human|审批|确认|人工/.test(text)) {
    return "approval";
  }
  if (/score|scor|rank|evaluate|assessment|screen|rubric|pass|reject|评估|评分|筛选|淘汰|通过|复核/.test(text)) {
    return "evaluation";
  }
  if (/resume|cv|attachment|artifact|download|file|pdf|docx|简历|附件|下载|归档/.test(text)) {
    return "resume";
  }
  if (/message|contact|communicat|outbound|email|chat|wecom|phone|send|reply|沟通|联系|外联|消息|发送|回复/.test(text)) {
    return "communication";
  }
  if (/application|apply|submission|delivery|funnel|stage|interview|offer|投递|申请|流程|阶段|面试|录用/.test(text)) {
    return "application";
  }
  if (/candidate|person|talent|profile|sourcing|候选|人才|人选|画像/.test(text)) {
    return "candidate";
  }
  if (/\bjd\b|job_description|job description|position|职位|岗位|招聘需求/.test(text)) {
    return "jd";
  }
  if (/sync|import|export|crawl|collect|同步|导入|采集|抓取/.test(text)) {
    return "sync";
  }
  if (/write|upsert|create|update|delete|archive|state|status|写入|创建|更新|删除|归档|状态/.test(text)) {
    return "state";
  }
  return null;
}

function businessActionLabel(category: BusinessActionTimelineItem["category"], copy: ReturnType<typeof useI18n>["copy"]): string {
  switch (category) {
    case "jd":
      return copy("JD", "JD");
    case "candidate":
      return copy("Candidate", "候选人");
    case "resume":
      return copy("Resume", "简历");
    case "communication":
      return copy("Communication", "沟通");
    case "application":
      return copy("Application", "投递流程");
    case "evaluation":
      return copy("Evaluation", "评估");
    case "sync":
      return copy("Sync", "同步");
    case "approval":
      return copy("Approval", "审批");
    case "state":
      return copy("State", "状态变更");
  }
}

function businessActionFilterLabel(filter: BusinessActionFilter, copy: ReturnType<typeof useI18n>["copy"]): string {
  switch (filter) {
    case "all":
      return copy("All", "全部");
    case "jd":
      return copy("JD", "JD");
    case "candidate":
      return copy("Candidate", "候选人");
    case "resume":
      return copy("Resume", "简历");
    case "communication":
      return copy("Message", "消息");
    case "application":
      return copy("Application", "投递");
    case "evaluation":
      return copy("Evaluation", "评估");
    case "sync":
      return copy("Sync", "同步");
    case "approval":
      return copy("Approval", "审批");
    case "state":
      return copy("State", "状态");
  }
}

function businessActionCategoryMark(category: BusinessActionTimelineItem["category"]): string {
  switch (category) {
    case "jd":
      return "JD";
    case "candidate":
      return "人";
    case "resume":
      return "简";
    case "communication":
      return "信";
    case "application":
      return "投";
    case "evaluation":
      return "评";
    case "sync":
      return "同";
    case "approval":
      return "审";
    case "state":
      return "态";
  }
}

function businessActionStatusLabel(status: BusinessActionTimelineItem["status"], copy: ReturnType<typeof useI18n>["copy"]): string {
  switch (status) {
    case "running":
      return copy("Running", "进行中");
    case "success":
      return copy("Success", "成功");
    case "warning":
      return copy("Needs attention", "需关注");
    case "error":
      return copy("Failed", "失败");
    case "neutral":
      return copy("Recorded", "已记录");
  }
}

function businessActionStatusTone(status: BusinessActionTimelineItem["status"]): "positive" | "neutral" | "warning" | "critical" {
  switch (status) {
    case "success":
      return "positive";
    case "warning":
    case "running":
      return "warning";
    case "error":
      return "critical";
    case "neutral":
      return "neutral";
  }
}

function runPhaseLabel(run: AgentRunRecord, copy: ReturnType<typeof useI18n>["copy"]): string {
  const normalized = run.status.trim().toLowerCase();
  if (normalized === "queued") {
    return copy("Queued, not executed yet", "已排队，尚未执行");
  }
  if (normalized === "running" || normalized === "active") {
    return run.startedAt ? copy("Executing", "执行中") : copy("Waiting for executor", "等待执行器接管");
  }
  if (normalized === "waiting_human") {
    return copy("Waiting for approval", "等待人工审批");
  }
  if (normalized === "blocked" || normalized === "blocked_human" || normalized === "blocked_environment") {
    return copy("Blocked", "受阻");
  }
  if (normalized === "paused") {
    return copy("Paused", "已暂停");
  }
  if (normalized === "completed" || normalized === "succeeded") {
    return copy("Completed", "已完成");
  }
  if (normalized === "failed" || normalized === "cancelled" || normalized === "interrupted" || normalized === "timed_out") {
    return copy("Stopped", "已停止");
  }
  return run.status;
}

function businessActionFromMessage(
  message: AgentConversationMessage,
  copy: ReturnType<typeof useI18n>["copy"],
): BusinessActionTimelineItem | null {
  const metadata = recordFrom(message.metadata);
  const data = payloadDataFromMessage(message);
  const source = [
    message.title,
    message.content,
    stringField(metadata, "eventKind", "itemType", "traceKind", "payloadKind", "toolName"),
    stringField(data, "kind", "tool_name", "name"),
    compactBusinessActionText(data.input),
    compactBusinessActionText(data.content),
  ].filter(Boolean).join(" ");
  const category = classifyBusinessActionCategory(source);
  if (!category) {
    return null;
  }
  const dataKind = stringField(data, "kind");
  const eventType = stringField(metadata, "event_type", "itemType");
  const isRuntimeToolEvent = eventType === "tool_event" || eventType === "runtime_event";
  if (isRuntimeToolEvent && dataKind && /delta|input_streamed|call_started|use_completed/.test(dataKind)) {
    return null;
  }
  const toolName = stringField(metadata, "toolName") ?? stringField(data, "tool_name", "name");
  const title = compactBusinessActionText(
    message.title
      || stringField(data, "summary", "title", "status")
      || toolName
      || source,
    72,
  );
  const detail = compactBusinessActionText(
    data.content
      ?? data.result
      ?? data.output
      ?? message.content
      ?? toolName
      ?? businessActionLabel(category, copy),
  );
  return {
    key: `message-${message.id}`,
    category,
    label: businessActionLabel(category, copy),
    title: title || businessActionLabel(category, copy),
    detail: detail || copy("Business state changed.", "业务状态已变化。"),
    time: message.createdAt,
    status: businessActionStatus(message),
  };
}

function businessActionFromApproval(
  approval: ApprovalItem,
  copy: ReturnType<typeof useI18n>["copy"],
): BusinessActionTimelineItem {
  return {
    key: `approval-${approval.id}`,
    category: "approval",
    label: copy("Approval", "审批"),
    title: cleanApprovalTitle(approval),
    detail: describeApprovalIntent(approval, copy),
    time: approval.createdAt,
    status: approval.status === "pending" ? "warning" : approval.status === "approved" ? "success" : "error",
  };
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
  const runtimeData = event.data.data && typeof event.data.data === "object" && !Array.isArray(event.data.data)
    ? event.data.data as Record<string, unknown>
    : event.data;
  const runtimeKind = String(runtimeData.kind ?? event.event);
  const toolName = String(runtimeData.tool_name ?? runtimeData.name ?? "unknown");
  switch (event.event) {
    case "tool_call":
      return `调用工具 ${String(event.data.name ?? "unknown")}`;
    case "tool_result":
      return `工具 ${String(event.data.tool_name ?? "unknown")} 已返回结果`;
    case "tool_blocked":
      return `工具 ${String(event.data.tool_name ?? "unknown")} 被阻止：${String(event.data.reason ?? "需要人工处理")}`;
    case "turn.waiting_human":
      return "AI助手正在等待人工审批后继续。";
    case "turn.cancelled":
      return `AI助手已取消：${String(event.data.reason ?? "cancelled")}`;
    case "turn.failed":
      return `AI助手运行失败：${String(event.data.error ?? event.data.reason ?? "unknown error")}`;
    default:
      break;
  }
  if (event.event === "tool_event") {
    if (runtimeKind === "tool_use_delta") {
      return String(runtimeData.delta ?? "").trim() ? `准备工具 ${toolName} 参数` : null;
    }
    if (runtimeKind === "tool_use_completed") {
      return `工具 ${toolName} 参数已准备`;
    }
    if (runtimeKind === "tool_call_started") {
      return `调用工具 ${toolName}`;
    }
    if (runtimeKind === "tool_result_ready") {
      return `工具 ${toolName} 已返回结果`;
    }
    if (runtimeKind === "tool_error") {
      return `工具 ${toolName} 返回异常`;
    }
  }
  if (event.event === "permission_requested") {
    return `工具 ${toolName} 需要人工确认`;
  }
  if (event.event === "turn_failed") {
    return `AI助手运行失败：${String(runtimeData.error ?? runtimeData.reason ?? "unknown error")}`;
  }
  return null;
}

function extractAssistantText(event: AssistantTurnStreamEvent): string {
  const runtimeData = event.data.data && typeof event.data.data === "object" && !Array.isArray(event.data.data)
    ? event.data.data as Record<string, unknown>
    : event.data;
  if (typeof runtimeData.message === "string") {
    return runtimeData.message;
  }
  if (typeof runtimeData.delta === "string") {
    return runtimeData.delta;
  }
  if (typeof runtimeData.content === "string") {
    return runtimeData.content;
  }
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
  const runtimeData = event.data.data && typeof event.data.data === "object" && !Array.isArray(event.data.data)
    ? event.data.data as Record<string, unknown>
    : event.data;
  const payloadKind = String(runtimeData.kind ?? event.event);
  const toolName = String(runtimeData.tool_name ?? runtimeData.name ?? "").trim();
  const eventKind =
    event.event === "tool_call" || event.event === "tool_event"
      ? "tool_call"
      : event.event === "tool_result"
        ? "execution_result"
        : event.event === "tool_blocked" || event.event === "turn.waiting_human" || event.event === "permission_requested"
          ? "confirmation"
          : event.event === "llm_delta" || event.event === "llm_final" || event.event === "assistant_message_delta" || event.event === "assistant_message_completed" || event.event === "reasoning_delta"
            ? "thinking"
            : "execution_result";
  const resolvedEventKind = payloadKind === "tool_result_ready" || payloadKind === "tool_error" ? "execution_result" : eventKind;

  return {
    ...event.data,
    eventKind: resolvedEventKind,
    itemType: event.event,
    traceKind: payloadKind,
    payloadKind,
    payload: {
      data: runtimeData,
    },
    toolName: toolName || undefined,
    toolUseId: runtimeData.tool_use_id,
    toolCallId: runtimeData.tool_call_id,
    turn_id: event.data.turn_id ?? runtimeData.turn_id,
    seq: event.data.seq,
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

function compactJsonSummary(value: Record<string, unknown> | undefined, fallback: string): string {
  if (!value || !Object.keys(value).length) {
    return fallback;
  }
  const type = typeof value.type === "string" ? value.type : null;
  const properties = isRecord(value.properties) ? Object.keys(value.properties) : [];
  const required = Array.isArray(value.required) ? value.required.map(String) : [];
  const parts = [
    type ? `type ${type}` : null,
    properties.length ? `${properties.slice(0, 6).join(", ")}${properties.length > 6 ? " +" + (properties.length - 6) : ""}` : null,
    required.length ? `required ${required.slice(0, 4).join(", ")}` : null,
  ].filter((part): part is string => Boolean(part));
  if (parts.length) {
    return parts.join(" · ");
  }
  return Object.keys(value).slice(0, 6).join(", ");
}

function metadataSummary(value: Record<string, unknown> | undefined, fallback: string): string {
  if (!value || !Object.keys(value).length) {
    return fallback;
  }
  return Object.entries(value)
    .slice(0, 6)
    .map(([key, item]) => `${key}: ${typeof item === "object" && item !== null ? "[object]" : String(item)}`)
    .join(" · ");
}

function hasRecordEntries(value: Record<string, unknown> | undefined): boolean {
  return Boolean(value && Object.keys(value).length);
}

function mcpStandardConfigSummary(mcp: McpServerRecord): string {
  const servers = isRecord(mcp.standardConfig.mcpServers) ? mcp.standardConfig.mcpServers : {};
  const byKey = servers[mcp.serverKey];
  const firstConfig = Object.values(servers).find((value): value is Record<string, unknown> => isRecord(value));
  const config: Record<string, unknown> = isRecord(byKey) ? byKey : (firstConfig || {});
  const command = typeof config.command === "string" ? config.command : null;
  const args = Array.isArray(config.args) ? config.args.map(String) : [];
  const url = typeof config.url === "string" ? config.url : null;
  const env = isRecord(config.env) ? Object.keys(config.env) : [];
  const parts = [
    command ? `command ${command}` : null,
    args.length ? `args ${args.join(" ")}` : null,
    url ? `url ${url}` : null,
    env.length ? `env ${env.join(", ")}` : null,
  ].filter((part): part is string => Boolean(part));
  return parts.join(" · ");
}

function mcpStandardConfigJson(mcp: McpServerRecord): string {
  const servers = isRecord(mcp.standardConfig.mcpServers) ? mcp.standardConfig.mcpServers : {};
  const byKey = servers[mcp.serverKey];
  const firstConfig = Object.values(servers).find((value): value is Record<string, unknown> => isRecord(value));
  const config = isRecord(byKey) ? byKey : firstConfig;
  if (!config) {
    return prettyJson(mcp.standardConfig);
  }
  return JSON.stringify({ mcpServers: { [mcp.serverKey]: config } }, null, 2);
}

function capabilityStatusTone(status: string, enabled = true): "positive" | "neutral" | "warning" | "critical" {
  const normalized = status.trim().toLowerCase();
  if (!enabled || normalized === "disabled") {
    return "neutral";
  }
  if (normalized === "active" || normalized === "enabled" || normalized === "healthy") {
    return "positive";
  }
  if (normalized === "failed" || normalized === "critical" || normalized === "error") {
    return "critical";
  }
  if (normalized === "warning" || normalized === "degraded") {
    return "warning";
  }
  return "neutral";
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

const RAIL_RESTORE_MIN_TOP = 84;
const RAIL_RESTORE_BOTTOM_GAP = 84;

function clampRailRestoreTop(top: number, containerHeight: number): number {
  const maxTop = Math.max(RAIL_RESTORE_MIN_TOP, containerHeight - RAIL_RESTORE_BOTTOM_GAP);
  return Math.min(Math.max(top, RAIL_RESTORE_MIN_TOP), maxTop);
}

export function ChatOverlay({
  transport,
  workspaceAgent,
  jobDescriptions = [],
  variant = "overlay",
}: ChatOverlayProps): JSX.Element {
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
  const [listCollapsed, setListCollapsed] = useState(false);
  const [railCollapsed, setRailCollapsed] = useState(false);
  const [railRestoreTop, setRailRestoreTop] = useState(128);
  const [collapsedGroups, setCollapsedGroups] = useState<Record<AgentKind, boolean>>({
    assistant: false,
    autonomous: false,
    jd_sync: false,
  });
  const [errorMessage, setErrorMessage] = useState<string>();
  const [settingsSnapshot, setSettingsSnapshot] = useState<SettingsSnapshot | null>(null);
  const [configDraft, setConfigDraft] = useState<ConfigDraft | null>(null);
  const [agentConfigDrafts, setAgentConfigDrafts] = useState<Record<AgentKind, AgentConfigDraft>>(agentConfigDraftTemplate);
  const [automationConfigDraft, setAutomationConfigDraft] = useState<AutomationConfigDraft>(automationConfigDraftTemplate);
  const [jdSyncConfigDraft, setJdSyncConfigDraft] = useState<AutomationConfigDraft>(automationConfigDraftTemplate);
  const [selectedAutomationJobId, setSelectedAutomationJobId] = useState<string | null>(null);
  const [selectedAutomationConfigPage, setSelectedAutomationConfigPage] = useState<AutomationConfigPageKey>("entry");
  const [systemPromptExpanded, setSystemPromptExpanded] = useState(false);
  const [selectedConfigSection, setSelectedConfigSection] = useState<AgentConfigSectionKey>("identity");
  const [selectedCapabilityKey, setSelectedCapabilityKey] = useState<string | null>(null);
  const [loadingSettings, setLoadingSettings] = useState(false);
  const [savingConfig, setSavingConfig] = useState(false);
  const [startingAutomationPlan, setStartingAutomationPlan] = useState(false);
  const [syncingAutomationJobs, setSyncingAutomationJobs] = useState(false);
  const [panelNotice, setPanelNotice] = useState<PanelNotice | null>(null);
  const [approvalNotes, setApprovalNotes] = useState<Record<string, string>>({});
  const [approvalSelections, setApprovalSelections] = useState<Record<string, string>>({});
  const [approvalActionId, setApprovalActionId] = useState<string | null>(null);
  const [runActionBusyId, setRunActionBusyId] = useState<string | null>(null);
  const [workspaceControlBusyAction, setWorkspaceControlBusyAction] = useState<string | null>(null);
  const [agentListFilter, setAgentListFilter] = useState<AgentListFilter>("all");
  const [activeRailTab, setActiveRailTab] = useState<AgentRailTab>("details");
  const [businessActionFilter, setBusinessActionFilter] = useState<BusinessActionFilter>("all");
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
  const railRestoreDragRef = useRef<{
    pointerId: number;
    pointerY: number;
    originTop: number;
    containerHeight: number;
    moved: boolean;
  } | null>(null);
  const streamShellRef = useRef<HTMLDivElement | null>(null);
  const streamShouldFollowRef = useRef(true);
  const streamLastMessageSignatureRef = useRef<string>("");
  const assistantAbortRef = useRef<AbortController | null>(null);
  const assistantStreamContentRef = useRef<Record<string, string>>({});
  const conversationLookupRef = useRef<Map<string, AgentConversationSummary>>(new Map());

  useEffect(() => {
    if (!pageMode) {
      return;
    }
    setListCollapsed(activePanel !== "conversation");
  }, [activePanel, pageMode]);

  const loadWorkspaces = useCallback(async (markLoading = true) => {
    if (markLoading) {
      setLoadingWorkspace(true);
    }
    try {
      const entries = await Promise.all(
        AGENT_KINDS.map(async (kind) => [kind, await apiClient.getAgentWorkspace(kind)] as const),
      );
      setWorkspaces(Object.fromEntries(entries) as Record<AgentKind, AgentWorkspaceRecord | null>);
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

  useEffect(() => {
    if (!visible) {
      return;
    }
    void loadWorkspaces();
    void loadSettings();
  }, [visible, loadSettings, loadWorkspaces]);

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
      jd_sync: agentConfigDraftFromWorkspace(workspaces.jd_sync),
    });
  }, [workspaces.assistant, workspaces.autonomous, workspaces.jd_sync]);

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
      jd_sync: dedupeConversations([
        ...(localConversations.jd_sync ?? []),
        ...(workspaces.jd_sync?.conversations ?? []),
      ]),
    }),
    [localConversations, workspaces],
  );

  const conversationLookup = useMemo(() => {
    const lookup = new Map<string, AgentConversationSummary>();
    AGENT_KINDS.forEach((kind) => {
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
    if (panelNotice?.tone !== "success") {
      return;
    }
    const notice = panelNotice;
    const timeoutId = window.setTimeout(() => {
      setPanelNotice((current) => (current === notice ? null : current));
    }, 3000);
    return () => window.clearTimeout(timeoutId);
  }, [panelNotice]);

  useEffect(() => {
    if (!visible) {
      return;
    }
    setSelectedConversation((current) => {
      const next = { ...current };
      AGENT_KINDS.forEach((kind) => {
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
  const automationJobDescriptions = useMemo(
    () => jobDescriptions.filter((job) => automationJobId(job) != null),
    [jobDescriptions],
  );
  const automationJobIds = useMemo(
    () => automationJobDescriptions.map(automationJobId).filter((id): id is string => Boolean(id)),
    [automationJobDescriptions],
  );
  const automationLaunchBlockers = useMemo(
    () => validateAutomationLaunchReadiness(automationConfigDraft, automationJobDescriptions),
    [automationConfigDraft, automationJobDescriptions],
  );
  const automationLaunchReady = automationLaunchBlockers.length === 0;
  const jdSyncLaunchBlockers = useMemo(
    () => validateJdSyncLaunchReadiness(jdSyncConfigDraft),
    [jdSyncConfigDraft],
  );
  const jdSyncLaunchReady = jdSyncLaunchBlockers.length === 0;
  const autonomousWorkspace = workspaces.autonomous;
  const autonomousActiveRun = useMemo(
    () => autonomousWorkspace?.runs.find((run) => isOpenRunStatus(run.status)) ?? null,
    [autonomousWorkspace],
  );
  const jdSyncWorkspace = workspaces.jd_sync;
  const jdSyncActiveRun = useMemo(
    () => jdSyncWorkspace?.runs.find((run) => isOpenRunStatus(run.status)) ?? null,
    [jdSyncWorkspace],
  );
  const runtimeActiveRun = activeAgent === "jd_sync" ? jdSyncActiveRun : activeAgent === "autonomous" ? autonomousActiveRun : null;
  const runtimeExecutingRun = runtimeActiveRun && isActivelyExecutingRunStatus(runtimeActiveRun.status) ? runtimeActiveRun : null;
  const runtimeResumableRun = runtimeActiveRun && isResumableRunStatus(runtimeActiveRun.status) ? runtimeActiveRun : null;
  const activeConversationRun = useMemo(() => {
    if (!activeWorkspace || activeAgent === "assistant") {
      return null;
    }
    const conversationIds = new Set(
      [activeConversationId, activeConversationSummary?.refId].filter((value): value is string => Boolean(value)),
    );
    return activeWorkspace.runs.find((run) =>
      conversationIds.has(run.id)
      || (run.refId != null && conversationIds.has(run.refId))
    ) ?? null;
  }, [activeAgent, activeConversationId, activeConversationSummary?.refId, activeWorkspace]);
  const activeConversationRunIsResumable = Boolean(
    activeConversationRun
    && activeAgent !== "assistant"
    && isResumableRunStatus(activeConversationRun.status),
  );
  const activeWorkspaceControlState = activeWorkspace?.workspaceControl?.state ?? "stopped";
  const activeWorkspaceStartBlockers =
    activeAgent === "autonomous"
      ? automationLaunchBlockers
      : activeAgent === "jd_sync"
        ? jdSyncLaunchBlockers
        : [];
  const activeWorkspaceStartReady = activeWorkspaceStartBlockers.length === 0;
  const activeWorkspaceCanStart = activeWorkspaceStartReady;
  const composerInputValue = activeDraftComposerKey != null ? draftComposerValues[activeDraftComposerKey] ?? "" : composerValue;
  const automationConfigHydrationKey = useMemo(() => {
    const definition = workspaces.autonomous?.agentDefinition;
    return JSON.stringify({
      productConfig: definition?.productConfig ?? null,
      runtimeMetadata: definition?.config.runtimeMetadata ?? null,
      jobIds: automationJobIds,
    });
  }, [
    automationJobIds,
    workspaces.autonomous?.agentDefinition.config.runtimeMetadata,
    workspaces.autonomous?.agentDefinition.productConfig,
  ]);

  useEffect(() => {
    setAutomationConfigDraft(automationConfigDraftFromWorkspace(workspaces.autonomous, automationJobDescriptions));
  }, [automationConfigHydrationKey]);

  const jdSyncConfigHydrationKey = useMemo(() => {
    const definition = workspaces.jd_sync?.agentDefinition;
    return JSON.stringify({
      productConfig: definition?.productConfig ?? null,
      runtimeMetadata: definition?.config.runtimeMetadata ?? null,
    });
  }, [
    workspaces.jd_sync?.agentDefinition.config.runtimeMetadata,
    workspaces.jd_sync?.agentDefinition.productConfig,
  ]);

  useEffect(() => {
    setJdSyncConfigDraft(automationConfigDraftFromWorkspace(workspaces.jd_sync, [], "jd_sync"));
  }, [jdSyncConfigHydrationKey]);

  useEffect(() => {
    setSelectedAutomationJobId((current) => {
      if (current && automationJobIds.includes(current)) {
        return current;
      }
      return automationJobIds[0] ?? null;
    });
  }, [automationJobIds]);

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

  const applyConversationRecord = useCallback(
    (agentKind: AgentKind, cacheKey: string, record: AgentConversationRecord) => {
      const existingSummary = conversationLookupRef.current.get(cacheKey);
      const nextConversation = {
        ...record.conversation,
        updatedAt: resolveConversationUpdatedAt(existingSummary, record.conversation, record.messages),
      };
      setLocalConversations((current) => ({
        ...current,
        [agentKind]: mergeConversationSummaries(current[agentKind] ?? [], [nextConversation]),
      }));
      setConversationCache((current) => ({
        ...current,
        [cacheKey]: {
          conversation: nextConversation,
          messages: mergeMessages(current[cacheKey]?.messages ?? [], record.messages),
        },
      }));
    },
    [],
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
        ? copy("New AI assistant chat", "新 AI助手会话")
        : copy("New automation run", "新自动化运行");
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
              ? copy("New AI assistant chat", "新 AI助手会话")
              : copy("New automation run", "新自动化运行"),
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

  const queueConversationStatusLabel = useCallback(
    (conversation: AgentConversationSummary) => {
      const normalized = String(conversation.status).trim().toLowerCase();
      if (normalized === "idle") {
        const preview = conversation.preview?.trim() ?? "";
        if (conversation.refId || preview) {
          return copy("Finished", "已结束");
        }
        return copy("Idle", "空闲");
      }
      if (normalized === "active") {
        return copy("Running", "运行中");
      }
      return describeConversationStatus(conversation.status);
    },
    [copy, describeConversationStatus],
  );

  const describeRunStatus = useCallback(
    (run: AgentRunRecord) => {
      const normalized = run.status.trim().toLowerCase();
      if (normalized === "idle") {
        const summary = run.summary?.trim() ?? "";
        if (run.startedAt || run.refId || summary) {
          return copy("Finished", "已结束");
        }
      }
      return describeConversationStatus(run.status);
    },
    [copy, describeConversationStatus],
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
        title: copy("No active run", "当前没有活跃运行"),
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
        latestRun ? `${copy("Last run", "最近一次")}：${describeRunStatus(latestRun)}` : null,
        activeWorkspace.agent.activeTask ? `${copy("Instruction", "当前指令")}：${activeWorkspace.agent.activeTask}` : null,
      ].filter((value): value is string => Boolean(value && value.trim()));

      return {
        badgeLabel: latestRun ? describeRunStatus(latestRun) : describeConversationStatus(activeWorkspace.agent.status),
        title: latestRun?.title || copy("No active run", "当前没有活跃运行"),
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
      activeWorkspace.agent.activeTask ? `${copy("Instruction", "当前指令")}：${activeWorkspace.agent.activeTask}` : null,
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
      badgeLabel: describeRunStatus(highlightedRun),
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
  }, [activeWorkspace, copy, describeConversationStatus, describeRunStatus]);

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
        applyConversationRecord(activeAgent, activeConversationCacheKey, record);
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

    if (!isRuntimeAgentKind(activeAgent)) {
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
  }, [activeAgent, activeConversationCacheKey, activeConversationId, applyConversationRecord, conversationPollMs, copy, visible]);

  useEffect(() => {
    if (!visible || !activeConversationId || !activeConversationCacheKey) {
      return;
    }
    if (!isRuntimeAgentKind(activeAgent) || activeConversationId.startsWith("draft-")) {
      return;
    }

    let active = true;
    const controller = new AbortController();
    void apiClient.streamAgentConversation(
      activeAgent,
      activeConversationId,
      { signal: controller.signal },
      (record) => {
        if (!active) {
          return;
        }
        applyConversationRecord(activeAgent, activeConversationCacheKey, record);
      },
    ).catch((error) => {
      if (!active || controller.signal.aborted) {
        return;
      }
      console.warn("Runtime conversation stream failed", error);
    });

    return () => {
      active = false;
      controller.abort();
    };
  }, [activeAgent, activeConversationCacheKey, activeConversationId, applyConversationRecord, visible]);

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
    if (activePanel === "conversation") {
      return;
    }
    const shell = streamShellRef.current;
    if (shell) {
      shell.scrollTop = 0;
    }
  }, [activeAgent, activePanel]);

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

  const handleClearConversation = async () => {
    const conversationId = activeConversationId;
    setPanelNotice(null);
    setErrorMessage(undefined);
    if (activeDraftComposerKey != null) {
      setDraftComposerValues((current) => {
        const next = { ...current };
        delete next[activeDraftComposerKey];
        return next;
      });
    } else {
      setComposerValue("");
    }

    if (!conversationId || conversationId.startsWith("draft-")) {
      if (conversationId) {
        removeDraftConversation(activeAgent, conversationId);
      }
      createDraftConversation(activeAgent);
      setPanelNotice({
        panel: "conversation",
        tone: "success",
        message: copy("Conversation cleared.", "已清空当前会话。"),
      });
      return;
    }

    setSending(true);
    try {
      const record = await apiClient.clearAgentConversation(activeAgent, conversationId);
      const cacheKey = conversationKey(activeAgent, record.conversation.id);
      setLocalConversations((current) => ({
        ...current,
        [activeAgent]: mergeConversationSummaries(current[activeAgent] ?? [], [record.conversation]),
      }));
      setConversationCache((current) => ({
        ...current,
        [cacheKey]: {
          conversation: record.conversation,
          messages: [],
        },
      }));
      setSelectedConversation((current) => ({
        ...current,
        [activeAgent]: record.conversation.id,
      }));
      if (activeAgent !== "assistant") {
        await loadWorkspaces();
      }
      setPanelNotice({
        panel: "conversation",
        tone: "success",
        message: copy("Conversation history cleared.", "已清空会话历史。"),
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : copy("Failed to clear conversation.", "清空会话失败。");
      setErrorMessage(message);
      setPanelNotice({
        panel: "conversation",
        tone: "error",
        message,
      });
    } finally {
      setSending(false);
    }
  };

  const handleAssistantEvent = useCallback(
    (
      conversationId: string,
      streamMessageId: string,
      userInput: string,
      event: AssistantTurnStreamEvent,
    ) => {
      if (
        event.event === "llm_delta"
        || event.event === "llm_final"
        || event.event === "assistant_message_delta"
        || event.event === "assistant_message_completed"
      ) {
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
          status: event.event === "llm_final" || event.event === "assistant_message_completed" ? "sent" : "streaming",
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
        role: event.event.startsWith("tool_") || event.event === "tool_event" ? "tool" : "system",
        kind: event.event === "tool_call" || event.event === "tool_event"
          ? "tool_use"
          : event.event.startsWith("tool_")
            ? "tool_result"
            : "status",
        content: detail,
        createdAt: event.receivedAt,
        status: event.event === "turn.failed" || event.event === "turn_failed" ? "failed" : "sent",
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
    if (isClearConversationCommand(text)) {
      await handleClearConversation();
      return;
    }
    if (activeAgent !== "assistant" && activeWorkspaceControlState !== "running" && !activeConversationRunIsResumable) {
      setPanelNotice({
        panel: "conversation",
        tone: "info",
        message: copy("Start the agent before sending messages.", "请先启动 Agent，再发送消息。"),
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
          const message = error instanceof Error ? error.message : copy("AI assistant request failed.", "AI助手请求失败。");
          if (!receivedStreamEvent && /:\s*(404|405)\b/.test(message)) {
            const result = await apiClient.sendAssistantMessage({ conversationId, message: text });
            appendMessage("assistant", conversationId, {
              id: streamMessageId,
              conversationId,
              role: "system",
              kind: "status",
              content:
                result.status === "queued"
                  ? copy("AI assistant SSE endpoint is unavailable. The request has been queued instead.", "AI助手 SSE 接口不可用，已改为排队提交。")
                  : copy("AI assistant accepted the request, but live streaming is unavailable.", "AI助手已接收请求，但当前环境不支持实时流式展示。"),
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
                "Fell back to queued delivery because the live AI assistant stream is unavailable.",
                "当前环境没有可用的 AI助手实时流，已自动降级为排队提交。",
              ),
            });
          } else if (!receivedStreamEvent && /aborted|abort/i.test(message)) {
            appendMessage("assistant", conversationId, {
              id: streamMessageId,
              conversationId,
              role: "system",
              kind: "status",
              content: copy("AI assistant stream was cancelled.", "AI助手流已取消。"),
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
        const normalizedConversationId = conversationId;
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

        if (activeConversationRun && isResumableRunStatus(activeConversationRun.status)) {
          const result = await apiClient.resumeAgentRun(
            activeAgent,
            activeConversationRun.id,
            copy("Resumed from conversation composer.", "从会话输入框继续执行。"),
            text,
          );
          if (activeWorkspaceControlState !== "running") {
            await apiClient.controlRuntimeWorkspace(
              activeAgent,
              "continue",
              copy("Workspace continued for resumed conversation run.", "为会话恢复运行继续工作区。"),
            );
          }
          await loadWorkspaces();
          appendMessage(activeAgent, result.refId ?? conversationId, {
            id: `runtime-run-resumed-${result.id}-${Date.now()}`,
            conversationId: result.refId ?? conversationId,
            role: "system",
            kind: "status",
            content: copy(
              "The selected run has been resumed with your message.",
              "已使用你的消息继续当前选中的运行。",
            ),
            createdAt: new Date().toISOString(),
            status: "sent",
            metadata: {
              eventKind: "thinking",
              itemType: "run_resumed_with_user_message",
              runId: result.id,
            },
          });
          return;
        }

        if (runtimeActiveRun) {
          const backendConversationId =
            runtimeActiveRun.refId && !runtimeActiveRun.refId.startsWith("draft-")
              ? runtimeActiveRun.refId
              : activeAgent === "jd_sync"
                ? "jd-sync-primary"
                : "autonomous-primary";
          const result = await apiClient.queueAgentPendingUserInputAfterNextToolCall(activeAgent, {
            conversationId: backendConversationId,
            message: text,
            priority: "next",
          });
          if (normalizedConversationId !== result.conversationId && normalizedConversationId.startsWith("draft-")) {
            removeDraftConversation(activeAgent, normalizedConversationId);
          }
          await loadWorkspaces();
          setSelectedConversation((current) => ({
            ...current,
            [activeAgent]: result.conversationId,
          }));
          if (normalizedConversationId !== result.conversationId) {
            appendMessage(activeAgent, result.conversationId, {
              id: `local-user-${timestamp}-${result.conversationId}`,
              conversationId: result.conversationId,
              role: "user",
              kind: "message",
              content: text,
              createdAt: timestamp,
              status: "sent",
              metadata: {
                eventKind: "human",
              },
            });
            syncConversationPreview(activeAgent, result.conversationId, text, trimTitle(text));
          }
          appendMessage(activeAgent, result.conversationId, {
            id: `runtime-user-input-queued-${result.requestId ?? Date.now()}`,
            conversationId: result.conversationId,
            role: "system",
            kind: "status",
            content: copy(
              "The message will be applied after the next tool call.",
              "这条消息会在下一次工具调用后注入。",
            ),
            createdAt: new Date().toISOString(),
            status: result.status === "queued" ? "pending" : "sent",
            metadata: {
              eventKind: "thinking",
              itemType: "pending_user_input_after_next_tool_call",
              requestId: result.requestId,
            },
          });
          return;
        }

        const draftConversationId = conversationId;
        const result = await apiClient.startAgentRun(activeAgent, {
          title: trimTitle(text),
          instruction: text,
          requestMessage: text,
          kind: activeAgent === "jd_sync" ? "jd_sync" : "automation_recruiting",
          conversationId: conversationId.startsWith("draft-") ? null : conversationId,
        });
        removeDraftConversation(activeAgent, draftConversationId);
        await loadWorkspaces();
        setSelectedConversation((current) => ({
          ...current,
          [activeAgent]: result.conversationId,
        }));
        appendMessage(activeAgent, result.conversationId, {
          id: `${activeAgent}-status-${result.runId ?? Date.now()}`,
          conversationId: result.conversationId,
          role: "system",
          kind: "status",
          content: copy("Agent run has been submitted to the backend.", "Agent 运行已提交到后端。"),
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

  const handleStartAutomationPlan = async () => {
    if (autonomousActiveRun) {
      setPanelNotice({
        panel: "config",
        tone: "info",
        message: copy(
          "Automation already has an open run. Wait for the current run to finish before starting the next one.",
          "Automation 当前已有未结束的运行，请等待当前运行结束后再启动下一轮。",
        ),
      });
      return;
    }
    if (automationLaunchBlockers.length) {
      setPanelNotice({
        panel: "config",
        tone: "error",
        message: `${copy("Complete configuration before starting automation:", "启动自动化前请先补全配置：")} ${automationLaunchBlockers.join("；")}`,
      });
      return;
    }

    setStartingAutomationPlan(true);
    setPanelNotice(null);
    setErrorMessage(undefined);
    try {
      const control = await apiClient.controlRuntimeWorkspace(
        "autonomous",
        "start",
        copy("Started from saved automation recruiting configuration.", "按已保存的自动化招聘配置启动。"),
      );
      await loadWorkspaces();
      setPanelNotice({
        panel: "config",
        tone: control.runStartBlocked ? "error" : "success",
        message: control.runStartBlocked?.reason
          ?? copy("Automation recruiting run has started from saved configuration.", "已按保存的配置启动自动化招聘运行。"),
      });
    } catch (error) {
      setPanelNotice({
        panel: "config",
        tone: "error",
        message: error instanceof Error ? error.message : copy("Failed to start automation run.", "启动自动化运行失败。"),
      });
    } finally {
      setStartingAutomationPlan(false);
    }
  };

  const handleStartJdSync = async () => {
    if (jdSyncActiveRun) {
      setPanelNotice({
        panel: "config",
        tone: "info",
        message: copy(
          "JD Sync already has an open run. Wait for it to finish before syncing again.",
          "JD 同步 Agent 当前已有未结束的运行，请等待完成后再同步。",
        ),
      });
      return;
    }
    const payload = buildJdSyncLaunchPayload(jdSyncConfigDraft);
    if (!payload || jdSyncLaunchBlockers.length) {
      setPanelNotice({
        panel: "config",
        tone: "error",
        message: `${copy("Complete configuration before starting JD Sync:", "启动 JD 同步前请先补全配置：")} ${jdSyncLaunchBlockers.join("；")}`,
      });
      return;
    }
    setSyncingAutomationJobs(true);
    setPanelNotice(null);
    setErrorMessage(undefined);
    try {
      const result = await apiClient.startAgentRun("jd_sync", payload);
      if ((workspaces.jd_sync?.workspaceControl?.state ?? "stopped") !== "running") {
        await apiClient.controlRuntimeWorkspace("jd_sync", "start", copy("Started for JD sync agent.", "为 JD 同步 Agent 启动工作区。"));
      }
      await loadWorkspaces();
      setSelectedConversation((current) => ({
        ...current,
        jd_sync: result.conversationId,
      }));
      setActivePanel("conversation");
      appendMessage("jd_sync", result.conversationId, {
        id: `jd-sync-${result.runId ?? Date.now()}`,
        conversationId: result.conversationId,
        role: "system",
        kind: "status",
        content: copy("JD sync run has started. After it finishes, return to JD strategy and select the synced JD.", "JD 同步运行已启动。完成后回到 JD 策略，选择已同步的 JD。"),
        createdAt: new Date().toISOString(),
        status: "sent",
        metadata: {
          eventKind: "thinking",
          launchPlan: payload.contextHints,
        },
      });
    } catch (error) {
      setPanelNotice({
        panel: "config",
        tone: "error",
        message: error instanceof Error ? error.message : copy("Failed to start JD sync.", "启动 JD 同步失败。"),
      });
    } finally {
      setSyncingAutomationJobs(false);
    }
  };

  const handleSaveConfig = async () => {
    if (!configDraft || !settingsSnapshot || !activeWorkspace) {
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
      const buildConfigPatch = (
        kind: AgentKind,
        workspace: AgentWorkspaceRecord,
        draft: AgentConfigDraft,
      ): { config: AgentWorkspaceRecord["agentDefinition"]["config"]; productConfig?: Record<string, unknown>; error?: string } => {
        const jsonFields = [
          { key: "toolScope" as const, label: copy("Capability usage", "能力使用"), value: draft.toolScopeJson },
          { key: "permissionPolicy" as const, label: copy("Approval rules", "审批规则"), value: draft.permissionPolicyJson },
          { key: "outputPolicy" as const, label: copy("Answer standard", "回答标准"), value: draft.outputPolicyJson },
          { key: "budgetPolicy" as const, label: copy("Interaction limits", "交互限制"), value: draft.budgetPolicyJson },
          { key: "modelConfig" as const, label: copy("Model settings", "模型设置"), value: draft.modelConfigJson },
          { key: "contextPolicy" as const, label: copy("Context scope", "上下文范围"), value: draft.contextPolicyJson },
          { key: "memoryPolicy" as const, label: copy("Retention rules", "保留规则"), value: draft.memoryPolicyJson },
        ];
        const parsed = Object.fromEntries(
          jsonFields.map((field) => [field.key, parseJsonRecordDraft(field.value, field.label)]),
        ) as Record<typeof jsonFields[number]["key"], { record: Record<string, unknown>; error?: string }>;
        const firstError = jsonFields.map((field) => parsed[field.key].error).find(Boolean);
        if (firstError) {
          return { config: workspace.agentDefinition.config, error: `${agentDisplayName(kind)} · ${firstError}` };
        }
        const runtimeMetadata = { ...workspace.agentDefinition.config.runtimeMetadata };
        const permissionPolicy = { ...parsed.permissionPolicy.record };
        let productConfig: Record<string, unknown> | undefined;
        if (kind === "autonomous") {
          runtimeMetadata.scoringRubric = draft.scoringRubric;
          runtimeMetadata.recruitingPolicy = recruitingPolicyPayloadFromDraft(draft.recruitingPolicy);
          const automationRecruitingConfig = automationConfigPayloadFromDraft(
            automationConfigDraft,
            automationJobDescriptions,
            workspace.tools,
          );
          delete runtimeMetadata.automationRecruitingConfig;
          delete runtimeMetadata.automation_recruiting_config;
          delete runtimeMetadata.automationConfig;
          delete runtimeMetadata.automation_config;
          const currentAutonomousConfig = recordField(
            isRecord(workspace.agentDefinition.productConfig) ? workspace.agentDefinition.productConfig : {},
            "autonomous",
          ) ?? {};
          productConfig = {
            autonomous: {
              ...currentAutonomousConfig,
              automation_recruiting_config: automationRecruitingConfig,
            },
          };
          permissionPolicy.businessToolApprovalPolicy = isRecord(automationRecruitingConfig.toolApprovalPolicy)
            ? automationRecruitingConfig.toolApprovalPolicy
            : {};
        } else if (kind === "jd_sync") {
          const jdSyncConfig = jdSyncConfigPayloadFromDraft(jdSyncConfigDraft);
          const currentJdSyncConfig = recordField(
            isRecord(workspace.agentDefinition.productConfig) ? workspace.agentDefinition.productConfig : {},
            "jd_sync",
          ) ?? {};
          productConfig = {
            jd_sync: {
              ...currentJdSyncConfig,
              jd_sync_config: jdSyncConfig,
            },
          };
        } else {
          delete runtimeMetadata.scoringRubric;
          delete runtimeMetadata.scoring_rubric;
          delete runtimeMetadata.recruitingPolicy;
          delete runtimeMetadata.recruiting_policy;
        }
        runtimeMetadata.contextPolicy = parsed.contextPolicy.record;
        runtimeMetadata.memoryPolicy = parsed.memoryPolicy.record;
        return {
          config: {
            ...workspace.agentDefinition.config,
            systemPrompt: draft.systemPrompt,
            identity: {
              ...workspace.agentDefinition.config.identity,
              statement: draft.identityStatement,
            },
            duties: listFromLines(draft.dutiesText),
            successCriteria: listFromLines(draft.successCriteriaText),
            boundaries: listFromLines(draft.boundariesText),
            toolScope: parsed.toolScope.record,
            permissionPolicy,
            outputPolicy: parsed.outputPolicy.record,
            budgetPolicy: parsed.budgetPolicy.record,
            modelConfig: parsed.modelConfig.record,
            runtimeMetadata,
          },
          productConfig,
        };
      };

      const configPatches = [activeAgent].map((kind) => {
        const workspace = workspaces[kind];
        const draft = agentConfigDrafts[kind];
        if (!workspace) {
          return null;
        }
        return { kind, workspace, patch: buildConfigPatch(kind, workspace, draft) };
      }).filter((item): item is { kind: AgentKind; workspace: AgentWorkspaceRecord; patch: ReturnType<typeof buildConfigPatch> } => Boolean(item));
      const firstConfigError = configPatches.map((item) => item.patch.error).find(Boolean);
      if (firstConfigError) {
        setPanelNotice({
          panel: "config",
          tone: "error",
          message: firstConfigError,
        });
        return;
      }
      const agentDefinitionUpdates = configPatches.map(({ kind, patch }) =>
        apiClient.updateProductAgentDefinition(kind, {
          config: {
            ...patch.config,
          },
          productConfig: patch.productConfig,
        }),
      );
      const [nextSettings] = await Promise.all([
        apiClient.updateSettings({
          desktopApprovalsOnly: configDraft.desktopApprovalsOnly,
          autonomyEnabled: configDraft.autonomyEnabled,
          skillHealthAutonomyEnabled: configDraft.skillHealthAutonomyEnabled,
          skillHealthAutonomyIntervalSeconds: interval,
        }),
        ...agentDefinitionUpdates,
      ]);
      setSettingsSnapshot(nextSettings);
      setConfigDraft(configDraftFromSettings(nextSettings));
      await loadWorkspaces();
      setPanelNotice({
        panel: "config",
        tone: "success",
        message: copy("Agent configuration saved.", "Agent 配置已保存。"),
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
        await apiClient.cancelAgentRun(activeAgent, run.id, copy("Cancelled from agent management page.", "在 Agent 管理页中手动中止。"));
      } else {
        await apiClient.resumeAgentRun(activeAgent, run.id, copy("Resumed from agent management page.", "在 Agent 管理页中手动恢复。"));
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

  const handleRestartRun = async (run: AgentRunRecord) => {
    setRunActionBusyId(run.id);
    try {
      if (isOpenRunStatus(run.status)) {
        await apiClient.cancelAgentRun(activeAgent, run.id, copy("Cancelled before restarting from agent management page.", "重新开始前在 Agent 管理页中止旧运行。"));
      }
      await apiClient.resumeAgentRun(activeAgent, run.id, copy("Restarted from agent management page.", "在 Agent 管理页中重新开始。"));
      if (activeWorkspaceControlState !== "running") {
        await apiClient.controlRuntimeWorkspace(activeAgent, "continue", copy("Workspace continued for restarted run.", "为重新开始的运行继续工作区。"));
      }
      await loadWorkspaces();
      setPanelNotice({
        panel: "runs",
        tone: "success",
        message: copy("Run restarted.", "已重新开始运行。"),
      });
    } catch (error) {
      setPanelNotice({
        panel: "runs",
        tone: "error",
        message: error instanceof Error ? error.message : copy("Restart failed.", "重新开始失败。"),
      });
    } finally {
      setRunActionBusyId(null);
    }
  };

  const handleStopCurrentTurn = async () => {
    if (activeAgent === "assistant") {
      assistantAbortRef.current?.abort();
      if (activeConversationId && !activeConversationId.startsWith("draft-")) {
        try {
          await apiClient.cancelAssistantTurn(activeConversationId);
        } catch {
          // The SSE abort path already interrupts the active assistant turn when connected.
        }
      }
      if (activeConversationId) {
        appendMessage("assistant", activeConversationId, {
          id: `assistant-cancel-${Date.now()}`,
          conversationId: activeConversationId,
          role: "system",
          kind: "status",
          content: copy("Current turn cancellation was requested.", "已请求终止当前 turn。"),
          createdAt: new Date().toISOString(),
          status: "sent",
          metadata: {
            eventKind: "execution_result",
            itemType: "turn_cancel_requested",
          },
        });
      }
      setSending(false);
      return;
    }

    if (!runtimeActiveRun) {
      return;
    }
    await handleRunAction(runtimeActiveRun, "cancel");
  };

  const handleWorkspaceControl = async (action: "start" | "pause" | "continue" | "terminate") => {
    if ((action === "start" || action === "continue") && activeAgent !== "assistant" && activeWorkspaceStartBlockers.length) {
      setPanelNotice({
        panel: "runs",
        tone: "error",
        message: `${activeAgent === "jd_sync" ? copy("Complete configuration before starting JD Sync:", "启动 JD 同步前请先补全配置：") : copy("Complete configuration before starting automation:", "启动自动化前请先补全配置：")} ${activeWorkspaceStartBlockers.join("；")}`,
      });
      return;
    }
    if (action === "continue" && runtimeResumableRun) {
      await handleRunAction(runtimeResumableRun, "resume");
      if (activeWorkspaceControlState !== "running") {
        await apiClient.controlRuntimeWorkspace(activeAgent, "continue", copy("Workspace continued for resumed run.", "为恢复运行继续工作区。"));
        await loadWorkspaces();
      }
      return;
    }
    if (action === "start" && activeAgent !== "jd_sync" && activeConversationRun && !isOpenRunStatus(activeConversationRun.status)) {
      await handleRestartRun(activeConversationRun);
      return;
    }
    if (activeAgent === "jd_sync" && action === "start") {
      if (jdSyncActiveRun) {
        if (activeWorkspaceControlState !== "running") {
          setWorkspaceControlBusyAction(action);
          try {
            await apiClient.controlRuntimeWorkspace("jd_sync", "start", copy("Started for JD sync agent.", "为 JD 同步 Agent 启动工作区。"));
            await loadWorkspaces();
            setPanelNotice({
              panel: "runs",
              tone: "success",
              message: copy("JD Sync workspace has continued the open run.", "已继续 JD 同步 Agent 的未结束运行。"),
            });
          } catch (error) {
            setPanelNotice({
              panel: "runs",
              tone: "error",
              message: error instanceof Error ? error.message : copy("Failed to start JD Sync.", "启动 JD 同步失败。"),
            });
          } finally {
            setWorkspaceControlBusyAction(null);
          }
          return;
        }
        setPanelNotice({
          panel: "runs",
          tone: "info",
          message: copy("JD Sync already has an open run. Wait for it to finish before syncing again.", "JD 同步 Agent 当前已有未结束的运行，请等待完成后再同步。"),
        });
        return;
      }
      const payload = buildJdSyncLaunchPayload(jdSyncConfigDraft);
      if (!payload || jdSyncLaunchBlockers.length) {
        setPanelNotice({
          panel: "runs",
          tone: "error",
          message: `${copy("Complete configuration before starting JD Sync:", "启动 JD 同步前请先补全配置：")} ${jdSyncLaunchBlockers.join("；")}`,
        });
        return;
      }
      setWorkspaceControlBusyAction(action);
      try {
        await apiClient.startAgentRun("jd_sync", payload);
        if ((workspaces.jd_sync?.workspaceControl?.state ?? "stopped") !== "running") {
          await apiClient.controlRuntimeWorkspace("jd_sync", "start", copy("Started for JD sync agent.", "为 JD 同步 Agent 启动工作区。"));
        }
        await loadWorkspaces();
        setPanelNotice({
          panel: "runs",
          tone: "success",
          message: copy("JD Sync run has started from the saved site configuration.", "已按保存的网站配置启动 JD 同步运行。"),
        });
      } catch (error) {
        setPanelNotice({
          panel: "runs",
          tone: "error",
          message: error instanceof Error ? error.message : copy("Failed to start JD Sync.", "启动 JD 同步失败。"),
        });
      } finally {
        setWorkspaceControlBusyAction(null);
      }
      return;
    }
    if (activeAgent === "autonomous" && action === "start" && !autonomousActiveRun && automationLaunchBlockers.length) {
      setPanelNotice({
        panel: "runs",
        tone: "error",
        message: `${copy("Complete configuration before starting automation:", "启动自动化前请先补全配置：")} ${automationLaunchBlockers.join("；")}`,
      });
      return;
    }
    setWorkspaceControlBusyAction(action);
    try {
      const reasonMap: Record<"start" | "pause" | "continue" | "terminate", string> = {
        start: copy("Started from agent workspace.", "在工作区手动开始。"),
        pause: copy("Paused from agent workspace.", "在工作区手动暂停。"),
        continue: copy("Continued from agent workspace.", "在工作区手动继续。"),
        terminate: copy("Terminated from agent workspace.", "在工作区手动终止。"),
      };
      const control = await apiClient.controlRuntimeWorkspace(activeAgent, action, reasonMap[action]);
      await loadWorkspaces();
      if ((action === "start" || action === "continue") && control.runStartBlocked) {
        setPanelNotice({
          panel: "runs",
          tone: "error",
          message: control.runStartBlocked.reason,
        });
        return;
      }
      setPanelNotice({
        panel: "runs",
        tone: "success",
        message:
          `${agentDisplayName(activeAgent)} ${
            action === "start"
              ? copy("started.", "已开始。")
              : action === "pause"
                ? copy("paused.", "已暂停。")
                : action === "continue"
                  ? copy("continued.", "已继续。")
                  : copy("terminated.", "已终止。")
          }`,
      });
    } catch (error) {
      setPanelNotice({
        panel: "runs",
        tone: "error",
        message: error instanceof Error ? error.message : copy("Workspace control failed.", "工作区控制失败。"),
      });
    } finally {
      setWorkspaceControlBusyAction(null);
    }
  };

  const composerCommandItems = useMemo<ChatComposerCommand[]>(() => {
    const commands: ChatComposerCommand[] = [
      {
        id: "clear",
        command: "clear",
        title: copy("Clear conversation", "清空会话"),
        description: copy("Reset this conversation context like Codex/Claude Code clear.", "像 Codex/Claude Code clear 一样重置当前会话上下文。"),
      },
    ];
    if (activeAgent !== "assistant") {
      commands.push(
        {
          id: "start",
          command: "start",
          title: copy("Start agent", "启动 Agent"),
          description: activeWorkspaceStartBlockers.length
            ? `${copy("Missing configuration:", "缺少配置：")} ${activeWorkspaceStartBlockers.join("；")}`
            : copy("Start or restart the selected automation workspace.", "启动或重新开始当前自动化工作区。"),
          disabled: workspaceControlBusyAction !== null || !activeWorkspaceCanStart,
        },
        {
          id: "pause",
          command: "pause",
          title: copy("Pause agent", "暂停 Agent"),
          description: copy("Pause the current automation workspace.", "暂停当前自动化工作区。"),
          disabled: workspaceControlBusyAction !== null || activeWorkspaceControlState !== "running",
        },
        {
          id: "continue",
          command: "continue",
          title: copy("Continue agent", "继续 Agent"),
          description: activeWorkspaceStartBlockers.length
            ? `${copy("Missing configuration:", "缺少配置：")} ${activeWorkspaceStartBlockers.join("；")}`
            : copy("Continue a paused automation workspace.", "继续已暂停的自动化工作区。"),
          disabled: workspaceControlBusyAction !== null || activeWorkspaceControlState !== "paused" || !activeWorkspaceCanStart,
        },
        {
          id: "terminate",
          command: "terminate",
          title: copy("Terminate agent", "终止 Agent"),
          description: copy("Terminate the current automation workspace and open runs.", "终止当前自动化工作区和未结束运行。"),
          disabled: workspaceControlBusyAction !== null || activeWorkspaceControlState === "stopped",
        },
      );
    }
    return commands;
  }, [activeAgent, activeWorkspaceCanStart, activeWorkspaceControlState, activeWorkspaceStartBlockers, copy, workspaceControlBusyAction]);

  const composerMatchedCommand = useMemo(() => {
    const query = slashCommandQuery(composerInputValue);
    if (query == null) {
      return null;
    }
    return composerCommandItems.find((command) => slashCommandMatches(command, query) && !command.disabled) ?? null;
  }, [composerCommandItems, composerInputValue]);

  const handleComposerCommand = async (commandId: string) => {
    if (commandId === "clear") {
      await handleClearConversation();
      return;
    }
    if (commandId === "start" || commandId === "pause" || commandId === "continue" || commandId === "terminate") {
      setComposerValue("");
      if (activeDraftComposerKey != null) {
        setDraftComposerValues((current) => ({
          ...current,
          [activeDraftComposerKey]: "",
        }));
      }
      await handleWorkspaceControl(commandId);
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

  const startRestoreDrag = (
    event: React.PointerEvent<HTMLButtonElement>,
    onRestore: () => void,
  ) => {
    if (event.pointerType === "mouse" && event.button !== 0) {
      return;
    }
    event.preventDefault();
    const button = event.currentTarget;
    const containerHeight = button.parentElement?.getBoundingClientRect().height ?? window.innerHeight;
    railRestoreDragRef.current = {
      pointerId: event.pointerId,
      pointerY: event.clientY,
      originTop: railRestoreTop,
      containerHeight,
      moved: false,
    };
    button.setPointerCapture(event.pointerId);

    const handleMove = (moveEvent: PointerEvent) => {
      const current = railRestoreDragRef.current;
      if (!current || moveEvent.pointerId !== current.pointerId) {
        return;
      }
      const deltaY = moveEvent.clientY - current.pointerY;
      const moved = current.moved || Math.abs(deltaY) > 3;
      railRestoreDragRef.current = {
        ...current,
        moved,
      };
      setRailRestoreTop(clampRailRestoreTop(current.originTop + deltaY, current.containerHeight));
    };

    const handleUp = (upEvent: PointerEvent) => {
      const current = railRestoreDragRef.current;
      if (!current || upEvent.pointerId !== current.pointerId) {
        return;
      }
      railRestoreDragRef.current = null;
      button.releasePointerCapture(upEvent.pointerId);
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
      window.removeEventListener("pointercancel", handleUp);
      if (!current.moved) {
        onRestore();
      }
    };

    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp);
    window.addEventListener("pointercancel", handleUp);
  };

  const startRailRestoreDrag = (event: React.PointerEvent<HTMLButtonElement>) => {
    startRestoreDrag(event, () => setRailCollapsed(false));
  };

  const startListRestoreDrag = (event: React.PointerEvent<HTMLButtonElement>) => {
    startRestoreDrag(event, () => setListCollapsed(false));
  };

  const renderEmptyPanel = (title: string, body: string) => (
    <div style={panelEmptyStyle()}>
      <div style={{ fontSize: "var(--font-size-base)", color: "var(--chat-text-primary)", fontWeight: 500 }}>{title}</div>
      <div>{body}</div>
    </div>
  );

  const renderRunsPanel = (runs: AgentRunRecord[]) => {
    const openRuns = runs.filter((run) => isOpenRunStatus(run.status)).length;
    const completedRuns = runs.filter((run) => run.status === "completed").length;
    const waitingRuns = runs.filter((run) => run.status === "waiting_human" || run.status === "blocked").length;
    const failedRuns = runs.filter((run) => run.status === "failed" || run.status === "cancelled").length;
    return (
      <div className="agent-runs">
        <section className="agent-runs__summary">
          <div><span>{copy("Open", "进行中")}</span><strong>{openRuns}</strong></div>
          <div><span>{copy("Waiting / blocked", "待处理/受阻")}</span><strong>{waitingRuns}</strong></div>
          <div><span>{copy("Completed", "已完成")}</span><strong>{completedRuns}</strong></div>
          <div><span>{copy("Failed", "失败/取消")}</span><strong>{failedRuns}</strong></div>
        </section>
        <section className="agent-runs__section-head">
          <div>
            <h4>{copy("Run timeline", "运行实例")}</h4>
            <p>{copy("This view shows execution state and operator actions. Business results are summarized under Work outputs.", "这里展示执行状态和人工操作；业务结果在工作产出中归档。")}</p>
          </div>
          <StatusBadge tone={openRuns ? "warning" : "neutral"}>{runs.length}</StatusBadge>
        </section>
        {!runs.length ? (
          <section className="chat-card">
            <div className="chat-list-item__summary">
              {copy("The backend has not reported any runs for this agent yet.", "当前 Agent 还没有返回运行记录。")}
            </div>
          </section>
        ) : null}
        {runs.map((run) => (
          <section key={run.id} className="agent-runs__card">
            <div className="agent-runs__card-head">
              <div>
                <div className="chat-list-item__title">{run.title}</div>
                <div className="chat-list-item__meta">
                  {copy("Updated", "更新时间")} · {formatDateTime(run.updatedAt)}
                </div>
              </div>
              <StatusBadge tone={run.status === "completed" ? "positive" : run.status === "failed" ? "critical" : "warning"}>
                {describeRunStatus(run)}
              </StatusBadge>
            </div>
            <div className="agent-runs__body">
              <div>
                <span>{copy("Business intent", "业务意图")}</span>
                <p>{run.summary || copy("No run summary returned yet.", "本轮还没有返回运行摘要。")}</p>
              </div>
              <div>
                <span>{copy("Execution state", "执行状态")}</span>
                <p>
                  {run.startedAt ? `${copy("Started", "开始")} · ${formatDateTime(run.startedAt)} · ` : ""}
                  {copy("Updated", "更新")} · {formatDateTime(run.updatedAt)}
                </p>
              </div>
              <div>
                <span>{copy("Run phase", "运行阶段")}</span>
                <p>{runPhaseLabel(run, copy)}</p>
              </div>
            </div>
            {activeAgent !== "assistant" ? (
              <div className="agent-runs__actions">
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
                      focusAgent(activeAgent, "conversation");
                      setSelectedConversation((current) => ({
                        ...current,
                        [activeAgent]: conversationId ?? current[activeAgent],
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
                <button
                  type="button"
                  className="chat-overlay__header-button"
                  disabled={runActionBusyId === run.id}
                  onClick={() => void handleRestartRun(run)}
                >
                  {runActionBusyId === run.id ? copy("Working…", "处理中…") : copy("Restart", "重新开始")}
                </button>
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

  const renderCapabilitiesPanel = (tools: AgentToolSummary[], skills: SkillRecord[], memories: AgentMemorySummary[], mcps: McpServerRecord[]) => {
    const memoryTools = tools.filter((tool) => tool.sourceKind === "memory_tool");
    const businessTools = tools
      .filter((tool) => tool.businessTool)
      .sort((left, right) => left.name.localeCompare(right.name));
    const systemTools = tools
      .filter((tool) => !tool.businessTool && tool.sourceKind !== "mcp_tool" && !/mcp/i.test(tool.serverName) && !memoryTools.includes(tool))
      .sort((left, right) => left.name.localeCompare(right.name));
    const toToolItem = (tool: AgentToolSummary, category: CapabilityCategoryKey): CapabilityItem => ({
      key: `tool:${tool.id}`,
      kind: "tool",
      category,
      label: tool.name,
      description: tool.description || tool.businessDomain || tool.resourceTargetKind || tool.endpoint || tool.serverName,
      metaLabel: copy("Source", "来源"),
      meta: tool.source,
      status: tool.status,
      tone: capabilityStatusTone(tool.status, tool.enabled),
      tool,
    });
    const toMcpItem = (mcp: McpServerRecord): CapabilityItem => ({
      key: `mcp:${mcp.id}`,
      kind: "mcp",
      category: "mcp",
      label: mcp.name || mcp.serverKey,
      description: mcp.healthError || `${mcp.transportKind} · ${mcp.protocol}`,
      metaLabel: copy("Server", "服务"),
      meta: mcp.serverKey,
      status: mcp.enabled ? mcp.healthStatus : "disabled",
      tone: capabilityStatusTone(mcp.enabled ? mcp.healthStatus : "disabled", mcp.enabled),
      mcp,
    });
    const groups: Array<{ key: CapabilityCategoryKey; label: string; description: string; items: CapabilityItem[] }> = [
      {
        key: "business",
        label: copy("Business tools", "招聘业务工具"),
        description: copy("Executable recruiting tools exposed by the product capability layer.", "由招聘业务能力层暴露的可执行工具。"),
        items: businessTools.map((tool) => toToolItem(tool, "business")),
      },
      {
        key: "skills",
        label: "Skills",
        description: copy("Reusable recruiting skills from the backend skill registry, filtered to trial or active records.", "来自后端 Skill 注册表的可复用招聘技能，只展示 trial 或 active。"),
        items: skills
          .slice()
          .sort((left, right) => left.name.localeCompare(right.name))
          .map((skill) => ({
            key: `skill:${skill.id}`,
            kind: "skill",
            category: "skills",
            label: skill.name,
            description: skill.summary || skill.description || copy("No summary yet.", "暂无摘要。"),
            metaLabel: copy("Source", "来源"),
            meta: copy("Skill registry", "技能库"),
            status: skill.health,
            tone: toneForHealth(skill.health),
            skill,
          })),
      },
      {
        key: "mcp",
        label: copy("External MCP", "外部 MCP"),
        description: copy("Configured MCP servers. Tools are shown inside each server instead of counted as separate MCP entries.", "按 MCP 服务查看配置；工具收敛在对应 MCP 内，不再把每个工具当成一个 MCP。"),
        items: mcps.slice().sort((left, right) => left.name.localeCompare(right.name)).map(toMcpItem),
      },
      {
        key: "memory",
        label: copy("Context / Memory", "上下文/记忆"),
        description: copy("Agent file-memory tools and scoped memory files used as context, not recruiting business facts.", "Agent file memory 工具与上下文文件，不等同于候选人/JD 等业务事实。"),
        items: [
          ...memoryTools.sort((left, right) => left.name.localeCompare(right.name)).map((tool) => toToolItem(tool, "memory")),
          ...memories
          .slice()
          .sort((left, right) => left.title.localeCompare(right.title))
          .map((memory): CapabilityItem => ({
            key: `memory:${memory.id}`,
            kind: "memory",
            category: "memory",
            label: memory.title,
            description: memory.summary,
            metaLabel: copy("Scope", "范围"),
            meta: memory.scope,
            status: memory.status,
            tone: capabilityStatusTone(memory.status),
            memory,
          })),
        ],
      },
      {
        key: "system",
        label: copy("System tools", "系统工具"),
        description: copy("Non-business support tools kept separate from recruiting actions.", "与招聘业务动作分开的系统辅助工具。"),
        items: systemTools.map((tool) => toToolItem(tool, "system")),
      },
    ];
    const selectedGroup =
      groups.find((group) => group.key === selectedCapabilityKey)
      ?? groups.find((group) => group.items.length)
      ?? groups[0];
    const selectedItems = selectedGroup?.items ?? [];

    return (
      <div className="agent-capabilities">
        <aside className="agent-capabilities__sidebar" aria-label={copy("Capability groups", "能力分组")}>
          {groups.map((group) => (
            <button
              key={group.key}
              type="button"
              className="agent-capabilities__group-button"
              data-active={group.key === selectedGroup?.key}
              onClick={() => setSelectedCapabilityKey(group.key)}
            >
              <span>{group.label}</span>
              <strong>{group.items.length}</strong>
              <small>{group.description}</small>
            </button>
          ))}
        </aside>
        <div className="agent-capabilities__detail">
          {selectedGroup ? (
            <>
              <div className="agent-capabilities__detail-head">
                <div>
                  <div className="chat-card__eyebrow">{copy("Capability group", "能力分组")}</div>
                  <h4>{selectedGroup.label}</h4>
                </div>
                <StatusBadge tone={selectedItems.length ? "positive" : "neutral"}>{selectedItems.length}</StatusBadge>
              </div>
              <div className="chat-list-item__summary">{selectedGroup.description}</div>
              <div className="agent-capabilities__tool-list">
                {selectedItems.map((item) => (
                  <section key={item.key} className="agent-capabilities__tool-card">
                    <div className="agent-capabilities__tool-card-head">
                      <div>
                        <strong>{item.label}</strong>
                        <span>{item.description || copy("No description returned.", "暂无描述。")}</span>
                      </div>
                      <StatusBadge tone={item.tone}>{item.status}</StatusBadge>
                    </div>
                    <div className="chat-card__meta-list">
                      <span>{item.metaLabel} · {item.meta}</span>
                      {item.tool ? <span>{copy("Risk", "风险")} · {item.tool.riskLevel}</span> : null}
                      {item.tool ? <span>{copy("Permission", "权限")} · {item.tool.permissionScope || copy("default", "默认")}</span> : null}
                      {item.tool?.businessDomain ? <span>{copy("Domain", "领域")} · {item.tool.businessDomain}</span> : null}
                      {item.tool?.resourceTargetKind ? <span>{copy("Resource", "资源")} · {item.tool.resourceTargetKind}</span> : null}
                      {item.tool?.capabilities.length ? <span>{copy("Tags", "标签")} · {item.tool.capabilities.join(", ")}</span> : null}
                      {item.tool?.endpoint ? <span>{copy("Endpoint", "地址")} · {item.tool.endpoint}</span> : null}
                      {item.mcp ? <span>{copy("Key", "键")} · {item.mcp.serverKey}</span> : null}
                      {item.mcp ? <span>{copy("Transport", "传输")} · {item.mcp.transportKind}</span> : null}
                      {item.mcp ? <span>{copy("Protocol", "协议")} · {item.mcp.protocol}</span> : null}
                      {item.mcp?.endpoint ? <span>{copy("Endpoint", "地址")} · {item.mcp.endpoint}</span> : null}
                      {item.mcp?.presetKey ? <span>{copy("Preset", "预置")} · {item.mcp.presetKey}</span> : null}
                      {item.mcp ? <span>{copy("Tools", "工具")} · {item.mcp.tools.length}</span> : null}
	                      {item.skill ? <span>{copy("Version", "版本")} · {item.skill.version}</span> : null}
	                      {item.skill ? <span>{copy("Stage", "阶段")} · {item.skill.boundStage}</span> : null}
	                      {item.skill ? <span>{copy("Platform", "平台")} · {item.skill.platform}</span> : null}
	                      {item.skill ? (
	                        <span>
	                          {copy("Provenance", "来源细节")} · {stringField(
	                            isRecord(item.skill.skillMetadata) ? item.skill.skillMetadata : undefined,
	                            "source",
	                            "source_path",
	                            "path",
	                            "learned_from",
	                            "proposed_by",
	                            "origin",
	                          ) ?? copy("not provided by backend", "后端未提供")}
	                        </span>
	                      ) : null}
	                      {item.skill?.riskLevel ? <span>{copy("Risk", "风险")} · {item.skill.riskLevel}</span> : null}
                      {item.memory ? <span>{copy("Scope", "范围")} · {item.memory.scope}</span> : null}
                      {item.memory ? <span>{copy("Updated", "更新时间")} · {formatDateTime(item.memory.updatedAt)}</span> : null}
                    </div>
                    <div className="agent-capabilities__summary-grid">
                      {item.tool ? (
                        <>
                          {hasRecordEntries(item.tool.inputSchema) ? <div><span>{copy("Input schema", "输入 Schema")}</span><strong>{compactJsonSummary(item.tool.inputSchema, "")}</strong></div> : null}
                          {hasRecordEntries(item.tool.outputSchema) ? <div><span>{copy("Output schema", "输出 Schema")}</span><strong>{compactJsonSummary(item.tool.outputSchema, "")}</strong></div> : null}
                          {hasRecordEntries(item.tool.toolMetadata) ? <div><span>{copy("Metadata", "元数据")}</span><strong>{metadataSummary(item.tool.toolMetadata, "")}</strong></div> : null}
                        </>
                      ) : null}
                      {item.mcp ? (
                        <>
                          {hasRecordEntries(item.mcp.standardConfig) ? <div><span>{copy("MCP config", "MCP 配置")}</span><strong>{mcpStandardConfigSummary(item.mcp)}</strong></div> : null}
                          {hasRecordEntries(item.mcp.serverMetadata) ? <div><span>{copy("Server metadata", "服务元数据")}</span><strong>{metadataSummary(item.mcp.serverMetadata, "")}</strong></div> : null}
                          {hasRecordEntries(item.mcp.authConfig) ? <div><span>{copy("Auth config", "认证配置")}</span><strong>{metadataSummary(item.mcp.authConfig, "")}</strong></div> : null}
                        </>
                      ) : null}
                      {item.skill ? (
                        <>
                          <div><span>{copy("Input schema", "输入 Schema")}</span><strong>{compactJsonSummary(item.skill.inputSchema, copy("Not provided", "未提供"))}</strong></div>
                          <div><span>{copy("Output schema", "输出 Schema")}</span><strong>{compactJsonSummary(item.skill.outputSchema, copy("Not provided", "未提供"))}</strong></div>
                          <div><span>{copy("Metadata", "元数据")}</span><strong>{metadataSummary(item.skill.skillMetadata, copy("Not provided", "未提供"))}</strong></div>
                        </>
                      ) : null}
                      {item.memory ? (
                        <div><span>{copy("Metadata", "元数据")}</span><strong>{metadataSummary(item.memory.metadata, copy("Not provided", "未提供"))}</strong></div>
                      ) : null}
                    </div>
                    {item.mcp && hasRecordEntries(item.mcp.standardConfig) ? (
                      <pre className="agent-capabilities__mcp-config">{mcpStandardConfigJson(item.mcp)}</pre>
                    ) : null}
                    {item.mcp?.tools.length ? (
                      <div className="agent-capabilities__mcp-tool-list">
                        {item.mcp.tools.map((tool) => (
                          <div key={tool.id || `${item.mcp?.id}:${tool.name}`} className="agent-capabilities__mcp-tool">
                            <strong>{tool.name}</strong>
                            {tool.description ? <span>{tool.description}</span> : null}
                            <small>
                              {[tool.riskLevel, tool.capabilities.length ? tool.capabilities.join(", ") : ""].filter(Boolean).join(" · ")}
                            </small>
                            {hasRecordEntries(tool.parameters) ? <small>{copy("Input", "输入")} · {compactJsonSummary(tool.parameters, "")}</small> : null}
                            {hasRecordEntries(tool.toolMetadata) ? <small>{copy("Metadata", "元数据")} · {metadataSummary(tool.toolMetadata, "")}</small> : null}
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </section>
                ))}
                {!selectedItems.length ? (
                  <div className="chat-list-item__summary">{copy("No items in this group.", "当前分组暂无条目。")}</div>
                ) : null}
              </div>
            </>
          ) : (
            <div className="chat-list-item__summary">{copy("No capabilities returned for this agent.", "后端暂未返回该 Agent 的能力。")}</div>
          )}
        </div>
      </div>
    );
  };

  const renderOutputsPanel = (workspace: AgentWorkspaceRecord) => {
    const policy = workspace.config.recruitingPolicy;
    const outputStandards = [
      {
        label: copy("Verdict", "候选人结论"),
        value: `${copy("Composite pass", "综合通过")} ${policy.thresholds.compositePass}+`,
        detail: copy("Must include pass, reject, or manual-review recommendation with evidence refs.", "必须给出通过、淘汰或人工复核建议，并附证据引用。"),
      },
      {
        label: copy("Evidence", "证据"),
        value: copy("JD + resume + communication", "JD + 简历 + 沟通"),
        detail: copy("Online resume, offline resume, and communication evidence stay separated.", "在线简历、离线简历和沟通证据必须分开记录。"),
      },
      {
        label: copy("Business state", "业务状态"),
        value: copy("created / updated / skipped", "新增/更新/跳过"),
        detail: copy("Outputs should name affected JD, application, candidate, and next step.", "产出必须说明影响的 JD、投递记录、候选人和下一步。"),
      },
      {
        label: copy("Governance", "治理"),
        value: copy("approval before side effects", "副作用前审批"),
        detail: copy("Messaging, upload, deletion, and external write actions stay approval-gated.", "发消息、上传、删除和外部写入仍需要审批。"),
      },
    ];
    return (
      <div className="agent-outputs">
        <section className="agent-outputs__standard">
          <div className="agent-runs__section-head">
            <div>
              <h4>{copy("Output acceptance standard", "产出验收标准")}</h4>
              <p>{copy("Work output means a business result, not a raw tool event or provider payload.", "工作产出指业务结果，不是原始工具事件或模型 payload。")}</p>
            </div>
          </div>
          <div className="agent-outputs__standard-grid">
            {outputStandards.map((item) => (
              <div key={item.label}>
                <span>{item.label}</span>
                <strong>{item.value}</strong>
                <p>{item.detail}</p>
              </div>
            ))}
          </div>
        </section>
        <section className="agent-runs__section-head">
          <div>
            <h4>{copy("Business result projection", "业务结果投影")}</h4>
            <p>{copy("The current backend workspace does not expose dedicated business result rows yet. Run events and approvals stay in Run records and are not treated as work outputs.", "当前后端工作区还没有返回专门的业务结果记录。运行事件与审批仍归在运行记录中，不当作工作产出。")}</p>
          </div>
          <StatusBadge tone="neutral">{copy("Not available", "待接入")}</StatusBadge>
        </section>
        <section className="agent-outputs__item">
          <div className="chat-list-item__summary">
            {copy(
              "Expected backend fields: affected JD, affected application/candidate, status, created/updated/skipped counts, blocker, next step, and evidence references.",
              "期望后端字段：影响的 JD、投递记录/候选人、业务状态、新增/更新/跳过数量、阻塞原因、下一步和证据引用。",
            )}
          </div>
        </section>
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

    if (!activeWorkspace) {
      return renderEmptyPanel(copy("Agent unavailable", "Agent 暂不可用"), copy("The current workspace has not returned an agent definition yet.", "当前工作区还没有返回 AgentDefinition。"));
    }

    return (() => {
      const renderBaseCapabilityReadOnly = (draft: AgentConfigDraft) => {
        const systemInstruction = firstReadableText(
          "-",
          draft.systemPrompt,
          activeWorkspace.config.systemPrompt,
          activeWorkspace.agent.description,
        );
        const provider = firstReadableText("-", activeWorkspace.productAdapterConfig.providerLabel, "OpenAI compatible");
        const model = firstReadableText("-", activeWorkspace.productAdapterConfig.modelLabel, activeWorkspace.agent.defaultModel);
        const productAdapter = firstReadableText("-", activeWorkspace.productBinding.productAdapterKey);
        const agentDefinition = firstReadableText("-", activeWorkspace.agentDefinition.key, activeWorkspace.agent.definitionKey);
        const outputSummary = firstReadableText(
          jsonDraftReadableSummary(draft.outputPolicyJson, copy("Defined by product adapter output policy.", "由产品适配器的输出策略定义。"), "response_standard", "responseStyle", "output_standard"),
          draft.successCriteriaText,
        );
        const rows: BaseCapabilityRow[] = [
          {
            label: copy("Identity", "身份设定"),
            detail: firstReadableText("-", draft.identityStatement, activeWorkspace.agent.description),
          },
          {
            label: copy("Responsibilities", "职责描述"),
            detail: firstReadableText("-", draft.dutiesText, activeWorkspace.agent.activeInstruction, agentModeSummary(activeAgent)),
          },
          {
            label: copy("Boundaries", "行为边界"),
            detail: firstReadableText("-", draft.boundariesText, activeWorkspace.config.boundaries.join("\n")),
          },
          {
            label: copy("Tool boundaries", "工具使用边界"),
            detail: jsonDraftReadableSummary(
              draft.toolScopeJson,
              copy("Tools are limited by product capabilities, business permissions, and configured approval gates.", "工具使用受产品能力、业务权限和已配置审批节点限制。"),
              "capability_usage",
              "tool_usage",
              "allowed_tools",
            ),
          },
          {
            label: copy("Human confirmation", "人工确认规则"),
            detail: jsonDraftReadableSummary(
              draft.permissionPolicyJson,
              copy("Approval is determined by business tool permissions, with auto-approval as the default unless a tool is gated.", "审批由业务工具权限决定；默认自动通过，关键工具可配置为审批节点。"),
              "approval_rules",
              "approval_triggers",
              "write_policy",
            ),
          },
          {
            label: copy("Run context", "运行上下文"),
            detail: jsonDraftReadableSummary(
              draft.contextPolicyJson,
              activeAgent === "autonomous"
                ? copy("Run context is assembled from selected JDs, candidate facts, resume evidence, communication state, scores, and current workflow state.", "运行上下文由选中 JD、候选人事实、简历证据、沟通状态、评分和当前流程状态装配。")
                : copy("Chat context is scoped to the current conversation and relevant recruiting records.", "对话上下文限定在当前会话与相关招聘记录内。"),
              "run_context",
              "context_scope",
              "sources",
            ),
          },
          {
            label: copy("Context retention", "上下文留存"),
            detail: jsonDraftReadableSummary(
              draft.memoryPolicyJson,
              activeAgent === "autonomous"
                ? copy("Candidate/JD follow-up context is isolated; reusable knowledge must not mix temporary blockers or unrelated candidate facts.", "候选人/JD 跟进上下文独立隔离；可复用知识不得混入临时阻塞或无关候选人事实。")
                : copy("Only reusable collaboration knowledge can be retained; transient chat facts remain scoped to the turn or conversation.", "只沉淀可复用协作知识；临时对话事实保留在当前轮次或会话范围内。"),
              "reusable_knowledge",
              "retention_rules",
              "memory_scope",
            ),
          },
          {
            label: copy("Output standard", "产出标准"),
            detail: outputSummary,
          },
          {
            label: copy("Stable workflow boundary", "稳定流程边界"),
            detail: activeAgent === "autonomous"
              ? copy("Daily recruiting policy is maintained in JD strategy, execution SOP, site scope, and tool permissions. Base capability only protects shared state, approvals, duplicate actions, and governed writes.", "日常招聘策略在 JD 策略、执行 SOP、站点范围和工具权限中维护；基础能力只保护共享状态、审批、重复动作和受控写入。")
              : copy("AI assistant remains conversation-led: it explains, drafts, checks evidence, and hands off write actions through governed tools.", "AI助手由对话驱动：负责解释、草拟、核对证据，并通过受治理工具交接写入动作。"),
          },
          {
            label: copy("Configuration source", "配置来源"),
            detail: `${copy("Definition", "定义")} ${agentDefinition} · ${copy("Product workflow", "产品流程")} ${productAdapter}`,
          },
        ];

        return (
          <div className="agent-config-base-readonly">
            <div className="agent-config-base-runtime">
              <div><span>{copy("Provider", "Provider")}</span><strong>{provider}</strong></div>
              <div><span>{copy("Model", "模型")}</span><strong>{model}</strong></div>
              <div><span>{copy("Account", "账户")}</span><strong>{settingsSnapshot.platform.account}</strong></div>
              <div><span>{copy("Mode", "模式")}</span><strong>{agentModeLabel(activeAgent)}</strong></div>
            </div>

            <div className="agent-config-base-table">
              {rows.map((row) => (
                <div key={row.label}>
                  <span>{row.label}</span>
                  <p>{row.detail}</p>
                </div>
              ))}
            </div>

            <div className="agent-config-readonly-block">
              <div>
                <strong>{copy("Built-in behavior statement", "内置行为说明")}</strong>
                <span>{copy("Visible for inspection only. It is not the daily recruiting policy entry and changes through product releases.", "仅用于审阅当前版本的基础行为，不作为日常招聘策略入口。")}</span>
              </div>
              <button type="button" className="chat-overlay__header-button" onClick={() => setSystemPromptExpanded((current) => !current)}>
                {systemPromptExpanded ? copy("Hide", "收起") : copy("View", "查看")}
              </button>
            </div>
            {systemPromptExpanded ? <pre className="agent-config-preview">{systemInstruction}</pre> : null}
          </div>
        );
      };

      if (String(activeAgent) === "jd_sync") {
        const updateJdSyncSop = (field: keyof AutomationExecutionSopDraft, value: string) => {
          setJdSyncConfigDraft((current) => ({
            ...current,
            executionSop: {
              ...current.executionSop,
              [field]: value,
            },
          }));
        };
        const updateJdSyncPolicy = (value: string) => {
          setJdSyncConfigDraft((current) => ({
            ...current,
            syncPolicy: {
              ...current.syncPolicy,
              jdSyncText: value,
            },
          }));
        };
        const siteReady = Boolean(jdSyncConfigDraft.executionSop.siteEntryUrl.trim());
        const readinessBlockers = validateJdSyncLaunchReadiness(jdSyncConfigDraft);
        return (
          <div className="agent-config agent-config--automation">
            <div className="agent-config-automation-layout">
              <div className="agent-config-automation-main">
                <div className="agent-config-automation-actions">
                  <button
                    type="button"
                    className="chat-overlay__header-button"
                    disabled={savingConfig}
                    onClick={() => {
                      setAgentConfigDrafts((current) => ({
                        ...current,
                        jd_sync: agentConfigDraftFromWorkspace(workspaces.jd_sync),
                      }));
                      setJdSyncConfigDraft(automationConfigDraftFromWorkspace(workspaces.jd_sync, [], "jd_sync"));
                    }}
                  >
                    {copy("Reset", "重置")}
                  </button>
                  <button type="button" className="chat-overlay__header-button" disabled={savingConfig} onClick={() => void handleSaveConfig()}>
                    {savingConfig ? copy("Saving…", "保存中…") : copy("Save configuration", "保存配置")}
                  </button>
                </div>
                <section className="agent-config-independent-panel agent-config-sop-panel">
                  <div className="agent-config-sop-section">
                    <div className="agent-config-panel-head">
                      <div>
                        <h4>{copy("JD sync site", "JD 同步网站")}</h4>
                        <p>{copy("This agent only syncs job descriptions from a logged-in recruiting site.", "这个 Agent 只从已登录招聘网站同步 JD，不处理候选人。")}</p>
                      </div>
                    </div>
                    <div className="agent-config-readiness" data-state={siteReady && !readinessBlockers.length ? "ready" : "blocked"}>
                      <strong>{siteReady && !readinessBlockers.length ? copy("Ready to start", "可启动") : copy("Configuration missing", "配置缺失")}</strong>
                      <span>
                        {readinessBlockers.length
                          ? `${copy("Complete before start:", "启动前需要补全：")} ${readinessBlockers.join("；")}`
                          : copy("Saved site configuration can be used to start JD sync.", "已具备启动 JD 同步所需的网站配置。")}
                      </span>
                    </div>
                    <div className="agent-config-editor__fields">
                      <label className="agent-config-editor__field agent-config-editor__field--wide">
                        <span>{copy("Recruiting target page URL", "招聘网站目标网页 URL")}</span>
                        <FormInput
                          placeholder="https://..."
                          value={jdSyncConfigDraft.executionSop.siteEntryUrl}
                          onChange={(event) => updateJdSyncSop("siteEntryUrl", event.target.value)}
                        />
                      </label>
                    </div>
                    <label className="agent-config-editor__field">
                      <span>{copy("Site execution boundaries", "站点执行边界")}</span>
                      <FormTextarea
                        value={jdSyncConfigDraft.executionSop.siteAccessRulesText}
                        onChange={(event) => updateJdSyncSop("siteAccessRulesText", event.target.value)}
                        className="chat-overlay-form-textarea--medium"
                      />
                    </label>
                    <label className="agent-config-editor__field">
                      <span>{copy("JD sync policy", "JD 同步策略")}</span>
                      <FormTextarea
                        value={jdSyncConfigDraft.syncPolicy.jdSyncText}
                        onChange={(event) => updateJdSyncPolicy(event.target.value)}
                        className="chat-overlay-form-textarea--medium"
                      />
                    </label>
                    <div className="chat-empty-inline">
                      {automationJobDescriptions.length
                        ? copy(`${automationJobDescriptions.length} JD records are currently in the workspace.`, `当前工作区已有 ${automationJobDescriptions.length} 个 JD。`)
                        : copy("No JD records yet. Save configuration, then run JD Sync.", "当前还没有 JD。请先保存配置，再运行 JD 同步。")}
                    </div>
                  </div>
                </section>
              </div>
            </div>
          </div>
        );
      }

      if (String(activeAgent) === "autonomous") {
        const activeAgentConfig = agentConfigDrafts.autonomous;
        const selectedJob = automationJobDescriptions.find((job) => automationJobId(job) === selectedAutomationJobId) ?? null;
        const selectedJobStrategy = selectedAutomationJobId ? automationConfigDraft.jobStrategies[selectedAutomationJobId] : undefined;
        const selectedJobEnabled = selectedAutomationJobId ? automationConfigDraft.selectedRunJobIds.includes(selectedAutomationJobId) : false;
        const selectedJobRecommendation = selectedJob
          ? recommendedAutomationJobStrategy(selectedJob, recruitingPolicyPayloadFromDraft(activeAgentConfig.recruitingPolicy))
          : null;
        const selectedLaunchJobs = automationConfigDraft.selectedRunJobIds
          .map((jobId) => {
            const job = automationJobDescriptions.find((item) => automationJobId(item) === jobId);
            const strategy = automationConfigDraft.jobStrategies[jobId];
            return job && strategy ? { jobId, job, strategy } : null;
          })
          .filter((item): item is { jobId: string; job: JobDescriptionSummaryRecord; strategy: AutomationJobStrategyDraft } => Boolean(item));
        const businessTools = activeWorkspace.tools.filter((tool) => tool.businessTool);
        const selectedJobsHaveStrategy = selectedLaunchJobs.every((item) =>
          item.strategy.screeningCriteria.trim()
          && item.strategy.onlineResumeCriteria.trim()
          && item.strategy.offlineResumeCriteria.trim()
          && item.strategy.compositeScoring.trim()
          && item.strategy.manualReviewRules.trim()
          && item.strategy.onlineResumePass.trim()
          && item.strategy.offlineResumePass.trim()
          && item.strategy.compositePass.trim()
          && item.strategy.manualReviewMin.trim(),
        );
        const siteReady = Boolean(
          automationConfigDraft.executionSop.siteEntryUrl.trim(),
        );
        const siteAndJdReady = siteReady && automationJobDescriptions.length > 0;
        const sopReady = Boolean(automationConfigDraft.executionSop.stepsText.trim());
        const schedulerReady = Boolean(
          automationConfigDraft.activationPolicy.scanIntervalMinutes.trim()
          && automationConfigDraft.activationPolicy.candidatePoolTarget.trim()
          && automationConfigDraft.activationPolicy.backlogThreshold.trim()
          && automationConfigDraft.activationPolicy.priorityDiscoveryWeight.trim()
          && automationConfigDraft.activationPolicy.priorityUnreadMessageWeight.trim()
          && automationConfigDraft.activationPolicy.priorityScoringBacklogWeight.trim()
          && automationConfigDraft.activationPolicy.priorityApprovalWeight.trim()
          && automationConfigDraft.activationPolicy.priorityJdGapWeight.trim()
          && automationConfigDraft.activationPolicy.messageSlaMinutes.trim()
          && automationConfigDraft.activationPolicy.siteCooldownMinutes.trim()
          && automationConfigDraft.activationPolicy.retryCooldownMinutes.trim()
          && automationConfigDraft.activationPolicy.maxActionsPerHour.trim()
          && automationConfigDraft.activationPolicy.maxConsecutiveErrors.trim(),
        );
        const automationConfigPages: Array<{ key: AutomationConfigPageKey; label: string; meta: string; passed: boolean }> = [
          {
            key: "entry",
            label: copy("Recruiting site", "招聘网站"),
            meta: siteReady
              ? `${readableUrlHost(automationConfigDraft.executionSop.siteEntryUrl)} · ${automationJobDescriptions.length} JD`
              : copy("Required", "必填"),
            passed: siteAndJdReady,
          },
          {
            key: "jd",
            label: copy("JD strategy", "JD 策略"),
            meta: selectedLaunchJobs.length ? `${selectedLaunchJobs.length}/${automationJobDescriptions.length} JD` : copy("Required", "必填"),
            passed: selectedLaunchJobs.length > 0 && selectedJobsHaveStrategy,
          },
          {
            key: "sop",
            label: copy("Execution SOP", "执行 SOP"),
            meta: `${linesFromText(automationConfigDraft.executionSop.stepsText).length}`,
            passed: sopReady,
          },
          {
            key: "activation",
            label: copy("Scheduling rules", "调度规则"),
            meta: copy("Rules", "规则"),
            passed: schedulerReady,
          },
          {
            key: "tools",
            label: copy("Tool permissions", "工具权限"),
            meta: `${businessTools.length}`,
            passed: true,
          },
          {
            key: "base",
            label: copy("Base capability", "基础能力"),
            meta: copy("Read-only", "只读"),
            passed: true,
          },
        ];
        const updateAutomationSop = (field: keyof AutomationExecutionSopDraft, value: string) => {
          setAutomationConfigDraft((current) => ({
            ...current,
            executionSop: {
              ...current.executionSop,
              [field]: value,
            },
          }));
        };
        const updateAutomationActivationPolicy = <K extends keyof AutomationActivationPolicyDraft>(
          field: K,
          value: AutomationActivationPolicyDraft[K],
        ) => {
          setAutomationConfigDraft((current) => ({
            ...current,
            activationPolicy: {
              ...current.activationPolicy,
              [field]: value,
            },
          }));
        };
        const updateAutomationStrategy = (
          jobId: string,
          field: keyof AutomationJobStrategyDraft,
          value: string,
        ) => {
          setAutomationConfigDraft((current) => ({
            ...current,
            jobStrategies: {
              ...current.jobStrategies,
              [jobId]: {
                ...current.jobStrategies[jobId],
                [field]: value,
              },
            },
          }));
        };
        const toggleAutomationRunJob = (jobId: string, checked: boolean) => {
          setAutomationConfigDraft((current) => ({
            ...current,
            selectedRunJobIds: checked
              ? Array.from(new Set([...current.selectedRunJobIds, jobId]))
              : current.selectedRunJobIds.filter((id) => id !== jobId),
          }));
          setSelectedAutomationJobId(jobId);
        };
        const selectAllAutomationJobs = () => {
          const allJobIds = automationJobDescriptions.map(automationJobId).filter((id): id is string => Boolean(id));
          setAutomationConfigDraft((current) => ({
            ...current,
            selectedRunJobIds: allJobIds,
          }));
          setSelectedAutomationJobId((current) => current ?? allJobIds[0] ?? null);
        };
        const clearAllAutomationJobs = () => {
          setAutomationConfigDraft((current) => ({
            ...current,
            selectedRunJobIds: [],
          }));
        };
        const applyRecommendedAutomationStrategy = (job: JobDescriptionSummaryRecord) => {
          const jobId = automationJobId(job);
          if (!jobId) {
            return;
          }
          setAutomationConfigDraft((current) => ({
            ...current,
            jobStrategies: {
              ...current.jobStrategies,
              [jobId]: recommendedAutomationJobStrategy(job, recruitingPolicyPayloadFromDraft(activeAgentConfig.recruitingPolicy)),
            },
          }));
        };
        const updateToolApprovalMode = (toolId: string, mode: AutomationToolApprovalMode) => {
          setAutomationConfigDraft((current) => ({
            ...current,
            toolApprovalModes: {
              ...current.toolApprovalModes,
              [toolId]: mode,
            },
          }));
        };
        const renderLineEditor = (
          value: string,
          onChange: (next: string) => void,
          addLabel: string,
        ) => {
          const rows = linesFromText(value);
          const normalizedRows = rows.length ? rows : [""];
          const setRows = (nextRows: string[]) => {
            onChange(textFromLines(nextRows));
          };
          return (
            <div className="agent-config-line-editor">
              {normalizedRows.map((line, index) => (
                <div key={`${index}-${normalizedRows.length}`} className="agent-config-line-editor__row">
                  <span>{index + 1}</span>
                  <FormInput
                    value={line}
                    onChange={(event) => {
                      const nextRows = [...normalizedRows];
                      nextRows[index] = event.target.value;
                      setRows(nextRows);
                    }}
                  />
                  <button
                    type="button"
                    className="agent-config-line-editor__icon-button"
                    onClick={() => setRows(normalizedRows.filter((_, rowIndex) => rowIndex !== index))}
                    aria-label={copy("Remove row", "删除此条")}
                  >
                    ×
                  </button>
                </div>
              ))}
              <button type="button" className="agent-config-line-editor__add" onClick={() => setRows([...normalizedRows, ""])}>
                + {addLabel}
              </button>
            </div>
          );
        };
        const renderStrategyTextarea = (
          field: keyof AutomationJobStrategyDraft,
          label: string,
          description: string,
        ) => (
          <label className="agent-config-editor__field">
            <span>{label}</span>
            <small>{description}</small>
            {renderLineEditor(
              selectedJobStrategy ? String(selectedJobStrategy[field]) : "",
              (next) => {
                if (selectedAutomationJobId) {
                  updateAutomationStrategy(selectedAutomationJobId, field, next);
                }
              },
              copy("Add rule", "添加规则"),
            )}
          </label>
        );
        const renderStrategyRecommendation = () => {
          if (!selectedJob || !selectedJobRecommendation) {
            return null;
          }
          const scoreItems: Array<[string, string]> = [
            [copy("Online pass", "在线通过线"), selectedJobRecommendation.onlineResumePass],
            [copy("Offline pass", "离线通过线"), selectedJobRecommendation.offlineResumePass],
            [copy("Composite pass", "综合通过线"), selectedJobRecommendation.compositePass],
            [copy("Manual review", "人工复核线"), selectedJobRecommendation.manualReviewMin],
          ];
          const policyItems: Array<[string, string]> = [
            [copy("JD screening standard", "基于 JD 的候选人筛选标准"), selectedJobRecommendation.screeningCriteria],
            [copy("Online resume scoring", "在线简历评分标准"), selectedJobRecommendation.onlineResumeCriteria],
            [copy("Offline resume scoring", "离线简历评分标准"), selectedJobRecommendation.offlineResumeCriteria],
            [copy("Composite scoring standard", "综合评分标准"), selectedJobRecommendation.compositeScoring],
            [copy("Manual review rules", "人工复核规则"), selectedJobRecommendation.manualReviewRules],
          ];
          return (
            <section className="agent-config-strategy-recommendation">
              <div className="agent-config-strategy-recommendation__head">
                <strong>{copy("Recommended strategy template", "推荐策略模板")}</strong>
                <button type="button" className="chat-overlay__header-button" onClick={() => applyRecommendedAutomationStrategy(selectedJob)}>
                  {copy("Use this template", "使用此模板")}
                </button>
              </div>
              <div className="agent-config-strategy-recommendation__scores">
                {scoreItems.map(([label, value]) => (
                  <div key={label}>
                    <span>{label}</span>
                    <strong>{value}</strong>
                  </div>
                ))}
              </div>
              <div className="agent-config-strategy-recommendation__body">
                {policyItems.map(([label, value]) => (
                  <article key={label}>
                    <span>{label}</span>
                    <p>{value}</p>
                  </article>
                ))}
              </div>
            </section>
          );
        };
        const renderSchedulerToggle = (field: AutomationActivationBooleanField, label: string) => (
          <label className="agent-config-scheduler-toggle">
            <FormCheckbox
              type="checkbox"
              checked={Boolean(automationConfigDraft.activationPolicy[field])}
              onChange={(event) => updateAutomationActivationPolicy(field, event.target.checked)}
            />
            <span>{label}</span>
          </label>
        );
        const renderSchedulerNumber = (
          field: AutomationActivationNumberField,
          label: string,
          suffix: string,
        ) => (
          <label className="agent-config-score">
            <span>{label}</span>
            <div className="agent-config-number-with-unit">
              <FormInput
                type="number"
                min={0}
                value={String(automationConfigDraft.activationPolicy[field] ?? "")}
                onChange={(event) => updateAutomationActivationPolicy(field, event.target.value)}
              />
              <small>{suffix}</small>
            </div>
          </label>
        );

        return (
          <div className="agent-config agent-config--automation">
            <div className="agent-config-automation-layout">
              <div className="agent-config-automation-main">
                <div className="agent-config-automation-actions">
                  <button
                    type="button"
                    className="chat-overlay__header-button"
                    disabled={savingConfig}
                    onClick={() => {
                      setConfigDraft(configDraftFromSettings(settingsSnapshot));
                      setAgentConfigDrafts((current) => ({
                        ...current,
                        autonomous: agentConfigDraftFromWorkspace(workspaces.autonomous),
                      }));
                      setAutomationConfigDraft(automationConfigDraftFromWorkspace(workspaces.autonomous, automationJobDescriptions));
                    }}
                  >
                    {copy("Reset", "重置")}
                  </button>
                  <button type="button" className="chat-overlay__header-button" disabled={savingConfig} onClick={() => void handleSaveConfig()}>
                    {savingConfig ? copy("Saving…", "保存中…") : copy("Save configuration", "保存配置")}
                  </button>
                </div>
                <section className="agent-config-step-panel">
                  <div className="agent-config-sop-timeline agent-config-step-timeline" role="tablist" aria-label={copy("Automation configuration steps", "自动化配置节点")}>
                    <div className="agent-config-sop-timeline__line" aria-hidden="true" />
                    {automationConfigPages.map((node, index) => (
                      <button
                        key={node.key}
                        type="button"
                        role="tab"
                        aria-selected={selectedAutomationConfigPage === node.key}
                        data-active={selectedAutomationConfigPage === node.key}
                        data-pass={node.passed}
                        onClick={() => setSelectedAutomationConfigPage(node.key)}
                      >
                        <span>{node.passed ? "✓" : index + 1}</span>
                        <strong>{node.label}</strong>
                        <small>{node.meta}</small>
                      </button>
                    ))}
                  </div>
                </section>
            {selectedAutomationConfigPage === "base" ? (
              <section className="agent-config-system-preview">
                {renderBaseCapabilityReadOnly(activeAgentConfig)}
              </section>
            ) : null}

            {selectedAutomationConfigPage === "jd" ? (
            <section className="agent-config-automation-shell">
              <aside className="agent-config-jobs-panel" aria-label={copy("JD strategy list", "JD 策略列表")}>
                <div className="agent-config-job-actions">
                  <button type="button" className="chat-overlay__header-button" onClick={selectAllAutomationJobs}>
                    {copy("Select all", "全选")}
                  </button>
                  <button type="button" className="chat-overlay__header-button" onClick={clearAllAutomationJobs}>
                    {copy("Clear", "取消全选")}
                  </button>
                </div>
                <div className="agent-config-job-selector">
                  {automationJobDescriptions.map((job) => {
                    const jobId = automationJobId(job);
                    if (!jobId) {
                      return null;
                    }
                    const selectedForRun = automationConfigDraft.selectedRunJobIds.includes(jobId);
                    return (
                      <div key={jobId} className="agent-config-job-row agent-config-job-row--selectable" data-active={jobId === selectedAutomationJobId} data-selected={selectedForRun}>
                        <FormCheckbox
                          type="checkbox"
                          checked={selectedForRun}
                          onChange={(event) => toggleAutomationRunJob(jobId, event.target.checked)}
                          aria-label={copy("Enable JD for this run", "选择此 JD 生效")}
                        />
                        <button type="button" onClick={() => setSelectedAutomationJobId(jobId)}>
                          <strong>{job.title}</strong>
                          <small>{selectedForRun ? automationJobSubtitle(job) : copy("Not selected for automation", "未选择，不需要配置策略")}</small>
                        </button>
                      </div>
                    );
                  })}
                  {!automationJobDescriptions.length ? (
                    <div className="chat-empty-inline">{copy("Configure the target page URL and sync JD first.", "请先配置目标网页 URL 并同步 JD。")}</div>
                  ) : null}
                </div>
              </aside>

              <main className="agent-config-strategy-panel">
                <section className="agent-config-strategy-section">
                  <div className="agent-config-panel-head">
                    <div>
                      <h4>{selectedJob ? selectedJob.title : copy("Select an effective JD", "选择生效 JD")}</h4>
                      <p>{selectedJob ? automationJobSubtitle(selectedJob) : copy("Enable a JD on the left, then edit its screening and scoring policy.", "先在左侧选择生效 JD，再编辑该 JD 的筛选与评分策略。")}</p>
                    </div>
                  </div>
                  {selectedJob && selectedJobStrategy && selectedJobEnabled ? (
                    <div className="agent-config-editor__fields">
                      {renderStrategyRecommendation()}
                      <div className="agent-config-score-grid agent-config-score-grid--four">
                        {([
                          ["onlineResumePass", copy("Online pass", "在线通过线")],
                          ["offlineResumePass", copy("Offline pass", "离线通过线")],
                          ["compositePass", copy("Composite pass", "综合通过线")],
                          ["manualReviewMin", copy("Manual review", "人工复核线")],
                        ] as Array<[keyof AutomationJobStrategyDraft, string]>).map(([key, label]) => (
                          <label key={key} className="agent-config-score">
                            <span>{label}</span>
                            <FormInput
                              type="number"
                              min={0}
                              max={100}
                              value={selectedJobStrategy[key]}
                              onChange={(event) => updateAutomationStrategy(automationJobId(selectedJob) ?? "", key, event.target.value)}
                            />
                          </label>
                        ))}
                      </div>
                      {renderStrategyTextarea("screeningCriteria", copy("JD screening standard", "基于 JD 的候选人筛选标准"), copy("Hard requirements, exclusion rules, bonus points, and evidence that must be present for this JD.", "该 JD 的硬性要求、排除项、加分项和必须具备的证据。"))}
                      <div className="agent-config-resume-split">
                        <label className="agent-config-editor__field">
                          <span>{copy("Online resume scoring", "在线简历评分标准")}</span>
                          <small>{copy("What can be scored from public profile and online resume evidence.", "基于公开资料和在线简历证据可评分的内容。")}</small>
                          <FormTextarea
                            value={selectedJobStrategy.onlineResumeCriteria}
                            onChange={(event) => updateAutomationStrategy(automationJobId(selectedJob) ?? "", "onlineResumeCriteria", event.target.value)}
                            className="chat-overlay-form-textarea--medium"
                          />
                        </label>
                        <label className="agent-config-editor__field">
                          <span>{copy("Offline resume scoring", "离线简历评分标准")}</span>
                          <small>{copy("What must be checked after PDF/DOC/DOCX resume acquisition.", "获取 PDF/DOC/DOCX 简历后必须核查的内容。")}</small>
                          <FormTextarea
                            value={selectedJobStrategy.offlineResumeCriteria}
                            onChange={(event) => updateAutomationStrategy(automationJobId(selectedJob) ?? "", "offlineResumeCriteria", event.target.value)}
                            className="chat-overlay-form-textarea--medium"
                          />
                        </label>
                      </div>
                      {renderStrategyTextarea("compositeScoring", copy("Composite scoring standard", "综合评分标准"), copy("Final decision rule after JD fit, online resume, offline resume, communication evidence, and risks are combined.", "合并 JD 匹配、在线简历、离线简历、沟通证据和风险项后的最终决策规则。"))}
                      {renderStrategyTextarea("manualReviewRules", copy("Manual review rules", "人工复核规则"), copy("When the candidate should be marked for review instead of pass/reject.", "候选人何时进入复核，而不是直接通过或淘汰。"))}
                    </div>
                  ) : (
                    <div className="chat-empty-inline">
                      {selectedJob
                        ? copy("This JD is not selected for automation, so no strategy is required.", "该 JD 未选择生效，不需要配置策略。")
                        : copy("Select an effective JD to edit its strategy.", "请选择一个生效 JD 编辑策略。")}
                    </div>
                  )}
                </section>

              </main>
            </section>
            ) : null}

            {selectedAutomationConfigPage === "entry" ? (
            <section className="agent-config-independent-panel agent-config-sop-panel">
              <div className="agent-config-sop-section">
                <div className="agent-config-panel-head">
                  <div>
                    <h4>{copy("Recruiting site used by automation", "自动化招聘网站")}</h4>
                  </div>
                  <button
                    type="button"
                    className="chat-overlay__header-button"
                    onClick={() => focusAgent("jd_sync", "config")}
                  >
                    {copy("Open JD Sync Agent", "打开 JD 同步 Agent")}
                  </button>
                </div>
                <div className="agent-config-editor__fields">
                  <label className="agent-config-editor__field agent-config-editor__field--wide">
                    <span>{copy("Recruiting target page URL", "招聘网站目标网页 URL")}</span>
                    <FormInput
                      placeholder="https://..."
                      value={automationConfigDraft.executionSop.siteEntryUrl}
                      onChange={(event) => updateAutomationSop("siteEntryUrl", event.target.value)}
                    />
                  </label>
                </div>
                <div className="chat-empty-inline">
                  {automationJobDescriptions.length
                    ? copy(`${automationJobDescriptions.length} JD records are available for strategy configuration.`, `当前已有 ${automationJobDescriptions.length} 个 JD 可配置策略。`)
                    : copy("No synced JD yet. Run the JD Sync Agent first, then return to select effective JD.", "尚未同步 JD。请先运行 JD 同步 Agent，再回来选择生效 JD。")}
                </div>
                <label className="agent-config-editor__field">
                  <span>{copy("Site execution boundaries", "站点执行边界")}</span>
                  {renderLineEditor(
                    automationConfigDraft.executionSop.siteAccessRulesText,
                    (next) => updateAutomationSop("siteAccessRulesText", next),
                    copy("Add boundary", "添加边界"),
                  )}
                </label>
              </div>
            </section>
            ) : null}

            {selectedAutomationConfigPage === "sop" ? (
            <section className="agent-config-independent-panel agent-config-sop-panel">
              <FormTextarea
                value={automationConfigDraft.executionSop.stepsText}
                onChange={(event) => updateAutomationSop("stepsText", event.target.value)}
                className="agent-config-sop-prompt-textarea"
              />
            </section>
            ) : null}

            {selectedAutomationConfigPage === "activation" ? (
            <section className="agent-config-independent-panel">
              <div className="agent-config-scheduler-grid">
                <section className="agent-config-scheduler-section">
                  <strong>{copy("Wake triggers", "唤醒触发")}</strong>
                  <div className="agent-config-scheduler-toggle-grid">
                    {renderSchedulerToggle("manualStartEnabled", copy("Manual workspace start", "手动启动工作区"))}
                    {renderSchedulerToggle("scheduledScanEnabled", copy("Scheduled scan", "定时扫描"))}
                    {renderSchedulerToggle("jdPoolGapEnabled", copy("JD pool gap", "JD 候选人池缺口"))}
                    {renderSchedulerToggle("externalEventWakeEnabled", copy("External site events", "外部站点事件"))}
                    {renderSchedulerToggle("backlogWakeEnabled", copy("Backlog threshold", "积压阈值"))}
                  </div>
                  <div className="agent-config-score-grid agent-config-score-grid--three">
                    {renderSchedulerNumber("scanIntervalMinutes", copy("Scan interval", "扫描间隔"), copy("min", "分钟"))}
                    {renderSchedulerNumber("candidatePoolTarget", copy("Pool target", "候选人池目标"), copy("candidates", "人"))}
                    {renderSchedulerNumber("backlogThreshold", copy("Backlog threshold", "积压阈值"), copy("items", "项"))}
                  </div>
                </section>
                <section className="agent-config-scheduler-section">
                  <strong>{copy("Pause and stop guards", "暂停与停止保护")}</strong>
                  <div className="agent-config-scheduler-toggle-grid">
                    {renderSchedulerToggle("stopOnJdOffline", copy("Stop when JD is offline", "JD 下架时停止"))}
                    {renderSchedulerToggle("pauseOnLoginRequired", copy("Pause on login required", "需要登录时暂停"))}
                    {renderSchedulerToggle("pauseOnEntryUnavailable", copy("Pause when target page is unavailable", "目标网页不可用时暂停"))}
                    {renderSchedulerToggle("pauseOnApprovalPending", copy("Pause on pending approval", "等待审批时暂停"))}
                    {renderSchedulerToggle("pauseOnNoProgress", copy("Pause on no progress", "无进展时暂停"))}
                  </div>
                </section>
                <section className="agent-config-scheduler-section">
                  <strong>{copy("Priority weights", "优先级权重")}</strong>
                  <div className="agent-config-score-grid agent-config-score-grid--four">
                    {renderSchedulerNumber("priorityDiscoveryWeight", copy("Discovery", "发现候选人"), copy("pts", "分"))}
                    {renderSchedulerNumber("priorityUnreadMessageWeight", copy("Unread message", "未读消息"), copy("pts", "分"))}
                    {renderSchedulerNumber("priorityScoringBacklogWeight", copy("Scoring backlog", "评分积压"), copy("pts", "分"))}
                    {renderSchedulerNumber("priorityApprovalWeight", copy("Approval", "待审批"), copy("pts", "分"))}
                    {renderSchedulerNumber("priorityJdGapWeight", copy("JD gap multiplier", "JD 缺口系数"), copy("x", "倍"))}
                    {renderSchedulerNumber("messageSlaMinutes", copy("Message SLA", "消息 SLA"), copy("min", "分钟"))}
                  </div>
                </section>
                <section className="agent-config-scheduler-section">
                  <strong>{copy("Cooldown and limits", "冷却与频率限制")}</strong>
                  <div className="agent-config-score-grid agent-config-score-grid--four">
                    {renderSchedulerNumber("siteCooldownMinutes", copy("Site cooldown", "站点冷却"), copy("min", "分钟"))}
                    {renderSchedulerNumber("retryCooldownMinutes", copy("Retry cooldown", "重试冷却"), copy("min", "分钟"))}
                    {renderSchedulerNumber("maxActionsPerHour", copy("Max actions/hour", "每小时动作上限"), copy("actions", "次"))}
                    {renderSchedulerNumber("maxConsecutiveErrors", copy("Error limit", "连续错误上限"), copy("errors", "次"))}
                  </div>
                </section>
              </div>
            </section>
            ) : null}

            {selectedAutomationConfigPage === "tools" ? (
            <section className="agent-config-independent-panel">
              <div className="agent-config-tool-policy-list">
                {businessTools.map((tool) => {
                  const mode = automationConfigDraft.toolApprovalModes[tool.id] ?? "auto";
                  return (
                    <div key={tool.id} className="agent-config-tool-policy-row">
                      <div>
                        <strong>{tool.name}</strong>
                        <span>{tool.permissionScope || tool.riskLevel || tool.sourceKind}</span>
                        <p>{tool.description || tool.serverName}</p>
                      </div>
                      <div className="agent-config-segment" role="group" aria-label={tool.name}>
                        <button type="button" data-active={mode === "auto"} onClick={() => updateToolApprovalMode(tool.id, "auto")}>
                          {copy("Auto", "自动通过")}
                        </button>
                        <button type="button" data-active={mode === "approval"} onClick={() => updateToolApprovalMode(tool.id, "approval")}>
                          {copy("Approval", "需审批")}
                        </button>
                      </div>
                    </div>
                  );
                })}
                {!businessTools.length ? (
                  <div className="chat-empty-inline">{copy("No business tools are registered for this agent.", "当前 Agent 没有注册业务工具。")}</div>
                ) : null}
              </div>
            </section>
            ) : null}
              </div>
            </div>
          </div>
        );
      }

      const activeAgentConfig = agentConfigDrafts[activeAgent];
      const recruitingPolicy = activeAgentConfig.recruitingPolicy;
      const autonomousWorkflowSteps = [
        copy("Discover candidates for the selected JD and write them immediately.", "围绕选定 JD 发现候选人，并立即写入候选人库。"),
        copy("Collect online resume facts and update the candidate/application record.", "读取在线简历事实，并更新候选人/投递记录。"),
        copy("Score against JD criteria; archive hard fails and continue qualified candidates.", "按 JD 标准评分；硬性不通过直接归档，合格者继续推进。"),
        copy("Request offline resume with approval, then attach the verified artifact.", "经审批索要离线简历，并归档已验证附件。"),
        copy("Request contact details with approval and complete contact writeback.", "经审批索要联系方式，并补齐联系方式写回。"),
        copy("Stop scanning after the JD has enough complete qualified candidates.", "当该 JD 达到足够完整合格候选人后停止扫描。"),
      ];
      const configSections: Array<{ key: AgentConfigSectionKey; label: string; description: string }> = [
        ...(activeAgent === "assistant"
          ? [
              { key: "identity" as const, label: copy("AI assistant positioning", "AI助手定位"), description: copy("Conversation-facing identity, collaboration scope, and tone.", "配置对话助手的身份、协作范围和表达方式。") },
              { key: "responsibilities" as const, label: copy("Service scope", "服务范围"), description: copy("What the AI assistant can help with during a human-led recruiting workflow.", "配置人工主导招聘流程中，AI助手能协助的事项。") },
              { key: "output" as const, label: copy("Response standard", "回答标准"), description: copy("How the assistant should answer, cite evidence, and hand off next steps.", "配置回答方式、证据引用和下一步交接标准。") },
              { key: "tools" as const, label: copy("Capability usage", "能力使用"), description: copy("Which business tools the AI assistant may suggest or call in collaboration.", "配置 AI助手可建议或调用哪些业务能力。") },
              { key: "memory" as const, label: copy("Context scope", "上下文范围"), description: copy("What context can be used in a chat turn and what can be retained.", "配置对话轮次可使用和可沉淀的上下文。") },
              { key: "governance" as const, label: copy("Approval rules", "审批规则"), description: copy("Human confirmation rules for writes, outbound messages, and risky actions.", "配置写入、外联和高风险动作的人类确认规则。") },
              { key: "basePrompt" as const, label: copy("Base capability", "基础能力"), description: copy("Read-only stable identity and built-in behavior boundaries.", "只读查看稳定身份与内置行为边界。") },
            ]
          : [
              { key: "identity" as const, label: copy("Recruiting objective", "招聘目标"), description: copy("What the automation agent is expected to achieve for each JD.", "配置自动化招聘 Agent 针对每个 JD 要达成的目标。") },
              { key: "tools" as const, label: copy("JD screening", "JD 候选人筛选"), description: copy("JD-driven candidate selection criteria and hard filters.", "配置基于 JD 的候选人筛选标准和硬性排除项。") },
              { key: "output" as const, label: copy("Scoring standards", "评分标准"), description: copy("Online resume, offline resume, composite scoring, weights, and gates.", "配置在线简历、离线简历、综合评分、权重和阈值。") },
              { key: "responsibilities" as const, label: copy("Workflow", "工作流程"), description: copy("Production workflow from discovery to resume/contact completion and handoff.", "配置从发现候选人到简历/联系方式补齐和交接的生产流程。") },
              { key: "memory" as const, label: copy("Evidence context", "证据上下文"), description: copy("JD, resume, communication, score, and reusable recruiting context injected into the run.", "配置运行时注入的 JD、简历、沟通、评分和可复用招聘上下文。") },
              { key: "governance" as const, label: copy("Approval and handoff", "审批与交接"), description: copy("Approval gates, retry policy, human screening, interview, and offer handoff.", "配置审批门槛、重试策略、人工筛选、面试和 Offer 交接。") },
              { key: "basePrompt" as const, label: copy("Base capability", "基础能力"), description: copy("Read-only foundation for recruiting automation behavior.", "只读查看招聘自动化基础能力。") },
            ]),
      ];
      const selectedSection = configSections.find((section) => section.key === selectedConfigSection) ?? configSections[0];
      const hasIdentity = Boolean(activeAgentConfig.identityStatement.trim());
      const hasResponsibilities = listFromLines(activeAgentConfig.dutiesText).length > 0;
      const hasBoundaries = listFromLines(activeAgentConfig.boundariesText).length > 0;
      const hasAssistantOutput =
        Boolean(textFieldFromJsonDraft(activeAgentConfig.outputPolicyJson, "response_standard", "responseStyle").trim())
        || Boolean(activeAgentConfig.successCriteriaText.trim());
      const hasAutonomousScreening = Boolean(recruitingPolicy.jdStandards.trim());
      const hasAutonomousScoring = Boolean(recruitingPolicy.onlineResumeCriteria.trim())
        && Boolean(recruitingPolicy.offlineResumeCriteria.trim())
        && Boolean(recruitingPolicy.compositeScoring.trim());
      const validationItems = [
        {
          label: activeAgent === "assistant" ? copy("Positioning", "助手定位") : copy("Objective", "招聘目标"),
          passed: hasIdentity,
          detail: hasIdentity ? copy("Configured.", "已配置。") : copy("Required.", "必填。"),
        },
        {
          label: activeAgent === "assistant" ? copy("Service scope", "服务范围") : copy("Workflow", "工作流程"),
          passed: hasResponsibilities,
          detail: hasResponsibilities ? copy("Configured.", "已配置。") : copy("Add at least one item.", "至少需要一条。"),
        },
        {
          label: activeAgent === "assistant" ? copy("Boundaries", "边界") : copy("JD screening", "JD 筛选"),
          passed: activeAgent === "assistant" ? hasBoundaries : hasAutonomousScreening,
          detail: activeAgent === "assistant"
            ? (hasBoundaries ? copy("Configured.", "已配置。") : copy("Add at least one boundary.", "至少需要一条边界。"))
            : (hasAutonomousScreening ? copy("Configured.", "已配置。") : copy("Candidate screening criteria are required.", "需要配置候选人筛选标准。")),
        },
        {
          label: activeAgent === "assistant" ? copy("Response standard", "回答标准") : copy("Scoring", "评分标准"),
          passed: activeAgent === "assistant" ? hasAssistantOutput : hasAutonomousScoring,
          detail: activeAgent === "assistant"
            ? (hasAssistantOutput ? copy("Configured.", "已配置。") : copy("Response standard is required.", "需要配置回答标准。"))
            : (hasAutonomousScoring ? copy("Configured.", "已配置。") : copy("Resume and composite scoring standards are required.", "需要配置简历与综合评分标准。")),
        },
        {
          label: copy("Governance", "治理"),
          passed: hasBoundaries,
          detail: hasBoundaries ? copy("Boundaries and approvals are present.", "已有边界/审批约束。") : copy("Governance needs explicit boundaries.", "治理需要明确边界。"),
        },
      ];
      const passedValidationCount = validationItems.filter((item) => item.passed).length;
      const assembledPreview = activeAgent === "assistant"
        ? [
            ["助手定位", activeAgentConfig.identityStatement],
            ["服务范围", activeAgentConfig.dutiesText],
            ["回答标准", textFieldFromJsonDraft(activeAgentConfig.outputPolicyJson, "response_standard", "responseStyle") || activeAgentConfig.successCriteriaText],
            ["能力使用", textFieldFromJsonDraft(activeAgentConfig.toolScopeJson, "capability_usage", "tool_usage")],
            ["上下文范围", textFieldFromJsonDraft(activeAgentConfig.contextPolicyJson, "context_scope", "sources")],
            ["审批规则", textFieldFromJsonDraft(activeAgentConfig.permissionPolicyJson, "approval_rules", "approval_triggers")],
            ["边界", activeAgentConfig.boundariesText],
          ].map(([label, value]) => `## ${label}\n${value.trim() || "-"}`).join("\n\n")
        : [
            ["招聘目标", activeAgentConfig.identityStatement],
            ["候选人筛选标准", recruitingPolicy.jdStandards],
            ["在线简历评分", recruitingPolicy.onlineResumeCriteria],
            ["离线简历评分", recruitingPolicy.offlineResumeCriteria],
            ["综合评分标准", recruitingPolicy.compositeScoring],
            ["工作流程", activeAgentConfig.dutiesText],
            ["沟通证据", recruitingPolicy.communicationEvidence],
            ["人工筛选/交接", [recruitingPolicy.screeningRules, recruitingPolicy.interviewScheduling, recruitingPolicy.offerHandoff].filter(Boolean).join("\n")],
            ["基础行为说明", activeAgentConfig.systemPrompt],
          ].map(([label, value]) => `## ${label}\n${value.trim() || "-"}`).join("\n\n");
      const updateAgentDraft = (field: keyof Omit<AgentConfigDraft, "recruitingPolicy">, value: string) => {
        setAgentConfigDrafts((current) => ({
          ...current,
          [activeAgent]: {
            ...current[activeAgent],
            [field]: value,
          },
        }));
      };
      const updateJsonTextField = (
        field: "toolScopeJson" | "permissionPolicyJson" | "outputPolicyJson" | "budgetPolicyJson" | "modelConfigJson" | "contextPolicyJson" | "memoryPolicyJson",
        key: string,
        value: string,
      ) => {
        updateAgentDraft(field, updateJsonDraftTextField(String(activeAgentConfig[field]), key, value));
      };
      const updateRecruitingPolicyDraft = (
        field: keyof Omit<RecruitingPolicyDraft, "scoreWeights" | "thresholds">,
        value: string,
      ) => {
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
      const renderTextArea = (
        field: keyof Omit<AgentConfigDraft, "recruitingPolicy">,
        label: string,
        description: string,
        options?: { medium?: boolean; monospace?: boolean; placeholder?: string },
      ) => (
        <label className="agent-config-editor__field">
          <span>{label}</span>
          <small>{description}</small>
          <FormTextarea
            value={String(activeAgentConfig[field])}
            onChange={(event) => updateAgentDraft(field, event.target.value)}
            placeholder={options?.placeholder}
            className={[
              options?.medium ? "chat-overlay-form-textarea--medium" : "",
              options?.monospace ? "agent-config-editor__textarea--code" : "",
            ].filter(Boolean).join(" ")}
          />
        </label>
      );
      const renderJsonTextArea = (
        field: "toolScopeJson" | "permissionPolicyJson" | "outputPolicyJson" | "budgetPolicyJson" | "modelConfigJson" | "contextPolicyJson" | "memoryPolicyJson",
        key: string,
        label: string,
        description: string,
        options?: { medium?: boolean; placeholder?: string },
      ) => (
        <label className="agent-config-editor__field">
          <span>{label}</span>
          <small>{description}</small>
          <FormTextarea
            value={textFieldFromJsonDraft(String(activeAgentConfig[field]), key)}
            onChange={(event) => updateJsonTextField(field, key, event.target.value)}
            placeholder={options?.placeholder}
            className={options?.medium ? "chat-overlay-form-textarea--medium" : ""}
          />
        </label>
      );
      const renderRecruitingTextArea = (
        field: keyof Omit<RecruitingPolicyDraft, "scoreWeights" | "thresholds">,
        label: string,
        description: string,
        options?: { medium?: boolean; placeholder?: string },
      ) => (
        <label className="agent-config-editor__field">
          <span>{label}</span>
          <small>{description}</small>
          <FormTextarea
            value={String(recruitingPolicy[field])}
            onChange={(event) => updateRecruitingPolicyDraft(field, event.target.value)}
            placeholder={options?.placeholder}
            className={options?.medium ? "chat-overlay-form-textarea--medium" : ""}
          />
        </label>
      );

      return (
        <div className="agent-config agent-config--assembly">
          <section className="agent-config__header">
            <div>
              <span className="agent-config__eyebrow">{activeWorkspace.agentDefinition.key}</span>
              <h3>{activeAgent === "assistant" ? copy("AI assistant configuration", "AI助手配置") : copy("Recruiting automation configuration", "自动化招聘配置")}</h3>
              <p>
                {activeAgent === "assistant"
                  ? copy("Configure the conversational assistant for human-led recruiting work: what it can answer, what context it may use, and when it must ask for confirmation.", "配置人工主导招聘工作中的对话助手：能回答什么、使用哪些上下文、什么动作必须确认。")
                  : copy("Configure the autonomous recruiting agent around JD-driven candidate screening, resume scoring, composite scoring, workflow execution, approvals, and handoff.", "配置自动化招聘 Agent 的 JD 候选人筛选、简历评分、综合评分、工作流程、审批和交接规则。")}
              </p>
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
                    assistant: agentConfigDraftFromWorkspace(workspaces.assistant),
                    autonomous: agentConfigDraftFromWorkspace(workspaces.autonomous),
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

          <section className="agent-config-shell">
            <main className="agent-config-editor">
              <div className="agent-config-editor__bar">
                <div><span>{copy("Editing", "正在配置")}</span><strong>{normalizeAgentTitle(activeAgent, activeWorkspace.agent.name)}</strong></div>
                <div><span>Definition</span><strong>{activeWorkspace.agentDefinition.key}</strong></div>
                <div><span>{copy("Product workflow", "产品流程")}</span><strong>{activeWorkspace.productBinding.productAdapterKey || activeAgent}</strong></div>
              </div>

              <div className="agent-config-section-tabs" role="tablist" aria-label={copy("Configuration sections", "配置分区")}>
                {configSections.map((section) => (
                  <button key={section.key} type="button" data-active={section.key === selectedSection.key} onClick={() => setSelectedConfigSection(section.key)}>
                    {section.label}
                  </button>
                ))}
              </div>

              <section className="agent-config-editor__panel">
                <div className="agent-config-editor__panel-head">
                  <div>
                    <h4>{selectedSection.label}</h4>
                    <p>{selectedSection.description}</p>
                  </div>
                </div>

                {selectedSection.key === "identity" ? (
                  <div className="agent-config-editor__fields">
                    {renderTextArea(
                      "identityStatement",
                      activeAgent === "assistant" ? copy("AI assistant role", "AI助手身份") : copy("Recruiting objective", "招聘目标"),
                      activeAgent === "assistant"
                        ? copy("Define how the AI assistant should collaborate with the recruiter in chat.", "定义 AI助手在对话中如何与招聘员协作。")
                        : copy("Define the autonomous goal for each JD, including what counts as a qualified candidate.", "定义每个 JD 下的自动化目标，以及什么算合格候选人。"),
                      {
                        medium: true,
                        placeholder: activeAgent === "assistant"
                          ? copy("A recruiting copilot that helps inspect facts, draft responses, and explain next actions.", "辅助招聘员核对事实、草拟回复、解释下一步的招聘对话助手。")
                          : copy("Find complete, qualified candidates for each active JD with resume, contact, score, and evidence.", "为每个活跃 JD 找到具备简历、联系方式、评分和证据的完整合格候选人。"),
                      },
                    )}
                  </div>
                ) : null}

                {selectedSection.key === "responsibilities" ? (
                  <div className="agent-config-editor__fields">
                    {activeAgent === "assistant" ? (
                      <>
                        {renderTextArea("dutiesText", copy("AI assistant service scope", "AI助手服务范围"), copy("One supported collaboration job per line.", "每行一条可协作事项。"), { medium: true })}
                        {renderTextArea("successCriteriaText", copy("Answer success standard", "回答成功标准"), copy("Describe what makes a chat answer acceptable.", "描述什么样的对话回答才算可接受。"), { medium: true })}
                      </>
                    ) : (
                      <>
                        <div className="agent-config-workflow-reference">
                          {autonomousWorkflowSteps.map((step, index) => (
                            <div key={step}>
                              <span>{String.fromCharCode(65 + index)}</span>
                              <p>{step}</p>
                            </div>
                          ))}
                        </div>
                        {renderTextArea("dutiesText", copy("Workflow instructions", "工作流程说明"), copy("Describe the production SOP the autonomous agent should follow. It should stay site-neutral and tool-driven.", "描述自动化 Agent 要遵循的生产 SOP；保持站点中立，通过通用工具推进。"), { medium: true })}
                        {renderRecruitingTextArea("communicationEvidence", copy("Communication evidence requirements", "沟通证据要求"), copy("Define what communication facts must be recorded before advancing.", "定义推进前必须记录哪些沟通事实。"), { medium: true })}
                      </>
                    )}
                  </div>
                ) : null}

                {selectedSection.key === "boundaries" ? (
                  <div className="agent-config-editor__fields">
                    {renderTextArea("boundariesText", copy("Behavior boundaries", "行为边界"), copy("One non-negotiable constraint per line.", "每行一条不可突破的约束。"), { medium: true })}
                  </div>
                ) : null}

                {selectedSection.key === "tools" ? (
                  <div className="agent-config-editor__fields">
                    {activeAgent === "assistant" ? (
                      <>
                        {renderJsonTextArea("toolScopeJson", "capability_usage", copy("AI assistant capability usage", "AI助手能力使用"), copy("Describe which business tools can be suggested or used during human collaboration.", "描述人工协作时可建议或调用哪些业务能力。"), { medium: true })}
                        {renderTextArea("boundariesText", copy("Tool boundaries", "工具边界"), copy("One boundary per line. Include write, delete, outbound, and cross-candidate restrictions.", "每行一条边界，包括写入、删除、外联、跨候选人限制。"), { medium: true })}
                      </>
                    ) : (
                      <>
                        {renderRecruitingTextArea("jdStandards", copy("JD-based candidate screening standard", "基于 JD 的候选人筛选标准"), copy("Define how to extract hard requirements, fit dimensions, bonus points, exclusion rules, and evidence from each JD.", "定义如何从每个 JD 提取硬性要求、匹配维度、加分项、排除项和证据要求。"), { medium: true })}
                        {renderRecruitingTextArea("perJdEvaluation", copy("Per-JD evaluation method", "按 JD 差异化评估"), copy("Define how criteria change by JD while keeping the same workflow.", "定义不同 JD 如何改变判断标准，但不改变工作流。"), { medium: true })}
                      </>
                    )}
                  </div>
                ) : null}

                {selectedSection.key === "memory" ? (
                  <div className="agent-config-editor__fields">
                    {activeAgent === "assistant" ? (
                      <>
                        {renderJsonTextArea("contextPolicyJson", "context_scope", copy("Chat context scope", "对话上下文范围"), copy("Describe what the AI assistant may use from current JD, candidate, application, and conversation context.", "描述 AI助手可使用哪些当前 JD、候选人、投递和对话上下文。"), { medium: true })}
                        {renderJsonTextArea("memoryPolicyJson", "retention_rules", copy("Retention rules", "沉淀规则"), copy("Describe what can be retained as reusable knowledge and what must stay temporary.", "描述哪些内容可沉淀为可复用知识，哪些只能作为临时上下文。"), { medium: true })}
                      </>
                    ) : (
                      <>
                        {renderJsonTextArea("contextPolicyJson", "run_context", copy("Run context inputs", "运行上下文输入"), copy("Describe JD, candidate, resume, communication, skill, and business facts injected into autonomous runs.", "描述自动化运行注入的 JD、候选人、简历、沟通、skill 和业务事实。"), { medium: true })}
                        {renderJsonTextArea("memoryPolicyJson", "reusable_knowledge", copy("Reusable recruiting knowledge", "可复用招聘知识"), copy("Describe stable knowledge that may be retained across runs without storing temporary blockers or page details.", "描述可跨 run 保留的稳定招聘知识，避免沉淀临时 blocker 或页面细节。"), { medium: true })}
                      </>
                    )}
                  </div>
                ) : null}

                {selectedSection.key === "output" ? (
                  <div className="agent-config-editor__fields">
                    {activeAgent === "assistant" ? (
                      <>
                        {renderJsonTextArea("outputPolicyJson", "response_standard", copy("Response standard", "回答标准"), copy("Describe answer structure, evidence citation, uncertainty handling, and next-step phrasing.", "描述回答结构、证据引用、不确定性处理和下一步表达。"), { medium: true })}
                        {renderTextArea("successCriteriaText", copy("Acceptance criteria", "验收标准"), copy("One answer-quality criterion per line.", "每行一条回答质量验收标准。"), { medium: true })}
                      </>
                    ) : (
                      <>
                        <div className="agent-config-score-grid agent-config-score-grid--five">
                          {([
                            ["jdMatch", copy("JD match", "JD 匹配")],
                            ["onlineResume", copy("Online resume", "在线简历")],
                            ["offlineResume", copy("Offline resume", "离线简历")],
                            ["communication", copy("Communication", "沟通证据")],
                            ["stability", copy("Stability", "稳定性")],
                          ] as Array<[keyof RecruitingPolicyConfig["scoreWeights"], string]>).map(([key, label]) => (
                            <label key={key} className="agent-config-score">
                              <span>{label}</span>
                              <FormInput
                                type="number"
                                min={0}
                                max={100}
                                value={recruitingPolicy.scoreWeights[key]}
                                onChange={(event) => updateRecruitingPolicyNumber("scoreWeights", key, event.target.value)}
                              />
                            </label>
                          ))}
                        </div>
                        <div className="agent-config-threshold-grid">
                          {([
                            ["onlinePass", copy("Online pass", "在线通过")],
                            ["offlinePass", copy("Offline pass", "离线通过")],
                            ["compositePass", copy("Composite pass", "综合通过")],
                            ["manualReviewMin", copy("Manual review", "人工复核")],
                            ["interviewRecommend", copy("Interview", "推荐面试")],
                          ] as Array<[keyof RecruitingPolicyConfig["thresholds"], string]>).map(([key, label]) => (
                            <label key={key} className="agent-config-editor__field">
                              <span>{label}</span>
                              <FormInput
                                type="number"
                                min={0}
                                max={100}
                                value={recruitingPolicy.thresholds[key]}
                                onChange={(event) => updateRecruitingPolicyNumber("thresholds", key, event.target.value)}
                              />
                            </label>
                          ))}
                        </div>
                        {renderRecruitingTextArea("onlineResumeCriteria", copy("Online resume scoring standard", "在线简历评分标准"), copy("Define what can be judged from public profile and online resume evidence.", "定义可基于公开资料和在线简历证据判断的内容。"), { medium: true })}
                        {renderRecruitingTextArea("offlineResumeCriteria", copy("Offline resume scoring standard", "离线简历评分标准"), copy("Define what must be checked after PDF/DOC/DOCX resume acquisition.", "定义获取 PDF/DOC/DOCX 简历后必须检查的内容。"), { medium: true })}
                        {renderRecruitingTextArea("compositeScoring", copy("Composite scoring standard", "综合评分标准"), copy("Define how JD, resume, communication, stability, and hard filters produce the final decision.", "定义 JD、简历、沟通、稳定性和硬性条件如何形成最终结论。"), { medium: true })}
                        {renderTextArea("scoringRubric", copy("Detailed scoring rubric", "详细评分 Rubric"), copy("Detailed scoring rules used when producing candidate evidence and recommendations.", "生成候选人证据与建议时使用的详细评分规则。"), { medium: true })}
                      </>
                    )}
                  </div>
                ) : null}

                {selectedSection.key === "governance" ? (
                  <div className="agent-config-editor__fields">
                    <div className="agent-config-governance-row">
                      <label>
                        <FormCheckbox type="checkbox" checked={configDraft.desktopApprovalsOnly} onChange={(event) => setConfigDraft((current) => current ? { ...current, desktopApprovalsOnly: event.target.checked } : current)} />
                        <span>{copy("Desktop approvals only", "仅桌面审批")}</span>
                      </label>
                      {activeAgent === "autonomous" ? (
                        <>
                          <label>
                            <FormCheckbox type="checkbox" checked={configDraft.autonomyEnabled} onChange={(event) => setConfigDraft((current) => current ? { ...current, autonomyEnabled: event.target.checked } : current)} />
                            <span>{copy("Background execution", "后台执行")}</span>
                          </label>
                          <label>
                            <FormCheckbox type="checkbox" checked={configDraft.skillHealthAutonomyEnabled} onChange={(event) => setConfigDraft((current) => current ? { ...current, skillHealthAutonomyEnabled: event.target.checked } : current)} />
                            <span>{copy("Skill health wake-up", "技能巡检唤醒")}</span>
                          </label>
                          <label className="agent-config-governance-row__number">
                            <span>{copy("Wake-up interval", "唤醒间隔")}</span>
                            <FormInput type="number" min={1} value={configDraft.skillHealthAutonomyIntervalSeconds} onChange={(event) => setConfigDraft((current) => current ? { ...current, skillHealthAutonomyIntervalSeconds: event.target.value } : current)} />
                          </label>
                        </>
                      ) : null}
                    </div>
                    {activeAgent === "assistant" ? (
                      <>
                        {renderJsonTextArea("permissionPolicyJson", "approval_rules", copy("AI assistant approval rules", "AI助手审批规则"), copy("Describe when the AI assistant must ask before writing, sending, deleting, or changing business state.", "描述 AI助手在写入、发送、删除或变更业务状态前何时必须确认。"), { medium: true })}
                        {renderJsonTextArea("budgetPolicyJson", "interaction_limits", copy("Interaction limits", "交互限制"), copy("Describe expected turn length, escalation, and when to stop asking the model.", "描述单轮长度、升级路径和停止继续调用模型的条件。"), { medium: true })}
                      </>
                    ) : (
                      <>
                        {renderRecruitingTextArea("screeningRules", copy("Human screening rules", "人工筛选规则"), copy("Define what must be ready before human screening and how pass/reject/review recommendations are made.", "定义进入人工筛选前必须具备什么，以及通过/淘汰/复核建议如何生成。"), { medium: true })}
                        {renderRecruitingTextArea("interviewScheduling", copy("Interview handoff rules", "面试交接规则"), copy("Define what evidence and candidate constraints are needed before interview scheduling.", "定义面试安排前需要哪些证据和候选人约束。"), { medium: true })}
                        {renderRecruitingTextArea("offerHandoff", copy("Offer handoff rules", "Offer 交接规则"), copy("Define offer-stage handoff, risk notes, compensation constraints, and candidate feedback.", "定义 Offer 阶段交接、风险备注、薪资约束和候选人反馈。"), { medium: true })}
                        {renderJsonTextArea("permissionPolicyJson", "approval_rules", copy("Approval gates", "审批门槛"), copy("Describe which outbound, upload, writeback, archive, and external actions require human approval.", "描述哪些外联、上传、写回、归档和外部动作需要人工审批。"), { medium: true })}
                      </>
                    )}
                  </div>
                ) : null}

                {selectedSection.key === "basePrompt" ? (
                  renderBaseCapabilityReadOnly(activeAgentConfig)
                ) : null}
              </section>
            </main>

            <aside className="agent-config-inspector">
              <section>
                <div className="agent-config-inspector__head">
                  <span>{copy("Validation", "校验")}</span>
                  <StatusBadge tone={passedValidationCount === validationItems.length ? "positive" : "warning"}>{passedValidationCount}/{validationItems.length}</StatusBadge>
                </div>
                <div className="agent-config-validation-list">
                  {validationItems.map((item) => (
                    <div key={item.label} data-pass={item.passed}>
                      <span>{item.passed ? "✓" : "!"}</span>
                      <div>
                        <strong>{item.label}</strong>
                        <small>{item.detail}</small>
                      </div>
                    </div>
                  ))}
                </div>
              </section>

              <section>
                <div className="agent-config-inspector__head">
                  <span>{copy("Assembled preview", "装配预览")}</span>
                  <StatusBadge tone="neutral">{copy("Draft", "草稿")}</StatusBadge>
                </div>
                <pre className="agent-config-preview">{assembledPreview}</pre>
              </section>

              <section>
                <div className="agent-config-inspector__head">
                  <span>{copy("Business context", "业务上下文")}</span>
                </div>
                <div className="agent-config-context-note">
                  {activeAgent === "assistant"
                    ? copy(
                        "Current JD, candidate, application, and conversation facts are attached to the chat when relevant. The AI assistant configuration controls how that context is used.",
                        "当前 JD、候选人、投递记录和对话事实会在相关场景下进入对话上下文；AI助手配置控制这些上下文如何使用。",
                      )
                    : copy(
                        "Each autonomous run receives the selected JD standards, candidate facts, resume artifacts, communication evidence, score records, and configured recruiting target page URL.",
                        "每次自动化运行都会带入选中的 JD 标准、候选人事实、简历附件、沟通证据、评分记录和已配置的招聘网站目标网页 URL。",
                      )}
                </div>
              </section>
            </aside>
          </section>
        </div>
      );
    })();

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
      const pendingApprovals = activeWorkspace.approvals.filter((approval) => approval.status === "pending").length;
      const resolvedApprovals = activeWorkspace.approvals.filter((approval) => approval.status !== "pending").length;
      const enabledTools = activeWorkspace.tools.filter((tool) => tool.enabled).length;
      const healthySkills = activeWorkspace.skills.filter((skill) => skill.health === "healthy").length;
      const businessTools = activeWorkspace.tools.filter((tool) => tool.businessTool).length;
      const systemTools = activeWorkspace.tools.filter((tool) => !tool.businessTool).length;
      const latestRun = [...activeWorkspace.runs].sort(
        (left, right) => parseConversationSortTime(right.updatedAt) - parseConversationSortTime(left.updatedAt),
      )[0];
      const recentRuns = [...activeWorkspace.runs]
        .sort((left, right) => parseConversationSortTime(right.updatedAt) - parseConversationSortTime(left.updatedAt))
        .slice(0, 4);
      const context = (() => {
        if (activePanel === "config") {
          return {
            title: copy("Configuration details", "配置详情"),
            description: copy("Version, provider, policy and validation signals for the selected agent.", "展示当前 Agent 的版本、模型、策略和校验信号。"),
            metrics: [
              { label: copy("Definition", "定义"), value: activeWorkspace.agentDefinition.key },
              { label: copy("Provider", "Provider"), value: activeWorkspace.config.providerLabel || "-" },
              { label: copy("Boundaries", "边界"), value: activeWorkspace.config.boundaries.length },
              { label: copy("Approvals", "审批"), value: pendingApprovals },
            ],
            rows: [
              `${copy("Model", "模型")} · ${activeWorkspace.config.modelLabel || activeWorkspace.agent.defaultModel || "-"}`,
              `${copy("Product workflow", "产品流程")} · ${activeWorkspace.productBinding.productAdapterKey || activeAgent}`,
              `${copy("Scoring rubric", "评分规则")} · ${activeWorkspace.config.scoringRubric ? copy("Configured", "已配置") : copy("Empty", "未配置")}`,
            ],
          };
        }
        if (activePanel === "capabilities") {
          return {
            title: copy("Capability details", "能力详情"),
            description: copy("Tool, skill and memory inventory available to the selected product workflow.", "展示当前产品流程可用的工具、技能和记忆来源。"),
            metrics: [
              { label: copy("Business", "业务工具"), value: businessTools },
              { label: copy("System", "系统工具"), value: systemTools },
              { label: "Skills", value: activeWorkspace.skills.length },
              { label: "Memory", value: activeWorkspace.memories.length },
            ],
            rows: [
              `${copy("Enabled tools", "已启用工具")} · ${enabledTools}`,
              `${copy("Healthy skills", "健康技能")} · ${healthySkills}`,
              `${copy("Memory scopes", "记忆条目")} · ${activeWorkspace.memories.length}`,
            ],
          };
        }
        if (activePanel === "outputs") {
          return {
            title: copy("Output details", "产出详情"),
            description: copy("Output readiness and resolved human decisions from recent runs.", "展示最近运行的产出准备度和人工处理结果。"),
            metrics: [
              { label: copy("Completed", "已完成"), value: completedRuns },
              { label: copy("Resolved", "已处理审批"), value: resolvedApprovals },
              { label: copy("Failed", "失败"), value: failedRuns },
              { label: copy("Total", "总运行"), value: totalRuns },
            ],
            rows: [
              latestRun ? `${copy("Latest run", "最近运行")} · ${latestRun.title}` : copy("No recent runs", "暂无运行记录"),
              latestRun ? `${copy("Status", "状态")} · ${describeConversationStatus(latestRun.status)}` : `${copy("Status", "状态")} · -`,
              `${copy("Output source", "产出来源")} · ${copy("Run records and approvals", "运行记录与审批")}`,
            ],
          };
        }
        if (activePanel === "runs") {
          return {
            title: copy("Run details", "运行详情"),
            description: copy("Current queue pressure, terminal outcomes and the latest run references.", "展示当前队列压力、结束态和最近运行引用。"),
            metrics: [
              { label: copy("Open", "进行中"), value: openRuns },
              { label: copy("Completed", "已完成"), value: completedRuns },
              { label: copy("Failed", "失败"), value: failedRuns },
              { label: copy("Total", "总数"), value: totalRuns },
            ],
            rows: recentRuns.length
              ? recentRuns.map((run) => `${describeConversationStatus(run.status)} · ${run.title}`)
              : [copy("No recent runs", "暂无运行记录")],
          };
        }
        return {
          title: copy("Workspace details", "工作区详情"),
          description: copy("Live status, pending human decisions and the latest execution signal.", "展示实时状态、待确认事项和最近执行信号。"),
          metrics: [
            { label: copy("Open runs", "待处理运行"), value: openRuns },
            { label: copy("Approvals", "待确认"), value: pendingApprovals },
            { label: copy("Unread", "未读"), value: activeWorkspace.agent.unreadCount },
            { label: copy("Failed", "异常"), value: failedRuns },
          ],
          rows: [
            `${copy("Instruction", "指令")} · ${activeWorkspace.agent.activeTask || activeRunStatusText?.title || "-"}`,
            latestRun ? `${copy("Latest run", "最近运行")} · ${describeConversationStatus(latestRun.status)} · ${formatDateTime(latestRun.updatedAt)}` : copy("No recent runs", "暂无运行记录"),
            `${copy("Model", "模型")} · ${activeWorkspace.config.modelLabel || activeWorkspace.agent.defaultModel || "-"}`,
          ],
        };
      })();

      const businessActionsHelpText = copy(
        "Business actions record agent-level business outcomes such as JD writeback, candidate discovery, resume download, messaging, application stage updates, approvals, and external sync.",
        "业务动作记录 Agent 产生的业务结果，例如 JD 写回、候选人发现、简历下载、消息发送、投递阶段更新、审批和外部同步。",
      );

      return (
        <div className="agent-context-panel">
          <div className="agent-rail-tabs" role="tablist" aria-label={copy("Right panel", "右侧栏")}>
            <button
              type="button"
              role="tab"
              data-active={activeRailTab === "details"}
              aria-selected={activeRailTab === "details"}
              onClick={() => setActiveRailTab("details")}
            >
              {copy("Workspace details", "工作区详情")}
            </button>
            <span className="agent-rail-tabs__item" data-active={activeRailTab === "businessActions"}>
              <button
                type="button"
                role="tab"
                data-active={activeRailTab === "businessActions"}
                aria-selected={activeRailTab === "businessActions"}
                onClick={() => setActiveRailTab("businessActions")}
              >
                {copy("Business actions", "业务动作")}
              </button>
              <button
                type="button"
                className="agent-rail-tabs__info"
                aria-label={businessActionsHelpText}
                title={businessActionsHelpText}
              >
                i
              </button>
            </span>
          </div>
          {activeRailTab === "businessActions" ? renderBusinessActionsColumn() : (
            <>
          <div className="agent-context-panel__head">
            <div>
              <h3>{context.title}</h3>
            </div>
            <button className="agent-context-panel__collapse" type="button" onClick={() => setRailCollapsed(true)}>
              <span aria-hidden="true">›</span>
              <strong>{copy("Collapse", "收起")}</strong>
            </button>
          </div>
          <p>{context.description}</p>
          <div className="agent-context-panel__metrics">
            {context.metrics.map((metric) => (
              <div key={metric.label}>
                <span>{metric.label}</span>
                <strong>{metric.value}</strong>
              </div>
            ))}
          </div>
          <div className="agent-context-panel__rows">
            {context.rows.map((row, index) => (
              <div key={`${index}-${row}`}>
                {row}
              </div>
            ))}
          </div>
          <div className="agent-context-panel__actions">
            <button type="button" onClick={() => setActivePanel("config")}>{copy("Open config", "查看配置")}</button>
            <button type="button" onClick={() => setActivePanel("runs")}>{copy("View runs", "查看运行")}</button>
          </div>
            </>
          )}
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
                <span>{copy("Instruction", "当前指令")} · {activeWorkspace.agent.activeTask || "-"}</span>
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
      case "capabilities":
        return (
          <section className="chat-card">
            <div className="chat-card__eyebrow">{copy("Capability inventory", "能力清单")}</div>
            <div className="chat-card__meta-list">
              <span>{copy("Business", "业务")} · {activeWorkspace.tools.filter((tool) => tool.businessTool).length}</span>
              <span>{copy("System", "系统")} · {activeWorkspace.tools.filter((tool) => !tool.businessTool).length}</span>
              <span>Skills · {activeWorkspace.skills.length}</span>
              <span>Memory · {activeWorkspace.memories.length}</span>
            </div>
          </section>
        );
      case "outputs":
        return (
          <section className="chat-card">
            <div className="chat-card__eyebrow">{copy("Output stats", "产出统计")}</div>
            <div className="chat-card__meta-list">
              <span>{copy("Completed runs", "已完成运行")} · {activeWorkspace.runs.filter((run) => run.status === "completed").length}</span>
              <span>{copy("Resolved approvals", "已处理审批")} · {activeWorkspace.approvals.filter((approval) => approval.status !== "pending").length}</span>
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
      : [copy("External event", "外部事件"), copy("Schedule", "定时调度"), copy("Manual run", "手工运行"), copy("Sync feed", "同步数据流")];

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
            <div className="chat-list-item__title">{copy("Agent boundary", "Agent 边界")}</div>
            <p>
              {copy(
                "The agent core only owns turns, tools, permissions, and transcript. Recruiting semantics stay in product configuration, SOPs, business tools, and evidence records.",
                "Agent core 只负责轮次、工具、权限和记录；招聘语义保留在产品配置、SOP、业务工具和证据记录中。",
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
          <div>
            <h3>{copy("Run queue", "运行队列")}</h3>
          </div>
          <div className="agent-management-list__title-actions">
            <button
              className="agent-management-list__collapse"
              type="button"
              onClick={() => setListCollapsed(true)}
            >
              <span aria-hidden="true">‹</span>
              <strong>{copy("Collapse", "收起")}</strong>
            </button>
            <button
              type="button"
              onClick={() => {
                createDraftConversation(activeAgent);
                focusAgent(activeAgent, "conversation");
              }}
            >
              + {activeAgent === "assistant" ? copy("New chat", "新会话") : copy("New run", "新任务")}
            </button>
          </div>
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
                <div>
                  <strong>{normalizeAgentTitle(activeAgent, conversation.title)}</strong>
                  <span>{copy("ID", "ID")}：{conversation.refId || conversation.id}</span>
                </div>
              </div>
              <StatusBadge tone="neutral">{queueConversationStatusLabel(conversation)}</StatusBadge>
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

  const renderAgentWorkspaceHeader = () => {
    if (!activeWorkspace) {
      return (
        <section className="agent-management-workbench-head agent-management-workbench-head--loading">
          <div>
            <span>{copy("Loading workspace", "正在加载工作区")}</span>
            <h2>{agentDisplayName(activeAgent)}</h2>
          </div>
        </section>
      );
    }

    const workspaceTitle = agentDisplayName(activeAgent);
    const workspaceControl = activeWorkspace.workspaceControl;
    const controlState = workspaceControl?.state ?? "stopped";
    const sortedRuns = [...activeWorkspace.runs].sort(
      (left, right) => parseConversationSortTime(right.updatedAt) - parseConversationSortTime(left.updatedAt),
    );
    const currentRun = sortedRuns.find((run) => isOpenRunStatus(run.status)) ?? sortedRuns[0] ?? null;
    const currentId = activeConversationSummary?.refId || currentRun?.refId || activeConversationSummary?.id || currentRun?.id || "-";
    const workspaceTime = currentRun?.startedAt
      || workspaceControl?.updatedAt
      || currentRun?.updatedAt
      || activeConversationSummary?.updatedAt
      || activeConversation?.messages[0]?.createdAt
      || null;
    const headerStatusLabel = currentRun
      ? describeRunStatus(currentRun)
      : activeConversationSummary
      ? queueConversationStatusLabel(activeConversationSummary)
      : activeWorkspace.agent.status === "active"
        ? copy("Idle", "空闲")
        : describeConversationStatus(activeWorkspace.agent.status);
    const workspaceStartBlockers =
      activeAgent === "autonomous"
        ? automationLaunchBlockers
        : activeAgent === "jd_sync"
          ? jdSyncLaunchBlockers
          : [];
    const workspaceStartReady = workspaceStartBlockers.length === 0;

    return (
      <section className="agent-management-workbench-head">
        <div className="agent-management-workbench-head__title-row">
          <h2>{workspaceTitle}</h2>
          <StatusBadge tone={headerStatusLabel === copy("Idle", "空闲") ? "neutral" : toneForHealth(activeWorkspace.agent.health)}>
            {headerStatusLabel}
          </StatusBadge>
          <span className="agent-management-workbench-head__meta-item">{copy("ID", "ID")}：{currentId}</span>
          <span className="agent-management-workbench-head__meta-item">{copy("Time", "时间")}：{workspaceTime ? formatDateTime(workspaceTime) : "-"}</span>
        </div>
        {activeAgent !== "assistant" && !workspaceStartReady && controlState !== "running" ? (
          <div className="agent-workspace-control__blockers">
            {copy("Complete before start:", "启动前需要补全：")} {workspaceStartBlockers.join("；")}
          </div>
        ) : null}
      </section>
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

  const renderBusinessActionsColumn = () => {
    const filters: BusinessActionFilter[] = [
      "all",
      "jd",
      "candidate",
      "resume",
      "communication",
      "application",
      "evaluation",
      "sync",
      "approval",
      "state",
    ];
    const approvalItems = (activeWorkspace?.approvals ?? [])
      .filter((approval) => approval.status === "pending")
      .map((approval) => businessActionFromApproval(approval, copy));
    const messageItems = (activeConversation?.messages ?? [])
      .map((message) => businessActionFromMessage(message, copy))
      .filter((item): item is BusinessActionTimelineItem => Boolean(item));
    const uniqueItems = new Map<string, BusinessActionTimelineItem>();
    [...approvalItems, ...messageItems]
      .sort((left, right) => new Date(left.time).getTime() - new Date(right.time).getTime())
      .forEach((item) => {
        uniqueItems.set(item.key, item);
      });
    const allItems = Array.from(uniqueItems.values());
    const filteredItems = businessActionFilter === "all"
      ? allItems
      : allItems.filter((item) => item.category === businessActionFilter);
    const visibleItems = filteredItems.slice(-12);
    return (
      <section className="agent-business-actions" aria-label={copy("Business actions", "业务动作")}>
        <div className="agent-business-actions__filters" role="tablist" aria-label={copy("Business action filters", "业务动作筛选")}>
          {filters.map((filter) => (
            <button
              key={filter}
              type="button"
              role="tab"
              data-active={businessActionFilter === filter}
              aria-selected={businessActionFilter === filter}
              onClick={() => setBusinessActionFilter(filter)}
            >
              {businessActionFilterLabel(filter, copy)}
            </button>
          ))}
        </div>
        <div className="agent-business-actions__list">
          {visibleItems.map((item) => (
            <div key={item.key} className="agent-business-actions__item" data-category={item.category} data-status={item.status}>
              <div className="agent-business-actions__node" aria-hidden="true">
                {businessActionCategoryMark(item.category)}
              </div>
              <div className="agent-business-actions__body">
                <div className="agent-business-actions__title-row">
                  <strong>{item.title}</strong>
                  <time dateTime={item.time}>{formatDateTime(item.time)}</time>
                </div>
                <div className="agent-business-actions__meta">
                  <span>{item.label}</span>
                  <StatusBadge tone={businessActionStatusTone(item.status)}>
                    {businessActionStatusLabel(item.status, copy)}
                  </StatusBadge>
                </div>
                <small>{item.detail}</small>
              </div>
            </div>
          ))}
          {!visibleItems.length ? (
            <p className="agent-business-actions__empty">
              {copy("No business actions yet.", "暂无业务动作。")}
            </p>
          ) : null}
        </div>
      </section>
    );
  };

  const renderPanelContent = () => {
    if (activePanel === "conversation") {
      return (
        <div className="chat-stream chat-stream--management">
          {pageMode ? null : renderAgentCommandCenter()}
          <div className="agent-workspace-conversation-grid">
            <div className="agent-workspace-conversation-main">
              <ChatMessageStream
                loading={loadingWorkspace || loadingConversation}
                messages={activeConversation?.messages ?? []}
                renderTimelineAttachment={pageMode ? renderTimelineApprovalAttachment : undefined}
                variant={pageMode ? "timeline" : "cards"}
              />
            </div>
          </div>
        </div>
      );
    }

    if (!activeWorkspace) {
      return renderEmptyPanel(copy("Loading…", "加载中…"), copy("The overlay is still waiting for workspace data.", "Overlay 仍在等待工作区数据。"));
    }

    switch (activePanel) {
      case "config":
        return renderConfigPanel();
      case "capabilities":
        return renderCapabilitiesPanel(activeWorkspace.tools, activeWorkspace.skills, activeWorkspace.memories, activeWorkspace.mcps);
      case "outputs":
        return renderOutputsPanel(activeWorkspace);
      case "runs":
        return renderRunsPanel(activeWorkspace.runs);
      default:
        return null;
    }
  };

  const renderComposerControlActions = () => {
    if (activeAgent === "assistant") {
      return null;
    }
    if (runtimeExecutingRun && activeWorkspaceControlState === "running") {
      return (
        <button
          type="button"
          className="chat-composer__control-button chat-composer__control-button--pause"
          disabled={workspaceControlBusyAction !== null}
          onClick={() => void handleWorkspaceControl("pause")}
        >
          <span className="chat-composer__control-icon" data-icon="pause" aria-hidden="true" />
          <span>{workspaceControlBusyAction === "pause" ? copy("Pausing", "暂停中") : copy("Pause agent", "暂停 Agent")}</span>
        </button>
      );
    }
    if (runtimeResumableRun || (runtimeActiveRun && activeWorkspaceControlState === "paused")) {
      return (
        <button
          type="button"
          className="chat-composer__control-button chat-composer__control-button--continue"
          disabled={workspaceControlBusyAction !== null || !activeWorkspaceCanStart}
          onClick={() => void handleWorkspaceControl("continue")}
          title={!activeWorkspaceCanStart ? activeWorkspaceStartBlockers.join("；") : undefined}
        >
          <span className="chat-composer__control-icon" data-icon="start" aria-hidden="true" />
          <span>{workspaceControlBusyAction === "continue" ? copy("Starting", "启动中") : copy("Continue agent", "继续 Agent")}</span>
        </button>
      );
    }
    return (
      <button
        type="button"
        className="chat-composer__control-button chat-composer__control-button--primary chat-composer__control-button--start"
        disabled={workspaceControlBusyAction !== null || !activeWorkspaceCanStart}
        onClick={() => void handleWorkspaceControl("start")}
        title={!activeWorkspaceCanStart ? activeWorkspaceStartBlockers.join("；") : undefined}
      >
        <span className="chat-composer__control-icon" data-icon="start" aria-hidden="true" />
        <span>{workspaceControlBusyAction === "start" ? copy("Starting", "启动中") : copy("Start agent", "启动 Agent")}</span>
      </button>
    );
  };

  const renderComposerExecutionAction = () => {
    if (activeAgent !== "assistant" || !sending) {
      return null;
    }
    return (
      <button
        type="button"
        className="chat-composer__run-stop"
        disabled={runActionBusyId != null}
        onClick={() => void handleStopCurrentTurn()}
        aria-label={copy("Stop current turn", "终止当前 turn")}
        title={copy("Stop current turn", "终止当前 turn")}
      >
        <span aria-hidden="true" />
      </button>
    );
  };

  if (!visible) {
    return <></>;
  }

  return (
    <div className={pageMode ? "agent-management-page" : "chat-overlay-shell"}>
      <section className={pageMode ? "agent-management-surface" : "chat-overlay chat-overlay--drawer"}>
        {pageMode ? (
          <PageToolbar className="agent-management-topbar">
            <PageToolbarGroup className="agent-management-topbar__identity">
              <div className="agent-management-topbar__title">
                <span>{copy("RecruitStation", "RecruitStation")}</span>
                <strong>{copy("Agent management", "Agent 管理")}</strong>
              </div>
              <div className="agent-management-agent-switch" role="tablist" aria-label={copy("Agent type", "Agent 类型")}>
                {AGENT_KINDS.map((kind) => (
                  <button
                    key={kind}
                    type="button"
                    role="tab"
                    data-active={kind === activeAgent}
                    onClick={() => focusAgent(kind, activePanel)}
                  >
                    <span>{agentTabLabel(kind)}</span>
                    <small>{conversationsByAgent[kind].length}</small>
                  </button>
                ))}
              </div>
            </PageToolbarGroup>
            <PageToolbarGroup className="agent-management-topbar__search">
              <div className="agent-management-search">
                <span aria-hidden="true">⌕</span>
                <ToolbarInput
                  value={agentSearchQuery}
                  onChange={(event) => setAgentSearchQuery(event.target.value)}
                  placeholder={copy("Search sessions, run ID, or preview", "搜索会话、运行 ID 或摘要")}
                />
              </div>
            </PageToolbarGroup>
            <PageToolbarGroup className="agent-management-topbar__actions" align="end">
              <ToolbarButton
                className="agent-management-icon-button"
                onClick={() => void loadWorkspaces()}
                aria-label={copy("Refresh", "刷新")}
                icon={<span className="toolbar-button__icon toolbar-button__icon--refresh" aria-hidden="true" />}
              />
              <ToolbarButton
                onClick={() => {
                  createDraftConversation(activeAgent);
                  focusAgent(activeAgent, "conversation");
                }}
              >
                {activeAgent === "assistant" ? copy("New chat", "新建会话") : copy("New run", "新建任务")}
              </ToolbarButton>
            </PageToolbarGroup>
          </PageToolbar>
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
              {AGENT_KINDS.map((kind) => (
                <button
                  key={kind}
                  type="button"
                  className="chat-overlay__header-button"
                  data-active={kind === activeAgent}
                  onClick={() => focusAgent(kind, activePanel)}
                >
                  {agentTabLabel(kind)}
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

        <div
          className={pageMode ? "agent-management-layout" : "chat-overlay__body"}
          data-context-collapsed={pageMode && railCollapsed ? "true" : undefined}
          data-list-collapsed={pageMode && listCollapsed ? "true" : undefined}
        >
          {!pageMode || !listCollapsed ? <aside className={pageMode ? "agent-management-list-pane" : "chat-overlay__sidebar"}>
            {pageMode ? renderAgentListPane() : (
              <>
                <button
                  type="button"
                  className="chat-overlay__new"
                  onClick={() => {
                    createDraftConversation(activeAgent);
                    focusAgent(activeAgent, "conversation");
                  }}
                >
                  + {copy("New conversation", "新对话")}
                </button>

            {AGENT_KINDS.map((kind) => {
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
                          {agentTabLabel(kind)}
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
          </aside> : null}

          <main className={pageMode ? "agent-management-main-pane" : "chat-overlay__main"}>
            {pageMode && activePanel === "conversation" ? renderAgentWorkspaceHeader() : null}
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

            <div ref={streamShellRef} className="chat-overlay__stream-shell" onScroll={handleStreamScroll}>
              {errorMessage ? <div className="chat-overlay__error">{errorMessage}</div> : null}
              {panelNotice?.panel === activePanel ? <div className="chat-overlay__notice" style={noticeStyle(panelNotice.tone)}>{panelNotice.message}</div> : null}
              {renderPanelContent()}
            </div>

            {activePanel === "conversation" ? (
              <ChatComposer
                agentKind={activeAgent}
                inputDisabled={
                  sending
                  || loadingWorkspace
                }
                submitDisabled={
                  loadingWorkspace
                  || (activeAgent === "assistant" && sending)
                  || (activeAgent !== "assistant" && activeWorkspaceControlState !== "running" && !activeConversationRunIsResumable && composerMatchedCommand == null)
                }
                submitRequiresValue
                modelLabel={activeWorkspace?.config.modelLabel ?? activeWorkspace?.agent.defaultModel}
                contextLabel={
                  activeAgent !== "assistant"
                    ? activeAgent === "jd_sync" ? copy("JD sync run", "JD 同步运行") : copy("Automation run", "自动化运行")
                    : copy("Current workspace", "当前工作区")
                }
                submitLabel={
                  copy("Send", "发送")
                }
                controlActions={renderComposerControlActions()}
                executionAction={renderComposerExecutionAction()}
                value={composerInputValue}
                onChange={handleComposerChange}
                onSubmit={() => {
                  if (composerMatchedCommand) {
                    void handleComposerCommand(composerMatchedCommand.id);
                    return;
                  }
                  void handleSubmit();
                }}
                commandItems={composerCommandItems}
                onCommand={(commandId) => void handleComposerCommand(commandId)}
                shouldSubmitOnEnter={isClearConversationCommand}
              />
            ) : null}
          </main>

          {pageMode && listCollapsed ? (
            <button
              type="button"
              className="agent-list-restore"
              aria-label={copy("Show run queue", "展开运行队列")}
              style={{ top: `${railRestoreTop}px` }}
              onPointerDown={startListRestoreDrag}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  setListCollapsed(false);
                }
              }}
            >
              <span className="agent-list-restore__icon" aria-hidden="true" />
            </button>
          ) : null}
          {!railCollapsed ? <aside className={pageMode ? "agent-management-runtime-pane" : "chat-overlay__rail"}>{renderRailContent()}</aside> : null}
          {pageMode && railCollapsed ? (
            <button
              type="button"
              className="agent-context-restore"
              aria-label={copy("Show right panel", "展开右侧栏")}
              style={{ top: `${railRestoreTop}px` }}
              onPointerDown={startRailRestoreDrag}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  setRailCollapsed(false);
                }
              }}
            >
              <span className="agent-context-restore__icon" aria-hidden="true" />
            </button>
          ) : null}
        </div>
      </section>

      {!pageMode && workspaceAgent.status === "waiting_human" ? (
        <div className="chat-overlay__toast">{copy("Agent is waiting for desktop approval.", "Agent 正在等待桌面审批。")}</div>
      ) : null}
    </div>
  );
}
