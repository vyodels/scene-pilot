import React, { useMemo, useState } from "react";
import { MetricCard, Panel, ProgressBars, StatusBadge, Timeline } from "../../components";
import { formatCompactDate } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { theme } from "../../lib/theme";
import { translateUiToken } from "../../lib/uiText";
import type {
  AgentEvent,
  AgentQueueItem,
  AgentSnapshot,
  DashboardSummary,
  ExecutionGraphProjectionRecord,
  ExecutionTraceRecord,
  GoalSpecRecord,
  RuntimeEpisodeReplay,
  RuntimeWorkspaceData,
  SyncBacklogItem,
  SyncStatusSnapshot,
} from "../../lib/types";

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
  goals?: GoalSpecRecord[];
  traces?: ExecutionTraceRecord[];
  graphs?: ExecutionGraphProjectionRecord[];
  runningAction?: boolean;
  syncingAction?: boolean;
  onRunOnce(): void;
  onQueueScreeningTask(): void;
  onCreateGoal?(payload: { title: string; goalText: string; summary?: string }): void;
  onFlushSync?(): void;
  onSelectEpisode?(episodeId: string): void;
  onOpenCommunications?(filter?: string, candidateId?: string): void;
  onOpenAgentInbox?(): void;
}

function toneFromCandidateStatus(status: string): "positive" | "neutral" | "warning" | "critical" {
  if (/(rejected|cooldown)/i.test(status)) {
    return "critical";
  }
  if (/(pending|waiting|review|screening|communicating|resume|contact|assessment)/i.test(status)) {
    return "warning";
  }
  if (/(offer|passed|scheduled)/i.test(status)) {
    return "positive";
  }
  return "neutral";
}

