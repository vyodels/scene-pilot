import React, { useEffect, useMemo, useState } from "react";
import { Panel, StatusBadge, Timeline } from "../../components";
import { formatCompactDate } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { theme } from "../../lib/theme";
import { translateUiToken } from "../../lib/uiText";
import type {
  CompileTaskRequest,
  DomainPackRecord,
  RuntimeCapabilityDriver,
  RuntimeEpisode,
  RuntimeEpisodeReplay,
  RuntimeEnvironmentAssessment,
  RuntimeLearningOutcome,
  RuntimePatch,
  RuntimePlanReplanResult,
  RuntimeTaskSpec,
  RuntimeTemplate,
  RuntimeWorkspaceData,
} from "../../lib/types";

interface RuntimeControlViewProps {
  mode:
    | "workflow-create"
    | "workflow-trials"
    | "workflow-versions"
    | "workflow-adjustments"
    | "workflow-scenes";
  data: RuntimeWorkspaceData;
  busy: boolean;
  busyEpisodeId?: string;
  selectedEpisodeId?: string;
  actionPatchId?: string;
  busyPlanId?: string;
  replay?: RuntimeEpisodeReplay | null;
  lastOutcome?: RuntimeLearningOutcome | null;
  lastAssessment?: RuntimeEnvironmentAssessment | null;
  lastReplan?: RuntimePlanReplanResult | null;
  onCompileTask(payload: CompileTaskRequest): Promise<void>;
  onLaunchPlan(planId: string, taskSpecId: string): Promise<void>;
  onCreateTrialRun(taskSpecId: string, executionPlanId: string): Promise<void>;
  onExecuteTrialRun(episodeId: string): Promise<void>;
  onRefreshLearning(episodeId: string): Promise<void>;
  onConfirmTrial(episodeId: string): Promise<void>;
  onInspectEpisode(episodeId: string): void;
  onAssessEnvironment(executionPlanId: string, executionEpisodeId?: string): Promise<void>;
  onReplanPlan(
    executionPlanId: string,
    trigger: string,
    notes?: string,
    preferredCapabilityKeys?: string[],
  ): Promise<void>;
  onApprovePatch(id: string): Promise<void>;
  onRejectPatch(id: string): Promise<void>;
}

const inputShell = {
  width: "100%",
  borderRadius: "14px",
  border: `1px solid ${theme.colors.border}`,
  background: "rgba(255,255,255,0.04)",
  color: theme.colors.text,
  padding: "12px 14px",
} as const;

const actionButtonStyle = {
  border: `1px solid ${theme.colors.border}`,
  borderRadius: theme.radius.md,
  background: theme.colors.accentSoft,
  color: theme.colors.text,
  padding: "10px 12px",
  cursor: "pointer",
  fontWeight: 700,
} as const;

const compactSectionStyle = {
  display: "grid",
  gap: "12px",
  padding: "16px 18px",
  borderRadius: "18px",
  border: "1px solid rgba(255,255,255,0.08)",
  background: "rgba(255,255,255,0.03)",
} as const;

