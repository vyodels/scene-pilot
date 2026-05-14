import React, { useMemo, useState } from "react";
import type { RecruitmentStateMachine } from "@recruit-agent/shared";
import { PageToolbar, PageToolbarGroup, StatusBadge } from "../../components";
import { formatCompactDate } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { translateUiToken } from "../../lib/uiText";
import type {
  ApplicationThreadRecord,
  DashboardSummary,
  JobDescriptionSummaryRecord,
} from "../../lib/types";
import {
  buildApplicationViewModels,
  getContactChannels,
  resolveContactSummary,
  type ApplicationViewModel,
} from "../kanban-shared/kanbanUtils";
import { buildFunnelAnalytics, formatFunnelRate } from "../kanban-shared/funnelAnalytics";

export type DashboardApplicationSurface = "funnel" | "followUp";

export interface DashboardApplicationRoute {
  surface: DashboardApplicationSurface;
  label?: string;
  applicationId?: string;
  applicationIds?: string[];
  jobTitle?: string;
  statusId?: string;
  summaryKey?: string;
  milestoneId?: string;
}

interface DashboardViewProps {
  summary: DashboardSummary;
  stateMachine?: RecruitmentStateMachine | null;
  jobDescriptions?: JobDescriptionSummaryRecord[];
  threads?: ApplicationThreadRecord[];
  onOpenApplications?(route: DashboardApplicationRoute): void;
  onOpenJdWorkspace?(jobKey?: string | null): void;
  onOpenAgentRuntime?(): void;
  onOpenAgentConfig?(): void;
  onOpenSettings?(): void;
}

type ApplicationLane = "review" | "followUp" | "resume" | "interview" | "decision" | "blocked" | "active";
type FocusQueueTab = "all" | "review" | "followUp" | "resume" | "decision" | "blocked";
type DashboardIconName =
  | "approval"
  | "blocked"
  | "bot"
  | "briefcase"
  | "calendar"
  | "clock"
  | "contact"
  | "message"
  | "resume"
  | "review"
  | "settings"
  | "sync";

interface LaneConfig {
  tone: "positive" | "neutral" | "warning" | "critical";
  order: number;
}

interface HealthCard {
  key: string;
  icon: DashboardIconName;
  label: string;
  value: number;
  tone: "positive" | "neutral" | "warning" | "critical";
  route?: DashboardApplicationRoute;
  onClick?(): void;
}

interface ActivityItem {
  id: string;
  label: string;
  detail: string;
  at: string;
  tone: "positive" | "neutral" | "warning" | "critical";
  route?: DashboardApplicationRoute;
  onClick?(): void;
}

const laneConfig: Record<ApplicationLane, LaneConfig> = {
  blocked: { tone: "critical", order: 0 },
  review: { tone: "warning", order: 1 },
  followUp: { tone: "warning", order: 2 },
  resume: { tone: "warning", order: 3 },
  interview: { tone: "positive", order: 4 },
  decision: { tone: "positive", order: 5 },
  active: { tone: "neutral", order: 6 },
};

const focusTabs: FocusQueueTab[] = ["all", "review", "followUp", "resume", "decision", "blocked"];

