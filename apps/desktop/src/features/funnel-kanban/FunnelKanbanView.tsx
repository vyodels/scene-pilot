import React, { useEffect, useMemo, useState } from "react";
import { funnelMilestones } from "@scene-pilot/shared";
import type { CandidateTransitionPayload, RecruitmentStateMachine } from "@scene-pilot/shared";
import { CandidateTable } from "../kanban-shared/CandidateTable";
import { CandidateCommunicationPanel } from "../kanban-shared/CandidateCommunicationPanel";
import {
  CandidateDateRangeControl,
  createApplicationDateRangeState,
  resolveApplicationDateRangeFilter,
  type ApplicationDateRangeState,
} from "../kanban-shared/CandidateDateRangeControl";
import { CandidateDetailDrawer } from "../kanban-shared/CandidateDetailDrawer";
import { FunnelStageBar } from "../kanban-shared/FunnelStageBar";
import { ManualStatusOverrideDrawer } from "../kanban-shared/ManualStatusOverrideDrawer";
import { buildApplicationViewModels, createNodeMap, isWithinApplicationDateFilter } from "../kanban-shared/kanbanUtils";
import type { ApplicationRecord, ApplicationThreadRecord } from "../../lib/types";
import { useI18n } from "../../lib/i18n";

interface FunnelKanbanViewProps {
  applications: ApplicationRecord[];
  threads: ApplicationThreadRecord[];
  stateMachine: RecruitmentStateMachine;
  preferredApplicationId?: string;
  preferredConversationToken?: number;
  onOpenApplication(applicationId: string): void;
  onRefresh?(): Promise<unknown> | void;
  onCreateEntry(
    applicationId: string,
    payload: { direction: string; content: string; messageType?: string; platform?: string },
  ): Promise<unknown> | void;
  onTransition(applicationId: string, payload: CandidateTransitionPayload): Promise<unknown> | void;
}

export function FunnelKanbanView({
  applications,
  threads,
  stateMachine,
  preferredApplicationId,
  preferredConversationToken,
  onOpenApplication,
  onRefresh,
  onCreateEntry,
  onTransition,
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
        if (jobFilter !== "all" && item.application.jobDescription.title !== jobFilter) {
          return false;
        }
        return true;
      }),
    [jobFilter, models],
  );

  const nodeById = useMemo(() => createNodeMap(stateMachine), [stateMachine]);
  const dateFilter = useMemo(() => resolveApplicationDateRangeFilter(dateRange), [dateRange]);

  const stageItems = useMemo(
    () =>
      visibleMilestones.map((milestone) => {
        const count = jobFilteredModels.filter(
          (item) =>
            item.deepestMilestone === milestone.id &&
            isWithinApplicationDateFilter(item.milestoneReachedAt[milestone.id], dateFilter),
        ).length;
        return {
          milestoneId: milestone.id,
          label: milestone.label,
          count,
        };
      }),
    [dateFilter, jobFilteredModels, visibleMilestones],
  );

  const selectedNodeLabel =
    visibleMilestones.find((milestone) => milestone.id === selectedMilestone)?.label ?? copy("Selected stage", "当前阶段");
  const selectedApplications = useMemo(
    () =>
      jobFilteredModels
        .filter(
          (item) =>
            item.deepestMilestone === selectedMilestone &&
            isWithinApplicationDateFilter(item.milestoneReachedAt[selectedMilestone], dateFilter),
        )
        .map((item) => ({
          ...item,
          currentNode: item.currentNode ?? nodeById.get(item.currentStatus),
        })),
    [dateFilter, jobFilteredModels, nodeById, selectedMilestone],
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

  return (
    <div className="kanban-page">
      <div className="kanban-filter-row funnel-kanban__filter-row">
        <label className="kanban-filter">
          <span className="kanban-filter__label">{copy("Role", "岗位")}</span>
          <select value={jobFilter} onChange={(event) => setJobFilter(event.target.value)} className="kanban-filter__select">
            <option value="all">{copy("All roles", "全部")}</option>
            {jobOptions.map((jobTitle) => (
              <option key={jobTitle} value={jobTitle}>
                {jobTitle}
              </option>
            ))}
          </select>
        </label>
        <CandidateDateRangeControl value={dateRange} onChange={setDateRange} />
      </div>

      <div className="funnel-kanban__stage-row">
        <FunnelStageBar items={stageItems} activeMilestoneId={selectedMilestone} onSelect={setSelectedMilestone} />
      </div>

      <CandidateTable
        title={selectedNodeLabel}
        count={selectedApplications.length}
        applications={selectedApplications}
        stateMachine={stateMachine}
        emptyMessage={copy("No candidates reached this funnel milestone under the current filters.", "当前筛选条件下该漏斗阶段没有候选人。")}
        onOpenDetail={setDetailApplicationId}
        onOpenCommunication={setActiveConversationApplicationId}
        onTransition={onTransition}
      />

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
