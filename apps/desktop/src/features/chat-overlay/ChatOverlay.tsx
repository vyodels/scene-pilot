import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FormCheckbox, FormInput, FormTextarea, StatusBadge } from "../../components";
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
  AutonomousRunStartRequest,
  AssistantTurnStreamEvent,
  ChatOverlayPanelKey,
  JobDescriptionSummaryRecord,
  RecruitingPolicyConfig,
  SettingsSnapshot,
  SkillRecord,
} from "../../lib/types";
import { ChatComposer } from "./ChatComposer";
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
type CapabilityCategoryKey = "business" | "system" | "skills" | "mcp" | "memory";
type CapabilityItemKind = "tool" | "skill" | "memory";
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
type AutomationConfigPageKey = "jd" | "sop" | "run" | "tools" | "base";

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
  name: string;
  siteScope: string;
  stepsText: string;
  stopRulesText: string;
}

interface AutomationConfigDraft {
  selectedRunJobIds: string[];
  jobStrategies: Record<string, AutomationJobStrategyDraft>;
  executionSop: AutomationExecutionSopDraft;
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
  { key: "conversation", label: "对话" },
  { key: "config", label: "配置" },
  { key: "capabilities", label: "能力" },
  { key: "outputs", label: "工作产出" },
  { key: "runs", label: "运行记录" },
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
    : "由外部事件、定时调度或手工创建的自动化运行驱动，适合后台持续推进招聘流程。";
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

const DEFAULT_AUTOMATION_SOP_STEPS = [
  "确认本次运行选择的 JD 与对应策略版本。",
  "按 JD 策略发现候选人，先写入候选人事实与来源证据。",
  "完成在线简历事实采集，并按在线简历评分标准给出阶段结论。",
  "对在线通过或需复核的候选人索取离线简历，附件到位后按离线简历标准评分。",
  "汇总 JD 匹配、在线简历、离线简历、沟通证据和风险项，形成综合评分与建议动作。",
  "触发停止规则、JD 下架或进入人工审批节点时，按工具权限策略处理。",
];

const DEFAULT_AUTOMATION_STOP_RULES = [
  "JD 被人工下架后自动从可执行列表移除。",
  "候选人缺少关键证据时不得进入综合通过状态。",
  "外联、删除、归档、状态流转等关键业务工具按权限矩阵决定是否先审批。",
].join("\n");

function automationConfigDraftTemplate(): AutomationConfigDraft {
  return {
    selectedRunJobIds: [],
    jobStrategies: {},
    executionSop: {
      name: "标准招聘执行 SOP",
      siteScope: "本次运行所有选中 JD",
      stepsText: DEFAULT_AUTOMATION_SOP_STEPS.join("\n"),
      stopRulesText: DEFAULT_AUTOMATION_STOP_RULES,
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

function statusAllowsDefaultRunSelection(status: string | null | undefined): boolean {
  const normalized = (status ?? "").trim().toLowerCase();
  return normalized === "" || normalized === "active" || normalized === "open" || normalized === "published";
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
  job: JobDescriptionSummaryRecord,
  fallbackPolicy?: RecruitingPolicyConfig,
): AutomationJobStrategyDraft {
  const record = raw ?? {};
  return {
    screeningCriteria: stringFromUnknown(
      record.screeningCriteria ?? record.screening_criteria,
      fallbackPolicy?.jdStandards || job.requirements || job.summary || "",
    ),
    onlineResumeCriteria: stringFromUnknown(
      record.onlineResumeCriteria ?? record.online_resume_criteria,
      fallbackPolicy?.onlineResumeCriteria ?? "",
    ),
    offlineResumeCriteria: stringFromUnknown(
      record.offlineResumeCriteria ?? record.offline_resume_criteria,
      fallbackPolicy?.offlineResumeCriteria ?? "",
    ),
    compositeScoring: stringFromUnknown(
      record.compositeScoring ?? record.composite_scoring,
      fallbackPolicy?.compositeScoring ?? "",
    ),
    manualReviewRules: stringFromUnknown(
      record.manualReviewRules ?? record.manual_review_rules,
      fallbackPolicy?.screeningRules ?? "",
    ),
    onlineResumePass: stringFromUnknown(record.onlineResumePass ?? record.online_resume_pass, String(fallbackPolicy?.thresholds.onlinePass ?? 70)),
    offlineResumePass: stringFromUnknown(record.offlineResumePass ?? record.offline_resume_pass, String(fallbackPolicy?.thresholds.offlinePass ?? 72)),
    compositePass: stringFromUnknown(record.compositePass ?? record.composite_pass, String(fallbackPolicy?.thresholds.compositePass ?? 75)),
    manualReviewMin: stringFromUnknown(record.manualReviewMin ?? record.manual_review_min, String(fallbackPolicy?.thresholds.manualReviewMin ?? 60)),
  };
}

function automationConfigDraftFromWorkspace(
  workspace: AgentWorkspaceRecord | null,
  jobs: JobDescriptionSummaryRecord[],
): AutomationConfigDraft {
  const template = automationConfigDraftTemplate();
  const runtimeMetadata = isRecord(workspace?.agentDefinition.config.runtimeMetadata)
    ? workspace?.agentDefinition.config.runtimeMetadata
    : {};
  const rawConfig = recordField(runtimeMetadata, "automationRecruitingConfig", "automationConfig") ?? {};
  const rawSop = recordField(rawConfig, "executionSop", "execution_sop") ?? {};
  const rawStrategies = recordField(rawConfig, "jobStrategies", "job_strategies") ?? {};
  const rawToolPolicy = recordField(rawConfig, "toolApprovalPolicy", "tool_approval_policy") ?? {};
  const rawToolOverrides = recordField(rawToolPolicy, "overrides") ?? {};
  const fallbackPolicy = workspace?.productAdapterConfig.recruitingPolicy;
  const jobStrategies: Record<string, AutomationJobStrategyDraft> = {};

  jobs.forEach((job) => {
    const id = automationJobId(job);
    if (!id) {
      return;
    }
    const rawStrategy = isRecord(rawStrategies[id]) ? rawStrategies[id] : undefined;
    jobStrategies[id] = automationJobStrategyFromRaw(rawStrategy, job, fallbackPolicy);
  });

  const knownJobIds = new Set(Object.keys(jobStrategies));
  const configuredSelection = arrayStringField(rawConfig, "defaultRunJobIds", "default_run_job_ids", "selectedRunJobIds", "selected_run_job_ids")
    .filter((id) => knownJobIds.has(id));
  const defaultSelection = jobs
    .filter((job) => statusAllowsDefaultRunSelection(job.status))
    .map(automationJobId)
    .filter((id): id is string => Boolean(id && knownJobIds.has(id)))
    .slice(0, 5);
  const toolApprovalModes = Object.fromEntries(
    Object.entries(rawToolOverrides).map(([toolId, value]) => [
      toolId,
      value === "approval" ? "approval" : "auto",
    ]),
  ) as Record<string, AutomationToolApprovalMode>;

  return {
    selectedRunJobIds: configuredSelection.length ? configuredSelection : defaultSelection,
    jobStrategies,
    executionSop: {
      name: stringFromUnknown(rawSop.name, template.executionSop.name),
      siteScope: stringFromUnknown(rawSop.siteScope ?? rawSop.site_scope, template.executionSop.siteScope),
      stepsText: stringFromUnknown(rawSop.stepsText ?? rawSop.steps_text, template.executionSop.stepsText),
      stopRulesText: stringFromUnknown(rawSop.stopRulesText ?? rawSop.stop_rules_text, template.executionSop.stopRulesText),
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
              passThreshold: numberConfigValue(strategy.onlineResumePass, 70),
            },
            offline: {
              criteria: strategy.offlineResumeCriteria,
              passThreshold: numberConfigValue(strategy.offlineResumePass, 72),
            },
          },
          compositeScoring: {
            criteria: strategy.compositeScoring,
            passThreshold: numberConfigValue(strategy.compositePass, 75),
            manualReviewMin: numberConfigValue(strategy.manualReviewMin, 60),
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
      name: draft.executionSop.name,
      siteScope: draft.executionSop.siteScope,
      stepsText: draft.executionSop.stepsText,
      stopRulesText: draft.executionSop.stopRulesText,
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

function buildAutomationLaunchPayload(
  draft: AutomationConfigDraft,
  jobs: JobDescriptionSummaryRecord[],
  tools: AgentToolSummary[],
): AutonomousRunStartRequest | null {
  const jobById = new Map(jobs.map((job) => [automationJobId(job), job] as const).filter((entry): entry is [string, JobDescriptionSummaryRecord] => Boolean(entry[0])));
  const selectedJobs = draft.selectedRunJobIds
    .map((jobId) => {
      const job = jobById.get(jobId);
      const strategy = draft.jobStrategies[jobId];
      if (!job || !strategy) {
        return null;
      }
      return { jobId, job, strategy };
    })
    .filter((item): item is { jobId: string; job: JobDescriptionSummaryRecord; strategy: AutomationJobStrategyDraft } => Boolean(item));
  if (!selectedJobs.length) {
    return null;
  }
  const toolPolicy = automationConfigPayloadFromDraft(draft, jobs, tools).toolApprovalPolicy;
  const jobPlans = selectedJobs.map((item) => ({
    jobDescriptionId: item.jobId,
    title: item.job.title,
    companyName: item.job.companyName ?? null,
    status: item.job.status ?? null,
    screeningCriteria: item.strategy.screeningCriteria,
    scoringStandards: {
      onlineResume: {
        criteria: item.strategy.onlineResumeCriteria,
        passThreshold: numberConfigValue(item.strategy.onlineResumePass, 70),
      },
      offlineResume: {
        criteria: item.strategy.offlineResumeCriteria,
        passThreshold: numberConfigValue(item.strategy.offlineResumePass, 72),
      },
      composite: {
        criteria: item.strategy.compositeScoring,
        passThreshold: numberConfigValue(item.strategy.compositePass, 75),
        manualReviewMin: numberConfigValue(item.strategy.manualReviewMin, 60),
      },
    },
    manualReviewRules: item.strategy.manualReviewRules,
  }));
  return {
    title: `多 JD 自动化招聘 · ${selectedJobs.length} 个 JD`,
    instruction: [
      "按结构化启动计划运行自动化招聘 Agent。",
      `本次运行覆盖 ${selectedJobs.length} 个可执行 JD。`,
      "执行时必须使用配置页中的 JD 策略、评分标准、独立 SOP 与业务工具权限策略；不要让普通用户补充说明覆盖这些业务策略。",
    ].join("\n"),
    kind: "multi_jd_recruiting",
    jdId: null,
    candidateCountTarget: null,
    constraints: {
      scope_kind: "global",
      plan_kind: "multi_jd_recruiting",
      selected_job_description_ids: selectedJobs.map((item) => item.jobId),
      execution_sop: draft.executionSop,
      business_policy_overlay: {
        job_plans: jobPlans,
      },
      tool_approval_policy: toolPolicy,
    },
    successCriteria: {
      requiresOnlineResumeScore: true,
      requiresOfflineResumeScoreForCompleteCandidates: true,
      requiresCompositeScore: true,
      passDecisionSource: "score_thresholds",
      executableJobSource: "active_job_descriptions",
    },
    contextHints: {
      launch_plan: {
        plan_kind: "multi_jd_recruiting",
        jobs: jobPlans.map((plan) => ({
          jobDescriptionId: plan.jobDescriptionId,
          title: plan.title,
          companyName: plan.companyName,
          status: plan.status,
        })),
      },
    },
  };
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
  const [railCollapsed, setRailCollapsed] = useState(false);
  const [collapsedGroups, setCollapsedGroups] = useState<Record<AgentKind, boolean>>({
    assistant: false,
    autonomous: false,
  });
  const [errorMessage, setErrorMessage] = useState<string>();
  const [settingsSnapshot, setSettingsSnapshot] = useState<SettingsSnapshot | null>(null);
  const [configDraft, setConfigDraft] = useState<ConfigDraft | null>(null);
  const [agentConfigDrafts, setAgentConfigDrafts] = useState<Record<AgentKind, AgentConfigDraft>>(agentConfigDraftTemplate);
  const [automationConfigDraft, setAutomationConfigDraft] = useState<AutomationConfigDraft>(automationConfigDraftTemplate);
  const [selectedAutomationJobId, setSelectedAutomationJobId] = useState<string | null>(null);
  const [selectedAutomationConfigPage, setSelectedAutomationConfigPage] = useState<AutomationConfigPageKey>("jd");
  const [systemPromptExpanded, setSystemPromptExpanded] = useState(false);
  const [selectedConfigSection, setSelectedConfigSection] = useState<AgentConfigSectionKey>("identity");
  const [selectedCapabilityKey, setSelectedCapabilityKey] = useState<string | null>(null);
  const [loadingSettings, setLoadingSettings] = useState(false);
  const [savingConfig, setSavingConfig] = useState(false);
  const [startingAutomationPlan, setStartingAutomationPlan] = useState(false);
  const [panelNotice, setPanelNotice] = useState<PanelNotice | null>(null);
  const [approvalNotes, setApprovalNotes] = useState<Record<string, string>>({});
  const [approvalSelections, setApprovalSelections] = useState<Record<string, string>>({});
  const [approvalActionId, setApprovalActionId] = useState<string | null>(null);
  const [runActionBusyId, setRunActionBusyId] = useState<string | null>(null);
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
    });
  }, [workspaces.assistant, workspaces.autonomous]);

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
  const automationJobDescriptions = useMemo(
    () => jobDescriptions.filter((job) => automationJobId(job) != null),
    [jobDescriptions],
  );
  const automationJobIds = useMemo(
    () => automationJobDescriptions.map(automationJobId).filter((id): id is string => Boolean(id)),
    [automationJobDescriptions],
  );
  const autonomousWorkspace = workspaces.autonomous;
  const autonomousActiveRun = useMemo(
    () => autonomousWorkspace?.runs.find((run) => isOpenRunStatus(run.status)) ?? null,
    [autonomousWorkspace],
  );
  const autonomousStartBlocked = activeAgent === "autonomous" && autonomousActiveRun != null;
  const autonomousDraftEditable =
    activeAgent === "autonomous" && autonomousStartBlocked && activeDraftComposerKey != null;
  const composerInputValue = activeDraftComposerKey != null ? draftComposerValues[activeDraftComposerKey] ?? "" : composerValue;

  useEffect(() => {
    setAutomationConfigDraft(automationConfigDraftFromWorkspace(workspaces.autonomous, automationJobDescriptions));
  }, [automationJobDescriptions, workspaces.autonomous]);

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
              ? copy("New assistant chat", "新 Assistant 会话")
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
        latestRun ? `${copy("Last run", "最近一次")}：${describeConversationStatus(latestRun.status)}` : null,
        activeWorkspace.agent.activeTask ? `${copy("Instruction", "当前指令")}：${activeWorkspace.agent.activeTask}` : null,
      ].filter((value): value is string => Boolean(value && value.trim()));

      return {
        badgeLabel: describeConversationStatus(activeWorkspace.agent.status),
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
          "Automation already has an open run. Wait for the current run to finish before starting the next one.",
          "Automation 当前已有未结束的运行，请等待当前运行结束后再启动下一轮。",
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
        const result = await apiClient.startAutonomousRun({
          title: trimTitle(text),
          instruction: text,
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
          content: copy("Automation run has been submitted to the backend.", "自动化运行已提交到后端。"),
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
    const payload = buildAutomationLaunchPayload(
      automationConfigDraft,
      automationJobDescriptions,
      workspaces.autonomous?.tools ?? [],
    );
    if (!payload) {
      setPanelNotice({
        panel: "config",
        tone: "error",
        message: copy("Select at least one JD before starting automation.", "启动前至少选择一个 JD。"),
      });
      return;
    }

    setStartingAutomationPlan(true);
    setPanelNotice(null);
    setErrorMessage(undefined);
    try {
      const draftConversationId = createDraftConversation("autonomous");
      appendMessage("autonomous", draftConversationId, {
        id: `automation-plan-${Date.now()}`,
        conversationId: draftConversationId,
        role: "user",
        kind: "message",
        content: payload.instruction,
        createdAt: new Date().toISOString(),
        status: "sent",
        metadata: {
          eventKind: "human",
          launchPlan: payload.contextHints,
        },
      });
      const result = await apiClient.startAutonomousRun({
        ...payload,
        conversationId: null,
      });
      removeDraftConversation("autonomous", draftConversationId);
      await loadWorkspaces();
      setSelectedConversation((current) => ({
        ...current,
        autonomous: result.conversationId,
      }));
      setActivePanel("conversation");
      appendMessage("autonomous", result.conversationId, {
        id: `autonomous-plan-status-${result.runId ?? Date.now()}`,
        conversationId: result.conversationId,
        role: "system",
        kind: "status",
        content: copy("Structured multi-JD automation run has been submitted.", "结构化多 JD 自动化运行已提交。"),
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
        message: error instanceof Error ? error.message : copy("Failed to start automation run.", "启动自动化运行失败。"),
      });
    } finally {
      setStartingAutomationPlan(false);
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
      ): { config: AgentWorkspaceRecord["agentDefinition"]["config"]; error?: string } => {
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
        if (kind === "autonomous") {
          runtimeMetadata.scoringRubric = draft.scoringRubric;
          runtimeMetadata.recruitingPolicy = recruitingPolicyPayloadFromDraft(draft.recruitingPolicy);
          const automationRecruitingConfig = automationConfigPayloadFromDraft(
            automationConfigDraft,
            automationJobDescriptions,
            workspace.tools,
          );
          runtimeMetadata.automationRecruitingConfig = automationRecruitingConfig;
          permissionPolicy.businessToolApprovalPolicy = isRecord(automationRecruitingConfig.toolApprovalPolicy)
            ? automationRecruitingConfig.toolApprovalPolicy
            : {};
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
        };
      };

      const configPatches = (["assistant", "autonomous"] as AgentKind[]).map((kind) => {
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
                {describeConversationStatus(run.status)}
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
            </div>
            {activeAgent === "autonomous" ? (
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

  const renderCapabilitiesPanel = (tools: AgentToolSummary[], skills: SkillRecord[], memories: AgentMemorySummary[]) => {
    const memoryTools = tools.filter((tool) => tool.sourceKind === "memory_tool");
    const mcpTools = tools.filter((tool) => tool.sourceKind === "mcp_tool" || (!memoryTools.includes(tool) && /mcp/i.test(tool.serverName)));
    const businessTools = tools
      .filter((tool) => tool.businessTool)
      .sort((left, right) => left.name.localeCompare(right.name));
    const systemTools = tools
      .filter((tool) => !tool.businessTool && !mcpTools.includes(tool) && !memoryTools.includes(tool))
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
        description: copy("Enabled MCP tools and servers available to the agent as ordinary tool definitions.", "已启用的 MCP 工具和服务，进入 Agent 前会转换为普通工具定义。"),
        items: mcpTools.sort((left, right) => left.name.localeCompare(right.name)).map((tool) => toToolItem(tool, "mcp")),
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
                          <div><span>{copy("Input schema", "输入 Schema")}</span><strong>{compactJsonSummary(item.tool.inputSchema, copy("Not provided", "未提供"))}</strong></div>
                          <div><span>{copy("Output schema", "输出 Schema")}</span><strong>{compactJsonSummary(item.tool.outputSchema, copy("Not provided", "未提供"))}</strong></div>
                          <div><span>{copy("Metadata", "元数据")}</span><strong>{metadataSummary(item.tool.toolMetadata, copy("Not provided", "未提供"))}</strong></div>
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
            label: copy("Tool governance", "工具治理"),
            detail: jsonDraftReadableSummary(
              draft.toolScopeJson,
              copy("Tools are governed by the product adapter and business permission contracts.", "工具由产品适配器与业务权限契约治理。"),
              "capability_usage",
              "tool_usage",
              "allowed_tools",
            ),
          },
          {
            label: copy("Approval governance", "审批治理"),
            detail: jsonDraftReadableSummary(
              draft.permissionPolicyJson,
              copy("Approval is determined by business tool permissions, with auto-approval as the default unless a tool is gated.", "审批由业务工具权限决定；默认自动通过，关键工具可配置为审批节点。"),
              "approval_rules",
              "approval_triggers",
              "write_policy",
            ),
          },
          {
            label: copy("Context policy", "上下文策略"),
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
            label: copy("Memory policy", "Memory 策略"),
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
              ? copy("Base capability owns generic state-machine and tool-use constraints. Recruiting execution SOP is configured separately and applies to all selected JDs in a run.", "基础能力只负责通用状态机与工具使用约束；招聘执行 SOP 单独配置，并对一次运行内选中的所有 JD 生效。")
              : copy("Assistant remains conversation-led: it explains, drafts, checks evidence, and hands off write actions through governed tools.", "Assistant 由对话驱动：负责解释、草拟、核对证据，并通过受治理工具交接写入动作。"),
          },
          {
            label: copy("Product binding", "产品绑定"),
            detail: `${copy("Definition", "定义")} ${agentDefinition} · ${copy("Adapter", "适配器")} ${productAdapter}`,
          },
        ];

        return (
          <div className="agent-config-base-readonly">
            <div className="agent-config-panel-head">
              <div>
                <h4>{copy("Base capability", "基础能力")}</h4>
                <p>{copy("Read-only stable capability managed by product releases. High-frequency business policy is configured in dedicated pages.", "产品版本管理的只读稳定能力；高频业务策略在独立页面配置。")}</p>
              </div>
              <StatusBadge tone="neutral">{copy("Read only", "只读")}</StatusBadge>
            </div>

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
                <strong>{copy("System / developer instruction", "System / developer 指令")}</strong>
                <span>{copy("Visible for inspection only. It is not user-editable and changes through product releases.", "仅用于查看；不可由用户编辑，只随产品版本迭代。")}</span>
              </div>
              <button type="button" className="chat-overlay__header-button" onClick={() => setSystemPromptExpanded((current) => !current)}>
                {systemPromptExpanded ? copy("Hide", "收起") : copy("View", "查看")}
              </button>
            </div>
            {systemPromptExpanded ? <pre className="agent-config-preview">{systemInstruction}</pre> : null}
          </div>
        );
      };

      if (String(activeAgent) === "autonomous") {
        const activeAgentConfig = agentConfigDrafts.autonomous;
        const selectedJob = automationJobDescriptions.find((job) => automationJobId(job) === selectedAutomationJobId) ?? null;
        const selectedJobStrategy = selectedAutomationJobId ? automationConfigDraft.jobStrategies[selectedAutomationJobId] : undefined;
        const selectedLaunchJobs = automationConfigDraft.selectedRunJobIds
          .map((jobId) => {
            const job = automationJobDescriptions.find((item) => automationJobId(item) === jobId);
            const strategy = automationConfigDraft.jobStrategies[jobId];
            return job && strategy ? { jobId, job, strategy } : null;
          })
          .filter((item): item is { jobId: string; job: JobDescriptionSummaryRecord; strategy: AutomationJobStrategyDraft } => Boolean(item));
        const businessTools = activeWorkspace.tools.filter((tool) => tool.businessTool);
        const approvalToolCount = businessTools.filter((tool) => automationConfigDraft.toolApprovalModes[tool.id] === "approval").length;
        const selectedJobsHaveStrategy = selectedLaunchJobs.every((item) =>
          item.strategy.screeningCriteria.trim()
          && item.strategy.onlineResumeCriteria.trim()
          && item.strategy.offlineResumeCriteria.trim()
          && item.strategy.compositeScoring.trim(),
        );
        const sopReady = Boolean(automationConfigDraft.executionSop.stepsText.trim());
        const validationItems = [
          {
            label: copy("Selected JDs", "已选择 JD"),
            passed: selectedLaunchJobs.length > 0,
            detail: `${selectedLaunchJobs.length} / ${automationJobDescriptions.length}`,
          },
          {
            label: copy("Per-JD strategies", "逐 JD 策略"),
            passed: selectedJobsHaveStrategy,
            detail: selectedJobsHaveStrategy ? copy("Screening and scoring are configured.", "筛选与评分已配置。") : copy("Selected JDs need screening, resume, and composite rules.", "选中 JD 需要补齐筛选、简历与综合规则。"),
          },
          {
            label: copy("Execution SOP", "执行 SOP"),
            passed: sopReady,
            detail: sopReady ? automationConfigDraft.executionSop.name : copy("Add SOP steps.", "需要填写 SOP 步骤。"),
          },
          {
            label: copy("Tool permissions", "工具权限"),
            passed: true,
            detail: copy(`${approvalToolCount} approval gates`, `${approvalToolCount} 个审批节点`),
          },
        ];
        const passedValidationCount = validationItems.filter((item) => item.passed).length;
        const validationProgressPercent = Math.round((passedValidationCount / validationItems.length) * 100);
        const automationConfigPages: Array<{ key: AutomationConfigPageKey; label: string; description: string }> = [
          { key: "jd", label: copy("JD strategy", "JD 策略"), description: copy("Per-JD screening, resume scoring, composite thresholds, and acceptance output.", "逐 JD 配置筛选、简历评分、综合阈值和验收产出。") },
          { key: "sop", label: copy("Execution SOP", "执行 SOP"), description: copy("Shared execution method selected by a run plan.", "运行计划选择的共享执行方法。") },
          { key: "run", label: copy("Run plan", "运行计划"), description: copy("Choose executable JDs for the next autonomous run.", "选择下一次自动化运行的可执行 JD。") },
          { key: "tools", label: copy("Tool permissions", "工具权限"), description: copy("Approval gates bound to business tools.", "绑定业务工具的审批节点。") },
          { key: "base", label: copy("Base capability", "基础能力"), description: copy("Read-only stable system/developer instruction.", "只读查看稳定 system/developer 设定。") },
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
        const updateToolApprovalMode = (toolId: string, mode: AutomationToolApprovalMode) => {
          setAutomationConfigDraft((current) => ({
            ...current,
            toolApprovalModes: {
              ...current.toolApprovalModes,
              [toolId]: mode,
            },
          }));
        };
        const renderStrategyTextarea = (
          field: keyof AutomationJobStrategyDraft,
          label: string,
          description: string,
        ) => (
          <label className="agent-config-editor__field">
            <span>{label}</span>
            <small>{description}</small>
            <FormTextarea
              value={selectedJobStrategy ? String(selectedJobStrategy[field]) : ""}
              disabled={!selectedAutomationJobId || !selectedJobStrategy}
              onChange={(event) => {
                if (selectedAutomationJobId) {
                  updateAutomationStrategy(selectedAutomationJobId, field, event.target.value);
                }
              }}
              className="chat-overlay-form-textarea--medium"
            />
          </label>
        );

        return (
          <div className="agent-config agent-config--automation">
            <section className="agent-config__header">
              <div>
                <span className="agent-config__eyebrow">{activeWorkspace.agentDefinition.key}</span>
                <h3>{copy("Recruiting automation configuration", "自动化招聘配置")}</h3>
                <p>
                  {copy(
                    "Manage frequently changing business policy here: per-JD screening, resume scoring, composite scoring, execution SOP, run selection, and business tool approvals.",
                    "这里维护高频变化的业务策略：逐 JD 筛选、简历评分、综合评分、独立执行 SOP、运行选择和业务工具审批。",
                  )}
                </p>
              </div>
              <div className="agent-config__actions">
                <button
                  type="button"
                  className="chat-overlay__header-button"
                  disabled={savingConfig || startingAutomationPlan}
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
                  {savingConfig ? copy("Saving…", "保存中…") : copy("Save policy", "保存策略")}
                </button>
                <button
                  type="button"
                  className="chat-composer__submit"
                  disabled={startingAutomationPlan || autonomousStartBlocked || !selectedLaunchJobs.length}
                  onClick={() => void handleStartAutomationPlan()}
                >
                  {startingAutomationPlan ? copy("Starting…", "启动中…") : copy("Start selected JDs", "启动选中 JD")}
                </button>
              </div>
            </section>

            <nav className="agent-config-page-tabs" aria-label={copy("Automation configuration pages", "自动化配置页面")}>
              {automationConfigPages.map((page) => (
                <button
                  key={page.key}
                  type="button"
                  data-active={selectedAutomationConfigPage === page.key}
                  onClick={() => setSelectedAutomationConfigPage(page.key)}
                >
                  <strong>{page.label}</strong>
                  <span>{page.description}</span>
                </button>
              ))}
            </nav>

            {selectedAutomationConfigPage === "run" ? (
            <section className="agent-config-launch-status">
              <div className="agent-config-launch-status__head">
                <div>
                  <span>{copy("Configuration readiness", "配置完整度")}</span>
                  <strong>{passedValidationCount}/{validationItems.length}</strong>
                </div>
                <div className="agent-config-launch-status__meta">
                  <span>{copy("JDs", "JD")} {selectedLaunchJobs.length}</span>
                  <span>{copy("Approvals", "审批")} {approvalToolCount}</span>
                </div>
              </div>
              <div className="agent-config-timeline" aria-label={copy("Configuration readiness", "配置完整度")}>
                <div className="agent-config-timeline__line" aria-hidden="true">
                  <span style={{ width: `${validationProgressPercent}%` }} />
                </div>
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
              <div className="agent-config-run-selection">
                <div className="agent-config-panel-head">
                  <div>
                    <h4>{copy("Executable JD list", "可执行 JD 列表")}</h4>
                    <p>{copy("Active JDs are selected here for the next run. When a JD is taken offline by an operator, it leaves this list.", "下一次运行在这里选择启用 JD；JD 被人工下架后会离开可执行列表。")}</p>
                  </div>
                </div>
                <div className="agent-config-run-selection__list">
                  {automationJobDescriptions.map((job) => {
                    const jobId = automationJobId(job);
                    if (!jobId) {
                      return null;
                    }
                    const selectedForRun = automationConfigDraft.selectedRunJobIds.includes(jobId);
                    return (
                      <label key={jobId} className="agent-config-run-selection__row">
                        <FormCheckbox
                          type="checkbox"
                          checked={selectedForRun}
                          onChange={(event) => toggleAutomationRunJob(jobId, event.target.checked)}
                        />
                        <span>
                          <strong>{job.title}</strong>
                          <small>{automationJobSubtitle(job)}</small>
                        </span>
                      </label>
                    );
                  })}
                </div>
              </div>
            </section>
            ) : null}

            {selectedAutomationConfigPage === "base" ? (
              <section className="agent-config-system-preview">
                {renderBaseCapabilityReadOnly(activeAgentConfig)}
              </section>
            ) : null}

            {selectedAutomationConfigPage === "jd" ? (
            <section className="agent-config-automation-shell">
              <aside className="agent-config-jobs-panel">
                <div className="agent-config-panel-head">
                  <div>
                    <h4>{copy("JD strategy library", "JD 策略库")}</h4>
                    <p>{copy("Each JD keeps its own business policy. The workflow stays shared.", "每个 JD 独立维护业务策略，执行工作流保持共享。")}</p>
                  </div>
                  <StatusBadge tone={selectedLaunchJobs.length ? "positive" : "warning"}>{selectedLaunchJobs.length}</StatusBadge>
                </div>
                <div className="agent-config-job-selector">
                  {automationJobDescriptions.map((job) => {
                    const jobId = automationJobId(job);
                    if (!jobId) {
                      return null;
                    }
                    return (
                      <div key={jobId} className="agent-config-job-row" data-active={jobId === selectedAutomationJobId}>
                        <button type="button" onClick={() => setSelectedAutomationJobId(jobId)}>
                          <strong>{job.title}</strong>
                          <span>{automationJobSubtitle(job)}</span>
                        </button>
                      </div>
                    );
                  })}
                  {!automationJobDescriptions.length ? (
                    <div className="chat-empty-inline">{copy("No JD records available.", "当前没有可配置的 JD。")}</div>
                  ) : null}
                </div>
              </aside>

              <main className="agent-config-strategy-panel">
                <section className="agent-config-strategy-section">
                  <div className="agent-config-panel-head">
                    <div>
                      <h4>{selectedJob ? selectedJob.title : copy("Select a JD", "选择一个 JD")}</h4>
                      <p>{selectedJob ? automationJobSubtitle(selectedJob) : copy("Pick a JD from the left to edit its screening and scoring policy.", "从左侧选择 JD 后编辑筛选与评分策略。")}</p>
                    </div>
                    {selectedJob ? <StatusBadge tone="neutral">{selectedJob.status || "JD"}</StatusBadge> : null}
                  </div>
                  {selectedJob && selectedJobStrategy ? (
                    <div className="agent-config-editor__fields">
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
                    <div className="chat-empty-inline">{copy("Select a JD to edit its strategy.", "请选择一个 JD 编辑策略。")}</div>
                  )}
                </section>

              </main>
            </section>
            ) : null}

            {selectedAutomationConfigPage === "sop" ? (
            <section className="agent-config-independent-panel agent-config-sop-panel">
              <div className="agent-config-panel-head">
                <div>
                  <h4>{copy("Execution SOP", "招聘执行 SOP")}</h4>
                  <p>{copy("Independent capability shared by all selected JDs in the current run.", "独立能力配置，对本次运行选中的所有 JD 统一生效。")}</p>
                </div>
                <StatusBadge tone="neutral">{copy("Global", "全局")}</StatusBadge>
              </div>
              <div className="agent-config-editor__fields agent-config-editor__fields--two">
                <label className="agent-config-editor__field">
                  <span>{copy("SOP name", "SOP 名称")}</span>
                  <FormInput value={automationConfigDraft.executionSop.name} onChange={(event) => updateAutomationSop("name", event.target.value)} />
                </label>
                <label className="agent-config-editor__field">
                  <span>{copy("Scope", "生效范围")}</span>
                  <FormInput value={automationConfigDraft.executionSop.siteScope} onChange={(event) => updateAutomationSop("siteScope", event.target.value)} />
                </label>
                <label className="agent-config-editor__field">
                  <span>{copy("SOP steps", "SOP 步骤")}</span>
                  <small>{copy("One production step per line.", "每行一个生产执行步骤。")}</small>
                  <FormTextarea
                    value={automationConfigDraft.executionSop.stepsText}
                    onChange={(event) => updateAutomationSop("stepsText", event.target.value)}
                    className="chat-overlay-form-textarea--medium"
                  />
                </label>
                <label className="agent-config-editor__field">
                  <span>{copy("Stop and handoff rules", "停止与交接规则")}</span>
                  <small>{copy("When to stop, wait, escalate, or hand off.", "何时停止、等待、升级或交接。")}</small>
                  <FormTextarea
                    value={automationConfigDraft.executionSop.stopRulesText}
                    onChange={(event) => updateAutomationSop("stopRulesText", event.target.value)}
                    className="chat-overlay-form-textarea--medium"
                  />
                </label>
              </div>
            </section>
            ) : null}

            {selectedAutomationConfigPage === "tools" ? (
            <section className="agent-config-independent-panel">
              <div className="agent-config-panel-head">
                <div>
                  <h4>{copy("Business tool permissions", "业务工具权限")}</h4>
                  <p>{copy("Default is auto-approved. Mark only key business actions as approval gates.", "默认自动通过，只把关键业务动作设为审批节点。")}</p>
                </div>
                <StatusBadge tone={approvalToolCount ? "warning" : "positive"}>{approvalToolCount}</StatusBadge>
              </div>
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
              { key: "identity" as const, label: copy("Assistant positioning", "助手定位"), description: copy("Conversation-facing identity, collaboration scope, and tone.", "配置对话助手的身份、协作范围和表达方式。") },
              { key: "responsibilities" as const, label: copy("Service scope", "服务范围"), description: copy("What the assistant can help with during a human-led recruiting workflow.", "配置人工主导招聘流程中，Assistant 能协助的事项。") },
              { key: "output" as const, label: copy("Response standard", "回答标准"), description: copy("How the assistant should answer, cite evidence, and hand off next steps.", "配置回答方式、证据引用和下一步交接标准。") },
              { key: "tools" as const, label: copy("Capability usage", "能力使用"), description: copy("Which business tools the assistant may suggest or call in collaboration.", "配置 Assistant 可建议或调用哪些业务能力。") },
              { key: "memory" as const, label: copy("Context scope", "上下文范围"), description: copy("What context can be used in a chat turn and what can be retained.", "配置对话轮次可使用和可沉淀的上下文。") },
              { key: "governance" as const, label: copy("Approval rules", "审批规则"), description: copy("Human confirmation rules for writes, outbound messages, and risky actions.", "配置写入、外联和高风险动作的人类确认规则。") },
              { key: "basePrompt" as const, label: copy("Base capability", "基础能力"), description: copy("Read-only stable identity and system/developer instructions.", "只读查看稳定身份与 system/developer 指令。") },
            ]
          : [
              { key: "identity" as const, label: copy("Recruiting objective", "招聘目标"), description: copy("What the automation agent is expected to achieve for each JD.", "配置自动化招聘 Agent 针对每个 JD 要达成的目标。") },
              { key: "tools" as const, label: copy("JD screening", "JD 候选人筛选"), description: copy("JD-driven candidate selection criteria and hard filters.", "配置基于 JD 的候选人筛选标准和硬性排除项。") },
              { key: "output" as const, label: copy("Scoring standards", "评分标准"), description: copy("Online resume, offline resume, composite scoring, weights, and gates.", "配置在线简历、离线简历、综合评分、权重和阈值。") },
              { key: "responsibilities" as const, label: copy("Workflow", "工作流程"), description: copy("Production workflow from discovery to resume/contact completion and handoff.", "配置从发现候选人到简历/联系方式补齐和交接的生产流程。") },
              { key: "memory" as const, label: copy("Evidence context", "证据上下文"), description: copy("JD, resume, communication, score, and reusable recruiting context injected into the run.", "配置运行时注入的 JD、简历、沟通、评分和可复用招聘上下文。") },
              { key: "governance" as const, label: copy("Approval and handoff", "审批与交接"), description: copy("Approval gates, retry policy, human screening, interview, and offer handoff.", "配置审批门槛、重试策略、人工筛选、面试和 Offer 交接。") },
              { key: "basePrompt" as const, label: copy("Base prompt", "基础 Prompt"), description: copy("Reusable system prompt fragment for recruiting automation behavior.", "配置招聘自动化行为的可复用系统提示词片段。") },
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
            ["基础 Prompt", activeAgentConfig.systemPrompt],
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
              <h3>{activeAgent === "assistant" ? copy("Assistant configuration", "Assistant 配置") : copy("Recruiting automation configuration", "自动化招聘配置")}</h3>
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
                <div><span>{copy("Adapter", "Adapter")}</span><strong>{activeWorkspace.productBinding.productAdapterKey || activeAgent}</strong></div>
              </div>

              <div className="agent-config-section-tabs" role="tablist" aria-label={copy("Prompt sections", "Prompt 分区")}>
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
                      activeAgent === "assistant" ? copy("Assistant role", "助手身份") : copy("Recruiting objective", "招聘目标"),
                      activeAgent === "assistant"
                        ? copy("Define how the assistant should collaborate with the recruiter in chat.", "定义 Assistant 在对话中如何与招聘员协作。")
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
                        {renderTextArea("dutiesText", copy("Assistant service scope", "Assistant 服务范围"), copy("One supported collaboration job per line.", "每行一条可协作事项。"), { medium: true })}
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
                        {renderJsonTextArea("toolScopeJson", "capability_usage", copy("Assistant capability usage", "Assistant 能力使用"), copy("Describe which business tools can be suggested or used during human collaboration.", "描述人工协作时可建议或调用哪些业务能力。"), { medium: true })}
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
                        {renderJsonTextArea("contextPolicyJson", "context_scope", copy("Chat context scope", "对话上下文范围"), copy("Describe what the assistant may use from current JD, candidate, application, and conversation context.", "描述 Assistant 可使用哪些当前 JD、候选人、投递和对话上下文。"), { medium: true })}
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
                        {renderTextArea("scoringRubric", copy("Detailed scoring rubric", "详细评分 Rubric"), copy("Free-form rubric injected into the recruiting adapter.", "注入招聘 adapter 的详细评分规则。"), { medium: true })}
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
                        {renderJsonTextArea("permissionPolicyJson", "approval_rules", copy("Assistant approval rules", "Assistant 审批规则"), copy("Describe when the assistant must ask before writing, sending, deleting, or changing business state.", "描述 Assistant 在写入、发送、删除或变更业务状态前何时必须确认。"), { medium: true })}
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
                  <span>{copy("Adapter context", "Adapter 上下文")}</span>
                </div>
                <div className="agent-config-context-note">
                  {activeAgent === "assistant"
                    ? copy(
                        "Current JD, candidate, application, and conversation facts are injected by the assistant adapter as chat context. The assistant configuration controls how it uses that context.",
                        "当前 JD、候选人、投递记录和对话事实由 Assistant adapter 按需注入；Assistant 配置只控制它如何使用这些上下文。",
                      )
                    : copy(
                        "JD standards, candidate facts, resume artifacts, communication evidence, and score records are injected by the recruiting adapter or JD module for each autonomous run.",
                        "JD 标准、候选人事实、简历附件、沟通证据和评分记录由招聘 adapter 或 JD 模块按每次自动化运行注入。",
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
            <div className="agent-runtime-card__eyebrow">{copy("Conversation summary", "对话摘要")}</div>
            <div className="agent-runtime-grid">
              <div><span>{copy("Type", "类型")}</span><strong>{activeAgent === "assistant" ? "Assistant" : "Automation"}</strong></div>
              <div><span>{copy("Model", "模型")}</span><strong>{activeWorkspace.config.modelLabel || activeWorkspace.agent.defaultModel || "-"}</strong></div>
              <div><span>{copy("Tools", "工具")}</span><strong>{enabledTools}</strong></div>
              <div><span>{copy("Skills", "技能")}</span><strong>{healthySkills}</strong></div>
            </div>
          </section>

          <section className="agent-runtime-card">
            <div className="agent-runtime-card__eyebrow">{copy("Current run", "当前运行")}</div>
            <div className="agent-runtime-list">
              <span>{copy("Instruction", "指令")} · {activeWorkspace.agent.activeTask || activeRunStatusText?.title || "-"}</span>
              <span>{copy("Open runs", "待处理运行")} · {openRuns}</span>
              <span>{copy("Completed", "已完成")} · {completedRuns}</span>
              <span>{copy("Failed", "失败")} · {failedRuns}</span>
            </div>
            <div className="agent-runtime-actions">
              <button type="button" onClick={() => setActivePanel("runs")}>{copy("View runs", "查看运行")}</button>
              <button type="button" onClick={() => setActivePanel("conversation")}>{copy("Open conversation", "查看对话")}</button>
            </div>
          </section>

          <section className="agent-runtime-card">
            <div className="agent-runtime-card__title-row">
              <div className="agent-runtime-card__eyebrow">{copy("Today usage", "今日运行数据")}</div>
              <span>{copy("Live", "实时")}</span>
            </div>
            <div className="agent-runtime-metrics">
              <div><span>{copy("Runs", "运行")}</span><strong>{totalRuns}</strong></div>
              <div><span>{copy("Success", "成功率")}</span><strong>{successRate}%</strong></div>
              <div><span>{copy("Open", "进行中")}</span><strong>{openRuns}</strong></div>
              <div><span>{copy("Failed", "失败")}</span><strong>{failedRuns}</strong></div>
            </div>
          </section>

          <section className="agent-runtime-card">
            <div className="agent-runtime-card__eyebrow">{copy("Current progress", "当前运行进度")}</div>
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
                "The agent core only owns turns, tools, permissions, and transcript. Product semantics stay in adapters, prompts, and business tools.",
                "Agent core 只负责 turn、工具、权限和 transcript；产品语义保留在 adapter、prompt 和业务工具中。",
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
              createDraftConversation(activeAgent);
              focusAgent(activeAgent, "conversation");
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
      case "capabilities":
        return renderCapabilitiesPanel(activeWorkspace.tools, activeWorkspace.skills, activeWorkspace.memories);
      case "outputs":
        return renderOutputsPanel(activeWorkspace);
      case "runs":
        return renderRunsPanel(activeWorkspace.runs);
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
              <span>{copy("Status", "状态")}</span>
              <select value={agentListFilter} onChange={(event) => setAgentListFilter(event.target.value as AgentListFilter)}>
                <option value="all">{copy("All", "全部")}</option>
                <option value="running">{copy("Running", "运行中")}</option>
                <option value="waiting">{copy("Waiting", "待确认")}</option>
                <option value="done">{copy("Done", "已完成")}</option>
                <option value="failed">{copy("Failed", "失败")}</option>
              </select>
            </label>
            <div className="agent-management-search">
              <span aria-hidden="true">⌕</span>
              <input
                value={agentSearchQuery}
                onChange={(event) => setAgentSearchQuery(event.target.value)}
                placeholder={copy("Search sessions, run ID, or preview", "搜索会话、运行 ID 或摘要")}
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
                    createDraftConversation(activeAgent);
                    focusAgent(activeAgent, "conversation");
                  }}
                >
                  + {copy("New conversation", "新对话")}
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
                    ? copy("Automation run", "自动化运行")
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