function DashboardIcon({
  name,
  tone = "neutral",
}: {
  name: DashboardIconName;
  tone?: "positive" | "neutral" | "warning" | "critical";
}): JSX.Element {
  const shared = {
    width: 20,
    height: 20,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.75,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };

  const glyph = (() => {
    switch (name) {
      case "approval":
        return (
          <svg {...shared}>
            <path d="M7 12.5 10.2 16 17 8" />
            <rect x="4.5" y="4" width="15" height="16" rx="3" />
          </svg>
        );
      case "blocked":
        return (
          <svg {...shared}>
            <circle cx="12" cy="12" r="7.5" />
            <path d="m8 8 8 8" />
          </svg>
        );
      case "bot":
        return (
          <svg {...shared}>
            <rect x="5.5" y="8" width="13" height="10" rx="3" />
            <path d="M12 5v3" />
            <path d="M9.5 13h.01" />
            <path d="M14.5 13h.01" />
            <path d="M9.5 16h5" />
          </svg>
        );
      case "briefcase":
        return (
          <svg {...shared}>
            <rect x="4.5" y="7" width="15" height="12" rx="2" />
            <path d="M9 7V5.8C9 4.8 9.8 4 10.8 4h2.4C14.2 4 15 4.8 15 5.8V7" />
            <path d="M4.5 12h15" />
          </svg>
        );
      case "calendar":
        return (
          <svg {...shared}>
            <rect x="4.5" y="5.5" width="15" height="14" rx="2" />
            <path d="M8 4v3" />
            <path d="M16 4v3" />
            <path d="M4.5 10h15" />
          </svg>
        );
      case "clock":
        return (
          <svg {...shared}>
            <circle cx="12" cy="12" r="7.5" />
            <path d="M12 8v4.5l3 1.8" />
          </svg>
        );
      case "contact":
        return (
          <svg {...shared}>
            <path d="M7 7.5h10" />
            <path d="M7 12h6" />
            <path d="M7 16.5h4" />
            <rect x="4.5" y="4.5" width="15" height="15" rx="3" />
          </svg>
        );
      case "message":
        return (
          <svg {...shared}>
            <path d="M5 6.5h14v9.5H9l-4 3v-12.5Z" />
            <path d="M8.5 10h7" />
            <path d="M8.5 13h5" />
          </svg>
        );
      case "resume":
        return (
          <svg {...shared}>
            <path d="M7 4.5h7l3 3V19.5H7z" />
            <path d="M14 4.5v3h3" />
            <path d="M9.5 12h5" />
            <path d="M9.5 15h4" />
          </svg>
        );
      case "review":
        return (
          <svg {...shared}>
            <path d="M4.5 12 9 16.5 19.5 6" />
            <path d="M5 19.5h14" />
          </svg>
        );
      case "settings":
        return (
          <svg {...shared}>
            <circle cx="12" cy="12" r="3" />
            <path d="M12 4.5v2" />
            <path d="M12 17.5v2" />
            <path d="M19.5 12h-2" />
            <path d="M6.5 12h-2" />
          </svg>
        );
      default:
        return (
          <svg {...shared}>
            <path d="M5 12h4l2-5 3 10 2-5h3" />
            <path d="M4.5 5.5h15v13h-15z" />
          </svg>
        );
    }
  })();

  return (
    <span className="dashboard-icon" data-tone={tone}>
      {glyph}
    </span>
  );
}

function classifyApplication(application: ApplicationViewModel): ApplicationLane {
  const phase = application.currentNode?.phase;
  if (application.currentNode?.isTerminal || application.currentNode?.isSoftTerminal || application.displayStatus === "exception_closed") {
    return "blocked";
  }
  if (phase === "H") {
    return "decision";
  }
  if (phase === "G") {
    return "interview";
  }
  if (phase === "C") {
    return "resume";
  }
  if (phase === "B" || phase === "F") {
    return "followUp";
  }
  if (phase === "A" || phase === "D" || phase === "E") {
    return "review";
  }
  return "active";
}

function isActiveApplication(application: ApplicationViewModel): boolean {
  const node = application.displayNode ?? application.currentNode;
  if (!node) {
    return true;
  }
  if (node.phase === "I") {
    return false;
  }
  return (!node.isTerminal && !node.isSoftTerminal) || Boolean(node.isSuccess);
}

function laneLabel(lane: ApplicationLane, copy: (en: string, zh: string) => string): string {
  switch (lane) {
    case "review":
      return copy("New review", "新入审查");
    case "followUp":
      return copy("Communication follow-up", "沟通跟进");
    case "resume":
      return copy("Missing materials", "资料缺口");
    case "interview":
      return copy("Interview", "面试");
    case "decision":
      return copy("Decision", "决策");
    case "blocked":
      return copy("Blocked", "阻塞");
    default:
      return copy("Active", "推进中");
  }
}

function focusTabLabel(tab: FocusQueueTab, copy: (en: string, zh: string) => string): string {
  switch (tab) {
    case "review":
      return copy("New review", "新入审查");
    case "followUp":
      return copy("Communication", "沟通跟进");
    case "resume":
      return copy("Materials", "资料缺口");
    case "decision":
      return copy("Interview / decision", "面试决策");
    case "blocked":
      return copy("Blocked", "阻塞");
    default:
      return copy("All", "全部");
  }
}

