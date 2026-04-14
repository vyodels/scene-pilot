import React, { useMemo, useState } from "react";
import { Panel, StatusBadge, TopTabPage } from "../../components";
import { formatCompactDate } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { theme } from "../../lib/theme";
import { translateUiToken } from "../../lib/uiText";
import type {
  ApprovalItem,
  CompileTaskRequest,
  RuntimeEnvironmentAssessment,
  RuntimeEpisodeReplay,
  RuntimeLearningOutcome,
  RuntimePlanReplanResult,
  RuntimeWorkspaceData,
} from "../../lib/types";
import { RuntimeControlView } from "../runtime/RuntimeControlView";

type WorkflowManagementTab = "board" | "create" | "trials" | "versions" | "revisions" | "scenes";

interface WorkflowManagementViewProps {
  data: RuntimeWorkspaceData;
  approvals: ApprovalItem[];
  busy: boolean;
  busyEpisodeId?: string;
  selectedEpisodeId?: string;
  actionPatchId?: string;
  busyPlanId?: string;
  replay?: RuntimeEpisodeReplay | null;
  lastOutcome?: RuntimeLearningOutcome | null;
  lastAssessment?: RuntimeEnvironmentAssessment | null;
  lastReplan?: RuntimePlanReplanResult | null;
  onCompileTask(payload: CompileTaskRequest): Promise<void>;
  onLaunchPlan(planId: string, taskSpecId: string): Promise<void>;
  onCreateTrialRun(taskSpecId: string, executionPlanId: string): Promise<void>;
  onExecuteTrialRun(episodeId: string): Promise<void>;
  onRefreshLearning(episodeId: string): Promise<void>;
  onConfirmTrial(episodeId: string): Promise<void>;
  onInspectEpisode(episodeId: string): void;
  onAssessEnvironment(executionPlanId: string, executionEpisodeId?: string): Promise<void>;
  onReplanPlan(
    executionPlanId: string,
    trigger: string,
    notes?: string,
    preferredCapabilityKeys?: string[],
  ): Promise<void>;
  onApprovePatch(id: string): Promise<void>;
  onRejectPatch(id: string): Promise<void>;
}

function toneFromStatus(value: string): "positive" | "neutral" | "warning" | "critical" {
  if (/(rejected|failed|critical|diverged|drift|error)/i.test(value)) {
    return "critical";
  }
  if (/(pending|review|warning|blocked|draft)/i.test(value)) {
    return "warning";
  }
  if (/(active|approved|ready|confirmed|stable|running|completed)/i.test(value)) {
    return "positive";
  }
  return "neutral";
}

function translateWorkflowManagementText(value: string, copy: (en: string, zh: string) => string): string {
  return value
    .replace("Approve resume screening Skill", "批准 Resume Screening Skill")
    .replace("Approve Resume Screening Skill", "批准 Resume Screening Skill")
    .replace("Review the new initial screening strategy before activation.", "在启用前先审查新的初筛策略。")
    .replace("Enables the workflow path from scoring to human review.", "启用从评分到人工审查的工作流路径。")
    .replace("Activate talent pool handoff", "激活人才库交接")
    .replace("repository_listing", translateUiToken("repository_listing", copy));
}

