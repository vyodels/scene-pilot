import React, { useState } from "react";
import { Panel, StatusBadge } from "../../components";
import { theme } from "../../lib/theme";
import type {
  CompileTaskRequest,
  DomainPackRecord,
  RuntimeEpisode,
  RuntimeLearningOutcome,
  RuntimePatch,
  RuntimeTaskSpec,
  RuntimeTemplate,
  RuntimeWorkspaceData,
} from "../../lib/types";

interface RuntimeControlViewProps {
  mode: "runtime" | "trials" | "templates" | "patches" | "domains";
  data: RuntimeWorkspaceData;
  busy: boolean;
  actionPatchId?: string;
  lastOutcome?: RuntimeLearningOutcome | null;
  onCompileTask(payload: CompileTaskRequest): Promise<void>;
  onCreateTrialRun(taskSpecId: string, executionPlanId: string): Promise<void>;
  onExecuteTrialRun(episodeId: string): Promise<void>;
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

export function RuntimeControlView({
  mode,
  data,
  busy,
  actionPatchId,
  lastOutcome,
  onCompileTask,
  onCreateTrialRun,
  onExecuteTrialRun,
  onApprovePatch,
  onRejectPatch,
}: RuntimeControlViewProps): JSX.Element {
  const [instruction, setInstruction] = useState("打开网站，给我按照要求找到候选人，拿到简历，上传内网，评分。");
  const [domainHint, setDomainHint] = useState("");

  const taskById = new Map(data.taskSpecs.map((item) => [item.id, item]));
  const planById = new Map(data.plans.map((item) => [item.id, item]));

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

  const renderEpisodeCards = (episodes: RuntimeEpisode[]): JSX.Element => (
    <div style={{ display: "grid", gap: "14px" }}>
      {episodes.map((episode) => {
        const plan = planById.get(episode.executionPlanId);
        const task = taskById.get(episode.taskSpecId);
        return (
          <article
            key={episode.id}
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
                <strong>{task?.title ?? episode.id}</strong>
                <div style={{ color: theme.colors.muted, fontSize: "13px", marginTop: "6px" }}>
                  {plan?.name ?? "Detached plan"} · {episode.mode}
                </div>
              </div>
              <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                <StatusBadge tone={episode.divergenceDetected ? "critical" : "positive"}>
                  {episode.divergenceDetected ? "diverged" : episode.status}
                </StatusBadge>
                <StatusBadge tone="neutral">{episode.actions.length} actions</StatusBadge>
              </div>
            </div>
            <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
              {episode.resultSummary ?? "No trial summary recorded yet."}
            </div>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "10px", flexWrap: "wrap" }}>
              <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                <StatusBadge tone="neutral">
                  {episode.requiresConfirmation ? "awaits confirmation" : "no confirmation gate"}
                </StatusBadge>
                <StatusBadge tone="neutral">
                  {(episode.metrics.stepCount as number | undefined) ?? (episode.metrics.step_count as number | undefined) ?? episode.actions.length}{" "}
                  steps
                </StatusBadge>
              </div>
              <button
                type="button"
                onClick={() => void onExecuteTrialRun(episode.id)}
                disabled={busy}
                style={actionButtonStyle}
              >
                Execute trial
              </button>
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

  if (mode === "trials") {
    return (
      <div style={{ display: "grid", gap: "18px" }}>
        <Panel title="Trial Runs" eyebrow="Supervised Execution" description="Create, execute, and inspect supervised trial runs before a workflow becomes reusable.">
          {renderEpisodeCards(data.episodes)}
        </Panel>
        <Panel title="Environment Snapshots" eyebrow="Runtime Context" description="Latest captured environment states across trial runs.">
          <div style={{ display: "grid", gap: "12px" }}>
            {data.snapshots.map((snapshot) => (
              <article key={snapshot.id} style={{ padding: "14px", borderRadius: "16px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "10px", flexWrap: "wrap" }}>
                  <strong>{snapshot.title ?? snapshot.environmentKey ?? snapshot.id}</strong>
                  <StatusBadge tone="neutral">{snapshot.pageType ?? snapshot.source}</StatusBadge>
                </div>
                <div style={{ color: theme.colors.muted, fontSize: "13px", marginTop: "8px" }}>{snapshot.url ?? "No URL captured."}</div>
              </article>
            ))}
          </div>
        </Panel>
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
              {lastOutcome.patch ? <StatusBadge tone="warning">patch proposed</StatusBadge> : null}
              {lastOutcome.approval ? <StatusBadge tone="warning">approval created</StatusBadge> : null}
            </div>
            <div style={{ color: theme.colors.muted, lineHeight: 1.6 }}>
              {lastOutcome.episode.resultSummary ?? "No outcome summary available."}
            </div>
          </div>
        </Panel>
      ) : null}

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.1fr) minmax(320px, 0.9fr)", gap: "18px", alignItems: "start" }}>
        <Panel title="Compiled Tasks" eyebrow="Task Specs" description="Runtime-generated task definitions with inferred capabilities and approval policy.">
          {renderTaskCards()}
        </Panel>
        <Panel title="Seed Domain Packs" eyebrow="Compilation Hints" description="The runtime uses these packs to infer structure without hard-coding platform-specific workflows.">
          {renderDomainCards(data.domainPacks.slice(0, 4))}
        </Panel>
      </div>
    </div>
  );
}