function focusTabMatches(tab: FocusQueueTab, lane: ApplicationLane): boolean {
  if (tab === "all") {
    return lane !== "active";
  }
  if (tab === "decision") {
    return lane === "interview" || lane === "decision";
  }
  return lane === tab;
}

function contactChannelLabel(channel: string, copy: (en: string, zh: string) => string): string {
  switch (channel) {
    case "phone":
      return copy("Phone", "电话");
    case "wechat":
      return copy("WeChat", "微信");
    case "email":
      return copy("Email", "邮箱");
    default:
      return copy("Other", "其他");
  }
}

function presentRecruitingText(text: string, copy: (en: string, zh: string) => string): string {
  const cleaned = text
    .trim()
    .replace(/^Review template candidate for\s*/i, copy("Application review: ", "投递记录待复核："))
    .replace(/^Instruction intake failed to compile an executable plan:\s*/i, copy("Plan generation failed: ", "计划生成失败："))
    .replace(/^Runtime execution completed for recruiting\.?\s*/i, "")
    .replace(/\s+/g, " ")
    .trim();
  return cleaned || copy("System update", "系统更新");
}

function normalizeJobKey(job: JobDescriptionSummaryRecord): string {
  return job.jobDescriptionId || job.title || "unknown-jd";
}

function isAssignableJob(job: JobDescriptionSummaryRecord): boolean {
  const title = job.title.trim();
  if (!title) {
    return false;
  }
  if (job.jobDescriptionId) {
    return true;
  }
  return !["未分配岗位", "unassigned role", "unknown-jd"].includes(title.toLowerCase());
}

function isRecruitingJob(job: JobDescriptionSummaryRecord): boolean {
  const status = String(job.status ?? "").trim().toLowerCase();
  return !["closed", "archived", "inactive", "done", "关闭", "已关闭", "归档", "已归档"].includes(status);
}

function uniqueJobs(
  jobDescriptions: JobDescriptionSummaryRecord[],
  applications: ApplicationViewModel[],
): JobDescriptionSummaryRecord[] {
  const jobs = new Map<string, JobDescriptionSummaryRecord>();
  for (const job of jobDescriptions) {
    if (isAssignableJob(job)) {
      jobs.set(normalizeJobKey(job), job);
    }
  }
  for (const application of applications) {
    const job = application.application.jobDescription;
    if (isAssignableJob(job)) {
      jobs.set(normalizeJobKey(job), job);
    }
  }
  return [...jobs.values()];
}

function latestActivityAt(application: ApplicationViewModel): string {
  return application.latestActivityAt || application.application.lastContactedAt || "";
}

function isStale(application: ApplicationViewModel): boolean {
  const value = latestActivityAt(application);
  if (!value) {
    return true;
  }
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) {
    return false;
  }
  return Date.now() - timestamp > 7 * 24 * 60 * 60 * 1000;
}

function routeForApplications(
  surface: DashboardApplicationSurface,
  label: string,
  applications: ApplicationViewModel[],
  extra?: Partial<DashboardApplicationRoute>,
): DashboardApplicationRoute {
  return {
    surface,
    label,
    applicationIds: applications.map((application) => application.application.id),
    ...extra,
  };
}

function sourceLabel(application: ApplicationViewModel, copy: (en: string, zh: string) => string): string {
  const source = application.application.stateSnapshot?.latestTransitionSource?.trim().toLowerCase();
  if (!source) {
    return "—";
  }
  if (source === "operator") {
    return copy("Operator", "人工");
  }
  if (source === "agent") {
    return "Agent";
  }
  if (source === "system") {
    return copy("System", "系统");
  }
  if (source === "site") {
    return copy("Site import", "站点导入");
  }
  return application.application.stateSnapshot?.latestTransitionSource ?? "—";
}

function renderEmptyState(text: string): JSX.Element {
  return (
    <div className="dashboard-empty-state">
      {text}
    </div>
  );
}

