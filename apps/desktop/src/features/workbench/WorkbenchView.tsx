import React, { useEffect, useMemo, useState } from "react";
import { Panel, SectionTabs, StatusBadge, Timeline } from "../../components";
import { formatCompactDate } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { theme } from "../../lib/theme";
import { translateUiToken } from "../../lib/uiText";
import type {
  AgentEvent,
  AgentQueueItem,
  AgentSnapshot,
  DashboardSummary,
  RuntimeEnvironmentAssessment,
  RuntimeEpisodeReplay,
  RuntimeWorkspaceData,
  SyncBacklogItem,
  SyncStatusSnapshot,
} from "../../lib/types";
import { AgentMonitorView } from "../agent-monitor/AgentMonitorView";
import { CandidatesView } from "../candidates/CandidatesView";
import { WorkflowsView } from "../workflows/WorkflowsView";

type WorkbenchGlobalTab = "overview" | "operations";

function toneFromStatus(value: string): "positive" | "neutral" | "warning" | "critical" {
  if (/(failed|error|critical|diverged|drift|rejected)/i.test(value)) {
    return "critical";
  }
  if (/(pending|review|warning|blocked|draft)/i.test(value)) {
    return "warning";
  }
  if (/(active|approved|stable|running|completed|confirmed)/i.test(value)) {
    return "positive";
  }
  return "neutral";
}

interface WorkbenchViewProps {
  summary: DashboardSummary;
  data: RuntimeWorkspaceData;
  agent: AgentSnapshot;
  events: AgentEvent[];
  selectedEpisodeId?: string;
  replay?: RuntimeEpisodeReplay | null;
  syncStatus?: SyncStatusSnapshot | null;
  syncBacklog?: SyncBacklogItem[];
  queueItems?: AgentQueueItem[];
  runningAction?: boolean;
  syncingAction?: boolean;
  onRunOnce(): void;
  onQueueScreeningTask(): void;
  onFlushSync?(): void;
  onSelectEpisode?(episodeId: string): void;
}

