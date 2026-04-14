import React, { startTransition, useEffect, useMemo, useState } from "react";
import { Sidebar, TopBar } from "../../components";
import { apiClient } from "../../lib/api";
import { desktopMockSnapshot } from "../../lib/mockData";
import type { AgentEvent, DashboardSummary, WorkspaceTab } from "../../lib/types";
import { AgentMonitorView } from "../agent-monitor/AgentMonitorView";
import { ApprovalsView } from "../approvals/ApprovalsView";
import { CandidatesView } from "../candidates/CandidatesView";
import { DashboardView } from "../dashboard/DashboardView";
import { SettingsView } from "../settings/SettingsView";
import { SkillsView } from "../skills/SkillsView";
import { WorkflowsView } from "../workflows/WorkflowsView";
import { theme } from "../../lib/theme";

export function DesktopWorkspace(): JSX.Element {
  const [tab, setTab] = useState<WorkspaceTab>("dashboard");
  const [summary, setSummary] = useState<DashboardSummary>(desktopMockSnapshot);
  const [events, setEvents] = useState<AgentEvent[]>([
    { id: "stream-001", level: "info", source: "bootstrap", message: "Workspace loaded from mock snapshot.", at: "now" },
    { id: "stream-002", level: "warning", source: "scheduler", message: "One approval gate is waiting.", at: "now" },
  ]);
  const [refreshing, setRefreshing] = useState(false);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [approvalActionId, setApprovalActionId] = useState<string>();
  const [runtimeActionBusy, setRuntimeActionBusy] = useState(false);
  const [transport, setTransport] = useState(apiClient.describe().transport);
  const [errorMessage, setErrorMessage] = useState<string>();

  const appendEvent = (event: AgentEvent) => {
    setEvents((current) => [...current.slice(-29), event]);
  };

  const loadSummary = async (reason?: string) => {
    setRefreshing(true);
    try {
      const [nextSummary, nextAgent] = await Promise.all([apiClient.getDashboardSummary(), apiClient.getAgentSnapshot()]);
      startTransition(() => {
        setSummary({ ...nextSummary, agent: nextAgent });
      });
      setTransport("http");
      setErrorMessage(undefined);
      if (reason) {
        appendEvent({
          id: `local-${Date.now()}`,
          level: "success",
          source: "desktop",
          message: reason,
          at: new Date().toISOString(),
        });
      }
    } catch (error) {
      setTransport("mock");
      setErrorMessage(error instanceof Error ? error.message : "Failed to refresh workspace.");
      appendEvent({
        id: `local-error-${Date.now()}`,
        level: "warning",
        source: "desktop",
        message: "Backend unavailable. Using mock fallback snapshot.",
        at: new Date().toISOString(),
      });
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const [nextSummary, nextAgent] = await Promise.all([apiClient.getDashboardSummary(), apiClient.getAgentSnapshot()]);
        if (!alive) {
          return;
        }
        setSummary({ ...nextSummary, agent: nextAgent });
        setTransport("http");
        setEvents((current) => [
          ...current,
          {
            id: "stream-live-001",
            level: "success",
            source: "api",
            message: "Snapshot refreshed from the desktop client.",
            at: new Date().toISOString(),
          },
        ]);
      } catch {
        setTransport("mock");
      }
    })();

    const interval = window.setInterval(() => {
      void loadSummary();
    }, 10000);

    return () => {
      alive = false;
      window.clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    const unsubscribe = apiClient.subscribeToAgentStream((payload) => {
      if (!payload.id || !payload.message) {
        return;
      }
      setTransport("http");
      appendEvent({
        id: String(payload.id),
        level: payload.level,
        source: payload.source,
        message: payload.message,
        at: payload.at,
      });
      void loadSummary();
    });
    return unsubscribe;
  }, []);

  const summaryCounts = useMemo(
    () =>
      ({
        candidates: summary.candidates.length,
        workflows: summary.workflows.length,
        skills: summary.skills.filter((skill) => skill.status !== "active").length,
        approvals: summary.approvals.filter((approval) => approval.status === "pending").length,
        monitor: summary.agent.queueDepth,
      }) satisfies Partial<Record<WorkspaceTab, number>>,
    [summary],
  );

  const handleApprove = async (id: string) => {
    setApprovalActionId(id);
    try {
      await apiClient.approveItem(id);
      await loadSummary(`Approval ${id} accepted.`);
    } finally {
      setApprovalActionId(undefined);
    }
  };

  const handleReject = async (id: string) => {
    setApprovalActionId(id);
    try {
      await apiClient.rejectItem(id, "Rejected from desktop workspace.");
      await loadSummary(`Approval ${id} rejected.`);
    } finally {
      setApprovalActionId(undefined);
    }
  };

  const handleSaveSettings = async (patch: Partial<DashboardSummary["settings"]>) => {
    setSettingsSaving(true);
    try {
      const nextSettings = await apiClient.updateSettings(patch);
      startTransition(() => {
        setSummary((current) => ({ ...current, settings: nextSettings }));
      });
      await loadSummary("Settings saved.");
    } finally {
      setSettingsSaving(false);
    }
  };

  const handleRunOnce = async () => {
    setRuntimeActionBusy(true);
    try {
      const result = await apiClient.runAgentOnce();
      await loadSummary(`Run once completed with status ${result.status}.`);
    } finally {
      setRuntimeActionBusy(false);
    }
  };

  const handleQueueScreeningTask = async () => {
    setRuntimeActionBusy(true);
    try {
      const firstCandidate = summary.candidates[0];
      const task = await apiClient.queueTask({
        taskType: "initial_screening",
        payload: { jd_criteria: firstCandidate?.jdTitle ?? "Frontend Platform Engineer" },
        priority: 180,
        candidateId: firstCandidate?.id,
        workflowNodeId: "initial_screening",
      });
      await loadSummary(`Queued task ${task.taskType} with depth ${task.queueDepth}.`);
    } finally {
      setRuntimeActionBusy(false);
    }
  };

  const content = (() => {
    switch (tab) {
      case "dashboard":
        return <DashboardView summary={summary} />;
      case "candidates":
        return <CandidatesView candidates={summary.candidates} />;
      case "workflows":
        return <WorkflowsView workflows={summary.workflows} />;
      case "skills":
        return <SkillsView skills={summary.skills} />;
      case "approvals":
        return (
          <ApprovalsView
            approvals={summary.approvals}
            pendingActionId={approvalActionId}
            onApprove={handleApprove}
            onReject={handleReject}
          />
        );
      case "monitor":
        return (
          <AgentMonitorView
            agent={summary.agent}
            events={events}
            runningAction={runtimeActionBusy}
            onRunOnce={handleRunOnce}
            onQueueScreeningTask={handleQueueScreeningTask}
          />
        );
      case "settings":
        return <SettingsView settings={summary.settings} saving={settingsSaving} onSave={handleSaveSettings} />;
      default:
        return <DashboardView summary={summary} />;
    }
  })();

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "grid",
        gridTemplateColumns: "280px minmax(0, 1fr)",
        background:
          "radial-gradient(circle at top left, rgba(122,167,255,0.20), transparent 34%), radial-gradient(circle at bottom right, rgba(93,216,163,0.12), transparent 28%), linear-gradient(180deg, #070b16 0%, #0b1020 100%)",
        color: theme.colors.text,
      }}
    >
      <Sidebar active={tab} onChange={setTab} counts={summaryCounts} />
      <main style={{ display: "grid", gridTemplateRows: "auto 1fr", minWidth: 0 }}>
        <TopBar agent={summary.agent} settings={summary.settings} transport={transport} onRefresh={() => void loadSummary("Manual refresh completed.")} refreshing={refreshing} />
        <div style={{ padding: "22px", minWidth: 0, display: "grid", gap: "14px" }}>
          {errorMessage ? (
            <div
              style={{
                borderRadius: "16px",
                border: "1px solid rgba(255,122,122,0.18)",
                background: "rgba(255,122,122,0.08)",
                color: "#ffdede",
                padding: "12px 14px",
                fontSize: "13px",
              }}
            >
              {errorMessage}
            </div>
          ) : null}
          {content}
        </div>
      </main>
    </div>
  );
}
