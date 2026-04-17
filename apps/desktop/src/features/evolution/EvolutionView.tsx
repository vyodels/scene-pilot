import React, { useEffect, useMemo, useState } from "react";
import { MetricCard, Panel, StatusBadge } from "../../components";
import { formatCompactDate } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { translateUiToken } from "../../lib/uiText";
import type {
  AgentGlobalMemoryRecord,
  ApprovalItem,
  ApplicationRecord,
  EvolutionArtifactRecord,
  JobMemoryRecord,
  PersonMemoryRecord,
  RecruitAgentProfileRecord,
  SkillRecord,
} from "../../lib/types";

type EvolutionSection = "inbox" | "skills" | "memory" | "prompts" | "playbook" | "approvals" | "history";

interface EvolutionViewProps {
  profile: RecruitAgentProfileRecord | null;
  applications: ApplicationRecord[];
  approvals: ApprovalItem[];
  skills: SkillRecord[];
  artifacts: EvolutionArtifactRecord[];
  personMemories: PersonMemoryRecord[];
  jobMemories: JobMemoryRecord[];
  globalMemory: AgentGlobalMemoryRecord | null;
  pendingActionId?: string;
  requestedSection?: string;
  requestedItemId?: string;
  onApprove(id: string): Promise<void> | void;
  onReject(id: string): Promise<void> | void;
  onSaveProfile(payload: Partial<RecruitAgentProfileRecord>): Promise<void> | void;
  onUpdateSkill(skillId: string, payload: Partial<SkillRecord>): Promise<void> | void;
  onDeleteSkill(skillId: string): Promise<void> | void;
  onUpdatePersonMemory(personId: string, payload: Partial<PersonMemoryRecord>): Promise<void> | void;
  onCompactPersonMemory(personId: string): Promise<void> | void;
  onUpdateJobMemory(jobDescriptionId: string, payload: Partial<JobMemoryRecord>): Promise<void> | void;
  onCompactJobMemory(jobDescriptionId: string): Promise<void> | void;
  onUpdateGlobalMemory(payload: Partial<AgentGlobalMemoryRecord>): Promise<void> | void;
  onCompactGlobalMemory(): Promise<void> | void;
  onUpdateArtifact(artifactId: string, payload: Partial<EvolutionArtifactRecord>): Promise<void> | void;
  onOpenApplication(applicationId: string): void;
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

type SelectionKey = string;

type ListRow = {
  key: string;
  label: string;
  detail: string;
  status: string;
  updatedAt: string;
  tone: "positive" | "neutral" | "warning" | "critical";
};

const inputStyle: React.CSSProperties = {
  width: "100%",
  borderRadius: theme.radius.sm,
  border: `1px solid ${theme.colors.border}`,
  background: theme.colors.panel,
  color: theme.colors.text,
  minHeight: "var(--space-8)",
  padding: "0 var(--space-3)",
  fontSize: "var(--font-size-sm)",
};

const textAreaStyle: React.CSSProperties = {
  ...inputStyle,
  minHeight: "calc(var(--space-12) + var(--space-12) + var(--space-3))",
  padding: "var(--space-3)",
  lineHeight: 1.6,
  resize: "vertical",
};

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

const sectionLabelStyle: React.CSSProperties = {
  fontSize: "var(--font-size-xs)",
  color: theme.colors.muted,
  textTransform: "uppercase",
  letterSpacing: "0.12em",
};

function selectableRowStyle(active: boolean): React.CSSProperties {
  return {
    display: "grid",
    gap: "var(--space-2)",
    textAlign: "left",
    padding: "var(--space-3)",
    borderRadius: theme.radius.lg,
    border: `1px solid ${active ? theme.colors.accent : theme.colors.border}`,
    background: active ? theme.colors.accentSoft : theme.colors.background,
    color: theme.colors.text,
    cursor: "pointer",
  };
}

function stringifyJson(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2);
}

function parseJsonDraft(label: string, value: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(value);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
  } catch {
    // handled below
  }
  throw new Error(`${label} JSON 格式无效。`);
}