export function WorkbenchView({
  summary,
  data,
  agent,
  events,
  selectedEpisodeId,
  replay,
  syncStatus,
  syncBacklog = [],
  queueItems = [],
  runningAction,
  syncingAction,
  onRunOnce,
  onQueueScreeningTask,
  onFlushSync,
  onSelectEpisode,
}: WorkbenchViewProps): JSX.Element {
  const { copy } = useI18n();
  const [scopeId, setScopeId] = useState<string>("global");
  const [globalTab, setGlobalTab] = useState<WorkbenchGlobalTab>("overview");
  const [workflowTab, setWorkflowTab] = useState<string>("overview");

  const workflowScopes = useMemo(
    () =>
      data.taskSpecs.map((task) => {
        const plans = data.plans.filter((plan) => plan.taskSpecId === task.id);
        const episodes = data.episodes.filter((episode) => episode.taskSpecId === task.id);
        const templates = data.templates.filter((template) => template.sourceTaskSpecId === task.id || template.domain === task.domain);
        const adjustments = data.patches.filter((patch) => patch.taskSpecId === task.id);
        const assessments = data.environmentAssessments.filter((assessment) => assessment.taskSpecId === task.id);
        const snapshots = data.snapshots.filter((snapshot) => snapshot.taskSpecId === task.id);
        return {
          task,
          plans,
          episodes,
          templates,
          adjustments,
          assessments,
          snapshots,
        };
      }),
    [data.environmentAssessments, data.episodes, data.patches, data.plans, data.snapshots, data.taskSpecs, data.templates],
  );
  const timelineEvents = useMemo(
    () =>
      events.slice(-6).map((event) => ({
        id: event.id,
        label: event.source,
        detail: event.message,
        at: event.at,
        tone:
          event.level === "error"
            ? ("critical" as const)
            : event.level === "warning"
              ? ("warning" as const)
              : event.level === "success"
                ? ("positive" as const)
                : ("neutral" as const),
      })),
    [events],
  );

  useEffect(() => {
    if (scopeId === "global") {
      return;
    }
    if (!workflowScopes.some((scope) => scope.task.id === scopeId)) {
      setScopeId("global");
    }
  }, [scopeId, workflowScopes]);

  const selectedWorkflow = workflowScopes.find((scope) => scope.task.id === scopeId) ?? null;

  useEffect(() => {
    if (!selectedWorkflow) {
      return;
    }
    const availableTabs = ["overview", ...selectedWorkflow.episodes.map((episode) => episode.id)];
    if (!availableTabs.includes(workflowTab)) {
      setWorkflowTab("overview");
    }
  }, [selectedWorkflow, workflowTab]);

  useEffect(() => {
    if (!selectedWorkflow) {
      return;
    }
    if (workflowTab !== "overview") {
      onSelectEpisode?.(workflowTab);
    }
  }, [onSelectEpisode, selectedWorkflow, workflowTab]);

  const renderGlobalOverview = () => (
    <div style={{ display: "grid", gap: "18px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))", gap: "14px" }}>
        {[
          {
            label: copy("Running workflows", "运行中的工作流"),
            value: workflowScopes.filter((scope) => scope.episodes.some((episode) => /(running|pending|awaiting_review)/i.test(episode.status))).length,
            tone: "positive" as const,
          },
          {
            label: copy("Workflow instances", "工作流实例"),
            value: data.episodes.length,
            tone: "neutral" as const,
          },
          {
            label: copy("Pending approvals", "待审批"),
            value: summary.approvals.filter((approval) => approval.status === "pending").length,
            tone: "warning" as const,
          },
          {
            label: copy("Scene assessments", "场景评估"),
            value: data.environmentAssessments.length,
            tone: "neutral" as const,
          },
        ].map((card) => (
          <Panel key={card.label} dense title={String(card.value)} eyebrow={card.label}>
            <StatusBadge tone={card.tone}>{card.label}</StatusBadge>
          </Panel>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.1fr) minmax(320px, 0.9fr)", gap: "18px", alignItems: "start" }}>
        <Panel
          title={copy("Workflow operations", "工作流运行情况")}
          eyebrow={copy("Live workbench board", "实时工作台总览")}
          description={copy(
            "Track how many workflow instances are active, blocked, or waiting for operator review under each workflow.",
            "查看每条工作流下有多少工作流实例正在运行、阻塞或等待人工审查。",
          )}
        >
          <div style={{ display: "grid", gap: "12px" }}>
            {workflowScopes.map((scope) => (
              <button
                key={scope.task.id}
                type="button"
                onClick={() => setScopeId(scope.task.id)}
                style={{
                  cursor: "pointer",
                  width: "100%",
                  textAlign: "left",
                  padding: "14px",
                  borderRadius: "16px",
                  border: `1px solid ${scopeId === scope.task.id ? "rgba(122,167,255,0.36)" : theme.colors.border}`,
                  background: scopeId === scope.task.id ? "rgba(122,167,255,0.12)" : "rgba(255,255,255,0.02)",
                  color: theme.colors.text,
                  display: "grid",
                  gap: "8px",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", gap: "10px", alignItems: "start", flexWrap: "wrap" }}>
                  <div>
                    <strong>{scope.task.title}</strong>
                    <div style={{ color: theme.colors.muted, fontSize: "13px", marginTop: "6px" }}>{scope.task.goal}</div>
                  </div>
                  <StatusBadge tone={toneFromStatus(scope.task.status)}>{translateUiToken(scope.task.status, copy)}</StatusBadge>
                </div>
                <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                  <StatusBadge tone="neutral">{scope.task.domain}</StatusBadge>
                  <StatusBadge tone={scope.episodes.some((episode) => /(running|pending|awaiting_review)/i.test(episode.status)) ? "warning" : "neutral"}>
                    {copy(`${scope.episodes.length} workflow instances`, `${scope.episodes.length} 个工作流实例`)}
                  </StatusBadge>
                  <StatusBadge tone="neutral">{copy(`${scope.templates.length} versions`, `${scope.templates.length} 个版本`)}</StatusBadge>
                  {scope.adjustments.filter((patch) => patch.status === "pending_review").length ? (
                    <StatusBadge tone="warning">
                      {copy(
                        `${scope.adjustments.filter((patch) => patch.status === "pending_review").length} pending revisions`,
                        `${scope.adjustments.filter((patch) => patch.status === "pending_review").length} 个待处理修订建议`,
                      )}
                    </StatusBadge>
                  ) : null}
                </div>
              </button>
            ))}
          </div>
        </Panel>

        <Panel
          title={copy("Recent workbench signals", "最近工作台信号")}
          eyebrow={copy("Operator visibility", "操作员可见性")}
          description={copy(
            "Recent workflow-related events that explain why a workflow instance is moving, waiting, or asking for review.",
            "最近与工作流相关的事件，用来说明工作流实例为什么在推进、等待，或请求人工审查。",
          )}
        >
          <Timeline events={timelineEvents} />
        </Panel>
      </div>
    </div>
  );

  const renderSelectedWorkflowOverview = () => {
    if (!selectedWorkflow) {
      return null;
    }
    const runningInstances = selectedWorkflow.episodes.filter((episode) => /(running|pending|awaiting_review)/i.test(episode.status)).length;
    const latestAssessment =
      selectedWorkflow.assessments.sort((left, right) => right.updatedAt.localeCompare(left.updatedAt))[0] ?? null;

    return (
      <div style={{ display: "grid", gap: "18px" }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "14px" }}>
          {[
            { label: copy("Workflow instances", "工作流实例"), value: selectedWorkflow.episodes.length, tone: "neutral" as const },
            { label: copy("Running now", "当前运行中"), value: runningInstances, tone: runningInstances ? ("warning" as const) : ("neutral" as const) },
            { label: copy("Released versions", "已发布版本"), value: selectedWorkflow.templates.filter((template) => template.status === "active").length, tone: "positive" as const },
            { label: copy("Scene checks", "场景检查"), value: selectedWorkflow.assessments.length, tone: "neutral" as const },
          ].map((item) => (
            <Panel key={item.label} dense title={String(item.value)} eyebrow={item.label}>
              <StatusBadge tone={item.tone}>{item.label}</StatusBadge>
            </Panel>
          ))}
        </div>

        <Panel
          title={selectedWorkflow.task.title}
          eyebrow={copy("Selected workflow", "当前工作流")}
          description={selectedWorkflow.task.goal}
          actions={
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              <StatusBadge tone="neutral">{selectedWorkflow.task.domain}</StatusBadge>
              <StatusBadge tone={toneFromStatus(selectedWorkflow.task.status)}>{translateUiToken(selectedWorkflow.task.status, copy)}</StatusBadge>
            </div>
          }
        >
          <div style={{ display: "grid", gap: "12px" }}>
            <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
              {copy(
                `This workflow currently has ${selectedWorkflow.plans.length} plans, ${selectedWorkflow.episodes.length} workflow instances, and ${selectedWorkflow.adjustments.length} revision records.`,
                `这条工作流当前有 ${selectedWorkflow.plans.length} 个计划、${selectedWorkflow.episodes.length} 个工作流实例，以及 ${selectedWorkflow.adjustments.length} 条修订记录。`,
              )}
            </div>
            {latestAssessment ? (
              <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                <StatusBadge tone={toneFromStatus(latestAssessment.status)}>{latestAssessment.sceneType}</StatusBadge>
                <StatusBadge tone="neutral">{copy(`confidence ${Math.round(latestAssessment.confidence * 100)}%`, `置信度 ${Math.round(latestAssessment.confidence * 100)}%`)}</StatusBadge>
                <StatusBadge tone={latestAssessment.plannerGuidance.requiresHumanReview ? "warning" : "positive"}>
                  {latestAssessment.plannerGuidance.requiresHumanReview ? copy("needs review", "需要审查") : copy("ready to proceed", "可以继续")}
                </StatusBadge>
              </div>
            ) : null}
          </div>
        </Panel>

        {selectedWorkflow.task.domain === "recruiting" ? (
          <div style={{ display: "grid", gap: "18px" }}>
            <Panel
              title={copy("Recruiting workbench", "招聘工作台")}
              eyebrow={copy("Domain-specific operations", "领域专属操作")}
              description={copy(
                "Recruiting workflows expose candidate pipeline health, resume progress, and recruiting-specific flow state.",
                "招聘工作流会展示候选人流水线健康度、简历进度，以及招聘专属的流程状态。",
              )}
            >
              <CandidatesView candidates={summary.candidates} />
            </Panel>
            <Panel
              title={copy("Recruiting flow map", "招聘流程地图")}
              eyebrow={copy("Workflow state", "流程状态")}
              description={copy(
                "Recruiting remains one workflow category, so it keeps a dedicated operational panel inside the workbench.",
                "招聘仍然是一类工作流，因此会在工作台内部保留专属的运行面板。",
              )}
            >
              <WorkflowsView workflows={summary.workflows} />
            </Panel>
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(320px, 0.9fr)", gap: "18px", alignItems: "start" }}>
            <Panel
              title={copy("Scene observations", "场景观察")}
              eyebrow={copy("Live environment", "实时环境")}
              description={copy(
                "Workflow-specific scene observations and assessment summaries for the currently selected workflow.",
                "当前所选工作流的场景观察结果与环境评估摘要。",
              )}
            >
              <div style={{ display: "grid", gap: "10px" }}>
                {selectedWorkflow.assessments.slice(0, 4).map((assessment) => (
                  <article
                    key={assessment.id}
                    style={{
                      padding: "14px",
                      borderRadius: "16px",
                      border: "1px solid rgba(255,255,255,0.08)",
                      background: "rgba(255,255,255,0.03)",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", gap: "10px", flexWrap: "wrap" }}>
                      <strong>{assessment.sceneLabel}</strong>
                      <StatusBadge tone={toneFromStatus(assessment.status)}>{translateUiToken(assessment.status, copy)}</StatusBadge>
                    </div>
                    <div style={{ color: theme.colors.muted, fontSize: "13px", marginTop: "8px", lineHeight: 1.6 }}>{assessment.summary}</div>
                  </article>
                ))}
              </div>
            </Panel>
            <Panel
              title={copy("Version and revision summary", "版本与修订摘要")}
              eyebrow={copy("Workflow evolution", "工作流演进")}
              description={copy(
                "Versions, revision suggestions, and recent workflow evolution signals for this selected workflow.",
                "当前所选工作流的版本、修订建议，以及最近的演进信号。",
              )}
            >
              <div style={{ display: "grid", gap: "10px" }}>
                {selectedWorkflow.templates.slice(0, 3).map((template) => (
                  <div key={template.id} style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                    {copy(`Version ${template.version}`, `版本 ${template.version}`)} · {template.name}
                  </div>
                ))}
                {selectedWorkflow.adjustments.slice(0, 3).map((patch) => (
                  <div key={patch.id} style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                    {copy("Revision", "修订")} · {patch.title}
                  </div>
                ))}
              </div>
            </Panel>
          </div>
        )}
      </div>
    );
  };

  const renderSelectedWorkflowInstance = () => {
    if (!selectedWorkflow || workflowTab === "overview") {
      return null;
    }
    const episode = selectedWorkflow.episodes.find((item) => item.id === workflowTab);
    if (!episode) {
      return null;
    }
    const assessmentForEpisode =
      selectedWorkflow.assessments.find((assessment) => assessment.executionEpisodeId === episode.id) ??
      selectedWorkflow.assessments.find((assessment) => assessment.executionPlanId === episode.executionPlanId) ??
      null;
    const snapshots = selectedWorkflow.snapshots.filter((snapshot) => snapshot.executionEpisodeId === episode.id);
    const queueForEpisode = queueItems.filter((item) => {
      const taskSpecId = String((item.payload.task_spec_id ?? item.payload.taskSpecId ?? "") || "");
      return taskSpecId === selectedWorkflow.task.id;
    });
    const selectedReplay = replay?.episode.id === episode.id ? replay : null;

    return (
      <div style={{ display: "grid", gap: "18px" }}>
        <Panel
          title={copy("Workflow instance detail", "工作流实例详情")}
          eyebrow={copy("Live execution state", "实时执行状态")}
          description={episode.resultSummary ?? copy("This workflow instance is still gathering execution evidence.", "这个工作流实例还在持续收集执行证据。")}
          actions={
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              <StatusBadge tone={toneFromStatus(episode.status)}>{translateUiToken(episode.status, copy)}</StatusBadge>
              <StatusBadge tone="neutral">{translateUiToken(episode.mode, copy)}</StatusBadge>
              {episode.requiresConfirmation ? <StatusBadge tone="warning">{copy("awaiting confirmation", "等待确认")}</StatusBadge> : null}
            </div>
          }
        >
          <div style={{ display: "grid", gap: "12px" }}>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              {episode.startedAt ? <StatusBadge tone="neutral">{copy(`Started ${formatCompactDate(episode.startedAt)}`, `开始于 ${formatCompactDate(episode.startedAt)}`)}</StatusBadge> : null}
              {episode.finishedAt ? <StatusBadge tone="neutral">{copy(`Finished ${formatCompactDate(episode.finishedAt)}`, `结束于 ${formatCompactDate(episode.finishedAt)}`)}</StatusBadge> : null}
              <StatusBadge tone="neutral">{copy(`${episode.actions.length} actions`, `${episode.actions.length} 个动作`)}</StatusBadge>
              <StatusBadge tone="neutral">{copy(`${episode.observations.length} observations`, `${episode.observations.length} 条观察`)}</StatusBadge>
            </div>
            {assessmentForEpisode ? (
              <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                {assessmentForEpisode.summary}
              </div>
            ) : null}
          </div>
        </Panel>

        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(320px, 0.9fr)", gap: "18px", alignItems: "start" }}>
          <Panel
            title={copy("Replay and diagnostics", "回放与诊断")}
            eyebrow={copy("Instance evidence", "实例证据")}
            description={copy(
              "Diagnostic notes, replay timeline, and learning evidence bound to this workflow instance.",
              "与这个工作流实例绑定的诊断说明、回放时间线，以及学习证据。",
            )}
          >
            {selectedReplay ? (
              <Timeline events={selectedReplay.diagnostics} />
            ) : (
              <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                {copy("No replay bundle is loaded for this workflow instance yet.", "这个工作流实例暂未加载回放数据。")}
              </div>
            )}
          </Panel>

          <Panel
            title={copy("Scene context", "场景上下文")}
            eyebrow={copy("Snapshots and queue", "快照与队列")}
            description={copy(
              "Environment snapshots and queue signals related to the selected workflow instance.",
              "与当前工作流实例相关的环境快照和队列信号。",
            )}
          >
            <div style={{ display: "grid", gap: "10px" }}>
              {snapshots.slice(0, 3).map((snapshot) => (
                <article
                  key={snapshot.id}
                  style={{
                    padding: "12px",
                    borderRadius: "14px",
                    border: "1px solid rgba(255,255,255,0.08)",
                    background: "rgba(255,255,255,0.03)",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: "8px", flexWrap: "wrap" }}>
                    <strong>{snapshot.title ?? snapshot.environmentKey ?? snapshot.id}</strong>
                    <StatusBadge tone="neutral">{snapshot.pageType ?? snapshot.source}</StatusBadge>
                  </div>
                  <div style={{ color: theme.colors.muted, fontSize: "13px", marginTop: "8px" }}>{snapshot.url ?? copy("No URL captured.", "未捕获 URL。")}</div>
                </article>
              ))}
              {queueForEpisode.slice(0, 2).map((item) => (
                <div key={item.taskId} style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                  {item.taskType} · {translateUiToken(item.status, copy)}
                </div>
              ))}
            </div>
          </Panel>
        </div>
      </div>
    );
  };

  const globalTabs = [
    { key: "overview", label: copy("Global board", "全局看板"), detail: copy("All workflows at a glance", "汇总查看所有工作流") },
    { key: "operations", label: copy("Operations", "运行控制"), detail: copy("Queue, replay, sync, and runtime state", "查看队列、回放、同步与运行状态") },
  ] satisfies Array<{ key: WorkbenchGlobalTab; label: string; detail: string }>;

  const workflowTabs = selectedWorkflow
    ? [
        { key: "overview", label: copy("Overview", "总览"), detail: copy("Workflow-specific summary", "当前工作流汇总") },
        ...selectedWorkflow.episodes.map((episode, index) => ({
          key: episode.id,
          label: copy(`Instance ${index + 1}`, `实例 ${index + 1}`),
          detail: copy("Open live execution state", "查看当前执行状态"),
        })),
      ]
    : [];

  return (
    <div style={{ display: "grid", gap: "18px" }}>
      <Panel
        title={copy("Workbench", "工作台")}
        eyebrow={copy("Live workflow operations", "工作流实时运营")}
        description={copy(
          "The workbench keeps every workflow visible at runtime. Start from the global board, then drill into each workflow to inspect its workflow instances and domain-specific data.",
          "工作台会把每条工作流在运行中的状态保持可见。你可以先看全局看板，再进入每条工作流查看它的工作流实例和领域专属数据。",
        )}
      >
        <div style={{ display: "grid", gridTemplateColumns: "240px minmax(0, 1fr)", gap: "18px", alignItems: "start" }}>
          <aside style={{ display: "grid", gap: "10px" }}>
            <button
              type="button"
              onClick={() => setScopeId("global")}
              style={{
                cursor: "pointer",
                textAlign: "left",
                padding: "14px",
                borderRadius: "16px",
                border: `1px solid ${scopeId === "global" ? "rgba(122,167,255,0.36)" : theme.colors.border}`,
                background: scopeId === "global" ? "rgba(122,167,255,0.12)" : "rgba(255,255,255,0.02)",
                color: theme.colors.text,
                display: "grid",
                gap: "6px",
              }}
            >
              <strong>{copy("Global board", "全局看板")}</strong>
              <span style={{ color: theme.colors.muted, fontSize: "12px", lineHeight: 1.5 }}>
                {copy("Across all workflows", "查看所有工作流")}
              </span>
            </button>
            {workflowScopes.map((scope) => (
              <button
                key={scope.task.id}
                type="button"
                onClick={() => setScopeId(scope.task.id)}
                style={{
                  cursor: "pointer",
                  textAlign: "left",
                  padding: "14px",
                  borderRadius: "16px",
                  border: `1px solid ${scopeId === scope.task.id ? "rgba(122,167,255,0.36)" : theme.colors.border}`,
                  background: scopeId === scope.task.id ? "rgba(122,167,255,0.12)" : "rgba(255,255,255,0.02)",
                  color: theme.colors.text,
                  display: "grid",
                  gap: "6px",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", gap: "8px", alignItems: "start" }}>
                  <strong style={{ fontSize: "14px" }}>{scope.task.title}</strong>
                  <StatusBadge tone={scope.episodes.some((episode) => /(running|pending|awaiting_review)/i.test(episode.status)) ? "warning" : "neutral"}>
                    {scope.episodes.length}
                  </StatusBadge>
                </div>
                <span style={{ color: theme.colors.muted, fontSize: "12px", lineHeight: 1.5 }}>
                  {scope.task.domain}
                  {scope.episodes.length ? copy(` · ${scope.episodes.length} workflow instances`, ` · ${scope.episodes.length} 个工作流实例`) : ""}
                </span>
              </button>
            ))}
          </aside>

          <div style={{ display: "grid", gap: "18px", minWidth: 0 }}>
            {scopeId === "global" ? (
              <>
                <SectionTabs items={globalTabs} active={globalTab} onChange={(key) => setGlobalTab(key as WorkbenchGlobalTab)} />
                {globalTab === "overview" ? (
                  renderGlobalOverview()
                ) : (
                  <AgentMonitorView
                    agent={agent}
                    events={events}
                    episodes={data.episodes}
                    selectedEpisodeId={selectedEpisodeId}
                    replay={replay}
                    syncStatus={syncStatus}
                    syncBacklog={syncBacklog}
                    queueItems={queueItems}
                    runningAction={runningAction}
                    syncingAction={syncingAction}
                    onRunOnce={onRunOnce}
                    onQueueScreeningTask={onQueueScreeningTask}
                    onFlushSync={onFlushSync}
                    onSelectEpisode={onSelectEpisode}
                  />
                )}
              </>
            ) : selectedWorkflow ? (
              <>
                <SectionTabs items={workflowTabs} active={workflowTab} onChange={setWorkflowTab} />
                {workflowTab === "overview" ? renderSelectedWorkflowOverview() : renderSelectedWorkflowInstance()}
              </>
            ) : null}
          </div>
        </div>
      </Panel>
    </div>
  );
}
