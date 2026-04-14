import React, { useMemo, useState } from "react";
import { Panel, StatusBadge } from "../../components";
import { theme } from "../../lib/theme";
import type {
  CandidateRecord,
  CompileTaskRequest,
  DomainPackRecord,
  RuntimeEpisode,
  RuntimePatch,
  RuntimeTaskSpec,
  RuntimeTemplate,
  RuntimeWorkspaceData,
  WorkflowDefinition,
} from "../../lib/types";

const actionButton = {
  border: "1px solid rgba(255,255,255,0.12)",
  borderRadius: "12px",
  background: "rgba(122,167,255,0.18)",
  color: "#eef3ff",
  padding: "10px 14px",
  cursor: "pointer",
  fontWeight: 700,
} as const;

const mutedText = {
  color: "rgba(233,239,255,0.72)",
  fontSize: "13px",
  lineHeight: 1.6,
} as const;

function templateTone(status: string): "positive" | "neutral" | "warning" | "critical" {
  if (status === "active" || status === "confirmed") {
    return "positive";
  }
  if (status === "pending_review" || status === "pending") {
    return "warning";
  }
  if (status === "rejected" || status === "diverged") {
    return "critical";
  }
  return "neutral";
}

function formatCapabilities(values: string[]): string {
  return values.length ? values.join(" • ") : "No inferred capabilities";
}

function asStepCount(taskSpec: RuntimeTaskSpec, runtime: RuntimeWorkspaceData): number {
  const plan = runtime.plans.find((item) => item.id === taskSpec.activePlanId) ?? runtime.plans.find((item) => item.taskSpecId === taskSpec.id);
  return Array.isArray(plan?.planBody.steps) ? plan.planBody.steps.length : 0;
}

