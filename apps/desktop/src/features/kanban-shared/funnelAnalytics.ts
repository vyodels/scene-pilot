import { getFunnelMilestone } from "@recruit-agent/shared";
import type { ApplicationDateFilter } from "./kanbanUtils";
import { hasReachedFunnelMilestone, isWithinApplicationDateFilter, type ApplicationViewModel } from "./kanbanUtils";

export const successPathMilestoneIds = ["M01", "M04", "M08", "M11", "M13", "M14", "M18", "M19"] as const;

export interface FunnelStageMetric {
  milestoneId: string;
  label: string;
  count: number;
  widthPercent: number;
}

export interface FunnelTransitionMetric {
  key: string;
  fromMilestoneId: string;
  fromLabel: string;
  toMilestoneId: string;
  toLabel: string;
  fromCount: number;
  toCount: number;
  conversionRate: number;
  dropOff: number;
}

export interface FunnelKpiMetric {
  key: "total" | "interview" | "offer" | "success" | "successRate" | "quality";
  label: string;
  value: string;
  caption: string;
  tone: "positive" | "neutral" | "warning";
}

export interface FunnelJobMetric {
  key: string;
  jobTitle: string;
  total: number;
  interview: number;
  offer: number;
  success: number;
  successRate: number;
}

export interface FunnelDiagnosticMetric {
  key: string;
  label: string;
  value: string;
  detail: string;
  tone: "positive" | "neutral" | "warning" | "critical";
}

export interface FunnelAnalyticsResult {
  scopedApplications: ApplicationViewModel[];
  stageMetrics: FunnelStageMetric[];
  transitionMetrics: FunnelTransitionMetric[];
  jobMetrics: FunnelJobMetric[];
  diagnostics: FunnelDiagnosticMetric[];
  kpis: FunnelKpiMetric[];
  total: number;
  interview: number;
  offer: number;
  success: number;
  successRate: number;
  quality: number;
  risk: number;
  maxDropOff?: FunnelTransitionMetric;
  currentBottleneck?: { label: string; count: number };
}

interface BuildFunnelAnalyticsOptions {
  dateFilter?: ApplicationDateFilter;
  copy?: (en: string, zh: string) => string;
}

const riskMilestoneIds = new Set(["M05", "M09", "M12", "M17", "M20", "M21"]);

function defaultCopy(_en: string, zh: string): string {
  return zh;
}

function milestoneLabel(milestoneId: string): string {
  return getFunnelMilestone(milestoneId)?.label ?? milestoneId;
}

function reached(application: ApplicationViewModel, milestoneId: string): boolean {
  if (milestoneId === "M01") {
    return true;
  }
  return hasReachedFunnelMilestone(application.deepestMilestone, milestoneId);
}

function isInDateScope(application: ApplicationViewModel, dateFilter?: ApplicationDateFilter): boolean {
  if (!dateFilter || dateFilter.kind === "all") {
    return true;
  }
  return isWithinApplicationDateFilter(
    application.milestoneReachedAt.M01 ?? application.latestActivityAt ?? application.application.lastContactedAt,
    dateFilter,
  );
}

function percentage(numerator: number, denominator: number): number {
  if (!denominator) {
    return 0;
  }
  return Math.round((numerator / denominator) * 1000) / 10;
}

function formatRate(value: number): string {
  if (Number.isInteger(value)) {
    return `${value}%`;
  }
  return `${value.toFixed(1)}%`;
}

function isRiskApplication(application: ApplicationViewModel): boolean {
  const node = application.displayNode ?? application.currentNode;
  if (node?.isSoftTerminal) {
    return true;
  }
  if (node?.isTerminal && !node.isSuccess) {
    return true;
  }
  return riskMilestoneIds.has(application.deepestMilestone ?? "");
}

function groupKeyForJob(application: ApplicationViewModel): string {
  return application.application.jobDescriptionId ||
    application.application.jobDescription.jobDescriptionId ||
    application.application.jobDescription.title ||
    "unknown-job";
}

