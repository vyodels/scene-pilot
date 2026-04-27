import React, { useEffect, useMemo, useState } from "react";
import type { ApplicationTransitionPayload, RecruitmentStateMachine, StateNode } from "@recruit-agent/shared";
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
import { ApplicationFollowUpWorkspace } from "./ApplicationFollowUpWorkspace";

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
  onOpenDashboard(): void;
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

function applicationStatusLabel(label: string): string {
  return applicationScopedLabel(label);
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
  const labelById = new Map(visibleNodes.map((node) => [node.id, applicationStatusLabel(node.label)]));

  const toLabels = (statusIds: string[]) => statusIds.map((statusId) => labelById.get(statusId) ?? statusId);

  return [
    {
      key: "all",
      label: copy("All statuses", "全部状态"),
      summary: copy(
        "All applications currently visible under the current role and date filters.",
        "当前岗位与时间筛选下可见的全部投递记录。",
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
        "Applications still progressing in the main follow-up workflow.",
        "仍在主流程里活跃推进的投递记录。",
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
        "Applications currently stopped at a recruiter-operated step.",
        "当前停在需要招聘员处理或确认节点的投递记录。",
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
        "Applications still inside the retry window after no response.",
        "已发送跟进但尚未回复，仍处于可自动重试窗口内的投递记录。",
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
        "Applications temporarily paused and waiting for manual reactivation or cooldown expiry.",
        "已暂时暂停推进，等待冷却期结束或人工重新激活的投递记录。",
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
        "Applications already closed and kept only for record.",
        "流程已收口，仅做记录保留的投递记录。",
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
      label: copy("Application withdrew", "投递人主动放弃"),
      summary: copy(
        "Applications where the applicant explicitly withdrew from the current process.",
        "投递人明确表示退出当前流程，不再继续推进。",
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
    [effectiveDateFilter, jobFilter, models, topSearch],
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

  return (
    <div className="application-followup-page">
      <div className="application-followup-toolbar">
        <label>
          <span>{copy("Role", "岗位")}</span>
          <select value={jobFilter} onChange={(event) => setJobFilter(event.target.value)}>
            <option value="all">{copy("All roles", "全部")}</option>
            {jobOptions.map((jobTitle) => (
              <option key={jobTitle} value={jobTitle}>
                {jobTitle}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>{copy("Status filter", "状态筛选")}</span>
          <select value={statusFilter} onChange={(event) => {
            setStatusFilter(event.target.value as ApplicationFollowUpSummaryDefinition["key"]);
            setSelectedStatus("all");
          }}>
            {statusFilterOptions.map((option) => (
              <option key={option.key} value={option.key}>
                {option.key === "all" ? copy("All", "全部") : option.label} · {option.count}
              </option>
            ))}
          </select>
        </label>
        <CandidateDateRangeControl value={dateRange} onChange={setDateRange} />
        <label>
          <span>{copy("Status view", "状态视图")}</span>
          <select value={selectedStatus} onChange={(event) => setSelectedStatus(event.target.value)}>
            <option value="all">{copy("Main flow", "主流程")}</option>
            {stateMachine.nodes
              .filter((node) => node.uiConfig?.showInKanban !== false && !node.isTransient)
              .map((node) => (
                <option key={node.id} value={node.id}>
                  {applicationStatusLabel(node.label)}
                </option>
              ))}
          </select>
        </label>
        <label className="application-followup-toolbar__search">
          <span>{copy("Search", "搜索")}</span>
          <input
            value={topSearch}
            onChange={(event) => setTopSearch(event.target.value)}
            placeholder={copy("Application / name / phone / email", "搜索投递记录 / 姓名 / 手机号 / 邮箱")}
          />
        </label>
        <button type="button" onClick={() => void onRefresh?.()}>{copy("Refresh", "刷新")}</button>
      </div>

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
