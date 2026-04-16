import React, { useEffect, useMemo, useState } from "react";
import { funnelMilestones } from "@scene-pilot/shared";
import type { CandidateTransitionPayload, RecruitmentStateMachine } from "@scene-pilot/shared";
import { CandidateTable } from "../kanban-shared/CandidateTable";
import { CandidateCommunicationPanel } from "../kanban-shared/CandidateCommunicationPanel";
import {
  CandidateDateRangeControl,
  createCandidateDateRangeState,
  resolveCandidateDateRangeFilter,
  type CandidateDateRangeState,
} from "../kanban-shared/CandidateDateRangeControl";
import { CandidateDetailDrawer } from "../kanban-shared/CandidateDetailDrawer";
import { FunnelStageBar } from "../kanban-shared/FunnelStageBar";
import { ManualStatusOverrideDrawer } from "../kanban-shared/ManualStatusOverrideDrawer";
import { buildCandidateViewModels, createNodeMap, isWithinCandidateDateFilter } from "../kanban-shared/kanbanUtils";
import type { CandidateRecord, CandidateThreadRecord } from "../../lib/types";
import { useI18n } from "../../lib/i18n";

interface FunnelKanbanViewProps {
  candidates: CandidateRecord[];
  threads: CandidateThreadRecord[];
  stateMachine: RecruitmentStateMachine;
  preferredCandidateId?: string;
  preferredConversationToken?: number;
  onOpenCandidate(candidateId: string): void;
  onRefresh?(): Promise<unknown> | void;
  onCreateEntry(
    candidateId: string,
    payload: { direction: string; content: string; messageType?: string; platform?: string },
  ): Promise<unknown> | void;
  onTransition(candidateId: string, payload: CandidateTransitionPayload): Promise<unknown> | void;
}