function linesToArray(value: string): string[] {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

function arrayToLines(value: unknown): string {
  return Array.isArray(value) ? value.map((item) => String(item)).join("\n") : "";
}

function compactNumber(value: unknown, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function toneFromStatus(value: string): "positive" | "neutral" | "warning" | "critical" {
  if (/(critical|rejected|failed|degraded|disabled|cooldown)/i.test(value)) {
    return "critical";
  }
  if (/(pending|draft|review|warning|blocked)/i.test(value)) {
    return "warning";
  }
  if (/(approved|applied|active|healthy|completed)/i.test(value)) {
    return "positive";
  }
  return "neutral";
}

export function EvolutionView({
  profile,
  applications,
  approvals,
  skills,
  artifacts,
  personMemories,
  jobMemories,
  globalMemory,
  pendingActionId,
  requestedSection,
  requestedItemId,
  onApprove,
  onReject,
  onSaveProfile,
  onUpdateSkill,
  onDeleteSkill,
  onUpdatePersonMemory,
  onCompactPersonMemory,
  onUpdateJobMemory,
  onCompactJobMemory,
  onUpdateGlobalMemory,
  onCompactGlobalMemory,
  onUpdateArtifact,
  onOpenApplication,
}: EvolutionViewProps): JSX.Element {
  const { copy } = useI18n();
  const [section, setSection] = useState<EvolutionSection>("inbox");
  const [selectedKey, setSelectedKey] = useState<SelectionKey>();
  const [errorMessage, setErrorMessage] = useState<string>();

  const applicationDisplayNameById = useMemo(() => {
    const mapping = new Map<string, string>();
    for (const application of applications) {
      mapping.set(application.id, application.person.name);
      if (application.applicationId) {
        mapping.set(application.applicationId, application.person.name);
      }
      if (application.personId) {
        mapping.set(application.personId, application.person.name);
      }
    }
    return mapping;
  }, [applications]);
  const evolutionApprovals = useMemo(() => approvals.filter((item) => !item.relatedCandidateId), [approvals]);

  useEffect(() => {
    if (requestedSection === "inbox" || requestedSection === "skills" || requestedSection === "memory" || requestedSection === "prompts" || requestedSection === "playbook" || requestedSection === "approvals" || requestedSection === "history") {
      setSection(requestedSection);
    }
  }, [requestedSection]);

  const inboxRows = useMemo<ListRow[]>(
    () =>
      [
        ...evolutionApprovals
          .filter((item) => item.status === "pending")
          .map((item) => ({
            key: `approval:${item.id}`,
            label: item.title,
            detail: item.detail,
            status: item.status,
            updatedAt: item.updatedAt ?? item.createdAt,
            tone: toneFromStatus(item.status),
          })),
        ...artifacts
          .filter((item) => /(pending|draft|review)/i.test(item.status))
          .map((item) => ({
            key: `artifact:${item.id}`,
            label: item.title,
            detail: item.summary ?? item.artifactKind,
            status: item.status,
            updatedAt: item.updatedAt,
            tone: toneFromStatus(item.status),
          })),
      ].sort((left, right) => right.updatedAt.localeCompare(left.updatedAt)),
    [artifacts, evolutionApprovals],
  );

  const skillRows = useMemo<ListRow[]>(
    () =>
      skills
        .map((skill) => ({
          key: `skill:${skill.id}`,
          label: skill.name,
          detail: `${skill.boundStage} · ${skill.summary}`,
          status: skill.status === "active" ? skill.health : skill.status,
          updatedAt: skill.lastCheckedAt,
          tone: toneFromStatus(skill.health === "healthy" ? skill.status : skill.health),
        }))
        .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt)),
    [skills],
  );

  const memoryRows = useMemo<ListRow[]>(
    () => [
      {
        key: "policy:candidate",
        label: copy("Candidate memory policy", "候选人记忆策略"),
        detail: copy("Strict isolation, progressive disclosure, and auto compaction.", "严格隔离、渐进式披露和自动压缩。"),
        status: String(((profile?.memoryPolicy ?? {}) as Record<string, unknown>).candidate_memory ? "active" : "missing"),
        updatedAt: profile?.updatedAt ?? new Date().toISOString(),
        tone: "neutral",
      },
      {
        key: "policy:job",
        label: copy("JD memory policy", "JD 记忆策略"),
        detail: copy("Strict JD scoping with its own compact threshold.", "按 JD 严格隔离并单独维护阈值。"),
        status: String(((profile?.memoryPolicy ?? {}) as Record<string, unknown>).job_memory ? "active" : "missing"),
        updatedAt: profile?.updatedAt ?? new Date().toISOString(),
        tone: "neutral",
      },
      {
        key: "policy:global",
        label: copy("Global memory policy", "全局记忆策略"),
        detail: copy("Cross-candidate learnings only, without candidate leakage.", "只保留跨候选人的经验，不串候选人事实。"),
        status: String(((profile?.memoryPolicy ?? {}) as Record<string, unknown>).agent_global_memory ? "active" : "missing"),
        updatedAt: profile?.updatedAt ?? new Date().toISOString(),
        tone: "neutral",
      },
      ...personMemories.map((memory) => ({
        key: `memory:candidate:${memory.personId}`,
            label: applicationDisplayNameById.get(memory.personId) ?? memory.personId,
        detail: memory.summary ?? copy("Candidate-isolated memory", "候选人隔离记忆"),
        status: memory.status,
        updatedAt: memory.updatedAt,
        tone: toneFromStatus(memory.status),
      })),
      ...jobMemories.map((memory) => ({
        key: `memory:job:${memory.jobDescriptionId}`,
        label: memory.jobDescriptionId,
        detail: memory.summary ?? copy("JD-isolated memory", "JD 隔离记忆"),
        status: memory.status,
        updatedAt: memory.updatedAt,
        tone: toneFromStatus(memory.status),
      })),
      ...(globalMemory
        ? [
            {
              key: "memory:global",
              label: copy("Agent global memory", "Agent 全局记忆"),
              detail: globalMemory.summary ?? copy("Global learnings", "全局经验"),
              status: globalMemory.status,
              updatedAt: globalMemory.updatedAt,
              tone: toneFromStatus(globalMemory.status),
            },
          ]
        : []),
    ],
    [applicationDisplayNameById, personMemories, copy, globalMemory, jobMemories, profile],
  );

  const promptRows = useMemo<ListRow[]>(
    () => [
      {
        key: "prompt:profile",
        label: copy("Current prompt set", "当前提示词组"),
        detail: String(((profile?.promptConfig ?? {}) as Record<string, unknown>).system_prompt ?? copy("No prompt configured.", "尚未配置系统提示词。")),
        status: profile?.status ?? "draft",
        updatedAt: profile?.updatedAt ?? new Date().toISOString(),
        tone: toneFromStatus(profile?.status ?? "draft"),
      },
      ...artifacts
        .filter((item) => item.artifactKind === "prompt_patch")
        .map((item) => ({
          key: `artifact:${item.id}`,
          label: item.title,
          detail: item.summary ?? item.artifactKind,
          status: item.status,
          updatedAt: item.updatedAt,
          tone: toneFromStatus(item.status),
        })),
    ],
    [artifacts, copy, profile],
  );

  const playbookRows = useMemo<ListRow[]>(
    () => [
      {
        key: "playbook:current",
        label: copy("Current workflow blueprint", "当前工作流蓝图"),
        detail: copy("Default routing and status flow for the review center.", "审查中心默认的路由与状态流。"),
        status: profile?.status ?? "draft",
        updatedAt: profile?.updatedAt ?? new Date().toISOString(),
        tone: toneFromStatus(profile?.status ?? "draft"),
      },
      ...artifacts
        .filter((item) => /(playbook_patch|playbook_patch)/i.test(item.artifactKind))
        .map((item) => ({
          key: `artifact:${item.id}`,
          label: item.title,
          detail: item.summary ?? item.artifactKind,
          status: item.status,
          updatedAt: item.updatedAt,
          tone: toneFromStatus(item.status),
        })),
    ],
    [artifacts, copy, profile],
  );

  const approvalRows = useMemo<ListRow[]>(
    () =>
      evolutionApprovals.map((item) => ({
        key: `approval:${item.id}`,
        label: item.title,
        detail: item.detail,
        status: item.status,
        updatedAt: item.updatedAt ?? item.createdAt,
        tone: toneFromStatus(item.status),
      })),
    [evolutionApprovals],
  );

  const historyRows = useMemo<ListRow[]>(
    () =>
      [
        ...artifacts
          .filter((item) => /(approved|applied|rejected|archived)/i.test(item.status))
          .map((item) => ({
            key: `artifact:${item.id}`,
            label: item.title,
            detail: item.summary ?? item.artifactKind,
            status: item.status,
            updatedAt: item.updatedAt,
            tone: toneFromStatus(item.status),
          })),
        ...evolutionApprovals
          .filter((item) => item.status !== "pending")
          .map((item) => ({
            key: `approval:${item.id}`,
            label: item.title,
            detail: item.detail,
            status: item.status,
            updatedAt: item.updatedAt ?? item.createdAt,
            tone: toneFromStatus(item.status),
          })),
      ].sort((left, right) => right.updatedAt.localeCompare(left.updatedAt)),
    [artifacts, evolutionApprovals],
  );

  const rowsBySection: Record<EvolutionSection, ListRow[]> = {
    inbox: inboxRows,
    skills: skillRows,
    memory: memoryRows,
    prompts: promptRows,
    playbook: playbookRows,
    approvals: approvalRows,
    history: historyRows,
  };

  const currentRows = rowsBySection[section];
  const reviewMetrics: Array<{
    label: string;
    value: number;
    note: string;
    tone: "positive" | "neutral" | "warning";
  }> = [
    {
      label: copy("Open decisions", "待处理决策"),
      value: evolutionApprovals.filter((item) => item.status === "pending").length,
      note: copy("Approvals and review items still waiting for a final decision.", "仍在等待最终决策的审批和审查项。"),
      tone: evolutionApprovals.some((item) => item.status === "pending") ? "warning" : "positive",
    },
    {
      label: copy("Skill rules", "Skill 规则"),
      value: skillRows.length,
      note: copy("Published and pending skill rules currently visible in the strategy registry.", "当前在策略注册表里可见的已发布和待处理 skill 规则。"),
      tone: skillRows.length ? "neutral" : "positive",
    },
    {
      label: copy("Memory scopes", "记忆范围"),
      value: memoryRows.length,
      note: copy("Candidate, JD, and global memory scopes managed from the same review plane.", "在同一审查面里管理的候选人、JD 和全局记忆范围。"),
      tone: memoryRows.length ? "neutral" : "positive",
    },
    {
      label: copy("Review assets", "审查资产"),
      value: historyRows.length,
      note: copy("Historical review artifacts that can be audited or reopened.", "可供审计或重新查看的历史审查资产。"),
      tone: historyRows.length ? "neutral" : "positive",
    },
  ];

  useEffect(() => {
    if (requestedItemId) {
      const direct = currentRows.find((item) => item.key === requestedItemId || item.key.endsWith(`:${requestedItemId}`));
      if (direct) {
        setSelectedKey(direct.key);
        return;
      }
    }
    if (!currentRows.length) {
      setSelectedKey(undefined);
      return;
    }
    if (!selectedKey || !currentRows.some((item) => item.key === selectedKey)) {
      setSelectedKey(currentRows[0].key);
    }
  }, [currentRows, requestedItemId, selectedKey]);

  const selectedApproval = selectedKey?.startsWith("approval:") ? evolutionApprovals.find((item) => item.id === selectedKey.split(":")[1]) ?? null : null;
  const selectedSkill = selectedKey?.startsWith("skill:") ? skills.find((item) => item.id === selectedKey.split(":")[1]) ?? null : null;
  const selectedArtifact = selectedKey?.startsWith("artifact:") ? artifacts.find((item) => item.id === selectedKey.split(":")[1]) ?? null : null;
  const selectedMemoryRecord = useMemo(() => {
    if (!selectedKey?.startsWith("memory:")) {
      return null;
    }
    if (selectedKey === "memory:global") {
      return globalMemory ? { kind: "global" as const, record: globalMemory } : null;
    }
    const [, scope, target] = selectedKey.split(":");
    if (scope === "candidate") {
      const record = personMemories.find((item) => item.personId === target);
      return record ? { kind: "candidate" as const, record } : null;
    }
    const record = jobMemories.find((item) => item.jobDescriptionId === target);
    return record ? { kind: "job" as const, record } : null;
  }, [personMemories, globalMemory, jobMemories, selectedKey]);

  const selectedPolicyKey = selectedKey?.startsWith("policy:") ? selectedKey.split(":")[1] : null;

  const [skillDescriptionDraft, setSkillDescriptionDraft] = useState("");
  const [skillStrategyDraft, setSkillStrategyDraft] = useState("{}");
  const [skillExecutionHintsDraft, setSkillExecutionHintsDraft] = useState("{}");
  const [skillMetadataDraft, setSkillMetadataDraft] = useState("{}");

  const [artifactSummaryDraft, setArtifactSummaryDraft] = useState("");
  const [artifactStatusDraft, setArtifactStatusDraft] = useState<EvolutionArtifactRecord["status"]>("draft");
  const [artifactBodyDraft, setArtifactBodyDraft] = useState("{}");
  const [artifactMetadataDraft, setArtifactMetadataDraft] = useState("{}");

  const [memorySummaryDraft, setMemorySummaryDraft] = useState("");
  const [memoryDisclosurePreviewDraft, setMemoryDisclosurePreviewDraft] = useState("");
  const [memoryDisclosureOperatorDraft, setMemoryDisclosureOperatorDraft] = useState("");
  const [memoryDisclosureModelDraft, setMemoryDisclosureModelDraft] = useState("");
  const [memoryRawDraft, setMemoryRawDraft] = useState("{}");
  const [memoryCompactDraft, setMemoryCompactDraft] = useState("{}");

  const [policyThresholdDraft, setPolicyThresholdDraft] = useState("1000000");
  const [policyAutoCompact, setPolicyAutoCompact] = useState(true);
  const [policyDisclosureDraft, setPolicyDisclosureDraft] = useState("preview\noperator_summary\nmodel_context");

  const [identityDraft, setIdentityDraft] = useState("");
  const [positioningDraft, setPositioningDraft] = useState("");
  const [toneDraft, setToneDraft] = useState("");
  const [dutiesDraft, setDutiesDraft] = useState("");
  const [boundariesDraft, setBoundariesDraft] = useState("");
  const [systemPromptDraft, setSystemPromptDraft] = useState("");
  const [contextSlotsDraft, setContextSlotsDraft] = useState("");

  const [playbookJsonDraft, setPlaybookJsonDraft] = useState("{}");
  const [defaultStatusesDraft, setDefaultStatusesDraft] = useState("");

  useEffect(() => {
    if (!selectedSkill) {
      setSkillDescriptionDraft("");
      setSkillStrategyDraft("{}");
      setSkillExecutionHintsDraft("{}");
      setSkillMetadataDraft("{}");
      return;
    }
    setSkillDescriptionDraft(selectedSkill.description ?? "");
    setSkillStrategyDraft(stringifyJson(selectedSkill.strategy));
    setSkillExecutionHintsDraft(stringifyJson(selectedSkill.executionHints));
    setSkillMetadataDraft(stringifyJson(selectedSkill.skillMetadata));
  }, [selectedSkill]);

  useEffect(() => {
    if (!selectedArtifact) {
      setArtifactSummaryDraft("");
      setArtifactStatusDraft("draft");
      setArtifactBodyDraft("{}");
      setArtifactMetadataDraft("{}");
      return;
    }
    setArtifactSummaryDraft(selectedArtifact.summary ?? "");
    setArtifactStatusDraft(selectedArtifact.status);
    setArtifactBodyDraft(stringifyJson(selectedArtifact.artifactBody));
    setArtifactMetadataDraft(stringifyJson(selectedArtifact.artifactMetadata));
  }, [selectedArtifact]);

  useEffect(() => {
    if (!selectedMemoryRecord) {
      setMemorySummaryDraft("");
      setMemoryDisclosurePreviewDraft("");
      setMemoryDisclosureOperatorDraft("");
      setMemoryDisclosureModelDraft("");
      setMemoryRawDraft("{}");
      setMemoryCompactDraft("{}");
      return;
    }
    setMemorySummaryDraft(selectedMemoryRecord.record.summary ?? "");
    setMemoryDisclosurePreviewDraft(selectedMemoryRecord.record.disclosure.preview ?? "");
    setMemoryDisclosureOperatorDraft(selectedMemoryRecord.record.disclosure.operatorSummary ?? "");
    setMemoryDisclosureModelDraft(selectedMemoryRecord.record.disclosure.modelContext ?? "");
    setMemoryRawDraft(stringifyJson(selectedMemoryRecord.record.rawContent));
    setMemoryCompactDraft(stringifyJson(selectedMemoryRecord.record.content));
  }, [selectedMemoryRecord]);

  useEffect(() => {
    if (!selectedPolicyKey || !profile) {
      return;
    }
    const memoryPolicy = (profile.memoryPolicy ?? {}) as Record<string, unknown>;
    const policyKey = selectedPolicyKey === "candidate" ? "candidate_memory" : selectedPolicyKey === "job" ? "job_memory" : "agent_global_memory";
    const policy = (memoryPolicy[policyKey] ?? {}) as Record<string, unknown>;
    setPolicyThresholdDraft(String(policy.compact_threshold ?? 1_000_000));
    setPolicyAutoCompact(Boolean(policy.auto_compact ?? true));
    setPolicyDisclosureDraft(arrayToLines(policy.disclosure ?? ["preview", "operator_summary", "model_context"]));
  }, [profile, selectedPolicyKey]);

  useEffect(() => {
    if (!profile) {
      return;
    }
    const roleDefinition = (profile.roleDefinition ?? {}) as Record<string, unknown>;
    const promptConfig = (profile.promptConfig ?? {}) as Record<string, unknown>;
    const playbookBlueprint = (profile.playbookBlueprint ?? {}) as Record<string, unknown>;
    const statusMachine = (playbookBlueprint.status_machine ?? {}) as Record<string, unknown>;
    setIdentityDraft(String(roleDefinition.identity ?? ""));
    setPositioningDraft(String(roleDefinition.positioning ?? ""));
    setToneDraft(String(roleDefinition.tone ?? ""));
    setDutiesDraft(arrayToLines(roleDefinition.duties));
    setBoundariesDraft(arrayToLines(roleDefinition.boundaries));
    setSystemPromptDraft(String(promptConfig.system_prompt ?? ""));
    setContextSlotsDraft(arrayToLines(promptConfig.context_slots));
    setPlaybookJsonDraft(stringifyJson(playbookBlueprint));
    setDefaultStatusesDraft(arrayToLines(statusMachine.default_statuses));
  }, [profile]);

  const saveSkill = async () => {
    if (!selectedSkill) {
      return;
    }
    setErrorMessage(undefined);
    try {
      await onUpdateSkill(selectedSkill.id, {
        description: skillDescriptionDraft,
        strategy: parseJsonDraft("skill.strategy", skillStrategyDraft),
        executionHints: parseJsonDraft("skill.executionHints", skillExecutionHintsDraft),
        skillMetadata: parseJsonDraft("skill.metadata", skillMetadataDraft),
      });
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : copy("Failed to save skill.", "保存 skill 失败。"));
    }
  };

  const saveArtifact = async () => {
    if (!selectedArtifact) {
      return;
    }
    setErrorMessage(undefined);
    try {
      await onUpdateArtifact(selectedArtifact.id, {
        summary: artifactSummaryDraft,
        status: artifactStatusDraft,
        artifactBody: parseJsonDraft("artifact.body", artifactBodyDraft),
        artifactMetadata: parseJsonDraft("artifact.metadata", artifactMetadataDraft),
      });
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : copy("Failed to update artifact.", "更新演进产物失败。"));
    }
  };

  const saveMemory = async () => {
    if (!selectedMemoryRecord) {
      return;
    }
    setErrorMessage(undefined);
    const payload = {
      summary: memorySummaryDraft,
      rawContent: parseJsonDraft("memory.raw", memoryRawDraft),
      content: parseJsonDraft("memory.compact", memoryCompactDraft),
      disclosure: {
        preview: memoryDisclosurePreviewDraft,
        operatorSummary: memoryDisclosureOperatorDraft,
        modelContext: memoryDisclosureModelDraft,
        tiers: selectedMemoryRecord.record.disclosure.tiers,
      },
    };
    try {
      if (selectedMemoryRecord.kind === "candidate") {
        await onUpdatePersonMemory(selectedMemoryRecord.record.personId, payload);
      } else if (selectedMemoryRecord.kind === "job") {
        await onUpdateJobMemory(selectedMemoryRecord.record.jobDescriptionId, payload);
      } else {
        await onUpdateGlobalMemory(payload);
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : copy("Failed to save memory.", "保存 memory 失败。"));
    }
  };

  const compactMemory = async () => {
    if (!selectedMemoryRecord) {
      return;
    }
    if (selectedMemoryRecord.kind === "candidate") {
      await onCompactPersonMemory(selectedMemoryRecord.record.personId);
    } else if (selectedMemoryRecord.kind === "job") {
      await onCompactJobMemory(selectedMemoryRecord.record.jobDescriptionId);
    } else {
      await onCompactGlobalMemory();
    }
  };

  const savePolicy = async () => {
    if (!selectedPolicyKey || !profile) {
      return;
    }
    setErrorMessage(undefined);
    const key = selectedPolicyKey === "candidate" ? "candidate_memory" : selectedPolicyKey === "job" ? "job_memory" : "agent_global_memory";
    const current = (profile.memoryPolicy ?? {}) as Record<string, unknown>;
    try {
      await onSaveProfile({
        memoryPolicy: {
          ...current,
          [key]: {
            ...((current[key] ?? {}) as Record<string, unknown>),
            compact_threshold: compactNumber(policyThresholdDraft, 1_000_000),
            auto_compact: policyAutoCompact,
            disclosure: linesToArray(policyDisclosureDraft),
          },
        },
      });
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : copy("Failed to save memory policy.", "保存 memory 策略失败。"));
    }
  };

  const savePrompts = async () => {
    if (!profile) {
      return;
    }
    setErrorMessage(undefined);
    try {
      await onSaveProfile({
        roleDefinition: {
          ...((profile.roleDefinition ?? {}) as Record<string, unknown>),
          identity: identityDraft,
          positioning: positioningDraft,
          tone: toneDraft,
          duties: linesToArray(dutiesDraft),
          boundaries: linesToArray(boundariesDraft),
        },
        promptConfig: {
          ...((profile.promptConfig ?? {}) as Record<string, unknown>),
          system_prompt: systemPromptDraft,
          context_slots: linesToArray(contextSlotsDraft),
        },
      });
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : copy("Failed to save prompts.", "保存提示词失败。"));
    }
  };

  const savePlaybook = async () => {
    if (!profile) {
      return;
    }
    setErrorMessage(undefined);
    try {
      const playbookBlueprint = parseJsonDraft("playbookBlueprint", playbookJsonDraft);
      await onSaveProfile({
        playbookBlueprint: {
          ...playbookBlueprint,
          status_machine: {
            ...((playbookBlueprint.status_machine ?? {}) as Record<string, unknown>),
            default_statuses: linesToArray(defaultStatusesDraft),
          },
        },
      });
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : copy("Failed to save workflow blueprint.", "保存工作流蓝图失败。"));
    }
  };

  const sectionMeta: Record<EvolutionSection, { title: string; description: string }> = {
    inbox: {
      title: copy("Review queue", "审查队列"),
      description: copy("Open items that need a decision, a clarification, or a route to another surface.", "需要决策、补充说明或转交到其他页面的事项。"),
    },
    skills: {
      title: copy("Skill rules", "Skill 规则"),
      description: copy("Manage skill contracts, metadata, and health drift.", "管理 skill 契约、元数据和健康漂移。"),
    },
    memory: {
      title: copy("Memory scopes", "记忆范围"),
      description: copy("Manage scoped memory rules without mixing candidate or JD context.", "管理分域记忆规则，不混入候选人或 JD 上下文。"),
    },
    prompts: {
      title: copy("Prompt brief", "提示词简报"),
      description: copy("Maintain the role, tone, boundaries, and prompt slots visible to operators.", "维护对操作员可见的角色、口吻、边界和提示词槽位。"),
    },
    playbook: {
      title: copy("Workflow blueprint", "工作流蓝图"),
      description: copy("Edit the recruiting routing, status machine, and round templates.", "编辑招聘路由、状态机和多轮模板。"),
    },
    approvals: {
      title: copy("Policy exceptions", "策略例外"),
      description: copy("Central review queue for non-candidate decisions and exceptions.", "面向非候选人决策和例外的集中审查队列。"),
    },
    history: {
      title: copy("Review history", "审查历史"),
      description: copy("Reviewed decisions and applied or rejected strategy artifacts.", "已审查的决策以及已应用/已拒绝的策略产物。"),
    },
  };

  const renderList = () => (
    <div style={{ display: "grid", gap: "var(--space-1)", maxHeight: "70vh", overflowY: "auto" }}>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1fr) calc(var(--space-10) + var(--space-10) + var(--space-3)) calc(var(--space-10) + var(--space-10) + var(--space-2))",
          gap: "var(--space-2)",
          padding: "0 var(--space-3) var(--space-2)",
          color: theme.colors.muted,
          fontSize: "var(--font-size-xs)",
        }}
      >
        <span>{copy("Item", "项目")}</span>
        <span>{copy("Status", "状态")}</span>
        <span>{copy("Updated", "更新时间")}</span>
      </div>
      {currentRows.map((row) => (
        <button
          key={row.key}
          type="button"
          onClick={() => setSelectedKey(row.key)}
          style={{
            gridTemplateColumns: "minmax(0, 1fr) calc(var(--space-10) * 2 + var(--space-3)) calc(var(--space-10) * 2 + var(--space-2))",
            alignItems: "start",
            ...selectableRowStyle(selectedKey === row.key),
          }}
        >
          <div style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 600, fontSize: "var(--font-size-sm)", lineHeight: 1.4 }}>{row.label}</div>
            <div style={{ color: theme.colors.muted, fontSize: "var(--font-size-xs)", lineHeight: 1.5, marginTop: "var(--space-1)" }}>{row.detail}</div>
          </div>
          <div style={{ paddingTop: "calc(var(--space-1) / 2)" }}>
            <StatusBadge tone={row.tone}>{translateUiToken(row.status, copy)}</StatusBadge>
          </div>
          <div style={{ color: theme.colors.muted, fontSize: "var(--font-size-xs)", paddingTop: "var(--space-1)" }}>{formatCompactDate(row.updatedAt)}</div>
        </button>
      ))}
      {!currentRows.length ? <div style={{ color: theme.colors.muted, padding: "var(--space-3)" }}>{copy("No items.", "当前没有记录。")}</div> : null}
    </div>
  );

  const renderDetail = () => {
    if (selectedApproval) {
      return (
        <div style={{ display: "grid", gap: "var(--space-3)" }}>
          <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
            <StatusBadge tone={toneFromStatus(selectedApproval.status)}>{translateUiToken(selectedApproval.status, copy)}</StatusBadge>
            <StatusBadge tone="neutral">{selectedApproval.targetType ?? selectedApproval.kind}</StatusBadge>
          </div>
          <div style={{ lineHeight: 1.65 }}>{selectedApproval.detail}</div>
          {selectedApproval.payload ? (
            <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: "var(--font-size-xs)", lineHeight: 1.6, color: theme.colors.text }}>
              {JSON.stringify(selectedApproval.payload, null, 2)}
            </pre>
          ) : null}
          {selectedApproval.status === "pending" ? (
            <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
              <button type="button" onClick={() => void onApprove(selectedApproval.id)} disabled={pendingActionId === selectedApproval.id} style={buttonStyle}>
                {pendingActionId === selectedApproval.id ? copy("Working...", "处理中...") : copy("Approve", "批准")}
              </button>
              <button type="button" onClick={() => void onReject(selectedApproval.id)} disabled={pendingActionId === selectedApproval.id} style={dangerButtonStyle}>
                {copy("Reject", "拒绝")}
              </button>
            </div>
          ) : null}
        </div>
      );
    }

    if (selectedSkill) {
      return (
        <div style={{ display: "grid", gap: "var(--space-3)" }}>
          <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
            <StatusBadge tone={toneFromStatus(selectedSkill.health)}>{selectedSkill.health}</StatusBadge>
            <StatusBadge tone="neutral">{selectedSkill.boundStage}</StatusBadge>
            <StatusBadge tone="neutral">{selectedSkill.version}</StatusBadge>
          </div>
          <label style={{ display: "grid", gap: "var(--space-2)" }}>
            <span>{copy("Description", "说明")}</span>
            <textarea value={skillDescriptionDraft} onChange={(event) => setSkillDescriptionDraft(event.target.value)} style={textAreaStyle} />
          </label>
          <label style={{ display: "grid", gap: "var(--space-2)" }}>
            <span>{copy("Strategy JSON", "策略 JSON")}</span>
            <textarea value={skillStrategyDraft} onChange={(event) => setSkillStrategyDraft(event.target.value)} style={textAreaStyle} />
          </label>
          <label style={{ display: "grid", gap: "var(--space-2)" }}>
            <span>{copy("Execution hints JSON", "执行提示 JSON")}</span>
            <textarea value={skillExecutionHintsDraft} onChange={(event) => setSkillExecutionHintsDraft(event.target.value)} style={textAreaStyle} />
          </label>
          <label style={{ display: "grid", gap: "var(--space-2)" }}>
            <span>{copy("Metadata JSON", "元数据 JSON")}</span>
            <textarea value={skillMetadataDraft} onChange={(event) => setSkillMetadataDraft(event.target.value)} style={textAreaStyle} />
          </label>
          <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
            <button type="button" onClick={() => void saveSkill()} style={buttonStyle}>{copy("Save skill", "保存 skill")}</button>
            <button type="button" onClick={() => void onDeleteSkill(selectedSkill.id)} style={dangerButtonStyle}>{copy("Delete", "删除")}</button>
          </div>
        </div>
      );
    }

    if (selectedMemoryRecord) {
      return (
        <div style={{ display: "grid", gap: "var(--space-3)" }}>
          <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
            <StatusBadge tone="neutral">{selectedMemoryRecord.record.memorySchemaVersion}</StatusBadge>
            <StatusBadge tone="neutral">{copy(`tokens ${selectedMemoryRecord.record.tokenEstimate}`, `tokens ${selectedMemoryRecord.record.tokenEstimate}`)}</StatusBadge>
            {selectedMemoryRecord.record.compactedAt ? <StatusBadge tone="warning">{copy(`last compact ${formatCompactDate(selectedMemoryRecord.record.compactedAt)}`, `最近 compact 于 ${formatCompactDate(selectedMemoryRecord.record.compactedAt)}`)}</StatusBadge> : null}
          </div>
          <label style={{ display: "grid", gap: "var(--space-2)" }}>
            <span>{copy("Summary", "摘要")}</span>
            <textarea value={memorySummaryDraft} onChange={(event) => setMemorySummaryDraft(event.target.value)} style={textAreaStyle} />
          </label>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: "var(--space-3)" }}>
            <label style={{ display: "grid", gap: "var(--space-2)" }}>
              <span>{copy("Preview", "预览层")}</span>
              <input value={memoryDisclosurePreviewDraft} onChange={(event) => setMemoryDisclosurePreviewDraft(event.target.value)} style={inputStyle} />
            </label>
            <label style={{ display: "grid", gap: "var(--space-2)" }}>
              <span>{copy("Operator", "操作员层")}</span>
              <input value={memoryDisclosureOperatorDraft} onChange={(event) => setMemoryDisclosureOperatorDraft(event.target.value)} style={inputStyle} />
            </label>
            <label style={{ display: "grid", gap: "var(--space-2)" }}>
              <span>{copy("Model", "模型层")}</span>
              <input value={memoryDisclosureModelDraft} onChange={(event) => setMemoryDisclosureModelDraft(event.target.value)} style={inputStyle} />
            </label>
          </div>
          <label style={{ display: "grid", gap: "var(--space-2)" }}>
            <span>{copy("Raw JSON", "原始 JSON")}</span>
            <textarea value={memoryRawDraft} onChange={(event) => setMemoryRawDraft(event.target.value)} style={{ ...textAreaStyle, minHeight: "calc(var(--space-12) + var(--space-12) + var(--space-10) + var(--space-3))" }} />
          </label>
          <label style={{ display: "grid", gap: "var(--space-2)" }}>
            <span>{copy("Compacted JSON", "压缩后 JSON")}</span>
            <textarea value={memoryCompactDraft} onChange={(event) => setMemoryCompactDraft(event.target.value)} style={{ ...textAreaStyle, minHeight: "calc(var(--space-12) + var(--space-12) + var(--space-10) + var(--space-3))" }} />
          </label>
          <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
            <button type="button" onClick={() => void saveMemory()} style={buttonStyle}>{copy("Save memory", "保存 memory")}</button>
            <button type="button" onClick={() => void compactMemory()} style={buttonStyle}>{copy("Compact now", "立即 compact")}</button>
          </div>
        </div>
      );
    }

    if (selectedPolicyKey && profile) {
      return (
        <div style={{ display: "grid", gap: "var(--space-3)" }}>
          <label style={{ display: "grid", gap: "var(--space-2)" }}>
            <span>{copy("Compact threshold", "压缩阈值")}</span>
            <input value={policyThresholdDraft} onChange={(event) => setPolicyThresholdDraft(event.target.value)} style={inputStyle} />
          </label>
          <label style={{ display: "flex", gap: "var(--space-2)", alignItems: "center" }}>
            <input type="checkbox" checked={policyAutoCompact} onChange={(event) => setPolicyAutoCompact(event.target.checked)} />
            <span>{copy("Auto compact", "自动 compact")}</span>
          </label>
          <label style={{ display: "grid", gap: "var(--space-2)" }}>
            <span>{copy("Disclosure tiers", "披露层级")}</span>
            <textarea value={policyDisclosureDraft} onChange={(event) => setPolicyDisclosureDraft(event.target.value)} style={textAreaStyle} />
          </label>
          <button type="button" onClick={() => void savePolicy()} style={buttonStyle}>{copy("Save policy", "保存策略")}</button>
        </div>
      );
    }

    if (selectedArtifact) {
      return (
        <div style={{ display: "grid", gap: "var(--space-3)" }}>
          <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
            <StatusBadge tone={toneFromStatus(selectedArtifact.status)}>{translateUiToken(selectedArtifact.status, copy)}</StatusBadge>
            <StatusBadge tone="neutral">{selectedArtifact.artifactKind}</StatusBadge>
            {selectedArtifact.relatedCandidateId ? <StatusBadge tone="warning">{applicationDisplayNameById.get(selectedArtifact.relatedCandidateId) ?? selectedArtifact.relatedCandidateId}</StatusBadge> : null}
          </div>
          <label style={{ display: "grid", gap: "var(--space-2)" }}>
            <span>{copy("Summary", "摘要")}</span>
            <textarea value={artifactSummaryDraft} onChange={(event) => setArtifactSummaryDraft(event.target.value)} style={textAreaStyle} />
          </label>
          <label style={{ display: "grid", gap: "var(--space-2)" }}>
            <span>{copy("Status", "状态")}</span>
            <select value={artifactStatusDraft} onChange={(event) => setArtifactStatusDraft(event.target.value as EvolutionArtifactRecord["status"])} style={inputStyle}>
              <option value="draft">{copy("Draft", "草稿")}</option>
              <option value="pending_review">{copy("Pending review", "待审查")}</option>
              <option value="approved">{copy("Approved", "已批准")}</option>
              <option value="applied">{copy("Applied", "已应用")}</option>
              <option value="rejected">{copy("Rejected", "已拒绝")}</option>
            </select>
          </label>
          <label style={{ display: "grid", gap: "var(--space-2)" }}>
            <span>{copy("Artifact body JSON", "产物内容 JSON")}</span>
            <textarea value={artifactBodyDraft} onChange={(event) => setArtifactBodyDraft(event.target.value)} style={{ ...textAreaStyle, minHeight: "calc(var(--space-12) + var(--space-12) + var(--space-12) + var(--space-10) + var(--space-3))" }} />
          </label>
          <label style={{ display: "grid", gap: "var(--space-2)" }}>
            <span>{copy("Artifact metadata JSON", "产物元数据 JSON")}</span>
            <textarea value={artifactMetadataDraft} onChange={(event) => setArtifactMetadataDraft(event.target.value)} style={{ ...textAreaStyle, minHeight: "calc(var(--space-12) + var(--space-12) + var(--space-6))" }} />
          </label>
          <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
            <button type="button" onClick={() => void saveArtifact()} style={buttonStyle}>{copy("Save artifact", "保存产物")}</button>
            {selectedArtifact.relatedCandidateId ? (
              <button type="button" onClick={() => onOpenApplication(selectedArtifact.relatedCandidateId!)} style={buttonStyle}>
                {copy("Open candidate", "打开候选人")}
              </button>
            ) : null}
          </div>
        </div>
      );
    }

    if (section === "prompts" && profile) {
      return (
        <div style={{ display: "grid", gap: "var(--space-3)" }}>
          <label style={{ display: "grid", gap: "var(--space-2)" }}>
            <span>{copy("Identity", "身份")}</span>
            <input value={identityDraft} onChange={(event) => setIdentityDraft(event.target.value)} style={inputStyle} />
          </label>
          <label style={{ display: "grid", gap: "var(--space-2)" }}>
            <span>{copy("Positioning", "定位")}</span>
            <textarea value={positioningDraft} onChange={(event) => setPositioningDraft(event.target.value)} style={textAreaStyle} />
          </label>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "var(--space-3)" }}>
            <label style={{ display: "grid", gap: "var(--space-2)" }}>
              <span>{copy("Tone", "口吻")}</span>
              <input value={toneDraft} onChange={(event) => setToneDraft(event.target.value)} style={inputStyle} />
            </label>
            <label style={{ display: "grid", gap: "var(--space-2)" }}>
              <span>{copy("Context slots", "上下文槽位")}</span>
              <textarea value={contextSlotsDraft} onChange={(event) => setContextSlotsDraft(event.target.value)} style={textAreaStyle} />
            </label>
          </div>
          <label style={{ display: "grid", gap: "var(--space-2)" }}>
            <span>{copy("Duties", "职责")}</span>
            <textarea value={dutiesDraft} onChange={(event) => setDutiesDraft(event.target.value)} style={textAreaStyle} />
          </label>
          <label style={{ display: "grid", gap: "var(--space-2)" }}>
            <span>{copy("Boundaries", "边界")}</span>
            <textarea value={boundariesDraft} onChange={(event) => setBoundariesDraft(event.target.value)} style={textAreaStyle} />
          </label>
          <label style={{ display: "grid", gap: "var(--space-2)" }}>
            <span>{copy("System prompt", "系统提示词")}</span>
            <textarea value={systemPromptDraft} onChange={(event) => setSystemPromptDraft(event.target.value)} style={{ ...textAreaStyle, minHeight: "calc(var(--space-12) + var(--space-12) + var(--space-12) + var(--space-4))" }} />
          </label>
          <button type="button" onClick={() => void savePrompts()} style={buttonStyle}>{copy("Save prompts", "保存提示词")}</button>
        </div>
      );
    }

    if (section === "playbook" && profile) {
      return (
        <div style={{ display: "grid", gap: "var(--space-3)" }}>
          <label style={{ display: "grid", gap: "var(--space-2)" }}>
            <span>{copy("Default statuses", "默认状态")}</span>
            <textarea value={defaultStatusesDraft} onChange={(event) => setDefaultStatusesDraft(event.target.value)} style={textAreaStyle} />
          </label>
          <label style={{ display: "grid", gap: "var(--space-2)" }}>
            <span>{copy("Execution blueprint JSON", "执行蓝图 JSON")}</span>
            <textarea value={playbookJsonDraft} onChange={(event) => setPlaybookJsonDraft(event.target.value)} style={{ ...textAreaStyle, minHeight: "calc(var(--space-12) * 3 + var(--space-10) + var(--space-10) + var(--space-5) + var(--space-4))" }} />
          </label>
          <button type="button" onClick={() => void savePlaybook()} style={buttonStyle}>{copy("Save workflow blueprint", "保存工作流蓝图")}</button>
        </div>
      );
    }

    return <div style={{ color: theme.colors.muted }}>{copy("Select an item to inspect or edit it.", "请选择一项进行查看或编辑。")}</div>;
  };

  return (
    <div style={{ display: "grid", gap: "var(--space-5)", minWidth: 0, background: theme.colors.background, padding: "var(--space-5)", borderRadius: theme.radius.xl }}>
      <Panel
        title={copy("AI Review Center", "AI 审查中心")}
        eyebrow={copy("Strategy controls", "策略控制")}
        description={copy("Review skills, memory, prompts, and workflow blueprints as curated strategy assets.", "把 skills、memory、提示词和工作流蓝图当作可审查的策略资产来管理。")}
      >
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: "var(--space-3)" }}>
          {reviewMetrics.map((metric) => (
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
        gridTemplateColumns: "calc(var(--layout-left-list-width) - var(--space-10)) minmax(0, 1fr) var(--layout-right-panel-width)",
        gap: "var(--space-4)",
        minWidth: 0,
      }}
    >
      <Panel dense title={copy("Review map", "审查地图")} eyebrow={copy("Registry", "注册表")} description={copy("Choose the review surface you want to adjust.", "选择你要调整的审查面。")}>
        <div style={{ display: "grid", gap: "var(--space-2)" }}>
          {([
            ["inbox", inboxRows.length],
            ["skills", skillRows.length],
            ["memory", memoryRows.length],
            ["prompts", promptRows.length],
            ["playbook", playbookRows.length],
            ["approvals", approvalRows.filter((item) => item.status === "pending").length],
            ["history", historyRows.length],
          ] as Array<[EvolutionSection, number]>).map(([key, count]) => (
            <button
              key={key}
              type="button"
              onClick={() => setSection(key)}
              style={{
                gridTemplateColumns: "1fr auto",
                alignItems: "center",
                ...selectableRowStyle(section === key),
              }}
            >
              <span style={{ fontWeight: 600 }}>{sectionMeta[key].title}</span>
              <StatusBadge tone={count ? "warning" : "neutral"}>{count}</StatusBadge>
            </button>
          ))}
        </div>
      </Panel>

      <Panel dense title={sectionMeta[section].title} eyebrow={copy("Registry", "注册表")} description={sectionMeta[section].description}>
        {errorMessage ? (
          <div
            style={{
              marginBottom: "var(--space-3)",
              borderRadius: theme.radius.lg,
              border: `1px solid ${theme.colors.critical}`,
              background: "var(--danger-soft)",
              color: theme.colors.critical,
              padding: "var(--space-2) var(--space-3)",
              fontSize: "var(--font-size-xs)",
            }}
          >
            {errorMessage}
          </div>
        ) : null}
        {renderList()}
      </Panel>

      <Panel dense title={copy("Detail editor", "详情编辑")} eyebrow={copy("Editor", "编辑区")} description={copy("Inspect and modify the selected review item, policy exception, or history item.", "查看并修改当前选中的审查项、策略例外或历史记录。")}>
        {renderDetail()}
      </Panel>
      </div>
    </div>
  );
}
