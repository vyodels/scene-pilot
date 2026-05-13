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
    key: "online_resume_fetching",
    label: "在线简历获取中",
    sortOrder: 20,
    triggerStatuses: ["online_resume_fetching"],
    phase: "B",
    showInFunnel: true,
  },
  {
    id: "M03",
    key: "online_resume_acquired",
    label: "在线简历获取成功",
    sortOrder: 30,
    triggerStatuses: ["online_resume_acquired"],
    phase: "B",
    showInFunnel: true,
  },
  {
    id: "M04",
    key: "online_resume_passed",
    label: "在线简历评估通过",
    sortOrder: 40,
    triggerStatuses: ["online_resume_passed"],
    phase: "B",
    showInFunnel: true,
  },
  {
    id: "M05",
    key: "online_resume_rejected",
    label: "在线简历评估淘汰",
    sortOrder: 50,
    triggerStatuses: ["online_resume_rejected"],
    phase: "B",
    showInFunnel: false,
  },
  {
    id: "M06",
    key: "offline_resume_fetching",
    label: "离线简历获取中",
    sortOrder: 60,
    triggerStatuses: ["offline_resume_fetching"],
    phase: "D",
    showInFunnel: true,
  },
  {
    id: "M07",
    key: "offline_resume_acquired",
    label: "离线简历获取成功",
    sortOrder: 70,
    triggerStatuses: ["offline_resume_acquired"],
    phase: "D",
    showInFunnel: true,
  },
  {
    id: "M08",
    key: "offline_resume_passed",
    label: "离线简历评估通过",
    sortOrder: 80,
    triggerStatuses: ["offline_resume_passed"],
    phase: "D",
    showInFunnel: true,
  },
  {
    id: "M09",
    key: "offline_resume_rejected",
    label: "离线简历评估淘汰",
    sortOrder: 90,
    triggerStatuses: ["offline_resume_rejected"],
    phase: "D",
    showInFunnel: false,
  },
  {
    id: "M10",
    key: "human_screening",
    label: "人工筛选中",
    sortOrder: 100,
    triggerStatuses: ["human_screening"],
    phase: "E",
    showInFunnel: true,
  },
  {
    id: "M11",
    key: "human_screening_passed",
    label: "人工筛选通过",
    sortOrder: 110,
    triggerStatuses: ["human_screening_passed"],
    phase: "E",
    showInFunnel: true,
  },
  {
    id: "M12",
    key: "human_screening_rejected",
    label: "人工筛选未通过",
    sortOrder: 120,
    triggerStatuses: ["human_screening_rejected"],
    phase: "E",
    showInFunnel: false,
  },
  {
    id: "M13",
    key: "profile_ready",
    label: "候选人资料准备完毕",
    sortOrder: 130,
    triggerStatuses: ["profile_ready"],
    phase: "F",
    showInFunnel: true,
  },
  {
    id: "M14",
    key: "interview_pending",
    label: "待预约面试",
    sortOrder: 140,
    triggerStatuses: ["interview_pending"],
    phase: "G",
    showInFunnel: true,
  },
  {
    id: "M15",
    key: "interview_scheduled",
    label: "面试已预约",
    sortOrder: 150,
    triggerStatuses: ["interview_scheduled"],
    phase: "G",
    showInFunnel: true,
  },
  {
    id: "M16",
    key: "interview_passed",
    label: "面试通过",
    sortOrder: 160,
    triggerStatuses: ["interview_passed"],
    phase: "G",
    showInFunnel: true,
  },
  {
    id: "M17",
    key: "interview_rejected",
    label: "面试未通过",
    sortOrder: 170,
    triggerStatuses: ["interview_rejected"],
    phase: "G",
    showInFunnel: false,
  },
  {
    id: "M18",
    key: "offer_sent",
    label: "Offer已发出",
    sortOrder: 180,
    triggerStatuses: ["offer_sent"],
    phase: "H",
    showInFunnel: true,
  },
  {
    id: "M19",
    key: "offer_accepted",
    label: "Offer已接受",
    sortOrder: 190,
    triggerStatuses: ["offer_accepted"],
    phase: "H",
    showInFunnel: true,
  },
  {
    id: "M20",
    key: "offer_rejected",
    label: "Offer被拒",
    sortOrder: 200,
    triggerStatuses: ["offer_rejected"],
    phase: "H",
    showInFunnel: false,
  },
  {
    id: "M21",
    key: "exception_closed",
    label: "异常关闭",
    sortOrder: 210,
    triggerStatuses: ["exception_closed"],
    phase: "I",
    showInFunnel: false,
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
