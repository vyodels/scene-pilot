import React from "react";
import { formatChineseChatTime } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import type { ApplicationViewModel } from "./kanbanUtils";
import { CandidateAvatar } from "./ApplicationFollowUpPrimitives";

function avatarUrlFromContactInfo(contactInfo: Record<string, unknown>): string | undefined {
  const value =
    contactInfo.avatarUrl ??
    contactInfo.avatar_url ??
    contactInfo.photoUrl ??
    contactInfo.photo_url ??
    contactInfo.imageUrl ??
    contactInfo.image_url;
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

type ChatMessageSide = "candidate" | "operator" | "system";
type ChatMessageSender = ChatMessageSide;

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
  return { side: "system", sender: "system" };
}

interface ChatMessageFeedProps {
  record: ApplicationViewModel;
  operatorProfile?: {
    nickname: string;
    avatarUrl?: string | null;
  };
}

export function ChatMessageFeed({ record, operatorProfile }: ChatMessageFeedProps): JSX.Element {
  const { copy } = useI18n();
  const candidateAvatarUrl = avatarUrlFromContactInfo(record.application.person.contactInfo);
  const operatorName = operatorProfile?.nickname?.trim() || copy("Recruiter", "招聘方");
  const logs = [...(record.thread?.communicationLogs ?? [])].sort((left, right) => {
    const leftTime = left.timestamp ?? left.id;
    const rightTime = right.timestamp ?? right.id;
    return leftTime.localeCompare(rightTime);
  });

  if (!logs.length) {
    return (
      <div className="chat-feed">
        <article className="chat-feed__message" data-direction="candidate">
          <CandidateAvatar name={record.application.person.name} imageUrl={candidateAvatarUrl} />
          <div className="chat-feed__stack">
            <time className="chat-feed__time">{record.latestActivityAt ? formatChineseChatTime(record.latestActivityAt) : copy("No communication yet", "暂无沟通")}</time>
            <div className="chat-feed__bubble">
              <div className="chat-feed__content">
                {record.application.summary || record.thread?.stateSnapshot.latestNote || copy("No application summary has been recorded yet.", "当前投递记录暂未入库沟通内容。")}
              </div>
            </div>
          </div>
        </article>
      </div>
    );
  }

  return (
    <div className="chat-feed">
      {logs.map((log) => {
        const { side, sender } = messageSemantics(log.direction);
        return (
          <article key={log.id} className="chat-feed__message" data-direction={side}>
            {sender === "candidate" ? <CandidateAvatar name={record.application.person.name} imageUrl={candidateAvatarUrl} /> : null}
            <div className="chat-feed__stack">
              <time className="chat-feed__time">{formatChineseChatTime(log.timestamp) || "—"}</time>
              <div className="chat-feed__bubble">
                <div className="chat-feed__content">{log.content}</div>
              </div>
            </div>
            {sender === "operator" ? <CandidateAvatar name={operatorName} imageUrl={operatorProfile?.avatarUrl} /> : null}
          </article>
        );
      })}
    </div>
  );
}
