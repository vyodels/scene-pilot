import { getTriggeredMilestones } from "@scene-pilot/shared";
import type { HumanActionDefinition, RecruitmentStateMachine, StateNode, StateTransition } from "@scene-pilot/shared";
import type { CandidateRecord, CandidateThreadRecord } from "../../lib/types";

export interface CandidateViewModel {
  candidate: CandidateRecord;
  thread?: CandidateThreadRecord;
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

export function resolveCandidateCurrentStatus(candidate: CandidateRecord): string {
  return candidate.currentStatus?.trim() || candidate.status?.trim() || "discovered";
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

function buildMilestoneReachedAt(candidate: CandidateRecord, thread?: CandidateThreadRecord): Record<string, string> {
  const reachedAt: Record<string, string> = {};
  const transitions = [...(thread?.statusTransitions ?? [])].sort((left, right) => left.createdAt.localeCompare(right.createdAt));
  for (const transition of transitions) {
    if (transition.milestoneUpdated && !reachedAt[transition.milestoneUpdated]) {
      reachedAt[transition.milestoneUpdated] = transition.createdAt;
    }
  }
  const fallbackTimestamp =
    thread?.stateSnapshot.latestTransitionAt ?? transitions.at(-1)?.createdAt ?? candidate.lastContactedAt ?? undefined;
  if (candidate.deepestMilestone && fallbackTimestamp && !reachedAt[candidate.deepestMilestone]) {
    reachedAt[candidate.deepestMilestone] = fallbackTimestamp;
  }
  const inferredMilestones = getTriggeredMilestones(resolveCandidateCurrentStatus(candidate));
  for (const milestone of inferredMilestones) {
    if (fallbackTimestamp && !reachedAt[milestone.id]) {
      reachedAt[milestone.id] = fallbackTimestamp;
    }
  }
  return reachedAt;
}

function resolveLatestActivity(candidate: CandidateRecord, thread?: CandidateThreadRecord): string | undefined {
  const transitions = thread?.statusTransitions ?? [];
  const lastTransition = transitions.length ? [...transitions].sort((left, right) => right.createdAt.localeCompare(left.createdAt))[0] : undefined;
  return thread?.stateSnapshot.latestTransitionAt ?? lastTransition?.createdAt ?? candidate.lastContactedAt ?? undefined;
}

function resolveContactSummary(candidate: CandidateRecord, thread?: CandidateThreadRecord): string {
  const contactInfo = asObject(candidate.contactInfo);
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

export function buildCandidateViewModels(
  candidates: CandidateRecord[],
  threads: CandidateThreadRecord[],
  stateMachine: RecruitmentStateMachine,
): CandidateViewModel[] {
  const threadByCandidateId = new Map(threads.map((thread) => [thread.candidate.id, thread]));
  const nodeById = createNodeMap(stateMachine);

  return candidates.map((candidate) => {
    const thread = threadByCandidateId.get(candidate.id);
    const currentStatus = resolveCandidateCurrentStatus(candidate);
    const currentNode = nodeById.get(currentStatus);
    return {
      candidate,
      thread,
      currentStatus,
      currentNode,
      deepestMilestone: candidate.deepestMilestone,
      latestActivityAt: resolveLatestActivity(candidate, thread),
      humanRequired: currentNode?.executionConfig?.mode === "human_required",
      onlineResumeAvailable: candidate.resumeAvailable || Boolean(candidate.summary?.trim()),
      offlineResumeAvailable: Boolean(thread?.resumeArtifacts.length),
      contactSummary: resolveContactSummary(candidate, thread),
      milestoneReachedAt: buildMilestoneReachedAt(candidate, thread),
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