function summarizeJson(value: unknown): string {
  if (value === null || value === undefined) {
    return "None";
  }
  if (typeof value === "string") {
    return value;
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function metricStepCount(episode: RuntimeEpisode): number {
  const value = episode.metrics.stepCount ?? episode.metrics.step_count;
  return typeof value === "number" ? value : episode.actions.length;
}

function toneFromRuntimeStatus(value: string): "positive" | "neutral" | "warning" | "critical" {
  if (/(error|failed|diverg|drift|critical|rejected)/i.test(value)) {
    return "critical";
  }
  if (/(pending|review|await|warning|degraded)/i.test(value)) {
    return "warning";
  }
  if (/(active|ready|success|completed|confirmed|applied|aligned)/i.test(value)) {
    return "positive";
  }
  return "neutral";
}

function extractPlanCapabilities(planBody: { steps: Array<Record<string, unknown>> }): string[] {
  const seen = new Set<string>();
  const values: string[] = [];
  for (const step of planBody.steps) {
    const capability = typeof step.capability === "string" ? step.capability : null;
    if (capability && !seen.has(capability)) {
      seen.add(capability);
      values.push(capability);
    }
  }
  return values;
}

function formatConfidence(value: number): string {
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}

function compactRecordEntries(record: Record<string, unknown>, limit = 6): Array<[string, unknown]> {
  return Object.entries(record).filter(([, value]) => value !== null && value !== undefined).slice(0, limit);
}

function formatRecordSummary(record: Record<string, unknown>, copy: (en: string, zh: string) => string, limit = 6): string {
  return compactRecordEntries(record, limit)
    .map(([key, value]) => {
      const label = translateUiToken(key, copy);
      const normalized =
        typeof value === "string"
          ? translateUiToken(value, copy)
          : typeof value === "boolean"
            ? value
              ? copy("yes", "是")
              : copy("no", "否")
            : summarizeJson(value);
      return `${label}=${normalized}`;
    })
    .join(" · ");
}

function renderEmptyState(title: string, detail: string): JSX.Element {
  return (
    <div
      style={{
        padding: "18px",
        borderRadius: "18px",
        border: "1px solid rgba(255,255,255,0.08)",
        background: "rgba(255,255,255,0.03)",
        display: "grid",
        gap: "8px",
      }}
    >
      <strong>{title}</strong>
      <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>{detail}</div>
    </div>
  );
}

function compilerQualityTone(value: string | null): "positive" | "neutral" | "warning" | "critical" {
  if (value === "accepted" || value === "high") {
    return "positive";
  }
  if (value === "guardrailed" || value === "medium") {
    return "warning";
  }
  if (value === "fallback" || value === "low") {
    return "critical";
  }
  return "neutral";
}

function compiledQualitySummary(task: RuntimeTaskSpec): {
  source: string | null;
  qualityBand: string | null;
  warnings: string[];
  repairApplied: boolean;
} {
  const payload = task.compiledPayload ?? {};
  const quality = typeof payload.compiler_quality === "object" && payload.compiler_quality !== null
    ? (payload.compiler_quality as Record<string, unknown>)
    : {};
  return {
    source: typeof payload.compiler_source === "string" ? payload.compiler_source : typeof payload.compiler === "string" ? payload.compiler : null,
    qualityBand:
      typeof quality.quality_status === "string"
        ? quality.quality_status
        : typeof quality.quality_band === "string"
          ? quality.quality_band
          : typeof payload.quality_status === "string"
            ? String(payload.quality_status)
            : typeof payload.quality_band === "string"
              ? String(payload.quality_band)
              : null,
    warnings: Array.isArray(quality.warnings) ? quality.warnings.map(String) : [],
    repairApplied:
      typeof quality.repair_count === "number"
        ? Number(quality.repair_count) > 0
        : typeof payload.repair_count === "number"
          ? Number(payload.repair_count) > 0
          : Boolean(quality.repair_applied ?? payload.repair_applied ?? false),
  };
}

export function RuntimeControlView({
  mode,
  data,
  busy,
  busyEpisodeId,
  selectedEpisodeId,
  actionPatchId,
  busyPlanId,
  replay,
  lastOutcome,
  lastAssessment,
  lastReplan,
  onCompileTask,
  onLaunchPlan,
  onCreateTrialRun,
  onExecuteTrialRun,
  onRefreshLearning,
  onConfirmTrial,
  onInspectEpisode,
  onAssessEnvironment,
  onReplanPlan,
  onApprovePatch,
  onRejectPatch,
}: RuntimeControlViewProps): JSX.Element {
  const { copy } = useI18n();
  const [instruction, setInstruction] = useState("打开网站，给我按照要求找到候选人，拿到简历，上传内网，评分。");
  const [domainHint, setDomainHint] = useState("");
  const [replanPlanId, setReplanPlanId] = useState(data.plans[0]?.id ?? "");
  const [replanTrigger, setReplanTrigger] = useState("scene_drift");
  const [replanNotes, setReplanNotes] = useState("");
  const [selectedCapabilityKeys, setSelectedCapabilityKeys] = useState<string[]>([]);

  const taskById = useMemo(() => new Map(data.taskSpecs.map((item) => [item.id, item])), [data.taskSpecs]);
  const planById = useMemo(() => new Map(data.plans.map((item) => [item.id, item])), [data.plans]);
  const combinedReplans = useMemo(
    () => (lastReplan ? [lastReplan, ...data.replans.filter((item) => item.id !== lastReplan.id)] : data.replans),
    [data.replans, lastReplan],
  );
  const selectedPlan = useMemo(() => planById.get(replanPlanId) ?? data.plans[0] ?? null, [data.plans, planById, replanPlanId]);
  const selectedAssessment = useMemo(
    () =>
      (lastAssessment && (!selectedPlan || lastAssessment.executionPlanId === selectedPlan.id || lastAssessment.taskSpecId === selectedPlan.taskSpecId)
        ? lastAssessment
        : selectedPlan
        ? data.environmentAssessments.find(
            (assessment) =>
              assessment.executionPlanId === selectedPlan.id ||
              assessment.taskSpecId === selectedPlan.taskSpecId ||
              assessment.environmentKey === String(selectedPlan.environmentRequirements.environmentKey ?? ""),
          )
        : null) ?? data.environmentAssessments[0] ?? null,
    [data.environmentAssessments, lastAssessment, selectedPlan],
  );
  const highlightedDriverKeys = useMemo(
    () => new Set(selectedAssessment?.capabilityKeys ?? extractPlanCapabilities(selectedPlan?.planBody ?? { steps: [] })),
    [selectedAssessment, selectedPlan],
  );

  useEffect(() => {
    if (!selectedPlan && !replanPlanId) {
      return;
    }
    if (!selectedPlan || !data.plans.some((plan) => plan.id === replanPlanId)) {
      setReplanPlanId(data.plans[0]?.id ?? "");
    }
  }, [data.plans, replanPlanId, selectedPlan]);

  useEffect(() => {
    if (!selectedAssessment) {
      setSelectedCapabilityKeys([]);
      return;
    }
    setSelectedCapabilityKeys(selectedAssessment.capabilityKeys);
  }, [selectedAssessment?.id]);

  const renderTaskCards = (): JSX.Element => (
    <div style={{ display: "grid", gap: "14px" }}>
      {data.taskSpecs.map((task) => {
        const linkedPlan = data.plans.find((plan) => plan.taskSpecId === task.id);
        return (
          <article
            key={task.id}
            style={{
              padding: "16px",
              borderRadius: "18px",
              border: "1px solid rgba(255,255,255,0.08)",
              background: "rgba(255,255,255,0.03)",
              display: "grid",
              gap: "10px",
            }}
          >
            <div style={{ display: "flex", alignItems: "start", justifyContent: "space-between", gap: "12px", flexWrap: "wrap" }}>
              <div>
                <strong style={{ fontSize: "16px" }}>{task.title}</strong>
                <div style={{ color: theme.colors.muted, fontSize: "13px", marginTop: "6px" }}>{task.goal}</div>
              </div>
              <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                <StatusBadge tone="neutral">{translateUiToken(task.domain, copy)}</StatusBadge>
                <StatusBadge tone={task.status.includes("ready") ? "positive" : "warning"}>{translateUiToken(task.status, copy)}</StatusBadge>
              </div>
            </div>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              {task.preferredCapabilities.map((capability) => (
                <StatusBadge key={`${task.id}-${capability}`} tone="neutral">
                  {translateUiToken(capability, copy)}
                </StatusBadge>
              ))}
              {compiledQualitySummary(task).source ? <StatusBadge tone="neutral">{copy(`compiler ${compiledQualitySummary(task).source}`, `编译器 ${translateUiToken(String(compiledQualitySummary(task).source), copy)}`)}</StatusBadge> : null}
              {compiledQualitySummary(task).qualityBand ? (
                <StatusBadge tone={compilerQualityTone(compiledQualitySummary(task).qualityBand)}>
                  {copy(`quality ${compiledQualitySummary(task).qualityBand}`, `质量 ${translateUiToken(String(compiledQualitySummary(task).qualityBand), copy)}`)}
                </StatusBadge>
              ) : null}
              {compiledQualitySummary(task).repairApplied ? <StatusBadge tone="warning">{copy("repair applied", "已应用修复")}</StatusBadge> : null}
            </div>
            {compactRecordEntries(task.outputContract, 4).length ? (
              <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                  {copy("Output contract", "输出约定")}:{" "}
                {formatRecordSummary(task.outputContract, copy, 4)}
              </div>
            ) : null}
            {compiledQualitySummary(task).warnings.length ? (
              <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                {copy("Compiler warnings", "编译警告")}: {compiledQualitySummary(task).warnings.join(" · ")}
              </div>
            ) : null}
            {linkedPlan ? (
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "10px", flexWrap: "wrap" }}>
                <div style={{ color: theme.colors.muted, fontSize: "13px" }}>
                {copy("Linked plan", "关联计划")}: <strong style={{ color: theme.colors.text }}>{linkedPlan.name}</strong>
              </div>
              <button
                type="button"
                onClick={() => void onCreateTrialRun(task.id, linkedPlan.id)}
                disabled={busy}
                style={actionButtonStyle}
              >
                {copy("Create trial", "创建试跑")}
              </button>
              </div>
            ) : null}
          </article>
        );
      })}
    </div>
  );

  const renderPlanCards = (): JSX.Element => (
    <div style={{ display: "grid", gap: "14px" }}>
      {data.plans.map((plan) => {
        const isSelected = selectedPlan?.id === plan.id;
        const capabilities = extractPlanCapabilities(plan.planBody);
        const linkedAssessment = data.environmentAssessments.find(
          (assessment) => assessment.executionPlanId === plan.id || assessment.taskSpecId === plan.taskSpecId,
        );
        return (
          <article
            key={plan.id}
            style={{
              padding: "16px",
              borderRadius: "18px",
              border: isSelected ? "1px solid rgba(122,167,255,0.42)" : "1px solid rgba(255,255,255,0.08)",
              background: isSelected ? "rgba(122,167,255,0.08)" : "rgba(255,255,255,0.03)",
              display: "grid",
              gap: "10px",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", alignItems: "start", flexWrap: "wrap" }}>
              <div>
                <strong>{plan.name}</strong>
                <div style={{ color: theme.colors.muted, fontSize: "13px", marginTop: "6px", lineHeight: 1.6 }}>
                {copy(
                  `Mode ${plan.mode} · Approval ${plan.approvalState} · v${plan.version}`,
                  `模式 ${translateUiToken(plan.mode, copy)} · 审批 ${translateUiToken(plan.approvalState, copy)} · v${plan.version}`,
                )}
                </div>
              </div>
              <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                <StatusBadge tone={toneFromRuntimeStatus(plan.status)}>{translateUiToken(plan.status, copy)}</StatusBadge>
                {linkedAssessment ? (
                  <StatusBadge tone={toneFromRuntimeStatus(linkedAssessment.status)}>{translateUiToken(linkedAssessment.sceneType, copy)}</StatusBadge>
                ) : null}
              </div>
            </div>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              <StatusBadge tone="neutral">{copy(`${plan.planBody.steps.length} steps`, `${plan.planBody.steps.length} 步`)}</StatusBadge>
              {capabilities.map((capability) => (
                <StatusBadge key={`${plan.id}-${capability}`} tone="neutral">
                  {translateUiToken(capability, copy)}
                </StatusBadge>
              ))}
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", gap: "10px", alignItems: "center", flexWrap: "wrap" }}>
              <div style={{ color: theme.colors.muted, fontSize: "13px" }}>
                {linkedAssessment
                  ? copy(`${linkedAssessment.sceneLabel} · confidence ${formatConfidence(linkedAssessment.confidence)}`, `${linkedAssessment.sceneLabel} · 置信度 ${formatConfidence(linkedAssessment.confidence)}`)
                  : copy("No scene assessment recorded yet.", "尚未记录场景评估。")}
              </div>
              <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                <button
                  type="button"
                  onClick={() => void onLaunchPlan(plan.id, plan.taskSpecId)}
                  disabled={busy || busyPlanId === plan.id}
                  style={{ ...actionButtonStyle, background: "rgba(93,216,163,0.12)" }}
                >
                  {busyPlanId === plan.id ? copy("Queueing...", "入队中...") : copy("Launch workflow", "启动工作流")}
                </button>
                <button
                  type="button"
                  onClick={() => setReplanPlanId(plan.id)}
                  style={{ ...actionButtonStyle, background: isSelected ? "rgba(122,167,255,0.24)" : actionButtonStyle.background }}
                >
                    {isSelected ? copy("Selected for replan", "已选为重规划目标") : copy("Use for replan", "作为重规划目标")}
                </button>
              </div>
            </div>
          </article>
        );
      })}
    </div>
  );

  const renderEpisodeCards = (episodes: RuntimeEpisode[]): JSX.Element => (
    <div style={{ display: "grid", gap: "14px" }}>
      {episodes.length === 0 ? renderEmptyState(copy("No workflow instances yet", "还没有工作流实例"), copy("Create and execute a trial first. The selected workflow instance will appear here after it starts producing evidence.", "先创建并执行一次试跑。工作流实例开始产生证据后，会显示在这里。")) : null}
      {episodes.map((episode) => {
        const plan = planById.get(episode.executionPlanId);
        const task = taskById.get(episode.taskSpecId);
        const isSelected = selectedEpisodeId === episode.id;
        return (
          <article
            key={episode.id}
            style={{
              padding: "16px",
              borderRadius: "18px",
              border: isSelected ? "1px solid rgba(122,167,255,0.42)" : "1px solid rgba(255,255,255,0.08)",
              background: isSelected ? "rgba(122,167,255,0.08)" : "rgba(255,255,255,0.03)",
              display: "grid",
              gap: "10px",
            }}
          >
            <div style={{ display: "flex", alignItems: "start", justifyContent: "space-between", gap: "12px", flexWrap: "wrap" }}>
              <div>
                <strong>{task?.title ?? episode.id}</strong>
                <div style={{ color: theme.colors.muted, fontSize: "13px", marginTop: "6px" }}>
                  {plan?.name ?? copy("Unlinked plan", "未关联计划")} · {translateUiToken(episode.mode, copy)}
                </div>
              </div>
              <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                <StatusBadge tone={episode.divergenceDetected ? "critical" : "positive"}>
                  {episode.divergenceDetected ? copy("diverged", "已偏离") : translateUiToken(episode.status, copy)}
                </StatusBadge>
                <StatusBadge tone="neutral">{copy(`${metricStepCount(episode)} steps`, `${metricStepCount(episode)} 步`)}</StatusBadge>
              </div>
            </div>
            <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                  {episode.resultSummary ?? copy("No trial summary recorded yet.", "尚未记录试跑摘要。")}
            </div>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              <StatusBadge tone="neutral">
                  {episode.requiresConfirmation ? copy("awaiting confirmation", "等待确认") : copy("confirmed or not gated", "已确认或无需额外审批")}
              </StatusBadge>
              {episode.finishedAt ? <StatusBadge tone="neutral">{copy(`Finished ${formatCompactDate(episode.finishedAt)}`, `完成于 ${formatCompactDate(episode.finishedAt)}`)}</StatusBadge> : null}
            </div>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "10px", flexWrap: "wrap" }}>
              <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                <button
                  type="button"
                  onClick={() => onInspectEpisode(episode.id)}
                  disabled={busy}
                  style={{ ...actionButtonStyle, background: isSelected ? "rgba(122,167,255,0.24)" : actionButtonStyle.background }}
                >
                  {isSelected ? copy("Diagnostics selected", "已选诊断") : copy("Inspect instance", "查看实例")}
                </button>
                <button
                  type="button"
                  onClick={() => void onRefreshLearning(episode.id)}
                  disabled={busy || busyEpisodeId === episode.id}
                  style={{ ...actionButtonStyle, background: "rgba(93,216,163,0.12)" }}
                >
                  {busyEpisodeId === episode.id ? copy("Refreshing...", "刷新中...") : copy("Refresh learning", "刷新学习结果")}
                </button>
                {episode.status === "pending" ? (
                  <button
                    type="button"
                    onClick={() => void onExecuteTrialRun(episode.id)}
                    disabled={busy || busyEpisodeId === episode.id}
                    style={actionButtonStyle}
                  >
                    {busyEpisodeId === episode.id ? copy("Executing...", "执行中...") : copy("Execute trial", "执行试跑")}
                  </button>
                ) : null}
                {episode.requiresConfirmation || episode.status === "awaiting_review" ? (
                  <button
                    type="button"
                    onClick={() => void onConfirmTrial(episode.id)}
                    disabled={busy || busyEpisodeId === episode.id}
                    style={{ ...actionButtonStyle, background: "rgba(93,216,163,0.18)" }}
                  >
                    {busyEpisodeId === episode.id ? copy("Confirming...", "确认中...") : copy("Confirm trial", "确认试跑")}
                  </button>
                ) : null}
              </div>
            </div>
          </article>
        );
      })}
    </div>
  );

  const renderTemplateCards = (templates: RuntimeTemplate[]): JSX.Element => (
    <div style={{ display: "grid", gap: "14px" }}>
      {templates.length === 0 ? renderEmptyState(copy("No workflow versions yet", "还没有工作流版本"), copy("Published or reusable versions will appear here after supervised trials are confirmed.", "受监督试跑确认后，可发布或可复用的工作流版本会显示在这里。")) : null}
      {templates.map((template) => (
        <article
          key={template.id}
          style={{
            padding: "16px",
            borderRadius: "18px",
            border: "1px solid rgba(255,255,255,0.08)",
            background: "rgba(255,255,255,0.03)",
            display: "grid",
            gap: "10px",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", flexWrap: "wrap" }}>
            <div>
              <strong>{template.name}</strong>
              <div style={{ color: theme.colors.muted, fontSize: "13px", marginTop: "6px" }}>{template.validationSummary ?? copy("No validation summary yet.", "暂无验证摘要。")}</div>
            </div>
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
            <StatusBadge tone="neutral">{translateUiToken(template.domain, copy)}</StatusBadge>
            <StatusBadge tone={template.status === "active" ? "positive" : "warning"}>{translateUiToken(template.status, copy)}</StatusBadge>
            {typeof template.activationStrategy.governance === "object" && template.activationStrategy.governance !== null ? (
              <StatusBadge tone="neutral">
                {copy(`governance ${String((template.activationStrategy.governance as Record<string, unknown>).episode_quality_band ?? "tracked")}`, `治理 ${translateUiToken(String((template.activationStrategy.governance as Record<string, unknown>).episode_quality_band ?? "tracked"), copy)}`)}
              </StatusBadge>
            ) : null}
          </div>
          </div>
          <div style={{ color: theme.colors.muted, fontSize: "13px" }}>
                {copy(`${Array.isArray(template.templateBody.steps) ? (template.templateBody.steps as unknown[]).length : 0} planned steps · v${template.version}`, `${Array.isArray(template.templateBody.steps) ? (template.templateBody.steps as unknown[]).length : 0} 个计划步骤 · v${template.version}`)}
          </div>
          {typeof template.activationStrategy.governance === "object" && template.activationStrategy.governance !== null ? (
            <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
              {copy("Governance", "治理")}:{" "}
              {formatRecordSummary(template.activationStrategy.governance as Record<string, unknown>, copy, 4)}
              </div>
            ) : null}
        </article>
      ))}
    </div>
  );

  const renderPatchCards = (patches: RuntimePatch[]): JSX.Element => (
    <div style={{ display: "grid", gap: "14px" }}>
      {patches.length === 0 ? renderEmptyState(copy("No revision suggestions yet", "还没有修订建议"), copy("When runtime drift or supervised execution divergence is detected, revision suggestions will appear here for review.", "检测到运行时漂移或受监督执行偏差后，修订建议会出现在这里供审查。")) : null}
      {patches.map((patch) => (
        <article
          key={patch.id}
          style={{
            padding: "16px",
            borderRadius: "18px",
            border: "1px solid rgba(255,255,255,0.08)",
            background: "rgba(255,255,255,0.03)",
            display: "grid",
            gap: "10px",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", flexWrap: "wrap" }}>
            <div>
              <strong>{patch.title}</strong>
              <div style={{ color: theme.colors.muted, fontSize: "13px", marginTop: "6px" }}>
                {patch.divergenceSummary ?? patch.rationale ?? copy("No rationale supplied.", "未提供修订原因。")}
              </div>
            </div>
            <StatusBadge tone={patch.status === "pending_review" ? "warning" : patch.status === "applied" ? "positive" : "neutral"}>
              {translateUiToken(patch.status, copy)}
            </StatusBadge>
          </div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "10px", flexWrap: "wrap" }}>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                <StatusBadge tone="neutral">{translateUiToken(patch.patchKind, copy)}</StatusBadge>
              {patch.templateId ? <StatusBadge tone="neutral">{copy("version linked", "已关联工作流版本")}</StatusBadge> : null}
              {patch.runtimeMetadata.episode_quality_band ? (
                <StatusBadge tone={String(patch.runtimeMetadata.episode_quality_band) === "high" ? "positive" : "warning"}>
                  {copy(`quality ${String(patch.runtimeMetadata.episode_quality_band)}`, `质量 ${translateUiToken(String(patch.runtimeMetadata.episode_quality_band), copy)}`)}
                </StatusBadge>
              ) : null}
            </div>
            {patch.status === "pending_review" ? (
              <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                <button
                  type="button"
                  onClick={() => void onApprovePatch(patch.id)}
                  disabled={busy || actionPatchId === patch.id}
                  style={actionButtonStyle}
                >
                {copy("Approve proposal", "批准提案")}
                </button>
                <button
                  type="button"
                  onClick={() => void onRejectPatch(patch.id)}
                  disabled={busy || actionPatchId === patch.id}
                  style={{ ...actionButtonStyle, background: "rgba(255,128,128,0.12)" }}
                >
                  {copy("Reject proposal", "拒绝提案")}
                </button>
              </div>
            ) : null}
          </div>
          {compactRecordEntries(patch.runtimeMetadata, 5).length ? (
            <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
              {copy("Metadata", "元数据")}:{" "}
              {formatRecordSummary(patch.runtimeMetadata, copy, 5)}
            </div>
          ) : null}
        </article>
      ))}
    </div>
  );

  const renderDomainCards = (domains: DomainPackRecord[]): JSX.Element => (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "14px" }}>
      {domains.length === 0 ? renderEmptyState(copy("No scene profiles yet", "还没有场景画像"), copy("Reusable scene profiles will appear here after they are created or learned from workflow execution.", "创建或从工作流执行中学习出的可复用场景画像，会显示在这里。")) : null}
      {domains.map((domain) => (
        <article
          key={domain.key}
          style={{
            padding: "16px",
            borderRadius: "18px",
            border: "1px solid rgba(255,255,255,0.08)",
            background: "rgba(255,255,255,0.03)",
            display: "grid",
            gap: "10px",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", alignItems: "start" }}>
            <div>
              <strong>{domain.name}</strong>
              <div style={{ color: theme.colors.muted, fontSize: "13px", marginTop: "6px", lineHeight: 1.5 }}>{domain.description}</div>
            </div>
            <StatusBadge tone="neutral">{translateUiToken(domain.key, copy)}</StatusBadge>
          </div>
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
            <StatusBadge tone={domain.maturity === "beta" ? "positive" : domain.maturity === "stable" ? "positive" : "warning"}>
              {translateUiToken(domain.maturity, copy)}
            </StatusBadge>
            <StatusBadge tone="neutral">v{domain.version}</StatusBadge>
            <StatusBadge tone="neutral">{domain.runtimeOnly ? copy("runtime only", "仅运行时") : copy("packaged", "已打包")}</StatusBadge>
            <StatusBadge tone="neutral">
              {copy(`${domain.activeTemplateCount}/${domain.templateCount || domain.templateKeys.length} active versions`, `${domain.activeTemplateCount}/${domain.templateCount || domain.templateKeys.length} 个活动版本`)}
            </StatusBadge>
            {domain.defaultCapabilities.map((capability) => (
              <StatusBadge key={`${domain.key}-${capability}`} tone="neutral">
                {translateUiToken(capability, copy)}
              </StatusBadge>
            ))}
          </div>
          {domain.compilerHints.length ? (
            <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
              {copy("Compiler hints", "编译提示")}: {domain.compilerHints.join(" · ")}
            </div>
          ) : null}
          {domain.sceneExpectations.length ? (
            <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
              {copy("Scene expectations", "场景预期")}: {domain.sceneExpectations.join(" · ")}
            </div>
          ) : null}
          {compactRecordEntries(domain.trialExpectations, 4).length ? (
            <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
              {copy("Trial expectations", "试跑预期")}:{" "}
              {formatRecordSummary(domain.trialExpectations, copy, 4)}
            </div>
          ) : null}
          {compactRecordEntries(domain.qualityGates, 4).length ? (
            <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
              {copy("Quality gates", "质量门槛")}:{" "}
              {formatRecordSummary(domain.qualityGates, copy, 4)}
            </div>
          ) : null}
          {domain.sampleTasks.length ? (
            <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
              {copy("Example workflow", "示例工作流")}: {domain.sampleTasks[0]}
            </div>
          ) : null}
        </article>
      ))}
    </div>
  );

  const renderCapabilityDrivers = (drivers: RuntimeCapabilityDriver[]): JSX.Element => (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: "14px" }}>
      {drivers.map((driver) => {
        const highlighted = highlightedDriverKeys.has(driver.key);
        return (
          <article
            key={driver.id}
            style={{
              padding: "16px",
              borderRadius: "18px",
              border: highlighted ? "1px solid rgba(122,167,255,0.34)" : "1px solid rgba(255,255,255,0.08)",
              background: highlighted ? "rgba(122,167,255,0.08)" : "rgba(255,255,255,0.03)",
              display: "grid",
              gap: "10px",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", gap: "10px", flexWrap: "wrap" }}>
              <div>
                <strong>{driver.name}</strong>
                <div style={{ color: theme.colors.muted, fontSize: "13px", marginTop: "6px" }}>{driver.scope}</div>
              </div>
              <StatusBadge tone={toneFromRuntimeStatus(driver.status)}>{translateUiToken(driver.status, copy)}</StatusBadge>
            </div>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              <StatusBadge tone="neutral">{translateUiToken(driver.category, copy)}</StatusBadge>
              <StatusBadge tone="neutral">{translateUiToken(driver.safetyMode, copy)}</StatusBadge>
              <StatusBadge tone={driver.supportsWrite ? "warning" : "neutral"}>
                {driver.supportsWrite ? copy("write-enabled", "可写") : copy("read-only", "只读")}
              </StatusBadge>
            </div>
            <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>{driver.description}</div>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              {driver.sceneTypes.slice(0, 3).map((scene) => (
                <StatusBadge key={`${driver.id}-${scene}`} tone="neutral">
                  {translateUiToken(scene, copy)}
                </StatusBadge>
              ))}
            </div>
          </article>
        );
      })}
    </div>
  );

  const renderEnvironmentAssessments = (assessments: RuntimeEnvironmentAssessment[]): JSX.Element => (
    !assessments.length ? (
      <div style={{ color: theme.colors.muted }}>{copy("No live assessments yet. Refresh the selected scene to evaluate the current environment.", "暂无实时评估。请刷新所选场景以评估当前环境。")}</div>
    ) : (
    <div style={{ display: "grid", gap: "14px" }}>
      {assessments.map((assessment) => {
        const isSelected = selectedAssessment?.id === assessment.id;
        return (
          <article
            key={assessment.id}
            style={{
              padding: "16px",
              borderRadius: "18px",
              border: isSelected ? "1px solid rgba(122,167,255,0.42)" : "1px solid rgba(255,255,255,0.08)",
              background: isSelected ? "rgba(122,167,255,0.08)" : "rgba(255,255,255,0.03)",
              display: "grid",
              gap: "10px",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", gap: "10px", flexWrap: "wrap", alignItems: "start" }}>
              <div>
                <strong>{assessment.sceneLabel}</strong>
                <div style={{ color: theme.colors.muted, fontSize: "13px", marginTop: "6px" }}>{assessment.summary}</div>
              </div>
              <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                <StatusBadge tone={toneFromRuntimeStatus(assessment.status)}>{translateUiToken(assessment.status, copy)}</StatusBadge>
                <StatusBadge tone="neutral">{formatConfidence(assessment.confidence)}</StatusBadge>
              </div>
            </div>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              <StatusBadge tone="neutral">{assessment.environmentKey}</StatusBadge>
              <StatusBadge tone="neutral">{translateUiToken(assessment.sceneType, copy)}</StatusBadge>
              <StatusBadge tone="neutral">{translateUiToken(assessment.sceneProfile.interactionMode, copy)}</StatusBadge>
              <StatusBadge tone={assessment.plannerGuidance.requiresHumanReview ? "warning" : "neutral"}>
                {copy(`planner ${assessment.plannerGuidance.posture}`, `规划器 ${translateUiToken(assessment.plannerGuidance.posture, copy)}`)}
              </StatusBadge>
            </div>
            {assessment.driftSignals.length ? (
              <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                {copy("Drift", "漂移")}: {assessment.driftSignals.join(" · ")}
              </div>
            ) : (
              <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                {copy("Scene is aligned with the current execution model.", "当前场景与执行模型保持一致。")}
              </div>
            )}
            <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
              {copy(
                `Auth ${assessment.sceneProfile.authState} · ${assessment.sceneProfile.entityCount} entities · ${assessment.sceneProfile.affordanceCount} affordances`,
                `认证 ${translateUiToken(assessment.sceneProfile.authState, copy)} · ${assessment.sceneProfile.entityCount} 个实体 · ${assessment.sceneProfile.affordanceCount} 个可执行动作`,
              )}
            </div>
            {assessment.sceneProfile.primaryTargets.length ? (
              <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                {copy("Targets", "目标")}: {assessment.sceneProfile.primaryTargets.join(" · ")}
              </div>
            ) : null}
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              {assessment.capabilityKeys.map((capability) => (
                <StatusBadge key={`${assessment.id}-${capability}`} tone="neutral">
                  {translateUiToken(capability, copy)}
                </StatusBadge>
              ))}
              {assessment.plannerGuidance.insertedCapabilities.map((capability) => (
                <StatusBadge key={`${assessment.id}-inserted-${capability}`} tone="warning">
                  {copy(`next ${capability}`, `下一步 ${translateUiToken(capability, copy)}`)}
                </StatusBadge>
              ))}
            </div>
            {assessment.plannerGuidance.preferredNextActions.length ? (
              <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                {copy("Next", "下一步")}: {assessment.plannerGuidance.preferredNextActions.join(" · ")}
              </div>
            ) : null}
          </article>
        );
      })}
    </div>
    )
  );

  const renderReplanCards = (replans: RuntimePlanReplanResult[]): JSX.Element => (
    !replans.length ? (
      <div style={{ color: theme.colors.muted }}>{copy("No replans recorded yet. Generate a revision from the current scene assessment.", "尚未记录重规划结果。请基于当前场景评估生成一次修订。")}</div>
    ) : (
    <div style={{ display: "grid", gap: "14px" }}>
      {replans.map((replan) => (
        <article
          key={replan.id}
          style={{
            padding: "16px",
            borderRadius: "18px",
            border: lastReplan?.id === replan.id ? "1px solid rgba(122,167,255,0.42)" : "1px solid rgba(255,255,255,0.08)",
            background: lastReplan?.id === replan.id ? "rgba(122,167,255,0.08)" : "rgba(255,255,255,0.03)",
            display: "grid",
            gap: "10px",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", gap: "10px", alignItems: "start", flexWrap: "wrap" }}>
            <div>
              <strong>{replan.executionPlan.name}</strong>
              <div style={{ color: theme.colors.muted, fontSize: "13px", marginTop: "6px", lineHeight: 1.6 }}>{replan.summary}</div>
            </div>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              <StatusBadge tone={toneFromRuntimeStatus(replan.status)}>{translateUiToken(replan.status, copy)}</StatusBadge>
              <StatusBadge tone="neutral">{translateUiToken(replan.trigger, copy)}</StatusBadge>
            </div>
          </div>
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
            <StatusBadge tone="neutral">{copy(`${replan.executionPlan.planBody.steps.length} steps`, `${replan.executionPlan.planBody.steps.length} 步`)}</StatusBadge>
            {replan.recommendedCapabilityKeys.map((capability) => (
              <StatusBadge key={`${replan.id}-${capability}`} tone="neutral">
                {translateUiToken(capability, copy)}
              </StatusBadge>
            ))}
          </div>
          <div style={{ color: theme.colors.muted, fontSize: "13px" }}>
            {copy(`Created ${formatCompactDate(replan.createdAt)}`, `创建于 ${formatCompactDate(replan.createdAt)}`)}
            {replan.environmentAssessment ? copy(` · Scene ${replan.environmentAssessment.sceneType}`, ` · 场景 ${translateUiToken(replan.environmentAssessment.sceneType, copy)}`) : ""}
          </div>
          {replan.compilerNotes.length ? (
            <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
              {copy("Compiler notes", "编译说明")}: {replan.compilerNotes.join(" · ")}
            </div>
          ) : null}
          {replan.auditMetadata && compactRecordEntries(replan.auditMetadata, 4).length ? (
            <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
              {copy("Audit", "审计")}:{" "}
              {formatRecordSummary(replan.auditMetadata, copy, 4)}
            </div>
          ) : null}
        </article>
      ))}
    </div>
    )
  );

  const toggleCapabilityKey = (key: string) => {
    setSelectedCapabilityKeys((current) => (current.includes(key) ? current.filter((value) => value !== key) : [...current, key]));
  };

  if (mode === "workflow-trials") {
    return (
      <div style={{ display: "grid", gap: "14px" }}>
        {renderEpisodeCards(data.episodes)}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: "18px", alignItems: "start" }}>
          <Panel title={copy("Selected replay diagnostics", "已选回放诊断")} eyebrow={copy("Workflow instance replay", "工作流实例回放")} description={copy("The currently selected trial run with snapshots, timeline, and derived artifacts.", "当前选中的试跑结果，包含快照、时间线和衍生产物。")}>
            {replay ? (
              <div style={{ display: "grid", gap: "14px" }}>
                <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                  <StatusBadge tone={replay.episode.divergenceDetected ? "critical" : "positive"}>{translateUiToken(replay.episode.status, copy)}</StatusBadge>
                  {replay.template ? <StatusBadge tone="positive">{copy("version candidate", "版本候选")}</StatusBadge> : null}
                  {replay.patch ? <StatusBadge tone="warning">{copy("revision candidate", "修订建议候选项")}</StatusBadge> : null}
                  {replay.approval ? <StatusBadge tone="warning">{copy("approval pending", "审批待处理")}</StatusBadge> : null}
                </div>
                <div style={{ color: theme.colors.muted, lineHeight: 1.6 }}>
                  {replay.episode.resultSummary ?? copy("No replay summary available.", "暂无回放摘要。")}
                </div>
                <Timeline events={replay.diagnostics} />
              </div>
            ) : (
                <div style={{ color: theme.colors.muted }}>{copy("Select a workflow instance to inspect diagnostics.", "选择一个工作流实例以查看诊断。")}</div>
            )}
          </Panel>
          <Panel title={copy("Replay Context", "回放上下文")} eyebrow={copy("Snapshots and Notes", "快照与备注")} description={copy("Observed environment state and machine-readable artifacts recorded for the selected replay.", "为所选回放记录的环境状态与机器可读产物。")}>
            {replay ? (
              <div style={{ display: "grid", gap: "14px" }}>
                <div style={{ display: "grid", gap: "8px" }}>
                  {(replay.snapshots.length ? replay.snapshots : data.snapshots.filter((snapshot) => snapshot.executionEpisodeId === replay.episode.id)).map((snapshot) => (
                    <article
                      key={snapshot.id}
                      style={{ padding: "14px", borderRadius: "16px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", gap: "10px", flexWrap: "wrap" }}>
                        <strong>{snapshot.title ?? snapshot.environmentKey ?? snapshot.id}</strong>
                        <StatusBadge tone="neutral">{snapshot.pageType ?? snapshot.source}</StatusBadge>
                      </div>
                      <div style={{ color: theme.colors.muted, fontSize: "13px", marginTop: "8px" }}>{snapshot.url ?? copy("No URL captured.", "未捕获 URL。")}</div>
                    </article>
                  ))}
                </div>
                {replay.notes.length ? (
                  <div style={{ display: "grid", gap: "8px" }}>
                    {replay.notes.map((note, index) => (
                      <div key={`${replay.episode.id}-note-${index}`} style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                        {note}
                      </div>
                    ))}
                  </div>
                ) : null}
                <pre
                  style={{
                    margin: 0,
                    padding: "14px",
                    borderRadius: "16px",
                    background: "rgba(255,255,255,0.03)",
                    border: "1px solid rgba(255,255,255,0.08)",
                    color: theme.colors.muted,
                    fontSize: "12px",
                    overflowX: "auto",
                  }}
                >
                  {summarizeJson({
                    task: replay.taskSpec?.title ?? replay.episode.taskSpecId,
                    plan: replay.executionPlan?.name ?? replay.episode.executionPlanId,
                    patch: replay.patch?.title ?? null,
                    template: replay.template?.name ?? null,
                  })}
                </pre>
              </div>
            ) : (
              <div style={{ color: theme.colors.muted }}>{copy("Replay context will appear after selecting a workflow instance.", "选择工作流实例后，这里会显示回放上下文。")}</div>
            )}
          </Panel>
        </div>
      </div>
    );
  }

  if (mode === "workflow-versions") {
    return (
      <div style={{ display: "grid", gap: "14px" }}>
        {renderTemplateCards(data.templates)}
      </div>
    );
  }

  if (mode === "workflow-adjustments") {
    return (
      <div style={{ display: "grid", gap: "14px" }}>
        {renderPatchCards(data.patches)}
      </div>
    );
  }

  if (mode === "workflow-scenes") {
    return (
      <div style={{ display: "grid", gap: "14px" }}>
        {renderDomainCards(data.domainPacks)}
      </div>
    );
  }

  return (
    <div style={{ display: "grid", gap: "14px" }}>
      <section style={compactSectionStyle}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", alignItems: "start", flexWrap: "wrap" }}>
          <div style={{ color: theme.colors.muted, lineHeight: 1.6, fontSize: "13px", maxWidth: "820px" }}>
            {copy("Describe a business need in plain language. The system will infer the scene profile, generate a workflow draft, and seed a supervised trial plan.", "用自然语言描述业务需求。系统会推断场景画像、生成工作流草稿，并生成一份受监督试跑计划。")}
          </div>
          <button
            type="button"
            onClick={() =>
              void onCompileTask({
                instruction,
                domainHint: domainHint || undefined,
              })
            }
            disabled={busy || instruction.trim().length < 8}
            style={actionButtonStyle}
          >
            {busy ? copy("Generating...", "生成中...") : copy("Generate workflow", "生成工作流")}
          </button>
        </div>
        <div style={{ display: "grid", gap: "12px" }}>
          <textarea
            value={instruction}
            onChange={(event) => setInstruction(event.target.value)}
            rows={5}
            style={{ ...inputShell, resize: "vertical" }}
          />
          <input
            value={domainHint}
            onChange={(event) => setDomainHint(event.target.value)}
            placeholder={copy("Optional scene hint, e.g. recruiting / market_news", "可选场景提示，例如 recruiting / market_news")}
            style={inputShell}
          />
          {data.compilerContract ? (
            <div
              style={{
                borderRadius: "16px",
                border: "1px solid rgba(255,255,255,0.08)",
                background: "rgba(255,255,255,0.03)",
                padding: "14px",
                display: "grid",
                gap: "10px",
              }}
            >
              <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                <StatusBadge tone="neutral">{data.compilerContract.contractVersion}</StatusBadge>
                <StatusBadge tone="positive">{data.compilerContract.strategy}</StatusBadge>
                <StatusBadge tone={data.compilerContract.fallbackStrategy === "none" ? "positive" : "warning"}>
                  {copy(`fallback: ${data.compilerContract.fallbackStrategy}`, `回退策略：${data.compilerContract.fallbackStrategy}`)}
                </StatusBadge>
                <StatusBadge tone="neutral">{data.compilerContract.promptAsset}</StatusBadge>
              </div>
              <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                {copy("Required fields", "必填字段")}: {data.compilerContract.requiredFields.join(", ")}
              </div>
              {data.compilerContract.qualityGates.length ? (
                <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                  {copy("Quality gates", "质量门槛")}: {data.compilerContract.qualityGates.join(" · ")}
                </div>
              ) : null}
              {compactRecordEntries(data.compilerContract.repairPolicy, 4).length ? (
                <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                  {copy("Repair policy", "修复策略")}:{" "}
                  {formatRecordSummary(data.compilerContract.repairPolicy, copy, 4)}
                </div>
              ) : null}
              <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                {copy("Invariants", "不变式")}: {data.compilerContract.invariants.join(" ")}
              </div>
            </div>
          ) : null}
        </div>
      </section>

      {lastOutcome ? (
      <Panel title={copy("Latest trial outcome", "最近试跑结果")} eyebrow={copy("Learning loop", "学习闭环")} description={copy("The most recent trial execution outcome, including derived workflow versions or revision suggestions.", "最近一次试跑的执行结果，包括衍生工作流版本或修订建议。")}>
          <div style={{ display: "grid", gap: "12px" }}>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              <StatusBadge tone={lastOutcome.episode.divergenceDetected ? "critical" : "positive"}>
                {translateUiToken(lastOutcome.episode.status, copy)}
              </StatusBadge>
              {lastOutcome.template ? <StatusBadge tone="positive">{copy("version derived", "已生成版本")}</StatusBadge> : null}
              {lastOutcome.templateApproval ? (
                <StatusBadge tone={lastOutcome.templateApproval.status === "approved" ? "positive" : "warning"}>
                  {copy(`version approval ${lastOutcome.templateApproval.status}`, `版本审批 ${translateUiToken(lastOutcome.templateApproval.status, copy)}`)}
                </StatusBadge>
              ) : null}
              {lastOutcome.patch ? <StatusBadge tone="warning">{copy("revision proposed", "已提出修订建议")}</StatusBadge> : null}
              {lastOutcome.approval ? <StatusBadge tone="warning">{copy("approval created", "已创建审批")}</StatusBadge> : null}
            </div>
            <div style={{ color: theme.colors.muted, lineHeight: 1.6 }}>
              {lastOutcome.episode.resultSummary ?? copy("No outcome summary available.", "暂无结果摘要。")}
            </div>
            {lastOutcome.templateApproval?.notes ? (
              <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                {copy("Version review note", "版本审查说明")}: {lastOutcome.templateApproval.notes}
              </div>
            ) : null}
            {lastOutcome.skillHealth ? (
              <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                {copy("Skill health", "Skill health")}: {String(lastOutcome.skillHealth.health ?? lastOutcome.skillHealth.status ?? "unknown")}
              </div>
            ) : null}
            {lastOutcome.learningDraft?.tags?.length ? (
              <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                {copy("Learning tags", "学习标签")}: {lastOutcome.learningDraft.tags.join(" · ")}
              </div>
            ) : null}
          </div>
        </Panel>
      ) : null}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: "18px", alignItems: "start" }}>
        <Panel title={copy("Workflow drafts", "工作流草稿")} eyebrow={copy("Workflow definitions", "工作流定义")} description={copy("System-generated workflow drafts with inferred capabilities, approvals, and output expectations.", "系统生成的工作流草稿，包含推断出的能力、审批策略和输出预期。")}>
          {renderTaskCards()}
        </Panel>
        <Panel
          title={copy("Execution plans", "执行计划")}
          eyebrow={copy("Workflow plan inventory", "工作流计划清单")}
          description={copy("Plans are runtime proposals. Select one to inspect scene fitness and prepare a supervised replan.", "计划是运行时提出的执行方案。选择一个计划，检查场景适配性并准备受监督重规划。")}
        >
          {renderPlanCards()}
        </Panel>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(320px, 1fr)", gap: "18px", alignItems: "start" }}>
        <Panel
          title={copy("Capability catalog", "能力目录")}
          eyebrow={copy("Driver surface", "驱动能力面")}
          description={copy("Drivers are reusable runtime primitives. Highlighted entries are currently inferred from the selected plan or scene assessment.", "驱动是可复用的运行时原语。高亮项表示当前从所选计划或场景评估中推断出的驱动。")}
        >
          {renderCapabilityDrivers(data.capabilityDrivers)}
        </Panel>
        <Panel
          title={copy("Environment and scene assessments", "环境与场景评估")}
          eyebrow={copy("Live Context", "实时上下文")}
          description={copy("Scene assessments tell the runtime whether the current environment still matches the compiled execution model.", "场景评估会告诉运行时，当前环境是否仍然匹配已编译的执行模型。")}
          actions={
            selectedPlan ? (
              <button
                type="button"
                onClick={() => void onAssessEnvironment(selectedPlan.id, selectedEpisodeId)}
                disabled={busy || busyPlanId === selectedPlan.id}
                style={actionButtonStyle}
              >
                {busyPlanId === selectedPlan.id ? copy("Assessing...", "评估中...") : copy("Refresh assessment", "刷新评估")}
              </button>
            ) : undefined
          }
        >
          {renderEnvironmentAssessments(data.environmentAssessments)}
        </Panel>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 0.95fr) minmax(0, 1.05fr)", gap: "18px", alignItems: "start" }}>
        <Panel
          title={copy("Plan replanning", "计划重规划")}
          eyebrow={copy("Control Loop", "控制环")}
          description={copy("Use the current scene assessment and selected drivers to propose a safer next execution plan before promoting it.", "基于当前场景评估和选定驱动，提出更安全的下一版执行计划，然后再决定是否提升。")}
          actions={
            <button
              type="button"
              onClick={() =>
                selectedPlan
                  ? void onReplanPlan(
                      selectedPlan.id,
                      replanTrigger,
                      replanNotes || undefined,
                      selectedCapabilityKeys.length ? selectedCapabilityKeys : undefined,
                    )
                  : undefined
              }
              disabled={busy || !selectedPlan || busyPlanId === selectedPlan?.id}
              style={actionButtonStyle}
            >
              {busyPlanId === selectedPlan?.id ? copy("Replanning...", "重规划中...") : copy("Generate replan", "生成重规划")}
            </button>
          }
        >
          <div style={{ display: "grid", gap: "14px" }}>
            <label style={{ display: "grid", gap: "8px" }}>
              <span style={{ color: theme.colors.muted, fontSize: "13px" }}>{copy("Execution plan", "执行计划")}</span>
              <select value={selectedPlan?.id ?? ""} onChange={(event) => setReplanPlanId(event.target.value)} style={inputShell}>
                {data.plans.map((plan) => (
                  <option key={plan.id} value={plan.id}>
                    {plan.name}
                  </option>
                ))}
              </select>
            </label>
            <label style={{ display: "grid", gap: "8px" }}>
              <span style={{ color: theme.colors.muted, fontSize: "13px" }}>{copy("Replan trigger", "重规划触发器")}</span>
              <select value={replanTrigger} onChange={(event) => setReplanTrigger(event.target.value)} style={inputShell}>
                <option value="scene_drift">{copy("Scene drift", "场景漂移")}</option>
                <option value="driver_degradation">{copy("Driver degradation", "驱动退化")}</option>
                <option value="operator_feedback">{copy("Operator feedback", "操作员反馈")}</option>
                <option value="output_gap">{copy("Output gap", "输出缺口")}</option>
              </select>
            </label>
            <label style={{ display: "grid", gap: "8px" }}>
              <span style={{ color: theme.colors.muted, fontSize: "13px" }}>{copy("Operator notes", "操作员备注")}</span>
              <textarea
                value={replanNotes}
                onChange={(event) => setReplanNotes(event.target.value)}
                rows={4}
                placeholder={copy("Optional notes for the replanner, e.g. preserve the current output contract but add a scene assessment checkpoint.", "给重规划器的可选备注，例如保留当前输出契约，但补一个场景评估检查点。")}
                style={{ ...inputShell, resize: "vertical" }}
              />
            </label>
            <div style={{ display: "grid", gap: "8px" }}>
              <div style={{ color: theme.colors.muted, fontSize: "13px" }}>{copy("Preferred capability drivers", "优先能力驱动")}</div>
              <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                {data.capabilityDrivers.map((driver) => {
                  const selected = selectedCapabilityKeys.includes(driver.key);
                  return (
                    <button
                      key={driver.id}
                      type="button"
                      onClick={() => toggleCapabilityKey(driver.key)}
                      style={{
                        ...actionButtonStyle,
                        padding: "8px 10px",
                        background: selected ? "rgba(122,167,255,0.24)" : "rgba(255,255,255,0.04)",
                      }}
                    >
                      {driver.key}
                    </button>
                  );
                })}
              </div>
            </div>
            {selectedAssessment ? (
              <div
                style={{
                  padding: "14px",
                  borderRadius: "16px",
                  border: "1px solid rgba(255,255,255,0.08)",
                  background: "rgba(255,255,255,0.03)",
                  color: theme.colors.muted,
                  fontSize: "13px",
                  lineHeight: 1.6,
                }}
              >
                <strong style={{ color: theme.colors.text }}>{selectedAssessment.sceneLabel}</strong>
                <div style={{ marginTop: "6px" }}>{selectedAssessment.summary}</div>
              </div>
            ) : null}
          </div>
        </Panel>
        <Panel
          title={copy("Replanning results", "重规划结果")}
          eyebrow={copy("Latest Proposals", "最近提案")}
          description={copy("Review recent replans, linked scene assessments, and any approval-gated revision output before trial execution resumes.", "在恢复试跑执行之前，先审查近期重规划、关联场景评估，以及任何受审批控制的修订建议输出。")}
        >
          {combinedReplans.length ? (
            <div style={{ display: "grid", gap: "14px" }}>
              {lastReplan ? (
                <article
                  style={{
                    padding: "16px",
                    borderRadius: "18px",
                    border: "1px solid rgba(122,167,255,0.34)",
                    background: "rgba(122,167,255,0.08)",
                    display: "grid",
                    gap: "10px",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: "10px", flexWrap: "wrap", alignItems: "start" }}>
                    <div>
                      <strong>{lastReplan.executionPlan.name}</strong>
                      <div style={{ color: theme.colors.muted, fontSize: "13px", marginTop: "6px", lineHeight: 1.6 }}>
                        {lastReplan.summary}
                      </div>
                    </div>
                    <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                      <StatusBadge tone={toneFromRuntimeStatus(lastReplan.status)}>{translateUiToken(lastReplan.status, copy)}</StatusBadge>
                      {lastReplan.patch ? <StatusBadge tone="warning">{copy("revision output", "修订建议输出")}</StatusBadge> : null}
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                    <StatusBadge tone="neutral">{lastReplan.trigger}</StatusBadge>
                    <StatusBadge tone="neutral">{copy(`${lastReplan.executionPlan.planBody.steps.length} steps`, `${lastReplan.executionPlan.planBody.steps.length} 步`)}</StatusBadge>
                    {lastReplan.environmentAssessment ? (
                      <StatusBadge tone={toneFromRuntimeStatus(lastReplan.environmentAssessment.status)}>
                        {lastReplan.environmentAssessment.sceneType}
                      </StatusBadge>
                    ) : null}
                  </div>
                  {lastReplan.compilerNotes.length ? (
                    <pre
                      style={{
                        margin: 0,
                        padding: "14px",
                        borderRadius: "16px",
                        background: "rgba(255,255,255,0.03)",
                        border: "1px solid rgba(255,255,255,0.08)",
                        color: theme.colors.muted,
                        fontSize: "12px",
                        overflowX: "auto",
                      }}
                    >
                      {summarizeJson({
                        notes: lastReplan.compilerNotes,
                        recommended_capabilities: lastReplan.recommendedCapabilityKeys,
                        patch: lastReplan.patch?.title ?? null,
                      })}
                    </pre>
                  ) : null}
                </article>
              ) : null}
              {renderReplanCards(lastReplan ? combinedReplans.slice(1, 4) : combinedReplans.slice(0, 4))}
            </div>
          ) : (
            <div style={{ color: theme.colors.muted }}>{copy("No replans recorded yet. Select a plan and generate the next proposal.", "尚未记录重规划。请选择一个计划并生成下一版提案。")}</div>
          )}
        </Panel>
      </div>

      <Panel title={copy("Seed scene profiles", "场景画像种子")} eyebrow={copy("Compilation hints", "编译提示")} description={copy("The system uses these scene profiles to infer structure without hard-coding platform-specific workflows.", "系统会使用这些场景画像来推断结构，而不是硬编码平台特定工作流。")}>
        {renderDomainCards(data.domainPacks.slice(0, 4))}
      </Panel>
    </div>
  );
}
