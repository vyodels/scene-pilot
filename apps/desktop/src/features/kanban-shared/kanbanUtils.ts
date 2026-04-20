import { getTriggeredMilestones } from "@scene-pilot/shared";
import type { HumanActionDefinition, RecruitmentStateMachine, StateNode, StateTransition } from "@scene-pilot/shared";
import type { ApplicationRecord, ApplicationThreadRecord } from "../../lib/types";

export interface ApplicationViewModel {
  application: ApplicationRecord;
  thread?: ApplicationThreadRecord;
  currentStatus: string;
  currentNode?: StateNode;
  deepestMilestone?: string | null;
  latestActivityAt?: string;
  humanRequired: boolean;
  onlineResumeAvailable: boolean;
  offlineResumeAvailable: boolean;
  contactSummary: string;
  milestoneReachedAt: Record<string, string>;
}

export interface ApplicationDateFilter {
  kind: "all" | "custom";
  startDate: string;
  endDate: string;
}

export interface ContactDetailSummary {
  channel: "phone" | "wechat" | "email" | "other";
  value: string;
  source: string;
  recordedAt?: string;
}

export interface ResumeArtifactSummary {
  id: string;
  title: string;
  path?: string;
  source: string;
  recordedAt?: string;
  excerpt?: string;
  contactSummary?: string;
}

const orderedContactKeys = [
  "phone",
  "mobile",
  "telephone",
  "wechat",
  "weixin",
  "wx",
  "email",
  "contact",
  "contact_value",
] as const;

interface ContactDetailCandidate extends ContactDetailSummary {
  identity: string;
}

function asObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function pickString(value: unknown): string | undefined {
  if (typeof value !== "string") {
    return undefined;
  }
  const trimmed = value.trim();
  return trimmed ? trimmed : undefined;
}

function normalizeContactChannel(key: string): ContactDetailSummary["channel"] {
  const normalized = key.trim().toLowerCase();
  if (normalized === "phone" || normalized === "mobile" || normalized === "telephone") {
    return "phone";
  }
  if (normalized === "wechat" || normalized === "weixin" || normalized === "wx") {
    return "wechat";
  }
  if (normalized === "email") {
    return "email";
  }
  return "other";
}

