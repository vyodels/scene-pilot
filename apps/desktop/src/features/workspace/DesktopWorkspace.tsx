import React, { startTransition, useEffect, useMemo, useState } from "react";
import { Panel, Sidebar, TopBar } from "../../components";
import { apiClient } from "../../lib/api";
import { desktopMockSnapshot, desktopRuntimeMock } from "../../lib/mockData";
import { theme } from "../../lib/theme";
import type {
  AgentEvent,
  CompileTaskRequest,
  DashboardSummary,
  RuntimeLearningOutcome,
  RuntimeWorkspaceData,
  WorkspaceTab,
} from "../../lib/types";
import { AgentMonitorView } from "../agent-monitor/AgentMonitorView";
import { ApprovalsView } from "../approvals/ApprovalsView";
import { DashboardView } from "../dashboard/DashboardView";
import { CandidatesView } from "../candidates/CandidatesView";
import { SettingsView } from "../settings/SettingsView";
import { SkillsView } from "../skills/SkillsView";
import { RuntimeControlView } from "../runtime/RuntimeControlView";
import { WorkflowsView } from "../workflows/WorkflowsView";

export function DesktopWorkspace(): JSX.Element {
  const [tab, setTab] = useState<WorkspaceTab>("dashboard");
  const [summary, setSummary] = useState<DashboardSummary>(desktopMockSnapshot);
  const [runtimeData, setRuntimeData] = useState<RuntimeWorkspaceData>(desktopRuntimeMock);
  const [events, setEvents] = useState<AgentEvent[]>([
    { id: "stream-001", level: "info", source: "bootstrap", message: "Workspace loaded from mock snapshot.", at: "now" },
    { id: "stream-002", level: "warning", source: "runtime", message: "New workflows default into supervised trial mode.", at: "now" },
  ]);
  const [refreshing, setRefreshing] = useState(false);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [approvalActionId, setApprovalActionId] = useState<string>();
  const [runtimeActionBusy, setRuntimeActionBusy] = useState(false);
  const [trialTaskId, setTrialTaskId] = useState<string>();
  const [busyEpisodeId, setBusyEpisodeId] = useState<string>();
  const [busyPatchId, setBusyPatchId] = useState<string>();
  const [transport, setTransport] = useState(apiClient.describe().transport);
  const [errorMessage, setErrorMessage] = useState<string>();
  const [lastOutcome, setLastOutcome] = useState<RuntimeLearningOutcome | null>(null);

  const appendEvent = (event: AgentEvent) => {
    setEvents((current) => [...current.slice(-39), event]);
  };

  const loadWorkspace = async (reason?: string) => {
    setRefreshing(true);
    try {
      const [nextSummary, nextRuntime, nextAgent] = await Promise.all([
        apiClient.getDashboardSummary(),
        apiClient.getRuntimeWorkspaceData(),
        apiClient.getAgentSnapshot(),
      ]);
      startTransition(() => {
        setSummary({ ...nextSummary, agent: nextAgent });
        setRuntimeData(nextRuntime);
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
      setSummary(desktopMockSnapshot);
      setRuntimeData(desktopRuntimeMock);
      setErrorMessage(error instanceof Error ? error.message : "Failed to refresh workspace.");
      appendEvent({
        id: `local-error-${Date.now()}`,
        level: "warning",
        source: "desktop",
        message: "Backend unavailable. Using local mock runtime snapshot.",
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
        const [nextSummary, nextRuntime, nextAgent] = await Promise.all([
          apiClient.getDashboardSummary(),
          apiClient.getRuntimeWorkspaceData(),
          apiClient.getAgentSnapshot(),
        ]);
        if (!alive) {
          return;
        }
        setSummary({ ...nextSummary, agent: nextAgent });
        setRuntimeData(nextRuntime);
        setTransport("http");
        setEvents((current) => [
          ...current,
          {
            id: "stream-live-001",
            level: "success",
            source: "api",
            message: "Workspace refreshed from the local backend.",
            at: new Date().toISOString(),
          },
        ]);
      } catch {
        setTransport("mock");
      }
    })();

    const interval = window.setInterval(() => {
      void loadWorkspace();
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
      void loadWorkspace();
    });
    return unsubscribe;
  }, []);

  const counts = useMemo(
    () =>
      ({
        runtime: runtimeData.taskSpecs.length,
        trials: runtimeData.episodes.filter((episode) => episode.status !== "confirmed").length,
        templates: runtimeData.templates.length,
        patches: runtimeData.patches.filter((patch) => patch.status === "pending_review").length,
        domains: runtimeData.domainPacks.length,
        recruiting: summary.candidates.length,
        skills: summary.skills.filter((skill) => skill.status !== "active").length,
        approvals: summary.approvals.filter((approval) => approval.status === "pending").length,
        monitor: summary.agent.queueDepth,
      }) satisfies Partial<Record<WorkspaceTab, number>>,
    [runtimeData, summary],
  );

  const handleApprove = async (id: string) => {
    setApprovalActionId(id);
    try {
      await apiClient.approveItem(id);
      await loadWorkspace(`Approval ${id} accepted.`);
    } finally {
      setApprovalActionId(undefined);
    }
  };

  const handleReject = async (id: string) => {
    setApprovalActionId(id);
    try {
      await apiClient.rejectItem(id, "Rejected from desktop workspace.");
      await loadWorkspace(`Approval ${id} rejected.`);
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
      await loadWorkspace("Settings saved.");
    } finally {
      setSettingsSaving(false);
    }
  };

  const handleRunOnce = async () => {
    setRuntimeActionBusy(true);
    try {
      const result = await apiClient.runAgentOnce();
      await loadWorkspace(`Run once completed with status ${result.status}.`);
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
      await loadWorkspace(`Queued task ${task.taskType} with depth ${task.queueDepth}.`);
    } finally {
      setRuntimeActionBusy(false);
    }
  };

  const handleCompile = async (request: CompileTaskRequest) => {
    setRuntimeActionBusy(true);
    try {
      const result = await apiClient.compileRuntimeTask(request);
      appendEvent({
        id: `compile-${Date.now()}`,
        level: "success",
        source: "compiler",
        message: `Compiled ${result.taskSpec.title} for ${result.domainPack.name}.`,
        at: new Date().toISOString(),
      });
      await loadWorkspace(`Compiled task ${result.taskSpec.title}.`);
    } finally {
      setRuntimeActionBusy(false);
    }
  };

  const handleCreateTrial = async (taskSpecId: string, executionPlanId: string) => {
    setTrialTaskId(taskSpecId);
    try {
      const episode = await apiClient.createTrialRun(taskSpecId, executionPlanId, "Created from desktop control plane.");
      appendEvent({
        id: `trial-${episode.id}`,
        level: "info",
        source: "trial",
        message: `Created supervised trial ${episode.id}.`,
        at: new Date().toISOString(),
      });
      await loadWorkspace(`Created trial run ${episode.id}.`);
    } finally {
      setTrialTaskId(undefined);
    }
  };

  const handleExecuteTrial = async (episodeId: string) => {
    setBusyEpisodeId(episodeId);
    try {
      const outcome = await apiClient.executeTrialRun(episodeId, "Executed from the desktop control plane.");
      setLastOutcome(outcome);
      await loadWorkspace(`Executed trial ${episodeId}.`);
    } finally {
      setBusyEpisodeId(undefined);
    }
  };

  const handleLearnTrial = async (episodeId: string) => {
    setBusyEpisodeId(episodeId);
    try {
      const outcome = await apiClient.refreshRuntimeLearning(episodeId);
      setLastOutcome(outcome);
      await loadWorkspace(`Refreshed learning for trial ${episodeId}.`);
    } finally {
      setBusyEpisodeId(undefined);
    }
  };

  const handleConfirmTrial = async (episodeId: string) => {
    setBusyEpisodeId(episodeId);
    try {
      const outcome = await apiClient.confirmTrialRun(episodeId, "Approved after supervised desktop review.");
      setLastOutcome(outcome);
      await loadWorkspace(`Confirmed trial ${episodeId}.`);
    } finally {
      setBusyEpisodeId(undefined);
    }
  };

  const handleApprovePatch = async (id: string) => {
    setBusyPatchId(id);
    try {
      await apiClient.approveRuntimePatch(id, "Approved from desktop patch review.");
      await loadWorkspace(`Approved patch ${id}.`);
    } finally {
      setBusyPatchId(undefined);
    }
  };

  const handleRejectPatch = async (id: string) => {
    setBusyPatchId(id);
    try {
      await apiClient.rejectRuntimePatch(id, "Rejected from desktop patch review.");
      await loadWorkspace(`Rejected patch ${id}.`);
    } finally {
      setBusyPatchId(undefined);
    }
  };

  const content = (() => {
    switch (tab) {
      case "dashboard":
        return <DashboardView summary={summary} />;
      case "runtime":
      case "trials":
      case "templates":
      case "patches":
      case "domains":
        return (
          <RuntimeControlView
            mode={tab}
            data={runtimeData}
            busy={runtimeActionBusy}
            actionPatchId={busyPatchId}
            lastOutcome={lastOutcome}
            onCompileTask={handleCompile}
            onCreateTrialRun={handleCreateTrial}
            onExecuteTrialRun={handleExecuteTrial}
            onApprovePatch={handleApprovePatch}
            onRejectPatch={handleRejectPatch}
          />
        );
      case "recruiting":
        return (
          <div style={{ display: "grid", gap: "18px" }}>
            <Panel
              title="Candidates"
              eyebrow="Recruiting Domain Pack"
              description="Candidate pipeline and profile summaries remain available as a domain-specific operator view."
            >
              <CandidatesView candidates={summary.candidates} />
            </Panel>
            <Panel
              title="Workflows"
              eyebrow="Recruiting Templates"
              description="Existing recruiting workflows remain available while the core product moves to dynamic runtime planning."
            >
              <WorkflowsView workflows={summary.workflows} />
            </Panel>
          </div>
        );
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
      <Sidebar active={tab} onChange={setTab} counts={counts} />
      <main style={{ display: "grid", gridTemplateRows: "auto 1fr", minWidth: 0 }}>
        <TopBar
          agent={summary.agent}
          settings={summary.settings}
          transport={transport}
          onRefresh={() => void loadWorkspace("Manual refresh completed.")}
          refreshing={refreshing}
        />
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
