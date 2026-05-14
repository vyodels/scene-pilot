import React, { useEffect, useMemo, useState } from "react";
import { funnelMilestones } from "@recruit-agent/shared";
import type { ApplicationTransitionPayload, RecruitmentStateMachine } from "@recruit-agent/shared";
import { ToolbarField, ToolbarRefreshButton, ToolbarSelect } from "../../components";
import { CandidateTable } from "../kanban-shared/CandidateTable";
import { CandidateCommunicationPanel } from "../kanban-shared/CandidateCommunicationPanel";
import {
  CandidateDateRangeControl,
  createApplicationDateRangeState,
  resolveApplicationDateRangeFilter,
  type ApplicationDateRangeState,
} from "../kanban-shared/CandidateDateRangeControl";
import { CandidateDetailDrawer } from "../kanban-shared/CandidateDetailDrawer";
import { ManualStatusOverrideDrawer } from "../kanban-shared/ManualStatusOverrideDrawer";
import { buildFunnelAnalytics, formatFunnelRate } from "../kanban-shared/funnelAnalytics";
import {
  buildApplicationViewModels,
  createNodeMap,
  hasReachedFunnelMilestone,
} from "../kanban-shared/kanbanUtils";
import type { ApplicationRecord, ApplicationThreadRecord, SettingsSnapshot } from "../../lib/types";
import { useI18n } from "../../lib/i18n";
import type { ApplicationWorkspaceFilter } from "../candidates/CandidatesKanbanView";

interface FunnelKanbanViewProps {
  applications: ApplicationRecord[];
  threads: ApplicationThreadRecord[];
  stateMachine: RecruitmentStateMachine;
  preferredApplicationId?: string;
  preferredConversationToken?: number;
  preferredFilter?: ApplicationWorkspaceFilter;
  preferredFilterToken?: number;
  onOpenApplication(applicationId: string): void;
  onRefresh?(): Promise<unknown> | void;
  onCreateEntry(
    applicationId: string,
    payload: { direction: string; content: string; messageType?: string; platform?: string },
  ): Promise<unknown> | void;
  onTransition(applicationId: string, payload: ApplicationTransitionPayload): Promise<unknown> | void;
  operatorProfile?: SettingsSnapshot["userProfile"];
}