const buttonStyle: React.CSSProperties = {
  border: `1px solid ${theme.colors.border}`,
  borderRadius: "12px",
  background: "rgba(255,255,255,0.04)",
  color: theme.colors.text,
  padding: "9px 12px",
  cursor: "pointer",
  fontWeight: 700,
};

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
  goals = [],
  traces = [],
  graphs = [],
  runningAction,
  syncingAction,
  onRunOnce,
  onQueueScreeningTask,
  onCreateGoal,
  onFlushSync,
  onSelectEpisode,
  onOpenCommunications,
  onOpenAgentInbox,
}: WorkbenchViewProps): JSX.Element {
  const { copy } = useI18n();
  const [goalTitle, setGoalTitle] = useState("");
  const [goalText, setGoalText] = useState("");

  const executionCards = useMemo(
    () =>
      data.episodes.map((episode) => {
        const plan = data.plans.find((item) => item.id === episode.executionPlanId);
        return {
          id: episode.id,
          title: plan?.name ?? episode.executionPlanId,
          summary: episode.resultSummary ?? copy("No summary yet.", "暂无执行摘要。"),
          status: episode.status,
          at: episode.updatedAt,
        };
      }),
    [copy, data.episodes, data.plans],
  );

  const timelineEvents = useMemo(
    () =>
      events.slice(-8).map((event) => ({
        id: event.id,
        label: translateUiToken(event.source, copy),
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
    [copy, events],
  );

  const activeCandidates = summary.candidates.filter((candidate) => !/(rejected|cooldown)/i.test(candidate.status));
  const waitingCommunications = summary.candidates.filter((candidate) => /(contact_required|contact_acquired|pending_communication|communicating|waiting_reply|resume_requested)/i.test(candidate.status));
  const pendingApprovals = summary.approvals.filter((approval) => approval.status === "pending").length;
  const latestGoal = goals[0] ?? null;
  const latestTrace = traces[0] ?? null;
  const latestGraph = graphs[0] ?? null;

  return (
    <div style={{ display: "grid", gap: "18px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "14px" }}>
        <MetricCard label={copy("Active candidates", "活跃候选人")} value={String(activeCandidates.length)} delta={copy("local-first progress", "本地优先进度")} tone="positive" caption={copy("candidate scoped", "候选人维度")} onClick={() => onOpenCommunications?.("active")} />
        <MetricCard label={copy("Communication queue", "沟通队列")} value={String(waitingCommunications.length)} delta={copy("waiting for follow-up", "等待跟进")} tone="warning" caption={copy("runtime inbox", "运行时收件箱")} onClick={() => onOpenCommunications?.("waiting")} />
        <MetricCard label={copy("Pending approvals", "待处理审批")} value={String(pendingApprovals)} delta={copy("runtime + evolution", "运行时 + 演进")} tone={pendingApprovals ? "warning" : "neutral"} caption={copy("desktop review", "桌面审查")} onClick={() => onOpenAgentInbox?.()} />
        <MetricCard label={copy("Queue depth", "任务队列深度")} value={String(agent.queueDepth)} delta={translateUiToken(agent.status, copy)} tone={agent.health === "healthy" ? "positive" : "warning"} caption={copy("agent runtime", "agent 运行时")} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.2fr) minmax(320px, 0.8fr)", gap: "18px", alignItems: "start" }}>
        <Panel
          title={copy("Candidate progress", "候选人进度")}
          eyebrow={copy("Structured progress store", "结构化进度库")}
          description={copy(
            "The workbench should stay centered on candidate progression and agent output.",
            "工作台应该始终聚焦候选人推进和 agent 输出。",
          )}
        >
          <div style={{ display: "grid", gap: "12px" }}>
            <ProgressBars stages={summary.pipeline} />
            <div style={{ display: "grid", gap: "10px" }}>
              {summary.candidates.map((candidate) => (
                <button key={candidate.id} type="button" onClick={() => onOpenCommunications?.("candidate", candidate.id)} style={{ borderRadius: "16px", border: `1px solid ${theme.colors.border}`, background: "rgba(255,255,255,0.03)", padding: "12px 14px", textAlign: "left", cursor: "pointer", color: "inherit" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", alignItems: "start", flexWrap: "wrap" }}>
                    <div>
                      <strong>{candidate.name}</strong>
                      <div style={{ color: theme.colors.muted, fontSize: "13px", marginTop: "5px" }}>
                        {candidate.title} · {candidate.jdTitle} · {candidate.location}
                      </div>
                    </div>
                    <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                      <StatusBadge tone={toneFromCandidateStatus(candidate.status)}>{translateUiToken(candidate.status, copy)}</StatusBadge>
                      <StatusBadge tone="neutral">{candidate.stageKey}</StatusBadge>
                      <StatusBadge tone="neutral">{copy(`score ${candidate.matchScore}`, `分数 ${candidate.matchScore}`)}</StatusBadge>
                    </div>
                  </div>
                  <div style={{ marginTop: "8px", color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>{candidate.nextAction}</div>
                  <div style={{ marginTop: "8px", display: "flex", gap: "8px", flexWrap: "wrap" }}>
                    {candidate.tags.map((tag) => (
                      <StatusBadge key={tag} tone="neutral">
                        {tag}
                      </StatusBadge>
                    ))}
                  </div>
                </button>
              ))}
            </div>
          </div>
        </Panel>

        <Panel
          title={copy("Agent controls", "Agent 控制")}
          eyebrow={copy("Operational actions", "运行操作")}
          description={copy(
            "Keep manual triggers small and explicit: run once, enqueue a screening task, or flush sync backlog.",
            "手动触发尽量保持小而明确：单次运行、排入初筛任务、重试同步积压。",
          )}
        >
          <div style={{ display: "grid", gap: "10px" }}>
            <button type="button" onClick={onRunOnce} disabled={Boolean(runningAction)} style={buttonStyle}>
              {runningAction ? copy("Running...", "执行中...") : copy("Run agent once", "单次运行 Agent")}
            </button>
            <button type="button" onClick={onQueueScreeningTask} disabled={Boolean(runningAction)} style={buttonStyle}>
              {copy("Start candidate review goal", "启动候选人评估目标")}
            </button>
            <div style={{ display: "grid", gap: "8px", marginTop: "4px" }}>
              <input
                value={goalTitle}
                onChange={(event) => setGoalTitle(event.target.value)}
                placeholder={copy("Goal title", "目标标题")}
                style={{
                  borderRadius: "10px",
                  border: `1px solid ${theme.colors.border}`,
                  background: "rgba(255,255,255,0.03)",
                  color: theme.colors.text,
                  padding: "9px 10px",
                }}
              />
              <textarea
                value={goalText}
                onChange={(event) => setGoalText(event.target.value)}
                placeholder={copy("Describe what the Recruit Agent should achieve in natural language.", "直接描述 Recruit Agent 要完成什么，系统会先探索路径再执行。")}
                rows={4}
                style={{
                  borderRadius: "10px",
                  border: `1px solid ${theme.colors.border}`,
                  background: "rgba(255,255,255,0.03)",
                  color: theme.colors.text,
                  padding: "9px 10px",
                  resize: "vertical",
                }}
              />
              <button
                type="button"
                disabled={Boolean(runningAction) || !goalTitle.trim() || !goalText.trim()}
                onClick={() => {
                  onCreateGoal?.({
                    title: goalTitle.trim(),
                    goalText: goalText.trim(),
                    summary: copy("Start with a small exploratory run, then distill reusable strategy.", "先用小规模探索 run 找路径，再提炼可复用策略。"),
                  });
                  setGoalTitle("");
                  setGoalText("");
                }}
                style={buttonStyle}
              >
                {copy("Start adaptive goal", "启动目标驱动任务")}
              </button>
            </div>
            {onFlushSync ? (
              <button type="button" onClick={onFlushSync} disabled={Boolean(syncingAction)} style={buttonStyle}>
                {syncingAction ? copy("Syncing...", "同步中...") : copy("Flush sync backlog", "重试同步积压")}
              </button>
            ) : null}
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              <StatusBadge tone={agent.health === "healthy" ? "positive" : agent.health === "warning" ? "warning" : "critical"}>
                {translateUiToken(agent.status, copy)}
              </StatusBadge>
              <StatusBadge tone="neutral">{agent.activeTask}</StatusBadge>
              <StatusBadge tone="neutral">{copy(`browser ${agent.browserLock}`, `浏览器 ${agent.browserLock}`)}</StatusBadge>
            </div>
            {syncStatus ? (
              <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                {copy(
                  `Sync ${syncStatus.remoteAvailable ? "available" : "offline"} · pending ${syncStatus.pendingCount} · failed ${syncStatus.failedDeliveryCount ?? 0}`,
                  `同步${syncStatus.remoteAvailable ? "可用" : "离线"} · 待处理 ${syncStatus.pendingCount} · 失败 ${syncStatus.failedDeliveryCount ?? 0}`,
                )}
              </div>
            ) : null}
            {latestGoal ? (
              <div style={{ borderRadius: "12px", border: `1px solid ${theme.colors.border}`, padding: "10px 12px", background: "rgba(255,255,255,0.02)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "8px" }}>
                  <strong>{latestGoal.title}</strong>
                  <StatusBadge tone={/blocked|failed/i.test(latestGoal.status) ? "warning" : "neutral"}>{translateUiToken(latestGoal.status, copy)}</StatusBadge>
                </div>
                <div style={{ marginTop: "6px", color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                  {latestGoal.summary ?? latestGoal.goalText}
                </div>
              </div>
            ) : null}
          </div>
        </Panel>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: "18px", alignItems: "start" }}>
        <Panel title={copy("Recent execution results", "最近执行结果")} eyebrow={copy("Agent runs", "Agent 运行记录")} description={copy("A run record still exists technically, but it is presented as the Recruit Agent's recent output.", "技术上仍保留运行记录，但产品上展示为 Recruit Agent 的最近输出。")}>
          <div style={{ display: "grid", gap: "10px" }}>
            {executionCards.map((card) => (
              <button
                key={card.id}
                type="button"
                onClick={() => onSelectEpisode?.(card.id)}
                style={{
                  cursor: "pointer",
                  textAlign: "left",
                  borderRadius: "16px",
                  border: `1px solid ${selectedEpisodeId === card.id ? "rgba(122,167,255,0.36)" : theme.colors.border}`,
                  background: selectedEpisodeId === card.id ? "rgba(122,167,255,0.12)" : "rgba(255,255,255,0.03)",
                  color: theme.colors.text,
                  padding: "12px 14px",
                  display: "grid",
                  gap: "8px",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", gap: "10px", alignItems: "start" }}>
                  <strong>{card.title}</strong>
                  <StatusBadge tone={/(confirmed|completed)/i.test(card.status) ? "positive" : /(pending|awaiting|running)/i.test(card.status) ? "warning" : "critical"}>
                    {translateUiToken(card.status, copy)}
                  </StatusBadge>
                </div>
                <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>{card.summary}</div>
                <div style={{ color: theme.colors.muted, fontSize: "12px" }}>{formatCompactDate(card.at)}</div>
              </button>
            ))}
          </div>
        </Panel>

        <Panel title={copy("Replay and diagnostics", "回放与诊断")} eyebrow={copy("Selected run", "当前运行")} description={copy("Inspect the selected run summary and its first snapshot to understand what the agent observed.", "查看当前运行摘要和首个快照，理解 agent 当时看到了什么。")}>
          {replay ? (
            <div style={{ display: "grid", gap: "10px" }}>
              <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                <StatusBadge tone="neutral">{replay.executionPlan?.name ?? replay.episode.executionPlanId}</StatusBadge>
                <StatusBadge tone="neutral">{replay.snapshots[0]?.title ?? copy("No snapshot yet", "暂无快照")}</StatusBadge>
              </div>
              <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                {replay.episode.resultSummary ?? copy("No replay summary yet.", "暂无回放摘要。")}
              </div>
              {replay.snapshots[0] ? (
                <article style={{ borderRadius: "16px", border: `1px solid ${theme.colors.border}`, background: "rgba(255,255,255,0.03)", padding: "12px 14px" }}>
                  <div style={{ fontWeight: 700 }}>{replay.snapshots[0].title ?? copy("Snapshot", "快照")}</div>
                  <div style={{ marginTop: "6px", color: theme.colors.muted, fontSize: "13px" }}>
                    {replay.snapshots[0].url ?? copy("No URL", "无 URL")}
                  </div>
                </article>
              ) : null}
            </div>
          ) : (
            <div style={{ color: theme.colors.muted }}>{copy("Select a run to load replay diagnostics.", "选择一条运行记录查看回放诊断。")}</div>
          )}
        </Panel>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: "18px", alignItems: "start" }}>
        <Panel title={copy("Adaptive runtime", "目标驱动运行时")} eyebrow={copy("Goals, traces, graphs", "目标、轨迹、执行图")} description={copy("Goals are the new runtime entry. The graph is for human interpretation, while trace and strategy assets drive execution.", "目标是新的运行时入口；图用于解释，真正驱动执行的是 trace 和策略资产。")}>
          <div style={{ display: "grid", gap: "12px" }}>
            {latestGoal ? (
              <article style={{ borderRadius: "14px", border: `1px solid ${theme.colors.border}`, background: "rgba(255,255,255,0.03)", padding: "12px 14px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "8px", alignItems: "start" }}>
                  <strong>{latestGoal.title}</strong>
                  <StatusBadge tone={/blocked|failed/i.test(latestGoal.status) ? "warning" : "neutral"}>{translateUiToken(latestGoal.status, copy)}</StatusBadge>
                </div>
                <div style={{ color: theme.colors.muted, fontSize: "13px", marginTop: "6px", lineHeight: 1.6 }}>{latestGoal.goalText}</div>
                {latestTrace ? (
                  <div style={{ color: theme.colors.muted, fontSize: "12px", marginTop: "8px" }}>
                    {copy("Latest trace", "最近轨迹")} · {latestTrace.summary ?? latestTrace.status}
                  </div>
                ) : null}
                {latestGraph?.renderedText ? (
                  <pre style={{ marginTop: "10px", padding: "10px 12px", borderRadius: "12px", background: "rgba(5,10,18,0.65)", color: "#d9e5ff", fontSize: "12px", overflowX: "auto" }}>
                    {latestGraph.renderedText}
                  </pre>
                ) : null}
              </article>
            ) : (
              <div style={{ color: theme.colors.muted }}>{copy("No adaptive goal yet. Create one from the right panel.", "还没有目标驱动任务。可在右侧面板直接创建。")}</div>
            )}
          </div>
        </Panel>

        <Panel title={copy("Live event stream", "实时事件流")} eyebrow={copy("Operator visibility", "操作员可见性")} description={copy("Recent Recruit Agent signals from the local runtime.", "来自本地运行时的最近 Recruit Agent 信号。")}>
          <Timeline events={timelineEvents} />
        </Panel>

        <Panel title={copy("Queue and sync", "队列与同步")} eyebrow={copy("Operational backlog", "操作积压")} description={copy("Observe local queue pressure and sync backlog without leaving the workbench.", "不离开工作台即可观察本地队列压力和同步积压。")}>
          <div style={{ display: "grid", gap: "12px" }}>
            <div>
              <div style={{ fontWeight: 700, marginBottom: "8px" }}>{copy("Queue", "任务队列")}</div>
              <div style={{ display: "grid", gap: "8px" }}>
                {queueItems.slice(0, 4).map((item) => (
                  <article key={item.taskId} style={{ borderRadius: "14px", border: `1px solid ${theme.colors.border}`, background: "rgba(255,255,255,0.03)", padding: "10px 12px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: "8px" }}>
                      <strong>{item.taskType}</strong>
                      <StatusBadge tone="neutral">{item.status}</StatusBadge>
                    </div>
                    <div style={{ color: theme.colors.muted, fontSize: "12px", marginTop: "6px" }}>
                      {item.candidateId ?? copy("global task", "全局任务")} · {copy(`priority ${item.priority}`, `优先级 ${item.priority}`)}
                    </div>
                  </article>
                ))}
              </div>
            </div>

            <div>
              <div style={{ fontWeight: 700, marginBottom: "8px" }}>{copy("Sync backlog", "同步积压")}</div>
              <div style={{ display: "grid", gap: "8px" }}>
                {syncBacklog.slice(0, 4).map((item) => (
                  <article key={item.id} style={{ borderRadius: "14px", border: `1px solid ${theme.colors.border}`, background: "rgba(255,255,255,0.03)", padding: "10px 12px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: "8px" }}>
                      <strong>{item.entityType}</strong>
                      <StatusBadge tone={item.status === "pending" ? "warning" : item.status === "failed" ? "critical" : "positive"}>
                        {item.status}
                      </StatusBadge>
                    </div>
                    <div style={{ color: theme.colors.muted, fontSize: "12px", marginTop: "6px", lineHeight: 1.5 }}>{item.payloadSummary}</div>
                  </article>
                ))}
              </div>
            </div>
          </div>
        </Panel>
      </div>
    </div>
  );
}
