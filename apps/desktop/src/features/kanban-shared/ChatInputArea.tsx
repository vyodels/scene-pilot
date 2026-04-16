import React, { useEffect, useState } from "react";
import { useI18n } from "../../lib/i18n";
import type { CandidateViewModel } from "./kanbanUtils";

interface ChatInputAreaProps {
  record: CandidateViewModel;
  sending?: boolean;
  onSubmit(payload: { content: string; messageType?: string }): Promise<unknown> | void;
}

function createGreeting(record: CandidateViewModel): string {
  return `您好，看到您在 ${record.candidate.title} 方向的背景和我们 ${record.candidate.jdTitle} 岗位很匹配，方便了解一下您最近的机会考虑吗？`;
}

function createSuggestedReply(record: CandidateViewModel): string {
  const strengths = record.candidate.tags.slice(0, 2).join("、");
  return `结合您在 ${strengths || record.candidate.title} 方面的经验，我想进一步了解您最近做过的项目，以及是否方便补充一份最新简历。`;
}

export function ChatInputArea({ record, sending, onSubmit }: ChatInputAreaProps): JSX.Element {
  const { copy } = useI18n();
  const [draft, setDraft] = useState("");

  useEffect(() => {
    setDraft("");
  }, [record.candidate.id]);

  const handleSubmit = async () => {
    const content = draft.trim();
    if (!content) {
      return;
    }
    await onSubmit({ content, messageType: "text" });
    setDraft("");
  };

  const hasMessages = Boolean(record.thread?.communicationLogs.length);

  return (
    <div className="chat-input-area">
      <div className="chat-input-area__toolbar">
        <button type="button" className="chat-input-area__tool" onClick={() => setDraft(createGreeting(record))}>
          {copy("Template", "模板")}
        </button>
        <button type="button" className="chat-input-area__tool" onClick={() => setDraft(createSuggestedReply(record))}>
          {copy("Suggested phrasing", "建议话术")}
        </button>
      </div>
      <textarea
        className="chat-input-area__input"
        rows={6}
        value={draft}
        placeholder={
          hasMessages
            ? copy("Write a message. Agent will send it through the recruitment platform.", "输入消息，Agent 会代你在招聘平台发出。")
            : copy("Write the first message to start the conversation.", "输入第一条打招呼消息，开始沟通。")
        }
        onChange={(event) => setDraft(event.target.value)}
      />
      <div className="chat-input-area__footer">
        <span className="chat-input-area__hint">
          {hasMessages
            ? copy("Messages are sent through the platform and cannot be recalled.", "消息将通过平台发出，发送后不可撤回。")
            : copy("Agent will send the opening message on your behalf.", "Agent 将以你的身份在平台发出第一条消息。")}
        </span>
        <button type="button" className="chat-input-area__send" onClick={() => void handleSubmit()} disabled={sending || !draft.trim()}>
          {hasMessages ? copy("Send", "发送") : copy("Send and start", "发送并开始沟通")}
        </button>
      </div>
    </div>
  );
}
