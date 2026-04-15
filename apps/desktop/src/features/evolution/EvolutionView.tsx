import React, { useEffect, useMemo, useState } from "react";
import { Panel, StatusBadge } from "../../components";
import { formatCompactDate } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { theme } from "../../lib/theme";
import { translateUiToken } from "../../lib/uiText";
import type {
  AgentGlobalMemoryRecord,
  ApprovalItem,
  CandidateMemoryRecord,
  CandidateRecord,
  EvolutionArtifactRecord,
  JobMemoryRecord,
  RecruitAgentProfileRecord,
  SkillRecord,
} from "../../lib/types";

type EvolutionSection = "inbox" | "skills" | "memory" | "prompts" | "playbook" | "approvals" | "history";

interface EvolutionViewProps {
  profile: RecruitAgentProfileRecord | null;
  candidates: CandidateRecord[];
  approvals: ApprovalItem[];
  skills: SkillRecord[];
  artifacts: EvolutionArtifactRecord[];
  candidateMemories: CandidateMemoryRecord[];
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
  onUpdateCandidateMemory(candidateId: string, payload: Partial<CandidateMemoryRecord>): Promise<void> | void;
  onCompactCandidateMemory(candidateId: string): Promise<void> | void;
  onUpdateJobMemory(jdId: string, payload: Partial<JobMemoryRecord>): Promise<void> | void;
  onCompactJobMemory(jdId: string): Promise<void> | void;
  onUpdateGlobalMemory(payload: Partial<AgentGlobalMemoryRecord>): Promise<void> | void;
  onCompactGlobalMemory(): Promise<void> | void;
  onUpdateArtifact(artifactId: string, payload: Partial<EvolutionArtifactRecord>): Promise<void> | void;
  onOpenCandidate(candidateId: string): void;
}

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
  borderRadius: "10px",
  border: `1px solid ${theme.colors.border}`,
  background: "rgba(7,12,22,0.92)",
  color: theme.colors.text,
  padding: "9px 10px",
  fontSize: "13px",
};

const textAreaStyle: React.CSSProperties = {
  ...inputStyle,
  minHeight: "108px",
  lineHeight: 1.6,
  resize: "vertical",
};

