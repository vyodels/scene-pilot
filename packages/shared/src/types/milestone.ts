import type { ApplicationStatusTransition } from "./stateMachine";

export interface FunnelMilestone {
  id: string;
  key: string;
  label: string;
  sortOrder: number;
  triggerStatuses: string[];
  phase: string;
  showInFunnel: boolean;
}

export interface DeepestMilestoneAdvanceResult {
  deepestMilestone?: string;
  gainedMilestones: string[];
}

export const funnelMilestones: FunnelMilestone[] = [
  {
    id: "M01",
    key: "discovered",
    label: "已发现",
    sortOrder: 10,
    triggerStatuses: ["discovered"],
    phase: "A",
    showInFunnel: true,
  },
  {
    id: "M02",
    key: "ai_evaluated",
    label: "AI 在线评估完成",
    sortOrder: 20,
    triggerStatuses: ["ai_online_passed", "ai_online_rejected"],
    phase: "A",
    showInFunnel: false,
  },
  {
    id: "M03",
    key: "ai_screen_passed",
    label: "AI 在线评估通过",
    sortOrder: 30,
    triggerStatuses: ["ai_online_passed"],
    phase: "A",
    showInFunnel: true,
  },
  {
    id: "M04",
    key: "outreach_started",
    label: "已发起沟通",
    sortOrder: 40,
    triggerStatuses: ["outreach_sent"],
    phase: "B",
    showInFunnel: false,
  },
  {
    id: "M05",
    key: "conversation_built",
    label: "已建立对话",
    sortOrder: 50,
    triggerStatuses: ["in_conversation"],
    phase: "B",
    showInFunnel: true,
  },
  {
    id: "M06",
    key: "resume_obtained",
    label: "已获取线下简历",
    sortOrder: 60,
    triggerStatuses: ["resume_received"],
    phase: "C",
    showInFunnel: true,
  },
  {
    id: "M07",
    key: "offline_scored",
    label: "AI 线下评分完成",
    sortOrder: 70,
    triggerStatuses: ["offline_score_passed", "offline_score_rejected"],
    phase: "D",
    showInFunnel: false,
  },
  {
    id: "M08",
    key: "offline_passed",
    label: "AI 线下评分通过",
    sortOrder: 80,
    triggerStatuses: ["offline_score_passed"],
    phase: "D",
    showInFunnel: true,
  },
  {
    id: "M09",
    key: "human_screened",
    label: "人工初筛完成",
    sortOrder: 90,
    triggerStatuses: ["human_review_passed", "human_review_rejected"],
    phase: "E",
    showInFunnel: false,
  },
  {
    id: "M10",
    key: "human_passed",
    label: "人工初筛通过",
    sortOrder: 100,
    triggerStatuses: ["human_review_passed"],
    phase: "E",
    showInFunnel: true,
  },
  {
    id: "M11",
    key: "contact_obtained",
    label: "已获取联系方式",
    sortOrder: 110,
    triggerStatuses: ["contact_acquired"],
    phase: "F",
    showInFunnel: true,
  },
  {
    id: "M12",
    key: "interview_booked",
    label: "面试已预约",
    sortOrder: 120,
    triggerStatuses: ["interview_scheduled"],
    phase: "G",
    showInFunnel: true,
  },
  {
    id: "M13",
    key: "interview_passed",
    label: "面试通过",
    sortOrder: 130,
    triggerStatuses: ["interview_passed"],
    phase: "G",
    showInFunnel: true,
  },
  {
    id: "M14",
    key: "offer_accepted",
    label: "Offer 已接受",
    sortOrder: 140,
    triggerStatuses: ["offer_accepted"],
    phase: "H",
    showInFunnel: true,
  },
];

export const funnelMilestoneIds = funnelMilestones.map((milestone) => milestone.id);

const milestoneById = new Map(funnelMilestones.map((milestone) => [milestone.id, milestone]));
const milestoneIdsByStatus = new Map<string, string[]>();

for (const milestone of funnelMilestones) {
  for (const status of milestone.triggerStatuses) {
    const current = milestoneIdsByStatus.get(status) ?? [];
    current.push(milestone.id);
    milestoneIdsByStatus.set(status, current);
  }
}

export function getFunnelMilestone(milestoneId: string | null | undefined): FunnelMilestone | undefined {
  if (!milestoneId) {
    return undefined;
  }
  return milestoneById.get(milestoneId);
}

export function getTriggeredMilestoneIds(status: string | null | undefined): string[] {
  if (!status) {
    return [];
  }
  return milestoneIdsByStatus.get(status) ?? [];
}

export function getTriggeredMilestones(status: string | null | undefined): FunnelMilestone[] {
  return getTriggeredMilestoneIds(status)
    .map((milestoneId) => milestoneById.get(milestoneId))
    .filter((milestone): milestone is FunnelMilestone => Boolean(milestone));
}

export function listMilestonesInRange(
  fromMilestoneId: string | null | undefined,
  toMilestoneId: string | null | undefined,
): string[] {
  const target = getFunnelMilestone(toMilestoneId);
  if (!target) {
    return [];
  }
  const currentOrder = getFunnelMilestone(fromMilestoneId)?.sortOrder ?? 0;
  if (target.sortOrder <= currentOrder) {
    return [];
  }
  return funnelMilestones
    .filter((milestone) => milestone.sortOrder > currentOrder && milestone.sortOrder <= target.sortOrder)
    .map((milestone) => milestone.id);
}

export function advanceDeepestMilestone(
  currentMilestoneId: string | null | undefined,
  targetMilestoneIds: string[],
): DeepestMilestoneAdvanceResult {
  const currentOrder = getFunnelMilestone(currentMilestoneId)?.sortOrder ?? 0;
  const candidates = targetMilestoneIds
    .map((milestoneId) => getFunnelMilestone(milestoneId))
    .filter((milestone): milestone is FunnelMilestone => Boolean(milestone))
    .sort((left, right) => left.sortOrder - right.sortOrder);

  if (!candidates.length) {
    return { deepestMilestone: currentMilestoneId ?? undefined, gainedMilestones: [] };
  }

  const deepestTarget = candidates[candidates.length - 1];
  if (deepestTarget.sortOrder <= currentOrder) {
    return { deepestMilestone: currentMilestoneId ?? undefined, gainedMilestones: [] };
  }

  return {
    deepestMilestone: deepestTarget.id,
    gainedMilestones: listMilestonesInRange(currentMilestoneId, deepestTarget.id),
  };
}

export function advanceDeepestMilestoneByStatus(
  currentMilestoneId: string | null | undefined,
  status: string | null | undefined,
): DeepestMilestoneAdvanceResult {
  return advanceDeepestMilestone(currentMilestoneId, getTriggeredMilestoneIds(status));
}

export function extractMilestonesFromTransitions(transitions: Array<Pick<ApplicationStatusTransition, "toStatus">>): string[] {
  const reached = new Set<string>();
  let current: string | undefined;
  for (const transition of transitions) {
    const { deepestMilestone, gainedMilestones } = advanceDeepestMilestoneByStatus(current, transition.toStatus);
    for (const milestoneId of gainedMilestones) {
      reached.add(milestoneId);
    }
    current = deepestMilestone;
  }
  return funnelMilestones.filter((milestone) => reached.has(milestone.id)).map((milestone) => milestone.id);
}
