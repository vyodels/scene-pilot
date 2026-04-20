import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { StatusBadge } from "../../components";
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
}

type PanelNoticeTone = "info" | "success" | "error";

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
}

interface AutonomousGoalDraft {
  sceneTemplateKey: string;
  title: string;
  jdId: string;
  candidateCountTarget: string;
  goalText: string;
}

const panelItems: Array<{ key: ChatOverlayPanelKey; label: string }> = [
  { key: "conversation", label: "对话" },
  { key: "config", label: "配置" },
  { key: "runs", label: "运行" },
  { key: "approvals", label: "审批" },
  { key: "memory", label: "记忆" },
  { key: "skills", label: "技能" },
  { key: "tools", label: "工具" },
];

const assistantUserId = "desktop-user";

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

function agentConfigDraftTemplate(): Record<AgentKind, AgentConfigDraft> {
  return {
    assistant: {
      systemPrompt: "",
      goalTemplate: "",
      scoringRubric: "",
    },
    autonomous: {
      systemPrompt: "",
      goalTemplate: "",
      scoringRubric: "",
    },
  };
}

function agentConfigDraftFromWorkspace(workspace: AgentWorkspaceRecord | null): AgentConfigDraft {
  return {
    systemPrompt: workspace?.config.systemPrompt ?? "",
    goalTemplate: workspace?.config.goalTemplate ?? "",
    scoringRubric: workspace?.config.scoringRubric ?? "",
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

function summarizeApproval(approval: ApprovalItem): string {
  const toolName = approval.payload?.tool_name ?? approval.payload?.toolName;
  const executionStatus = approval.payload?.execution_status ?? approval.payload?.executionStatus;
  const reason = approval.payload?.reason;
  return [toolName, executionStatus, reason].filter((value): value is string => typeof value === "string" && value.length > 0).join(" · ");
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

function baseInputStyle(): React.CSSProperties {
  return {
    width: "100%",
    minHeight: 36,
    border: "1px solid var(--border-input)",
    borderRadius: 10,
    background: "var(--bg-card)",
    color: "var(--chat-text-primary)",
    fontSize: "var(--font-size-sm)",
    lineHeight: "var(--line-height-base)",
    fontFamily: "var(--font-sans)",
    padding: "8px 12px",
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

export function ChatOverlay({ transport, workspaceAgent }: ChatOverlayProps): JSX.Element {
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
  const [approvalActionId, setApprovalActionId] = useState<string | null>(null);
  const [runActionBusyId, setRunActionBusyId] = useState<string | null>(null);
  const [toolActionBusyKey, setToolActionBusyKey] = useState<string | null>(null);
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
    if (!isOpen) {
      return;
    }
    void loadWorkspaces();
    void loadSettings();
    void loadJobDescriptions();
    void loadSceneTemplates();
  }, [isOpen, loadJobDescriptions, loadSceneTemplates, loadSettings, loadWorkspaces]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const intervalId = window.setInterval(() => {
      void loadWorkspaces(false);
    }, 1500);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [isOpen, loadWorkspaces]);

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
    if (isOpen) {
      return;
    }
    assistantAbortRef.current?.abort();
    assistantAbortRef.current = null;
    assistantStreamContentRef.current = {};
    setSending(false);
  }, [isOpen]);

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
    if (!isOpen) {
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
  }, [conversationsByAgent, isOpen]);

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
        : copy("New autonomous session", "新 Autonomous 会话");
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
              : copy("New autonomous session", "新 Autonomous 会话"),
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
    const pendingApprovals = activeWorkspace.approvals.filter((approval) => approval.status === "pending").length;
    const openRuns = sortedRuns.filter((run) => isOpenRunStatus(run.status));
    const activeRuns = sortedRuns.filter((run) => isActivelyExecutingRunStatus(run.status));

    if (!latestOpenRun && !sortedRuns.length) {
      return {
        badgeLabel: describeConversationStatus(activeWorkspace.agent.status),
        title: copy("No active run", "当前没有运行中的任务"),
        detail: copy("Create a new session from the composer to start.", "可以通过下方输入框新建会话后启动。"),
        metrics: [
          `${copy("Sessions", "会话")} · ${activeWorkspace.conversations.length}`,
          `${copy("Pending approvals", "待审批")} · ${pendingApprovals}`,
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
          `${copy("Pending approvals", "待审批")} · ${pendingApprovals}`,
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
        `${copy("Pending approvals", "待审批")} · ${pendingApprovals}`,
      ].filter((value): value is string => Boolean(value)),
      tone: toneForRunStatus(highlightedRun.status),
    };
  }, [activeWorkspace, copy, describeConversationStatus]);

  const shouldShowRunStatusStrip = activePanel === "conversation" || activePanel === "runs" || activePanel === "approvals";

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
    if (!isOpen || !activeConversationId || !activeConversationCacheKey) {
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
    }, 1500);

    return () => {
      active = false;
      window.clearInterval(intervalId);
    };
  }, [activeAgent, activeConversationCacheKey, activeConversationId, copy, isOpen]);

  useEffect(() => {
    if (!isOpen) {
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
  }, [close, isOpen]);

  useEffect(() => {
    if (activePanel !== "conversation") {
      return;
    }
    const shell = streamShellRef.current;
    if (!shell) {
      return;
    }
    shell.scrollTop = shell.scrollHeight;
  }, [activePanel, activeConversation?.messages]);

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
        metadata: event.data,
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
          "Autonomous already has an open run. Wait for the current run to finish before starting the next goal.",
          "Autonomous 当前已有未结束的运行，请等待当前 run 结束后再启动下一轮 goal。",
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
          content: copy("Autonomous session has been submitted to the backend.", "Autonomous 会话已提交到后端。"),
          createdAt: new Date().toISOString(),
          status: "sent",
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

  const handleApprovalAction = async (approval: ApprovalItem, action: "approve" | "reject") => {
    setApprovalActionId(approval.id);
    try {
      if (action === "approve") {
        await apiClient.approveItem(approval.id);
      } else {
        await apiClient.rejectItem(approval.id, approvalNotes[approval.id]?.trim() || undefined);
      }
      await loadWorkspaces();
      setApprovalNotes((current) => {
        const next = { ...current };
        delete next[approval.id];
        return next;
      });
      setPanelNotice({
        panel: "approvals",
        tone: "success",
        message:
          action === "approve"
            ? copy("Approval has been confirmed.", "审批已通过。")
            : copy("Approval has been rejected.", "审批已拒绝。"),
      });
    } catch (error) {
      setPanelNotice({
        panel: "approvals",
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
        await apiClient.cancelAutonomousRun(run.id, copy("Cancelled from desktop overlay.", "在桌面悬浮窗中手动中止。"));
      } else {
        await apiClient.resumeAutonomousRun(run.id, copy("Resumed from desktop overlay.", "在桌面悬浮窗中手动恢复。"));
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
          `${template.title} template is now in the run form. Review the JD and goal text before starting.`,
          `${template.title} 模板已填入运行表单，启动前请确认 JD 与目标描述。`,
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
        message: copy("Title and goal text are required.", "标题和 goal 文本不能为空。"),
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
          "Autonomous already has an active run. Wait for it to finish before starting the next goal.",
          "Autonomous 当前已有运行中的任务，请等待当前运行结束后再启动下一轮 goal。",
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
          selectedTemplate ? `${selectedTemplate.title} created and queued.` : "Autonomous goal created and queued.",
          selectedTemplate ? `${selectedTemplate.title} 已创建并进入队列。` : "Autonomous goal 已创建并进入队列。",
        ),
      });
    } catch (error) {
      setPanelNotice({
        panel: "runs",
        tone: "error",
        message: error instanceof Error ? error.message : copy("Failed to create goal.", "创建 goal 失败。"),
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
          "Autonomous already has an open run. Wait for it to finish before queueing another template.",
          "Autonomous 当前已有未结束的运行，请等待其结束后再触发新的模板。",
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
            <div className="chat-card__eyebrow">{copy("New goal", "新建 goal")}</div>
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
                    <span>{copy("Template kind", "模板类型")} · {selectedTemplate.goalKind}</span>
                    <span>{copy("Requires JD", "需要 JD")} · {selectedTemplate.requiresJd ? copy("yes", "是") : copy("no", "否")}</span>
                    {selectedTemplate.supportsCandidateCountTarget ? (
                      <span>{copy("Supports target", "支持人数目标")} · {copy("yes", "是")}</span>
                    ) : null}
                  </div>
                </div>
              ) : null}
              <div style={{ display: "grid", gap: "var(--space-1)" }}>
                <span className="chat-list-item__title">{copy("Title", "标题")}</span>
                <input
                  type="text"
                  value={autonomousGoalDraft.title}
                  onChange={(event) =>
                    setAutonomousGoalDraft((current) => ({
                      ...current,
                      title: event.target.value,
                    }))
                  }
                  placeholder={copy("JD-xxx recruit 3 candidates", "例如：JD-xxx 找够 3 名候选人")}
                  style={baseInputStyle()}
                />
              </div>
              <div style={{ display: "grid", gap: "var(--space-1)" }}>
                <span className="chat-list-item__title">{copy("JD", "JD")}</span>
                <select
                  value={autonomousGoalDraft.jdId}
                  onChange={(event) =>
                    setAutonomousGoalDraft((current) => ({
                      ...current,
                      jdId: event.target.value,
                    }))
                  }
                  style={baseInputStyle()}
                >
                  <option value="">{copy("Select a JD (optional)", "选择一个 JD（可选）")}</option>
                  {jobDescriptionOptions.map((job) => (
                    <option key={job.jobDescriptionId ?? job.title} value={job.jobDescriptionId ?? ""}>
                      {job.title}
                    </option>
                  ))}
                </select>
              </div>
              {selectedTemplate?.supportsCandidateCountTarget ?? true ? (
                <div style={{ display: "grid", gap: "var(--space-1)" }}>
                  <span className="chat-list-item__title">{copy("Candidate target", "候选人数目标")}</span>
                  <input
                    type="number"
                    min={1}
                    value={autonomousGoalDraft.candidateCountTarget}
                    onChange={(event) =>
                      setAutonomousGoalDraft((current) => ({
                        ...current,
                        candidateCountTarget: event.target.value,
                      }))
                    }
                    style={baseInputStyle()}
                  />
                </div>
              ) : null}
              <div style={{ display: "grid", gap: "var(--space-1)" }}>
                <span className="chat-list-item__title">{copy("Goal text", "Goal 文本")}</span>
                <textarea
                  value={autonomousGoalDraft.goalText}
                  onChange={(event) =>
                    setAutonomousGoalDraft((current) => ({
                      ...current,
                      goalText: event.target.value,
                    }))
                  }
                  placeholder={copy("Describe the autonomous recruiting task…", "描述本轮 Autonomous 要完成的招聘任务…")}
                  style={{
                    ...baseInputStyle(),
                    minHeight: 116,
                    resize: "vertical",
                  }}
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
                      focusAgent("autonomous", "conversation");
                      setSelectedConversation((current) => ({
                        ...current,
                        autonomous: activeWorkspace?.conversations[0]?.id ?? run.refId ?? current.autonomous,
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

  const renderApprovalsPanel = (approvals: ApprovalItem[]) => {
    if (!approvals.length) {
      return renderEmptyPanel(copy("No approvals", "当前没有审批项"), copy("When the agent requires review, pending approvals will appear here.", "当 Agent 需要人工确认时，审批项会出现在这里。"));
    }
    return (
      <div className="chat-stream">
        {approvals.map((approval) => {
          const pending = approval.status === "pending";
          return (
            <section key={approval.id} className="chat-card">
              <div className="chat-card__title-row">
                <div>
                  <div className="chat-list-item__title">{approval.title}</div>
                  <div className="chat-list-item__meta">
                    {approval.requester} · {formatDateTime(approval.createdAt)}
                  </div>
                </div>
                <StatusBadge tone={approval.status === "approved" ? "positive" : approval.status === "rejected" ? "critical" : "warning"}>
                  {approval.status}
                </StatusBadge>
              </div>
              <div className="chat-list-item__summary">{approval.detail}</div>
              {summarizeApproval(approval) ? <div className="chat-list-item__meta">{summarizeApproval(approval)}</div> : null}
              {approval.notes ? <div className="chat-list-item__meta">{copy("Notes", "备注")} · {approval.notes}</div> : null}
              {pending ? (
                <div style={{ display: "grid", gap: "var(--space-2)" }}>
                  <textarea
                    value={approvalNotes[approval.id] ?? ""}
                    onChange={(event) =>
                      setApprovalNotes((current) => ({
                        ...current,
                        [approval.id]: event.target.value,
                      }))
                    }
                    placeholder={copy("Optional reviewer note for reject path…", "给拒绝动作填写可选备注…")}
                    style={{
                      ...baseInputStyle(),
                      minHeight: 88,
                      resize: "vertical",
                    }}
                  />
                  <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
                    <button
                      type="button"
                      className="chat-composer__submit"
                      disabled={approvalActionId === approval.id}
                      onClick={() => void handleApprovalAction(approval, "approve")}
                    >
                      {approvalActionId === approval.id ? copy("Working…", "处理中…") : copy("Approve", "通过")}
                    </button>
                    <button
                      type="button"
                      className="chat-overlay__header-button"
                      disabled={approvalActionId === approval.id}
                      onClick={() => void handleApprovalAction(approval, "reject")}
                    >
                      {copy("Reject", "拒绝")}
                    </button>
                  </div>
                </div>
              ) : (
                <div className="chat-list-item__meta">
                  {copy("Reviewed", "已处理")} · {approval.reviewedBy || copy("system", "系统")} · {approval.reviewedAt ? formatDateTime(approval.reviewedAt) : "-"}
                </div>
              )}
            </section>
          );
        })}
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

    return (
      <div className="chat-stream">
        <section className="chat-card">
          <div className="chat-card__eyebrow">{copy("Desktop controls", "桌面控制")}</div>
          <div style={{ display: "grid", gap: "var(--space-3)" }}>
            <div style={{ display: "grid", gap: "var(--space-1)" }}>
              <span className="chat-list-item__title">{copy("Desktop approvals only", "仅桌面审批")}</span>
              <label
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "var(--space-2)",
                  fontSize: "var(--font-size-sm)",
                  color: "var(--chat-text-secondary)",
                }}
              >
                <input
                  type="checkbox"
                  checked={configDraft.desktopApprovalsOnly}
                  onChange={(event) =>
                    setConfigDraft((current) =>
                      current
                        ? {
                            ...current,
                            desktopApprovalsOnly: event.target.checked,
                          }
                        : current,
                    )
                  }
                />
                {copy("Require local operator confirmation before continuing", "继续执行前必须经过本地操作员确认")}
              </label>
            </div>

            <div style={{ display: "grid", gap: "var(--space-1)" }}>
              <span className="chat-list-item__title">{copy("Autonomy enabled", "启用自治运行")}</span>
              <label
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "var(--space-2)",
                  fontSize: "var(--font-size-sm)",
                  color: "var(--chat-text-secondary)",
                }}
              >
                <input
                  type="checkbox"
                  checked={configDraft.autonomyEnabled}
                  onChange={(event) =>
                    setConfigDraft((current) =>
                      current
                        ? {
                            ...current,
                            autonomyEnabled: event.target.checked,
                          }
                        : current,
                    )
                  }
                />
                {copy("Allow autonomous background execution", "允许 Autonomous 在后台执行")}
              </label>
            </div>

            <div style={{ display: "grid", gap: "var(--space-1)" }}>
              <span className="chat-list-item__title">{copy("Skill health autonomy", "技能健康巡检")}</span>
              <label
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "var(--space-2)",
                  fontSize: "var(--font-size-sm)",
                  color: "var(--chat-text-secondary)",
                }}
              >
                <input
                  type="checkbox"
                  checked={configDraft.skillHealthAutonomyEnabled}
                  onChange={(event) =>
                    setConfigDraft((current) =>
                      current
                        ? {
                            ...current,
                            skillHealthAutonomyEnabled: event.target.checked,
                          }
                        : current,
                    )
                  }
                />
                {copy("Run periodic skill health checks automatically", "自动执行周期性技能健康巡检")}
              </label>
            </div>

            <div style={{ display: "grid", gap: "var(--space-1)" }}>
              <span className="chat-list-item__title">{copy("Health check interval (seconds)", "巡检间隔（秒）")}</span>
              <input
                type="number"
                min={1}
                value={configDraft.skillHealthAutonomyIntervalSeconds}
                onChange={(event) =>
                  setConfigDraft((current) =>
                    current
                      ? {
                          ...current,
                          skillHealthAutonomyIntervalSeconds: event.target.value,
                        }
                      : current,
                  )
                }
                style={baseInputStyle()}
              />
            </div>

            <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
              <button type="button" className="chat-composer__submit" disabled={savingConfig} onClick={() => void handleSaveConfig()}>
                {savingConfig ? copy("Saving…", "保存中…") : copy("Save configuration", "保存配置")}
              </button>
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
            </div>
          </div>
        </section>

        <section className="chat-card">
          <div className="chat-card__eyebrow">
            {activeAgent === "autonomous" ? copy("Autonomous prompt", "Autonomous Prompt") : copy("Assistant prompt", "Assistant Prompt")}
          </div>
          <div style={{ display: "grid", gap: "var(--space-3)" }}>
            <div style={{ display: "grid", gap: "var(--space-1)" }}>
              <span className="chat-list-item__title">{copy("System prompt", "System Prompt")}</span>
              <textarea
                value={agentConfigDrafts[activeAgent].systemPrompt}
                onChange={(event) =>
                  setAgentConfigDrafts((current) => ({
                    ...current,
                    [activeAgent]: {
                      ...current[activeAgent],
                      systemPrompt: event.target.value,
                    },
                  }))
                }
                style={{
                  ...baseInputStyle(),
                  minHeight: 160,
                  resize: "vertical",
                }}
              />
            </div>

            {activeAgent === "autonomous" ? (
              <div style={{ display: "grid", gap: "var(--space-1)" }}>
                <span className="chat-list-item__title">{copy("Goal template", "任务描述模板")}</span>
                <textarea
                  value={agentConfigDrafts[activeAgent].goalTemplate}
                  onChange={(event) =>
                    setAgentConfigDrafts((current) => ({
                      ...current,
                      [activeAgent]: {
                        ...current[activeAgent],
                        goalTemplate: event.target.value,
                      },
                    }))
                  }
                  placeholder={copy(
                    "Describe the long-running recruiting mission for autonomous execution…",
                    "填写 Autonomous 持续执行的真实招聘任务描述…",
                  )}
                  style={{
                    ...baseInputStyle(),
                    minHeight: 196,
                    resize: "vertical",
                  }}
                />
              </div>
            ) : null}

            <div style={{ display: "grid", gap: "var(--space-1)" }}>
              <span className="chat-list-item__title">{copy("Scoring rubric", "评分 Rubric")}</span>
              <textarea
                value={agentConfigDrafts[activeAgent].scoringRubric}
                onChange={(event) =>
                  setAgentConfigDrafts((current) => ({
                    ...current,
                    [activeAgent]: {
                      ...current[activeAgent],
                      scoringRubric: event.target.value,
                    },
                  }))
                }
                placeholder={copy("Paste the scoring rubric used by this agent…", "填写当前 Agent 使用的评分 Rubric…")}
                style={{
                  ...baseInputStyle(),
                  minHeight: 136,
                  resize: "vertical",
                }}
              />
            </div>
          </div>
        </section>

        <section className="chat-card">
          <div className="chat-card__eyebrow">{copy("Environment snapshot", "环境快照")}</div>
          <div className="chat-card__meta-list">
            <span>{copy("Locale", "语言")} · {settingsSnapshot.locale}</span>
            <span>{copy("Timezone", "时区")} · {settingsSnapshot.timezone}</span>
            <span>{copy("Intranet sync", "内网同步")} · {settingsSnapshot.intranetEnabled ? copy("enabled", "已启用") : copy("disabled", "已关闭")}</span>
            <span>{copy("Active account", "当前账户")} · {settingsSnapshot.platform.account}</span>
          </div>
        </section>

        <section className="chat-card chat-card--code">
          <div className="chat-card__eyebrow">{copy("Agent profile", "Agent 画像")}</div>
          <div className="chat-card__meta-list">
            <span>{copy("Provider", "Provider")} · {activeWorkspace?.config.providerLabel || "-"}</span>
            <span>{copy("Model", "模型")} · {activeWorkspace?.config.modelLabel || activeWorkspace?.agent.defaultModel || "-"}</span>
          </div>
          {activeWorkspace?.config.boundaries?.length ? (
            <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
              {activeWorkspace.config.boundaries.map((boundary) => (
                <span key={boundary} className="chat-chip">
                  {boundary}
                </span>
              ))}
            </div>
          ) : null}
          <pre>
            <code>{activeWorkspace?.config.systemPrompt || copy("No prompt exposed yet.", "后端暂未暴露 prompt。")}</code>
          </pre>
          {activeWorkspace?.config.goalTemplate ? (
            <pre>
              <code>{activeWorkspace.config.goalTemplate}</code>
            </pre>
          ) : null}
          {activeWorkspace?.config.scoringRubric ? (
            <pre>
              <code>{activeWorkspace.config.scoringRubric}</code>
            </pre>
          ) : null}
        </section>
      </div>
    );
  };

  const renderRailContent = () => {
    if (!activeWorkspace) {
      return null;
    }

    switch (activePanel) {
      case "conversation":
        return (
          <div className="chat-rail__stack">
            <section className="chat-card">
              <div className="chat-card__eyebrow">{copy("Agent summary", "Agent 摘要")}</div>
              <div className="chat-card__title-row">
                <h4>{activeWorkspace.agent.name}</h4>
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
      case "approvals":
        return (
          <section className="chat-card">
            <div className="chat-card__eyebrow">{copy("Approval summary", "审批概览")}</div>
            <div className="chat-card__meta-list">
              <span>{copy("Pending", "待审批")} · {activeWorkspace.approvals.filter((approval) => approval.status === "pending").length}</span>
              <span>{copy("Approved", "已通过")} · {activeWorkspace.approvals.filter((approval) => approval.status === "approved").length}</span>
              <span>{copy("Rejected", "已拒绝")} · {activeWorkspace.approvals.filter((approval) => approval.status === "rejected").length}</span>
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

  const renderPanelContent = () => {
    if (activePanel === "conversation") {
      return (
        <ChatMessageStream
          loading={loadingWorkspace || loadingConversation}
          messages={activeConversation?.messages ?? []}
        />
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
      case "approvals":
        return renderApprovalsPanel(activeWorkspace.approvals);
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

  if (!isOpen) {
    return <></>;
  }

  return (
    <div className="chat-overlay-shell">
      <section
        className="chat-overlay"
        style={{
          left: `${overlayRect.x}px`,
          top: `${overlayRect.y}px`,
          width: `${overlayRect.width}px`,
          height: `${overlayRect.height}px`,
        }}
      >
        <header className="chat-overlay__header" onMouseDown={startHeaderDrag}>
          <div className="chat-overlay__brand">
            <span className="chat-overlay__logo">RA</span>
            <div>
              <div className="chat-overlay__eyebrow">Recruit Agent</div>
              <div className="chat-overlay__title">
                {activeConversationSummary?.title || (activeAgent === "assistant" ? "Assistant" : "Autonomous")}
              </div>
            </div>
          </div>
          <div className="chat-overlay__header-actions">
            {transport !== "http" ? <StatusBadge tone="critical">{copy("offline", "离线")}</StatusBadge> : null}
            <button type="button" className="chat-overlay__header-button" onClick={() => setRailCollapsed((current) => !current)}>
              {railCollapsed ? copy("Show rail", "展开侧栏") : copy("Hide rail", "收起侧栏")}
            </button>
            <button type="button" className="chat-overlay__header-button" onClick={close}>
              {copy("Minimize", "最小化")}
            </button>
            <button type="button" className="chat-overlay__header-button" onClick={close}>
              {copy("Close", "关闭")}
            </button>
          </div>
        </header>

        <div className="chat-overlay__body">
          <aside className="chat-overlay__sidebar">
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
              + {activeAgent === "assistant" ? copy("New session", "新会话") : copy("New goal", "新目标")}
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
                          {kind === "assistant" ? copy("Assistant", "Assistant") : copy("Autonomous", "Autonomous")}
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
                            <div className="chat-overlay__conversation-title">{conversation.title}</div>
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
          </aside>

          <main className="chat-overlay__main">
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

            {activeWorkspace && activeRunStatusText && shouldShowRunStatusStrip ? (
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

            <div ref={streamShellRef} className="chat-overlay__stream-shell">
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
                    ? copy("Autonomous session", "Autonomous 会话")
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

          {!railCollapsed ? <aside className="chat-overlay__rail">{renderRailContent()}</aside> : null}
        </div>

        <div className="chat-overlay__resize-handle" onMouseDown={startResize} />
      </section>

      {workspaceAgent.status === "waiting_human" ? (
        <div className="chat-overlay__toast">{copy("Agent is waiting for desktop approval.", "Agent 正在等待桌面审批。")}</div>
      ) : null}
    </div>
  );
}
