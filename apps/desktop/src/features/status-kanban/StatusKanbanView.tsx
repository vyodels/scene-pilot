import React, { useEffect, useMemo, useState } from "react";
import type { ApplicationTransitionPayload, RecruitmentStateMachine, StateNode } from "@recruit-agent/shared";
import { PageToolbar, PageToolbarGroup, StatusBadge, ToolbarField, ToolbarInput, ToolbarRefreshButton, ToolbarSelect } from "../../components";
import {
  CandidateDateRangeControl,
  createApplicationDateRangeState,
  resolveApplicationDateRangeFilter,
  type ApplicationDateRangeState,
} from "../kanban-shared/CandidateDateRangeControl";
import {
  applicationScopedLabel,
  buildApplicationViewModels,
  isWithinApplicationDateFilter,
  nodeTone,
} from "../kanban-shared/kanbanUtils";
import type { ApplicationFollowUpSummaryDefinition, ApplicationRecord, ApplicationThreadRecord } from "../../lib/types";
import { useI18n } from "../../lib/i18n";
import type { ApplicationWorkspaceFilter } from "../candidates/CandidatesKanbanView";
import { ApplicationFollowUpWorkspace } from "./ApplicationFollowUpWorkspace";

interface StatusKanbanViewProps {
  applications: ApplicationRecord[];
  threads: ApplicationThreadRecord[];
  stateMachine: RecruitmentStateMachine;
  summaryDefinitions?: ApplicationFollowUpSummaryDefinition[];
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
  onOpenDashboard(): void;
}

function isGlobalTerminal(node: StateNode): boolean {
  return node.phase === "I";
}

function isBranchNode(node: StateNode): boolean {
  if (isGlobalTerminal(node)) {
    return false;
  }
  return (node.isTerminal || node.isSoftTerminal) && !node.isSuccess;
}

function applicationStatusLabel(label: string): string {
  return label;
}

