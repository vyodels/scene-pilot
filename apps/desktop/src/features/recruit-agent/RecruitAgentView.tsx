import React, { useEffect, useMemo, useState } from "react";
import type { RecruitmentStateMachine, RecruitmentStateMachineUpdatePayload } from "@scene-pilot/shared";
import { StatusBadge } from "../../components";
import { Panel, TopTabPage } from "../../components";
import { formatCompactDate } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { StateMachineEditor } from "../state-machine/StateMachineEditor";
import type {
  AgentGlobalMemoryRecord,
  ApplicationRecord,
  JobMemoryRecord,
  PersonMemoryRecord,
  RecruitAgentProfileRecord,
  SkillRecord,
} from "../../lib/types";

type RecruitAgentTab = "profile" | "blueprint" | "state-machine" | "context" | "memory" | "skills";
type MemoryTargetKey = `candidate:${string}` | `job:${string}` | "global";

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

interface RecruitAgentViewProps {
  profile: RecruitAgentProfileRecord | null;
  stateMachine: RecruitmentStateMachine | null;
  applications: ApplicationRecord[];
  skills: SkillRecord[];
  personMemories: PersonMemoryRecord[];
  jobMemories: JobMemoryRecord[];
  globalMemory: AgentGlobalMemoryRecord | null;
  onSaveProfile(payload: Partial<RecruitAgentProfileRecord>): Promise<void> | void;
  onSaveStateMachine(payload: RecruitmentStateMachineUpdatePayload): Promise<void> | void;
  onUpdateSkill(skillId: string, payload: Partial<SkillRecord>): Promise<void> | void;
  onDeleteSkill(skillId: string): Promise<void> | void;
  onUpdatePersonMemory(personId: string, payload: Partial<PersonMemoryRecord>): Promise<void> | void;
  onCompactPersonMemory(personId: string): Promise<void> | void;
  onUpdateJobMemory(jobDescriptionId: string, payload: Partial<JobMemoryRecord>): Promise<void> | void;
  onCompactJobMemory(jobDescriptionId: string): Promise<void> | void;
  onUpdateGlobalMemory(payload: Partial<AgentGlobalMemoryRecord>): Promise<void> | void;
  onCompactGlobalMemory(): Promise<void> | void;
}

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
  width: "100%",
  minHeight: "calc(var(--space-12) + var(--space-12) + var(--space-6))",
  borderRadius: theme.radius.md,
  border: `1px solid ${theme.colors.border}`,
  background: theme.colors.panel,
  color: theme.colors.text,
  padding: "var(--space-3)",
  fontSize: "var(--font-size-sm)",
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

