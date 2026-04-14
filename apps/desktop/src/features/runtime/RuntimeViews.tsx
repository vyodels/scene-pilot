import React, { useMemo, useState } from "react";
import { Panel, StatusBadge } from "../../components";
import { useI18n } from "../../lib/i18n";
import { theme } from "../../lib/theme";
import { translateUiToken } from "../../lib/uiText";
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
  const { copy } = useI18n();
  const [instruction, setInstruction] = useState("打开网页，找到好用的 PDF 转换工具，做对比并整理候选清单。");
  const [domainHint, setDomainHint] = useState("web_research");
  const [title, setTitle] = useState("调研 PDF 转换工具");

  const recentTasks = useMemo(() => runtime.taskSpecs.slice(0, 6), [runtime.taskSpecs]);

  return (
    <div style={{ display: "grid", gap: "18px" }}>
      <Panel
        title={copy("Task Compiler", "任务编译器")}
        eyebrow={copy("Runtime", "运行时")}
        description={copy("Turn natural language into a supervised task spec and trial plan. New workflows are compiled at runtime, not hardcoded into the product.", "将自然语言转成受监督的任务规格和试跑计划。新工作流在运行时编译，而不是硬编码进产品。")}
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
              <span style={mutedText}>{copy("Task title", "任务标题")}</span>
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
              <span style={mutedText}>{copy("Scene profile", "场景画像")}</span>
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
            <span style={mutedText}>{copy("Instruction", "任务指令")}</span>
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
            <div style={mutedText}>{copy("The compiler will infer a scene profile, approval gates, default output contract, and a first trial plan.", "编译器会推断场景画像、审批关卡、默认输出约定，以及首个试跑计划。")}</div>
            <button type="submit" style={actionButton} disabled={compiling}>
              {compiling ? copy("Compiling...", "编译中...") : copy("Compile Task", "编译任务")}
            </button>
          </div>
        </form>
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: "18px", alignItems: "start" }}>
        <Panel title={copy("Recent Task Specs", "最近任务规格")} eyebrow={copy("Runtime queue", "运行时待处理")} description={copy("Compiled tasks stay local-first and point to their active trial plan.", "已编译任务保持本地优先，并指向当前活动的试跑计划。")}>
          <div style={{ display: "grid", gap: "12px" }}>
            {recentTasks.map((task) => (
              <article key={task.id} style={{ padding: "14px", borderRadius: "16px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", alignItems: "start" }}>
                  <div>
                    <strong>{task.title}</strong>
                    <div style={{ ...mutedText, marginTop: "6px" }}>{task.goal}</div>
                  </div>
                  <StatusBadge tone={templateTone(task.status)}>{translateUiToken(task.status, copy)}</StatusBadge>
                </div>
                <div style={{ display: "flex", gap: "10px", marginTop: "10px", flexWrap: "wrap" }}>
                  <StatusBadge tone="neutral">{task.domain}</StatusBadge>
                  <StatusBadge tone="neutral">{copy(`${asStepCount(task, runtime)} steps`, `${asStepCount(task, runtime)} 步`)}</StatusBadge>
                </div>
                <div style={{ ...mutedText, marginTop: "10px" }}>{formatCapabilities(task.preferredCapabilities)}</div>
              </article>
            ))}
          </div>
        </Panel>

        <Panel title={copy("Plan Inventory", "计划清单")} eyebrow={copy("Compiled execution plans", "已编译执行计划")} description={copy("The runtime generates plans at execution time and only promotes them after supervision.", "运行时会在执行时生成计划，并仅在受监督后进行提升。")}>
          <div style={{ display: "grid", gap: "12px" }}>
            {runtime.plans.slice(0, 6).map((plan) => (
              <article key={plan.id} style={{ padding: "14px", borderRadius: "16px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "10px" }}>
                  <strong>{plan.name}</strong>
                  <StatusBadge tone={templateTone(plan.status)}>{translateUiToken(plan.status, copy)}</StatusBadge>
                </div>
                <div style={{ ...mutedText, marginTop: "8px" }}>
                  {copy(`Mode ${plan.mode} • Approval ${plan.approvalState} • ${Array.isArray(plan.planBody.steps) ? plan.planBody.steps.length : 0} steps`, `模式 ${plan.mode} • 审批 ${plan.approvalState} • ${Array.isArray(plan.planBody.steps) ? plan.planBody.steps.length : 0} 步`)}
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
  const { copy } = useI18n();
  return (
    <div style={{ display: "grid", gap: "18px" }}>
      <Panel
        title={copy("Supervised Trial Runs", "受监督试跑")}
        eyebrow={copy("Trial supervision", "试跑监督")}
        description={copy("New workflows are exercised under human supervision first. Divergence generates revision suggestions; stable runs can be confirmed into reusable templates.", "新工作流会先在人工监督下运行。发生偏差时会生成修订建议，稳定的运行则可被确认为可复用模板。")}
      >
        <div style={{ display: "grid", gap: "12px" }}>
          {runtime.episodes.map((episode) => {
            const snapshot = runtime.snapshots.find((item) => item.executionEpisodeId === episode.id);
            return (
              <article key={episode.id} style={{ padding: "16px", borderRadius: "18px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)", display: "grid", gap: "12px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", alignItems: "start" }}>
                  <div>
                    <strong>{episode.id}</strong>
                    <div style={{ ...mutedText, marginTop: "6px" }}>{episode.resultSummary ?? copy("Waiting for supervised execution.", "等待受监督执行。")}</div>
                  </div>
                  <StatusBadge tone={templateTone(episode.status)}>{translateUiToken(episode.status, copy)}</StatusBadge>
                </div>
                <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
                  <StatusBadge tone="neutral">{translateUiToken(episode.mode, copy)}</StatusBadge>
                  <StatusBadge tone={episode.requiresConfirmation ? "warning" : "positive"}>
                    {episode.requiresConfirmation ? copy("needs confirmation", "需要确认") : copy("confirmed", "已确认")}
                  </StatusBadge>
                  {episode.divergenceDetected ? <StatusBadge tone="critical">{copy("diverged", "已偏离")}</StatusBadge> : null}
                </div>
                {snapshot ? (
                  <div style={mutedText}>
                    {copy("Snapshot", "快照")}: {snapshot.pageType ?? "runtime_state"}
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
                    {busyEpisodeId === episode.id ? copy("Running...", "运行中...") : copy("Execute Trial", "执行试跑")}
                  </button>
                  <button
                    type="button"
                    onClick={() => void onExecute(episode.id, true)}
                    style={{ ...actionButton, background: "rgba(255,176,95,0.18)" }}
                    disabled={busyEpisodeId === episode.id}
                  >
                    {copy("Simulate Divergence", "模拟偏差")}
                  </button>
                  <button
                    type="button"
                    onClick={() => void onConfirm(episode.id)}
                    style={{ ...actionButton, background: "rgba(93,216,163,0.18)" }}
                    disabled={busyEpisodeId === episode.id || !episode.requiresConfirmation}
                  >
                    {copy("Confirm Trial", "确认试跑")}
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
  const { copy } = useI18n();
  return (
    <Panel
      title={copy("Workflow Templates", "工作流模板")}
      eyebrow={copy("Template library", "模板库")}
      description={copy("Stable execution patterns are promoted into reusable templates after supervised confirmation.", "稳定的执行模式会在受监督确认后提升为可复用模板。")}
    >
      <div style={{ display: "grid", gap: "12px" }}>
        {templates.map((template) => (
          <article key={template.id} style={{ padding: "16px", borderRadius: "18px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", alignItems: "start" }}>
              <div>
                <strong>{template.name}</strong>
                <div style={{ ...mutedText, marginTop: "6px" }}>{template.validationSummary ?? copy("Awaiting validation summary.", "等待验证摘要。")}</div>
              </div>
              <StatusBadge tone={templateTone(template.status)}>{translateUiToken(template.status, copy)}</StatusBadge>
            </div>
            <div style={{ display: "flex", gap: "10px", marginTop: "12px", flexWrap: "wrap" }}>
              <StatusBadge tone="neutral">{template.domain}</StatusBadge>
              <StatusBadge tone="neutral">v{template.version}</StatusBadge>
              <StatusBadge tone="neutral">
                {copy(`${Array.isArray(template.templateBody.steps) ? template.templateBody.steps.length : 0} steps`, `${Array.isArray(template.templateBody.steps) ? template.templateBody.steps.length : 0} 步`)}
              </StatusBadge>
            </div>
          </article>
        ))}
      </div>
    </Panel>
  );
}

export function RuntimePatchesView({ patches }: { patches: RuntimePatch[] }): JSX.Element {
  const { copy } = useI18n();
  return (
    <Panel
      title={copy("Workflow Patches", "工作流补丁")}
      eyebrow={copy("Divergence review", "偏差审查")}
      description={copy("When the runtime sees the live environment drift away from the expected plan, it proposes approval-gated workflow revisions.", "当运行时发现真实环境偏离预期计划时，会提出受审批控制的工作流修订建议。")}
    >
      <div style={{ display: "grid", gap: "12px" }}>
        {patches.map((patch) => (
          <article key={patch.id} style={{ padding: "16px", borderRadius: "18px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", alignItems: "start" }}>
              <div>
                <strong>{patch.title}</strong>
                <div style={{ ...mutedText, marginTop: "6px" }}>{patch.divergenceSummary ?? patch.rationale ?? copy("Revision suggestion awaiting review.", "修订建议等待审查。")}</div>
              </div>
              <StatusBadge tone={templateTone(patch.status)}>{translateUiToken(patch.status, copy)}</StatusBadge>
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
  const { copy } = useI18n();
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "18px" }}>
      {domainPacks.map((pack) => (
        <Panel
          key={pack.key}
          title={pack.name}
          eyebrow={copy(`Scene Profile · ${pack.key}`, `场景画像 · ${pack.key}`)}
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
  const { copy } = useI18n();
  return (
    <div style={{ display: "grid", gap: "18px" }}>
      <Panel
        title={copy("Recruiting Scene Profile", "招聘场景画像")}
        eyebrow={copy("Specialized capability", "专用能力")}
        description={copy("Recruiting remains available as a reusable scene profile on top of the shared runtime. This view keeps the pipeline and workflow-specific state visible.", "招聘仍然作为共享运行时之上的可复用场景画像保留。这个视图会继续展示流水线和工作流专属状态。")}
      >
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "12px" }}>
          {candidates.map((candidate) => (
            <article key={candidate.id} style={{ padding: "16px", borderRadius: "18px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: "8px", alignItems: "start" }}>
                <div>
                  <strong>{candidate.name}</strong>
                  <div style={{ ...mutedText, marginTop: "6px" }}>{candidate.title} • {candidate.location}</div>
                </div>
                <StatusBadge tone={templateTone(candidate.status)}>{translateUiToken(candidate.status, copy)}</StatusBadge>
              </div>
              <div style={{ ...mutedText, marginTop: "10px" }}>{candidate.summary}</div>
            </article>
          ))}
        </div>
      </Panel>

      <Panel title={copy("Recruiting Workflows", "招聘工作流")} eyebrow={copy("Current domain templates", "当前领域模板")} description={copy("These are still domain-specific views layered on the general runtime control plane.", "这些仍然是叠加在通用运行时控制平面之上的领域化视图。")}>
        <div style={{ display: "grid", gap: "12px" }}>
          {workflows.map((workflow) => (
            <article key={workflow.id} style={{ padding: "16px", borderRadius: "18px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", alignItems: "start" }}>
                <div>
                  <strong>{workflow.name}</strong>
                  <div style={{ ...mutedText, marginTop: "6px" }}>{workflow.jdTitle}</div>
                </div>
                <StatusBadge tone={templateTone(workflow.status)}>{translateUiToken(workflow.status, copy)}</StatusBadge>
              </div>
            </article>
          ))}
        </div>
      </Panel>
    </div>
  );
}