export function FunnelKanbanView({
  candidates,
  threads,
  stateMachine,
  preferredCandidateId,
  preferredConversationToken,
  onOpenCandidate,
  onRefresh,
  onCreateEntry,
  onTransition,
}: FunnelKanbanViewProps): JSX.Element {
  const { copy } = useI18n();
  const [jobFilter, setJobFilter] = useState("all");
  const [dateRange, setDateRange] = useState<CandidateDateRangeState>(() => createCandidateDateRangeState());
  const visibleMilestones = useMemo(
    () => funnelMilestones.filter((milestone) => milestone.showInFunnel),
    [],
  );
  const [selectedMilestone, setSelectedMilestone] = useState<string>(visibleMilestones[0]?.id ?? "M01");
  const [activeConversationCandidateId, setActiveConversationCandidateId] = useState<string>();
  const [detailCandidateId, setDetailCandidateId] = useState<string>();
  const [overrideCandidateId, setOverrideCandidateId] = useState<string>();

  useEffect(() => {
    if (!visibleMilestones.some((milestone) => milestone.id === selectedMilestone)) {
      setSelectedMilestone(visibleMilestones[0]?.id ?? "M01");
    }
  }, [selectedMilestone, visibleMilestones]);

  const models = useMemo(
    () => buildCandidateViewModels(candidates, threads, stateMachine),
    [candidates, stateMachine, threads],
  );

  const jobOptions = useMemo(
    () => Array.from(new Set(models.map((item) => item.candidate.jdTitle))).sort((left, right) => left.localeCompare(right)),
    [models],
  );

  const jobFilteredModels = useMemo(
    () =>
      models.filter((item) => {
        if (jobFilter !== "all" && item.candidate.jdTitle !== jobFilter) {
          return false;
        }
        return true;
      }),
    [jobFilter, models],
  );

  const nodeById = useMemo(() => createNodeMap(stateMachine), [stateMachine]);
  const dateFilter = useMemo(() => resolveCandidateDateRangeFilter(dateRange), [dateRange]);

  const stageItems = useMemo(
    () =>
      visibleMilestones.map((milestone) => {
        const count = jobFilteredModels.filter(
          (item) =>
            item.deepestMilestone === milestone.id &&
            isWithinCandidateDateFilter(item.milestoneReachedAt[milestone.id], dateFilter),
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
  const selectedCandidates = useMemo(
    () =>
      jobFilteredModels
        .filter(
          (item) =>
            item.deepestMilestone === selectedMilestone &&
            isWithinCandidateDateFilter(item.milestoneReachedAt[selectedMilestone], dateFilter),
        )
        .map((item) => ({
          ...item,
          currentNode: item.currentNode ?? nodeById.get(item.currentStatus),
        })),
    [dateFilter, jobFilteredModels, nodeById, selectedMilestone],
  );
  const detailRecord = selectedCandidates.find((item) => item.candidate.id === detailCandidateId) ?? null;
  const overrideRecord =
    selectedCandidates.find((item) => item.candidate.id === overrideCandidateId) ??
    (detailRecord?.candidate.id === overrideCandidateId ? detailRecord : null);

  useEffect(() => {
    if (!selectedCandidates.length) {
      setActiveConversationCandidateId(undefined);
      setDetailCandidateId(undefined);
      setOverrideCandidateId(undefined);
      return;
    }
    if (activeConversationCandidateId && selectedCandidates.some((item) => item.candidate.id === activeConversationCandidateId)) {
      if (detailCandidateId && !selectedCandidates.some((item) => item.candidate.id === detailCandidateId)) {
        setDetailCandidateId(undefined);
      }
      if (overrideCandidateId && !selectedCandidates.some((item) => item.candidate.id === overrideCandidateId)) {
        setOverrideCandidateId(undefined);
      }
      return;
    }
    setActiveConversationCandidateId(undefined);
    if (detailCandidateId && !selectedCandidates.some((item) => item.candidate.id === detailCandidateId)) {
      setDetailCandidateId(undefined);
    }
    if (overrideCandidateId && !selectedCandidates.some((item) => item.candidate.id === overrideCandidateId)) {
      setOverrideCandidateId(undefined);
    }
  }, [activeConversationCandidateId, detailCandidateId, overrideCandidateId, selectedCandidates]);

  useEffect(() => {
    if (!preferredCandidateId || preferredConversationToken == null) {
      return;
    }
    const target = models.find((item) => item.candidate.id === preferredCandidateId);
    if (!target) {
      return;
    }
    setJobFilter("all");
    if (target.deepestMilestone) {
      setSelectedMilestone(target.deepestMilestone);
    }
    setActiveConversationCandidateId(preferredCandidateId);
  }, [models, preferredCandidateId, preferredConversationToken]);

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
        count={selectedCandidates.length}
        candidates={selectedCandidates}
        stateMachine={stateMachine}
        emptyMessage={copy("No candidates reached this funnel milestone under the current filters.", "当前筛选条件下该漏斗阶段没有候选人。")}
        onOpenDetail={setDetailCandidateId}
        onOpenCommunication={setActiveConversationCandidateId}
        onTransition={onTransition}
      />

      {activeConversationCandidateId ? (
        <CandidateCommunicationPanel
          candidates={selectedCandidates}
          selectedCandidateId={activeConversationCandidateId}
          stateMachine={stateMachine}
          onSelectCandidate={setActiveConversationCandidateId}
          onClose={() => setActiveConversationCandidateId(undefined)}
          onOpenFullCockpit={onOpenCandidate}
          onRefresh={onRefresh}
          onCreateEntry={onCreateEntry}
          onTransition={onTransition}
        />
      ) : null}

      <CandidateDetailDrawer
        open={Boolean(detailRecord)}
        record={detailRecord}
        stateMachine={stateMachine}
        onClose={() => setDetailCandidateId(undefined)}
        onTransition={onTransition}
        onRequestOverride={() => {
          if (detailRecord) {
            setOverrideCandidateId(detailRecord.candidate.id);
          }
        }}
      />

      <ManualStatusOverrideDrawer
        open={Boolean(overrideRecord)}
        record={overrideRecord}
        stateMachine={stateMachine}
        onClose={() => setOverrideCandidateId(undefined)}
        onSubmit={onTransition}
      />
    </div>
  );
}
