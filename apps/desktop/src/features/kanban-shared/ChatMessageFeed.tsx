import React, { Fragment } from "react";
import { StatusBadge } from "../../components";
import { formatCompactDate } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import type { ApplicationViewModel } from "./kanbanUtils";

function dayKey(timestamp?: string | null): string {
  if (!timestamp) {
    return "unknown";
  }
  return timestamp.slice(0, 10);
}

function messageDirection(direction: string): "inbound" | "outbound" | "system" {
  if (direction === "inbound" || direction === "outbound") {
    return direction;
  }
  return "system";
}

interface ChatMessageFeedProps {
  record: ApplicationViewModel;
}

export function ChatMessageFeed({ record }: ChatMessageFeedProps): JSX.Element {
  const { copy } = useI18n();
  const logs = [...(record.thread?.communicationLogs ?? [])].sort((left, right) => {
    const leftTime = left.timestamp ?? left.id;
    const rightTime = right.timestamp ?? right.id;
    return leftTime.localeCompare(rightTime);
  });

  if (!logs.length) {
    const overallScore =
      typeof record.application.aiScores?.overall === "number"
        ? Number(record.application.aiScores.overall)
        : typeof record.application.matchScore === "number"
          ? record.application.matchScore
          : null;

    return (
      <div className="chat-feed__empty-card">
        <div className="chat-feed__empty-head">
          <strong>
            {record.application.person.name} · {record.application.person.title}
          </strong>
          <span>{record.application.person.location}</span>
        </div>
        <p className="chat-feed__empty-summary">{record.application.summary || copy("No online resume summary yet.", "暂无在线简历摘要。")}</p>
        <div className="chat-feed__empty-metrics">
          <StatusBadge tone="positive">
            {copy("Online score", "在线评分")} {overallScore != null ? `${Math.round(overallScore)}/100` : copy("Pending", "待生成")}
          </StatusBadge>
          <StatusBadge tone={record.currentNode?.executionConfig?.mode === "human_required" ? "warning" : "neutral"}>
            {record.currentNode?.label ?? record.currentStatus}
          </StatusBadge>
        </div>
        <div className="chat-feed__empty-facts">
          <span>{copy("Role", "应聘岗位")}：{record.application.jobDescription.title}</span>
          <span>{copy("Experience", "工作年限")}：{record.application.person.experienceYears || "—"}</span>
          <span>{copy("Location", "所在地")}：{record.application.person.location || "—"}</span>
        </div>
      </div>
    );
  }

  let previousDay = "";

  return (
    <div className="chat-feed">
      {logs.map((log) => {
        const currentDay = dayKey(log.timestamp);
        const showDayChip = currentDay !== previousDay;
        previousDay = currentDay;
        const direction = messageDirection(log.direction);
        return (
          <Fragment key={log.id}>
            {showDayChip ? (
              <div className="chat-feed__day-chip">{log.timestamp ? formatCompactDate(log.timestamp).split(",")[0] : copy("Unknown day", "未知日期")}</div>
            ) : null}
            <article className="chat-feed__message" data-direction={direction}>
              <div className="chat-feed__bubble">
                <div className="chat-feed__content">{log.content}</div>
                <div className="chat-feed__bubble-meta">
                  <span>{log.timestamp ? formatCompactDate(log.timestamp) : copy("Just now", "刚刚")}</span>
                  {direction === "outbound" ? <span>{copy("Agent sent", "Agent 发送")}</span> : null}
                  {direction === "system" ? <span>{copy("System", "系统")}</span> : null}
                </div>
              </div>
            </article>
          </Fragment>
        );
      })}
    </div>
  );
}
