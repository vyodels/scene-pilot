import React, { useEffect, useMemo, useRef, useState } from "react";
import type { ApplicationTransitionPayload, RecruitmentStateMachine, StateNode } from "@scene-pilot/shared";
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
import { StatusChain } from "../kanban-shared/StatusChain";
import { buildApplicationViewModels, isWithinApplicationDateFilter, nodeTone } from "../kanban-shared/kanbanUtils";
import type { ApplicationFollowUpSummaryDefinition, ApplicationRecord, ApplicationThreadRecord } from "../../lib/types";
import { useI18n } from "../../lib/i18n";

interface StatusKanbanViewProps {
  applications: ApplicationRecord[];
  threads: ApplicationThreadRecord[];
  stateMachine: RecruitmentStateMachine;
  summaryDefinitions?: ApplicationFollowUpSummaryDefinition[];
  preferredApplicationId?: string;
  preferredConversationToken?: number;
  onOpenApplication(applicationId: string): void;
  onRefresh?(): Promise<unknown> | void;
  onCreateEntry(
    applicationId: string,
    payload: { direction: string; content: string; messageType?: string; platform?: string },
  ): Promise<unknown> | void;
  onTransition(applicationId: string, payload: ApplicationTransitionPayload): Promise<unknown> | void;
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

function isProcessNode(node: StateNode): boolean {
  return !isGlobalTerminal(node) && !node.isTerminal && !node.isSoftTerminal;
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

function buildFallbackSummaryDefinitions(
  stateMachine: RecruitmentStateMachine,
  copy: (en: string, zh: string) => string,
): ApplicationFollowUpSummaryDefinition[] {
  const visibleNodes = stateMachine.nodes.filter(
    (node) => node.uiConfig?.showInKanban !== false && !node.isTransient,
  );
  const closureStatuses = visibleNodes
    .filter((node) => ["no_response", "cooldown", "archived", "candidate_withdrew"].includes(node.id))
    .map((node) => node.id);
  const activeStatuses = visibleNodes
    .filter(
      (node) =>
        node.phase !== "Z" &&
        (((!node.isTerminal && !node.isSoftTerminal) || node.isSuccess)) &&
        !closureStatuses.includes(node.id),
    )
    .map((node) => node.id);
  const humanRequiredStatuses = visibleNodes
    .filter((node) => activeStatuses.includes(node.id) && node.executionConfig?.mode === "human_required")
    .map((node) => node.id);
  const labelById = new Map(visibleNodes.map((node) => [node.id, node.label]));

  const toLabels = (statusIds: string[]) => statusIds.map((statusId) => labelById.get(statusId) ?? statusId);

  return [
    {
      key: "all",
      label: copy("All statuses", "全部状态"),
      summary: copy(
        "All candidates currently visible under the current role and date filters.",
        "当前岗位与时间筛选下可见的全部候选人。",
      ),
      relation: copy("Base pool", "基准池"),
      matchingMode: "all",
      includeStatuses: visibleNodes.map((node) => node.id),
      excludeStatuses: [],
      includeLabels: toLabels(visibleNodes.map((node) => node.id)),
      excludeLabels: [],
    },
    {
      key: "active",
      label: copy("In follow-up", "跟进中"),
      summary: copy(
        "Candidates still progressing in the main follow-up workflow.",
        "仍在主流程里活跃推进的候选人总池。",
      ),
      relation: copy("Main workflow pool", "主流程总池"),
      matchingMode: "status_set",
      includeStatuses: activeStatuses,
      excludeStatuses: closureStatuses,
      includeLabels: toLabels(activeStatuses),
      excludeLabels: toLabels(closureStatuses),
    },
    {
      key: "human",
      label: copy("Needs human", "等待人工"),
      summary: copy(
        "Candidates currently stopped at a recruiter-operated step.",
        "当前停在需要招聘员处理或确认节点的候选人。",
      ),
      relation: copy("Subset of in follow-up", "跟进中的子集"),
      matchingMode: "status_set",
      includeStatuses: humanRequiredStatuses,
      excludeStatuses: closureStatuses,
      includeLabels: toLabels(humanRequiredStatuses),
      excludeLabels: toLabels(closureStatuses),
    },
    {
      key: "no_response",
      label: copy("Retry pending", "无回复·可重试"),
      summary: copy(
        "Candidates still inside the retry window after no response.",
        "已发送跟进但尚未回复，仍处于可自动重试窗口内的候选人。",
      ),
      relation: copy("Independent waiting pool", "独立等待池"),
      matchingMode: "status_set",
      includeStatuses: visibleNodes.filter((node) => node.id === "no_response").map((node) => node.id),
      excludeStatuses: [],
      includeLabels: toLabels(visibleNodes.filter((node) => node.id === "no_response").map((node) => node.id)),
      excludeLabels: [],
    },
    {
      key: "cooldown",
      label: copy("Cooldown", "冷却中"),
      summary: copy(
        "Candidates temporarily paused and waiting for manual reactivation or cooldown expiry.",
        "已暂时暂停推进，等待冷却期结束或人工重新激活的候选人。",
      ),
      relation: copy("Paused pool", "暂停池"),
      matchingMode: "status_set",
      includeStatuses: visibleNodes.filter((node) => node.id === "cooldown").map((node) => node.id),
      excludeStatuses: [],
      includeLabels: toLabels(visibleNodes.filter((node) => node.id === "cooldown").map((node) => node.id)),
      excludeLabels: [],
    },
    {
      key: "archived",
      label: copy("Archived", "已归档"),
      summary: copy(
        "Candidates already closed and kept only for record.",
        "流程已收口，仅做记录保留的候选人。",
      ),
      relation: copy("Closed state", "收口态"),
      matchingMode: "status_set",
      includeStatuses: visibleNodes.filter((node) => node.id === "archived").map((node) => node.id),
      excludeStatuses: [],
      includeLabels: toLabels(visibleNodes.filter((node) => node.id === "archived").map((node) => node.id)),
      excludeLabels: [],
    },
    {
      key: "candidate_withdrew",
      label: copy("Candidate withdrew", "候选人主动放弃"),
      summary: copy(
        "Candidates who explicitly withdrew from the current process.",
        "候选人明确表示退出当前流程，不再继续推进。",
      ),
      relation: copy("Closed state", "收口态"),
      matchingMode: "status_set",
      includeStatuses: visibleNodes.filter((node) => node.id === "candidate_withdrew").map((node) => node.id),
      excludeStatuses: [],
      includeLabels: toLabels(visibleNodes.filter((node) => node.id === "candidate_withdrew").map((node) => node.id)),
      excludeLabels: [],
    },
  ];
}

export function StatusKanbanView({
  applications,
  threads,
  stateMachine,
  summaryDefinitions = [],
  preferredApplicationId,
  preferredConversationToken,
  onOpenApplication,
  onRefresh,
  onCreateEntry,
  onTransition,
}: StatusKanbanViewProps): JSX.Element {
  const { copy } = useI18n();
  const [jobFilter, setJobFilter] = useState("all");
  const [visibilityFilter, setVisibilityFilter] = useState<"all" | "active" | "human">("all");
  const [dateRange, setDateRange] = useState<ApplicationDateRangeState>(() => createApplicationDateRangeState());
  const [selectedStatus, setSelectedStatus] = useState<string>("all");
  const [hoveredSummaryKey, setHoveredSummaryKey] =
    useState<ApplicationFollowUpSummaryDefinition["key"] | null>(null);
  const [activeConversationApplicationId, setActiveConversationApplicationId] = useState<string>();
  const [detailApplicationId, setDetailApplicationId] = useState<string>();
  const [overrideApplicationId, setOverrideApplicationId] = useState<string>();
  const chainContainerRef = useRef<HTMLDivElement | null>(null);
  const [chainWidth, setChainWidth] = useState(1200);

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

  const effectiveDateFilter = useMemo(() => resolveApplicationDateRangeFilter(dateRange), [dateRange]);
  const effectiveSummaryDefinitions = useMemo(
    () => (summaryDefinitions.length ? summaryDefinitions : buildFallbackSummaryDefinitions(stateMachine, copy)),
    [copy, stateMachine, summaryDefinitions],
  );

  const summaryDefinitionByKey = useMemo(
    () => new Map(effectiveSummaryDefinitions.map((definition) => [definition.key, definition])),
    [effectiveSummaryDefinitions],
  );

  const matchesSummaryDefinition = useMemo(
    () =>
      (
        item: (typeof models)[number],
        key: ApplicationFollowUpSummaryDefinition["key"],
      ): boolean => {
        const definition = summaryDefinitionByKey.get(key);
        if (!definition || definition.matchingMode === "all") {
          return true;
        }
        if (definition.includeStatuses.length && !definition.includeStatuses.includes(item.currentStatus)) {
          return false;
        }
        if (definition.excludeStatuses.includes(item.currentStatus)) {
          return false;
        }
        return true;
      },
    [models, summaryDefinitionByKey],
  );

  const baseFilteredModels = useMemo(
    () =>
      models.filter((item) => {
        if (jobFilter !== "all" && item.application.jobDescription.title !== jobFilter) {
          return false;
        }
        if (!isWithinApplicationDateFilter(item.latestActivityAt, effectiveDateFilter)) {
          return false;
        }
        return true;
      }),
    [effectiveDateFilter, jobFilter, models],
  );

  const filteredModels = useMemo(
    () =>
      baseFilteredModels.filter((item) => {
        if (visibilityFilter !== "all" && !matchesSummaryDefinition(item, visibilityFilter)) {
          return false;
        }
        return true;
      }),
    [baseFilteredModels, matchesSummaryDefinition, visibilityFilter],
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
          node.id !== "no_response" &&
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
          node.id !== "no_response" &&
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

  const statusSummaryOptions = useMemo(() => {
    return effectiveSummaryDefinitions.map((definition) => ({
      ...definition,
      label:
        definition.key === "all"
          ? copy("All statuses", "全部状态")
          : definition.label,
      count:
        definition.key === "all"
          ? baseFilteredModels.length
          : baseFilteredModels.filter((item) => matchesSummaryDefinition(item, definition.key)).length,
      kind: (
        definition.key === "all" || definition.key === "active" || definition.key === "human" ? "visibility" : "status"
      ) as "visibility" | "status",
    }));
  }, [baseFilteredModels, copy, effectiveSummaryDefinitions, matchesSummaryDefinition]);

  const rows = useMemo(
    () =>
      splitMainNodesIntoRows(mainNodes, chainWidth - 8).map((nodesInRow, rowIndex) => ({
        key: `main-${rowIndex + 1}`,
        items: nodesInRow.map((node) => {
          const count = countByStatus.get(node.id) ?? 0;
          return {
            statusId: node.id,
            label: node.label,
            count,
            tone: nodeTone(node),
            emphasized: node.executionConfig?.mode === "human_required",
            showAlertMarker: isProcessNode(node) && count > 0,
            branches: branchNodes
              .filter((branch) => (transitionsByFromState.get(node.id) ?? []).includes(branch.id))
              .map((branch) => ({
                statusId: branch.id,
                label: branch.label,
                count: countByStatus.get(branch.id) ?? 0,
                tone: nodeTone(branch),
                emphasized: branch.executionConfig?.mode === "human_required",
              })),
          };
        }),
      })),
    [branchNodes, chainWidth, countByStatus, mainNodes, transitionsByFromState],
  );

  const tableApplications = useMemo(
    () =>
      selectedStatus === "all"
        ? filteredModels
        : filteredModels.filter((item) => item.currentStatus === selectedStatus),
    [filteredModels, selectedStatus],
  );
  const detailRecord = tableApplications.find((item) => item.application.id === detailApplicationId) ?? null;
  const overrideRecord =
    tableApplications.find((item) => item.application.id === overrideApplicationId) ??
    (detailRecord?.application.id === overrideApplicationId ? detailRecord : null);

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
    if (!tableApplications.length) {
      setActiveConversationApplicationId(undefined);
      setDetailApplicationId(undefined);
      setOverrideApplicationId(undefined);
      return;
    }
    if (activeConversationApplicationId && !tableApplications.some((item) => item.application.id === activeConversationApplicationId)) {
      setActiveConversationApplicationId(undefined);
    }
    if (detailApplicationId && !tableApplications.some((item) => item.application.id === detailApplicationId)) {
      setDetailApplicationId(undefined);
    }
    if (overrideApplicationId && !tableApplications.some((item) => item.application.id === overrideApplicationId)) {
      setOverrideApplicationId(undefined);
    }
  }, [activeConversationApplicationId, detailApplicationId, overrideApplicationId, tableApplications]);

  useEffect(() => {
    if (!preferredApplicationId || preferredConversationToken == null) {
      return;
    }
    const target = models.find((item) => item.application.id === preferredApplicationId);
    if (!target) {
      return;
    }
    setJobFilter("all");
    setVisibilityFilter("all");
    setSelectedStatus(target.currentStatus);
    setActiveConversationApplicationId(preferredApplicationId);
  }, [models, preferredApplicationId, preferredConversationToken]);

  const selectedLabel =
    selectedStatus === "all"
      ? copy("All candidates", "全部候选人")
      : selectedStatus === "cooldown"
        ? copy("Cooldown candidates", "冷却中候选人")
        : selectedStatus === "no_response"
          ? copy("Retry pending candidates", "无回复·可重试候选人")
      : stateMachine.nodes.find((node) => node.id === selectedStatus)?.label ?? copy("Status not mapped", "状态未映射");

  return (
    <div className="kanban-page">
      <div className="kanban-filter-row status-kanban__summary-row">
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
        <div className="kanban-filter__group">
          {statusSummaryOptions.map((option) => (
            <div
              key={option.key}
              className="kanban-summary-filter"
              onMouseEnter={() => setHoveredSummaryKey(option.key)}
              onMouseLeave={() => setHoveredSummaryKey((current) => (current === option.key ? null : current))}
            >
              <button
                type="button"
                className="kanban-filter__toggle"
                data-active={
                  option.kind === "visibility"
                    ? visibilityFilter === option.key && selectedStatus === "all"
                    : selectedStatus === option.key
                }
                onFocus={() => setHoveredSummaryKey(option.key)}
                onBlur={() => setHoveredSummaryKey((current) => (current === option.key ? null : current))}
                onClick={() => {
                  if (option.kind === "visibility") {
                    setVisibilityFilter(option.key as "all" | "active" | "human");
                    setSelectedStatus("all");
                  } else {
                    setVisibilityFilter("all");
                    setSelectedStatus(option.key);
                  }
                }}
              >
                {`${option.label}-${option.count}`}
              </button>
              {hoveredSummaryKey === option.key ? (
                <div className="kanban-summary-filter__popover" role="dialog" aria-label={option.label}>
                  <div className="kanban-summary-filter__title">{option.label}</div>
                  <div className="kanban-summary-filter__summary">{option.summary}</div>
                  {option.relation ? (
                    <div className="kanban-summary-filter__meta">
                      <span className="kanban-summary-filter__pill">{option.relation}</span>
                    </div>
                  ) : null}
                  {option.includeLabels.length ? (
                    <div className="kanban-summary-filter__group">
                      <div className="kanban-summary-filter__group-label">{copy("Includes", "包含")}</div>
                      <div className="kanban-summary-filter__pill-row">
                        {option.includeLabels.map((label) => (
                          <span key={`${option.key}:include:${label}`} className="kanban-summary-filter__pill">
                            {label}
                          </span>
                        ))}
                      </div>
                    </div>
                  ) : null}
                  {option.excludeLabels.length ? (
                    <div className="kanban-summary-filter__group">
                      <div className="kanban-summary-filter__group-label">{copy("Excludes", "不包含")}</div>
                      <div className="kanban-summary-filter__pill-row">
                        {option.excludeLabels.map((label) => (
                          <span
                            key={`${option.key}:exclude:${label}`}
                            className="kanban-summary-filter__pill kanban-summary-filter__pill--muted"
                          >
                            {label}
                          </span>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      </div>

      <div ref={chainContainerRef}>
        <StatusChain
          rows={rows}
          globalTerminalItems={[]}
          activeStatus={selectedStatus === "no_response" ? "cooldown" : selectedStatus}
          showOverview={false}
          humanRequiredTooltip={copy("This node requires recruiter action.", "这个节点是需要人工操作的节点。")}
          onSelect={setSelectedStatus}
        />
      </div>

      <CandidateTable
        title={selectedLabel}
        count={tableApplications.length}
        applications={tableApplications}
        stateMachine={stateMachine}
        emptyMessage={copy("No candidates in this status under the current filters.", "当前筛选条件下该状态没有候选人。")}
        onOpenDetail={setDetailApplicationId}
        onOpenCommunication={setActiveConversationApplicationId}
        onTransition={onTransition}
      />

      {activeConversationApplicationId ? (
        <CandidateCommunicationPanel
          applications={tableApplications}
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
