import type { JobDescriptionSummaryRecord } from "../../lib/types";
import { formatDateTime } from "../../lib/format";
import type { ApplicationViewModel } from "../kanban-shared/kanbanUtils";

export type JdStatusBucket = "recruiting" | "paused" | "closed";

export interface JdFunnelStep {
  key: string;
  label: string;
  value: number;
  percent: number;
}

export interface JdRecentApplication {
  id: string;
  personName: string;
  personTitle: string;
  statusLabel: string;
  updatedAt: string;
  avatarUrl?: string;
}

export interface JdManagementRow {
  key: string;
  job: JobDescriptionSummaryRecord;
  statusBucket: JdStatusBucket;
  statusLabel: string;
  applications: ApplicationViewModel[];
  currentApplicants: number;
  interviewing: number;
  offers: number;
  ownerName: string;
  latestUpdateText: string;
  funnelSteps: JdFunnelStep[];
  recentApplications: JdRecentApplication[];
}

export interface JdManagementStats {
  total: number;
  recruiting: number;
  paused: number;
  closed: number;
}

export interface JdManagementModel {
  rows: JdManagementRow[];
  stats: JdManagementStats;
}

function asObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function pickString(value: unknown): string | undefined {
  if (typeof value !== "string") {
    return undefined;
  }
  const trimmed = value.trim();
  return trimmed || undefined;
}

