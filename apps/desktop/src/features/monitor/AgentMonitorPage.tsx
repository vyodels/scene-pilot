import { useEffect, useState } from "react";
import { Panel, StatusBadge } from "../../components";
import { apiClient } from "../../lib/api";
import { formatCompactDate } from "../../lib/format";
import type { AgentEvent } from "../../lib/types";
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
  const [agent, setAgent] = useState<Awaited<ReturnType<typeof apiClient.getAgentSnapshot>> | null>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefreshedAt, setLastRefreshedAt] = useState<string | null>(null);
  const [runningAction, setRunningAction] = useState(false);

  const loadMonitor = async () => {
    setLoading(true);
    try {
      const [nextSummary, nextAgent] = await Promise.all([apiClient.getDashboardSummary(), apiClient.getAgentSnapshot()]);
      setAgent(nextAgent);
      const nextEvents: AgentEvent[] = [
        ...nextSummary.timeline.map((event) => ({
          id: event.id,
          level: toAgentEventLevel(event.tone),
          source: "workflow",
          message: event.label,
          at: event.at,
        })),
        ...nextSummary.alerts.map((event) => ({
          id: event.id,
          level: toAgentEventLevel(event.tone),
          source: "alert",
          message: event.detail,
          at: event.at,
        })),
      ];
      setEvents(nextEvents);
      setError(null);
      setLastRefreshedAt(new Date().toISOString());
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load agent monitor.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadMonitor();
  }, []);

  if (loading && agent === null) {
    return (
      <Panel title="Agent runtime" eyebrow="Monitor" description="Loading agent state from the local backend...">
        <div style={{ color: "rgba(233,239,255,0.72)", fontSize: "14px" }}>Synchronizing runtime state.</div>
      </Panel>
    );
  }

  return (
    <div style={{ display: "grid", gap: "16px" }}>
      {error ? (
        <Panel
          title="Agent runtime"
          eyebrow="Monitor"
          description="The desktop client could not refresh the agent monitor from the backend."
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
              Retry
            </button>
          </div>
        </Panel>
      ) : null}

      <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", alignItems: "center" }}>
        <div style={{ color: "rgba(233,239,255,0.72)", fontSize: "13px" }}>
          {loading
            ? "Refreshing agent monitor..."
            : lastRefreshedAt
              ? `Last refreshed ${formatCompactDate(lastRefreshedAt)}`
              : "Agent monitor is loaded from the backend."}
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
          {loading ? "Refreshing..." : "Refresh"}
        </button>
      </div>

      {agent ? (
        <AgentMonitorView
          agent={agent}
          events={events}
          runningAction={runningAction}
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
                payload: { jd_criteria: firstCandidate?.jdTitle ?? "Frontend Platform Engineer" },
                priority: 180,
                candidateId: firstCandidate?.id,
                workflowNodeId: "initial_screening",
              });
              await loadMonitor();
            } finally {
              setRunningAction(false);
            }
          }}
        />
      ) : null}
    </div>
  );
}
