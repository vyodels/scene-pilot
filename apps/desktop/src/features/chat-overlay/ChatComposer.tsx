import React from "react";
import { useI18n } from "../../lib/i18n";
import type { AgentKind } from "../../lib/types";

interface ChatComposerProps {
  agentKind: AgentKind;
  inputDisabled?: boolean;
  submitDisabled?: boolean;
  modelLabel?: string | null;
  contextLabel?: string | null;
  submitLabel?: string | null;
  value: string;
  onChange(value: string): void;
  onSubmit(): void;
}

export function ChatComposer({
  agentKind,
  inputDisabled,
  submitDisabled,
  modelLabel,
  contextLabel,
  submitLabel,
  value,
  onChange,
  onSubmit,
}: ChatComposerProps): JSX.Element {
  const { copy } = useI18n();

  return (
    <div className="chat-composer">
      <div className="chat-composer__chips">
        <span className="chat-chip">{agentKind === "assistant" ? copy("Assistant", "Assistant") : copy("Autonomous", "Autonomous")}</span>
        {modelLabel ? <span className="chat-chip">{modelLabel}</span> : null}
        {contextLabel ? <span className="chat-chip">{contextLabel}</span> : null}
      </div>

      <div className="chat-composer__box">
        <button type="button" className="chat-composer__icon-button" disabled aria-label={copy("Attachment coming soon", "附件能力后续补齐")}>
          +
        </button>
        <textarea
          className="chat-composer__input"
          placeholder={
            agentKind === "assistant"
              ? copy("Ask Assistant to inspect or summarize the workspace…", "让 Assistant 帮你分析或总结当前工作区…")
              : copy("Describe the next autonomous session…", "输入本轮 Autonomous 会话要处理的任务…")
          }
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
              event.preventDefault();
              onSubmit();
            }
          }}
          disabled={inputDisabled}
        />
        <button
          type="button"
          className="chat-composer__submit"
          onClick={onSubmit}
          disabled={submitDisabled || !value.trim()}
        >
          {submitLabel || copy("Send", "发送")}
        </button>
      </div>

      <div className="chat-composer__hint">{copy("Cmd/Ctrl + Enter to send · Enter keeps newline", "Cmd/Ctrl + Enter 发送 · Enter 保留换行")}</div>
    </div>
  );
}
