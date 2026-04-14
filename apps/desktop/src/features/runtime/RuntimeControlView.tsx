import React, { useEffect, useMemo, useState } from "react";
import { Panel, StatusBadge, Timeline } from "../../components";
import { formatCompactDate } from "../../lib/format";
import { theme } from "../../lib/theme";
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
  mode: "runtime" | "trials" | "templates" | "patches" | "domains";
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
                <StatusBadge tone="neutral">{task.domain}</StatusBadge>
                <StatusBadge tone={task.status.includes("ready") ? "positive" : "warning"}>{task.status}</StatusBadge>
              </div>
            </div>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              {task.preferredCapabilities.map((capability) => (
                <StatusBadge key={`${task.id}-${capability}`} tone="neutral">
                  {capability}
                </StatusBadge>
              ))}
            </div>
            {linkedPlan ? (
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "10px", flexWrap: "wrap" }}>
                <div style={{ color: theme.colors.muted, fontSize: "13px" }}>
                  Linked plan: <strong style={{ color: theme.colors.text }}>{linkedPlan.name}</strong>
                </div>
                <button
                  type="button"
                  onClick={() => void onCreateTrialRun(task.id, linkedPlan.id)}
                  disabled={busy}
                  style={actionButtonStyle}
                >
                  Create trial run
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
                  Mode {plan.mode} · Approval {plan.approvalState} · v{plan.version}
                </div>
              </div>
              <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                <StatusBadge tone={toneFromRuntimeStatus(plan.status)}>{plan.status}</StatusBadge>
                {linkedAssessment ? (
                  <StatusBadge tone={toneFromRuntimeStatus(linkedAssessment.status)}>{linkedAssessment.sceneType}</StatusBadge>
                ) : null}
              </div>
            </div>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              <StatusBadge tone="neutral">{plan.planBody.steps.length} steps</StatusBadge>
              {capabilities.map((capability) => (
                <StatusBadge key={`${plan.id}-${capability}`} tone="neutral">
                  {capability}
                </StatusBadge>
              ))}
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", gap: "10px", alignItems: "center", flexWrap: "wrap" }}>
              <div style={{ color: theme.colors.muted, fontSize: "13px" }}>
                {linkedAssessment
                  ? `${linkedAssessment.sceneLabel} · confidence ${formatConfidence(linkedAssessment.confidence)}`
                  : "No scene assessment recorded yet."}
              </div>
              <button
                type="button"
                onClick={() => setReplanPlanId(plan.id)}
                style={{ ...actionButtonStyle, background: isSelected ? "rgba(122,167,255,0.24)" : actionButtonStyle.background }}
              >
                {isSelected ? "Selected for replan" : "Use for replan"}
              </button>
            </div>
          </article>
        );
      })}
    </div>
  );

  const renderEpisodeCards = (episodes: RuntimeEpisode[]): JSX.Element => (
    <div style={{ display: "grid", gap: "14px" }}>
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
                  {plan?.name ?? "Detached plan"} · {episode.mode}
                </div>
              </div>
              <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                <StatusBadge tone={episode.divergenceDetected ? "critical" : "positive"}>
                  {episode.divergenceDetected ? "diverged" : episode.status}
                </StatusBadge>
                <StatusBadge tone="neutral">{metricStepCount(episode)} steps</StatusBadge>
              </div>
            </div>
            <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
              {episode.resultSummary ?? "No trial summary recorded yet."}
            </div>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              <StatusBadge tone="neutral">
                {episode.requiresConfirmation ? "awaits confirmation" : "confirmed or ungated"}
              </StatusBadge>
              {episode.finishedAt ? <StatusBadge tone="neutral">Finished {formatCompactDate(episode.finishedAt)}</StatusBadge> : null}
            </div>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "10px", flexWrap: "wrap" }}>
              <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                <button
                  type="button"
                  onClick={() => onInspectEpisode(episode.id)}
                  disabled={busy}
                  style={{ ...actionButtonStyle, background: isSelected ? "rgba(122,167,255,0.24)" : actionButtonStyle.background }}
                >
                  {isSelected ? "Diagnostics selected" : "Inspect diagnostics"}
                </button>
                <button
                  type="button"
                  onClick={() => void onRefreshLearning(episode.id)}
                  disabled={busy || busyEpisodeId === episode.id}
                  style={{ ...actionButtonStyle, background: "rgba(93,216,163,0.12)" }}
                >
                  {busyEpisodeId === episode.id ? "Refreshing..." : "Refresh learning"}
                </button>
                {episode.status === "pending" ? (
                  <button
                    type="button"
                    onClick={() => void onExecuteTrialRun(episode.id)}
                    disabled={busy || busyEpisodeId === episode.id}
                    style={actionButtonStyle}
                  >
                    {busyEpisodeId === episode.id ? "Executing..." : "Execute trial"}
                  </button>
                ) : null}
                {episode.requiresConfirmation || episode.status === "awaiting_review" ? (
                  <button
                    type="button"
                    onClick={() => void onConfirmTrial(episode.id)}
                    disabled={busy || busyEpisodeId === episode.id}
                    style={{ ...actionButtonStyle, background: "rgba(93,216,163,0.18)" }}
                  >
                    {busyEpisodeId === episode.id ? "Confirming..." : "Confirm trial"}
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
              <div style={{ color: theme.colors.muted, fontSize: "13px", marginTop: "6px" }}>{template.validationSummary ?? "No validation summary yet."}</div>
            </div>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              <StatusBadge tone="neutral">{template.domain}</StatusBadge>
              <StatusBadge tone={template.status === "active" ? "positive" : "warning"}>{template.status}</StatusBadge>
            </div>
          </div>
          <div style={{ color: theme.colors.muted, fontSize: "13px" }}>
            {Array.isArray(template.templateBody.steps) ? (template.templateBody.steps as unknown[]).length : 0} planned steps · v{template.version}
          </div>
        </article>
      ))}
    </div>
  );

  const renderPatchCards = (patches: RuntimePatch[]): JSX.Element => (
    <div style={{ display: "grid", gap: "14px" }}>
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
                {patch.divergenceSummary ?? patch.rationale ?? "No rationale supplied."}
              </div>
            </div>
            <StatusBadge tone={patch.status === "pending_review" ? "warning" : patch.status === "applied" ? "positive" : "neutral"}>
              {patch.status}
            </StatusBadge>
          </div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "10px", flexWrap: "wrap" }}>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              <StatusBadge tone="neutral">{patch.patchKind}</StatusBadge>
              {patch.templateId ? <StatusBadge tone="neutral">template linked</StatusBadge> : null}
            </div>
            {patch.status === "pending_review" ? (
              <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                <button
                  type="button"
                  onClick={() => void onApprovePatch(patch.id)}
                  disabled={busy || actionPatchId === patch.id}
                  style={actionButtonStyle}
                >
                  Approve patch
                </button>
                <button
                  type="button"
                  onClick={() => void onRejectPatch(patch.id)}
                  disabled={busy || actionPatchId === patch.id}
                  style={{ ...actionButtonStyle, background: "rgba(255,128,128,0.12)" }}
                >
                  Reject patch
                </button>
              </div>
            ) : null}
          </div>
        </article>
      ))}
    </div>
  );

  const renderDomainCards = (domains: DomainPackRecord[]): JSX.Element => (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "14px" }}>
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
            <StatusBadge tone="neutral">{domain.key}</StatusBadge>
          </div>
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
            {domain.defaultCapabilities.map((capability) => (
              <StatusBadge key={`${domain.key}-${capability}`} tone="neutral">
                {capability}
              </StatusBadge>
            ))}
          </div>
          {domain.sampleTasks.length ? (
            <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
              Example: {domain.sampleTasks[0]}
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
              <StatusBadge tone={toneFromRuntimeStatus(driver.status)}>{driver.status}</StatusBadge>
            </div>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              <StatusBadge tone="neutral">{driver.category}</StatusBadge>
              <StatusBadge tone="neutral">{driver.safetyMode}</StatusBadge>
              <StatusBadge tone={driver.supportsWrite ? "warning" : "neutral"}>
                {driver.supportsWrite ? "write-enabled" : "read-only"}
              </StatusBadge>
            </div>
            <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>{driver.description}</div>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              {driver.sceneTypes.slice(0, 3).map((scene) => (
                <StatusBadge key={`${driver.id}-${scene}`} tone="neutral">
                  {scene}
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
      <div style={{ color: theme.colors.muted }}>No live assessments yet. Refresh the selected scene to evaluate the current environment.</div>
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
                <StatusBadge tone={toneFromRuntimeStatus(assessment.status)}>{assessment.status}</StatusBadge>
                <StatusBadge tone="neutral">{formatConfidence(assessment.confidence)}</StatusBadge>
              </div>
            </div>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              <StatusBadge tone="neutral">{assessment.environmentKey}</StatusBadge>
              <StatusBadge tone="neutral">{assessment.sceneType}</StatusBadge>
              <StatusBadge tone="neutral">{assessment.sceneProfile.interactionMode}</StatusBadge>
              <StatusBadge tone={assessment.plannerGuidance.requiresHumanReview ? "warning" : "neutral"}>
                planner {assessment.plannerGuidance.posture}
              </StatusBadge>
            </div>
            {assessment.driftSignals.length ? (
              <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                Drift: {assessment.driftSignals.join(" · ")}
              </div>
            ) : (
              <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                Scene is aligned with the current execution model.
              </div>
            )}
            <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
              Auth {assessment.sceneProfile.authState} · {assessment.sceneProfile.entityCount} entities · {assessment.sceneProfile.affordanceCount} affordances
            </div>
            {assessment.sceneProfile.primaryTargets.length ? (
              <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                Targets: {assessment.sceneProfile.primaryTargets.join(" · ")}
              </div>
            ) : null}
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              {assessment.capabilityKeys.map((capability) => (
                <StatusBadge key={`${assessment.id}-${capability}`} tone="neutral">
                  {capability}
                </StatusBadge>
              ))}
              {assessment.plannerGuidance.insertedCapabilities.map((capability) => (
                <StatusBadge key={`${assessment.id}-inserted-${capability}`} tone="warning">
                  next {capability}
                </StatusBadge>
              ))}
            </div>
            {assessment.plannerGuidance.preferredNextActions.length ? (
              <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                Next: {assessment.plannerGuidance.preferredNextActions.join(" · ")}
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
      <div style={{ color: theme.colors.muted }}>No replans recorded yet. Generate a revision from the current scene assessment.</div>
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
              <StatusBadge tone={toneFromRuntimeStatus(replan.status)}>{replan.status}</StatusBadge>
              <StatusBadge tone="neutral">{replan.trigger}</StatusBadge>
            </div>
          </div>
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
            <StatusBadge tone="neutral">{replan.executionPlan.planBody.steps.length} steps</StatusBadge>
            {replan.recommendedCapabilityKeys.map((capability) => (
              <StatusBadge key={`${replan.id}-${capability}`} tone="neutral">
                {capability}
              </StatusBadge>
            ))}
          </div>
          <div style={{ color: theme.colors.muted, fontSize: "13px" }}>
            Created {formatCompactDate(replan.createdAt)}
            {replan.environmentAssessment ? ` · Scene ${replan.environmentAssessment.sceneType}` : ""}
          </div>
        </article>
      ))}
    </div>
    )
  );

  const toggleCapabilityKey = (key: string) => {
    setSelectedCapabilityKeys((current) => (current.includes(key) ? current.filter((value) => value !== key) : [...current, key]));
  };

  if (mode === "trials") {
    return (
      <div style={{ display: "grid", gap: "18px" }}>
        <Panel title="Trial Runs" eyebrow="Supervised Execution" description="Create, execute, inspect, and confirm trials before a workflow becomes reusable.">
          {renderEpisodeCards(data.episodes)}
        </Panel>
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.1fr) minmax(320px, 0.9fr)", gap: "18px", alignItems: "start" }}>
          <Panel title="Selected Replay Diagnostics" eyebrow="Episode Replay" description="The currently selected trial run with snapshots, timeline, and derived artifacts.">
            {replay ? (
              <div style={{ display: "grid", gap: "14px" }}>
                <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                  <StatusBadge tone={replay.episode.divergenceDetected ? "critical" : "positive"}>{replay.episode.status}</StatusBadge>
                  {replay.template ? <StatusBadge tone="positive">template candidate</StatusBadge> : null}
                  {replay.patch ? <StatusBadge tone="warning">patch candidate</StatusBadge> : null}
                  {replay.approval ? <StatusBadge tone="warning">approval pending</StatusBadge> : null}
                </div>
                <div style={{ color: theme.colors.muted, lineHeight: 1.6 }}>
                  {replay.episode.resultSummary ?? "No replay summary available."}
                </div>
                <Timeline events={replay.diagnostics} />
              </div>
            ) : (
              <div style={{ color: theme.colors.muted }}>Select a trial run to inspect diagnostics.</div>
            )}
          </Panel>
          <Panel title="Replay Context" eyebrow="Snapshots and Notes" description="Observed environment state and machine-readable artifacts recorded for the selected replay.">
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
                      <div style={{ color: theme.colors.muted, fontSize: "13px", marginTop: "8px" }}>{snapshot.url ?? "No URL captured."}</div>
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
              <div style={{ color: theme.colors.muted }}>Replay context will appear after selecting a trial run.</div>
            )}
          </Panel>
        </div>
      </div>
    );
  }

  if (mode === "templates") {
    return (
      <div style={{ display: "grid", gap: "18px" }}>
        <Panel title="Workflow Templates" eyebrow="Reuse and Governance" description="Validated execution plans that are ready to be reused or promoted into production packs.">
          {renderTemplateCards(data.templates)}
        </Panel>
      </div>
    );
  }

  if (mode === "patches") {
    return (
      <div style={{ display: "grid", gap: "18px" }}>
        <Panel title="Workflow Patches" eyebrow="Runtime Drift" description="Execution divergence proposals generated from trial runs.">
          {renderPatchCards(data.patches)}
        </Panel>
      </div>
    );
  }

  if (mode === "domains") {
    return (
      <div style={{ display: "grid", gap: "18px" }}>
        <Panel title="Domain Packs" eyebrow="Reusable Capability Packs" description="Recruiting is only one pack. These seeds tell the runtime what to prefer when compiling new tasks.">
          {renderDomainCards(data.domainPacks)}
        </Panel>
      </div>
    );
  }

  return (
    <div style={{ display: "grid", gap: "18px" }}>
      <Panel
        title="Dynamic Task Compiler"
        eyebrow="Natural Language Entry"
        description="Describe a task in plain language. The runtime will infer the domain pack, compile a TaskSpec, and seed a trial plan."
        actions={
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
            {busy ? "Compiling..." : "Compile task"}
          </button>
        }
      >
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
            placeholder="Optional domain hint, e.g. recruiting / market_news"
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
                <StatusBadge tone="positive">{data.compilerContract.strategy}</StatusBadge>
                <StatusBadge tone="warning">fallback: {data.compilerContract.fallbackStrategy}</StatusBadge>
                <StatusBadge tone="neutral">{data.compilerContract.promptAsset}</StatusBadge>
              </div>
              <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                Required fields: {data.compilerContract.requiredFields.join(", ")}
              </div>
              <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                Invariants: {data.compilerContract.invariants.join(" ")}
              </div>
            </div>
          ) : null}
        </div>
      </Panel>

      {lastOutcome ? (
        <Panel title="Latest Trial Outcome" eyebrow="Learning Loop" description="The most recent trial execution outcome, including derived templates or patches.">
          <div style={{ display: "grid", gap: "12px" }}>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              <StatusBadge tone={lastOutcome.episode.divergenceDetected ? "critical" : "positive"}>
                {lastOutcome.episode.status}
              </StatusBadge>
              {lastOutcome.template ? <StatusBadge tone="positive">template derived</StatusBadge> : null}
              {lastOutcome.templateApproval ? (
                <StatusBadge tone={lastOutcome.templateApproval.status === "approved" ? "positive" : "warning"}>
                  template approval {lastOutcome.templateApproval.status}
                </StatusBadge>
              ) : null}
              {lastOutcome.patch ? <StatusBadge tone="warning">patch proposed</StatusBadge> : null}
              {lastOutcome.approval ? <StatusBadge tone="warning">approval created</StatusBadge> : null}
            </div>
            <div style={{ color: theme.colors.muted, lineHeight: 1.6 }}>
              {lastOutcome.episode.resultSummary ?? "No outcome summary available."}
            </div>
            {lastOutcome.templateApproval?.notes ? (
              <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                Template review note: {lastOutcome.templateApproval.notes}
              </div>
            ) : null}
            {lastOutcome.skillHealth ? (
              <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                Skill health: {String(lastOutcome.skillHealth.health ?? lastOutcome.skillHealth.status ?? "unknown")}
              </div>
            ) : null}
          </div>
        </Panel>
      ) : null}

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.1fr) minmax(320px, 0.9fr)", gap: "18px", alignItems: "start" }}>
        <Panel title="Compiled Tasks" eyebrow="Task Specs" description="Runtime-generated task definitions with inferred capabilities and approval policy.">
          {renderTaskCards()}
        </Panel>
        <Panel
          title="Plan Inventory"
          eyebrow="Execution Plans"
          description="Plans are runtime proposals. Select one to inspect scene fitness and prepare a supervised replan."
        >
          {renderPlanCards()}
        </Panel>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(320px, 1fr)", gap: "18px", alignItems: "start" }}>
        <Panel
          title="Capability Driver Catalog"
          eyebrow="Driver Surface"
          description="Drivers are reusable runtime primitives. Highlighted entries are currently inferred from the selected plan or scene assessment."
        >
          {renderCapabilityDrivers(data.capabilityDrivers)}
        </Panel>
        <Panel
          title="Environment and Scene Assessments"
          eyebrow="Live Context"
          description="Scene assessments tell the runtime whether the current environment still matches the compiled execution model."
          actions={
            selectedPlan ? (
              <button
                type="button"
                onClick={() => void onAssessEnvironment(selectedPlan.id, selectedEpisodeId)}
                disabled={busy || busyPlanId === selectedPlan.id}
                style={actionButtonStyle}
              >
                {busyPlanId === selectedPlan.id ? "Assessing..." : "Refresh assessment"}
              </button>
            ) : undefined
          }
        >
          {renderEnvironmentAssessments(data.environmentAssessments)}
        </Panel>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 0.95fr) minmax(0, 1.05fr)", gap: "18px", alignItems: "start" }}>
        <Panel
          title="Plan Replanning"
          eyebrow="Control Loop"
          description="Use the current scene assessment and selected drivers to propose a safer next execution plan before promoting it."
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
              {busyPlanId === selectedPlan?.id ? "Replanning..." : "Generate replan"}
            </button>
          }
        >
          <div style={{ display: "grid", gap: "14px" }}>
            <label style={{ display: "grid", gap: "8px" }}>
              <span style={{ color: theme.colors.muted, fontSize: "13px" }}>Execution plan</span>
              <select value={selectedPlan?.id ?? ""} onChange={(event) => setReplanPlanId(event.target.value)} style={inputShell}>
                {data.plans.map((plan) => (
                  <option key={plan.id} value={plan.id}>
                    {plan.name}
                  </option>
                ))}
              </select>
            </label>
            <label style={{ display: "grid", gap: "8px" }}>
              <span style={{ color: theme.colors.muted, fontSize: "13px" }}>Replan trigger</span>
              <select value={replanTrigger} onChange={(event) => setReplanTrigger(event.target.value)} style={inputShell}>
                <option value="scene_drift">Scene drift</option>
                <option value="driver_degradation">Driver degradation</option>
                <option value="operator_feedback">Operator feedback</option>
                <option value="output_gap">Output gap</option>
              </select>
            </label>
            <label style={{ display: "grid", gap: "8px" }}>
              <span style={{ color: theme.colors.muted, fontSize: "13px" }}>Operator notes</span>
              <textarea
                value={replanNotes}
                onChange={(event) => setReplanNotes(event.target.value)}
                rows={4}
                placeholder="Optional notes for the replanner, e.g. preserve the current output contract but add a scene assessment checkpoint."
                style={{ ...inputShell, resize: "vertical" }}
              />
            </label>
            <div style={{ display: "grid", gap: "8px" }}>
              <div style={{ color: theme.colors.muted, fontSize: "13px" }}>Preferred capability drivers</div>
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
          title="Replanning Results"
          eyebrow="Latest Proposals"
          description="Review recent replans, linked scene assessments, and any approval-gated patch output before trial execution resumes."
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
                      <StatusBadge tone={toneFromRuntimeStatus(lastReplan.status)}>{lastReplan.status}</StatusBadge>
                      {lastReplan.patch ? <StatusBadge tone="warning">patch output</StatusBadge> : null}
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                    <StatusBadge tone="neutral">{lastReplan.trigger}</StatusBadge>
                    <StatusBadge tone="neutral">{lastReplan.executionPlan.planBody.steps.length} steps</StatusBadge>
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
            <div style={{ color: theme.colors.muted }}>No replans recorded yet. Select a plan and generate the next proposal.</div>
          )}
        </Panel>
      </div>

      <Panel title="Seed Domain Packs" eyebrow="Compilation Hints" description="The runtime uses these packs to infer structure without hard-coding platform-specific workflows.">
        {renderDomainCards(data.domainPacks.slice(0, 4))}
      </Panel>
    </div>
  );
}
