import React, { useState } from "react";
import { Panel, StatusBadge } from "../../components";
import { formatCompactDate } from "../../lib/format";
import { theme } from "../../lib/theme";
import type { CompileTaskRequest, DomainPackRecord, RuntimeExecutionPlan, RuntimeTaskSpec } from "../../lib/types";

interface RuntimeAuthoringViewProps {
  domainPacks: DomainPackRecord[];
  taskSpecs: RuntimeTaskSpec[];
  plans: RuntimeExecutionPlan[];
  compiling: boolean;
  trialTaskId?: string;
  onCompile(request: CompileTaskRequest): void;
  onCreateTrial(taskSpecId: string, executionPlanId: string): void;
}

const inputStyle = {
  width: "100%",
  borderRadius: "14px",
  border: `1px solid ${theme.colors.border}`,
  background: "rgba(255,255,255,0.04)",
  color: theme.colors.text,
  padding: "12px 14px",
  fontSize: "14px",
} as const;

export function RuntimeAuthoringView({
  domainPacks,
  taskSpecs,
  plans,
  compiling,
  trialTaskId,
  onCompile,
  onCreateTrial,
}: RuntimeAuthoringViewProps): JSX.Element {
  const [instruction, setInstruction] = useState("打开网站，帮我找到值得用的 PDF 转换器，比较后输出 shortlist。");
  const [title, setTitle] = useState("Research PDF converters");
  const [domainHint, setDomainHint] = useState("web_research");

  return (
    <div style={{ display: "grid", gap: "18px" }}>
      <Panel
        title="Task compiler"
        eyebrow="Natural language entry"
        description="Describe the task in normal language. The runtime compiles it into a TaskSpec and trial-ready ExecutionPlan."
      >
        <div style={{ display: "grid", gap: "12px" }}>
          <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 220px", gap: "12px" }}>
            <input style={inputStyle} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Task title" />
            <select style={inputStyle} value={domainHint} onChange={(event) => setDomainHint(event.target.value)}>
              {domainPacks.map((pack) => (
                <option key={pack.key} value={pack.key}>
                  {pack.name}
                </option>
              ))}
            </select>
          </div>
          <textarea
            style={{ ...inputStyle, minHeight: "120px", resize: "vertical" }}
            value={instruction}
            onChange={(event) => setInstruction(event.target.value)}
            placeholder="Describe what the agent should do and what output you expect."
          />
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "12px", flexWrap: "wrap" }}>
            <div style={{ color: theme.colors.muted, fontSize: "13px" }}>
              New tasks default into supervised trial mode and can later be promoted into templates and skills.
            </div>
            <button
              type="button"
              onClick={() => onCompile({ instruction, title, domainHint })}
              disabled={compiling || !instruction.trim()}
              style={{
                border: `1px solid ${theme.colors.border}`,
                borderRadius: "14px",
                padding: "10px 14px",
                cursor: "pointer",
                fontWeight: 700,
                background: "rgba(93,216,163,0.16)",
                color: "#dcfff1",
              }}
            >
              {compiling ? "Compiling..." : "Compile task"}
            </button>
          </div>
        </div>
      </Panel>

      <Panel
        title="Recent task specs"
        eyebrow="Compiled runtime tasks"
        description="Each task stays local-first. Trial plans can be launched immediately, then reviewed before promotion."
      >
        <div style={{ display: "grid", gap: "12px" }}>
          {taskSpecs.map((task) => {
            const plan = plans.find((item) => item.id === task.activePlanId) ?? plans.find((item) => item.taskSpecId === task.id);
            return (
              <article
                key={task.id}
                style={{
                  borderRadius: "18px",
                  border: `1px solid ${theme.colors.border}`,
                  background: "rgba(255,255,255,0.03)",
                  padding: "16px",
                  display: "grid",
                  gap: "10px",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", alignItems: "start", flexWrap: "wrap" }}>
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                      <strong>{task.title}</strong>
                      <StatusBadge tone="neutral">{task.domain}</StatusBadge>
                      <StatusBadge tone={task.status.includes("ready") ? "positive" : "warning"}>{task.status}</StatusBadge>
                    </div>
                    <div style={{ marginTop: "6px", color: theme.colors.muted, fontSize: "13px", lineHeight: 1.5 }}>{task.goal}</div>
                  </div>
                  {plan ? (
                    <button
                      type="button"
                      onClick={() => onCreateTrial(task.id, plan.id)}
                      disabled={trialTaskId === task.id}
                      style={{
                        border: `1px solid ${theme.colors.border}`,
                        borderRadius: "14px",
                        padding: "9px 12px",
                        cursor: "pointer",
                        fontWeight: 700,
                        background: "rgba(122,167,255,0.18)",
                        color: "#edf4ff",
                      }}
                    >
                      {trialTaskId === task.id ? "Creating trial..." : "Start trial"}
                    </button>
                  ) : null}
                </div>
                <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                  {task.preferredCapabilities.map((capability) => (
                    <StatusBadge key={capability} tone="neutral">
                      {capability}
                    </StatusBadge>
                  ))}
                </div>
                <div style={{ color: "rgba(233,239,255,0.56)", fontSize: "12px" }}>
                  Updated {formatCompactDate(task.updatedAt)}
                  {plan ? ` · Plan ${plan.name}` : " · No active plan"}
                </div>
              </article>
            );
          })}
        </div>
      </Panel>
    </div>
  );
}