export function buildFunnelAnalytics(
  applications: ApplicationViewModel[],
  options: BuildFunnelAnalyticsOptions = {},
): FunnelAnalyticsResult {
  const copy = options.copy ?? defaultCopy;
  const scopedApplications = applications.filter((application) => isInDateScope(application, options.dateFilter));
  const total = scopedApplications.length;
  const stageMetrics = successPathMilestoneIds.map((milestoneId) => {
    const count = scopedApplications.filter((application) => reached(application, milestoneId)).length;
    return {
      milestoneId,
      label: milestoneLabel(milestoneId),
      count,
      widthPercent: Math.max(18, percentage(count, total)),
    };
  });

  const transitionMetrics = stageMetrics.slice(1).map((stage, index) => {
    const previous = stageMetrics[index];
    return {
      key: `${previous.milestoneId}:${stage.milestoneId}`,
      fromMilestoneId: previous.milestoneId,
      fromLabel: previous.label,
      toMilestoneId: stage.milestoneId,
      toLabel: stage.label,
      fromCount: previous.count,
      toCount: stage.count,
      conversionRate: percentage(stage.count, previous.count),
      dropOff: Math.max(0, previous.count - stage.count),
    };
  });

  const interview = stageMetrics.find((stage) => stage.milestoneId === "M14")?.count ?? 0;
  const offer = stageMetrics.find((stage) => stage.milestoneId === "M18")?.count ?? 0;
  const success = stageMetrics.find((stage) => stage.milestoneId === "M19")?.count ?? 0;
  const successRate = percentage(success, total);
  const quality = scopedApplications.filter(
    (application) => (application.application.matchScore ?? 0) >= 80 && reached(application, "M13"),
  ).length;
  const risk = scopedApplications.filter(isRiskApplication).length;
  const maxDropOff = transitionMetrics.reduce<FunnelTransitionMetric | undefined>(
    (current, item) => (!current || item.dropOff > current.dropOff ? item : current),
    undefined,
  );

  const bottleneckCounts = new Map<string, { label: string; count: number }>();
  for (const application of scopedApplications) {
    const key = application.deepestMilestone || application.displayStatus || application.currentStatus;
    if (key === "M19") {
      continue;
    }
    const current = bottleneckCounts.get(key) ?? {
      label: application.deepestMilestoneLabel || application.displayStatusLabel || application.currentStatusLabel,
      count: 0,
    };
    current.count += 1;
    bottleneckCounts.set(key, current);
  }
  const currentBottleneck = [...bottleneckCounts.values()].sort((left, right) => right.count - left.count)[0];

  const jobs = new Map<string, FunnelJobMetric>();
  for (const application of scopedApplications) {
    const key = groupKeyForJob(application);
    const current = jobs.get(key) ?? {
      key,
      jobTitle: application.application.jobDescription.title || copy("Unassigned role", "未分配岗位"),
      total: 0,
      interview: 0,
      offer: 0,
      success: 0,
      successRate: 0,
    };
    current.total += 1;
    current.interview += reached(application, "M14") ? 1 : 0;
    current.offer += reached(application, "M18") ? 1 : 0;
    current.success += reached(application, "M19") ? 1 : 0;
    current.successRate = percentage(current.success, current.total);
    jobs.set(key, current);
  }
  const jobMetrics = [...jobs.values()].sort(
    (left, right) => right.total - left.total || right.successRate - left.successRate || left.jobTitle.localeCompare(right.jobTitle),
  );

  const diagnostics: FunnelDiagnosticMetric[] = [
    {
      key: "drop-off",
      label: copy("Largest drop-off", "最大流失点"),
      value: maxDropOff && maxDropOff.dropOff ? `${maxDropOff.dropOff}` : copy("None", "暂无"),
      detail:
        maxDropOff && maxDropOff.dropOff
          ? `${maxDropOff.fromLabel} → ${maxDropOff.toLabel} · ${formatRate(maxDropOff.conversionRate)}`
          : copy("No adjacent stage drop-off in the current scope.", "当前范围内相邻阶段暂无明显流失。"),
      tone: maxDropOff && maxDropOff.dropOff ? "warning" : "positive",
    },
    {
      key: "bottleneck",
      label: copy("Current bottleneck", "当前卡点"),
      value: currentBottleneck?.count ? `${currentBottleneck.count}` : copy("None", "暂无"),
      detail: currentBottleneck?.count
        ? currentBottleneck.label
        : copy("No active bottleneck outside successful hires.", "成功以外暂无集中卡点。"),
      tone: currentBottleneck?.count ? "warning" : "positive",
    },
    {
      key: "quality",
      label: copy("High-quality candidates", "高质量候选"),
      value: `${quality}`,
      detail: copy("Score >= 80 and profile-ready or later.", "匹配度≥80 且已到达资料准备完毕及以后。"),
      tone: quality ? "positive" : "neutral",
    },
    {
      key: "risk",
      label: copy("Risk candidates", "风险候选"),
      value: `${risk}`,
      detail: copy("Rejected, closed, or terminal non-success records.", "淘汰、关闭或非成功终态投递。"),
      tone: risk ? "critical" : "neutral",
    },
  ];

  const kpis: FunnelKpiMetric[] = [
    {
      key: "total",
      label: copy("Applications", "总投递"),
      value: `${total}`,
      caption: copy("Current filter scope", "当前筛选范围"),
      tone: "neutral",
    },
    {
      key: "interview",
      label: copy("Entered interview", "进入面试"),
      value: `${interview}`,
      caption: copy("Reached M14", "到达 M14"),
      tone: interview ? "positive" : "neutral",
    },
    {
      key: "offer",
      label: copy("Offers sent", "Offer 发出"),
      value: `${offer}`,
      caption: copy("Reached M18", "到达 M18"),
      tone: offer ? "positive" : "neutral",
    },
    {
      key: "success",
      label: copy("Successful hires", "招聘成功"),
      value: `${success}`,
      caption: copy("Offer accepted", "Offer 已接受"),
      tone: success ? "positive" : "neutral",
    },
    {
      key: "successRate",
      label: copy("Success rate", "成功率"),
      value: formatRate(successRate),
      caption: copy("M19 / M01", "M19 / M01"),
      tone: successRate ? "positive" : "neutral",
    },
    {
      key: "quality",
      label: copy("Quality pool", "高质量候选"),
      value: `${quality}`,
      caption: copy("Score >= 80", "匹配度≥80"),
      tone: quality ? "positive" : "neutral",
    },
  ];

  return {
    scopedApplications,
    stageMetrics,
    transitionMetrics,
    jobMetrics,
    diagnostics,
    kpis,
    total,
    interview,
    offer,
    success,
    successRate,
    quality,
    risk,
    maxDropOff,
    currentBottleneck,
  };
}

export function formatFunnelRate(value: number): string {
  return formatRate(value);
}
