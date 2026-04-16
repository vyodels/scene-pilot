import React, { useEffect, useMemo, useRef, useState } from "react";
import type { CandidateTransitionPayload, RecruitmentStateMachine, StateNode } from "@scene-pilot/shared";
import { CandidateTable } from "../kanban-shared/CandidateTable";
import { CandidateCommunicationPanel } from "../kanban-shared/CandidateCommunicationPanel";
import {
  CandidateDateRangeControl,
  createCandidateDateRangeState,
  resolveCandidateDateRangeFilter,
  type CandidateDateRangeState,
} from "../kanban-shared/CandidateDateRangeControl";
import { CandidateDetailDrawer } from "../kanban-shared/CandidateDetailDrawer";
import { ManualStatusOverrideDrawer } from "../kanban-shared/ManualStatusOverrideDrawer";
import { StatusChain } from "../kanban-shared/StatusChain";
import { buildCandidateViewModels, isWithinCandidateDateFilter, nodeTone } from "../kanban-shared/kanbanUtils";
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

function isGlobalTerminal(node: StateNode): boolean {
  return node.phase === "Z";
}

function isBranchNode(node: StateNode): boolean {
  if (isGlobalTerminal(node)) {
    return false;
  }
  return (node.isTerminal || node.isSoftTerminal) && !node.isSuccess;
}

function estimateStatusNodeWidth(label: string): number {
  const contentWidth = Array.from(label).reduce((total, char) => {
    if (/[A-Za-z0-9]/.test(char)) {
      return total + 8;
    }
    if (char === "·" || char === "-" || char === " ") {
      return total + 5;
    }
    return total + 12;
  }, 0);
  return contentWidth + 30;
}

