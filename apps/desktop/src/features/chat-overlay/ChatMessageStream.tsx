import React from "react";
import { formatDateTime } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import type { AgentConversationMessage } from "../../lib/types";

interface ChatMessageStreamProps {
  loading?: boolean;
  messages: AgentConversationMessage[];
}

type Block =
  | { type: "paragraph"; lines: string[] }
  | { type: "list"; ordered: boolean; items: string[] }
  | { type: "table"; header: string[]; rows: string[][] }
  | { type: "callout"; tone: "info" | "warning" | "success" | "critical"; title: string; lines: string[] }
  | { type: "code"; language: string | null; value: string }
  | { type: "diagram"; label: string; language: string; value: string };

interface Segment {
  type: "text" | "code";
  value: string;
  language: string | null;
}

function splitSegments(content: string): Segment[] {
  const segments: Segment[] = [];
  const pattern = /```([a-zA-Z0-9_-]+)?\n?([\s\S]*?)```/g;
  let cursor = 0;

  for (const match of content.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > cursor) {
      segments.push({
        type: "text",
        value: content.slice(cursor, index),
        language: null,
      });
    }
    segments.push({
      type: "code",
      language: match[1] ? match[1].trim().toLowerCase() : null,
      value: match[2].trim(),
    });
    cursor = index + match[0].length;
  }

  if (cursor < content.length) {
    segments.push({
      type: "text",
      value: content.slice(cursor),
      language: null,
    });
  }

  return segments.filter((segment) => segment.value.trim().length > 0);
}

function isMarkdownTable(lines: string[]): boolean {
  if (lines.length < 2) {
    return false;
  }
  const separator = lines[1].replace(/\|/g, "").trim();
  return lines[0].includes("|") && /^:?-{3,}:?(?:\s+:?-{3,}:?)*$/.test(separator.replace(/\s+/g, " "));
}

function parseTableRow(line: string): string[] {
  return line
    .split("|")
    .map((part) => part.trim())
    .filter((part, index, array) => !(index === 0 && part === "") && !(index === array.length - 1 && part === ""));
}

function parseCallout(lines: string[]): Block | null {
  if (!lines.length) {
    return null;
  }

  const match = lines[0].match(/^(IMPORTANT|WARNING|NOTE|TIP|SUCCESS|INFO|关键|重要|警告|提示|注意|结论)\s*[:：]\s*(.*)$/i);
  if (!match) {
    return null;
  }

  const keyword = match[1].toLowerCase();
  const title = match[1];
  const firstLine = match[2]?.trim();
  const tone =
    keyword === "warning" || keyword === "警告" || keyword === "注意"
      ? "warning"
      : keyword === "success"
        ? "success"
        : keyword === "important" || keyword === "关键" || keyword === "重要"
          ? "critical"
          : "info";

  return {
    type: "callout",
    tone,
    title,
    lines: [firstLine, ...lines.slice(1)].filter((line) => line.length > 0),
  };
}

function diagramLabelFor(language: string | null, value: string): string | null {
  const normalized = (language ?? "").toLowerCase();
  const firstLine = value.split("\n")[0]?.trim().toLowerCase() ?? "";

  if (normalized === "mermaid") {
    if (firstLine.startsWith("sequencediagram")) {
      return "时序图";
    }
    if (firstLine.startsWith("graph") || firstLine.startsWith("flowchart")) {
      return "流程图";
    }
    if (firstLine.startsWith("statediagram")) {
      return "状态图";
    }
    if (firstLine.startsWith("gantt")) {
      return "甘特图";
    }
    if (firstLine.startsWith("classdiagram")) {
      return "类图";
    }
    return "图示";
  }

  if (normalized === "flowchart") {
    return "流程图";
  }
  if (normalized === "sequence" || normalized === "sequence-diagram") {
    return "时序图";
  }
  if (normalized === "architecture" || normalized === "arch") {
    return "架构图";
  }
  if (normalized === "diagram" || normalized === "plantuml") {
    return "图示";
  }

  return null;
}

