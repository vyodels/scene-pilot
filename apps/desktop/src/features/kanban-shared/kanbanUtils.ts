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

function resolveContactSummary(application: ApplicationRecord, thread?: ApplicationThreadRecord): string {
  const contactInfo = asObject(application.person.contactInfo);
  const orderedKeys = [
    "phone",
    "mobile",
    "telephone",
    "wechat",
    "weixin",
    "wx",
    "email",
    "contact",
    "contact_value",
  ];

  for (const key of orderedKeys) {
    const direct = pickString(contactInfo[key]);
    if (direct) {
      return direct;
    }
  }

  for (const artifact of thread?.resumeArtifacts ?? []) {
    const snapshot = asObject(artifact.contactSnapshot);
    for (const key of orderedKeys) {
      const direct = pickString(snapshot[key]);
      if (direct) {
        return direct;
      }
    }
  }

  const channels = thread?.stateSnapshot.contactChannels.filter(Boolean) ?? [];
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
