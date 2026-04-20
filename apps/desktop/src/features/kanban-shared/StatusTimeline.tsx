import React from "react";
import { getFunnelMilestone } from "@scene-pilot/shared";
import type { ApplicationStatusTransition, RecruitmentStateMachine } from "@scene-pilot/shared";
import { StatusBadge } from "../../components";
import { formatCompactDate } from "../../lib/format";
import { useI18n } from "../../lib/i18n";

interface StatusTimelineProps {
  transitions: ApplicationStatusTransition[];
  stateMachine?: RecruitmentStateMachine;
  compact?: boolean;
  maxItems?: number;
  onShowMore?(): void;
}

function actorTone(transition: ApplicationStatusTransition): "positive" | "neutral" | "warning" | "critical" {
  if (transition.isOverride) {
    return "warning";
  }
  if (transition.milestoneUpdated) {
    return "positive";
  }
  if (transition.actor.includes("agent")) {
    return "neutral";
  }
  return "neutral";
}

function actorLabel(actor: ApplicationStatusTransition["actor"], copy: (en: string, zh: string) => string): string {
  switch (actor) {
    case "agent":
      return copy("Agent", "Agent");
    case "agent_override":
      return copy("Agent override", "Agent 覆盖");
    case "recruiter":
      return copy("Recruiter", "招聘员");
    case "recruiter_override":
      return copy("Recruiter override", "招聘员覆盖");
    default:
      return copy("System", "系统");
  }
}

export function StatusTimeline({
  transitions,
  stateMachine,
  compact = false,
  maxItems,
  onShowMore,
}: StatusTimelineProps): JSX.Element {
  const { copy } = useI18n();
  const nodeLabelById = new Map((stateMachine?.nodes ?? []).map((node) => [node.id, node.label]));
  const items = [...transitions].sort((left, right) => right.createdAt.localeCompare(left.createdAt));
  const visibleItems = typeof maxItems === "number" ? items.slice(0, maxItems) : items;

  if (!visibleItems.length) {
    return <div className="status-timeline__empty">{copy("No status history yet.", "暂无状态历史。")}</div>;
  }

  return (
    <div className={`status-timeline${compact ? " status-timeline--compact" : ""}`}>
      {visibleItems.map((transition) => {
        const resolvedStatusLabel =
          transition.toStatusLabel ||
          nodeLabelById.get(transition.toStatus) ||
          copy("Status not mapped", "状态未映射");
        const resolvedMilestoneLabel =
          transition.milestoneUpdated
            ? (getFunnelMilestone(transition.milestoneUpdated)?.label ?? copy("Milestone not mapped", "里程碑未映射"))
            : null;
        return (
          <article
            key={transition.id}
            className="status-timeline__item"
            data-tone={actorTone(transition)}
          >
            <div className="status-timeline__marker">
              <span className="status-timeline__dot" />
              {transition.milestoneUpdated ? <span className="status-timeline__icon">★</span> : null}
              {transition.isOverride ? <span className="status-timeline__icon">⚡</span> : null}
            </div>
            <div className="status-timeline__body">
              <div className="status-timeline__header">
                <strong>{resolvedStatusLabel}</strong>
                <div className="status-timeline__meta">
                  <StatusBadge tone={actorTone(transition)}>{actorLabel(transition.actor, copy)}</StatusBadge>
                  <span>{formatCompactDate(transition.createdAt)}</span>
                </div>
              </div>
              <div className="status-timeline__detail">
                {transition.trigger ? (
                  <span>
                    {copy("Trigger", "触发")}：{transition.trigger}
                  </span>
                ) : null}
                {transition.overrideReason ? (
                  <span>
                    {copy("Override reason", "覆盖理由")}：{transition.overrideReason}
                  </span>
                ) : null}
                {transition.note ? (
                  <span>
                    {copy("Note", "备注")}：{transition.note}
                  </span>
                ) : null}
                {transition.milestoneUpdated ? (
                  <span>
                    {copy("Milestone", "里程碑")}：{resolvedMilestoneLabel}
                  </span>
                ) : null}
              </div>
            </div>
          </article>
        );
      })}
      {maxItems != null && items.length > maxItems && onShowMore ? (
        <button type="button" className="status-timeline__more" onClick={onShowMore}>
          {copy("View full history", "查看完整历史")}
        </button>
      ) : null}
    </div>
  );
}