function textToBlocks(content: string): Block[] {
  const blocks: Block[] = [];
  const paragraphs = content
    .split(/\n{2,}/g)
    .map((part) => part.trim())
    .filter(Boolean);

  paragraphs.forEach((paragraph) => {
    const lines = paragraph.split("\n").map((line) => line.trimEnd()).filter((line) => line.trim().length > 0);
    if (!lines.length) {
      return;
    }

    const callout = parseCallout(lines);
    if (callout) {
      blocks.push(callout);
      return;
    }

    if (isMarkdownTable(lines)) {
      const [headerLine, , ...rowLines] = lines;
      blocks.push({
        type: "table",
        header: parseTableRow(headerLine),
        rows: rowLines.map(parseTableRow),
      });
      return;
    }

    if (lines.every((line) => /^\d+\.\s+/.test(line))) {
      blocks.push({
        type: "list",
        ordered: true,
        items: lines.map((line) => line.replace(/^\d+\.\s+/, "").trim()),
      });
      return;
    }

    if (lines.every((line) => /^[-*]\s+/.test(line))) {
      blocks.push({
        type: "list",
        ordered: false,
        items: lines.map((line) => line.replace(/^[-*]\s+/, "").trim()),
      });
      return;
    }

    blocks.push({
      type: "paragraph",
      lines,
    });
  });

  return blocks;
}

function contentToBlocks(content: string): Block[] {
  return splitSegments(content).flatMap((segment) => {
    if (segment.type === "text") {
      return textToBlocks(segment.value);
    }

    const label = diagramLabelFor(segment.language, segment.value);
    if (label) {
      return [
        {
          type: "diagram",
          label,
          language: segment.language ?? "diagram",
          value: segment.value,
        },
      ];
    }

    return [
      {
        type: "code",
        language: segment.language,
        value: segment.value,
      },
    ];
  });
}

function renderInline(text: string, keyPrefix: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  const pattern = /(\*\*[^*]+\*\*|==[^=]+==)/g;
  let cursor = 0;
  let index = 0;

  for (const match of text.matchAll(pattern)) {
    const start = match.index ?? 0;
    if (start > cursor) {
      nodes.push(<React.Fragment key={`${keyPrefix}-text-${index}`}>{text.slice(cursor, start)}</React.Fragment>);
      index += 1;
    }

    const token = match[0];
    if (token.startsWith("**")) {
      nodes.push(
        <strong key={`${keyPrefix}-strong-${index}`} className="chat-message__strong">
          {token.slice(2, -2)}
        </strong>,
      );
    } else {
      nodes.push(
        <mark key={`${keyPrefix}-mark-${index}`} className="chat-message__mark">
          {token.slice(2, -2)}
        </mark>,
      );
    }

    cursor = start + token.length;
    index += 1;
  }

  if (cursor < text.length) {
    nodes.push(<React.Fragment key={`${keyPrefix}-tail-${index}`}>{text.slice(cursor)}</React.Fragment>);
  }

  return nodes;
}

function renderLine(line: string, keyPrefix: string): React.ReactNode {
  return renderInline(line, keyPrefix).map((node, index) => <React.Fragment key={`${keyPrefix}-${index}`}>{node}</React.Fragment>);
}