export function RecruitAgentView({
  profile,
  stateMachine,
  applications,
  skills,
  personMemories,
  jobMemories,
  globalMemory,
  onSaveProfile,
  onSaveStateMachine,
  onUpdateSkill,
  onDeleteSkill,
  onUpdatePersonMemory,
  onCompactPersonMemory,
  onUpdateJobMemory,
  onCompactJobMemory,
  onUpdateGlobalMemory,
  onCompactGlobalMemory,
}: RecruitAgentViewProps): JSX.Element {
  const { copy } = useI18n();
  const [tab, setTab] = useState<RecruitAgentTab>("profile");
  const [errorMessage, setErrorMessage] = useState<string>();

  const [descriptionDraft, setDescriptionDraft] = useState("");
  const [identityDraft, setIdentityDraft] = useState("");
  const [positioningDraft, setPositioningDraft] = useState("");
  const [dutiesDraft, setDutiesDraft] = useState("");
  const [toneDraft, setToneDraft] = useState("");
  const [boundariesDraft, setBoundariesDraft] = useState("");
  const [successCriteriaDraft, setSuccessCriteriaDraft] = useState("");
  const [forbiddenActionsDraft, setForbiddenActionsDraft] = useState("");
  const [systemPromptDraft, setSystemPromptDraft] = useState("");
  const [contextSlotsDraft, setContextSlotsDraft] = useState("");
  const [dashboardDraft, setDashboardDraft] = useState("{}");
  const [channelDraft, setChannelDraft] = useState("{}");
  const [metadataDraft, setMetadataDraft] = useState("{}");
  const [contextTokenBudgetDraft, setContextTokenBudgetDraft] = useState("4096");
  const [contextLlmRerankEnabled, setContextLlmRerankEnabled] = useState(false);
  const [contextLlmTopKDraft, setContextLlmTopKDraft] = useState("6");
  const [contextLlmMaxBoostDraft, setContextLlmMaxBoostDraft] = useState("8");
  const [contextDropOrderDraft, setContextDropOrderDraft] = useState("");
  const [candidateMustIncludeDraft, setCandidateMustIncludeDraft] = useState("");
  const [candidateWeightsDraft, setCandidateWeightsDraft] = useState("{}");
  const [agentMustIncludeDraft, setAgentMustIncludeDraft] = useState("");
  const [agentWeightsDraft, setAgentWeightsDraft] = useState("{}");
  const [runTypeOverridesDraft, setRunTypeOverridesDraft] = useState("{}");

  const [playbookJsonDraft, setPlaybookJsonDraft] = useState("{}");
  const [candidateCompactThreshold, setCandidateCompactThreshold] = useState("1000000");
  const [jobCompactThreshold, setJobCompactThreshold] = useState("1000000");
  const [globalCompactThreshold, setGlobalCompactThreshold] = useState("1000000");
  const [candidateAutoCompact, setCandidateAutoCompact] = useState(true);
  const [jobAutoCompact, setJobAutoCompact] = useState(true);
  const [globalAutoCompact, setGlobalAutoCompact] = useState(true);
  const [defaultStatusesDraft, setDefaultStatusesDraft] = useState("");

  const [selectedSkillId, setSelectedSkillId] = useState<string>();
  const [skillDescriptionDraft, setSkillDescriptionDraft] = useState("");
  const [skillStrategyDraft, setSkillStrategyDraft] = useState("{}");
  const [skillExecutionHintsDraft, setSkillExecutionHintsDraft] = useState("{}");
  const [skillMetadataDraft, setSkillMetadataDraft] = useState("{}");
  const [skillInputDraft, setSkillInputDraft] = useState("{}");
  const [skillOutputDraft, setSkillOutputDraft] = useState("{}");
  const [skillHealthConfigDraft, setSkillHealthConfigDraft] = useState("{}");

  const [selectedMemoryKey, setSelectedMemoryKey] = useState<MemoryTargetKey>("global");
  const [memorySummaryDraft, setMemorySummaryDraft] = useState("");
  const [memoryDisclosurePreviewDraft, setMemoryDisclosurePreviewDraft] = useState("");
  const [memoryDisclosureOperatorDraft, setMemoryDisclosureOperatorDraft] = useState("");
  const [memoryDisclosureModelDraft, setMemoryDisclosureModelDraft] = useState("");
  const [memoryRawDraft, setMemoryRawDraft] = useState("{}");
  const [memoryCompactDraft, setMemoryCompactDraft] = useState("{}");

  useEffect(() => {
    if (!profile) {
      return;
    }
    const roleDefinition = (profile.roleDefinition ?? {}) as Record<string, unknown>;
    const promptConfig = (profile.promptConfig ?? {}) as Record<string, unknown>;
    const contextPolicy = ((promptConfig.context_policy as Record<string, unknown> | undefined) ?? {}) as Record<string, unknown>;
    const contextGlobal = ((contextPolicy.global as Record<string, unknown> | undefined) ?? {}) as Record<string, unknown>;
    const contextLanes = ((contextPolicy.lanes as Record<string, unknown> | undefined) ?? {}) as Record<string, unknown>;
    const candidateLanePolicy = ((contextLanes.candidate as Record<string, unknown> | undefined) ?? {}) as Record<string, unknown>;
    const agentLanePolicy = ((contextLanes.agent as Record<string, unknown> | undefined) ?? {}) as Record<string, unknown>;
    const memoryPolicy = (profile.memoryPolicy ?? {}) as Record<string, unknown>;
    const playbookBlueprint = (profile.playbookBlueprint ?? {}) as Record<string, unknown>;
    const statusMachine = (playbookBlueprint.status_machine ?? {}) as Record<string, unknown>;
    setDescriptionDraft(profile.description ?? "");
    setIdentityDraft(String(roleDefinition.identity ?? ""));
    setPositioningDraft(String(roleDefinition.positioning ?? ""));
    setDutiesDraft(arrayToLines(roleDefinition.duties));
    setToneDraft(String(roleDefinition.tone ?? ""));
    setBoundariesDraft(arrayToLines(roleDefinition.boundaries));
    setSuccessCriteriaDraft(arrayToLines(roleDefinition.success_criteria));
    setForbiddenActionsDraft(arrayToLines(roleDefinition.forbidden_actions));
    setSystemPromptDraft(String(promptConfig.system_prompt ?? ""));
    setContextSlotsDraft(Array.isArray(promptConfig.context_slots) ? promptConfig.context_slots.join(", ") : "");
    setDashboardDraft(stringifyJson(profile.dashboardConfig));
    setChannelDraft(stringifyJson(profile.channelConfig));
    setMetadataDraft(stringifyJson(profile.agentMetadata));
    setContextTokenBudgetDraft(String(contextGlobal.token_budget_default ?? 4096));
    setContextLlmRerankEnabled(Boolean(contextGlobal.llm_rerank_enabled ?? false));
    setContextLlmTopKDraft(String(contextGlobal.llm_rerank_top_k ?? 6));
    setContextLlmMaxBoostDraft(String(contextGlobal.llm_rerank_max_boost ?? 8));
    setContextDropOrderDraft(arrayToLines(contextGlobal.drop_order));
    setCandidateMustIncludeDraft(arrayToLines(candidateLanePolicy.must_include));
    setCandidateWeightsDraft(stringifyJson(candidateLanePolicy.default_weights));
    setAgentMustIncludeDraft(arrayToLines(agentLanePolicy.must_include));
    setAgentWeightsDraft(stringifyJson(agentLanePolicy.default_weights));
    setRunTypeOverridesDraft(stringifyJson(contextPolicy.run_type_overrides));
    setPlaybookJsonDraft(stringifyJson(profile.playbookBlueprint));
    setCandidateCompactThreshold(String(((memoryPolicy.candidate_memory as Record<string, unknown> | undefined)?.compact_threshold ?? 1_000_000)));
    setJobCompactThreshold(String(((memoryPolicy.job_memory as Record<string, unknown> | undefined)?.compact_threshold ?? 1_000_000)));
    setGlobalCompactThreshold(String(((memoryPolicy.agent_global_memory as Record<string, unknown> | undefined)?.compact_threshold ?? 1_000_000)));
    setCandidateAutoCompact(Boolean((memoryPolicy.candidate_memory as Record<string, unknown> | undefined)?.auto_compact ?? true));
    setJobAutoCompact(Boolean((memoryPolicy.job_memory as Record<string, unknown> | undefined)?.auto_compact ?? true));
    setGlobalAutoCompact(Boolean((memoryPolicy.agent_global_memory as Record<string, unknown> | undefined)?.auto_compact ?? true));
    setDefaultStatusesDraft(Array.isArray(statusMachine.default_statuses) ? statusMachine.default_statuses.join("\n") : "");
  }, [profile]);

  useEffect(() => {
    if (!skills.length) {
      setSelectedSkillId(undefined);
      return;
    }
    if (!selectedSkillId || !skills.some((item) => item.id === selectedSkillId)) {
      setSelectedSkillId(skills[0].id);
    }
  }, [selectedSkillId, skills]);

  const selectedSkill = skills.find((item) => item.id === selectedSkillId) ?? null;

  useEffect(() => {
    if (!selectedSkill) {
      setSkillDescriptionDraft("");
      setSkillStrategyDraft("{}");
      setSkillExecutionHintsDraft("{}");
      setSkillMetadataDraft("{}");
      setSkillInputDraft("{}");
      setSkillOutputDraft("{}");
      setSkillHealthConfigDraft("{}");
      return;
    }
    setSkillDescriptionDraft(selectedSkill.description ?? "");
    setSkillStrategyDraft(stringifyJson(selectedSkill.strategy));
    setSkillExecutionHintsDraft(stringifyJson(selectedSkill.executionHints));
    setSkillMetadataDraft(stringifyJson(selectedSkill.skillMetadata));
    setSkillInputDraft(stringifyJson(selectedSkill.inputSchema));
    setSkillOutputDraft(stringifyJson(selectedSkill.outputSchema));
    setSkillHealthConfigDraft(stringifyJson(selectedSkill.healthCheckConfig));
  }, [selectedSkill]);

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

  const memoryTargets = useMemo(() => {
    const items: Array<{ key: MemoryTargetKey; label: string; detail: string }> = [
      { key: "global", label: copy("Global Memory", "全局记忆"), detail: copy("Cross-candidate lessons only", "仅跨候选人的全局经验") },
      ...personMemories.map((item) => ({
        key: `candidate:${item.personId}` as const,
        label: applicationDisplayNameById.get(item.personId) ?? item.personId,
        detail: copy("Candidate-isolated memory", "候选人隔离记忆"),
      })),
      ...jobMemories.map((item) => ({
        key: `job:${item.jobDescriptionId}` as const,
        label: item.jobDescriptionId,
        detail: copy("JD-isolated memory", "JD 隔离记忆"),
      })),
    ];
    return items;
  }, [applicationDisplayNameById, personMemories, copy, jobMemories]);

  useEffect(() => {
    if (!memoryTargets.length) {
      return;
    }
    if (!memoryTargets.some((item) => item.key === selectedMemoryKey)) {
      setSelectedMemoryKey(memoryTargets[0].key);
    }
  }, [memoryTargets, selectedMemoryKey]);

  const selectedMemory = useMemo(() => {
    if (selectedMemoryKey === "global") {
      return globalMemory ? { kind: "global" as const, record: globalMemory } : null;
    }
    const [scope, id] = selectedMemoryKey.split(":");
    if (scope === "candidate") {
      const record = personMemories.find((item) => item.personId === id);
      return record ? { kind: "candidate" as const, record } : null;
    }
    const record = jobMemories.find((item) => item.jobDescriptionId === id);
    return record ? { kind: "job" as const, record } : null;
  }, [personMemories, globalMemory, jobMemories, selectedMemoryKey]);

  const parsedPlaybookDraft = useMemo(() => {
    try {
      return parseJsonDraft("playbookBlueprint", playbookJsonDraft);
    } catch {
      return null;
    }
  }, [playbookJsonDraft]);

  const blueprintStageGroups = useMemo(
    () => (parsedPlaybookDraft && Array.isArray(parsedPlaybookDraft.stage_groups) ? (parsedPlaybookDraft.stage_groups as Array<Record<string, unknown>>) : []),
    [parsedPlaybookDraft],
  );

  const blueprintStages = useMemo(
    () => {
      if (!parsedPlaybookDraft) {
        return [];
      }
      if (Array.isArray(parsedPlaybookDraft.adaptive_stages)) {
        return parsedPlaybookDraft.adaptive_stages as Array<Record<string, unknown>>;
      }
      return Array.isArray(parsedPlaybookDraft.nodes) ? (parsedPlaybookDraft.nodes as Array<Record<string, unknown>>) : [];
    },
    [parsedPlaybookDraft],
  );

  useEffect(() => {
    if (!selectedMemory) {
      setMemorySummaryDraft("");
      setMemoryDisclosurePreviewDraft("");
      setMemoryDisclosureOperatorDraft("");
      setMemoryDisclosureModelDraft("");
      setMemoryRawDraft("{}");
      setMemoryCompactDraft("{}");
      return;
    }
    setMemorySummaryDraft(selectedMemory.record.summary ?? "");
    setMemoryDisclosurePreviewDraft(selectedMemory.record.disclosure.preview ?? "");
    setMemoryDisclosureOperatorDraft(selectedMemory.record.disclosure.operatorSummary ?? "");
    setMemoryDisclosureModelDraft(selectedMemory.record.disclosure.modelContext ?? "");
    setMemoryRawDraft(stringifyJson(selectedMemory.record.rawContent));
    setMemoryCompactDraft(stringifyJson(selectedMemory.record.content));
  }, [selectedMemory]);

  const saveProfile = async (payload: Partial<RecruitAgentProfileRecord>) => {
    setErrorMessage(undefined);
    try {
      await onSaveProfile(payload);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : copy("Failed to save Recruit Agent profile.", "保存 Recruit Agent 配置失败。"));
    }
  };

  const handleSaveProfile = async () => {
    setErrorMessage(undefined);
    try {
      const advancedBlueprint = parseJsonDraft("playbookBlueprint", playbookJsonDraft);
      await saveProfile({
        description: descriptionDraft,
        roleDefinition: {
          identity: identityDraft,
          positioning: positioningDraft,
          duties: linesToArray(dutiesDraft),
          tone: toneDraft,
          boundaries: linesToArray(boundariesDraft),
          success_criteria: linesToArray(successCriteriaDraft),
          forbidden_actions: linesToArray(forbiddenActionsDraft),
        },
        promptConfig: {
          ...((profile?.promptConfig ?? {}) as Record<string, unknown>),
          system_prompt: systemPromptDraft,
          context_slots: contextSlotsDraft.split(",").map((item) => item.trim()).filter(Boolean),
        },
        dashboardConfig: parseJsonDraft("dashboardConfig", dashboardDraft),
        channelConfig: parseJsonDraft("channelConfig", channelDraft),
        agentMetadata: parseJsonDraft("agentMetadata", metadataDraft),
        playbookBlueprint: {
          ...advancedBlueprint,
          status_machine: {
            ...(((advancedBlueprint.status_machine as Record<string, unknown> | undefined) ?? {})),
            default_statuses: linesToArray(defaultStatusesDraft),
          },
        },
        memoryPolicy: {
          candidate_memory: {
            ...((((profile?.memoryPolicy ?? {}) as Record<string, unknown>).candidate_memory as Record<string, unknown> | undefined) ?? {}),
            auto_compact: candidateAutoCompact,
            compact_threshold: compactNumber(candidateCompactThreshold, 1_000_000),
            disclosure: ["preview", "operator_summary", "model_context"],
          },
          job_memory: {
            ...((((profile?.memoryPolicy ?? {}) as Record<string, unknown>).job_memory as Record<string, unknown> | undefined) ?? {}),
            auto_compact: jobAutoCompact,
            compact_threshold: compactNumber(jobCompactThreshold, 1_000_000),
            disclosure: ["preview", "operator_summary", "model_context"],
          },
          agent_global_memory: {
            ...((((profile?.memoryPolicy ?? {}) as Record<string, unknown>).agent_global_memory as Record<string, unknown> | undefined) ?? {}),
            auto_compact: globalAutoCompact,
            compact_threshold: compactNumber(globalCompactThreshold, 1_000_000),
            disclosure: ["preview", "operator_summary", "model_context"],
          },
        },
      });
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : copy("Failed to save Recruit Agent profile.", "保存 Recruit Agent 配置失败。"));
    }
  };

  const handleSaveContextPolicy = async () => {
    setErrorMessage(undefined);
    try {
      await saveProfile({
        promptConfig: {
          ...((profile?.promptConfig ?? {}) as Record<string, unknown>),
          context_policy: {
            version: "context-policy-v1",
            global: {
              token_budget_default: compactNumber(contextTokenBudgetDraft, 4096),
              llm_rerank_enabled: contextLlmRerankEnabled,
              llm_rerank_top_k: compactNumber(contextLlmTopKDraft, 6),
              llm_rerank_max_boost: compactNumber(contextLlmMaxBoostDraft, 8),
              drop_order: linesToArray(contextDropOrderDraft),
            },
            lanes: {
              candidate: {
                must_include: linesToArray(candidateMustIncludeDraft),
                default_weights: parseJsonDraft("context_policy.lanes.candidate.default_weights", candidateWeightsDraft),
              },
              agent: {
                must_include: linesToArray(agentMustIncludeDraft),
                default_weights: parseJsonDraft("context_policy.lanes.agent.default_weights", agentWeightsDraft),
              },
            },
            run_type_overrides: parseJsonDraft("context_policy.run_type_overrides", runTypeOverridesDraft),
          },
        },
      });
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : copy("Failed to save context policy.", "保存上下文策略失败。"));
    }
  };

  const handleSaveSkill = async () => {
    if (!selectedSkill) {
      return;
    }
    setErrorMessage(undefined);
    try {
      await onUpdateSkill(selectedSkill.id, {
        description: skillDescriptionDraft,
        strategy: parseJsonDraft("skill.strategy", skillStrategyDraft),
        executionHints: parseJsonDraft("skill.executionHints", skillExecutionHintsDraft),
        skillMetadata: parseJsonDraft("skill.skillMetadata", skillMetadataDraft),
        inputSchema: parseJsonDraft("skill.inputSchema", skillInputDraft),
        outputSchema: parseJsonDraft("skill.outputSchema", skillOutputDraft),
        healthCheckConfig: parseJsonDraft("skill.healthCheckConfig", skillHealthConfigDraft),
      });
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : copy("Failed to save skill.", "保存 skill 失败。"));
    }
  };

  const handleSaveMemory = async () => {
    if (!selectedMemory) {
      return;
    }
    setErrorMessage(undefined);
    try {
      const payload = {
        summary: memorySummaryDraft,
        rawContent: parseJsonDraft("memory.rawContent", memoryRawDraft),
        content: parseJsonDraft("memory.content", memoryCompactDraft),
        disclosure: {
          preview: memoryDisclosurePreviewDraft,
          operatorSummary: memoryDisclosureOperatorDraft,
          modelContext: memoryDisclosureModelDraft,
          tiers: selectedMemory.record.disclosure.tiers,
        },
      };
      if (selectedMemory.kind === "candidate") {
        await onUpdatePersonMemory(selectedMemory.record.personId, payload);
        return;
      }
      if (selectedMemory.kind === "job") {
        await onUpdateJobMemory(selectedMemory.record.jobDescriptionId, payload);
        return;
      }
      await onUpdateGlobalMemory(payload);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : copy("Failed to save memory.", "保存 memory 失败。"));
    }
  };

  const handleCompactMemory = async () => {
    if (!selectedMemory) {
      return;
    }
    if (selectedMemory.kind === "candidate") {
      await onCompactPersonMemory(selectedMemory.record.personId);
      return;
    }
    if (selectedMemory.kind === "job") {
      await onCompactJobMemory(selectedMemory.record.jobDescriptionId);
      return;
    }
    await onCompactGlobalMemory();
  };

  const updatePlaybookDraft = (updater: (draft: Record<string, unknown>) => void) => {
    const parsed = parseJsonDraft("playbookBlueprint", playbookJsonDraft);
    updater(parsed);
    setPlaybookJsonDraft(stringifyJson(parsed));
    const statusMachine = (parsed.status_machine ?? {}) as Record<string, unknown>;
    setDefaultStatusesDraft(Array.isArray(statusMachine.default_statuses) ? statusMachine.default_statuses.map((item) => String(item)).join("\n") : "");
  };

  const updateStageGroupField = (groupIndex: number, field: string, value: unknown) => {
    updatePlaybookDraft((draft) => {
      const groups = Array.isArray(draft.stage_groups) ? [...(draft.stage_groups as Array<Record<string, unknown>>)] : [];
      const group = { ...(groups[groupIndex] ?? {}) };
      group[field] = value;
      groups[groupIndex] = group;
      draft.stage_groups = groups;
    });
  };

  const updateStageField = (groupIndex: number, stageIndex: number, field: string, value: unknown) => {
    updatePlaybookDraft((draft) => {
      const groups = Array.isArray(draft.stage_groups) ? [...(draft.stage_groups as Array<Record<string, unknown>>)] : [];
      const group = { ...(groups[groupIndex] ?? {}) };
      const stages = Array.isArray(group.stages) ? [...(group.stages as Array<Record<string, unknown>>)] : [];
      const stage = { ...(stages[stageIndex] ?? {}) };
      stage[field] = value;
      stages[stageIndex] = stage;
      group.stages = stages;
      groups[groupIndex] = group;
      draft.stage_groups = groups;
    });
  };

  const addStageToGroup = (groupIndex: number) => {
    updatePlaybookDraft((draft) => {
      const groups = Array.isArray(draft.stage_groups) ? [...(draft.stage_groups as Array<Record<string, unknown>>)] : [];
      const group = { ...(groups[groupIndex] ?? {}) };
      const stages = Array.isArray(group.stages) ? [...(group.stages as Array<Record<string, unknown>>)] : [];
      stages.push({ key: `custom_stage_${stages.length + 1}`, label: `自定义阶段 ${stages.length + 1}` });
      group.stages = stages;
      groups[groupIndex] = group;
      draft.stage_groups = groups;
    });
  };

  const updateInterviewRoundField = (groupIndex: number, roundIndex: number, field: string, value: unknown) => {
    updatePlaybookDraft((draft) => {
      const groups = Array.isArray(draft.stage_groups) ? [...(draft.stage_groups as Array<Record<string, unknown>>)] : [];
      const group = { ...(groups[groupIndex] ?? {}) };
      const rounds = Array.isArray(group.default_rounds) ? [...(group.default_rounds as Array<Record<string, unknown>>)] : [];
      const round = { ...(rounds[roundIndex] ?? {}) };
      round[field] = value;
      rounds[roundIndex] = round;
      group.default_rounds = rounds;
      groups[groupIndex] = group;
      draft.stage_groups = groups;
    });
  };

  const updateBlueprintStageField = (nodeIndex: number, field: string, value: unknown) => {
    updatePlaybookDraft((draft) => {
      const nodes = Array.isArray(draft.nodes) ? [...(draft.nodes as Array<Record<string, unknown>>)] : [];
      const node = { ...(nodes[nodeIndex] ?? {}) };
      node[field] = value;
      nodes[nodeIndex] = node;
      draft.nodes = nodes;
    });
  };

  const profileContent = (
    <div style={{ display: "grid", gap: "var(--space-5)" }}>
      <Panel
        title={copy("AI Strategy", "AI 策略")}
        eyebrow={copy("Role and scope", "角色与边界")}
        description={copy("Define the recruiting voice, role, duties, and prompt sources as structured fields.", "用结构化字段定义招聘语气、角色、职责和提示来源。")}
        actions={
          <div style={{ display: "flex", gap: "var(--space-2)" }}>
            <StatusBadge tone={profile?.isPrimary ? "positive" : "neutral"}>{profile?.status ?? "draft"}</StatusBadge>
            <button type="button" onClick={() => void handleSaveProfile()} style={buttonStyle}>{copy("Save", "保存")}</button>
          </div>
        }
      >
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "var(--space-5)" }}>
          <div style={{ display: "grid", gap: "var(--space-3)" }}>
            <label style={{ display: "grid", gap: "var(--space-2)" }}>
              <span>{copy("Overview", "概述")}</span>
              <textarea value={descriptionDraft} onChange={(event) => setDescriptionDraft(event.target.value)} style={{ ...textAreaStyle, minHeight: "calc(var(--space-12) + var(--space-10))" }} />
            </label>
            <label style={{ display: "grid", gap: "var(--space-2)" }}>
              <span>{copy("Role identity", "角色身份")}</span>
              <input value={identityDraft} onChange={(event) => setIdentityDraft(event.target.value)} style={inputStyle} />
            </label>
            <label style={{ display: "grid", gap: "var(--space-2)" }}>
              <span>{copy("Positioning", "定位")}</span>
              <textarea value={positioningDraft} onChange={(event) => setPositioningDraft(event.target.value)} style={{ ...textAreaStyle, minHeight: "calc(var(--space-12) + var(--space-10))" }} />
            </label>
            <label style={{ display: "grid", gap: "var(--space-2)" }}>
              <span>{copy("Responsibilities", "职责")}</span>
              <textarea value={dutiesDraft} onChange={(event) => setDutiesDraft(event.target.value)} style={textAreaStyle} />
            </label>
            <label style={{ display: "grid", gap: "var(--space-2)" }}>
              <span>{copy("Voice", "语气")}</span>
              <input value={toneDraft} onChange={(event) => setToneDraft(event.target.value)} style={inputStyle} />
            </label>
          </div>

          <div style={{ display: "grid", gap: "var(--space-3)" }}>
            <label style={{ display: "grid", gap: "var(--space-2)" }}>
              <span>{copy("Guardrails", "护栏")}</span>
              <textarea value={boundariesDraft} onChange={(event) => setBoundariesDraft(event.target.value)} style={textAreaStyle} />
            </label>
            <label style={{ display: "grid", gap: "var(--space-2)" }}>
              <span>{copy("Success signals", "成功信号")}</span>
              <textarea value={successCriteriaDraft} onChange={(event) => setSuccessCriteriaDraft(event.target.value)} style={textAreaStyle} />
            </label>
            <label style={{ display: "grid", gap: "var(--space-2)" }}>
              <span>{copy("Never-do list", "禁止事项")}</span>
              <textarea value={forbiddenActionsDraft} onChange={(event) => setForbiddenActionsDraft(event.target.value)} style={textAreaStyle} />
            </label>
            <label style={{ display: "grid", gap: "var(--space-2)" }}>
              <span>{copy("Core prompt", "核心提示词")}</span>
              <textarea value={systemPromptDraft} onChange={(event) => setSystemPromptDraft(event.target.value)} style={textAreaStyle} />
            </label>
            <label style={{ display: "grid", gap: "var(--space-2)" }}>
              <span>{copy("Context sources", "上下文来源")}</span>
              <input value={contextSlotsDraft} onChange={(event) => setContextSlotsDraft(event.target.value)} style={inputStyle} placeholder={copy("candidate_memory, job_memory, candidate_thread", "candidate_memory, job_memory, candidate_thread")} />
            </label>
          </div>
        </div>
      </Panel>

      <Panel title={copy("Supporting configuration", "辅助配置")} eyebrow={copy("Secondary settings", "次级设置")} description={copy("Workspace, channel, and metadata remain editable as supporting controls.", "工作区、渠道和元数据仍可作为辅助配置继续编辑。")}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: "var(--space-5)" }}>
          <label style={{ display: "grid", gap: "var(--space-2)" }}>
            <span>{copy("Workspace config JSON", "工作区配置 JSON")}</span>
            <textarea value={dashboardDraft} onChange={(event) => setDashboardDraft(event.target.value)} style={textAreaStyle} />
          </label>
          <label style={{ display: "grid", gap: "var(--space-2)" }}>
            <span>{copy("Delivery config JSON", "消息配置 JSON")}</span>
            <textarea value={channelDraft} onChange={(event) => setChannelDraft(event.target.value)} style={textAreaStyle} />
          </label>
          <label style={{ display: "grid", gap: "var(--space-2)" }}>
            <span>{copy("Strategy metadata JSON", "策略元数据 JSON")}</span>
            <textarea value={metadataDraft} onChange={(event) => setMetadataDraft(event.target.value)} style={textAreaStyle} />
          </label>
        </div>
      </Panel>
    </div>
  );

  const blueprintContent = (
    <div style={{ display: "grid", gap: "var(--space-5)" }}>
      <Panel
        title={copy("Strategy map", "策略地图")}
        eyebrow={copy("Adaptive stages", "自适应阶段")}
        description={copy("Define the stage groups and adaptive stages the strategy follows.", "定义策略在各阶段组和自适应阶段中的推进方式。")}
        actions={<button type="button" onClick={() => void handleSaveProfile()} style={buttonStyle}>{copy("Save strategy map", "保存策略地图")}</button>}
      >
        <div style={{ display: "grid", gap: "var(--space-4)" }}>
          <div style={{ display: "grid", gridTemplateColumns: "calc(var(--layout-left-list-width) - var(--space-10) - var(--space-5)) minmax(0, 1fr)", gap: "var(--space-3)", alignItems: "start" }}>
            <label style={{ display: "grid", gap: "var(--space-2)" }}>
              <span>{copy("Default statuses", "默认状态列表")}</span>
              <textarea value={defaultStatusesDraft} onChange={(event) => setDefaultStatusesDraft(event.target.value)} style={{ ...textAreaStyle, minHeight: "calc(var(--space-12) * 3 + var(--space-10) + var(--space-5) + var(--space-4))" }} />
            </label>
            <div style={{ display: "grid", gap: "var(--space-3)" }}>
              <div style={{ display: "grid", gridTemplateColumns: "calc(var(--space-10) * 3) calc(var(--space-10) * 4) calc(var(--space-10) * 2 + var(--space-5)) minmax(0, 1fr) auto", gap: "var(--space-2)", color: theme.colors.muted, fontSize: "var(--font-size-xs)" }}>
                <span>{copy("Group", "阶段组")}</span>
                <span>{copy("Stage key", "阶段键")}</span>
                <span>{copy("Repeatable", "可重复")}</span>
                <span>{copy("Stage label", "阶段标题")}</span>
                <span>{copy("Action", "操作")}</span>
              </div>
              {blueprintStageGroups.map((group, groupIndex) => {
                const stages = Array.isArray(group.stages) ? (group.stages as Array<Record<string, unknown>>) : [];
                const rounds = Array.isArray(group.default_rounds) ? (group.default_rounds as Array<Record<string, unknown>>) : [];
                return (
                  <div key={String(group.id ?? groupIndex)} style={{ display: "grid", gap: "var(--space-2)", borderTop: `1px solid ${theme.colors.border}`, paddingTop: "var(--space-2)" }}>
                    <div style={{ display: "grid", gridTemplateColumns: "calc(var(--space-10) * 3) calc(var(--space-10) * 4) calc(var(--space-10) * 2 + var(--space-5)) minmax(0, 1fr) auto", gap: "var(--space-2)", alignItems: "center" }}>
                      <input value={String(group.name ?? "")} onChange={(event) => updateStageGroupField(groupIndex, "name", event.target.value)} style={inputStyle} />
                      <input value={String(group.id ?? "")} onChange={(event) => updateStageGroupField(groupIndex, "id", event.target.value)} style={inputStyle} />
                      <label style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", fontSize: "var(--font-size-sm)" }}>
                        <input type="checkbox" checked={Boolean(group.repeatable ?? false)} onChange={(event) => updateStageGroupField(groupIndex, "repeatable", event.target.checked)} />
                        <span>{Boolean(group.repeatable ?? false) ? copy("Yes", "是") : copy("No", "否")}</span>
                      </label>
                      <div style={{ color: theme.colors.muted, fontSize: "var(--font-size-xs)" }}>{String(group.name ?? group.id ?? "")}</div>
                      <button type="button" onClick={() => addStageToGroup(groupIndex)} style={buttonStyle}>{copy("Add stage", "加阶段")}</button>
                    </div>
                    {stages.map((stage, stageIndex) => (
                      <div key={String(stage.key ?? `${groupIndex}-${stageIndex}`)} style={{ display: "grid", gridTemplateColumns: "calc(var(--space-10) * 3) calc(var(--space-10) * 4) calc(var(--space-10) * 2 + var(--space-5)) minmax(0, 1fr) auto", gap: "var(--space-2)", alignItems: "center" }}>
                        <div style={{ color: theme.colors.muted, fontSize: "var(--font-size-xs)" }}>{String(group.name ?? group.id ?? "")}</div>
                        <input value={String(stage.key ?? "")} onChange={(event) => updateStageField(groupIndex, stageIndex, "key", event.target.value)} style={inputStyle} />
                        <div style={{ color: theme.colors.muted, fontSize: "var(--font-size-xs)" }}>{copy("stage", "阶段")}</div>
                        <input value={String(stage.label ?? "")} onChange={(event) => updateStageField(groupIndex, stageIndex, "label", event.target.value)} style={inputStyle} />
                        <span style={{ color: theme.colors.muted, fontSize: "var(--font-size-xs)" }}>{stageIndex + 1}</span>
                      </div>
                    ))}
                    {rounds.map((round, roundIndex) => (
                      <div key={String(round.round ?? `${groupIndex}-round-${roundIndex}`)} style={{ display: "grid", gridTemplateColumns: "calc(var(--space-10) * 3) calc(var(--space-10) * 4) calc(var(--space-10) * 2 + var(--space-5)) minmax(0, 1fr) auto", gap: "var(--space-2)", alignItems: "center" }}>
                        <div style={{ color: theme.colors.muted, fontSize: "var(--font-size-xs)" }}>{copy("Interview", "面试轮次")}</div>
                        <input value={String(round.waiting_key ?? "")} onChange={(event) => updateInterviewRoundField(groupIndex, roundIndex, "waiting_key", event.target.value)} style={inputStyle} />
                        <div style={{ color: theme.colors.muted, fontSize: "var(--font-size-xs)" }}>{copy(`Round ${String(round.round ?? roundIndex + 1)}`, `第 ${String(round.round ?? roundIndex + 1)} 轮`)}</div>
                        <input value={String(round.scheduled_key ?? "")} onChange={(event) => updateInterviewRoundField(groupIndex, roundIndex, "scheduled_key", event.target.value)} style={inputStyle} />
                        <span style={{ color: theme.colors.muted, fontSize: "var(--font-size-xs)" }}>{copy("waiting / scheduled", "待约 / 已约")}</span>
                      </div>
                    ))}
                  </div>
                );
              })}
              {!blueprintStageGroups.length ? <div style={{ color: theme.colors.muted, fontSize: "var(--font-size-sm)" }}>{copy("Strategy map JSON is invalid or missing stage groups.", "策略地图 JSON 无效，或缺少阶段组。")}</div> : null}
            </div>
          </div>
          <div style={{ display: "grid", gap: "var(--space-3)" }}>
            <div style={{ display: "grid", gridTemplateColumns: "calc(var(--space-10) * 4 + var(--space-5)) calc(var(--space-10) * 3 + var(--space-5)) calc(var(--space-10) * 3) minmax(0, 1fr)", gap: "var(--space-2)", color: theme.colors.muted, fontSize: "var(--font-size-xs)" }}>
              <span>{copy("Stage", "阶段")}</span>
              <span>{copy("Task type", "任务类型")}</span>
              <span>{copy("Needs skill", "需要 skill")}</span>
              <span>{copy("Purpose / next stage", "用途 / 下一步")}</span>
            </div>
            {blueprintStages.map((node, nodeIndex) => {
              const transitions = Array.isArray(node.transitions) ? (node.transitions as Array<Record<string, unknown>>) : [];
              return (
                <div key={String(node.id ?? nodeIndex)} style={{ display: "grid", gridTemplateColumns: "calc(var(--space-10) * 4 + var(--space-5)) calc(var(--space-10) * 3 + var(--space-5)) calc(var(--space-10) * 3) minmax(0, 1fr)", gap: "var(--space-2)", alignItems: "center" }}>
                  <input value={String(node.name ?? "")} onChange={(event) => updateBlueprintStageField(nodeIndex, "name", event.target.value)} style={inputStyle} />
                  <input value={String(node.task_type ?? "")} onChange={(event) => updateBlueprintStageField(nodeIndex, "task_type", event.target.value)} style={inputStyle} />
                  <label style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", fontSize: "var(--font-size-sm)" }}>
                    <input type="checkbox" checked={Boolean(node.requires_skill ?? false)} onChange={(event) => updateBlueprintStageField(nodeIndex, "requires_skill", event.target.checked)} />
                    <span>{Boolean(node.requires_skill ?? false) ? copy("Yes", "是") : copy("No", "否")}</span>
                  </label>
                  <div style={{ color: theme.colors.muted, fontSize: "var(--font-size-xs)", lineHeight: 1.5 }}>
                    {String(node.purpose ?? "").trim()
                      ? `${String(node.purpose ?? "")}${node.next_stage ? `\n${copy("Next", "下一步")}: ${String(node.next_stage)}` : ""}`
                      : transitions.length
                        ? transitions.map((item) => `${String(item.condition ?? "default")} -> ${String(item.target_node_id ?? "")}`).join("\n")
                        : copy("No transitions", "无流转")}
                  </div>
                </div>
              );
            })}
          </div>
          <details>
            <summary style={{ cursor: "pointer", color: theme.colors.muted, fontSize: "var(--font-size-xs)" }}>{copy("Advanced JSON editor", "高级 JSON 编辑器")}</summary>
            <label style={{ display: "grid", gap: "var(--space-2)", marginTop: "var(--space-3)" }}>
              <span>{copy("Strategy map JSON", "策略地图 JSON")}</span>
              <textarea value={playbookJsonDraft} onChange={(event) => setPlaybookJsonDraft(event.target.value)} style={{ ...textAreaStyle, minHeight: "calc(var(--space-12) * 3 + var(--space-10) + var(--space-10) + var(--space-5) + var(--space-4))" }} />
            </label>
          </details>
        </div>
      </Panel>

      <Panel title={copy("Memory policy", "记忆策略")} eyebrow={copy("Layered compaction", "分层压缩")} description={copy("All memory keeps a summary, an internal view, and a model-facing view. Auto compaction runs when the configured threshold is exceeded.", "所有 memory 都同时保留摘要层、内部视图层和模型可见层。超过阈值时自动压缩。")}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: "var(--space-5)" }}>
          <article style={{ display: "grid", gap: "var(--space-3)" }}>
            <strong>{copy("Candidate memory", "候选人记忆")}</strong>
            <label style={{ display: "grid", gap: "var(--space-2)" }}>
              <span>{copy("Compact threshold", "压缩阈值")}</span>
              <input value={candidateCompactThreshold} onChange={(event) => setCandidateCompactThreshold(event.target.value)} style={inputStyle} />
            </label>
            <label style={{ display: "flex", gap: "var(--space-2)", alignItems: "center" }}>
              <input type="checkbox" checked={candidateAutoCompact} onChange={(event) => setCandidateAutoCompact(event.target.checked)} />
              <span>{copy("Auto compact", "自动 compact")}</span>
            </label>
          </article>
          <article style={{ display: "grid", gap: "var(--space-3)" }}>
            <strong>{copy("JD memory", "JD 记忆")}</strong>
            <label style={{ display: "grid", gap: "var(--space-2)" }}>
              <span>{copy("Compact threshold", "压缩阈值")}</span>
              <input value={jobCompactThreshold} onChange={(event) => setJobCompactThreshold(event.target.value)} style={inputStyle} />
            </label>
            <label style={{ display: "flex", gap: "var(--space-2)", alignItems: "center" }}>
              <input type="checkbox" checked={jobAutoCompact} onChange={(event) => setJobAutoCompact(event.target.checked)} />
              <span>{copy("Auto compact", "自动 compact")}</span>
            </label>
          </article>
          <article style={{ display: "grid", gap: "var(--space-3)" }}>
            <strong>{copy("Global memory", "全局记忆")}</strong>
            <label style={{ display: "grid", gap: "var(--space-2)" }}>
              <span>{copy("Compact threshold", "压缩阈值")}</span>
              <input value={globalCompactThreshold} onChange={(event) => setGlobalCompactThreshold(event.target.value)} style={inputStyle} />
            </label>
            <label style={{ display: "flex", gap: "var(--space-2)", alignItems: "center" }}>
              <input type="checkbox" checked={globalAutoCompact} onChange={(event) => setGlobalAutoCompact(event.target.checked)} />
              <span>{copy("Auto compact", "自动 compact")}</span>
            </label>
          </article>
        </div>
      </Panel>
    </div>
  );

  const memoryContent = (
    <div style={{ display: "grid", gridTemplateColumns: "var(--layout-right-panel-width) minmax(0, 1fr)", gap: "var(--space-5)" }}>
      <Panel title={copy("Memory workspace", "记忆工作区")} eyebrow={copy("Strict isolation", "严格隔离")} description={copy("Candidate memory and JD memory stay isolated. The UI reveals summary, internal view, and model-facing view in order.", "Candidate memory 和 JD memory 保持隔离。界面按顺序展示摘要、内部视图和模型可见视图。")}>
        <div style={{ display: "grid", gap: "var(--space-3)" }}>
          {memoryTargets.map((item) => (
            <button
              key={item.key}
              type="button"
              onClick={() => setSelectedMemoryKey(item.key)}
              style={{
                cursor: "pointer",
                textAlign: "left",
                borderRadius: theme.radius.xl,
                border: `1px solid ${selectedMemoryKey === item.key ? theme.colors.accent : theme.colors.border}`,
                background: selectedMemoryKey === item.key ? "var(--brand-primary-soft)" : "var(--bg-page)",
                color: theme.colors.text,
                padding: "var(--space-3)",
              }}
            >
              <div style={{ fontWeight: 600 }}>{item.label}</div>
              <div style={{ color: theme.colors.muted, fontSize: "var(--font-size-xs)", marginTop: "var(--space-1)" }}>{item.detail}</div>
            </button>
          ))}
        </div>
      </Panel>

      <Panel
        title={selectedMemory ? (selectedMemory.kind === "candidate" ? applicationDisplayNameById.get(selectedMemory.record.personId) ?? selectedMemory.record.personId : selectedMemory.kind === "job" ? selectedMemory.record.jobDescriptionId : copy("Global memory", "全局记忆")) : copy("Memory detail", "Memory 详情")}
        eyebrow={copy("Progressive disclosure", "渐进式披露")}
        description={copy("Raw evidence remains preserved. The compacted content and model-ready view are editable separately.", "原始证据会被保留。压缩内容和模型可用视图可以独立编辑。")}
        actions={
          <div style={{ display: "flex", gap: "var(--space-2)" }}>
            <button type="button" onClick={() => void handleCompactMemory()} style={buttonStyle} disabled={!selectedMemory}>{copy("Compact", "执行 compact")}</button>
            <button type="button" onClick={() => void handleSaveMemory()} style={buttonStyle} disabled={!selectedMemory}>{copy("Save", "保存")}</button>
          </div>
        }
      >
        {selectedMemory ? (
          <div style={{ display: "grid", gap: "var(--space-3)" }}>
            <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
              <StatusBadge tone="neutral">{selectedMemory.record.memorySchemaVersion}</StatusBadge>
              <StatusBadge tone="neutral">{copy(`tokens ${selectedMemory.record.tokenEstimate}`, `tokens ${selectedMemory.record.tokenEstimate}`)}</StatusBadge>
              {selectedMemory.record.compactedAt ? <StatusBadge tone="warning">{copy(`last compact ${formatCompactDate(selectedMemory.record.compactedAt)}`, `最近 compact 于 ${formatCompactDate(selectedMemory.record.compactedAt)}`)}</StatusBadge> : null}
            </div>
            <label style={{ display: "grid", gap: "var(--space-2)" }}>
              <span>{copy("Summary", "摘要")}</span>
              <textarea value={memorySummaryDraft} onChange={(event) => setMemorySummaryDraft(event.target.value)} style={{ ...textAreaStyle, minHeight: "calc(var(--space-12) + var(--space-10))" }} />
            </label>
            <label style={{ display: "grid", gap: "var(--space-2)" }}>
              <span>{copy("Recruiter preview", "招聘视图")}</span>
              <input value={memoryDisclosurePreviewDraft} onChange={(event) => setMemoryDisclosurePreviewDraft(event.target.value)} style={inputStyle} />
            </label>
            <label style={{ display: "grid", gap: "var(--space-2)" }}>
              <span>{copy("Internal summary", "内部摘要")}</span>
              <textarea value={memoryDisclosureOperatorDraft} onChange={(event) => setMemoryDisclosureOperatorDraft(event.target.value)} style={{ ...textAreaStyle, minHeight: "calc(var(--space-12) + var(--space-10))" }} />
            </label>
            <label style={{ display: "grid", gap: "var(--space-2)" }}>
              <span>{copy("Model view", "模型视图")}</span>
              <textarea value={memoryDisclosureModelDraft} onChange={(event) => setMemoryDisclosureModelDraft(event.target.value)} style={{ ...textAreaStyle, minHeight: "calc(var(--space-10) * 3)" }} />
            </label>
            <details>
              <summary style={{ cursor: "pointer", color: theme.colors.muted }}>{copy("Show compacted content JSON", "查看 compact 后内容 JSON")}</summary>
              <textarea value={memoryCompactDraft} onChange={(event) => setMemoryCompactDraft(event.target.value)} style={{ ...textAreaStyle, minHeight: "calc(var(--space-12) * 3 + var(--space-10) + var(--space-5) + var(--space-4))", marginTop: "var(--space-3)" }} />
            </details>
            <details>
              <summary style={{ cursor: "pointer", color: theme.colors.muted }}>{copy("Show raw record JSON", "查看原始记录 JSON")}</summary>
              <textarea value={memoryRawDraft} onChange={(event) => setMemoryRawDraft(event.target.value)} style={{ ...textAreaStyle, minHeight: "calc(var(--space-12) * 3 + var(--space-10) + var(--space-5) + var(--space-4))", marginTop: "var(--space-3)" }} />
            </details>
          </div>
        ) : (
          <div style={{ color: theme.colors.muted }}>{copy("No memory selected.", "尚未选择 memory。")}</div>
        )}
      </Panel>
    </div>
  );

  const contextContent = (
    <div style={{ display: "grid", gap: "var(--space-5)" }}>
      <Panel
        title={copy("Context policy", "上下文策略")}
        eyebrow={copy("Code first, user configurable", "代码优先，用户可配")}
        description={copy("Hard constraints stay in code. This page only adjusts preference, budget, and optional LLM rerank behavior for allowed fragments.", "硬边界仍然由代码控制。这个页面只调整允许片段范围内的偏好、预算和可选的 LLM 辅助重排。")}
        actions={<button type="button" onClick={() => void handleSaveContextPolicy()} style={buttonStyle}>{copy("Save policy", "保存策略")}</button>}
      >
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: "var(--space-3)" }}>
          <label style={{ display: "grid", gap: "var(--space-2)" }}>
            <span>{copy("Default token budget", "默认 Token 预算")}</span>
            <input value={contextTokenBudgetDraft} onChange={(event) => setContextTokenBudgetDraft(event.target.value)} style={inputStyle} />
          </label>
          <label style={{ display: "grid", gap: "var(--space-2)" }}>
            <span>{copy("LLM rerank top K", "LLM 重排 Top K")}</span>
            <input value={contextLlmTopKDraft} onChange={(event) => setContextLlmTopKDraft(event.target.value)} style={inputStyle} />
          </label>
          <label style={{ display: "grid", gap: "var(--space-2)" }}>
            <span>{copy("LLM max boost", "LLM 最大加减分")}</span>
            <input value={contextLlmMaxBoostDraft} onChange={(event) => setContextLlmMaxBoostDraft(event.target.value)} style={inputStyle} />
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", marginTop: "var(--space-6)" }}>
            <input type="checkbox" checked={contextLlmRerankEnabled} onChange={(event) => setContextLlmRerankEnabled(event.target.checked)} />
            <span>{copy("Enable LLM rerank", "启用 LLM 辅助重排")}</span>
          </label>
        </div>
        <label style={{ display: "grid", gap: "var(--space-2)", marginTop: "var(--space-3)" }}>
          <span>{copy("Drop order", "超预算时优先丢弃顺序")}</span>
          <textarea value={contextDropOrderDraft} onChange={(event) => setContextDropOrderDraft(event.target.value)} style={{ ...textAreaStyle, minHeight: "calc(var(--space-12) + var(--space-10) + var(--space-6))" }} />
        </label>
      </Panel>

      <Panel
        title={copy("Lane preference", "Lane 偏好")}
        eyebrow={copy("Per-lane priority", "按 lane 配置优先级")}
        description={copy("Candidate lane and strategy lane can prefer different fragment classes. Hard safety boundaries still remain enforced in code.", "候选人 lane 和策略 lane 可以偏好不同的片段类型，但硬安全边界仍然由代码强制执行。")}
      >
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "var(--space-5)" }}>
          <div style={{ display: "grid", gap: "var(--space-3)" }}>
            <strong>{copy("Candidate lane", "候选人 lane")}</strong>
            <label style={{ display: "grid", gap: "var(--space-2)" }}>
              <span>{copy("Must include", "必须包含")}</span>
              <textarea value={candidateMustIncludeDraft} onChange={(event) => setCandidateMustIncludeDraft(event.target.value)} style={{ ...textAreaStyle, minHeight: "calc(var(--space-12) + var(--space-10) + var(--space-6))" }} />
            </label>
            <label style={{ display: "grid", gap: "var(--space-2)" }}>
              <span>{copy("Default weights JSON", "默认权重 JSON")}</span>
              <textarea value={candidateWeightsDraft} onChange={(event) => setCandidateWeightsDraft(event.target.value)} style={{ ...textAreaStyle, minHeight: "calc(var(--space-12) * 3 + var(--space-10) + var(--space-5) + var(--space-4))" }} />
            </label>
          </div>
          <div style={{ display: "grid", gap: "var(--space-3)" }}>
            <strong>{copy("Strategy lane", "策略 lane")}</strong>
            <label style={{ display: "grid", gap: "var(--space-2)" }}>
              <span>{copy("Must include", "必须包含")}</span>
              <textarea value={agentMustIncludeDraft} onChange={(event) => setAgentMustIncludeDraft(event.target.value)} style={{ ...textAreaStyle, minHeight: "calc(var(--space-12) + var(--space-10) + var(--space-6))" }} />
            </label>
            <label style={{ display: "grid", gap: "var(--space-2)" }}>
              <span>{copy("Default weights JSON", "默认权重 JSON")}</span>
              <textarea value={agentWeightsDraft} onChange={(event) => setAgentWeightsDraft(event.target.value)} style={{ ...textAreaStyle, minHeight: "calc(var(--space-12) * 3 + var(--space-10) + var(--space-5) + var(--space-4))" }} />
            </label>
          </div>
        </div>
      </Panel>

      <Panel
        title={copy("Run type overrides", "按任务类型覆盖")}
        eyebrow={copy("Advanced overrides", "高级覆盖")}
        description={copy("Use this only for task-specific prefer/suppress rules such as outreach, scoring, or resume follow-up.", "这里只用来处理按任务类型的 prefer/suppress 规则，比如外联、评分、催简历。")}
      >
        <label style={{ display: "grid", gap: "var(--space-2)" }}>
          <span>{copy("Run type overrides JSON", "任务类型覆盖 JSON")}</span>
          <textarea value={runTypeOverridesDraft} onChange={(event) => setRunTypeOverridesDraft(event.target.value)} style={{ ...textAreaStyle, minHeight: "calc(var(--space-12) * 3 + var(--space-10) + var(--space-10) + var(--space-5) + var(--space-4))" }} />
        </label>
      </Panel>
    </div>
  );

  const skillContent = (
    <div style={{ display: "grid", gridTemplateColumns: "var(--layout-right-panel-width) minmax(0, 1fr)", gap: "var(--space-5)" }}>
      <Panel title={copy("Skill library", "Skill 库")} eyebrow={copy("Editable items", "可编辑项")} description={copy("Skills remain viewable, editable, and removable. The UI shows a short summary first, then full schemas under details.", "skill 保持可查看、可修改、可删除。界面先展示简短摘要，再在详情中展示完整 schema。")}>
        <div style={{ display: "grid", gap: "var(--space-3)" }}>
          {skills.map((skill) => (
            <button
              key={skill.id}
              type="button"
              onClick={() => setSelectedSkillId(skill.id)}
              style={{
                cursor: "pointer",
                textAlign: "left",
                borderRadius: theme.radius.xl,
                border: `1px solid ${selectedSkillId === skill.id ? theme.colors.accent : theme.colors.border}`,
                background: selectedSkillId === skill.id ? "var(--brand-primary-soft)" : "var(--bg-page)",
                color: theme.colors.text,
                padding: "var(--space-3)",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--space-2)", alignItems: "start" }}>
                <strong>{skill.name}</strong>
                <StatusBadge tone={skill.health === "healthy" ? "positive" : skill.health === "warning" ? "warning" : "critical"}>
                  {skill.status}
                </StatusBadge>
              </div>
              <div style={{ color: theme.colors.muted, fontSize: "var(--font-size-xs)", marginTop: "var(--space-2)" }}>{skill.skillId} · {skill.category ?? "general"} · {skill.riskLevel ?? "medium"}</div>
            </button>
          ))}
        </div>
      </Panel>

      <Panel
        title={selectedSkill?.name ?? copy("Skill detail", "Skill 详情")}
        eyebrow={copy("Progressive disclosure", "渐进式披露")}
        description={selectedSkill?.summary ?? copy("Select a skill to inspect its summary, strategy, and full schema.", "选择一个 skill 查看摘要、策略和完整 schema。")}
        actions={
          selectedSkill ? (
            <div style={{ display: "flex", gap: "var(--space-2)" }}>
              <button type="button" onClick={() => void handleSaveSkill()} style={buttonStyle}>{copy("Save skill", "保存 skill")}</button>
              <button type="button" onClick={() => void onDeleteSkill(selectedSkill.id)} style={dangerButtonStyle}>{copy("Delete", "删除")}</button>
            </div>
          ) : null
        }
      >
        {selectedSkill ? (
          <div style={{ display: "grid", gap: "var(--space-3)" }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: "var(--space-3)" }}>
              <label style={{ display: "grid", gap: "var(--space-2)" }}>
                <span>{copy("Name", "名称")}</span>
                <input value={selectedSkill.name} readOnly style={inputStyle} />
              </label>
              <label style={{ display: "grid", gap: "var(--space-2)" }}>
                <span>{copy("Skill ID", "Skill ID")}</span>
                <input value={selectedSkill.skillId} readOnly style={inputStyle} />
              </label>
              <label style={{ display: "grid", gap: "var(--space-2)" }}>
                <span>{copy("Bound stage", "绑定阶段")}</span>
                <input value={selectedSkill.boundStage} readOnly style={inputStyle} />
              </label>
              <label style={{ display: "grid", gap: "var(--space-2)" }}>
                <span>{copy("Risk", "风险等级")}</span>
                <input value={selectedSkill.riskLevel ?? "medium"} readOnly style={inputStyle} />
              </label>
            </div>
            <label style={{ display: "grid", gap: "var(--space-2)" }}>
              <span>{copy("Operator summary", "操作员摘要")}</span>
              <textarea value={skillDescriptionDraft} onChange={(event) => setSkillDescriptionDraft(event.target.value)} style={{ ...textAreaStyle, minHeight: "calc(var(--space-12) + var(--space-10))" }} />
            </label>
            <label style={{ display: "grid", gap: "var(--space-2)" }}>
              <span>{copy("Strategy JSON", "策略 JSON")}</span>
              <textarea value={skillStrategyDraft} onChange={(event) => setSkillStrategyDraft(event.target.value)} style={textAreaStyle} />
            </label>
            <label style={{ display: "grid", gap: "var(--space-2)" }}>
              <span>{copy("Guidance JSON", "指导 JSON")}</span>
              <textarea value={skillExecutionHintsDraft} onChange={(event) => setSkillExecutionHintsDraft(event.target.value)} style={textAreaStyle} />
            </label>
            <label style={{ display: "grid", gap: "var(--space-2)" }}>
              <span>{copy("Skill metadata JSON", "Skill 元数据 JSON")}</span>
              <textarea value={skillMetadataDraft} onChange={(event) => setSkillMetadataDraft(event.target.value)} style={textAreaStyle} />
            </label>
            <details>
              <summary style={{ cursor: "pointer", color: theme.colors.muted }}>{copy("Show input/output schemas", "查看输入/输出 schema")}</summary>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "var(--space-5)", marginTop: "var(--space-3)" }}>
                <textarea value={skillInputDraft} onChange={(event) => setSkillInputDraft(event.target.value)} style={textAreaStyle} />
                <textarea value={skillOutputDraft} onChange={(event) => setSkillOutputDraft(event.target.value)} style={textAreaStyle} />
              </div>
            </details>
            <details>
              <summary style={{ cursor: "pointer", color: theme.colors.muted }}>{copy("Show health check config", "查看健康检查配置")}</summary>
              <textarea value={skillHealthConfigDraft} onChange={(event) => setSkillHealthConfigDraft(event.target.value)} style={{ ...textAreaStyle, marginTop: "var(--space-3)" }} />
            </details>
          </div>
        ) : (
          <div style={{ color: theme.colors.muted }}>{copy("No skill selected.", "尚未选择 skill。")}</div>
        )}
      </Panel>
    </div>
  );

  return (
    <div style={{ display: "grid", gap: "var(--space-5)", minWidth: 0, background: theme.colors.background, padding: "var(--space-5)", borderRadius: theme.radius.xl }}>
      {errorMessage ? (
        <div
          style={{
            borderRadius: theme.radius.xl,
            border: `1px solid ${theme.colors.critical}`,
            background: "var(--danger-soft)",
            color: theme.colors.critical,
            padding: "var(--space-3) var(--space-4)",
            fontSize: "var(--font-size-sm)",
          }}
        >
          {errorMessage}
        </div>
      ) : null}
      <TopTabPage
        items={[
          { key: "profile", label: copy("Strategy brief", "策略概览") },
          { key: "blueprint", label: copy("Strategy", "策略") },
          { key: "state-machine", label: copy("State machine", "状态机") },
          { key: "context", label: copy("Context", "上下文") },
          { key: "memory", label: copy("Memory", "记忆") },
          { key: "skills", label: copy("Skills", "技能") },
        ]}
        active={tab}
        onChange={(next) => setTab(next as RecruitAgentTab)}
      >
        {tab === "profile" ? profileContent : null}
        {tab === "blueprint" ? blueprintContent : null}
        {tab === "state-machine" ? <StateMachineEditor stateMachine={stateMachine} skills={skills} onSave={onSaveStateMachine} /> : null}
        {tab === "context" ? contextContent : null}
        {tab === "memory" ? memoryContent : null}
        {tab === "skills" ? skillContent : null}
      </TopTabPage>
    </div>
  );
}
