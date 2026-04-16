import React, { useEffect, useMemo, useState } from "react";
import { funnelMilestones } from "@scene-pilot/shared";
import type { CandidateTransitionPayload, RecruitmentStateMachine } from "@scene-pilot/shared";
import { CandidateTable } from "../kanban-shared/CandidateTable";
import { CandidateCommunicationPanel } from "../kanban-shared/CandidateCommunicationPanel";
import { CandidateDetailDrawer } from "../kanban-shared/CandidateDetailDrawer";
import { FunnelStageBar } from "../kanban-shared/FunnelStageBar";
import { ManualStatusOverrideDrawer } from "../kanban-shared/ManualStatusOverrideDrawer";
import { buildCandidateViewModels, createNodeMap } from "../kanban-shared/kanbanUtils";
import type { CandidateRecord, CandidateThreadRecord } from "../../lib/types";
import { useI18n } from "../../lib/i18n";

type TimeWindow = "all" | "7d" | "30d" | "90d";

interface FunnelKanbanViewProps {
  candidates: CandidateRecord[];
  threads: CandidateThreadRecord[];
  stateMachine: RecruitmentStateMachine;
  onOpenCandidate(candidateId: string): void;
  onCreateEntry(
    candidateId: string,
    payload: { direction: string; content: string; messageType?: string; platform?: string },
  ): Promise<unknown> | void;
  onTransition(candidateId: string, payload: CandidateTransitionPayload): Promise<unknown> | void;
}

function compareByWindow(timestamp: string | undefined, windowKey: TimeWindow): boolean {
  if (windowKey === "all") {
    return true;
  }
  if (!timestamp) {
    return false;
  }
  const days = windowKey === "7d" ? 7 : windowKey === "30d" ? 30 : 90;
  const target = Date.now() - days * 24 * 60 * 60 * 1000;
  return new Date(timestamp).getTime() >= target;
}

export function FunnelKanbanView({
  candidates,
  threads,
  stateMachine,
  onOpenCandidate,
  onCreateEntry,
  onTransition,
}: FunnelKanbanViewProps): JSX.Element {
  const { copy } = useI18n();
  const [jobFilter, setJobFilter] = useState("all");
  const [timeWindow, setTimeWindow] = useState<TimeWindow>("all");
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

  const stageItems = useMemo(
    () =>
      visibleMilestones.map((milestone) => {
        const count = jobFilteredModels.filter(
          (item) => item.deepestMilestone === milestone.id && compareByWindow(item.milestoneReachedAt[milestone.id], timeWindow),
        ).length;
        const phaseNodes = stateMachine.nodes.filter(
          (node) =>
            node.phase === milestone.phase &&
            node.uiConfig?.showInFunnel === false &&
            (node.isTerminal || node.isSoftTerminal),
        );
        const annotationParts = phaseNodes
          .map((node) => {
            const nodeCount = jobFilteredModels.filter(
              (item) => item.currentStatus === node.id && compareByWindow(item.latestActivityAt, timeWindow),
            ).length;
            if (!nodeCount) {
              return null;
            }
            return `-${nodeCount} ${node.label}`;
          })
          .filter((value): value is string => Boolean(value));
        return {
          milestoneId: milestone.id,
          label: milestone.label,
          count,
          annotation: annotationParts.join(" · ") || undefined,
        };
      }),
    [jobFilteredModels, stateMachine.nodes, timeWindow, visibleMilestones],
  );

  const selectedNodeLabel =
    visibleMilestones.find((milestone) => milestone.id === selectedMilestone)?.label ?? copy("Selected stage", "当前阶段");
  const selectedCandidates = useMemo(
    () =>
      jobFilteredModels
        .filter(
          (item) =>
            item.deepestMilestone === selectedMilestone &&
            compareByWindow(item.milestoneReachedAt[selectedMilestone], timeWindow),
        )
        .map((item) => ({
          ...item,
          currentNode: item.currentNode ?? nodeById.get(item.currentStatus),
        })),
    [jobFilteredModels, nodeById, selectedMilestone, timeWindow],
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

  return (
    <div className="kanban-page">
      <div className="kanban-filter-row">
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
        <div className="kanban-filter__group">
          <span className="kanban-filter__label">{copy("Time window", "时间段")}</span>
          {[
            { key: "all" as const, label: copy("All", "全部") },
            { key: "7d" as const, label: copy("Last 7 days", "近 7 天") },
            { key: "30d" as const, label: copy("Last 30 days", "近 30 天") },
            { key: "90d" as const, label: copy("Last 90 days", "近 90 天") },
          ].map((option) => (
            <button
              key={option.key}
              type="button"
              className="kanban-filter__toggle"
              data-active={timeWindow === option.key}
              onClick={() => setTimeWindow(option.key)}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      <FunnelStageBar items={stageItems} activeMilestoneId={selectedMilestone} onSelect={setSelectedMilestone} />

      <CandidateTable
        title={selectedNodeLabel}
        count={selectedCandidates.length}
        description={copy(
          "按候选人当前最深里程碑展示，淘汰分支作为阶段注释显示。",
          "按候选人当前最深里程碑展示，淘汰分支作为阶段注释显示。",
        )}
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