function FunnelChart({ stages }: { stages: ReturnType<typeof buildFunnelAnalytics>["stageMetrics"] }): JSX.Element {
  const chartHeight = stages.length * 56 + 16;
  const maxWidth = 520;
  const minWidth = 118;
  const centerX = 320;

  return (
    <svg className="funnel-analysis-chart" viewBox={`0 0 640 ${chartHeight}`} role="img" aria-label="招聘转化漏斗图">
      {stages.map((stage, index) => {
        const y = index * 56 + 8;
        const nextStage = stages[index + 1];
        const topWidth = Math.max(minWidth, (maxWidth * stage.widthPercent) / 100);
        const bottomWidth = Math.max(minWidth, (maxWidth * (nextStage?.widthPercent ?? stage.widthPercent)) / 100);
        const points = [
          `${centerX - topWidth / 2},${y}`,
          `${centerX + topWidth / 2},${y}`,
          `${centerX + bottomWidth / 2},${y + 44}`,
          `${centerX - bottomWidth / 2},${y + 44}`,
        ].join(" ");
        return (
          <g key={stage.milestoneId} className="funnel-analysis-chart__stage" data-step={index}>
            <polygon points={points} />
            <text x={centerX - Math.min(topWidth, bottomWidth) / 2 + 18} y={y + 27}>
              {stage.label}
            </text>
            <text x={centerX + Math.min(topWidth, bottomWidth) / 2 - 18} y={y + 27} textAnchor="end">
              {stage.count}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function stageReachedCount(
  applications: ReturnType<typeof buildApplicationViewModels>,
  milestoneId: string,
): number {
  if (milestoneId === "M01") {
    return applications.length;
  }
  return applications.filter((item) => hasReachedFunnelMilestone(item.deepestMilestone, milestoneId)).length;
}

export function FunnelKanbanView({
  applications,
  threads,
  stateMachine,
  preferredApplicationId,
  preferredConversationToken,
  preferredFilter,
  preferredFilterToken,
  onOpenApplication,
  onRefresh,
  onCreateEntry,
  onTransition,
  operatorProfile,
}: FunnelKanbanViewProps): JSX.Element {
  const { copy } = useI18n();
  const [jobFilter, setJobFilter] = useState("all");
  const [dateRange, setDateRange] = useState<ApplicationDateRangeState>(() => createApplicationDateRangeState());
  const visibleMilestones = useMemo(
    () => funnelMilestones.filter((milestone) => milestone.showInFunnel),
    [],
  );
  const [selectedMilestone, setSelectedMilestone] = useState<string>(visibleMilestones[0]?.id ?? "M01");
  const [activeConversationApplicationId, setActiveConversationApplicationId] = useState<string>();
  const [detailApplicationId, setDetailApplicationId] = useState<string>();
  const [overrideApplicationId, setOverrideApplicationId] = useState<string>();

  useEffect(() => {
    if (!visibleMilestones.some((milestone) => milestone.id === selectedMilestone)) {
      setSelectedMilestone(visibleMilestones[0]?.id ?? "M01");
    }
  }, [selectedMilestone, visibleMilestones]);

  const models = useMemo(
    () => buildApplicationViewModels(applications, threads, stateMachine),
    [applications, stateMachine, threads],
  );

  const jobOptions = useMemo(
    () =>
      Array.from(new Set(models.map((item) => item.application.jobDescription.title))).sort((left, right) =>
        left.localeCompare(right),
      ),
    [models],
  );

  const jobFilteredModels = useMemo(
    () =>
      models.filter((item) => {
        if (preferredFilter?.applicationIds && !preferredFilter.applicationIds.includes(item.application.id)) {
          return false;
        }
        if (jobFilter !== "all" && item.application.jobDescription.title !== jobFilter) {
          return false;
        }
        return true;
      }),
    [jobFilter, models, preferredFilter?.applicationIds],
  );

  const nodeById = useMemo(() => createNodeMap(stateMachine), [stateMachine]);
  const dateFilter = useMemo(() => resolveApplicationDateRangeFilter(dateRange), [dateRange]);
  const funnelAnalytics = useMemo(
    () => buildFunnelAnalytics(jobFilteredModels, { dateFilter, copy }),
    [copy, dateFilter, jobFilteredModels],
  );

  const stageItems = useMemo(
    () =>
      visibleMilestones.map((milestone) => {
        return {
          milestoneId: milestone.id,
          label: milestone.label,
          count: stageReachedCount(funnelAnalytics.scopedApplications, milestone.id),
        };
      }),
    [funnelAnalytics.scopedApplications, visibleMilestones],
  );

  const selectedNodeLabel =
    visibleMilestones.find((milestone) => milestone.id === selectedMilestone)?.label ?? copy("Selected stage", "当前阶段");
  const selectedStageCount = stageItems.find((item) => item.milestoneId === selectedMilestone)?.count ?? 0;
  const selectedApplications = useMemo(
    () =>
      funnelAnalytics.scopedApplications
        .filter(
          (item) =>
            selectedMilestone === "M01" || hasReachedFunnelMilestone(item.deepestMilestone, selectedMilestone),
        )
        .map((item) => ({
          ...item,
          currentNode: item.currentNode ?? nodeById.get(item.currentStatus),
        })),
    [funnelAnalytics.scopedApplications, nodeById, selectedMilestone],
  );
  const detailRecord = selectedApplications.find((item) => item.application.id === detailApplicationId) ?? null;
  const overrideRecord =
    selectedApplications.find((item) => item.application.id === overrideApplicationId) ??
    (detailRecord?.application.id === overrideApplicationId ? detailRecord : null);

  useEffect(() => {
    if (!selectedApplications.length) {
      setActiveConversationApplicationId(undefined);
      setDetailApplicationId(undefined);
      setOverrideApplicationId(undefined);
      return;
    }
    if (activeConversationApplicationId && selectedApplications.some((item) => item.application.id === activeConversationApplicationId)) {
      if (detailApplicationId && !selectedApplications.some((item) => item.application.id === detailApplicationId)) {
        setDetailApplicationId(undefined);
      }
      if (overrideApplicationId && !selectedApplications.some((item) => item.application.id === overrideApplicationId)) {
        setOverrideApplicationId(undefined);
      }
      return;
    }
    setActiveConversationApplicationId(undefined);
    if (detailApplicationId && !selectedApplications.some((item) => item.application.id === detailApplicationId)) {
      setDetailApplicationId(undefined);
    }
    if (overrideApplicationId && !selectedApplications.some((item) => item.application.id === overrideApplicationId)) {
      setOverrideApplicationId(undefined);
    }
  }, [activeConversationApplicationId, detailApplicationId, overrideApplicationId, selectedApplications]);

  useEffect(() => {
    if (!preferredApplicationId || preferredConversationToken == null) {
      return;
    }
    const target = models.find((item) => item.application.id === preferredApplicationId);
    if (!target) {
      return;
    }
    setJobFilter("all");
    if (target.deepestMilestone) {
      setSelectedMilestone(target.deepestMilestone);
    }
    setActiveConversationApplicationId(preferredApplicationId);
  }, [models, preferredApplicationId, preferredConversationToken]);

  useEffect(() => {
    if (!preferredFilter || preferredFilterToken == null) {
      return;
    }
    if (preferredFilter.jobTitle) {
      setJobFilter(preferredFilter.jobTitle);
    } else {
      setJobFilter("all");
    }
    if (preferredFilter.milestoneId && visibleMilestones.some((milestone) => milestone.id === preferredFilter.milestoneId)) {
      setSelectedMilestone(preferredFilter.milestoneId);
    }
    const targetId = preferredFilter.applicationIds?.[0] ?? preferredApplicationId;
    const target = targetId ? models.find((item) => item.application.id === targetId) : undefined;
    if (target?.deepestMilestone && !preferredFilter.milestoneId) {
      setSelectedMilestone(target.deepestMilestone);
    }
    if (targetId && models.some((item) => item.application.id === targetId)) {
      setActiveConversationApplicationId(targetId);
    }
  }, [models, preferredApplicationId, preferredFilter, preferredFilterToken, visibleMilestones]);

  return (
    <div className="application-funnel-page">
      <main className="application-funnel-main">
        <div className="application-funnel-hero">
          <div>
            <h1>{copy("Recruiting conversion analytics", "招聘转化分析")}</h1>
            <p>
              {jobFilter === "all" ? copy("All roles", "全部岗位") : jobFilter}
              {" · "}
              {copy(`${funnelAnalytics.total} applications in scope`, `当前范围 ${funnelAnalytics.total} 条投递记录`)}
            </p>
          </div>
          <div className="application-funnel-toolbar">
            <ToolbarField label={copy("Role", "岗位")}>
              <ToolbarSelect value={jobFilter} onChange={(event) => setJobFilter(event.target.value)}>
                <option value="all">{copy("All roles", "全部")}</option>
                {jobOptions.map((jobTitle) => (
                  <option key={jobTitle} value={jobTitle}>
                    {jobTitle}
                  </option>
                ))}
              </ToolbarSelect>
            </ToolbarField>
            <CandidateDateRangeControl value={dateRange} onChange={setDateRange} />
            <ToolbarRefreshButton
              onClick={() => void onRefresh?.()}
              disabled={!onRefresh}
              label={copy("Refresh", "刷新")}
              refreshingLabel={copy("Refreshing...", "刷新中...")}
            />
          </div>
        </div>

        <section className="funnel-analysis-kpis" aria-label={copy("Funnel KPIs", "漏斗关键指标")}>
          {funnelAnalytics.kpis.map((item) => (
            <article key={item.key} className="funnel-analysis-kpi" data-tone={item.tone}>
              <span>{item.label}</span>
              <strong>{item.value}</strong>
              <em>{item.caption}</em>
            </article>
          ))}
        </section>

        <section className="funnel-analysis-grid">
          <article className="funnel-analysis-panel funnel-analysis-panel--chart">
            <div className="funnel-analysis-panel__head">
              <h2>{copy("Success path funnel", "成功路径漏斗")}</h2>
              <span>{copy("M01 to M19", "M01 至 M19")}</span>
            </div>
            {funnelAnalytics.total ? (
              <FunnelChart stages={funnelAnalytics.stageMetrics} />
            ) : (
              <div className="funnel-analysis-empty">{copy("No recruiting conversion data yet.", "还没有招聘转化数据哦")}</div>
            )}
          </article>

          <article className="funnel-analysis-panel">
            <div className="funnel-analysis-panel__head">
              <h2>{copy("Stage conversion", "阶段转化率")}</h2>
              <span>{copy("Adjacent stage conversion", "相邻阶段转化")}</span>
            </div>
            {funnelAnalytics.total ? (
              <div className="funnel-conversion-list">
                {funnelAnalytics.transitionMetrics.map((item) => (
                  <div key={item.key} className="funnel-conversion-row">
                    <div>
                      <strong>{item.fromLabel} → {item.toLabel}</strong>
                      <span>{copy(`${item.dropOff} lost`, `流失 ${item.dropOff}`)}</span>
                    </div>
                    <div className="funnel-conversion-row__bar">
                      <i style={{ width: `${Math.max(2, item.conversionRate)}%` }} />
                    </div>
                    <em>{formatFunnelRate(item.conversionRate)}</em>
                  </div>
                ))}
              </div>
            ) : (
              <div className="funnel-analysis-empty">{copy("No recruiting conversion data yet.", "还没有招聘转化数据哦")}</div>
            )}
          </article>
        </section>

        <section className="funnel-analysis-grid funnel-analysis-grid--secondary">
          <article className="funnel-analysis-panel">
            <div className="funnel-analysis-panel__head">
              <h2>{copy("Role progress comparison", "岗位招聘进展对比")}</h2>
              <span>{copy("Click a role to filter", "点击岗位切换筛选")}</span>
            </div>
            <div className="funnel-job-table">
              <div className="funnel-job-table__head">
                <span>{copy("Role", "岗位")}</span>
                <span>{copy("Applications", "投递")}</span>
                <span>{copy("Interview", "面试")}</span>
                <span>Offer</span>
                <span>{copy("Success", "成功")}</span>
                <span>{copy("Rate", "成功率")}</span>
              </div>
              {funnelAnalytics.jobMetrics.length ? (
                funnelAnalytics.jobMetrics.map((row) => (
                  <button
                    key={row.key}
                    type="button"
                    className="funnel-job-table__row"
                    data-active={jobFilter === row.jobTitle}
                    onClick={() => setJobFilter(row.jobTitle)}
                  >
                    <strong>{row.jobTitle}</strong>
                    <span>{row.total}</span>
                    <span>{row.interview}</span>
                    <span>{row.offer}</span>
                    <span>{row.success}</span>
                    <span>{formatFunnelRate(row.successRate)}</span>
                  </button>
                ))
              ) : (
                <div className="funnel-analysis-empty">{copy("No data yet.", "还没有数据哦")}</div>
              )}
            </div>
          </article>

          <article className="funnel-analysis-panel">
            <div className="funnel-analysis-panel__head">
              <h2>{copy("Diagnostics", "诊断结论")}</h2>
              <span>{copy("Data-driven signals", "基于真实数据")}</span>
            </div>
            <div className="funnel-diagnostic-grid">
              {funnelAnalytics.diagnostics.map((item) => (
                <div key={item.key} className="funnel-diagnostic-card" data-tone={item.tone}>
                  <span>{item.label}</span>
                  <strong>{item.value}</strong>
                  <em>{item.detail}</em>
                </div>
              ))}
            </div>
          </article>
        </section>

        <section className="funnel-stage-navigator" aria-label={copy("Funnel stage navigation", "漏斗阶段导航")}>
          <div className="funnel-stage-navigator__head">
            <h2>{copy("Stage detail", "阶段明细")}</h2>
            <span>{copy(`${selectedStageCount} applications`, `${selectedStageCount} 条投递记录`)}</span>
          </div>
          <div className="funnel-stage-navigator__nodes">
            {stageItems.map((item) => (
              <button
                key={item.milestoneId}
                type="button"
                data-active={selectedMilestone === item.milestoneId}
                onClick={() => setSelectedMilestone(item.milestoneId)}
              >
                <i>{item.milestoneId.replace("M", "")}</i>
                <span>{item.label}</span>
                <strong>{item.count}</strong>
              </button>
            ))}
          </div>
        </section>

        <CandidateTable
          title={selectedNodeLabel}
          count={selectedApplications.length}
          description={copy("Current selected milestone candidate detail.", "当前选中阶段候选人明细。")}
          applications={selectedApplications}
          stateMachine={stateMachine}
          onOpenDetail={setDetailApplicationId}
          onOpenCommunication={setActiveConversationApplicationId}
          onTransition={onTransition}
        />
      </main>

      {activeConversationApplicationId ? (
        <CandidateCommunicationPanel
          applications={selectedApplications}
          selectedApplicationId={activeConversationApplicationId}
          stateMachine={stateMachine}
          onSelectApplication={setActiveConversationApplicationId}
          onClose={() => setActiveConversationApplicationId(undefined)}
          onOpenFullCockpit={onOpenApplication}
          onRefresh={onRefresh}
          onCreateEntry={onCreateEntry}
          onTransition={onTransition}
          operatorProfile={operatorProfile}
        />
      ) : null}

      <CandidateDetailDrawer
        open={Boolean(detailRecord)}
        record={detailRecord}
        stateMachine={stateMachine}
        onClose={() => setDetailApplicationId(undefined)}
        onTransition={onTransition}
        onRequestOverride={() => {
          if (detailRecord) {
            setOverrideApplicationId(detailRecord.application.id);
          }
        }}
      />

      <ManualStatusOverrideDrawer
        open={Boolean(overrideRecord)}
        record={overrideRecord}
        stateMachine={stateMachine}
        onClose={() => setOverrideApplicationId(undefined)}
        onSubmit={onTransition}
      />
    </div>
  );
}