function pickNumber(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
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

function normalizeStatusBucket(job: JobDescriptionSummaryRecord): JdStatusBucket {
  const status = String(job.status ?? "").trim().toLowerCase();
  if (["paused", "pause", "suspended", "hold", "暂停", "暂停中", "暂缓中"].includes(status)) {
    return "paused";
  }
  if (["closed", "archived", "inactive", "done", "关闭", "已关闭", "归档", "已归档"].includes(status)) {
    return "closed";
  }
  return "recruiting";
}

export function jdStatusLabel(bucket: JdStatusBucket): string {
  switch (bucket) {
    case "paused":
      return "暂停中";
    case "closed":
      return "已关闭";
    default:
      return "招聘中";
  }
}

function statusRank(bucket: JdStatusBucket): number {
  switch (bucket) {
    case "recruiting":
      return 0;
    case "paused":
      return 1;
    case "closed":
      return 2;
    default:
      return 3;
  }
}

function applicationBelongsToJob(application: ApplicationViewModel, job: JobDescriptionSummaryRecord): boolean {
  const applicationJobId = application.application.jobDescriptionId || application.application.jobDescription.jobDescriptionId;
  if (job.jobDescriptionId && applicationJobId) {
    return job.jobDescriptionId === applicationJobId;
  }
  return application.application.jobDescription.title === job.title;
}

function mergeJobDescriptions(
  jobDescriptions: JobDescriptionSummaryRecord[],
  applications: ApplicationViewModel[],
): JobDescriptionSummaryRecord[] {
  const jobs = new Map<string, JobDescriptionSummaryRecord>();
  for (const job of jobDescriptions) {
    if (!isAssignableJob(job)) {
      continue;
    }
    jobs.set(normalizeJobKey(job), job);
  }
  for (const application of applications) {
    const job = application.application.jobDescription;
    const key = normalizeJobKey({
      ...job,
      jobDescriptionId: application.application.jobDescriptionId || job.jobDescriptionId,
    });
    if (!isAssignableJob({ ...job, jobDescriptionId: application.application.jobDescriptionId || job.jobDescriptionId })) {
      continue;
    }
    if (!jobs.has(key)) {
      jobs.set(key, {
        ...job,
        jobDescriptionId: application.application.jobDescriptionId || job.jobDescriptionId,
      });
    }
  }
  return [...jobs.values()];
}

function hasStatusToken(application: ApplicationViewModel, tokens: string[]): boolean {
  const haystack = [
    application.currentStatus,
    application.displayStatus,
    application.currentStatusLabel,
    application.displayStatusLabel,
    application.application.currentStatus,
    application.application.stageKey,
  ].join(" ").toLowerCase();
  return tokens.some((token) => haystack.includes(token));
}

function buildFunnelSteps(applications: ApplicationViewModel[]): JdFunnelStep[] {
  const total = applications.length;
  const interviewing = applications.filter((item) => hasStatusToken(item, ["interview", "面试"])).length;
  const offers = applications.filter((item) => hasStatusToken(item, ["offer", "录用"])).length;
  const hired = applications.filter((item) => hasStatusToken(item, ["hired", "入职"])).length;
  const steps = [
    { key: "applications", label: "投递", value: total },
    { key: "communicating", label: "沟通中", value: applications.filter((item) => hasStatusToken(item, ["communicat", "dialogue", "沟通", "对话"])).length },
    { key: "interviewing", label: "面试中", value: interviewing },
    { key: "offers", label: "Offer中", value: offers },
    { key: "hired", label: "入职", value: hired },
  ];
  return steps.map((step) => ({
    ...step,
    percent: total > 0 ? Math.round((step.value / total) * 1000) / 10 : 0,
  }));
}

function getApplicationUpdatedAt(application: ApplicationViewModel): string {
  return (
    application.latestActivityAt ||
    application.thread?.stageEvents?.[0]?.createdAt ||
    application.thread?.communicationLogs?.[0]?.timestamp ||
    application.application.lastContactedAt ||
    ""
  );
}

function buildRecentApplications(applications: ApplicationViewModel[]): JdRecentApplication[] {
  return [...applications]
    .sort((left, right) => getApplicationUpdatedAt(right).localeCompare(getApplicationUpdatedAt(left)))
    .slice(0, 4)
    .map((application) => {
      const contactInfo = asObject(application.application.person.contactInfo);
      return {
        id: application.application.applicationId || application.application.id,
        personName: application.application.person.name || "未命名投递人",
        personTitle: application.application.person.title || application.application.jobDescription.title || "—",
        statusLabel: application.displayStatusLabel || application.currentStatusLabel || application.application.currentStatus,
        updatedAt: formatDateTime(getApplicationUpdatedAt(application)),
        avatarUrl:
          pickString(contactInfo.avatarUrl) ||
          pickString(contactInfo.avatar_url) ||
          pickString(contactInfo.photoUrl) ||
          pickString(contactInfo.photo_url),
      };
    });
}

function resolveOwnerName(job: JobDescriptionSummaryRecord, applications: ApplicationViewModel[]): string {
  const metadata = asObject(job.detailMetadata);
  return (
    pickString(metadata.ownerName) ||
    pickString(metadata.owner_name) ||
    pickString(metadata.recruiterName) ||
    pickString(metadata.recruiter_name) ||
    pickString(asObject(applications[0]?.application.stateSnapshot?.snapshotMetadata).ownerName) ||
    "—"
  );
}

function resolveLatestUpdateText(job: JobDescriptionSummaryRecord, applications: ApplicationViewModel[]): string {
  const latestApplicationAt = applications
    .map(getApplicationUpdatedAt)
    .filter(Boolean)
    .sort((left, right) => right.localeCompare(left))[0];
  return formatDateTime(latestApplicationAt || job.updatedAt || job.createdAt);
}

function resolveJdCounts(applications: ApplicationViewModel[]): {
  currentApplicants: number;
  interviewing: number;
  offers: number;
} {
  return {
    currentApplicants: applications.length,
    interviewing: applications.filter((item) => hasStatusToken(item, ["interview", "面试"])).length,
    offers: applications.filter((item) => hasStatusToken(item, ["offer", "录用"])).length,
  };
}

export function getJdMetadataString(job: JobDescriptionSummaryRecord, keys: string[], fallback = "—"): string {
  const metadata = asObject(job.detailMetadata);
  for (const key of keys) {
    const direct = pickString(metadata[key]);
    if (direct) {
      return direct;
    }
  }
  return fallback;
}

export function getJdMetadataNumber(job: JobDescriptionSummaryRecord, keys: string[], fallback = 0): number {
  const metadata = asObject(job.detailMetadata);
  for (const key of keys) {
    const direct = pickNumber(metadata[key]);
    if (direct != null) {
      return direct;
    }
  }
  return fallback;
}

export function buildJdManagementModel(
  jobDescriptions: JobDescriptionSummaryRecord[],
  applications: ApplicationViewModel[],
): JdManagementModel {
  const jobs = mergeJobDescriptions(jobDescriptions, applications);
  const rows = jobs.map((job) => {
    const relatedApplications = applications.filter((application) => applicationBelongsToJob(application, job));
    const statusBucket = normalizeStatusBucket(job);
    const counts = resolveJdCounts(relatedApplications);
    return {
      key: normalizeJobKey(job),
      job,
      statusBucket,
      statusLabel: jdStatusLabel(statusBucket),
      applications: relatedApplications,
      ...counts,
      ownerName: resolveOwnerName(job, relatedApplications),
      latestUpdateText: resolveLatestUpdateText(job, relatedApplications),
      funnelSteps: buildFunnelSteps(relatedApplications),
      recentApplications: buildRecentApplications(relatedApplications),
    } satisfies JdManagementRow;
  }).sort((left, right) => (
    statusRank(left.statusBucket) - statusRank(right.statusBucket) ||
    right.currentApplicants - left.currentApplicants ||
    left.job.title.localeCompare(right.job.title, "zh-CN")
  ));

  return {
    rows,
    stats: {
      total: rows.length,
      recruiting: rows.filter((row) => row.statusBucket === "recruiting").length,
      paused: rows.filter((row) => row.statusBucket === "paused").length,
      closed: rows.filter((row) => row.statusBucket === "closed").length,
    },
  };
}