export function DashboardView({
  summary,
  stateMachine,
  jobDescriptions = [],
  threads = [],
  onOpenApplications,
  onOpenJdWorkspace,
  onOpenAgentRuntime,
  onOpenAgentConfig,
  onOpenSettings,
}: DashboardViewProps): JSX.Element {
  const { copy } = useI18n();
  const [focusTab, setFocusTab] = useState<FocusQueueTab>("all");

  const applicationModels = useMemo(
    () => (stateMachine ? buildApplicationViewModels(summary.applications, threads, stateMachine) : []),
    [stateMachine, summary.applications, threads],
  );
  const funnelAnalytics = useMemo(
    () => buildFunnelAnalytics(applicationModels, { copy }),
    [applicationModels, copy],
  );

  const applicationsByLane = useMemo(() => {
    return applicationModels.reduce<Record<ApplicationLane, ApplicationViewModel[]>>(
      (acc, application) => {
        acc[classifyApplication(application)].push(application);
        return acc;
      },
      {
        review: [],
        followUp: [],
        resume: [],
        interview: [],
        decision: [],
        blocked: [],
        active: [],
      },
    );
  }, [applicationModels]);

  const pendingApprovals = summary.approvals.filter((item) => item.status === "pending");
  const activeApplications = applicationModels.filter(isActiveApplication);
  const missingContact = applicationModels.filter((application) => {
    const contactSummary = application.contactSummary || resolveContactSummary(application.application, application.thread);
    return !application.application.stateSnapshot?.contactAcquired && contactSummary === "—";
  });
  const missingResume = applicationModels.filter((application) => !application.application.resumeAvailable && !application.offlineResumeAvailable);
  const staleApplications = applicationModels.filter(isStale);
  const jobs = useMemo(() => uniqueJobs(jobDescriptions, applicationModels), [applicationModels, jobDescriptions]);
  const recruitingJobs = jobs.filter(isRecruitingJob);
  const waitingHumanCount = summary.agent.status === "waiting_human" ? 1 : 0;
  const todayAttentionCount = new Set(
    [
      ...applicationsByLane.review,
      ...applicationsByLane.followUp,
      ...applicationsByLane.resume,
      ...applicationsByLane.interview,
      ...applicationsByLane.decision,
      ...applicationsByLane.blocked,
    ].map((application) => application.application.id),
  ).size + pendingApprovals.length + waitingHumanCount;

  const healthCards: HealthCard[] = [
    {
      key: "review",
      icon: "review",
      label: copy("New / review", "新入 / 待审查"),
      value: applicationsByLane.review.length,
      tone: applicationsByLane.review.length ? "warning" : "neutral",
      route: routeForApplications("followUp", copy("New / review", "新入 / 待审查"), applicationsByLane.review),
    },
    {
      key: "follow-up",
      icon: "message",
      label: copy("Contact / reply", "待联系 / 待回复"),
      value: applicationsByLane.followUp.length,
      tone: applicationsByLane.followUp.length ? "warning" : "neutral",
      route: routeForApplications("followUp", copy("Contact / reply", "待联系 / 待回复"), applicationsByLane.followUp),
    },
    {
      key: "resume",
      icon: "resume",
      label: copy("Missing resume", "缺简历"),
      value: missingResume.length,
      tone: missingResume.length ? "warning" : "neutral",
      route: routeForApplications("followUp", copy("Missing resume", "缺简历"), missingResume),
    },
    {
      key: "decision",
      icon: "calendar",
      label: copy("Interview / decision", "面试 / 决策"),
      value: applicationsByLane.interview.length + applicationsByLane.decision.length,
      tone: applicationsByLane.interview.length + applicationsByLane.decision.length ? "positive" : "neutral",
      route: routeForApplications(
        "followUp",
        copy("Interview / decision", "面试 / 决策"),
        [...applicationsByLane.interview, ...applicationsByLane.decision],
      ),
    },
    {
      key: "blocked",
      icon: "blocked",
      label: copy("Blocked", "阻塞"),
      value: applicationsByLane.blocked.length,
      tone: applicationsByLane.blocked.length ? "critical" : "neutral",
      route: routeForApplications("followUp", copy("Blocked", "阻塞"), applicationsByLane.blocked),
    },
    {
      key: "approvals",
      icon: "approval",
      label: copy("Pending approvals", "待审批"),
      value: pendingApprovals.length,
      tone: pendingApprovals.length ? "warning" : "neutral",
      onClick: onOpenAgentRuntime,
    },
  ];

  const focusApplications = applicationModels
    .filter((application) => focusTabMatches(focusTab, classifyApplication(application)))
    .sort((left, right) => {
      const laneDiff = laneConfig[classifyApplication(left)].order - laneConfig[classifyApplication(right)].order;
      if (laneDiff !== 0) {
        return laneDiff;
      }
      const rightTime = latestActivityAt(right);
      const leftTime = latestActivityAt(left);
      if (rightTime !== leftTime) {
        return rightTime.localeCompare(leftTime);
      }
      return left.application.person.name.localeCompare(right.application.person.name);
    })
    .slice(0, 8);

  const recentCommunicationItems = threads
    .flatMap((thread) =>
      thread.communicationLogs.slice(0, 1).map((entry) => ({
        entry,
        application: applicationModels.find((item) => item.application.id === (thread.applicationId || thread.application.id)),
      })),
    )
    .filter((item): item is { entry: (typeof threads)[number]["communicationLogs"][number]; application: ApplicationViewModel } => Boolean(item.application))
    .sort((left, right) => String(right.entry.timestamp ?? "").localeCompare(String(left.entry.timestamp ?? "")))
    .slice(0, 3);

  const activityItems: ActivityItem[] = [
    ...summary.alerts.slice(0, 4).map((event) => ({
      id: event.id,
      label: presentRecruitingText(event.label, copy),
      detail: presentRecruitingText(event.detail, copy),
      at: event.at,
      tone: event.tone,
      onClick: onOpenAgentRuntime,
    })),
    ...pendingApprovals.slice(0, 3).map((approval) => ({
      id: `approval:${approval.id}`,
      label: presentRecruitingText(approval.title, copy),
      detail: presentRecruitingText(approval.detail, copy),
      at: approval.createdAt,
      tone: "warning" as const,
      route: approval.relatedApplicationId
        ? { surface: "followUp", applicationId: approval.relatedApplicationId, label: copy("Related approval", "相关审批") }
        : undefined,
      onClick: approval.relatedApplicationId ? undefined : onOpenAgentRuntime,
    })),
  ].slice(0, 7);

  const riskItems = [
    {
      key: "reply",
      icon: "message" as const,
      label: copy("Waiting reply", "待回复"),
      value: applicationsByLane.followUp.length,
      route: routeForApplications("followUp", copy("Waiting reply", "待回复"), applicationsByLane.followUp),
    },
    {
      key: "stale",
      icon: "clock" as const,
      label: copy("Stale", "超时未跟进"),
      value: staleApplications.length,
      route: routeForApplications("followUp", copy("Stale", "超时未跟进"), staleApplications),
    },
    {
      key: "contact",
      icon: "contact" as const,
      label: copy("No contact", "缺联系方式"),
      value: missingContact.length,
      route: routeForApplications("followUp", copy("No contact", "缺联系方式"), missingContact),
    },
    {
      key: "resume",
      icon: "resume" as const,
      label: copy("No resume", "缺简历"),
      value: missingResume.length,
      route: routeForApplications("followUp", copy("No resume", "缺简历"), missingResume),
    },
  ];

  const openRoute = (route?: DashboardApplicationRoute) => {
    if (route) {
      onOpenApplications?.(route);
    }
  };

  return (
    <div className="dashboard-workbench">
      <PageToolbar className="dashboard-topbar">
        <PageToolbarGroup className="dashboard-topbar__metrics">
          <span className="dashboard-status-chip" data-tone={todayAttentionCount ? "warning" : "positive"}>
            <DashboardIcon name="clock" tone={todayAttentionCount ? "warning" : "positive"} />
            {copy("Today", "待处理")}
            <strong>{todayAttentionCount}</strong>
          </span>
          <span className="dashboard-status-chip">
            <DashboardIcon name="message" />
            {copy("Active", "活跃")}
            <strong>{activeApplications.length}</strong>
          </span>
          <span className="dashboard-status-chip">
            <DashboardIcon name="briefcase" />
            {copy("Roles", "岗位")}
            <strong>{recruitingJobs.length}</strong>
          </span>
          <span className="dashboard-status-chip" data-tone={pendingApprovals.length ? "warning" : "neutral"}>
            <DashboardIcon name="approval" tone={pendingApprovals.length ? "warning" : "neutral"} />
            {copy("Approvals", "审批")}
            <strong>{pendingApprovals.length}</strong>
          </span>
        </PageToolbarGroup>
        <PageToolbarGroup className="dashboard-action-strip" align="end">
          <button
            type="button"
            className="dashboard-button dashboard-button--primary"
            onClick={() => openRoute({ surface: "followUp", summaryKey: "active", label: copy("Active applications", "活跃投递") })}
          >
            <DashboardIcon name="message" tone="positive" />
            {copy("Application desk", "投递工作台")}
          </button>
          <button type="button" className="dashboard-button" onClick={() => onOpenJdWorkspace?.()}>
            <DashboardIcon name="briefcase" />
            JD
          </button>
          <button type="button" className="dashboard-button" onClick={onOpenAgentRuntime}>
            <DashboardIcon name="bot" />
            Agent
          </button>
        </PageToolbarGroup>
      </PageToolbar>

      <div className="dashboard-workbench__body">
        <main className="dashboard-workbench__main">
          <section className="dashboard-panel dashboard-panel--metrics">
            <div className="dashboard-kpi-strip">
              {healthCards.map((card) => (
                <button
                  key={card.key}
                  type="button"
                  className="dashboard-kpi"
                  data-tone={card.tone}
                  onClick={() => {
                    if (card.onClick) {
                      card.onClick();
                      return;
                    }
                    openRoute(card.route);
                  }}
                >
                  <DashboardIcon name={card.icon} tone={card.tone} />
                  <span className="dashboard-kpi__body">
                    <strong>{card.value}</strong>
                    <span>{card.label}</span>
                  </span>
                </button>
              ))}
            </div>
          </section>

          <section className="dashboard-panel dashboard-panel--main">
            <div className="dashboard-section-head">
              <h2>{copy("Today focus queue", "今日关注队列")}</h2>
              <StatusBadge tone="neutral">{copy(`${focusApplications.length} visible`, `当前 ${focusApplications.length} 条`)}</StatusBadge>
            </div>

            <div className="dashboard-tabs" role="tablist" aria-label={copy("Focus queue filters", "关注队列筛选")}>
              {focusTabs.map((tab) => (
                <button
                  key={tab}
                  type="button"
                  role="tab"
                  aria-selected={focusTab === tab}
                  data-active={focusTab === tab}
                  onClick={() => setFocusTab(tab)}
                >
                  {focusTabLabel(tab, copy)}
                </button>
              ))}
            </div>

            <div className="dashboard-focus-table">
              <div className="dashboard-focus-table__head">
                <span />
                <span>{copy("Candidate / JD", "候选人 / JD")}</span>
                <span>{copy("Stage", "阶段")}</span>
                <span>{copy("Next step", "下一步")}</span>
                <span>{copy("Evidence", "证据")}</span>
                <span>{copy("Updated", "更新")}</span>
              </div>
              {focusApplications.length
                ? focusApplications.map((application) => {
                    const lane = classifyApplication(application);
                    const contactSummary = application.contactSummary || resolveContactSummary(application.application, application.thread);
                    const contactChannels = getContactChannels(application.application, application.thread).map((channel) => contactChannelLabel(channel, copy));
                    const updatedAt = latestActivityAt(application);
                    return (
                      <button
                        key={application.application.id}
                        type="button"
                        className="dashboard-focus-row"
                        onClick={() =>
                          openRoute({
                            surface: "followUp",
                            applicationId: application.application.id,
                            label: application.application.person.name,
                          })
                        }
                      >
                        <DashboardIcon name={lane === "resume" ? "resume" : lane === "blocked" ? "blocked" : lane === "decision" || lane === "interview" ? "calendar" : "message"} tone={laneConfig[lane].tone} />
                        <span className="dashboard-focus-row__identity">
                          <strong>{application.application.person.name}</strong>
                          <span>{application.application.jobDescription.title || "—"} · {application.currentStatusLabel}</span>
                        </span>
                        <span className="dashboard-focus-row__stage">
                          <StatusBadge tone={laneConfig[lane].tone}>{laneLabel(lane, copy)}</StatusBadge>
                          {application.application.matchScore != null ? (
                            <StatusBadge tone="neutral">{copy(`Score ${application.application.matchScore}`, `分数 ${application.application.matchScore}`)}</StatusBadge>
                          ) : null}
                        </span>
                        <span className="dashboard-focus-row__next">{application.application.nextAction || copy("No next action recorded yet.", "尚未记录下一步建议。")}</span>
                        <span className="dashboard-focus-row__evidence">
                          <span>
                            {contactSummary !== "—" ? contactSummary : contactChannels.join(" / ") || copy("No contact", "缺联系方式")}
                            {" · "}
                            {application.application.resumeAvailable || application.offlineResumeAvailable ? copy("Resume ready", "简历已到位") : copy("Resume missing", "简历缺失")}
                          </span>
                        </span>
                        <span className="dashboard-focus-row__updated">
                          {updatedAt ? formatCompactDate(updatedAt) : sourceLabel(application, copy)}
                        </span>
                      </button>
                    );
                  })
                : renderEmptyState(copy("No focused application records under this tab.", "当前筛选下没有需要关注的投递记录。"))}
            </div>
          </section>

          <section className="dashboard-panel">
            <div className="dashboard-section-head">
              <h2>{copy("Recent business activity", "最近业务动态")}</h2>
            </div>
            <div className="dashboard-activity-list">
              {activityItems.length
                ? activityItems.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      className="dashboard-activity-row"
                      onClick={() => {
                        if (item.route) {
                          openRoute(item.route);
                          return;
                        }
                        item.onClick?.();
                      }}
                    >
                      <DashboardIcon name={item.tone === "critical" ? "blocked" : item.tone === "warning" ? "approval" : "sync"} tone={item.tone} />
                      <span>
                        <strong>{item.label}</strong>
                        <em>{item.detail}</em>
                      </span>
                      <StatusBadge tone={item.tone}>{formatCompactDate(item.at)}</StatusBadge>
                    </button>
                  ))
                : renderEmptyState(copy("No recent business activity is available yet.", "尚无最近业务动态。"))}
            </div>
          </section>
        </main>

        <aside className="dashboard-workbench__rail">
          <section className="dashboard-panel dashboard-panel--rail">
            <div className="dashboard-section-head">
              <h2>{copy("Recruiting analysis", "招聘分析入口")}</h2>
              <button
                type="button"
                className="dashboard-button dashboard-button--compact"
                onClick={() => openRoute({ surface: "funnel", label: copy("Recruiting conversion analytics", "招聘转化分析") })}
              >
                {copy("Open", "进入")}
              </button>
            </div>
            <button
              type="button"
              className="dashboard-analysis-entry"
              onClick={() => openRoute({ surface: "funnel", label: copy("Recruiting conversion analytics", "招聘转化分析") })}
            >
              <span className="dashboard-analysis-entry__hero">
                <DashboardIcon name="sync" tone={funnelAnalytics.success ? "positive" : "neutral"} />
                <span>
                  <strong>{copy("Conversion health", "转化健康度")}</strong>
                  <em>
                    {funnelAnalytics.total
                      ? copy(
                          `${funnelAnalytics.success} successful hires · ${formatFunnelRate(funnelAnalytics.successRate)} success rate`,
                          `成功 ${funnelAnalytics.success} 人 · 成功率 ${formatFunnelRate(funnelAnalytics.successRate)}`,
                        )
                      : copy("No conversion data yet.", "还没有招聘转化数据哦")}
                  </em>
                </span>
              </span>
              <span className="dashboard-analysis-entry__metrics">
                <span>
                  <strong>{funnelAnalytics.success}</strong>
                  <em>{copy("Success", "成功")}</em>
                </span>
                <span>
                  <strong>{formatFunnelRate(funnelAnalytics.successRate)}</strong>
                  <em>{copy("Success rate", "成功率")}</em>
                </span>
                <span>
                  <strong>{funnelAnalytics.maxDropOff?.dropOff ?? 0}</strong>
                  <em>{copy("Max loss", "最大流失")}</em>
                </span>
              </span>
              <span className="dashboard-analysis-entry__summary">
                {funnelAnalytics.maxDropOff?.dropOff
                  ? `${funnelAnalytics.maxDropOff.fromLabel} → ${funnelAnalytics.maxDropOff.toLabel}`
                  : copy("No obvious drop-off in the current funnel.", "当前漏斗暂无明显流失点。")}
              </span>
            </button>
          </section>

          <section className="dashboard-panel dashboard-panel--rail">
            <div className="dashboard-section-head">
              <h2>{copy("Communication and materials", "沟通与资料")}</h2>
            </div>
            <div className="dashboard-rail-stat-grid">
              {riskItems.map((item) => (
                <button key={item.key} type="button" className="dashboard-rail-stat" onClick={() => openRoute(item.route)}>
                  <DashboardIcon name={item.icon} tone={item.value ? "warning" : "neutral"} />
                  <span>
                    <strong>{item.value}</strong>
                    <em>{item.label}</em>
                  </span>
                </button>
              ))}
            </div>
            <div className="dashboard-rail-list">
              {recentCommunicationItems.length
                ? recentCommunicationItems.map(({ entry, application }) => (
                    <button
                      key={entry.id}
                      type="button"
                      className="dashboard-activity-row dashboard-activity-row--compact"
                      onClick={() => openRoute({ surface: "followUp", applicationId: application.application.id, label: application.application.person.name })}
                    >
                      <DashboardIcon name="message" />
                      <span>
                        <strong>{application.application.person.name}</strong>
                        <em>{entry.content || copy("No message content.", "暂无沟通内容。")}</em>
                      </span>
                      <StatusBadge tone="neutral">{formatCompactDate(entry.timestamp)}</StatusBadge>
                    </button>
                  ))
                : renderEmptyState(copy("No communication summary is available yet.", "尚无最近沟通摘要。"))}
            </div>
          </section>

          <section className="dashboard-panel dashboard-panel--rail">
            <div className="dashboard-section-head">
              <h2>{copy("Agent and approvals", "Agent / 审批")}</h2>
            </div>
            <div className="dashboard-rail-list">
              <button type="button" className="dashboard-activity-row" onClick={onOpenAgentRuntime}>
                <DashboardIcon name="bot" tone={summary.agent.health === "healthy" ? "positive" : summary.agent.health === "warning" ? "warning" : "critical"} />
                <span>
                  <strong>{copy("Autonomous status", "Autonomous 状态")}</strong>
                  <em>
                    {summary.agent.activeTask || copy("No active task.", "暂无运行任务。")}
                    {" · "}
                    {copy(`Queue ${summary.agent.queueDepth}`, `队列 ${summary.agent.queueDepth}`)}
                  </em>
                </span>
                <StatusBadge tone={summary.agent.health === "healthy" ? "positive" : summary.agent.health === "warning" ? "warning" : "critical"}>
                  {translateUiToken(summary.agent.status, copy)}
                </StatusBadge>
              </button>
              <button type="button" className="dashboard-activity-row" onClick={onOpenAgentRuntime}>
                <DashboardIcon name="approval" tone={pendingApprovals.length ? "warning" : "neutral"} />
                <span>
                  <strong>{copy("Pending approvals", "待处理审批")}</strong>
                  <em>{pendingApprovals[0] ? presentRecruitingText(pendingApprovals[0].title, copy) : copy("No approval is waiting now.", "当前没有待审批项。")}</em>
                </span>
                <StatusBadge tone={pendingApprovals.length ? "warning" : "neutral"}>{pendingApprovals.length}</StatusBadge>
              </button>
              <button type="button" className="dashboard-activity-row" onClick={onOpenAgentConfig}>
                <DashboardIcon name="settings" tone={summary.settings.desktopApprovalsOnly ? "warning" : "neutral"} />
                <span>
                  <strong>{copy("Assistant config", "Assistant 配置")}</strong>
                  <em>{copy("Open configuration and tool governance.", "进入配置与工具治理页面。")}</em>
                </span>
                <StatusBadge tone={summary.settings.desktopApprovalsOnly ? "warning" : "neutral"}>
                  {summary.settings.desktopApprovalsOnly ? copy("Desktop review", "桌面确认") : copy("Mixed review", "混合确认")}
                </StatusBadge>
              </button>
              <button type="button" className="dashboard-activity-row" onClick={onOpenSettings}>
                <DashboardIcon name="sync" tone={summary.settings.intranetEnabled ? "positive" : "neutral"} />
                <span>
                  <strong>{copy("Sync settings", "同步设置")}</strong>
                  <em>{summary.settings.platform.account}</em>
                </span>
                <StatusBadge tone={summary.settings.intranetEnabled ? "positive" : "neutral"}>
                  {summary.settings.intranetEnabled ? copy("Enabled", "已启用") : copy("Local", "本地")}
                </StatusBadge>
              </button>
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}