function renderBlock(block: Block, key: string): React.ReactNode {
  switch (block.type) {
    case "paragraph":
      return (
        <p key={key} className="chat-message__paragraph">
          {block.lines.map((line, lineIndex) => (
            <React.Fragment key={`${key}-line-${lineIndex}`}>
              {renderLine(line, `${key}-line-${lineIndex}`)}
              {lineIndex < block.lines.length - 1 ? <br /> : null}
            </React.Fragment>
          ))}
        </p>
      );
    case "list":
      if (block.ordered) {
        return (
          <ol key={key} className="chat-message__list chat-message__list--ordered">
            {block.items.map((item, index) => (
              <li key={`${key}-item-${index}`}>{renderLine(item, `${key}-item-${index}`)}</li>
            ))}
          </ol>
        );
      }
      return (
        <ul key={key} className="chat-message__list">
          {block.items.map((item, index) => (
            <li key={`${key}-item-${index}`}>{renderLine(item, `${key}-item-${index}`)}</li>
          ))}
        </ul>
      );
    case "table":
      return (
        <div key={key} className="chat-message__table-shell">
          <table className="chat-message__table">
            <thead>
              <tr>
                {block.header.map((cell, index) => (
                  <th key={`${key}-head-${index}`}>{renderLine(cell, `${key}-head-${index}`)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, rowIndex) => (
                <tr key={`${key}-row-${rowIndex}`}>
                  {row.map((cell, cellIndex) => (
                    <td key={`${key}-row-${rowIndex}-cell-${cellIndex}`}>{renderLine(cell, `${key}-row-${rowIndex}-cell-${cellIndex}`)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    case "callout":
      return (
        <section key={key} className="chat-message__callout" data-tone={block.tone}>
          <div className="chat-message__callout-title">{block.title}</div>
          <div className="chat-message__callout-body">
            {block.lines.map((line, index) => (
              <p key={`${key}-callout-${index}`} className="chat-message__paragraph">
                {renderLine(line, `${key}-callout-${index}`)}
              </p>
            ))}
          </div>
        </section>
      );
    case "diagram":
      return (
        <section key={key} className="chat-message__diagram-shell">
          <div className="chat-message__diagram-head">
            <span className="chat-message__diagram-label">{block.label}</span>
            <span className="chat-message__diagram-language">{block.language}</span>
          </div>
          <pre className="chat-message__diagram-code">
            <code>{block.value}</code>
          </pre>
        </section>
      );
    case "code":
      return (
        <section key={key} className="chat-message__code-shell">
          {block.language ? <div className="chat-message__code-head">{block.language}</div> : null}
          <pre className="chat-message__code">
            <code>{block.value}</code>
          </pre>
        </section>
      );
    default:
      return null;
  }
}

function roleLabel(message: AgentConversationMessage, copy: ReturnType<typeof useI18n>["copy"]): string {
  if (message.kind === "tool_use") {
    return copy("Tool call", "工具调用");
  }
  if (message.kind === "tool_result") {
    return copy("Tool result", "工具结果");
  }
  if (message.role === "assistant") {
    return copy("Assistant", "Assistant");
  }
  if (message.role === "user") {
    return copy("You", "你");
  }
  if (message.role === "tool") {
    return copy("Tool", "工具");
  }
  return copy("System", "系统");
}

function messageKindLabel(message: AgentConversationMessage, copy: ReturnType<typeof useI18n>["copy"]): string | null {
  if (message.kind === "status") {
    return copy("Run update", "状态更新");
  }
  if (message.kind === "tool_use") {
    return copy("Tool call", "工具调用");
  }
  if (message.kind === "tool_result") {
    return copy("Tool result", "工具结果");
  }
  return null;
}

export function ChatMessageStream({ loading, messages }: ChatMessageStreamProps): JSX.Element {
  const { copy } = useI18n();

  if (loading) {
    return (
      <div className="chat-stream chat-stream--empty">
        <div className="chat-stream__empty-title">{copy("Loading conversation…", "正在加载会话…")}</div>
      </div>
    );
  }

  if (!messages.length) {
    return (
      <div className="chat-stream chat-stream--empty">
        <div className="chat-stream__empty-title">{copy("No messages yet", "还没有消息")}</div>
        <div className="chat-stream__empty-text">
          {copy(
            "Use the composer below to start a new assistant request or autonomous session.",
            "在下方输入框发起第一条 Assistant 请求或 Autonomous 会话。",
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="chat-stream">
      {messages.map((message) => {
        const blocks = contentToBlocks(message.content);
        const kindLabel = messageKindLabel(message, copy);
        return (
          <article key={message.id} className="chat-message" data-role={message.role} data-kind={message.kind}>
            <div className="chat-message__meta">
              <span className="chat-message__meta-main">
                <span className="chat-message__role-badge">{roleLabel(message, copy)}</span>
                {kindLabel ? <span className="chat-message__meta-kind">{kindLabel}</span> : null}
              </span>
              <span className="chat-message__meta-time">
                {message.status === "streaming" ? copy("Streaming", "流式输出中") : formatDateTime(message.createdAt)}
              </span>
            </div>
            {message.title ? <div className="chat-message__title">{message.title}</div> : null}
            <div className="chat-message__body">
              {message.content
                ? blocks.map((block, index) => renderBlock(block, `${message.id}-${index}`))
                : message.status === "streaming"
                  ? copy("Assistant is responding…", "Assistant 正在输出…")
                  : copy("Waiting for content…", "等待内容返回…")}
            </div>
          </article>
        );
      })}
    </div>
  );
}