export function StatusKanbanView({
  applications,
  threads,
  stateMachine,
  summaryDefinitions = [],
  preferredApplicationId,
  preferredConversationToken,
  preferredFilter,
  preferredFilterToken,
  onOpenApplication,
  onRefresh,
  onCreateEntry,
  onTransition,
  onOpenDashboard,
}: StatusKanbanViewProps): JSX.Element {
  const { copy } = useI18n();
  const [jobFilter, setJobFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState<ApplicationFollowUpSummaryDefinition["key"]>("all");
  const [dateRange, setDateRange] = useState<ApplicationDateRangeState>(() => createApplicationDateRangeState());
  const [selectedStatus, setSelectedStatus] = useState<string>("all");
  const [selectedApplicationId, setSelectedApplicationId] = useState<string>();
  const [stageExpanded, setStageExpanded] = useState(false);
  const [topSearch, setTopSearch] = useState("");

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
    () => summaryDefinitions,
    [summaryDefinitions],
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
        if (definition.includeStatuses.length && !definition.includeStatuses.includes(item.displayStatus)) {
          return false;
        }
        if (definition.excludeStatuses.includes(item.displayStatus)) {
          return false;
        }
        return true;
      },
    [models, summaryDefinitionByKey],
  );

  const baseFilteredModels = useMemo(
    () =>
      models.filter((item) => {
        if (preferredFilter?.applicationIds && !preferredFilter.applicationIds.includes(item.application.id)) {
          return false;
        }
        if (jobFilter !== "all" && item.application.jobDescription.title !== jobFilter) {
          return false;
        }
        if (!isWithinApplicationDateFilter(item.latestActivityAt, effectiveDateFilter)) {
          return false;
        }
        const keyword = topSearch.trim().toLowerCase();
        if (keyword) {
          const haystack = [
            item.application.person.name,
            item.application.person.title,
            item.application.person.location,
            item.application.jobDescription.title,
            item.application.platform,
            item.currentStatusLabel,
            item.contactSummary,
          ]
            .filter(Boolean)
            .join(" ")
            .toLowerCase();
          if (!haystack.includes(keyword)) {
            return false;
          }
        }
        return true;
      }),
    [effectiveDateFilter, jobFilter, models, preferredFilter?.applicationIds, topSearch],
  );

  const filteredModels = useMemo(
    () =>
      baseFilteredModels.filter((item) => {
        if (statusFilter !== "all" && !matchesSummaryDefinition(item, statusFilter)) {
          return false;
        }
        return true;
      }),
    [baseFilteredModels, matchesSummaryDefinition, statusFilter],
  );

  const countByStatus = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of filteredModels) {
      counts.set(item.displayStatus, (counts.get(item.displayStatus) ?? 0) + 1);
    }
    return counts;
  }, [filteredModels]);

  const mainNodes = useMemo(
    () =>
      stateMachine.nodes.filter(
        (node) =>
          node.uiConfig?.showInKanban !== false &&
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
          !isGlobalTerminal(node) &&
          isBranchNode(node),
      ),
    [stateMachine.nodes],
  );

  const statusSummaryOptions = useMemo(() => {
    return effectiveSummaryDefinitions.map((definition) => ({
      ...definition,
      label:
        definition.key === "all"
          ? copy("All statuses", "全部状态")
          : applicationScopedLabel(definition.label),
      count:
        definition.key === "all"
          ? baseFilteredModels.length
          : baseFilteredModels.filter((item) => matchesSummaryDefinition(item, definition.key)).length,
      kind: (
        definition.key === "all" || definition.key === "active" || definition.key === "human" ? "visibility" : "status"
      ) as "visibility" | "status",
    }));
  }, [baseFilteredModels, copy, effectiveSummaryDefinitions, matchesSummaryDefinition]);

  const statusFilterOptions = useMemo(
    () => statusSummaryOptions.filter((option) => option.key === "all" || option.kind === "status"),
    [statusSummaryOptions],
  );

  const stageItems = useMemo(
    () =>
      mainNodes.map((node) => ({
        node,
        count: countByStatus.get(node.id) ?? 0,
        tone: nodeTone(node),
      })),
    [countByStatus, mainNodes],
  );

  const branchItems = useMemo(() => {
    const nodeById = new Map(stateMachine.nodes.map((node) => [node.id, node]));
    const mainNodeIds = new Set(mainNodes.map((node) => node.id));
    return branchNodes.map((branch) => {
      const parentLinks = [...stateMachine.transitions, ...stateMachine.globalTransitions]
        .filter((transition) => transition.toState === branch.id)
        .map((transition) => transition.fromState)
        .filter((fromState, index, array) => fromState !== "*" && array.indexOf(fromState) === index)
        .map((fromState) => {
          const parent = nodeById.get(fromState);
          const parentId = mainNodeIds.has(fromState) ? fromState : "all";
          return {
            parentId,
            fromState,
            fromLabel: parent ? applicationStatusLabel(parent.label) : fromState,
          };
        });
      return {
        node: branch,
        count: countByStatus.get(branch.id) ?? 0,
        links: parentLinks.length
          ? parentLinks
          : [{ parentId: "all", fromState: "*", fromLabel: copy("Any main stage", "任意主流程节点") }],
      };
    });
  }, [branchNodes, copy, countByStatus, mainNodes, stateMachine.globalTransitions, stateMachine.nodes, stateMachine.transitions]);

  const branchItemsByParent = useMemo(() => {
    const itemsByParent = new Map<string, Array<(typeof branchItems)[number] & { fromLabel: string }>>();
    for (const item of branchItems) {
      for (const link of item.links) {
        const current = itemsByParent.get(link.parentId) ?? [];
        current.push({ ...item, fromLabel: link.fromLabel });
        itemsByParent.set(link.parentId, current);
      }
    }
    return itemsByParent;
  }, [branchItems]);

  const tableApplications = useMemo(
    () =>
      selectedStatus === "all"
        ? filteredModels
        : filteredModels.filter((item) => item.displayStatus === selectedStatus),
    [filteredModels, selectedStatus],
  );
  useEffect(() => {
    if (!tableApplications.length) {
      setSelectedApplicationId(undefined);
      return;
    }
    if (!selectedApplicationId || !tableApplications.some((item) => item.application.id === selectedApplicationId)) {
      setSelectedApplicationId(tableApplications[0]?.application.id);
    }
  }, [selectedApplicationId, tableApplications]);

  useEffect(() => {
    if (!preferredApplicationId || preferredConversationToken == null) {
      return;
    }
    const target = models.find((item) => item.application.id === preferredApplicationId);
    if (!target) {
      return;
    }
    setJobFilter("all");
    setStatusFilter("all");
    setSelectedStatus(target.displayStatus);
    setSelectedApplicationId(preferredApplicationId);
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
    if (preferredFilter.summaryKey && summaryDefinitionByKey.has(preferredFilter.summaryKey)) {
      setStatusFilter(preferredFilter.summaryKey);
    } else {
      setStatusFilter("all");
    }
    if (preferredFilter.statusId) {
      setSelectedStatus(preferredFilter.statusId);
    } else {
      setSelectedStatus("all");
    }
    const targetId = preferredFilter.applicationIds?.[0] ?? preferredApplicationId;
    if (targetId && models.some((item) => item.application.id === targetId)) {
      setSelectedApplicationId(targetId);
    }
  }, [models, preferredApplicationId, preferredFilter, preferredFilterToken, summaryDefinitionByKey]);

  return (
    <div className="application-followup-page">
      <PageToolbar className="application-followup-toolbar">
        <PageToolbarGroup className="application-followup-toolbar__filters">
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
        <ToolbarField label={copy("Status filter", "状态筛选")}>
          <ToolbarSelect value={statusFilter} onChange={(event) => {
            setStatusFilter(event.target.value as ApplicationFollowUpSummaryDefinition["key"]);
            setSelectedStatus("all");
          }}>
            {statusFilterOptions.map((option) => (
              <option key={option.key} value={option.key}>
                {option.key === "all" ? copy("All", "全部") : option.label} · {option.count}
              </option>
            ))}
          </ToolbarSelect>
        </ToolbarField>
        <CandidateDateRangeControl value={dateRange} onChange={setDateRange} />
        <ToolbarField label={copy("Status view", "状态视图")}>
          <ToolbarSelect value={selectedStatus} onChange={(event) => setSelectedStatus(event.target.value)}>
            <option value="all">{copy("Main flow", "主流程")}</option>
            {stateMachine.nodes
              .filter((node) => node.uiConfig?.showInKanban !== false)
              .map((node) => (
                <option key={node.id} value={node.id}>
                  {applicationStatusLabel(node.label)}
                </option>
              ))}
          </ToolbarSelect>
        </ToolbarField>
        </PageToolbarGroup>
        <PageToolbarGroup className="application-followup-toolbar__actions" align="end">
        <ToolbarField label={copy("Search", "搜索")} className="application-followup-toolbar__search">
          <ToolbarInput
            value={topSearch}
            onChange={(event) => setTopSearch(event.target.value)}
            placeholder={copy("Application / name / phone / email", "搜索投递记录 / 姓名 / 手机号 / 邮箱")}
          />
        </ToolbarField>
        <ToolbarRefreshButton
          onClick={() => void onRefresh?.()}
          disabled={!onRefresh}
          label={copy("Refresh", "刷新")}
          refreshingLabel={copy("Refreshing...", "刷新中...")}
        />
        {preferredFilter?.label ? (
          <StatusBadge tone="neutral">
            {copy(`From dashboard: ${preferredFilter.label}`, `首页筛选：${preferredFilter.label}`)}
          </StatusBadge>
        ) : null}
        </PageToolbarGroup>
      </PageToolbar>

      <div
        className="application-followup-stage-strip"
        data-expanded={stageExpanded ? "true" : undefined}
        aria-label={copy("Application stages", "投递状态流程")}
      >
        <div className="application-followup-stage-strip__scroller">
          <div className="application-followup-stage-strip__flow">
            <div className="application-followup-stage-strip__stage-column">
              <button
                type="button"
                className="application-followup-stage-strip__node"
                data-active={selectedStatus === "all"}
                onClick={() => setSelectedStatus("all")}
              >
                <span>{copy("All", "全部")}</span>
                <strong>{filteredModels.length}</strong>
              </button>
              {stageExpanded && branchItemsByParent.get("all")?.length ? (
                <div className="application-followup-stage-strip__branch-slot">
                  {branchItemsByParent.get("all")?.map((item) => (
                    <button
                      key={item.node.id}
                      type="button"
                      className="application-followup-stage-strip__branch-node"
                      data-active={selectedStatus === item.node.id}
                      onClick={() => setSelectedStatus(item.node.id)}
                    >
                      <span className="application-followup-stage-strip__branch-parent">{item.fromLabel}</span>
                      <span className="application-followup-stage-strip__branch-connector">↓</span>
                      <strong>{applicationStatusLabel(item.node.label)}</strong>
                      <em>{item.count}</em>
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
            {stageItems.map((item) => (
              <React.Fragment key={item.node.id}>
                <span className="application-followup-stage-strip__arrow">→</span>
                <div className="application-followup-stage-strip__stage-column">
                  <button
                    type="button"
                    className="application-followup-stage-strip__node"
                    data-active={selectedStatus === item.node.id}
                    data-tone={item.tone}
                    onClick={() => setSelectedStatus(item.node.id)}
                  >
                    <span>{applicationStatusLabel(item.node.label)}</span>
                    <strong>{item.count}</strong>
                  </button>
                  {stageExpanded && branchItemsByParent.get(item.node.id)?.length ? (
                    <div className="application-followup-stage-strip__branch-slot">
                      {branchItemsByParent.get(item.node.id)?.map((branchItem) => (
                        <button
                          key={`${item.node.id}:${branchItem.node.id}`}
                          type="button"
                          className="application-followup-stage-strip__branch-node"
                          data-active={selectedStatus === branchItem.node.id}
                          onClick={() => setSelectedStatus(branchItem.node.id)}
                        >
                          <span className="application-followup-stage-strip__branch-parent">{branchItem.fromLabel}</span>
                          <span className="application-followup-stage-strip__branch-connector">↓</span>
                          <strong>{applicationStatusLabel(branchItem.node.label)}</strong>
                          <em>{branchItem.count}</em>
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
              </React.Fragment>
            ))}
            {branchNodes.length ? (
              <button
                type="button"
                className="application-followup-stage-strip__toggle"
                onClick={() => setStageExpanded((current) => !current)}
              >
                {stageExpanded ? copy("Collapse exception flow", "收起异常流程") : copy("Expand exception flow", "展开异常流程")}
              </button>
            ) : null}
          </div>
        </div>
      </div>

      <ApplicationFollowUpWorkspace
        applications={tableApplications}
        selectedApplicationId={selectedApplicationId}
        stateMachine={stateMachine}
        onSelectApplication={setSelectedApplicationId}
        onOpenFullCockpit={onOpenApplication}
        onOpenDashboard={onOpenDashboard}
        onRefresh={onRefresh}
        onCreateEntry={onCreateEntry}
        onTransition={onTransition}
      />
    </div>
  );
}