function splitMainNodesIntoRows(nodes: StateNode[], availableWidth: number): StateNode[][] {
  const rows: StateNode[][] = [];
  let currentRow: StateNode[] = [];
  let currentWidth = 0;
  const maxWidth = Math.max(availableWidth, 720);
  const connectorWidth = 18;

  for (const node of nodes) {
    const itemWidth = estimateStatusNodeWidth(`${node.label}-0`);
    const nextWidth = currentRow.length ? currentWidth + connectorWidth + itemWidth : currentWidth + itemWidth;
    if (currentRow.length && nextWidth > maxWidth) {
      rows.push(currentRow);
      currentRow = [node];
      currentWidth = itemWidth;
      continue;
    }
    currentRow.push(node);
    currentWidth = nextWidth;
  }

  if (currentRow.length) {
    rows.push(currentRow);
  }

  return rows;
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
  const [dateRange, setDateRange] = useState<CandidateDateRangeState>(() => createCandidateDateRangeState());
  const [selectedStatus, setSelectedStatus] = useState<string>("all");
  const [activeConversationCandidateId, setActiveConversationCandidateId] = useState<string>();
  const [detailCandidateId, setDetailCandidateId] = useState<string>();
  const [overrideCandidateId, setOverrideCandidateId] = useState<string>();
  const chainContainerRef = useRef<HTMLDivElement | null>(null);
  const [chainWidth, setChainWidth] = useState(1200);

  const models = useMemo(
    () => buildCandidateViewModels(candidates, threads, stateMachine),
    [candidates, stateMachine, threads],
  );

  const jobOptions = useMemo(
    () => Array.from(new Set(models.map((item) => item.candidate.jdTitle))).sort((left, right) => left.localeCompare(right)),
    [models],
  );

  const effectiveDateFilter = useMemo(() => resolveCandidateDateRangeFilter(dateRange), [dateRange]);

  const baseFilteredModels = useMemo(
    () =>
      models.filter((item) => {
        if (jobFilter !== "all" && item.candidate.jdTitle !== jobFilter) {
          return false;
        }
        if (!isWithinCandidateDateFilter(item.latestActivityAt, effectiveDateFilter)) {
          return false;
        }
        return true;
      }),
    [effectiveDateFilter, jobFilter, models],
  );

  const filteredModels = useMemo(
    () =>
      baseFilteredModels.filter((item) => {
        if (visibilityFilter === "human" && !item.humanRequired) {
          return false;
        }
        if (
          visibilityFilter === "active" &&
          item.currentNode &&
          (item.currentNode.isTerminal || item.currentNode.isSoftTerminal) &&
          !item.currentNode.isSuccess
        ) {
          return false;
        }
        return true;
      }),
    [baseFilteredModels, visibilityFilter],
  );

  const countByStatus = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of filteredModels) {
      counts.set(item.currentStatus, (counts.get(item.currentStatus) ?? 0) + 1);
    }
    return counts;
  }, [filteredModels]);

  const visibilityCounts = useMemo(
    () => ({
      all: baseFilteredModels.length,
      active: baseFilteredModels.filter(
        (item) =>
          !item.currentNode ||
          ((!item.currentNode.isTerminal && !item.currentNode.isSoftTerminal) || item.currentNode.isSuccess),
      ).length,
      human: baseFilteredModels.filter((item) => item.humanRequired).length,
    }),
    [baseFilteredModels],
  );

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

  const transitionsByFromState = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const transition of [...stateMachine.transitions, ...stateMachine.globalTransitions]) {
      if (!transition.fromState || transition.fromState === "*") {
        continue;
      }
      const current = map.get(transition.fromState) ?? [];
      current.push(transition.toState);
      map.set(transition.fromState, current);
    }
    return map;
  }, [stateMachine.globalTransitions, stateMachine.transitions]);

  const globalTerminalItems = useMemo(
    () =>
      stateMachine.nodes
        .filter((node) => node.uiConfig?.showInKanban !== false && !node.isTransient && isGlobalTerminal(node))
        .map((node) => ({
          statusId: node.id,
          label: node.label,
          count: countByStatus.get(node.id) ?? 0,
          tone: nodeTone(node),
        })),
    [countByStatus, stateMachine.nodes],
  );

  const rows = useMemo(
    () =>
      splitMainNodesIntoRows(mainNodes, chainWidth - 8).map((nodesInRow, rowIndex) => ({
        key: `main-${rowIndex + 1}`,
        items: nodesInRow.map((node) => ({
          statusId: node.id,
          label: node.label,
          count: countByStatus.get(node.id) ?? 0,
          tone: nodeTone(node),
          emphasized: node.executionConfig?.mode === "human_required",
          branches: branchNodes
            .filter((branch) => (transitionsByFromState.get(node.id) ?? []).includes(branch.id))
            .map((branch) => ({
              statusId: branch.id,
              label: branch.label,
              count: countByStatus.get(branch.id) ?? 0,
              tone: nodeTone(branch),
            })),
        })),
      })),
    [branchNodes, chainWidth, countByStatus, mainNodes, transitionsByFromState],
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
    if (!chainContainerRef.current || typeof ResizeObserver === "undefined") {
      return undefined;
    }
    const observer = new ResizeObserver((entries) => {
      const nextWidth = entries[0]?.contentRect.width ?? 0;
      if (nextWidth > 0) {
        setChainWidth(nextWidth);
      }
    });
    observer.observe(chainContainerRef.current);
    return () => observer.disconnect();
  }, []);

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
          {[
            { key: "all" as const, label: copy("All", "全部"), count: visibilityCounts.all },
            { key: "active" as const, label: copy("Only active", "只看未淘汰"), count: visibilityCounts.active },
            { key: "human" as const, label: copy("Needs human", "只看等待人工"), count: visibilityCounts.human },
          ].map((option) => (
            <button
              key={option.key}
              type="button"
              className="kanban-filter__toggle"
              data-active={visibilityFilter === option.key}
              onClick={() => {
                setVisibilityFilter(option.key);
                setSelectedStatus("all");
              }}
            >
              {`${option.label}-${option.count}`}
            </button>
          ))}
        </div>
        <div className="kanban-filter__group">
          {globalTerminalItems.map((item) => (
            <button
              key={item.statusId}
              type="button"
              className="kanban-filter__toggle"
              data-active={selectedStatus === item.statusId}
              onClick={() => setSelectedStatus(item.statusId)}
            >
              {`${item.label}-${item.count}`}
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
        <CandidateDateRangeControl value={dateRange} onChange={setDateRange} />
      </div>

      <div ref={chainContainerRef}>
        <StatusChain
          rows={rows}
          globalTerminalItems={[]}
          activeStatus={selectedStatus}
          showOverview={false}
          onSelect={setSelectedStatus}
        />
      </div>

      <CandidateTable
        title={selectedLabel}
        count={tableCandidates.length}
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
