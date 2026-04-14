import React from "react";
import { Panel, StatusBadge, Timeline } from "../../components";
import type { AgentEvent, AgentSnapshot } from "../../lib/types";

interface AgentMonitorViewProps {
  agent: AgentSnapshot;
  events: AgentEvent[];
  runningAction?: boolean;
  onRunOnce(): void;
  onQueueScreeningTask(): void;
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

export function AgentMonitorView({
  agent,
  events,
  runningAction,
  onRunOnce,
  onQueueScreeningTask,
}: AgentMonitorViewProps): JSX.Element {
  return (
    <div style={{ display: "grid", gap: "18px", gridTemplateColumns: "minmax(0, 1.1fr) minmax(320px, 0.9fr)" }}>
      <Panel
        title="Agent runtime"
        eyebrow="Serialized execution"
        description="Current run state and browser lock status."
        actions={
          <div style={{ display: "flex", gap: "8px" }}>
            <button type="button" onClick={onQueueScreeningTask} disabled={runningAction} style={actionButtonStyle}>
              Queue recruiting task
            </button>
            <button type="button" onClick={onRunOnce} disabled={runningAction} style={actionButtonStyle}>
              {runningAction ? "Running..." : "Run next task"}
            </button>
          </div>
        }
      >
        <div style={{ display: "grid", gap: "12px" }}>
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
            <StatusBadge tone={agent.status === "running" ? "positive" : agent.status === "waiting_human" ? "warning" : "neutral"}>{agent.status}</StatusBadge>
            <StatusBadge tone={agent.browserLock === "held" ? "warning" : "positive"}>{agent.browserLock}</StatusBadge>
            <StatusBadge tone={agent.health === "healthy" ? "positive" : agent.health === "warning" ? "warning" : "critical"}>{agent.health}</StatusBadge>
          </div>
          <div style={{ display: "grid", gap: "8px", color: "rgba(233,239,255,0.72)", fontSize: "13px" }}>
            <div>Active task: {agent.activeTask}</div>
            <div>Uptime: {agent.uptime}</div>
            <div>Queue depth: {agent.queueDepth}</div>
            <div>Token budget used: {agent.tokenBudgetUsed}%</div>
          </div>
        </div>
      </Panel>
      <Panel title="Runtime events" eyebrow="Agent stream" description="Events that can be surfaced in the final desktop event stream.">
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
