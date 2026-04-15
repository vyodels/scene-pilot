import React, { startTransition, useEffect, useMemo, useState } from "react";
import { Sidebar, TopBar } from "../../components";
import { apiClient } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { desktopAgentQueueMock, desktopMockSnapshot, desktopReplayMockByEpisode, desktopRuntimeMock, desktopSyncBacklogMock, desktopSyncStatusMock } from "../../lib/mockData";
import { theme } from "../../lib/theme";
import { translateUiToken } from "../../lib/uiText";
import type {
  AgentEvent,
  AgentQueueItem,
  CompileTaskRequest,
  DashboardSummary,
  RuntimeEnvironmentAssessment,
  RuntimeEpisodeReplay,
  RuntimeLearningOutcome,
  RuntimePlanReplanResult,
  RuntimeWorkspaceData,
  SyncBacklogItem,
  SyncStatusSnapshot,
  WorkspaceTab,
} from "../../lib/types";
import { ApprovalsView } from "../approvals/ApprovalsView";
import { HumanAssistDock } from "../approvals/HumanAssistDock";
import { DashboardView } from "../dashboard/DashboardView";
import { SettingsView } from "../settings/SettingsView";
import { SkillsView } from "../skills/SkillsView";
import { WorkflowManagementView } from "../workflow-management/WorkflowManagementView";
import { WorkbenchView } from "../workbench/WorkbenchView";

function prependUniqueById<T extends { id: string }>(preferred: T[], fallback: T[]): T[] {
  const seen = new Set<string>();
  const merged: T[] = [];
  for (const item of [...preferred, ...fallback]) {
    if (!item || seen.has(item.id)) {
      continue;
    }
    seen.add(item.id);
    merged.push(item);
  }
  return merged;
}

function mergeRuntimeWorkspaceData(
  nextRuntime: RuntimeWorkspaceData,
  currentRuntime: RuntimeWorkspaceData,
  lastAssessment: RuntimeEnvironmentAssessment | null,
  lastReplan: RuntimePlanReplanResult | null,
): RuntimeWorkspaceData {
  const assessment = lastAssessment ? [lastAssessment] : [];
  const replanAssessment = lastReplan?.environmentAssessment ? [lastReplan.environmentAssessment] : [];
  const replanPatch = lastReplan?.patch ? [lastReplan.patch] : [];
  const replanPlan = lastReplan ? [lastReplan.executionPlan] : [];
  const replans = lastReplan ? [lastReplan] : [];

  return {
    ...nextRuntime,
    plans: prependUniqueById(replanPlan, prependUniqueById(nextRuntime.plans, currentRuntime.plans)),
    capabilityDrivers: nextRuntime.capabilityDrivers.length ? nextRuntime.capabilityDrivers : currentRuntime.capabilityDrivers,
    environmentAssessments: prependUniqueById(
      assessment,
      prependUniqueById(replanAssessment, prependUniqueById(nextRuntime.environmentAssessments, currentRuntime.environmentAssessments)),
    ),
    patches: prependUniqueById(replanPatch, prependUniqueById(nextRuntime.patches, currentRuntime.patches)),
    replans: prependUniqueById(replans, prependUniqueById(nextRuntime.replans, currentRuntime.replans)),
  };
}

