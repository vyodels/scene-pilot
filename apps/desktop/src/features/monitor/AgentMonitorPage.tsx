import { useEffect, useState } from "react";
import { Panel, StatusBadge } from "../../components";
import { apiClient } from "../../lib/api";
import { formatCompactDate } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { desktopAgentQueueMock, desktopMockSnapshot, desktopReplayMockByEpisode, desktopRuntimeMock, desktopSyncBacklogMock, desktopSyncStatusMock } from "../../lib/mockData";
import type { AgentEvent, AgentQueueItem, RuntimeEpisode, RuntimeEpisodeReplay, SyncBacklogItem, SyncStatusSnapshot } from "../../lib/types";
import { AgentMonitorView } from "../agent-monitor/AgentMonitorView";

function toAgentEventLevel(tone: "positive" | "neutral" | "warning" | "critical"): AgentEvent["level"] {
  if (tone === "critical") {
    return "error";
  }
  if (tone === "warning") {
    return "warning";
  }
  if (tone === "positive") {
    return "success";
  }
  return "info";
}

export function AgentMonitorPage() {
  const { copy } = useI18n();
  const [agent, setAgent] = useState<Awaited<ReturnType<typeof apiClient.getAgentSnapshot>> | null>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefreshedAt, setLastRefreshedAt] = useState<string | null>(null);
  const [runningAction, setRunningAction] = useState(false);
  const [syncingAction, setSyncingAction] = useState(false);
  const [episodes, setEpisodes] = useState<RuntimeEpisode[]>([]);
  const [selectedEpisodeId, setSelectedEpisodeId] = useState<string | undefined>();
  const [replay, setReplay] = useState<RuntimeEpisodeReplay | null>(desktopReplayMockByEpisode["episode-001"]);
  const [syncStatus, setSyncStatus] = useState<SyncStatusSnapshot>(desktopSyncStatusMock);
  const [syncBacklog, setSyncBacklog] = useState<SyncBacklogItem[]>(desktopSyncBacklogMock);
  const [queueItems, setQueueItems] = useState<AgentQueueItem[]>(desktopAgentQueueMock);

  const loadMonitor = async () => {
    setLoading(true);
    try {
      const [nextSummary, nextAgent, nextEpisodes, nextSyncStatus, nextSyncBacklog, nextQueueItems] = await Promise.all([
        apiClient.getDashboardSummary(),
        apiClient.getAgentSnapshot(),
        apiClient.listRuntimeEpisodes(),
        apiClient.getSyncStatus(),
        apiClient.listSyncBacklog(),
        apiClient.listAgentQueue(),
      ]);
      setAgent(nextAgent);
      setEpisodes(nextEpisodes);
      setSyncStatus(nextSyncStatus);
      setSyncBacklog(nextSyncBacklog);
      setQueueItems(nextQueueItems);
      setSelectedEpisodeId((current) => current ?? nextEpisodes[0]?.id);
      const nextEvents: AgentEvent[] = [
        ...nextSummary.timeline.map((event) => ({
          id: event.id,
          level: toAgentEventLevel(event.tone),
          source: "工作流",
          message: event.label,
          at: event.at,
        })),
        ...nextSummary.alerts.map((event) => ({
          id: event.id,
          level: toAgentEventLevel(event.tone),
          source: "告警",
          message: event.detail,
          at: event.at,
        })),
      ];
      setEvents(nextEvents);
      setError(null);
      setLastRefreshedAt(new Date().toISOString());
    } catch (loadError) {
      setAgent(desktopMockSnapshot.agent);
      setEpisodes(desktopRuntimeMock.episodes);
      setSyncStatus(desktopSyncStatusMock);
      setSyncBacklog(desktopSyncBacklogMock);
      setQueueItems(desktopAgentQueueMock);
      setSelectedEpisodeId((current) => current ?? desktopRuntimeMock.episodes[0]?.id);
      setEvents([
        ...desktopMockSnapshot.timeline.map((event) => ({
          id: event.id,
          level: toAgentEventLevel(event.tone),
          source: "工作流",
          message: event.label,
          at: event.at,
        })),
        ...desktopMockSnapshot.alerts.map((event) => ({
          id: event.id,
          level: toAgentEventLevel(event.tone),
          source: "告警",
          message: event.detail,
          at: event.at,
        })),
      ]);
      setError(loadError instanceof Error ? loadError.message : copy("Failed to load agent monitor.", "加载 Agent 监控失败。"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadMonitor();
  }, []);

  useEffect(() => {
    const episodeId = selectedEpisodeId ?? episodes[0]?.id;
    if (!episodeId) {
      setReplay(null);
      return;
    }
    let active = true;
    void (async () => {
      try {
        const nextReplay = await apiClient.getRuntimeReplay(episodeId);
        if (active) {
          setReplay(nextReplay);
        }
      } catch {
        if (active) {
          setReplay(desktopReplayMockByEpisode[episodeId] ?? desktopReplayMockByEpisode["episode-001"] ?? null);
        }
      }
    })();
    return () => {
      active = false;
    };
  }, [episodes, selectedEpisodeId]);

  if (loading && agent === null) {
    return (
      <Panel title={copy("Agent runtime", "Agent 运行态")} eyebrow={copy("Monitor", "监控")} description={copy("Loading agent state from the local backend...", "正在从本地后端加载 Agent 状态...")}>
        <div style={{ color: "rgba(233,239,255,0.72)", fontSize: "14px" }}>{copy("Synchronizing runtime state.", "正在同步运行时状态。")}</div>
      </Panel>
    );
  }

  return (
    <div style={{ display: "grid", gap: "16px" }}>
      {error ? (
        <Panel
          title={copy("Agent runtime", "Agent 运行态")}
          eyebrow={copy("Monitor", "监控")}
          description={copy("The desktop client could not refresh the agent monitor from the backend.", "桌面客户端无法从后端刷新 Agent 监控数据。")}
          actions={<StatusBadge tone="critical">error</StatusBadge>}
        >
          <div style={{ display: "grid", gap: "12px" }}>
            <div style={{ color: "rgba(233,239,255,0.78)", lineHeight: 1.6 }}>{error}</div>
            <button
              type="button"
              onClick={() => void loadMonitor()}
              style={{
                alignSelf: "start",
                border: "1px solid rgba(255,255,255,0.12)",
                borderRadius: "12px",
                background: "rgba(122,167,255,0.18)",
                color: "#eef3ff",
                padding: "10px 14px",
                cursor: "pointer",
                fontWeight: 700,
              }}
            >
              {copy("Retry", "重试")}
            </button>
          </div>
        </Panel>
      ) : null}

      <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", alignItems: "center" }}>
        <div style={{ color: "rgba(233,239,255,0.72)", fontSize: "13px" }}>
          {loading
            ? copy("Refreshing agent monitor...", "正在刷新 Agent 监控...")
            : lastRefreshedAt
              ? copy(`Last refreshed ${formatCompactDate(lastRefreshedAt)}`, `最近刷新于 ${formatCompactDate(lastRefreshedAt)}`)
              : copy("Agent monitor is loaded from the backend.", "Agent 监控已从后端加载。")}
        </div>
        <button
          type="button"
          onClick={() => void loadMonitor()}
          disabled={loading}
          style={{
            border: "1px solid rgba(255,255,255,0.12)",
            borderRadius: "12px",
            background: "rgba(122,167,255,0.18)",
            color: "#eef3ff",
            padding: "10px 14px",
            cursor: loading ? "not-allowed" : "pointer",
            fontWeight: 700,
          }}
        >
          {loading ? copy("Refreshing...", "刷新中...") : copy("Refresh", "刷新")}
        </button>
      </div>

      {agent ? (
        <AgentMonitorView
          agent={agent}
          events={events}
          episodes={episodes}
          selectedEpisodeId={selectedEpisodeId}
          replay={replay}
          syncStatus={syncStatus}
          syncBacklog={syncBacklog}
          queueItems={queueItems}
          runningAction={runningAction}
          syncingAction={syncingAction}
          onRunOnce={async () => {
            setRunningAction(true);
            try {
              await apiClient.runAgentOnce();
              await loadMonitor();
            } finally {
              setRunningAction(false);
            }
          }}
          onQueueScreeningTask={async () => {
            setRunningAction(true);
            try {
              const summary = await apiClient.getDashboardSummary();
              const firstCandidate = summary.candidates[0];
              await apiClient.queueTask({
                taskType: "initial_screening",
                payload: { jd_criteria: firstCandidate?.jdTitle ?? "前端平台工程师" },
                priority: 180,
                candidateId: firstCandidate?.id,
                workflowNodeId: "initial_screening",
              });
              await loadMonitor();
            } finally {
              setRunningAction(false);
            }
          }}
          onFlushSync={async () => {
            setSyncingAction(true);
            try {
              await apiClient.flushSyncBacklog();
              await loadMonitor();
            } finally {
              setSyncingAction(false);
            }
          }}
          onSelectEpisode={setSelectedEpisodeId}
        />
      ) : null}
    </div>
  );
}
