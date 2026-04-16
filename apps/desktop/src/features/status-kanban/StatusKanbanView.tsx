import React, { useEffect, useMemo, useState } from "react";
import type { CandidateTransitionPayload, RecruitmentStateMachine, StateNode } from "@scene-pilot/shared";
import { CandidateTable } from "../kanban-shared/CandidateTable";
import { CandidateCommunicationPanel } from "../kanban-shared/CandidateCommunicationPanel";
import { CandidateDetailDrawer } from "../kanban-shared/CandidateDetailDrawer";
import { ManualStatusOverrideDrawer } from "../kanban-shared/ManualStatusOverrideDrawer";
import { StatusChain } from "../kanban-shared/StatusChain";
import { buildCandidateViewModels, nodeTone } from "../kanban-shared/kanbanUtils";
import type { CandidateRecord, CandidateThreadRecord } from "../../lib/types";
import { useI18n } from "../../lib/i18n";

interface StatusKanbanViewProps {
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

const phaseRows = [
  ["A", "B"],
  ["C", "D", "E"],
  ["F", "G", "H"],
];

function isGlobalTerminal(node: StateNode): boolean {
  return node.phase === "Z";
}

function isBranchNode(node: StateNode): boolean {
  if (isGlobalTerminal(node)) {
    return false;
  }
  return (node.isTerminal || node.isSoftTerminal) && !node.isSuccess;
}

export function StatusKanbanView({
  candidates,
  threads,
  stateMachine,
  onOpenCandidate,
  onCreateEntry,
  onTransition,
}: StatusKanbanViewProps): JSX.Element {
  const { copy } = useI18n();
  const [jobFilter, setJobFilter] = useState("all");
  const [visibilityFilter, setVisibilityFilter] = useState<"all" | "active" | "human">("all");
  const [selectedStatus, setSelectedStatus] = useState<string>("all");
  const [activeConversationCandidateId, setActiveConversationCandidateId] = useState<string>();
  const [detailCandidateId, setDetailCandidateId] = useState<string>();
  const [overrideCandidateId, setOverrideCandidateId] = useState<string>();

  const models = useMemo(
    () => buildCandidateViewModels(candidates, threads, stateMachine),
    [candidates, stateMachine, threads],
  );

  const jobOptions = useMemo(
    () => Array.from(new Set(models.map((item) => item.candidate.jdTitle))).sort((left, right) => left.localeCompare(right)),
    [models],
  );

  const filteredModels = useMemo(
    () =>
      models.filter((item) => {
        if (jobFilter !== "all" && item.candidate.jdTitle !== jobFilter) {
          return false;
        }
        if (visibilityFilter === "human" && !item.humanRequired) {
          return false;
        }
        if (visibilityFilter === "active" && item.currentNode && (item.currentNode.isTerminal || item.currentNode.isSoftTerminal) && !item.currentNode.isSuccess) {
          return false;
        }
        return true;
      }),
    [jobFilter, models, visibilityFilter],
  );

  const countByStatus = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of filteredModels) {
      counts.set(item.currentStatus, (counts.get(item.currentStatus) ?? 0) + 1);
    }
    return counts;
  }, [filteredModels]);

  const mainNodes = useMemo(
    () =>
      stateMachine.nodes.filter(
        (node) =>
          node.uiConfig?.showInKanban !== false &&
          !node.isTransient &&
          !isGlobalTerminal(node) &&
          !isBranchNode(node),
      ),
    [stateMachine.nodes],
  );

  const branchNodes = useMemo(
    () =>
      stateMachine.nodes.filter(
        (node) =>
          node.uiConfig?.showInKanban !== false &&
          !node.isTransient &&
          !isGlobalTerminal(node) &&
          isBranchNode(node),
      ),
    [stateMachine.nodes],
  );

  const globalTerminalItems = useMemo(
    () =>
      stateMachine.nodes
        .filter((node) => node.uiConfig?.showInKanban !== false && !node.isTransient && isGlobalTerminal(node))
        .map((node) => ({
          statusId: node.id,
          label: node.label,
          count: countByStatus.get(node.id) ?? 0,
          tone: nodeTone(node),
        }))
        .filter((item) => item.count > 0),
    [countByStatus, stateMachine.nodes],
  );

  const rows = useMemo(
    () =>
      phaseRows
        .map((phases, index) => {
          const rowMainNodes = mainNodes.filter((node) => phases.includes(node.phase));
          const phaseTailNode = new Map<string, string>();
          for (const node of rowMainNodes) {
            phaseTailNode.set(node.phase, node.id);
          }
          return {
            key: `row-${index + 1}`,
            items: rowMainNodes.map((node) => ({
              statusId: node.id,
              label: node.label,
              count: countByStatus.get(node.id) ?? 0,
              tone: nodeTone(node),
              emphasized: node.executionConfig?.mode === "human_required",
              branches:
                phaseTailNode.get(node.phase) === node.id
                  ? branchNodes
                      .filter((branch) => branch.phase === node.phase)
                      .map((branch) => ({
                        statusId: branch.id,
                        label: branch.label,
                        count: countByStatus.get(branch.id) ?? 0,
                        tone: nodeTone(branch),
                      }))
                      .filter((branch) => branch.count > 0)
                  : [],
            })),
          };
        })
        .filter((row) => row.items.length > 0),
    [branchNodes, countByStatus, mainNodes],
  );

  const tableCandidates = useMemo(
    () =>
      selectedStatus === "all"
        ? filteredModels
        : filteredModels.filter((item) => item.currentStatus === selectedStatus),
    [filteredModels, selectedStatus],
  );
  const detailRecord = tableCandidates.find((item) => item.candidate.id === detailCandidateId) ?? null;
  const overrideRecord =
    tableCandidates.find((item) => item.candidate.id === overrideCandidateId) ??
    (detailRecord?.candidate.id === overrideCandidateId ? detailRecord : null);

  useEffect(() => {
    if (!tableCandidates.length) {
      setActiveConversationCandidateId(undefined);
      setDetailCandidateId(undefined);
      setOverrideCandidateId(undefined);
      return;
    }
    if (activeConversationCandidateId && !tableCandidates.some((item) => item.candidate.id === activeConversationCandidateId)) {
      setActiveConversationCandidateId(undefined);
    }
    if (detailCandidateId && !tableCandidates.some((item) => item.candidate.id === detailCandidateId)) {
      setDetailCandidateId(undefined);
    }
    if (overrideCandidateId && !tableCandidates.some((item) => item.candidate.id === overrideCandidateId)) {
      setOverrideCandidateId(undefined);
    }
  }, [activeConversationCandidateId, detailCandidateId, overrideCandidateId, tableCandidates]);

  const selectedLabel =
    selectedStatus === "all"
      ? copy("All candidates", "全部候选人")
      : stateMachine.nodes.find((node) => node.id === selectedStatus)?.label ?? selectedStatus;

  return (
    <div className="kanban-page">
      <div className="kanban-filter-row">
        <div className="kanban-filter__group">
          <span className="kanban-filter__label">{copy("View", "显示")}</span>
          {[
            { key: "all" as const, label: copy("All", "全部") },
            { key: "active" as const, label: copy("Only active", "只看未淘汰") },
            { key: "human" as const, label: copy("Needs human", "只看等待人工") },
          ].map((option) => (
            <button
              key={option.key}
              type="button"
              className="kanban-filter__toggle"
              data-active={visibilityFilter === option.key}
              onClick={() => setVisibilityFilter(option.key)}
            >
              {option.label}
            </button>
          ))}
        </div>
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
      </div>

      <StatusChain
        rows={rows}
        globalTerminalItems={globalTerminalItems}
        activeStatus={selectedStatus}
        allCount={filteredModels.length}
        onSelect={setSelectedStatus}
      />

      <CandidateTable
        title={selectedLabel}
        count={tableCandidates.length}
        description={copy(
          "按当前状态展示候选人，人工节点会直接暴露状态机配置的操作按钮。",
          "按当前状态展示候选人，人工节点会直接暴露状态机配置的操作按钮。",
        )}
        candidates={tableCandidates}
        stateMachine={stateMachine}
        emptyMessage={copy("No candidates in this status under the current filters.", "当前筛选条件下该状态没有候选人。")}
        onOpenDetail={setDetailCandidateId}
        onOpenCommunication={setActiveConversationCandidateId}
        onTransition={onTransition}
      />

      {activeConversationCandidateId ? (
        <CandidateCommunicationPanel
          candidates={tableCandidates}
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