export function WorkflowManagementView({
  data,
  approvals,
  busy,
  busyEpisodeId,
  selectedEpisodeId,
  actionPatchId,
  busyPlanId,
  replay,
  lastOutcome,
  lastAssessment,
  lastReplan,
  onCompileTask,
  onLaunchPlan,
  onCreateTrialRun,
  onExecuteTrialRun,
  onRefreshLearning,
  onConfirmTrial,
  onInspectEpisode,
  onAssessEnvironment,
  onReplanPlan,
  onApprovePatch,
  onRejectPatch,
}: WorkflowManagementViewProps): JSX.Element {
  const { copy } = useI18n();
  const [tab, setTab] = useState<WorkflowManagementTab>("board");

  const taskLifecycle = useMemo(() => {
    const latestEpisodes = new Map<string, RuntimeWorkspaceData["episodes"][number]>();
    for (const episode of data.episodes) {
      const current = latestEpisodes.get(episode.taskSpecId);
      if (!current || current.updatedAt < episode.updatedAt) {
        latestEpisodes.set(episode.taskSpecId, episode);
      }
    }

    return data.taskSpecs.map((task) => {
      const plans = data.plans.filter((plan) => plan.taskSpecId === task.id);
      const episodes = data.episodes.filter((episode) => episode.taskSpecId === task.id);
      const templates = data.templates.filter((template) => template.sourceTaskSpecId === task.id || template.domain === task.domain);
      const adjustments = data.patches.filter((patch) => patch.taskSpecId === task.id);
      return {
        task,
        latestEpisode: latestEpisodes.get(task.id) ?? null,
        planCount: plans.length,
        trialCount: episodes.length,
        activeTrialCount: episodes.filter((episode) => /(pending|running|awaiting_review)/i.test(episode.status)).length,
        awaitingConfirmationCount: episodes.filter((episode) => episode.requiresConfirmation).length,
        versionCount: templates.length,
        pendingAdjustmentCount: adjustments.filter((patch) => patch.status === "pending_review").length,
      };
    });
  }, [data.episodes, data.patches, data.plans, data.taskSpecs, data.templates]);

  const topItems = [
    { key: "board", label: copy("Workflow board", "工作流看板"), detail: copy("Lifecycle overview", "生命周期总览"), count: data.taskSpecs.length },
    { key: "create", label: copy("Create workflow", "创建工作流"), detail: copy("Describe needs and build a draft", "描述需求并生成草稿") },
    { key: "trials", label: copy("Trial center", "试跑"), detail: copy("Run supervised validation", "执行受监督验证"), count: data.episodes.filter((episode) => episode.status !== "confirmed").length },
    { key: "versions", label: copy("Workflow versions", "工作流版本"), detail: copy("Review reusable released versions", "查看可复用版本"), count: data.templates.length },
    { key: "revisions", label: copy("Revision suggestions", "修订建议"), detail: copy("Review divergences and suggested updates", "审查偏差与建议修改"), count: data.patches.filter((patch) => patch.status === "pending_review").length },
    { key: "scenes", label: copy("Scene profiles", "场景画像"), detail: copy("Manage reusable scene knowledge", "管理可复用场景知识"), count: data.domainPacks.length },
  ] satisfies Array<{ key: WorkflowManagementTab; label: string; detail: string; count?: number }>;

  const board = (
    <div style={{ display: "grid", gap: "18px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "14px" }}>
        {[
          {
            label: copy("Draft workflows", "草稿工作流"),
            value: taskLifecycle.filter((item) => /draft/i.test(item.task.status)).length,
            tone: "warning" as const,
            detail: copy("Need editing or first validation", "仍需编辑或首次验证"),
          },
          {
            label: copy("Awaiting trial", "待试跑"),
            value: taskLifecycle.filter((item) => !item.trialCount || item.activeTrialCount > 0).length,
            tone: "neutral" as const,
            detail: copy("Ready for supervised checks", "已准备进入受监督检查"),
          },
          {
            label: copy("Published versions", "已发布版本"),
            value: data.templates.filter((template) => template.status === "active").length,
            tone: "positive" as const,
            detail: copy("Reusable workflow versions", "可复用的工作流版本"),
          },
          {
            label: copy("Pending revisions", "待处理修订建议"),
            value: data.patches.filter((patch) => patch.status === "pending_review").length,
            tone: "warning" as const,
            detail: copy("Need operator review", "等待操作员审查"),
          },
        ].map((item) => (
          <Panel key={item.label} dense title={item.value.toString()} eyebrow={item.label} description={item.detail}>
            <StatusBadge tone={item.tone}>{item.label}</StatusBadge>
          </Panel>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: "18px", alignItems: "start" }}>
        <Panel
          title={copy("Workflow lifecycle board", "工作流生命周期看板")}
          eyebrow={copy("From draft to release", "从草稿到发布")}
          description={copy(
            "Each workflow stays visible through creation, supervised trial, revision review, and version release.",
            "每条工作流都会沿着创建、受监督试跑、修订审查和版本发布的完整生命周期保持可见。",
          )}
        >
          <div style={{ display: "grid", gap: "12px" }}>
            {taskLifecycle.map((item) => (
              <article
                key={item.task.id}
                style={{
                  padding: "16px",
                  borderRadius: "18px",
                  border: "1px solid rgba(255,255,255,0.08)",
                  background: "rgba(255,255,255,0.03)",
                  display: "grid",
                  gap: "10px",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", flexWrap: "wrap", alignItems: "start" }}>
                  <div>
                    <strong style={{ fontSize: "16px" }}>{item.task.title}</strong>
                    <div style={{ color: theme.colors.muted, fontSize: "13px", marginTop: "6px", lineHeight: 1.6 }}>{item.task.goal}</div>
                  </div>
                  <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                    <StatusBadge tone="neutral">{translateUiToken(item.task.domain, copy)}</StatusBadge>
                    <StatusBadge tone={toneFromStatus(item.task.status)}>{translateUiToken(item.task.status, copy)}</StatusBadge>
                  </div>
                </div>
                <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                  <StatusBadge tone="neutral">{copy(`${item.planCount} plans`, `${item.planCount} 个计划`)}</StatusBadge>
                  <StatusBadge tone={item.activeTrialCount ? "warning" : "neutral"}>{copy(`${item.trialCount} workflow instances`, `${item.trialCount} 个工作流实例`)}</StatusBadge>
                  <StatusBadge tone={item.awaitingConfirmationCount ? "warning" : "positive"}>
                    {copy(`${item.awaitingConfirmationCount} pending confirmation`, `${item.awaitingConfirmationCount} 个待确认`)}
                  </StatusBadge>
                  <StatusBadge tone="neutral">{copy(`${item.versionCount} versions`, `${item.versionCount} 个版本`)}</StatusBadge>
                  {item.pendingAdjustmentCount ? (
                    <StatusBadge tone="warning">{copy(`${item.pendingAdjustmentCount} revision suggestions`, `${item.pendingAdjustmentCount} 个修订建议`)}</StatusBadge>
                  ) : null}
                </div>
                <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                  {item.latestEpisode
                    ? copy(
                        `Latest workflow instance updated ${formatCompactDate(item.latestEpisode.updatedAt)} with status ${item.latestEpisode.status}.`,
                        `最近一次工作流实例更新于 ${formatCompactDate(item.latestEpisode.updatedAt)}，状态为 ${translateUiToken(item.latestEpisode.status, copy)}。`,
                      )
                    : copy("This workflow has not entered a trial yet.", "这条工作流还没有进入试跑。")}
                </div>
              </article>
            ))}
          </div>
        </Panel>

        <Panel
          title={copy("Operator focus", "当前待办")}
          eyebrow={copy("What needs attention", "需要优先关注")}
          description={copy(
            "Trials, approvals, and workflow revisions that should be handled before a workflow can stabilize.",
            "工作流稳定下来之前，需要先处理的试跑、审批和修订建议。",
          )}
        >
          <div style={{ display: "grid", gap: "12px" }}>
            {data.episodes
              .filter((episode) => episode.requiresConfirmation || /(awaiting_review|pending|running)/i.test(episode.status))
              .slice(0, 4)
              .map((episode) => (
                <article
                  key={episode.id}
                  style={{
                    padding: "14px",
                    borderRadius: "16px",
                    background: "rgba(255,255,255,0.03)",
                    border: "1px solid rgba(255,255,255,0.08)",
                    display: "grid",
                    gap: "8px",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: "8px", flexWrap: "wrap" }}>
                    <strong>{data.taskSpecs.find((task) => task.id === episode.taskSpecId)?.title ?? episode.id}</strong>
                    <StatusBadge tone={toneFromStatus(episode.status)}>{translateUiToken(episode.status, copy)}</StatusBadge>
                  </div>
                  <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                    {episode.resultSummary ?? copy("Waiting for supervised feedback.", "等待受监督反馈。")}
                  </div>
                </article>
              ))}
            {data.patches
              .filter((patch) => patch.status === "pending_review")
              .slice(0, 2)
              .map((patch) => (
                <article
                  key={patch.id}
                  style={{
                    padding: "14px",
                    borderRadius: "16px",
                    background: "rgba(255,255,255,0.03)",
                    border: "1px solid rgba(255,255,255,0.08)",
                    display: "grid",
                    gap: "8px",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: "8px", flexWrap: "wrap" }}>
                    <strong>{patch.title}</strong>
                    <StatusBadge tone="warning">{copy("pending review", "待审查")}</StatusBadge>
                  </div>
                  <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                    {translateWorkflowManagementText(patch.divergenceSummary ?? patch.rationale ?? copy("Waiting for operator review.", "等待操作员审查。"), copy)}
                  </div>
                </article>
              ))}
            {approvals
              .filter((approval) => approval.status === "pending")
              .slice(0, 2)
              .map((approval) => (
                <article
                  key={approval.id}
                  style={{
                    padding: "14px",
                    borderRadius: "16px",
                    background: "rgba(255,255,255,0.03)",
                    border: "1px solid rgba(255,255,255,0.08)",
                    display: "grid",
                    gap: "8px",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: "8px", flexWrap: "wrap" }}>
                    <strong>{translateWorkflowManagementText(approval.title, copy)}</strong>
                    <StatusBadge tone="warning">{copy("pending approval", "待审批")}</StatusBadge>
                  </div>
                  <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>{translateWorkflowManagementText(approval.detail, copy)}</div>
                </article>
              ))}
          </div>
        </Panel>
      </div>
    </div>
  );

  const runtimeMode =
    tab === "create"
      ? "workflow-create"
      : tab === "trials"
        ? "workflow-trials"
        : tab === "versions"
          ? "workflow-versions"
          : tab === "revisions"
            ? "workflow-adjustments"
            : "workflow-scenes";

  return (
    <TopTabPage items={topItems} active={tab} onChange={(key) => setTab(key as WorkflowManagementTab)}>
      {tab === "board" ? (
        board
      ) : (
        <RuntimeControlView
          mode={runtimeMode}
          data={data}
          busy={busy}
          busyEpisodeId={busyEpisodeId}
          selectedEpisodeId={selectedEpisodeId}
          actionPatchId={actionPatchId}
          busyPlanId={busyPlanId}
          replay={replay}
          lastOutcome={lastOutcome}
          lastAssessment={lastAssessment}
          lastReplan={lastReplan}
          onCompileTask={onCompileTask}
          onLaunchPlan={onLaunchPlan}
          onCreateTrialRun={onCreateTrialRun}
          onExecuteTrialRun={onExecuteTrialRun}
          onRefreshLearning={onRefreshLearning}
          onConfirmTrial={onConfirmTrial}
          onInspectEpisode={onInspectEpisode}
          onAssessEnvironment={onAssessEnvironment}
          onReplanPlan={onReplanPlan}
          onApprovePatch={onApprovePatch}
          onRejectPatch={onRejectPatch}
        />
      )}
    </TopTabPage>
  );
}
