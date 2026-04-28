import React, { useEffect, useState } from "react";
import { apiClient } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import type { ApplicationViewModel } from "./kanbanUtils";

interface ChatInputAreaProps {
  record: ApplicationViewModel;
  sending?: boolean;
  onSubmit(payload: { content: string; messageType?: string }): Promise<unknown> | void;
}

export function ChatInputArea({ record, sending, onSubmit }: ChatInputAreaProps): JSX.Element {
  const { copy } = useI18n();
  const [draft, setDraft] = useState("");
  const [renderingTemplate, setRenderingTemplate] = useState(false);

  useEffect(() => {
    setDraft("");
  }, [record.application.id]);

  const handleSubmit = async () => {
    const content = draft.trim();
    if (!content) {
      return;
    }
    await onSubmit({ content, messageType: "text" });
    setDraft("");
  };

  const applyTemplate = async (templateId: string) => {
    setRenderingTemplate(true);
    try {
      const rendered = await apiClient.renderCommunicationTemplate(templateId, {
        applicationId: record.application.id,
      });
      if (rendered.content.trim()) {
        setDraft(rendered.content);
      }
    } finally {
      setRenderingTemplate(false);
    }
  };

  const hasMessages = Boolean(record.thread?.communicationLogs.length);

  return (
    <div className="chat-input-area">
      <div className="chat-input-area__toolbar">
        <button type="button" className="chat-input-area__tool" disabled={renderingTemplate} onClick={() => void applyTemplate("application_greeting")}>
          {copy("Template", "模板")}
        </button>
        <button type="button" className="chat-input-area__tool" disabled={renderingTemplate} onClick={() => void applyTemplate("resume_request")}>
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
