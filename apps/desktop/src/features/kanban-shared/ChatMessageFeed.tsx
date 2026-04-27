import React, { Fragment } from "react";
import { formatCompactDate } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import type { ApplicationViewModel } from "./kanbanUtils";
import { CandidateAvatar } from "./ApplicationFollowUpPrimitives";

function dayKey(timestamp?: string | null): string {
  if (!timestamp) {
    return "unknown";
  }
  return timestamp.slice(0, 10);
}

type ChatMessageSide = "candidate" | "operator";
type ChatMessageSender = ChatMessageSide | "system";

interface ChatMessageSemantics {
  side: ChatMessageSide;
  sender: ChatMessageSender;
}

function messageSemantics(direction: string): ChatMessageSemantics {
  const normalizedDirection = direction.toLowerCase();
  if (normalizedDirection === "inbound" || normalizedDirection === "applicant" || normalizedDirection === "candidate") {
    return { side: "candidate", sender: "candidate" };
  }
  if (normalizedDirection === "outbound" || normalizedDirection === "recruiter" || normalizedDirection === "agent" || normalizedDirection === "operator") {
    return { side: "operator", sender: "operator" };
  }
  return { side: "operator", sender: "system" };
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
    return (
      <div className="chat-feed">
        <div className="chat-feed__day-chip">{copy("Application context", "投递记录上下文")}</div>
        <article className="chat-feed__message" data-direction="candidate">
          <CandidateAvatar name={record.application.person.name} />
          <div className="chat-feed__bubble">
            <div className="chat-feed__bubble-head">
              <strong>{record.application.person.name}</strong>
              <span>{record.latestActivityAt ? formatCompactDate(record.latestActivityAt) : copy("No communication yet", "暂无沟通")}</span>
            </div>
            <div className="chat-feed__content">
              {record.application.summary || record.thread?.stateSnapshot.latestNote || copy("No application summary has been recorded yet.", "当前投递记录暂未入库沟通内容。")}
            </div>
            <div className="chat-feed__bubble-meta">
              <span>{record.application.person.title || copy("Applicant", "投递人")}</span>
              <span>{record.currentStatusLabel}</span>
            </div>
          </div>
        </article>
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
        const { side, sender } = messageSemantics(log.direction);
        return (
          <Fragment key={log.id}>
            {showDayChip ? (
              <div className="chat-feed__day-chip">{log.timestamp ? formatCompactDate(log.timestamp).split(",")[0] : copy("Unknown day", "未知日期")}</div>
            ) : null}
            <article className="chat-feed__message" data-direction={side}>
              {sender === "candidate" ? <CandidateAvatar name={record.application.person.name} /> : null}
              <div className="chat-feed__bubble">
                <div className="chat-feed__bubble-head">
                  <strong>
                    {sender === "operator" ? copy("Recruiter", "招聘方") : sender === "system" ? copy("System", "系统") : record.application.person.name}
                  </strong>
                  <span>{log.timestamp ? formatCompactDate(log.timestamp) : copy("Just now", "刚刚")}</span>
                </div>
                <div className="chat-feed__content">{log.content}</div>
                <div className="chat-feed__bubble-meta">
                  {sender === "operator" ? <span>{copy("Sent", "已发送")}</span> : null}
                  {sender === "candidate" ? <span>{copy("Received", "已接收")}</span> : null}
                  {sender === "system" ? <span>{copy("System", "系统")}</span> : null}
                </div>
              </div>
              {sender === "operator" ? <CandidateAvatar name={copy("Recruiter", "招聘方")} /> : null}
            </article>
          </Fragment>
        );
      })}
    </div>
  );
}