const buttonStyle: React.CSSProperties = {
  border: `1px solid ${theme.colors.border}`,
  borderRadius: "10px",
  background: "rgba(255,255,255,0.04)",
  color: theme.colors.text,
  padding: "8px 10px",
  cursor: "pointer",
  fontWeight: 700,
};

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
  candidates,
  approvals,
  skills,
  artifacts,
  candidateMemories,
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
  onUpdateCandidateMemory,
  onCompactCandidateMemory,
  onUpdateJobMemory,
  onCompactJobMemory,
  onUpdateGlobalMemory,
  onCompactGlobalMemory,
  onUpdateArtifact,
  onOpenCandidate,
}: EvolutionViewProps): JSX.Element {
  const { copy } = useI18n();
  const [section, setSection] = useState<EvolutionSection>("inbox");
  const [selectedKey, setSelectedKey] = useState<SelectionKey>();
  const [errorMessage, setErrorMessage] = useState<string>();

  const candidateNameById = useMemo(() => new Map(candidates.map((candidate) => [candidate.id, candidate.name])), [candidates]);
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
      ...candidateMemories.map((memory) => ({
        key: `memory:candidate:${memory.candidateId}`,
        label: candidateNameById.get(memory.candidateId) ?? memory.candidateId,
        detail: memory.summary ?? copy("Candidate-isolated memory", "候选人隔离记忆"),
        status: memory.status,
        updatedAt: memory.updatedAt,
        tone: toneFromStatus(memory.status),
      })),
      ...jobMemories.map((memory) => ({
        key: `memory:job:${memory.jdId}`,
        label: memory.jdId,
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
    [candidateMemories, candidateNameById, copy, globalMemory, jobMemories, profile],
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
        label: copy("Current playbook", "当前执行编排"),
        detail: copy("Default recruiting playbook and status machine.", "默认招聘执行编排与状态机。"),
        status: profile?.status ?? "draft",
        updatedAt: profile?.updatedAt ?? new Date().toISOString(),
        tone: toneFromStatus(profile?.status ?? "draft"),
      },
      ...artifacts
        .filter((item) => /(playbook_patch|workflow_patch)/i.test(item.artifactKind))
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
      const record = candidateMemories.find((item) => item.candidateId === target);
      return record ? { kind: "candidate" as const, record } : null;
    }
    const record = jobMemories.find((item) => item.jdId === target);
    return record ? { kind: "job" as const, record } : null;
  }, [candidateMemories, globalMemory, jobMemories, selectedKey]);

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

  const [workflowJsonDraft, setWorkflowJsonDraft] = useState("{}");
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
    const workflowDefinition = (profile.workflowDefinition ?? {}) as Record<string, unknown>;
    const statusMachine = (workflowDefinition.status_machine ?? {}) as Record<string, unknown>;
    setIdentityDraft(String(roleDefinition.identity ?? ""));
    setPositioningDraft(String(roleDefinition.positioning ?? ""));
    setToneDraft(String(roleDefinition.tone ?? ""));
    setDutiesDraft(arrayToLines(roleDefinition.duties));
    setBoundariesDraft(arrayToLines(roleDefinition.boundaries));
    setSystemPromptDraft(String(promptConfig.system_prompt ?? ""));
    setContextSlotsDraft(arrayToLines(promptConfig.context_slots));
    setWorkflowJsonDraft(stringifyJson(workflowDefinition));
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
        await onUpdateCandidateMemory(selectedMemoryRecord.record.candidateId, payload);
      } else if (selectedMemoryRecord.kind === "job") {
        await onUpdateJobMemory(selectedMemoryRecord.record.jdId, payload);
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
      await onCompactCandidateMemory(selectedMemoryRecord.record.candidateId);
    } else if (selectedMemoryRecord.kind === "job") {
      await onCompactJobMemory(selectedMemoryRecord.record.jdId);
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
      const workflowDefinition = parseJsonDraft("workflowDefinition", workflowJsonDraft);
      await onSaveProfile({
        workflowDefinition: {
          ...workflowDefinition,
          status_machine: {
            ...((workflowDefinition.status_machine ?? {}) as Record<string, unknown>),
            default_statuses: linesToArray(defaultStatusesDraft),
          },
        },
      });
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : copy("Failed to save playbook.", "保存执行编排失败。"));
    }
  };

  const sectionMeta: Record<EvolutionSection, { title: string; description: string }> = {
    inbox: {
      title: copy("Inbox", "收件箱"),
      description: copy("Pending approvals and evolution drafts that need immediate review.", "需要立即审查的待批事项和演进草稿。"),
    },
    skills: {
      title: copy("Skills", "Skills"),
      description: copy("Manage structured skill contracts, metadata, and health drift.", "管理结构化 skill 契约、元数据和健康漂移。"),
    },
    memory: {
      title: copy("Memory", "Memory"),
      description: copy("Manage memory policies and isolated memory layers without mixing candidate or JD scopes.", "统一管理记忆策略和隔离记忆层，不串候选人或 JD。"),
    },
    prompts: {
      title: copy("Prompts", "提示词"),
      description: copy("Maintain operator-visible role, tone, boundaries, and prompt slots.", "维护对用户可见的角色、口吻、边界和提示词槽位。"),
    },
    playbook: {
      title: copy("Playbooks", "执行编排"),
      description: copy("Edit the recruiting playbook, status machine, and round templates.", "编辑招聘执行编排、状态机和多轮模板。"),
    },
    approvals: {
      title: copy("Approvals", "审批"),
      description: copy("Central review queue for non-candidate approvals.", "面向非候选人事项的集中审批队列。"),
    },
    history: {
      title: copy("History", "历史"),
      description: copy("Reviewed approvals and applied or rejected evolution artifacts.", "已审查审批以及已应用/已拒绝的演进产物历史。"),
    },
  };

  const renderList = () => (
    <div style={{ display: "grid", gap: "4px", maxHeight: "70vh", overflowY: "auto" }}>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 92px 88px", gap: "8px", padding: "0 10px 6px", color: theme.colors.muted, fontSize: "12px" }}>
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
            display: "grid",
            gridTemplateColumns: "minmax(0, 1fr) 92px 88px",
            gap: "8px",
            alignItems: "start",
            textAlign: "left",
            padding: "9px 10px",
            borderRadius: "10px",
            border: `1px solid ${selectedKey === row.key ? "rgba(122,167,255,0.34)" : theme.colors.border}`,
            background: selectedKey === row.key ? "rgba(122,167,255,0.10)" : "rgba(255,255,255,0.02)",
            color: theme.colors.text,
            cursor: "pointer",
          }}
        >
          <div style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 700, fontSize: "13px", lineHeight: 1.4 }}>{row.label}</div>
            <div style={{ color: theme.colors.muted, fontSize: "12px", lineHeight: 1.5, marginTop: "3px" }}>{row.detail}</div>
          </div>
          <div style={{ paddingTop: "2px" }}>
            <StatusBadge tone={row.tone}>{translateUiToken(row.status, copy)}</StatusBadge>
          </div>
          <div style={{ color: theme.colors.muted, fontSize: "11px", paddingTop: "4px" }}>{formatCompactDate(row.updatedAt)}</div>
        </button>
      ))}
      {!currentRows.length ? <div style={{ color: theme.colors.muted, padding: "10px" }}>{copy("No items.", "当前没有记录。")}</div> : null}
    </div>
  );

  const renderDetail = () => {
    if (selectedApproval) {
      return (
        <div style={{ display: "grid", gap: "12px" }}>
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
            <StatusBadge tone={toneFromStatus(selectedApproval.status)}>{translateUiToken(selectedApproval.status, copy)}</StatusBadge>
            <StatusBadge tone="neutral">{selectedApproval.targetType ?? selectedApproval.kind}</StatusBadge>
          </div>
          <div style={{ lineHeight: 1.65 }}>{selectedApproval.detail}</div>
          {selectedApproval.payload ? (
            <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: "12px", lineHeight: 1.6, color: "rgba(233,239,255,0.78)" }}>
              {JSON.stringify(selectedApproval.payload, null, 2)}
            </pre>
          ) : null}
          {selectedApproval.status === "pending" ? (
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              <button type="button" onClick={() => void onApprove(selectedApproval.id)} disabled={pendingActionId === selectedApproval.id} style={buttonStyle}>
                {pendingActionId === selectedApproval.id ? copy("Working...", "处理中...") : copy("Approve", "批准")}
              </button>
              <button type="button" onClick={() => void onReject(selectedApproval.id)} disabled={pendingActionId === selectedApproval.id} style={{ ...buttonStyle, background: "rgba(255,122,122,0.10)", color: "#ffdede" }}>
                {copy("Reject", "拒绝")}
              </button>
            </div>
          ) : null}
        </div>
      );
    }

    if (selectedSkill) {
      return (
        <div style={{ display: "grid", gap: "12px" }}>
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
            <StatusBadge tone={toneFromStatus(selectedSkill.health)}>{selectedSkill.health}</StatusBadge>
            <StatusBadge tone="neutral">{selectedSkill.boundStage}</StatusBadge>
            <StatusBadge tone="neutral">{selectedSkill.version}</StatusBadge>
          </div>
          <label style={{ display: "grid", gap: "6px" }}>
            <span>{copy("Description", "说明")}</span>
            <textarea value={skillDescriptionDraft} onChange={(event) => setSkillDescriptionDraft(event.target.value)} style={textAreaStyle} />
          </label>
          <label style={{ display: "grid", gap: "6px" }}>
            <span>{copy("Strategy JSON", "策略 JSON")}</span>
            <textarea value={skillStrategyDraft} onChange={(event) => setSkillStrategyDraft(event.target.value)} style={textAreaStyle} />
          </label>
          <label style={{ display: "grid", gap: "6px" }}>
            <span>{copy("Execution hints JSON", "执行提示 JSON")}</span>
            <textarea value={skillExecutionHintsDraft} onChange={(event) => setSkillExecutionHintsDraft(event.target.value)} style={textAreaStyle} />
          </label>
          <label style={{ display: "grid", gap: "6px" }}>
            <span>{copy("Metadata JSON", "元数据 JSON")}</span>
            <textarea value={skillMetadataDraft} onChange={(event) => setSkillMetadataDraft(event.target.value)} style={textAreaStyle} />
          </label>
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
            <button type="button" onClick={() => void saveSkill()} style={buttonStyle}>{copy("Save skill", "保存 skill")}</button>
            <button type="button" onClick={() => void onDeleteSkill(selectedSkill.id)} style={{ ...buttonStyle, background: "rgba(255,122,122,0.10)", color: "#ffdede" }}>{copy("Delete", "删除")}</button>
          </div>
        </div>
      );
    }

    if (selectedMemoryRecord) {
      return (
        <div style={{ display: "grid", gap: "12px" }}>
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
            <StatusBadge tone="neutral">{selectedMemoryRecord.record.memorySchemaVersion}</StatusBadge>
            <StatusBadge tone="neutral">{copy(`tokens ${selectedMemoryRecord.record.tokenEstimate}`, `tokens ${selectedMemoryRecord.record.tokenEstimate}`)}</StatusBadge>
            {selectedMemoryRecord.record.compactedAt ? <StatusBadge tone="warning">{copy(`last compact ${formatCompactDate(selectedMemoryRecord.record.compactedAt)}`, `最近 compact 于 ${formatCompactDate(selectedMemoryRecord.record.compactedAt)}`)}</StatusBadge> : null}
          </div>
          <label style={{ display: "grid", gap: "6px" }}>
            <span>{copy("Summary", "摘要")}</span>
            <textarea value={memorySummaryDraft} onChange={(event) => setMemorySummaryDraft(event.target.value)} style={textAreaStyle} />
          </label>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: "10px" }}>
            <label style={{ display: "grid", gap: "6px" }}>
              <span>{copy("Preview", "预览层")}</span>
              <input value={memoryDisclosurePreviewDraft} onChange={(event) => setMemoryDisclosurePreviewDraft(event.target.value)} style={inputStyle} />
            </label>
            <label style={{ display: "grid", gap: "6px" }}>
              <span>{copy("Operator", "操作员层")}</span>
              <input value={memoryDisclosureOperatorDraft} onChange={(event) => setMemoryDisclosureOperatorDraft(event.target.value)} style={inputStyle} />
            </label>
            <label style={{ display: "grid", gap: "6px" }}>
              <span>{copy("Model", "模型层")}</span>
              <input value={memoryDisclosureModelDraft} onChange={(event) => setMemoryDisclosureModelDraft(event.target.value)} style={inputStyle} />
            </label>
          </div>
          <label style={{ display: "grid", gap: "6px" }}>
            <span>{copy("Raw JSON", "原始 JSON")}</span>
            <textarea value={memoryRawDraft} onChange={(event) => setMemoryRawDraft(event.target.value)} style={{ ...textAreaStyle, minHeight: "140px" }} />
          </label>
          <label style={{ display: "grid", gap: "6px" }}>
            <span>{copy("Compacted JSON", "压缩后 JSON")}</span>
            <textarea value={memoryCompactDraft} onChange={(event) => setMemoryCompactDraft(event.target.value)} style={{ ...textAreaStyle, minHeight: "140px" }} />
          </label>
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
            <button type="button" onClick={() => void saveMemory()} style={buttonStyle}>{copy("Save memory", "保存 memory")}</button>
            <button type="button" onClick={() => void compactMemory()} style={buttonStyle}>{copy("Compact now", "立即 compact")}</button>
          </div>
        </div>
      );
    }

    if (selectedPolicyKey && profile) {
      return (
        <div style={{ display: "grid", gap: "12px" }}>
          <label style={{ display: "grid", gap: "6px" }}>
            <span>{copy("Compact threshold", "压缩阈值")}</span>
            <input value={policyThresholdDraft} onChange={(event) => setPolicyThresholdDraft(event.target.value)} style={inputStyle} />
          </label>
          <label style={{ display: "flex", gap: "8px", alignItems: "center" }}>
            <input type="checkbox" checked={policyAutoCompact} onChange={(event) => setPolicyAutoCompact(event.target.checked)} />
            <span>{copy("Auto compact", "自动 compact")}</span>
          </label>
          <label style={{ display: "grid", gap: "6px" }}>
            <span>{copy("Disclosure tiers", "披露层级")}</span>
            <textarea value={policyDisclosureDraft} onChange={(event) => setPolicyDisclosureDraft(event.target.value)} style={textAreaStyle} />
          </label>
          <button type="button" onClick={() => void savePolicy()} style={buttonStyle}>{copy("Save policy", "保存策略")}</button>
        </div>
      );
    }

    if (selectedArtifact) {
      return (
        <div style={{ display: "grid", gap: "12px" }}>
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
            <StatusBadge tone={toneFromStatus(selectedArtifact.status)}>{translateUiToken(selectedArtifact.status, copy)}</StatusBadge>
            <StatusBadge tone="neutral">{selectedArtifact.artifactKind}</StatusBadge>
            {selectedArtifact.relatedCandidateId ? <StatusBadge tone="warning">{candidateNameById.get(selectedArtifact.relatedCandidateId) ?? selectedArtifact.relatedCandidateId}</StatusBadge> : null}
          </div>
          <label style={{ display: "grid", gap: "6px" }}>
            <span>{copy("Summary", "摘要")}</span>
            <textarea value={artifactSummaryDraft} onChange={(event) => setArtifactSummaryDraft(event.target.value)} style={textAreaStyle} />
          </label>
          <label style={{ display: "grid", gap: "6px" }}>
            <span>{copy("Status", "状态")}</span>
            <select value={artifactStatusDraft} onChange={(event) => setArtifactStatusDraft(event.target.value as EvolutionArtifactRecord["status"])} style={inputStyle}>
              <option value="draft">{copy("Draft", "草稿")}</option>
              <option value="pending_review">{copy("Pending review", "待审查")}</option>
              <option value="approved">{copy("Approved", "已批准")}</option>
              <option value="applied">{copy("Applied", "已应用")}</option>
              <option value="rejected">{copy("Rejected", "已拒绝")}</option>
            </select>
          </label>
          <label style={{ display: "grid", gap: "6px" }}>
            <span>{copy("Artifact body JSON", "产物内容 JSON")}</span>
            <textarea value={artifactBodyDraft} onChange={(event) => setArtifactBodyDraft(event.target.value)} style={{ ...textAreaStyle, minHeight: "180px" }} />
          </label>
          <label style={{ display: "grid", gap: "6px" }}>
            <span>{copy("Artifact metadata JSON", "产物元数据 JSON")}</span>
            <textarea value={artifactMetadataDraft} onChange={(event) => setArtifactMetadataDraft(event.target.value)} style={{ ...textAreaStyle, minHeight: "120px" }} />
          </label>
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
            <button type="button" onClick={() => void saveArtifact()} style={buttonStyle}>{copy("Save artifact", "保存产物")}</button>
            {selectedArtifact.relatedCandidateId ? (
              <button type="button" onClick={() => onOpenCandidate(selectedArtifact.relatedCandidateId!)} style={buttonStyle}>
                {copy("Open candidate", "打开候选人")}
              </button>
            ) : null}
          </div>
        </div>
      );
    }

    if (section === "prompts" && profile) {
      return (
        <div style={{ display: "grid", gap: "12px" }}>
          <label style={{ display: "grid", gap: "6px" }}>
            <span>{copy("Identity", "身份")}</span>
            <input value={identityDraft} onChange={(event) => setIdentityDraft(event.target.value)} style={inputStyle} />
          </label>
          <label style={{ display: "grid", gap: "6px" }}>
            <span>{copy("Positioning", "定位")}</span>
            <textarea value={positioningDraft} onChange={(event) => setPositioningDraft(event.target.value)} style={textAreaStyle} />
          </label>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "10px" }}>
            <label style={{ display: "grid", gap: "6px" }}>
              <span>{copy("Tone", "口吻")}</span>
              <input value={toneDraft} onChange={(event) => setToneDraft(event.target.value)} style={inputStyle} />
            </label>
            <label style={{ display: "grid", gap: "6px" }}>
              <span>{copy("Context slots", "上下文槽位")}</span>
              <textarea value={contextSlotsDraft} onChange={(event) => setContextSlotsDraft(event.target.value)} style={textAreaStyle} />
            </label>
          </div>
          <label style={{ display: "grid", gap: "6px" }}>
            <span>{copy("Duties", "职责")}</span>
            <textarea value={dutiesDraft} onChange={(event) => setDutiesDraft(event.target.value)} style={textAreaStyle} />
          </label>
          <label style={{ display: "grid", gap: "6px" }}>
            <span>{copy("Boundaries", "边界")}</span>
            <textarea value={boundariesDraft} onChange={(event) => setBoundariesDraft(event.target.value)} style={textAreaStyle} />
          </label>
          <label style={{ display: "grid", gap: "6px" }}>
            <span>{copy("System prompt", "系统提示词")}</span>
            <textarea value={systemPromptDraft} onChange={(event) => setSystemPromptDraft(event.target.value)} style={{ ...textAreaStyle, minHeight: "160px" }} />
          </label>
          <button type="button" onClick={() => void savePrompts()} style={buttonStyle}>{copy("Save prompts", "保存提示词")}</button>
        </div>
      );
    }

    if (section === "playbook" && profile) {
      return (
        <div style={{ display: "grid", gap: "12px" }}>
          <label style={{ display: "grid", gap: "6px" }}>
            <span>{copy("Default statuses", "默认状态")}</span>
            <textarea value={defaultStatusesDraft} onChange={(event) => setDefaultStatusesDraft(event.target.value)} style={textAreaStyle} />
          </label>
          <label style={{ display: "grid", gap: "6px" }}>
            <span>{copy("Workflow definition JSON", "工作流定义 JSON")}</span>
            <textarea value={workflowJsonDraft} onChange={(event) => setWorkflowJsonDraft(event.target.value)} style={{ ...textAreaStyle, minHeight: "260px" }} />
          </label>
          <button type="button" onClick={() => void savePlaybook()} style={buttonStyle}>{copy("Save playbook", "保存执行编排")}</button>
        </div>
      );
    }

    return <div style={{ color: theme.colors.muted }}>{copy("Select an item to inspect or edit it.", "请选择一项进行查看或编辑。")}</div>;
  };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "220px minmax(0, 1fr) 420px", gap: "16px", minWidth: 0 }}>
      <Panel dense title={copy("Evolution", "Evolution")} eyebrow={copy("Governance", "治理中心")} description={copy("A dense asset registry for skills, memory, prompts, playbooks, approvals, and history.", "一个高密度治理中心，用来管理 skills、memory、提示词、执行编排、审批和历史版本。")}>
        <div style={{ display: "grid", gap: "6px" }}>
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
                display: "grid",
                gridTemplateColumns: "1fr auto",
                alignItems: "center",
                gap: "8px",
                textAlign: "left",
                padding: "9px 10px",
                borderRadius: "10px",
                border: `1px solid ${section === key ? "rgba(122,167,255,0.34)" : theme.colors.border}`,
                background: section === key ? "rgba(122,167,255,0.10)" : "rgba(255,255,255,0.02)",
                color: theme.colors.text,
                cursor: "pointer",
              }}
            >
              <span style={{ fontWeight: 700 }}>{sectionMeta[key].title}</span>
              <StatusBadge tone={count ? "warning" : "neutral"}>{count}</StatusBadge>
            </button>
          ))}
        </div>
      </Panel>

      <Panel dense title={sectionMeta[section].title} eyebrow={copy("Registry", "注册表")} description={sectionMeta[section].description}>
        {errorMessage ? (
          <div style={{ marginBottom: "10px", borderRadius: "10px", border: "1px solid rgba(255,122,122,0.18)", background: "rgba(255,122,122,0.08)", color: "#ffdede", padding: "8px 10px", fontSize: "12px" }}>
            {errorMessage}
          </div>
        ) : null}
        {renderList()}
      </Panel>

      <Panel dense title={copy("Detail", "详情")} eyebrow={copy("Editor", "编辑区")} description={copy("Inspect and modify the currently selected asset, approval, or history item.", "查看并修改当前选中的资产、审批或历史记录。")}>
        {renderDetail()}
      </Panel>
    </div>
  );
}