export function RuntimeControlView({
  runtime,
  compiling,
  onCompile,
}: {
  runtime: RuntimeWorkspaceData;
  compiling: boolean;
  onCompile(payload: CompileTaskRequest): Promise<void>;
}): JSX.Element {
  const [instruction, setInstruction] = useState("Open the web and find useful PDF converters, compare them, and prepare a shortlist.");
  const [domainHint, setDomainHint] = useState("web_research");
  const [title, setTitle] = useState("Research PDF converters");

  const recentTasks = useMemo(() => runtime.taskSpecs.slice(0, 6), [runtime.taskSpecs]);

  return (
    <div style={{ display: "grid", gap: "18px" }}>
      <Panel
        title="Task Compiler"
        eyebrow="Runtime"
        description="Turn natural language into a supervised task spec and trial plan. New workflows are compiled at runtime, not hardcoded into the product."
      >
        <form
          style={{ display: "grid", gap: "12px" }}
          onSubmit={(event) => {
            event.preventDefault();
            void onCompile({ instruction, title, domainHint });
          }}
        >
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "12px" }}>
            <label style={{ display: "grid", gap: "8px" }}>
              <span style={mutedText}>Task title</span>
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                style={{
                  borderRadius: "12px",
                  border: "1px solid rgba(255,255,255,0.12)",
                  background: "rgba(255,255,255,0.04)",
                  color: theme.colors.text,
                  padding: "12px 14px",
                }}
              />
            </label>
            <label style={{ display: "grid", gap: "8px" }}>
              <span style={mutedText}>Domain pack</span>
              <select
                value={domainHint}
                onChange={(event) => setDomainHint(event.target.value)}
                style={{
                  borderRadius: "12px",
                  border: "1px solid rgba(255,255,255,0.12)",
                  background: "rgba(255,255,255,0.04)",
                  color: theme.colors.text,
                  padding: "12px 14px",
                }}
              >
                {runtime.domainPacks.map((pack) => (
                  <option key={pack.key} value={pack.key}>
                    {pack.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label style={{ display: "grid", gap: "8px" }}>
            <span style={mutedText}>Instruction</span>
            <textarea
              value={instruction}
              onChange={(event) => setInstruction(event.target.value)}
              rows={5}
              style={{
                resize: "vertical",
                borderRadius: "14px",
                border: "1px solid rgba(255,255,255,0.12)",
                background: "rgba(255,255,255,0.04)",
                color: theme.colors.text,
                padding: "14px",
                lineHeight: 1.6,
              }}
            />
          </label>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "12px", flexWrap: "wrap" }}>
            <div style={mutedText}>The compiler will infer domain pack, approval gates, default output contract, and a first trial plan.</div>
            <button type="submit" style={actionButton} disabled={compiling}>
              {compiling ? "Compiling..." : "Compile Task"}
            </button>
          </div>
        </form>
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.1fr) minmax(320px, 0.9fr)", gap: "18px", alignItems: "start" }}>
        <Panel title="Recent Task Specs" eyebrow="Runtime backlog" description="Compiled tasks stay local-first and point to their active trial plan.">
          <div style={{ display: "grid", gap: "12px" }}>
            {recentTasks.map((task) => (
              <article key={task.id} style={{ padding: "14px", borderRadius: "16px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", alignItems: "start" }}>
                  <div>
                    <strong>{task.title}</strong>
                    <div style={{ ...mutedText, marginTop: "6px" }}>{task.goal}</div>
                  </div>
                  <StatusBadge tone={templateTone(task.status)}>{task.status}</StatusBadge>
                </div>
                <div style={{ display: "flex", gap: "10px", marginTop: "10px", flexWrap: "wrap" }}>
                  <StatusBadge tone="neutral">{task.domain}</StatusBadge>
                  <StatusBadge tone="neutral">{asStepCount(task, runtime)} steps</StatusBadge>
                </div>
                <div style={{ ...mutedText, marginTop: "10px" }}>{formatCapabilities(task.preferredCapabilities)}</div>
              </article>
            ))}
          </div>
        </Panel>

        <Panel title="Plan Inventory" eyebrow="Compiled execution plans" description="The runtime generates plans at execution time and only promotes them after supervision.">
          <div style={{ display: "grid", gap: "12px" }}>
            {runtime.plans.slice(0, 6).map((plan) => (
              <article key={plan.id} style={{ padding: "14px", borderRadius: "16px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "10px" }}>
                  <strong>{plan.name}</strong>
                  <StatusBadge tone={templateTone(plan.status)}>{plan.status}</StatusBadge>
                </div>
                <div style={{ ...mutedText, marginTop: "8px" }}>
                  Mode {plan.mode} • Approval {plan.approvalState} • {Array.isArray(plan.planBody.steps) ? plan.planBody.steps.length : 0} steps
                </div>
              </article>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}

export function TrialRunsView({
  runtime,
  busyEpisodeId,
  onExecute,
  onConfirm,
}: {
  runtime: RuntimeWorkspaceData;
  busyEpisodeId?: string;
  onExecute(episodeId: string, simulateDivergence?: boolean): Promise<void>;
  onConfirm(episodeId: string): Promise<void>;
}): JSX.Element {
  return (
    <div style={{ display: "grid", gap: "18px" }}>
      <Panel
        title="Supervised Trial Runs"
        eyebrow="Trial supervision"
        description="New workflows are exercised under human supervision first. Divergence generates patches; stable runs can be confirmed into reusable templates."
      >
        <div style={{ display: "grid", gap: "12px" }}>
          {runtime.episodes.map((episode) => {
            const snapshot = runtime.snapshots.find((item) => item.executionEpisodeId === episode.id);
            return (
              <article key={episode.id} style={{ padding: "16px", borderRadius: "18px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)", display: "grid", gap: "12px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", alignItems: "start" }}>
                  <div>
                    <strong>{episode.id}</strong>
                    <div style={{ ...mutedText, marginTop: "6px" }}>{episode.resultSummary ?? "Waiting for supervised execution."}</div>
                  </div>
                  <StatusBadge tone={templateTone(episode.status)}>{episode.status}</StatusBadge>
                </div>
                <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
                  <StatusBadge tone="neutral">{episode.mode}</StatusBadge>
                  <StatusBadge tone={episode.requiresConfirmation ? "warning" : "positive"}>
                    {episode.requiresConfirmation ? "needs confirmation" : "confirmed"}
                  </StatusBadge>
                  {episode.divergenceDetected ? <StatusBadge tone="critical">diverged</StatusBadge> : null}
                </div>
                {snapshot ? (
                  <div style={mutedText}>
                    Snapshot: {snapshot.pageType ?? "runtime_state"}
                    {snapshot.url ? ` • ${snapshot.url}` : ""}
                  </div>
                ) : null}
                <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
                  <button
                    type="button"
                    onClick={() => void onExecute(episode.id, false)}
                    style={actionButton}
                    disabled={busyEpisodeId === episode.id}
                  >
                    {busyEpisodeId === episode.id ? "Running..." : "Execute Trial"}
                  </button>
                  <button
                    type="button"
                    onClick={() => void onExecute(episode.id, true)}
                    style={{ ...actionButton, background: "rgba(255,176,95,0.18)" }}
                    disabled={busyEpisodeId === episode.id}
                  >
                    Simulate Divergence
                  </button>
                  <button
                    type="button"
                    onClick={() => void onConfirm(episode.id)}
                    style={{ ...actionButton, background: "rgba(93,216,163,0.18)" }}
                    disabled={busyEpisodeId === episode.id || !episode.requiresConfirmation}
                  >
                    Confirm Trial
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      </Panel>
    </div>
  );
}

export function RuntimeTemplatesView({ templates }: { templates: RuntimeTemplate[] }): JSX.Element {
  return (
    <Panel
      title="Workflow Templates"
      eyebrow="Template library"
      description="Stable execution patterns are promoted into reusable templates after supervised confirmation."
    >
      <div style={{ display: "grid", gap: "12px" }}>
        {templates.map((template) => (
          <article key={template.id} style={{ padding: "16px", borderRadius: "18px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", alignItems: "start" }}>
              <div>
                <strong>{template.name}</strong>
                <div style={{ ...mutedText, marginTop: "6px" }}>{template.validationSummary ?? "Awaiting validation summary."}</div>
              </div>
              <StatusBadge tone={templateTone(template.status)}>{template.status}</StatusBadge>
            </div>
            <div style={{ display: "flex", gap: "10px", marginTop: "12px", flexWrap: "wrap" }}>
              <StatusBadge tone="neutral">{template.domain}</StatusBadge>
              <StatusBadge tone="neutral">v{template.version}</StatusBadge>
              <StatusBadge tone="neutral">
                {Array.isArray(template.templateBody.steps) ? template.templateBody.steps.length : 0} steps
              </StatusBadge>
            </div>
          </article>
        ))}
      </div>
    </Panel>
  );
}

export function RuntimePatchesView({ patches }: { patches: RuntimePatch[] }): JSX.Element {
  return (
    <Panel
      title="Workflow Patches"
      eyebrow="Divergence review"
      description="When the runtime sees the live environment drift away from the expected plan, it proposes approval-gated workflow patches."
    >
      <div style={{ display: "grid", gap: "12px" }}>
        {patches.map((patch) => (
          <article key={patch.id} style={{ padding: "16px", borderRadius: "18px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", alignItems: "start" }}>
              <div>
                <strong>{patch.title}</strong>
                <div style={{ ...mutedText, marginTop: "6px" }}>{patch.divergenceSummary ?? patch.rationale ?? "Patch awaiting review."}</div>
              </div>
              <StatusBadge tone={templateTone(patch.status)}>{patch.status}</StatusBadge>
            </div>
            <div style={{ display: "flex", gap: "10px", marginTop: "12px", flexWrap: "wrap" }}>
              <StatusBadge tone="neutral">{patch.patchKind}</StatusBadge>
              {patch.proposedBy ? <StatusBadge tone="neutral">{patch.proposedBy}</StatusBadge> : null}
            </div>
          </article>
        ))}
      </div>
    </Panel>
  );
}

export function DomainPacksView({ domainPacks }: { domainPacks: DomainPackRecord[] }): JSX.Element {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "18px" }}>
      {domainPacks.map((pack) => (
        <Panel
          key={pack.key}
          title={pack.name}
          eyebrow={`Domain Pack · ${pack.key}`}
          description={pack.description}
        >
          <div style={{ display: "grid", gap: "12px" }}>
            <div style={mutedText}>{formatCapabilities(pack.defaultCapabilities)}</div>
            <div style={{ display: "grid", gap: "8px" }}>
              {pack.sampleTasks.map((sample) => (
                <div key={sample} style={{ ...mutedText, padding: "10px 12px", borderRadius: "12px", background: "rgba(255,255,255,0.03)" }}>
                  {sample}
                </div>
              ))}
            </div>
          </div>
        </Panel>
      ))}
    </div>
  );
}

export function RecruitingPackView({
  candidates,
  workflows,
}: {
  candidates: CandidateRecord[];
  workflows: WorkflowDefinition[];
}): JSX.Element {
  return (
    <div style={{ display: "grid", gap: "18px" }}>
      <Panel
        title="Recruiting Domain Pack"
        eyebrow="Specialized capability"
        description="Recruiting remains available as a domain pack on top of the shared runtime. This view keeps the pipeline and workflow-specific state visible."
      >
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "12px" }}>
          {candidates.map((candidate) => (
            <article key={candidate.id} style={{ padding: "16px", borderRadius: "18px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: "8px", alignItems: "start" }}>
                <div>
                  <strong>{candidate.name}</strong>
                  <div style={{ ...mutedText, marginTop: "6px" }}>{candidate.title} • {candidate.location}</div>
                </div>
                <StatusBadge tone={templateTone(candidate.status)}>{candidate.status}</StatusBadge>
              </div>
              <div style={{ ...mutedText, marginTop: "10px" }}>{candidate.summary}</div>
            </article>
          ))}
        </div>
      </Panel>

      <Panel title="Recruiting Workflows" eyebrow="Current domain templates" description="These are still domain-specific views layered on the general runtime control plane.">
        <div style={{ display: "grid", gap: "12px" }}>
          {workflows.map((workflow) => (
            <article key={workflow.id} style={{ padding: "16px", borderRadius: "18px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", alignItems: "start" }}>
                <div>
                  <strong>{workflow.name}</strong>
                  <div style={{ ...mutedText, marginTop: "6px" }}>{workflow.jdTitle}</div>
                </div>
                <StatusBadge tone={templateTone(workflow.status)}>{workflow.status}</StatusBadge>
              </div>
            </article>
          ))}
        </div>
      </Panel>
    </div>
  );
}