function summarizeSourceToken(value: string): string {
  const text = value.trim();
  if (!text) {
    return "unknown";
  }
  return text
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function maskPhoneValue(value: string): string {
  const digits = value.replace(/\D+/g, "");
  if (!digits) {
    return value;
  }
  if (digits.length <= 4) {
    return `${digits.slice(0, 1)}***`;
  }
  if (digits.length <= 7) {
    return `${digits.slice(0, 2)}***${digits.slice(-2)}`;
  }
  return `${digits.slice(0, 3)}****${digits.slice(-4)}`;
}

function maskEmailValue(value: string): string {
  const [localPart, domain] = value.split("@");
  if (!localPart || !domain) {
    return value;
  }
  if (localPart.length <= 2) {
    return `${localPart.slice(0, 1)}***@${domain}`;
  }
  return `${localPart.slice(0, 2)}***@${domain}`;
}

function maskGenericValue(value: string): string {
  if (value.length <= 2) {
    return `${value.slice(0, 1)}***`;
  }
  if (value.length <= 5) {
    return `${value.slice(0, 1)}***${value.slice(-1)}`;
  }
  return `${value.slice(0, 2)}***${value.slice(-2)}`;
}

function maskContactValue(channel: ContactDetailSummary["channel"], value: string): string {
  switch (channel) {
    case "phone":
      return maskPhoneValue(value);
    case "email":
      return maskEmailValue(value);
    default:
      return maskGenericValue(value);
  }
}

function normalizeContactIdentity(channel: ContactDetailSummary["channel"], value: string): string {
  switch (channel) {
    case "phone":
      return value.replace(/\D+/g, "");
    case "wechat":
    case "email":
      return value.trim().toLowerCase();
    default:
      return value.trim();
  }
}

function summarizeText(value: string | undefined, maxLength = 160): string | undefined {
  const text = value?.replace(/\s+/g, " ").trim();
  if (!text) {
    return undefined;
  }
  if (text.length <= maxLength) {
    return text;
  }
  return `${text.slice(0, maxLength).trimEnd()}…`;
}

function formatContactSourceLabel(source: string, detail?: string): string {
  const sourceLabel = summarizeSourceToken(source);
  return detail ? `${sourceLabel} · ${detail}` : sourceLabel;
}

function extractContactDetails(
  snapshot: Record<string, unknown>,
  source: string,
  recordedAt?: string,
  detail?: string,
): ContactDetailCandidate[] {
  const entries: ContactDetailCandidate[] = [];
  for (const key of orderedContactKeys) {
    const direct = pickString(snapshot[key]);
    if (!direct) {
      continue;
    }
    const channel = normalizeContactChannel(key);
    entries.push({
      channel,
      value: maskContactValue(channel, direct),
      identity: normalizeContactIdentity(channel, direct),
      source: formatContactSourceLabel(source, detail),
      recordedAt,
    });
  }
  return entries;
}

function compareContactDetails(left: ContactDetailSummary, right: ContactDetailSummary): number {
  const priority = {
    phone: 0,
    wechat: 1,
    email: 2,
    other: 3,
  } satisfies Record<ContactDetailSummary["channel"], number>;
  return priority[left.channel] - priority[right.channel] || left.source.localeCompare(right.source);
}

export function getContactDetails(
  application: ApplicationRecord,
  thread?: ApplicationThreadRecord,
): ContactDetailSummary[] {
  const details: ContactDetailCandidate[] = [
    ...extractContactDetails(asObject(application.person.contactInfo), "profile"),
  ];

  for (const artifact of thread?.resumeArtifacts ?? []) {
    details.push(
      ...extractContactDetails(
        asObject(artifact.contactSnapshot),
        "resume artifact",
        artifact.capturedAt ?? artifact.createdAt,
        artifact.fileName ?? artifact.filePath ?? summarizeSourceToken(artifact.source),
      ),
    );
  }

  const deduped = new Map<string, ContactDetailSummary>();
  for (const detail of details) {
    const key = `${detail.channel}:${detail.identity}`;
    if (!deduped.has(key)) {
      deduped.set(key, {
        channel: detail.channel,
        value: detail.value,
        source: detail.source,
        recordedAt: detail.recordedAt,
      });
    }
  }

  return [...deduped.values()].sort(compareContactDetails);
}

export function getContactChannels(
  application: ApplicationRecord,
  thread?: ApplicationThreadRecord,
): string[] {
  const channels = new Set<string>();
  for (const detail of getContactDetails(application, thread)) {
    channels.add(detail.channel);
  }
  for (const raw of thread?.stateSnapshot.contactChannels ?? []) {
    const normalized = raw.trim().toLowerCase();
    if (normalized) {
      channels.add(normalized);
    }
  }
  for (const raw of application.stateSnapshot?.contactChannels ?? []) {
    const normalized = raw.trim().toLowerCase();
    if (normalized) {
      channels.add(normalized);
    }
  }
  return [...channels];
}

export function getResumeArtifactSummaries(thread?: ApplicationThreadRecord): ResumeArtifactSummary[] {
  return (thread?.resumeArtifacts ?? [])
    .map((artifact) => ({
      id: artifact.id,
      title: artifact.fileName ?? artifact.filePath ?? summarizeSourceToken(artifact.artifactType || "resume artifact"),
      path:
        artifact.filePath ??
        pickString(asObject(artifact.artifactMetadata).path) ??
        pickString(asObject(artifact.artifactMetadata).download_path),
      source: summarizeSourceToken(artifact.source),
      recordedAt: artifact.capturedAt ?? artifact.createdAt,
      excerpt: summarizeText(artifact.extractedText ?? undefined),
      contactSummary: resolveContactSummaryFromSnapshot(asObject(artifact.contactSnapshot)),
    }))
    .sort((left, right) => (right.recordedAt ?? "").localeCompare(left.recordedAt ?? ""));
}

function resolveContactSummaryFromSnapshot(snapshot: Record<string, unknown>): string | undefined {
  const summary = extractContactDetails(snapshot, "profile")
    .slice(0, 2)
    .map((detail) => detail.value)
    .join(" / ");
  return summary || undefined;
}

export function resolveApplicationCurrentStatus(application: ApplicationRecord): string {
  return application.currentStatus.trim() || "discovered";
}

export function createNodeMap(stateMachine: RecruitmentStateMachine): Map<string, StateNode> {
  return new Map(stateMachine.nodes.map((node) => [node.id, node]));
}

export function createTransitionMap(stateMachine: RecruitmentStateMachine): Map<string, StateTransition[]> {
  const map = new Map<string, StateTransition[]>();
  for (const transition of [...stateMachine.transitions, ...stateMachine.globalTransitions]) {
    const key = transition.fromState;
    const current = map.get(key) ?? [];
    current.push(transition);
    map.set(key, current);
  }
  return map;
}

function buildMilestoneReachedAt(application: ApplicationRecord, thread?: ApplicationThreadRecord): Record<string, string> {
  const reachedAt: Record<string, string> = {};
  const transitions = [...(thread?.statusTransitions ?? [])].sort((left, right) => left.createdAt.localeCompare(right.createdAt));
  for (const transition of transitions) {
    if (transition.milestoneUpdated && !reachedAt[transition.milestoneUpdated]) {
      reachedAt[transition.milestoneUpdated] = transition.createdAt;
    }
  }
  const fallbackTimestamp =
    thread?.stateSnapshot.latestTransitionAt ?? transitions.at(-1)?.createdAt ?? application.lastContactedAt ?? undefined;
  if (application.deepestMilestone && fallbackTimestamp && !reachedAt[application.deepestMilestone]) {
    reachedAt[application.deepestMilestone] = fallbackTimestamp;
  }
  const inferredMilestones = getTriggeredMilestones(resolveApplicationCurrentStatus(application));
  for (const milestone of inferredMilestones) {
    if (fallbackTimestamp && !reachedAt[milestone.id]) {
      reachedAt[milestone.id] = fallbackTimestamp;
    }
  }
  return reachedAt;
}

function resolveLatestActivity(application: ApplicationRecord, thread?: ApplicationThreadRecord): string | undefined {
  const transitions = thread?.statusTransitions ?? [];
  const lastTransition = transitions.length ? [...transitions].sort((left, right) => right.createdAt.localeCompare(left.createdAt))[0] : undefined;
  return thread?.stateSnapshot.latestTransitionAt ?? lastTransition?.createdAt ?? application.lastContactedAt ?? undefined;
}

export function resolveContactSummary(application: ApplicationRecord, thread?: ApplicationThreadRecord): string {
  const details = getContactDetails(application, thread);
  if (details.length) {
    return details
      .slice(0, 2)
      .map((detail) => detail.value)
      .join(" / ");
  }

  const channels = getContactChannels(application, thread);
  if (channels.length) {
    return channels.slice(0, 2).join(" / ");
  }

  return "—";
}

export function buildApplicationViewModels(
  applications: ApplicationRecord[],
  threads: ApplicationThreadRecord[],
  stateMachine: RecruitmentStateMachine,
): ApplicationViewModel[] {
  const threadByApplicationId = new Map(threads.map((thread) => [thread.application.id, thread]));
  const nodeById = createNodeMap(stateMachine);

  return applications.map((application) => {
    const thread = threadByApplicationId.get(application.id);
    const currentStatus = resolveApplicationCurrentStatus(application);
    const currentNode = nodeById.get(currentStatus);
    return {
      application,
      thread,
      currentStatus,
      currentNode,
      deepestMilestone: application.deepestMilestone,
      latestActivityAt: resolveLatestActivity(application, thread),
      humanRequired: currentNode?.executionConfig?.mode === "human_required",
      onlineResumeAvailable: application.resumeAvailable || Boolean(application.summary?.trim()),
      offlineResumeAvailable: Boolean(thread?.resumeArtifacts.length),
      contactSummary: resolveContactSummary(application, thread),
      milestoneReachedAt: buildMilestoneReachedAt(application, thread),
    };
  });
}

function inferActionStyle(nodeById: Map<string, StateNode>, toStatus: string): HumanActionDefinition["style"] {
  const targetNode = nodeById.get(toStatus);
  if (!targetNode) {
    return "default";
  }
  if (targetNode.isTerminal && !targetNode.isSuccess) {
    return "danger";
  }
  if (targetNode.isSuccess || targetNode.isTransient) {
    return "primary";
  }
  return "default";
}

export function deriveHumanActionsForNode(
  node: StateNode,
  stateMachine: RecruitmentStateMachine,
): HumanActionDefinition[] {
  const configured = node.executionConfig?.humanActions;
  if (configured?.length) {
    return configured;
  }

  const nodeById = createNodeMap(stateMachine);
  const transitions = [...stateMachine.transitions, ...stateMachine.globalTransitions].filter(
    (transition) =>
      (transition.fromState === node.id || transition.fromState === "*") &&
      (transition.allowedActors == null || transition.allowedActors.includes("recruiter")),
  );

  return transitions.map((transition) => ({
    label: transition.label ?? nodeById.get(transition.toState)?.label ?? transition.toState,
    toStatus: transition.toState,
    style: inferActionStyle(nodeById, transition.toState),
    requiresNote: transition.requiresNote,
  }));
}

export function nodeTone(node?: StateNode): "positive" | "neutral" | "warning" | "critical" {
  switch (node?.uiConfig?.color) {
    case "success":
      return "positive";
    case "warning":
      return "warning";
    case "danger":
      return "critical";
    default:
      return "neutral";
  }
}

export function isWithinApplicationDateFilter(
  timestamp: string | undefined,
  filter: ApplicationDateFilter,
): boolean {
  if (filter.kind === "all") {
    return true;
  }
  if (!timestamp) {
    return false;
  }

  const value = new Date(timestamp).getTime();
  if (Number.isNaN(value)) {
    return false;
  }

  if (filter.startDate) {
    const start = new Date(`${filter.startDate}T00:00:00`).getTime();
    if (!Number.isNaN(start) && value < start) {
      return false;
    }
  }

  if (filter.endDate) {
    const end = new Date(`${filter.endDate}T23:59:59.999`).getTime();
    if (!Number.isNaN(end) && value > end) {
      return false;
    }
  }

  return true;
}