export function DesktopWorkspace(): JSX.Element {
  const { copy } = useI18n();
  const [tab, setTab] = useState<WorkspaceTab>("dashboard");
  const [summary, setSummary] = useState<DashboardSummary>(desktopMockSnapshot);
  const [runtimeData, setRuntimeData] = useState<RuntimeWorkspaceData>(desktopRuntimeMock);
  const [events, setEvents] = useState<AgentEvent[]>([
    { id: "stream-001", level: "info", source: "bootstrap", message: copy("Workspace loaded from the local sample snapshot.", "工作区已从本地示例快照加载。"), at: copy("now", "刚刚") },
    { id: "stream-002", level: "warning", source: "runtime", message: copy("New workflows default into supervised trial mode.", "新工作流默认进入受监督试跑模式。"), at: copy("now", "刚刚") },
  ]);
  const [refreshing, setRefreshing] = useState(false);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [approvalActionId, setApprovalActionId] = useState<string>();
  const [runtimeActionBusy, setRuntimeActionBusy] = useState(false);
  const [trialTaskId, setTrialTaskId] = useState<string>();
  const [busyEpisodeId, setBusyEpisodeId] = useState<string>();
  const [busyPatchId, setBusyPatchId] = useState<string>();
  const [busyPlanId, setBusyPlanId] = useState<string>();
  const [selectedEpisodeId, setSelectedEpisodeId] = useState<string>();
  const [selectedReplay, setSelectedReplay] = useState<RuntimeEpisodeReplay | null>(null);
  const [syncStatus, setSyncStatus] = useState<SyncStatusSnapshot>(desktopSyncStatusMock);
  const [syncBacklog, setSyncBacklog] = useState<SyncBacklogItem[]>(desktopSyncBacklogMock);
  const [queueItems, setQueueItems] = useState<AgentQueueItem[]>(desktopAgentQueueMock);
  const [syncingBacklog, setSyncingBacklog] = useState(false);
  const [transport, setTransport] = useState(apiClient.describe().transport);
  const [errorMessage, setErrorMessage] = useState<string>();
  const [lastOutcome, setLastOutcome] = useState<RuntimeLearningOutcome | null>(null);
  const [lastAssessment, setLastAssessment] = useState<RuntimeEnvironmentAssessment | null>(
    desktopRuntimeMock.environmentAssessments[0] ?? null,
  );
  const [lastReplan, setLastReplan] = useState<RuntimePlanReplanResult | null>(desktopRuntimeMock.replans[0] ?? null);
  const [assistOpen, setAssistOpen] = useState(false);

  const appendEvent = (event: AgentEvent) => {
    setEvents((current) => [...current.slice(-39), event]);
  };

  const loadWorkspace = async (reason?: string) => {
    setRefreshing(true);
    try {
      const [nextSummary, nextRuntime, nextAgent, nextSyncStatus, nextSyncBacklog, nextQueueItems, nextApprovals] = await Promise.all([
        apiClient.getDashboardSummary(),
        apiClient.getRuntimeWorkspaceData(),
        apiClient.getAgentSnapshot(),
        apiClient.getSyncStatus(),
        apiClient.listSyncBacklog(),
        apiClient.listAgentQueue(),
        apiClient.listApprovals(),
      ]);
      startTransition(() => {
        setSummary({ ...nextSummary, agent: nextAgent, approvals: nextApprovals });
        setRuntimeData((current) => mergeRuntimeWorkspaceData(nextRuntime, current, lastAssessment, lastReplan));
        setSyncStatus(nextSyncStatus);
        setSyncBacklog(nextSyncBacklog);
        setQueueItems(nextQueueItems);
      });
      setSelectedEpisodeId((current) => current ?? nextRuntime.episodes[0]?.id);
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
      setRuntimeData((current) => mergeRuntimeWorkspaceData(desktopRuntimeMock, current, lastAssessment, lastReplan));
      setSyncStatus(desktopSyncStatusMock);
      setSyncBacklog(desktopSyncBacklogMock);
      setQueueItems(desktopAgentQueueMock);
      setSelectedReplay(desktopReplayMockByEpisode[selectedEpisodeId ?? "episode-001"] ?? desktopReplayMockByEpisode["episode-001"]);
      setErrorMessage(error instanceof Error ? error.message : copy("Failed to refresh workspace.", "刷新工作区失败。"));
      appendEvent({
        id: `local-error-${Date.now()}`,
        level: "warning",
        source: "desktop",
        message: copy("Backend unavailable. Using the local sample runtime snapshot.", "本地后端暂时不可用，已切换到本地示例运行时快照。"),
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
        const [nextSummary, nextRuntime, nextAgent, nextSyncStatus, nextSyncBacklog, nextQueueItems, nextApprovals] = await Promise.all([
          apiClient.getDashboardSummary(),
          apiClient.getRuntimeWorkspaceData(),
          apiClient.getAgentSnapshot(),
          apiClient.getSyncStatus(),
          apiClient.listSyncBacklog(),
          apiClient.listAgentQueue(),
          apiClient.listApprovals(),
        ]);
        if (!alive) {
          return;
        }
        setSummary({ ...nextSummary, agent: nextAgent, approvals: nextApprovals });
        setRuntimeData((current) => mergeRuntimeWorkspaceData(nextRuntime, current, lastAssessment, lastReplan));
        setSyncStatus(nextSyncStatus);
        setSyncBacklog(nextSyncBacklog);
        setQueueItems(nextQueueItems);
        setSelectedEpisodeId((current) => current ?? nextRuntime.episodes[0]?.id);
        setTransport("http");
        setEvents((current) => [
          ...current,
          {
            id: "stream-live-001",
            level: "success",
            source: "api",
            message: copy("Workspace refreshed from the local backend.", "工作区已从本地后端刷新。"),
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

  useEffect(() => {
    if (summary.approvals.some((approval) => approval.status === "pending")) {
      setAssistOpen(true);
    }
  }, [summary.approvals]);

  useEffect(() => {
    const episodeId = selectedEpisodeId;
    if (!episodeId) {
      setSelectedReplay(null);
      return;
    }

    let active = true;
    void (async () => {
      try {
        const replay = await apiClient.getRuntimeReplay(episodeId);
        if (active) {
          setSelectedReplay(replay);
        }
      } catch {
        if (active) {
          setSelectedReplay(desktopReplayMockByEpisode[episodeId] ?? desktopReplayMockByEpisode["episode-001"] ?? null);
        }
      }
    })();

    return () => {
      active = false;
    };
  }, [runtimeData.episodes, selectedEpisodeId]);

  const counts = useMemo(
    () =>
      ({
        "workflow-management": runtimeData.taskSpecs.length,
        workbench: runtimeData.episodes.filter((episode) => /(pending|running|awaiting_review)/i.test(episode.status)).length,
        skills: summary.skills.filter((skill) => skill.status !== "active").length,
        approvals: summary.approvals.filter((approval) => approval.status === "pending").length,
      }) satisfies Partial<Record<WorkspaceTab, number>>,
    [runtimeData, summary],
  );

  const sectionMeta = useMemo(
    (): Record<WorkspaceTab, { eyebrow: string; title: string; description: string }> => ({
      dashboard: {
        eyebrow: copy("ScenePilot", "ScenePilot"),
        title: copy("Overview", "概览"),
        description: copy("A concise global view of health, approvals, and cross-workflow movement.", "集中查看健康状态、审批情况和跨工作流的整体变化。"),
      },
      "workflow-management": {
        eyebrow: copy("Workflow lifecycle", "工作流生命周期"),
        title: copy("Workflow management", "工作流管理"),
        description: copy("Create workflows, shape scene profiles, run trials, review revisions, and release reusable versions.", "创建工作流、整理场景画像、执行试跑、审查修订建议，并发布可复用版本。"),
      },
      workbench: {
        eyebrow: copy("Live operations", "实时运营"),
        title: copy("Workbench", "工作台"),
        description: copy("Inspect each workflow and its workflow instances with workflow-specific operational views.", "查看每条工作流及其工作流实例，并进入该工作流的专属工作台视图。"),
      },
      skills: {
        eyebrow: copy("Skill governance", "Skill 治理"),
        title: copy("Skills", "Skills"),
        description: copy("Track Skills approval, health, and evolution across released workflows.", "查看 Skills 在已发布工作流中的审批、健康状态和演进情况。"),
      },
      approvals: {
        eyebrow: copy("Human gates", "人工关卡"),
        title: copy("Approvals", "审批中心"),
        description: copy("Review approvals before workflow versions, revision suggestions, or sensitive actions go live.", "在工作流版本、修订建议或敏感动作生效前完成审批。"),
      },
      settings: {
        eyebrow: copy("Local operator settings", "本地操作设置"),
        title: copy("Settings", "设置"),
        description: copy("Manage providers, local sync behavior, and operator controls for this machine.", "管理本机的 provider、本地同步行为和操作员控制项。"),
      },
    }),
    [copy],
  );

  const handleApprove = async (id: string) => {
    setApprovalActionId(id);
    try {
      await apiClient.approveItem(id);
      await loadWorkspace(copy(`Approval ${id} accepted.`, `已批准审批项 ${id}。`));
    } finally {
      setApprovalActionId(undefined);
    }
  };

  const handleReject = async (id: string) => {
    setApprovalActionId(id);
    try {
      await apiClient.rejectItem(id, "由桌面工作区拒绝。");
      await loadWorkspace(copy(`Approval ${id} rejected.`, `已拒绝审批项 ${id}。`));
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
      await loadWorkspace(copy("Settings saved.", "设置已保存。"));
    } finally {
      setSettingsSaving(false);
    }
  };

  const handleRunOnce = async () => {
    setRuntimeActionBusy(true);
    try {
      const result = await apiClient.runAgentOnce();
      await loadWorkspace(copy(`Run once completed with status ${result.status}.`, `单次运行已完成，状态为 ${translateUiToken(result.status, copy)}。`));
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
        payload: { jd_criteria: firstCandidate?.jdTitle ?? "前端平台工程师" },
        priority: 180,
        candidateId: firstCandidate?.id,
        workflowNodeId: "initial_screening",
      });
      await loadWorkspace(copy(`Queued task ${task.taskType} with depth ${task.queueDepth}.`, `已将任务 ${task.taskType} 放入队列，当前深度为 ${task.queueDepth}。`));
    } finally {
      setRuntimeActionBusy(false);
    }
  };

  const handleCompile = async (request: CompileTaskRequest) => {
    setRuntimeActionBusy(true);
    try {
      const result = await apiClient.compileRuntimeTask(request);
      setErrorMessage(undefined);
      appendEvent({
        id: `compile-${Date.now()}`,
        level: "success",
        source: "compiler",
        message: copy(`Compiled ${result.taskSpec.title} for ${result.domainPack.name}.`, `已为 ${result.domainPack.name} 编译工作流《${result.taskSpec.title}》。`),
        at: new Date().toISOString(),
      });
      await loadWorkspace(copy(`Compiled task ${result.taskSpec.title}.`, `已完成工作流《${result.taskSpec.title}》的编译。`));
    } catch (error) {
      const message = error instanceof Error ? error.message : copy("Task compilation failed.", "任务编译失败。");
      setErrorMessage(message);
      appendEvent({
        id: `compile-error-${Date.now()}`,
        level: "warning",
        source: "compiler",
        message,
        at: new Date().toISOString(),
      });
    } finally {
      setRuntimeActionBusy(false);
    }
  };

  const handleLaunchPlan = async (planId: string, taskSpecId: string) => {
    setBusyPlanId(planId);
    try {
      const launched = await apiClient.launchRuntimePlan(planId, taskSpecId, "production");
      setSelectedEpisodeId(launched.executionEpisode.id);
      appendEvent({
        id: `launch-${launched.taskId}`,
        level: "info",
        source: "runtime-launch",
        message: copy(`Queued managed execution ${launched.taskId} for plan ${planId}.`, `已为计划 ${planId} 排入托管运行 ${launched.taskId}。`),
        at: new Date().toISOString(),
      });
      await loadWorkspace(copy(`Queued managed execution ${launched.taskId}.`, `已排入托管运行 ${launched.taskId}。`));
    } finally {
      setBusyPlanId(undefined);
    }
  };

  const handleCreateTrial = async (taskSpecId: string, executionPlanId: string) => {
    setTrialTaskId(taskSpecId);
    try {
      const episode = await apiClient.createTrialRun(taskSpecId, executionPlanId, "由桌面控制台创建。");
      appendEvent({
        id: `trial-${episode.id}`,
        level: "info",
        source: "trial",
        message: copy(`Created supervised trial ${episode.id}.`, `已创建受监督试跑 ${episode.id}。`),
        at: new Date().toISOString(),
      });
      setSelectedEpisodeId(episode.id);
      await loadWorkspace(copy(`Created trial run ${episode.id}.`, `已创建试跑 ${episode.id}。`));
    } finally {
      setTrialTaskId(undefined);
    }
  };

  const handleExecuteTrial = async (episodeId: string) => {
    setBusyEpisodeId(episodeId);
    try {
      const outcome = await apiClient.executeTrialRun(episodeId, "由桌面控制台执行。");
      setLastOutcome(outcome);
      await loadWorkspace(copy(`Executed trial ${episodeId}.`, `已执行试跑 ${episodeId}。`));
    } finally {
      setBusyEpisodeId(undefined);
    }
  };

  const handleLearnTrial = async (episodeId: string) => {
    setBusyEpisodeId(episodeId);
    try {
      const outcome = await apiClient.refreshRuntimeLearning(episodeId);
      setLastOutcome(outcome);
      await loadWorkspace(copy(`Refreshed learning for trial ${episodeId}.`, `已刷新试跑 ${episodeId} 的学习结果。`));
    } finally {
      setBusyEpisodeId(undefined);
    }
  };

  const handleConfirmTrial = async (episodeId: string) => {
    setBusyEpisodeId(episodeId);
    try {
      const outcome = await apiClient.confirmTrialRun(episodeId, "经桌面端受监督审查后批准。");
      setLastOutcome(outcome);
      await loadWorkspace(copy(`Confirmed trial ${episodeId}.`, `已确认试跑 ${episodeId}。`));
    } finally {
      setBusyEpisodeId(undefined);
    }
  };

  const handleApprovePatch = async (id: string) => {
    setBusyPatchId(id);
    try {
      await apiClient.approveRuntimePatch(id, "由桌面端修订审查批准。");
      await loadWorkspace(copy(`Approved patch ${id}.`, `已批准修订建议 ${id}。`));
    } finally {
      setBusyPatchId(undefined);
    }
  };

  const handleRejectPatch = async (id: string) => {
    setBusyPatchId(id);
    try {
      await apiClient.rejectRuntimePatch(id, "由桌面端修订审查拒绝。");
      await loadWorkspace(copy(`Rejected patch ${id}.`, `已拒绝修订建议 ${id}。`));
    } finally {
      setBusyPatchId(undefined);
    }
  };

  const resolveRuntimeSnapshot = (executionPlanId: string, executionEpisodeId?: string) => {
    if (selectedReplay && selectedReplay.executionPlan?.id === executionPlanId) {
      return selectedReplay.snapshots[0] ?? null;
    }
    if (executionEpisodeId) {
      return runtimeData.snapshots.find((snapshot) => snapshot.executionEpisodeId === executionEpisodeId) ?? null;
    }
    return runtimeData.snapshots.find((snapshot) => snapshot.executionPlanId === executionPlanId) ?? null;
  };

  const handleAssessEnvironment = async (executionPlanId: string, executionEpisodeId?: string) => {
    setBusyPlanId(executionPlanId);
    try {
      const plan = runtimeData.plans.find((item) => item.id === executionPlanId);
      const assessment = await apiClient.assessRuntimeEnvironment({
        taskSpecId: plan?.taskSpecId,
        executionPlanId,
        executionEpisodeId,
        snapshot: resolveRuntimeSnapshot(executionPlanId, executionEpisodeId) ?? undefined,
      });
      setLastAssessment(assessment);
      startTransition(() => {
        setRuntimeData((current) => ({
          ...current,
          environmentAssessments: prependUniqueById([assessment], current.environmentAssessments),
        }));
      });
      appendEvent({
        id: `assessment-${Date.now()}`,
        level: assessment.driftSignals.length ? "warning" : "success",
        source: "scene-assessment",
        message: copy(`Assessed ${assessment.sceneLabel} for plan ${executionPlanId}.`, `已为计划 ${executionPlanId} 完成场景《${assessment.sceneLabel}》评估。`),
        at: new Date().toISOString(),
      });
    } finally {
      setBusyPlanId(undefined);
    }
  };

  const handleReplanPlan = async (
    executionPlanId: string,
    trigger: string,
    notes?: string,
    preferredCapabilityKeys?: string[],
  ) => {
    setBusyPlanId(executionPlanId);
    try {
      const plan = runtimeData.plans.find((item) => item.id === executionPlanId);
      const result = await apiClient.replanRuntimePlan({
        executionPlanId,
        taskSpecId: plan?.taskSpecId,
        executionEpisodeId: selectedEpisodeId,
        snapshot: resolveRuntimeSnapshot(executionPlanId, selectedEpisodeId) ?? undefined,
        trigger,
        reason: notes,
        notes,
        preferredCapabilityKeys,
      });
      setLastReplan(result);
      startTransition(() => {
        setRuntimeData((current) =>
          mergeRuntimeWorkspaceData(
            {
              ...current,
              plans: prependUniqueById([result.executionPlan], current.plans),
              environmentAssessments: result.environmentAssessment
                ? prependUniqueById([result.environmentAssessment], current.environmentAssessments)
                : current.environmentAssessments,
              patches: result.patch ? prependUniqueById([result.patch], current.patches) : current.patches,
              replans: prependUniqueById([result], current.replans),
            },
            current,
            result.environmentAssessment ?? lastAssessment,
            result,
          ),
        );
      });
      appendEvent({
        id: `replan-${result.id}`,
        level: result.patch ? "warning" : "success",
        source: "replanner",
        message: copy(`Prepared replan ${result.executionPlan.name} from ${executionPlanId}.`, `已基于 ${executionPlanId} 生成重规划《${result.executionPlan.name}》。`),
        at: new Date().toISOString(),
      });
    } finally {
      setBusyPlanId(undefined);
    }
  };

  const handleInspectEpisode = (episodeId: string) => {
    setSelectedEpisodeId(episodeId);
    appendEvent({
      id: `replay-${episodeId}-${Date.now()}`,
      level: "info",
      source: "replay",
      message: copy(`Loaded replay diagnostics for ${episodeId}.`, `已加载 ${episodeId} 的回放诊断信息。`),
      at: new Date().toISOString(),
    });
  };

  const handleFlushSync = async () => {
    setSyncingBacklog(true);
    try {
      const result = await apiClient.flushSyncBacklog();
      await loadWorkspace(result.message);
    } finally {
      setSyncingBacklog(false);
    }
  };

  const content = (() => {
    switch (tab) {
      case "dashboard":
        return <DashboardView summary={summary} />;
      case "workflow-management":
        return (
          <WorkflowManagementView
            data={runtimeData}
            approvals={summary.approvals}
            busy={runtimeActionBusy}
            busyEpisodeId={busyEpisodeId}
            selectedEpisodeId={selectedEpisodeId}
            actionPatchId={busyPatchId}
            busyPlanId={busyPlanId}
            replay={selectedReplay}
            lastOutcome={lastOutcome}
            lastAssessment={lastAssessment}
            lastReplan={lastReplan}
            onCompileTask={handleCompile}
            onLaunchPlan={handleLaunchPlan}
            onCreateTrialRun={handleCreateTrial}
            onExecuteTrialRun={handleExecuteTrial}
            onRefreshLearning={handleLearnTrial}
            onConfirmTrial={handleConfirmTrial}
            onInspectEpisode={handleInspectEpisode}
            onAssessEnvironment={handleAssessEnvironment}
            onReplanPlan={handleReplanPlan}
            onApprovePatch={handleApprovePatch}
            onRejectPatch={handleRejectPatch}
          />
        );
      case "workbench":
        return (
          <WorkbenchView
            summary={summary}
            data={runtimeData}
            agent={summary.agent}
            events={events}
            selectedEpisodeId={selectedEpisodeId}
            replay={selectedReplay}
            syncStatus={syncStatus}
            syncBacklog={syncBacklog}
            queueItems={queueItems}
            runningAction={runtimeActionBusy}
            syncingAction={syncingBacklog}
            onRunOnce={handleRunOnce}
            onQueueScreeningTask={handleQueueScreeningTask}
            onFlushSync={handleFlushSync}
            onSelectEpisode={handleInspectEpisode}
          />
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
        gridTemplateColumns: "248px minmax(0, 1fr)",
        background:
          "linear-gradient(180deg, #0a101a 0%, #0d1320 100%)",
        color: theme.colors.text,
      }}
    >
      <Sidebar active={tab} onChange={setTab} counts={counts} />
      <main style={{ display: "grid", gridTemplateRows: "auto 1fr", minWidth: 0 }}>
        <TopBar
          agent={summary.agent}
          settings={summary.settings}
          transport={transport}
          sectionEyebrow={sectionMeta[tab].eyebrow}
          sectionTitle={sectionMeta[tab].title}
          sectionDescription={sectionMeta[tab].description}
          onRefresh={() => void loadWorkspace(copy("Manual refresh completed.", "已完成手动刷新。"))}
          refreshing={refreshing}
        />
        <div style={{ padding: "0 22px 22px", minWidth: 0, display: "grid", gap: "18px" }}>
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
      <HumanAssistDock
        approvals={summary.approvals}
        pendingActionId={approvalActionId}
        isOpen={assistOpen}
        onToggle={() => setAssistOpen((current) => !current)}
        onApprove={handleApprove}
        onReject={handleReject}
      />
    </div>
  );
}
