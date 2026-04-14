import React from "react";
import { Panel, StatusBadge, Timeline } from "../../components";
import { formatCompactDate } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { translateUiToken } from "../../lib/uiText";
import { theme } from "../../lib/theme";
import type { AgentEvent, AgentQueueItem, AgentSnapshot, RuntimeEpisode, RuntimeEpisodeReplay, SyncBacklogItem, SyncStatusSnapshot } from "../../lib/types";

interface AgentMonitorViewProps {
  agent: AgentSnapshot;
  events: AgentEvent[];
  episodes?: RuntimeEpisode[];
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

const actionButtonStyle = {
  border: "1px solid rgba(255,255,255,0.12)",
  borderRadius: "12px",
  background: "rgba(122,167,255,0.18)",
  color: "#eef3ff",
  padding: "10px 12px",
  cursor: "pointer",
  fontWeight: 700,
} as const;

function backlogTone(status: string): "positive" | "neutral" | "warning" | "critical" {
  if (/(error|failed)/i.test(status)) {
    return "critical";
  }
  if (/(pending|retry|queued)/i.test(status)) {
    return "warning";
  }
  if (/(synced|completed)/i.test(status)) {
    return "positive";
  }
  return "neutral";
}

function syncModeDescription(syncStatus: SyncStatusSnapshot | null | undefined, copy: (en: string, zh: string) => string): string {
  if (!syncStatus) {
    return copy("No sync status available.", "暂无同步状态。");
  }
  if (!syncStatus.enabled) {
    return copy("Remote sync is disabled. Pending sync items stay local until an intranet target is enabled.", "远端同步未启用。待同步内容会继续保留在本地，直到启用内网目标。");
  }
  if (!syncStatus.remoteAvailable) {
    return copy("Remote sync is enabled, but the target is currently unavailable.", "远端同步已启用，但当前目标不可用。");
  }
  return copy("Remote sync is enabled and reachable.", "远端同步已启用且可达。");
}

export function AgentMonitorView({
  agent,
  events,
  episodes = [],
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
}: AgentMonitorViewProps): JSX.Element {
  const { copy } = useI18n();

  return (
    <div style={{ display: "grid", gap: "18px" }}>
      <div style={{ display: "grid", gap: "18px", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))" }}>
        <Panel
          title={copy("Runtime operations", "运行控制")}
          eyebrow={copy("Serialized execution", "串行执行")}
          description={copy("Current run state, browser lock status, and direct operator actions for the local workbench.", "本地工作台当前的运行状态、浏览器锁状态，以及可直接触发的操作动作。")}
          actions={
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              <button type="button" onClick={onQueueScreeningTask} disabled={runningAction} style={actionButtonStyle}>
                {copy("Queue recruiting task", "加入招聘工作流")}
              </button>
              <button type="button" onClick={onRunOnce} disabled={runningAction} style={actionButtonStyle}>
                {runningAction ? copy("Running...", "运行中...") : copy("Run next task", "运行下一个任务")}
              </button>
            </div>
          }
        >
          <div style={{ display: "grid", gap: "12px" }}>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              <StatusBadge tone={agent.status === "running" ? "positive" : agent.status === "waiting_human" ? "warning" : "neutral"}>{translateUiToken(agent.status, copy)}</StatusBadge>
              <StatusBadge tone={agent.browserLock === "held" ? "warning" : "positive"}>{translateUiToken(agent.browserLock, copy)}</StatusBadge>
              <StatusBadge tone={agent.health === "healthy" ? "positive" : agent.health === "warning" ? "warning" : "critical"}>{translateUiToken(agent.health, copy)}</StatusBadge>
            </div>
            <div style={{ display: "grid", gap: "8px", color: "rgba(233,239,255,0.72)", fontSize: "13px" }}>
              <div>{copy("Active task", "当前任务")}: {agent.activeTask}</div>
              <div>{copy("Uptime", "运行时长")}: {agent.uptime}</div>
              <div>{copy("Queue depth", "队列深度")}: {agent.queueDepth}</div>
              <div>{copy("Token budget used", "Token 预算使用")}: {agent.tokenBudgetUsed}%</div>
            </div>
          </div>
        </Panel>
        <Panel title={copy("Sync queue", "同步积压")} eyebrow={copy("Local-First Sync", "本地优先同步")} description={copy("Local queued sync state and manual retry controls for optional intranet sync.", "用于可选内网同步的本地积压状态与手动重试控制。")}>
          <div style={{ display: "grid", gap: "12px" }}>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              <StatusBadge tone={syncStatus?.enabled ? "positive" : "neutral"}>{translateUiToken(syncStatus?.mode ?? "local_only", copy)}</StatusBadge>
              <StatusBadge tone={syncStatus?.remoteAvailable ? "positive" : "warning"}>
                {syncStatus?.remoteAvailable ? copy("remote reachable", "远端可达") : copy("remote unavailable", "远端不可达")}
              </StatusBadge>
              <StatusBadge tone={syncStatus?.pendingCount ? "warning" : "positive"}>
                {copy(`${syncStatus?.pendingCount ?? syncBacklog.length} pending`, `${syncStatus?.pendingCount ?? syncBacklog.length} 个待处理`)}
              </StatusBadge>
              {syncStatus?.failedDeliveryCount ? (
                <StatusBadge tone="warning">{copy(`${syncStatus.failedDeliveryCount} failed deliveries`, `${syncStatus.failedDeliveryCount} 个投递失败`)}</StatusBadge>
              ) : null}
              {syncStatus?.deferredCount ? <StatusBadge tone="neutral">{copy(`${syncStatus.deferredCount} deferred`, `${syncStatus.deferredCount} 个已延期`)}</StatusBadge> : null}
            </div>
            <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
              {syncStatus?.recentErrors[0] ?? syncStatus?.latestError ?? syncModeDescription(syncStatus, copy)}
            </div>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              {syncStatus?.protocolVersion ? <StatusBadge tone="neutral">{copy(`protocol ${syncStatus.protocolVersion}`, `协议 ${syncStatus.protocolVersion}`)}</StatusBadge> : null}
              {syncStatus?.source ? <StatusBadge tone="neutral">{copy(`source ${syncStatus.source}`, `来源 ${syncStatus.source}`)}</StatusBadge> : null}
              {typeof syncStatus?.backlogTotal === "number" ? <StatusBadge tone="neutral">{copy(`${syncStatus.backlogTotal} total`, `总计 ${syncStatus.backlogTotal}`)}</StatusBadge> : null}
              {syncStatus?.lastAttemptAt ? <StatusBadge tone="neutral">{copy(`Last attempt ${formatCompactDate(syncStatus.lastAttemptAt)}`, `最近尝试于 ${formatCompactDate(syncStatus.lastAttemptAt)}`)}</StatusBadge> : null}
              {syncStatus?.lastSuccessAt ? <StatusBadge tone="neutral">{copy(`Last success ${formatCompactDate(syncStatus.lastSuccessAt)}`, `最近成功于 ${formatCompactDate(syncStatus.lastSuccessAt)}`)}</StatusBadge> : null}
              {syncStatus?.nextAttemptAt ? <StatusBadge tone="neutral">{copy(`Next retry ${formatCompactDate(syncStatus.nextAttemptAt)}`, `下次重试 ${formatCompactDate(syncStatus.nextAttemptAt)}`)}</StatusBadge> : null}
            </div>
            {syncStatus?.byStatus && Object.keys(syncStatus.byStatus).length ? (
              <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                {copy("Status mix", "状态分布")}: {Object.entries(syncStatus.byStatus).map(([key, value]) => `${translateUiToken(key, copy)}=${value}`).join(" · ")}
              </div>
            ) : null}
            {onFlushSync ? (
              <button type="button" onClick={onFlushSync} disabled={syncingAction} style={actionButtonStyle}>
                {syncingAction ? copy("Retrying...", "重试中...") : copy("Retry queued sync", "重试同步积压")}
              </button>
            ) : null}
          </div>
        </Panel>
      </div>

      <Panel title={copy("Queue audit", "队列审计")} eyebrow={copy("Persistent queue", "持久化队列")} description={copy("Recent queued work and lifecycle audit emitted by the serialized scheduler.", "串行调度器输出的近期排队工作和生命周期审计。")}>
        <div style={{ display: "grid", gap: "12px" }}>
          {queueItems.length ? (
            queueItems.slice(0, 4).map((item) => (
              <article
                key={item.taskId}
                style={{
                  padding: "12px",
                  borderRadius: "14px",
                  border: "1px solid rgba(255,255,255,0.08)",
                  background: "rgba(255,255,255,0.03)",
                  display: "grid",
                  gap: "6px",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", gap: "8px", flexWrap: "wrap" }}>
                  <strong>{item.taskType}</strong>
                  <StatusBadge tone={backlogTone(item.status)}>{translateUiToken(item.status, copy)}</StatusBadge>
                </div>
                <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.5 }}>
                  {item.taskId}
                  {item.candidateId ? copy(` · candidate ${item.candidateId}`, ` · 候选人 ${item.candidateId}`) : ""}
                  {item.workflowNodeId ? copy(` · node ${item.workflowNodeId}`, ` · 节点 ${item.workflowNodeId}`) : ""}
                </div>
                <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                  <StatusBadge tone="neutral">{copy(`priority ${item.priority}`, `优先级 ${item.priority}`)}</StatusBadge>
                  <StatusBadge tone="neutral">{copy(`attempts ${item.attempts}`, `尝试 ${item.attempts}`)}</StatusBadge>
                </div>
                {item.queueAudit.length ? (
                  <div style={{ color: theme.colors.muted, fontSize: "12px", lineHeight: 1.6 }}>
                    {copy("Audit", "审计")}:{" "}
                    {item.queueAudit
                      .slice(-3)
                      .map((entry) => `${entry.kind}${entry.error ? ` (${entry.error})` : ""}`)
                      .join(" → ")}
                  </div>
                ) : null}
              </article>
            ))
          ) : (
            <div style={{ color: theme.colors.muted, fontSize: "13px" }}>{copy("Queue audit will appear after the scheduler persists work items.", "调度器持久化工作项后，这里会显示队列审计。")}</div>
          )}
        </div>
      </Panel>

      <div style={{ display: "grid", gap: "18px", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))" }}>
        <Panel title={copy("Replay diagnostics", "回放诊断")} eyebrow={copy("Workflow instance replay", "工作流实例回放")} description={copy("Select a supervised workflow instance to inspect divergence, snapshots, and derived learning artifacts.", "选择一个受监督工作流实例，检查偏差、快照和衍生学习产物。")}>
          <div style={{ display: "grid", gap: "12px" }}>
            {episodes.length ? (
              <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                {episodes.slice(0, 6).map((episode) => (
                  <button
                    key={episode.id}
                    type="button"
                    onClick={() => onSelectEpisode?.(episode.id)}
                    style={{
                      ...actionButtonStyle,
                      background: selectedEpisodeId === episode.id ? "rgba(122,167,255,0.28)" : "rgba(255,255,255,0.04)",
                    }}
                  >
                    {episode.id}
                  </button>
                ))}
              </div>
            ) : null}
            {replay ? (
              <div style={{ display: "grid", gap: "12px" }}>
                <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                  <StatusBadge tone={replay.episode.divergenceDetected ? "critical" : "positive"}>{translateUiToken(replay.episode.status, copy)}</StatusBadge>
                  {replay.patch ? <StatusBadge tone="warning">{copy("revision proposed", "已提出修订建议")}</StatusBadge> : null}
                  {replay.template ? <StatusBadge tone="positive">{copy("version ready", "版本已就绪")}</StatusBadge> : null}
                  {replay.approval ? <StatusBadge tone="warning">{copy("approval pending", "审批待处理")}</StatusBadge> : null}
                </div>
                <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                  {replay.episode.resultSummary ?? copy("No replay summary available.", "暂无回放摘要。")}
                </div>
                <Timeline events={replay.diagnostics} />
              </div>
            ) : (
              <div style={{ color: theme.colors.muted, fontSize: "13px" }}>{copy("Replay diagnostics will appear after you select a workflow instance.", "选择工作流实例后，这里会显示回放诊断。")}</div>
            )}
          </div>
        </Panel>
        <Panel title={copy("Replay context", "回放上下文")} eyebrow={copy("Snapshots and sync queue", "快照与同步积压")} description={copy("Captured environment state and the newest local queued sync entries.", "捕获的环境状态与最新本地同步积压条目。")}>
          <div style={{ display: "grid", gap: "12px" }}>
            {replay?.snapshots?.length ? (
              replay.snapshots.map((snapshot) => (
                <article
                  key={snapshot.id}
                  style={{
                    padding: "14px",
                    borderRadius: "16px",
                    border: "1px solid rgba(255,255,255,0.08)",
                    background: "rgba(255,255,255,0.03)",
                    display: "grid",
                    gap: "8px",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: "8px", flexWrap: "wrap" }}>
                    <strong>{snapshot.title ?? snapshot.environmentKey ?? snapshot.id}</strong>
                    <StatusBadge tone="neutral">{snapshot.pageType ?? snapshot.source}</StatusBadge>
                  </div>
                  <div style={{ color: theme.colors.muted, fontSize: "13px" }}>{snapshot.url ?? copy("No URL captured.", "未捕获 URL。")}</div>
                </article>
              ))
            ) : (
              <div style={{ color: theme.colors.muted, fontSize: "13px" }}>{copy("No replay snapshots available for the selected episode.", "所选 episode 暂无回放快照。")}</div>
            )}
            <div style={{ display: "grid", gap: "8px" }}>
              {syncBacklog.slice(0, 3).map((item) => (
                <article
                  key={item.id}
                  style={{
                    padding: "12px",
                    borderRadius: "14px",
                    border: "1px solid rgba(255,255,255,0.08)",
                    background: "rgba(255,255,255,0.03)",
                    display: "grid",
                    gap: "6px",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: "8px", flexWrap: "wrap" }}>
                    <strong>{item.entityType}</strong>
                    <StatusBadge tone={backlogTone(item.status)}>{translateUiToken(item.status, copy)}</StatusBadge>
                  </div>
                  <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.5 }}>
                    {item.payloadSummary ?? item.target}
                  </div>
                  <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                    <StatusBadge tone="neutral">{item.target}</StatusBadge>
                    <StatusBadge tone="neutral">{copy(`attempts ${item.attemptCount}`, `尝试 ${item.attemptCount}`)}</StatusBadge>
                    {item.deliveryMode ? <StatusBadge tone="neutral">{item.deliveryMode}</StatusBadge> : null}
                    {item.protocolVersion ? <StatusBadge tone="neutral">{copy(`protocol ${item.protocolVersion}`, `协议 ${item.protocolVersion}`)}</StatusBadge> : null}
                  </div>
                  {(item.lastAttemptedAt || item.nextAttemptAt || item.lastError) ? (
                    <div style={{ color: theme.colors.muted, fontSize: "12px", lineHeight: 1.6 }}>
                      {item.lastAttemptedAt ? copy(`Last attempt ${formatCompactDate(item.lastAttemptedAt)} · `, `最近尝试于 ${formatCompactDate(item.lastAttemptedAt)} · `) : ""}
                      {item.nextAttemptAt ? copy(`Next retry ${formatCompactDate(item.nextAttemptAt)} · `, `下次重试 ${formatCompactDate(item.nextAttemptAt)} · `) : ""}
                      {item.lastError ? copy(`Error: ${item.lastError}`, `错误：${item.lastError}`) : copy("No delivery error recorded.", "未记录投递错误。")}
                    </div>
                  ) : null}
                </article>
              ))}
            </div>
          </div>
        </Panel>
      </div>

      <Panel title={copy("Runtime events", "运行时事件")} eyebrow={copy("Agent stream", "Agent 事件流")} description={copy("Events that can be surfaced in the final desktop event stream.", "可在桌面事件流中展示的运行时事件。")}>
        <Timeline
          events={events.map((event) => ({
            id: event.id,
            label: `${event.source}: ${event.message}`,
            detail: event.message,
            at: event.at,
            tone: event.level === "error" ? "critical" : event.level === "warning" ? "warning" : event.level === "success" ? "positive" : "neutral",
          }))}
        />
      </Panel>
    </div>
  );
}
