import React, { useEffect, useMemo, useState } from "react";
import type { CandidateTransitionPayload } from "@scene-pilot/shared";
import { Panel, StatusBadge } from "../../components";
import { formatCompactDate } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { translateUiToken } from "../../lib/uiText";
import type {
  ApprovalItem,
  CandidateAssessmentRecord,
  CandidateThreadRecord,
  RecruitAgentProfileRecord,
} from "../../lib/types";

interface CommunicationsViewProps {
  profile: RecruitAgentProfileRecord | null;
  threads: CandidateThreadRecord[];
  preferredCandidateId?: string;
  preferredStatusFilter?: string;
  pendingActionId?: string;
  onApprove(id: string): Promise<void> | void;
  onReject(id: string): Promise<void> | void;
  onCreateEntry(candidateId: string, payload: { direction: string; content: string; messageType?: string; platform?: string }): Promise<void> | void;
  onTransitionState(candidateId: string, payload: CandidateTransitionPayload): Promise<void> | void;
  onCreateAssessment(
    candidateId: string,
    payload: {
      assessmentType: string;
      stageKey?: string;
      status?: string;
      decision?: string;
      score?: number;
      summary?: string;
      evidenceRefs?: unknown[];
      metadata?: Record<string, unknown>;
      createdBy?: string;
      reviewedBy?: string;
    },
  ): Promise<void> | void;
}

type QueueFilter = "all" | "active" | "waiting" | "resume" | "interviews" | "decision" | "blocked";

type StageOption = {
  value: string;
  label: string;
};

const pageStyle: React.CSSProperties = {
  display: "grid",
  gap: "var(--space-5)",
};

const heroStyle: React.CSSProperties = {
  display: "grid",
  gap: "var(--space-4)",
  padding: "var(--space-6)",
  border: "1px solid var(--border-line)",
  borderRadius: "var(--radius-lg)",
  background: "var(--bg-card)",
};

const layoutStyle: React.CSSProperties = {
  display: "grid",
  gap: "var(--space-4)",
  gridTemplateColumns: "var(--layout-left-list-width) minmax(0, 1.1fr) var(--layout-right-panel-width)",
  alignItems: "start",
};

const fieldGridStyle: React.CSSProperties = {
  display: "grid",
  gap: "var(--space-3)",
};

const controlLabelStyle: React.CSSProperties = {
  display: "grid",
  gap: "var(--space-2)",
  fontSize: "var(--font-size-sm)",
  color: "var(--text-secondary)",
};

const inputStyle: React.CSSProperties = {
  width: "100%",
  minWidth: 0,
  minHeight: "32px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--border-input)",
  background: "var(--bg-card)",
  color: "var(--text-primary)",
  padding: "0 var(--space-3)",
  fontSize: "var(--font-size-sm)",
};

const textareaStyle: React.CSSProperties = {
  ...inputStyle,
  minHeight: "92px",
  padding: "var(--space-3)",
  resize: "vertical",
  lineHeight: "var(--line-height-base)",
};

const buttonStyle: React.CSSProperties = {
  minHeight: "32px",
  border: "1px solid var(--border-input)",
  borderRadius: "var(--radius-sm)",
  background: "var(--bg-card)",
  color: "var(--text-primary)",
  padding: "0 var(--space-4)",
  cursor: "pointer",
  fontWeight: "var(--font-weight-medium)",
};

const primaryButtonStyle: React.CSSProperties = {
  ...buttonStyle,
  borderColor: "var(--brand-primary)",
  background: "var(--brand-primary)",
  color: "var(--text-inverse)",
};

const candidateButtonStyle: React.CSSProperties = {
  width: "100%",
  textAlign: "left",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--border-line)",
  background: "var(--bg-subtle)",
  color: "var(--text-primary)",
  padding: "var(--space-4)",
  display: "grid",
  gap: "var(--space-2)",
  cursor: "pointer",
};

const metricStripStyle: React.CSSProperties = {
  display: "grid",
  gap: "var(--space-3)",
  gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
};

const metricCardStyle: React.CSSProperties = {
  display: "grid",
  gap: "var(--space-1)",
  padding: "var(--space-4)",
  border: "1px solid var(--border-line)",
  borderRadius: "var(--radius-md)",
  background: "var(--bg-card)",
};

const bubbleBaseStyle: React.CSSProperties = {
  maxWidth: "60%",
  borderRadius: "var(--radius-lg)",
  padding: "var(--space-3)",
  display: "grid",
  gap: "var(--space-1)",
  border: "1px solid var(--border-line)",
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function normalize(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9\u4e00-\u9fff]+/gi, "");
}

function statusTone(status: string): "positive" | "neutral" | "warning" | "critical" {
  if (/(rejected|cooldown|failed|critical|blocked)/i.test(status)) {
    return "critical";
  }
  if (/(waiting|pending|review|requested|schedule|followup|resume)/i.test(status)) {
    return "warning";
  }
  if (/(passed|received|completed|scheduled|acquired|offer|hired|active)/i.test(status)) {
    return "positive";
  }
  return "neutral";
}

function classifyThread(thread: CandidateThreadRecord): QueueFilter {
  const status = normalize(
    `${thread.candidate.status} ${thread.candidate.stageKey} ${thread.candidate.nextAction} ${thread.stateSnapshot.resumeStatus ?? ""} ${
      thread.stateSnapshot.contactStatus ?? ""
    }`,
  );

  if (/(rejected|cooldown|failed|blocked|archived)/.test(status)) {
    return "blocked";
  }
  if (/(offer|hired|decision|accepted|selected)/.test(status)) {
    return "decision";
  }
  if (/(interview|schedule|scheduled|onsite|phoneinterview|screeningcall)/.test(status)) {
    return "interviews";
  }
  if (!thread.candidate.resumeAvailable || /(resume_requested|resume_pending|waiting_resume|needresume)/.test(status)) {
    return "resume";
  }
  if (/(contact_required|contact_needed|waiting_reply|pending_communication|communicating|outreach|followup)/.test(status)) {
    return "waiting";
  }
  return "active";
}

function conversationBubbleStyle(direction: string): React.CSSProperties {
  if (direction === "outbound") {
    return {
      ...bubbleBaseStyle,
      justifySelf: "end",
      background: "var(--brand-primary)",
      borderColor: "var(--brand-primary)",
      color: "var(--text-inverse)",
    };
  }
  if (direction === "inbound") {
    return {
      ...bubbleBaseStyle,
      justifySelf: "start",
      background: "var(--bg-card)",
    };
  }
  return {
    ...bubbleBaseStyle,
    justifySelf: "center",
    background: "var(--bg-subtle)",
  };
}

function readContactField(candidate: CandidateThreadRecord["candidate"], key: string): string | null {
  const raw = candidate.contactInfo?.[key];
  return typeof raw === "string" && raw.trim() ? raw : null;
}

function PendingRuntimeApprovals({
  approvals,
  pendingActionId,
  onApprove,
  onReject,
}: {
  approvals: ApprovalItem[];
  pendingActionId?: string;
  onApprove(id: string): Promise<void> | void;
  onReject(id: string): Promise<void> | void;
}): JSX.Element {
  const { copy } = useI18n();

  if (!approvals.length) {
    return <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)" }}>{copy("No review requests are waiting on this candidate.", "当前候选人没有待处理确认。")}</div>;
  }

  return (
    <div style={{ display: "grid", gap: "var(--space-3)" }}>
      {approvals.map((approval) => (
        <article
          key={approval.id}
          style={{
            display: "grid",
            gap: "var(--space-3)",
            padding: "var(--space-4)",
            borderRadius: "var(--radius-md)",
            border: "1px solid var(--border-line)",
            background: "var(--bg-subtle)",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start", gap: "var(--space-3)" }}>
            <div style={{ display: "grid", gap: "6px" }}>
              <strong>{approval.title}</strong>
              <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)", lineHeight: "var(--line-height-base)" }}>{approval.detail}</div>
            </div>
            <StatusBadge tone={approval.status === "pending" ? "warning" : approval.status === "approved" ? "positive" : "critical"}>
              {translateUiToken(approval.status, copy)}
            </StatusBadge>
          </div>
          {approval.payload && Object.keys(approval.payload).length ? (
            <details>
              <summary style={{ cursor: "pointer", color: "var(--text-secondary)", fontSize: "var(--font-size-xs)" }}>
                {copy("Show details", "查看详情")}
              </summary>
              <pre
                style={{
                  margin: "10px 0 0",
                  padding: "var(--space-3)",
                  borderRadius: "var(--radius-sm)",
                  background: "var(--bg-card)",
                  color: "var(--text-secondary)",
                  fontSize: "12px",
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                }}
              >
                {JSON.stringify(approval.payload, null, 2)}
              </pre>
            </details>
          ) : null}
          {approval.status === "pending" ? (
            <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
              <button type="button" style={primaryButtonStyle} onClick={() => void onApprove(approval.id)} disabled={pendingActionId === approval.id}>
                {pendingActionId === approval.id ? copy("Working...", "处理中...") : copy("Approve", "确认")}
              </button>
              <button
                type="button"
                style={{ ...buttonStyle, color: "var(--danger)", borderColor: "color-mix(in srgb, var(--danger) 30%, var(--border-input))" }}
                onClick={() => void onReject(approval.id)}
                disabled={pendingActionId === approval.id}
              >
                {copy("Reject", "拒绝")}
              </button>
            </div>
          ) : null}
        </article>
      ))}
    </div>
  );
}

function AssessmentCard({ item }: { item: CandidateAssessmentRecord }): JSX.Element {
  const { copy } = useI18n();

  return (
    <article
      style={{
        display: "grid",
        gap: "var(--space-2)",
        padding: "var(--space-4)",
        borderRadius: "var(--radius-md)",
        border: "1px solid var(--border-line)",
        background: "var(--bg-subtle)",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--space-3)", alignItems: "start" }}>
        <div style={{ display: "grid", gap: "4px" }}>
          <strong>{item.assessmentType === "ai" ? copy("AI review", "AI 评审") : copy("Manual review", "人工评审")}</strong>
          <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-xs)" }}>{item.stageKey ?? copy("Unassigned stage", "未绑定阶段")}</div>
        </div>
        <StatusBadge tone={statusTone(item.status)}>{translateUiToken(item.status, copy)}</StatusBadge>
      </div>
      <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
        {item.decision ? <StatusBadge tone={statusTone(item.decision)}>{translateUiToken(item.decision, copy)}</StatusBadge> : null}
        {item.score != null ? <StatusBadge tone="neutral">{copy(`score ${item.score}`, `分数 ${item.score}`)}</StatusBadge> : null}
      </div>
      {item.summary ? <div style={{ fontSize: "var(--font-size-sm)", lineHeight: "var(--line-height-base)" }}>{item.summary}</div> : null}
      <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-xs)" }}>{formatCompactDate(item.createdAt)}</div>
    </article>
  );
}

export function CommunicationsView({
  profile,
  threads,
  preferredCandidateId,
  preferredStatusFilter,
  pendingActionId,
  onApprove,
  onReject,
  onCreateEntry,
  onTransitionState,
  onCreateAssessment,
}: CommunicationsViewProps): JSX.Element {
  const { copy } = useI18n();
  const [selectedCandidateId, setSelectedCandidateId] = useState<string>();
  const [queueFilter, setQueueFilter] = useState<QueueFilter>("all");
  const [draft, setDraft] = useState("");
  const [direction, setDirection] = useState("outbound");
  const [messageType, setMessageType] = useState("text");
  const [transitionStatus, setTransitionStatus] = useState("");
  const [transitionNote, setTransitionNote] = useState("");
  const [contactChannelsDraft, setContactChannelsDraft] = useState("");
  const [interviewRoundDraft, setInterviewRoundDraft] = useState("1");
  const [assessmentType, setAssessmentType] = useState("manual");
  const [assessmentDecision, setAssessmentDecision] = useState("pass");
  const [assessmentScore, setAssessmentScore] = useState("80");
  const [assessmentSummary, setAssessmentSummary] = useState("");

  useEffect(() => {
    if (!threads.length) {
      setSelectedCandidateId(undefined);
      return;
    }
    if (preferredCandidateId && threads.some((thread) => thread.candidate.id === preferredCandidateId)) {
      setSelectedCandidateId(preferredCandidateId);
      return;
    }
    if (!selectedCandidateId || !threads.some((thread) => thread.candidate.id === selectedCandidateId)) {
      setSelectedCandidateId(threads[0]?.candidate.id);
    }
  }, [preferredCandidateId, selectedCandidateId, threads]);

  useEffect(() => {
    switch (preferredStatusFilter) {
      case "candidate":
        setQueueFilter("all");
        break;
      case "active":
      case "waiting":
      case "resume":
      case "interviews":
      case "decision":
      case "blocked":
        setQueueFilter(preferredStatusFilter);
        break;
      default:
        break;
    }
  }, [preferredStatusFilter]);

  const filteredThreads = useMemo(() => {
    if (preferredCandidateId && preferredStatusFilter === "candidate") {
      return threads.filter((thread) => thread.candidate.id === preferredCandidateId);
    }
    if (queueFilter === "all") {
      return threads;
    }
    return threads.filter((thread) => classifyThread(thread) === queueFilter);
  }, [preferredCandidateId, preferredStatusFilter, queueFilter, threads]);

  const selectedThread = useMemo(
    () => filteredThreads.find((thread) => thread.candidate.id === selectedCandidateId) ?? filteredThreads[0] ?? null,
    [filteredThreads, selectedCandidateId],
  );

  const stageOptions = useMemo(() => {
    const options: StageOption[] = [];
    const stageGroups = profile?.playbookBlueprint?.["stage_groups"];
    if (Array.isArray(stageGroups)) {
      stageGroups.forEach((group) => {
        const record = asRecord(group);
        if (!record) {
          return;
        }
        const stages = record["stages"];
        if (Array.isArray(stages)) {
          stages.forEach((stage) => {
            const stageRecord = asRecord(stage);
            if (!stageRecord) {
              return;
            }
            const value = typeof stageRecord["key"] === "string" ? stageRecord["key"] : typeof stageRecord["label"] === "string" ? stageRecord["label"] : "";
            if (!value) {
              return;
            }
            const label = typeof stageRecord["label"] === "string" ? stageRecord["label"] : value;
            options.push({ value, label });
          });
        }
        const rounds = record["default_rounds"];
        if (Array.isArray(rounds)) {
          rounds.forEach((round) => {
            const roundRecord = asRecord(round);
            if (!roundRecord) {
              return;
            }
            const roundIndex = typeof roundRecord["round"] === "number" || typeof roundRecord["round"] === "string" ? String(roundRecord["round"]) : "";
            const waitingKey = typeof roundRecord["waiting_key"] === "string" ? roundRecord["waiting_key"] : "";
            const scheduledKey = typeof roundRecord["scheduled_key"] === "string" ? roundRecord["scheduled_key"] : "";
            if (waitingKey) {
              options.push({ value: waitingKey, label: copy(`Round ${roundIndex} waiting`, `第 ${roundIndex} 轮待预约`) });
            }
            if (scheduledKey) {
              options.push({ value: scheduledKey, label: copy(`Round ${roundIndex} scheduled`, `第 ${roundIndex} 轮已预约`) });
            }
          });
        }
      });
    }
    if (!options.length && selectedThread) {
      return selectedThread.availableStatuses.map((status) => ({ value: status, label: translateUiToken(status, copy) }));
    }
    return options;
  }, [copy, profile, selectedThread]);

  useEffect(() => {
    if (!selectedThread) {
      setTransitionStatus("");
      setTransitionNote("");
      return;
    }
    setTransitionStatus(selectedThread.stateSnapshot.currentStageKey ?? selectedThread.candidate.status);
    setContactChannelsDraft(selectedThread.stateSnapshot.contactChannels.join(", "));
  }, [selectedThread]);

  const queueMetrics = useMemo(() => {
    return threads.reduce<Record<QueueFilter, number>>(
      (acc, thread) => {
        acc[classifyThread(thread)] += 1;
        return acc;
      },
      {
        all: threads.length,
        active: 0,
        waiting: 0,
        resume: 0,
        interviews: 0,
        decision: 0,
        blocked: 0,
      },
    );
  }, [threads]);

  const handleSubmit = async () => {
    if (!selectedThread || !draft.trim()) {
      return;
    }
    await onCreateEntry(selectedThread.candidate.id, {
      direction,
      content: draft.trim(),
      messageType,
      platform: selectedThread.candidate.platform,
    });
    setDraft("");
  };

  const handleTransition = async () => {
    if (!selectedThread || !transitionStatus.trim()) {
      return;
    }
    const contactChannels = contactChannelsDraft
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    await onTransitionState(selectedThread.candidate.id, {
      actor: "recruiter",
      toStatus: transitionStatus,
      trigger: "manual_transition",
      stageKey: transitionStatus,
      stageLabel: transitionStatus,
      note: transitionNote.trim() || undefined,
      interviewRound: Number(interviewRoundDraft || "0") || undefined,
      contactChannels,
    });
    setTransitionNote("");
  };

  const handleAssessment = async () => {
    if (!selectedThread || !assessmentSummary.trim()) {
      return;
    }
    await onCreateAssessment(selectedThread.candidate.id, {
      assessmentType,
      stageKey: selectedThread.stateSnapshot.currentStageKey ?? selectedThread.candidate.stageKey,
      status: "completed",
      decision: assessmentDecision,
      score: Number(assessmentScore || "0") || undefined,
      summary: assessmentSummary.trim(),
      evidenceRefs: selectedThread.candidate.tags,
      createdBy: "desktop-user",
    });
    setAssessmentSummary("");
  };

  return (
    <div style={pageStyle}>
      <section style={heroStyle}>
        <div style={{ display: "grid", gap: "var(--space-2)" }}>
          <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-xs)", letterSpacing: "0.16em", textTransform: "uppercase" }}>
            {copy("Communications", "沟通中心")}
          </div>
          <h1 style={{ margin: 0, fontSize: "var(--font-size-lg)", lineHeight: "var(--line-height-tight)", fontWeight: "var(--font-weight-bold)" }}>
            {copy("Candidate cockpit", "候选人沟通驾驶舱")}
          </h1>
          <p style={{ margin: 0, color: "var(--text-secondary)", maxWidth: "760px", lineHeight: "var(--line-height-base)" }}>
            {copy(
              "Stay inside one candidate at a time: review the latest conversation, confirm the next stage, and keep resume and contact facts attached to the same record.",
              "以候选人为单位处理沟通：查看最新对话、确认下一阶段，并把简历与联系方式始终收拢在同一条记录里。",
            )}
          </p>
        </div>
        <div style={metricStripStyle}>
          <div style={metricCardStyle}>
            <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-xs)", textTransform: "uppercase", letterSpacing: "0.08em" }}>{copy("Open queue", "开放队列")}</div>
            <strong style={{ fontSize: "var(--font-size-xl)" }}>{threads.length}</strong>
            <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)" }}>{copy("Candidates with active communication context", "有沟通上下文的候选人")}</div>
          </div>
          <div style={metricCardStyle}>
            <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-xs)", textTransform: "uppercase", letterSpacing: "0.08em" }}>{copy("Waiting reply", "待回复")}</div>
            <strong style={{ fontSize: "var(--font-size-xl)" }}>{queueMetrics.waiting}</strong>
            <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)" }}>{copy("Need contact follow-up", "需要继续跟进联系")}</div>
          </div>
          <div style={metricCardStyle}>
            <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-xs)", textTransform: "uppercase", letterSpacing: "0.08em" }}>{copy("Resume pending", "待补简历")}</div>
            <strong style={{ fontSize: "var(--font-size-xl)" }}>{queueMetrics.resume}</strong>
            <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)" }}>{copy("Candidates still missing resume artifacts", "尚未沉淀简历制品的候选人")}</div>
          </div>
          <div style={metricCardStyle}>
            <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-xs)", textTransform: "uppercase", letterSpacing: "0.08em" }}>{copy("Review requests", "待处理确认")}</div>
            <strong style={{ fontSize: "var(--font-size-xl)" }}>{threads.reduce((sum, thread) => sum + thread.runtimeApprovals.filter((item) => item.status === "pending").length, 0)}</strong>
            <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)" }}>{copy("Approvals still blocking progress", "仍在阻塞推进的确认项")}</div>
          </div>
        </div>
      </section>

      <div style={layoutStyle}>
        <Panel
          title={copy("Candidate queue", "候选人队列")}
          eyebrow={copy("Queue first", "队列优先")}
          description={copy("Choose a lane to focus on and jump directly into the candidate that needs action now.", "先按队列筛选，再进入当前最需要动作的候选人。")}
        >
          <div style={{ display: "grid", gap: "var(--space-3)" }}>
            <select value={queueFilter} onChange={(event) => setQueueFilter(event.target.value as QueueFilter)} style={inputStyle}>
              <option value="all">{copy("All candidates", "全部候选人")}</option>
              <option value="active">{copy("Active", "推进中")}</option>
              <option value="waiting">{copy("Waiting reply", "待回复")}</option>
              <option value="resume">{copy("Resume pending", "待简历")}</option>
              <option value="interviews">{copy("Interview queue", "面试阶段")}</option>
              <option value="decision">{copy("Decision queue", "决策阶段")}</option>
              <option value="blocked">{copy("Blocked", "阻塞")}</option>
            </select>

            <div style={{ display: "grid", gap: "var(--space-3)" }}>
              {filteredThreads.map((thread) => {
                const active = thread.candidate.id === selectedThread?.candidate.id;
                const pendingCount = thread.runtimeApprovals.filter((item) => item.status === "pending").length;
                const lane = classifyThread(thread);
                return (
                  <button
                    key={thread.candidate.id}
                    type="button"
                    onClick={() => setSelectedCandidateId(thread.candidate.id)}
                    style={{
                      ...candidateButtonStyle,
                      borderColor: active ? "color-mix(in srgb, var(--brand-primary) 28%, var(--border-line))" : "var(--border-line)",
                      background: active ? "color-mix(in srgb, var(--brand-primary-soft) 36%, white)" : candidateButtonStyle.background,
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start", gap: "var(--space-3)" }}>
                      <strong>{thread.candidate.name}</strong>
                      {pendingCount ? <StatusBadge tone="warning">{pendingCount}</StatusBadge> : null}
                    </div>
                    <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)" }}>
                      {thread.candidate.jdTitle} · {thread.candidate.location || copy("Unknown city", "城市待补")}
                    </div>
                    <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
                      <StatusBadge tone={statusTone(thread.candidate.status)}>{translateUiToken(thread.candidate.status, copy)}</StatusBadge>
                      <StatusBadge tone={statusTone(lane)}>{copy(lane === "waiting" ? "waiting" : lane, lane === "waiting" ? "待回复" : translateUiToken(lane, copy))}</StatusBadge>
                      <StatusBadge tone={thread.candidate.resumeAvailable ? "positive" : "warning"}>
                        {thread.candidate.resumeAvailable ? copy("Resume ready", "已有简历") : copy("Resume pending", "待简历")}
                      </StatusBadge>
                    </div>
                    <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-xs)", lineHeight: "var(--line-height-base)" }}>
                      {thread.candidate.nextAction || thread.contextSummary || copy("No next action yet.", "暂无下一步建议。")}
                    </div>
                  </button>
                );
              })}
            </div>

            {!filteredThreads.length ? <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)" }}>{copy("No candidates match the current queue filter.", "当前筛选下没有候选人。")}</div> : null}
          </div>
        </Panel>

        <Panel
          title={selectedThread?.candidate.name ?? copy("Conversation cockpit", "沟通视图")}
          eyebrow={copy("Candidate timeline", "候选人时间线")}
          description={
            selectedThread?.contextSummary ??
            copy("Read the latest thread, append operator notes, and keep the next move attached to this candidate.", "查看最新线程、补充人工记录，并把下一步动作继续挂在这个候选人名下。")
          }
          actions={
            selectedThread ? (
              <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
                <StatusBadge tone="neutral">{selectedThread.candidate.jdTitle}</StatusBadge>
                <StatusBadge tone={statusTone(selectedThread.candidate.status)}>{translateUiToken(selectedThread.candidate.status, copy)}</StatusBadge>
                <StatusBadge tone={selectedThread.runtimeApprovals.some((item) => item.status === "pending") ? "warning" : "positive"}>
                  {copy(
                    `${selectedThread.runtimeApprovals.filter((item) => item.status === "pending").length} pending`,
                    `${selectedThread.runtimeApprovals.filter((item) => item.status === "pending").length} 个待确认`,
                  )}
                </StatusBadge>
              </div>
            ) : null
          }
        >
          {selectedThread ? (
            <div style={{ display: "grid", gap: "var(--space-4)" }}>
              <div style={{ display: "grid", gap: "var(--space-3)", maxHeight: "520px", overflowY: "auto", paddingRight: "4px" }}>
                {selectedThread.communicationLogs.length ? (
                  selectedThread.communicationLogs.map((log) => (
                    <article key={log.id} style={conversationBubbleStyle(log.direction)}>
                      <div
                        style={{
                          fontSize: "var(--font-size-xs)",
                          color: log.direction === "outbound" ? "color-mix(in srgb, var(--text-inverse) 72%, transparent)" : "var(--text-secondary)",
                        }}
                      >
                        {translateUiToken(log.direction, copy)} · {log.timestamp ? formatCompactDate(log.timestamp) : copy("now", "刚刚")}
                      </div>
                      <div style={{ fontSize: "var(--font-size-sm)", lineHeight: "var(--line-height-base)" }}>{log.content}</div>
                    </article>
                  ))
                ) : (
                  <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)" }}>{copy("No messages yet.", "暂无沟通记录。")}</div>
                )}
              </div>

              <div style={{ display: "grid", gap: "var(--space-3)" }}>
                <div style={{ display: "grid", gap: "var(--space-3)", gridTemplateColumns: "140px 140px minmax(0, 1fr)" }}>
                  <label style={controlLabelStyle}>
                    <span>{copy("Direction", "方向")}</span>
                    <select value={direction} onChange={(event) => setDirection(event.target.value)} style={inputStyle}>
                      <option value="outbound">{copy("Outbound", "发出")}</option>
                      <option value="inbound">{copy("Inbound", "收到")}</option>
                      <option value="system">{copy("System", "系统")}</option>
                    </select>
                  </label>
                  <label style={controlLabelStyle}>
                    <span>{copy("Type", "类型")}</span>
                    <select value={messageType} onChange={(event) => setMessageType(event.target.value)} style={inputStyle}>
                      <option value="text">{copy("Text", "文本")}</option>
                      <option value="note">{copy("Note", "备注")}</option>
                      <option value="approval">{copy("Approval", "确认")}</option>
                    </select>
                  </label>
                  <label style={controlLabelStyle}>
                    <span>{copy("Message", "消息")}</span>
                    <textarea value={draft} onChange={(event) => setDraft(event.target.value)} style={textareaStyle} />
                  </label>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--space-3)", flexWrap: "wrap", alignItems: "center" }}>
                  <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)" }}>
                    {copy("Append notes or operator messages without leaving the candidate context.", "无需离开候选人上下文，就能追加人工备注和消息。")}
                  </div>
                  <button type="button" style={primaryButtonStyle} onClick={() => void handleSubmit()}>
                    {copy("Append to thread", "追加到线程")}
                  </button>
                </div>
              </div>
            </div>
          ) : (
            <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)" }}>{copy("No candidate selected.", "尚未选择候选人。")}</div>
          )}
        </Panel>

        <div style={{ display: "grid", gap: "var(--space-4)" }}>
          <Panel
            title={copy("Candidate facts", "候选人事实")}
            eyebrow={copy("Profile snapshot", "资料快照")}
            description={copy("Contact, owner, resume, and current stage stay consolidated on one side.", "联系方式、负责人、简历和当前阶段集中在右侧查看。")}
          >
            {selectedThread ? (
              <div style={{ display: "grid", gap: "var(--space-3)" }}>
                <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
                  <StatusBadge tone={selectedThread.stateSnapshot.contactAcquired ? "positive" : "warning"}>
                    {selectedThread.stateSnapshot.contactAcquired ? copy("Contact acquired", "已拿到联系方式") : copy("Contact missing", "待拿联系方式")}
                  </StatusBadge>
                  <StatusBadge tone={selectedThread.candidate.resumeAvailable ? "positive" : "warning"}>
                    {selectedThread.candidate.resumeAvailable ? copy("Resume received", "已收到简历") : copy("Resume pending", "待简历")}
                  </StatusBadge>
                  <StatusBadge tone="neutral">{copy(`Match ${selectedThread.candidate.matchScore}`, `匹配度 ${selectedThread.candidate.matchScore}`)}</StatusBadge>
                </div>
                <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)", lineHeight: "var(--line-height-base)" }}>
                  {selectedThread.candidate.summary || copy("No candidate summary yet.", "暂无候选人摘要。")}
                </div>
                <div style={{ display: "grid", gap: "var(--space-2)", fontSize: "var(--font-size-sm)" }}>
                  <div>{copy("Phone", "手机号")}: {readContactField(selectedThread.candidate, "phone") ?? copy("Unknown", "未知")}</div>
                  <div>{copy("WeChat", "微信")}: {readContactField(selectedThread.candidate, "wechat") ?? copy("Unknown", "未知")}</div>
                  <div>{copy("Contact channels", "联系方式渠道")}: {selectedThread.stateSnapshot.contactChannels.length ? selectedThread.stateSnapshot.contactChannels.join(", ") : copy("None", "暂无")}</div>
                  <div>{copy("Current stage", "当前阶段")}: {translateUiToken(selectedThread.stateSnapshot.currentStageKey ?? selectedThread.candidate.stageKey, copy)}</div>
                  <div>{copy("Latest resume", "最近简历")}: {selectedThread.resumeArtifacts[0]?.fileName ?? selectedThread.resumeArtifacts[0]?.filePath ?? copy("None", "暂无")}</div>
                  <div>{copy("Owner", "负责人")}: {selectedThread.assignments[0]?.assignee ?? copy("Unassigned", "未分配")}</div>
                </div>
              </div>
            ) : null}
          </Panel>

          <Panel
            title={copy("Stage transition", "阶段流转")}
            eyebrow={copy("Operator action", "人工动作")}
            description={copy("Use the current queue facts to move this candidate forward and keep the full history on record.", "结合当前事实推进候选人，并保留完整的状态历史。")}
          >
            {selectedThread ? (
              <div style={fieldGridStyle}>
                <label style={controlLabelStyle}>
                  <span>{copy("Target status", "目标状态")}</span>
                  <select value={transitionStatus} onChange={(event) => setTransitionStatus(event.target.value)} style={inputStyle}>
                    {stageOptions.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label style={controlLabelStyle}>
                  <span>{copy("Contact channels", "联系方式渠道")}</span>
                  <input value={contactChannelsDraft} onChange={(event) => setContactChannelsDraft(event.target.value)} style={inputStyle} placeholder={copy("phone, wechat", "phone, wechat")} />
                </label>
                <label style={controlLabelStyle}>
                  <span>{copy("Interview round", "面试轮次")}</span>
                  <input value={interviewRoundDraft} onChange={(event) => setInterviewRoundDraft(event.target.value)} style={inputStyle} />
                </label>
                <label style={controlLabelStyle}>
                  <span>{copy("Operator note", "操作备注")}</span>
                  <textarea value={transitionNote} onChange={(event) => setTransitionNote(event.target.value)} style={{ ...textareaStyle, minHeight: "80px" }} />
                </label>
                <button type="button" style={primaryButtonStyle} onClick={() => void handleTransition()}>
                  {copy("Apply transition", "应用流转")}
                </button>
              </div>
            ) : null}
          </Panel>

          <Panel
            title={copy("Assessments", "评估")}
            eyebrow={copy("AI and manual", "AI 与人工")}
            description={copy("Save a quick assessment, then review the latest scorecards and decisions below it.", "先保存简要评估，再查看最新评分卡和评审结论。")}
          >
            {selectedThread ? (
              <div style={{ display: "grid", gap: "var(--space-4)" }}>
                <div style={{ display: "grid", gap: "var(--space-3)", gridTemplateColumns: "repeat(2, minmax(0, 1fr))" }}>
                  <label style={controlLabelStyle}>
                    <span>{copy("Type", "类型")}</span>
                    <select value={assessmentType} onChange={(event) => setAssessmentType(event.target.value)} style={inputStyle}>
                      <option value="manual">{copy("Manual", "人工")}</option>
                      <option value="ai">{copy("AI", "AI")}</option>
                    </select>
                  </label>
                  <label style={controlLabelStyle}>
                    <span>{copy("Decision", "结论")}</span>
                    <select value={assessmentDecision} onChange={(event) => setAssessmentDecision(event.target.value)} style={inputStyle}>
                      <option value="pass">{copy("Pass", "通过")}</option>
                      <option value="review">{copy("Review", "待复核")}</option>
                      <option value="reject">{copy("Reject", "淘汰")}</option>
                    </select>
                  </label>
                </div>
                <label style={controlLabelStyle}>
                  <span>{copy("Score", "分数")}</span>
                  <input value={assessmentScore} onChange={(event) => setAssessmentScore(event.target.value)} style={inputStyle} />
                </label>
                <label style={controlLabelStyle}>
                  <span>{copy("Assessment summary", "评估摘要")}</span>
                  <textarea value={assessmentSummary} onChange={(event) => setAssessmentSummary(event.target.value)} style={{ ...textareaStyle, minHeight: "84px" }} />
                </label>
                <button type="button" style={buttonStyle} onClick={() => void handleAssessment()}>
                  {copy("Save assessment", "保存评估")}
                </button>

                <div style={{ display: "grid", gap: "var(--space-3)" }}>
                  {selectedThread.assessments.length ? selectedThread.assessments.slice(0, 3).map((item) => <AssessmentCard key={item.id} item={item} />) : <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)" }}>{copy("No assessments yet.", "暂无评估。")}</div>}
                </div>

                <div style={{ display: "grid", gap: "var(--space-2)" }}>
                  <div style={{ fontWeight: "var(--font-weight-medium)" }}>{copy("Recent scorecards", "最近评分卡")}</div>
                  {selectedThread.scorecards.length ? (
                    selectedThread.scorecards.slice(0, 3).map((item) => (
                      <div
                        key={item.id}
                        style={{
                          display: "grid",
                          gap: "4px",
                          padding: "var(--space-3)",
                          borderRadius: "var(--radius-sm)",
                          background: "var(--bg-subtle)",
                          fontSize: "var(--font-size-sm)",
                        }}
                      >
                        <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--space-3)" }}>
                          <strong>{item.source}</strong>
                          <span>{item.scoreTotal ?? "-"}</span>
                        </div>
                        <div style={{ color: "var(--text-secondary)" }}>{item.summary ?? copy("No summary", "暂无摘要")}</div>
                      </div>
                    ))
                  ) : (
                    <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)" }}>{copy("No scorecards yet.", "暂无评分卡。")}</div>
                  )}
                </div>
              </div>
            ) : null}
          </Panel>

          <Panel
            title={copy("Resume and sync", "简历与同步")}
            eyebrow={copy("Structured records", "结构化记录")}
            description={copy("Recent artifacts, sync attempts, and ownership records stay visible while you communicate.", "沟通过程中也能直接看到最近制品、同步记录和负责人信息。")}
          >
            {selectedThread ? (
              <div style={{ display: "grid", gap: "var(--space-4)" }}>
                <div style={{ display: "grid", gap: "var(--space-2)" }}>
                  <div style={{ fontWeight: "var(--font-weight-medium)" }}>{copy("Resume artifacts", "简历制品")}</div>
                  {selectedThread.resumeArtifacts.length ? (
                    selectedThread.resumeArtifacts.slice(0, 3).map((item) => (
                      <div key={item.id} style={{ padding: "var(--space-3)", borderRadius: "var(--radius-sm)", background: "var(--bg-subtle)", fontSize: "var(--font-size-sm)" }}>
                        <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--space-3)" }}>
                          <strong>{item.artifactType}</strong>
                          <span style={{ color: "var(--text-secondary)" }}>{item.source}</span>
                        </div>
                        <div style={{ color: "var(--text-secondary)", marginTop: "4px" }}>{item.fileName ?? item.filePath ?? copy("No file path", "暂无文件路径")}</div>
                      </div>
                    ))
                  ) : (
                    <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)" }}>{copy("No resume artifacts yet.", "暂无简历制品。")}</div>
                  )}
                </div>

                <div style={{ display: "grid", gap: "var(--space-2)" }}>
                  <div style={{ fontWeight: "var(--font-weight-medium)" }}>{copy("Sync status", "同步状态")}</div>
                  {selectedThread.syncRecords.length ? (
                    selectedThread.syncRecords.slice(0, 3).map((item) => (
                      <div key={item.id} style={{ display: "grid", gap: "4px", padding: "var(--space-3)", borderRadius: "var(--radius-sm)", background: "var(--bg-subtle)", fontSize: "var(--font-size-sm)" }}>
                        <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--space-3)" }}>
                          <strong>{item.destination}</strong>
                          <StatusBadge tone={statusTone(item.status)}>{translateUiToken(item.status, copy)}</StatusBadge>
                        </div>
                        <div style={{ color: "var(--text-secondary)" }}>{item.externalRef ?? copy("No external reference", "暂无外部引用")}</div>
                      </div>
                    ))
                  ) : (
                    <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)" }}>{copy("No sync attempts yet.", "暂无同步记录。")}</div>
                  )}
                </div>

                <div style={{ display: "grid", gap: "var(--space-2)" }}>
                  <div style={{ fontWeight: "var(--font-weight-medium)" }}>{copy("Stage timeline", "阶段时间线")}</div>
                  {selectedThread.stageEvents.length ? (
                    selectedThread.stageEvents.slice(0, 4).map((event) => (
                      <div key={event.id} style={{ paddingLeft: "12px", borderLeft: "2px solid color-mix(in srgb, var(--brand-primary) 24%, var(--border-line))" }}>
                        <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--space-3)", fontSize: "var(--font-size-sm)" }}>
                          <strong>{translateUiToken(event.toStatus, copy)}</strong>
                          <span style={{ color: "var(--text-secondary)" }}>{event.occurredAt ? formatCompactDate(event.occurredAt) : copy("now", "刚刚")}</span>
                        </div>
                        {event.note ? <div style={{ marginTop: "4px", color: "var(--text-secondary)", fontSize: "var(--font-size-sm)" }}>{event.note}</div> : null}
                      </div>
                    ))
                  ) : (
                    <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)" }}>{copy("No stage events yet.", "暂无阶段事件。")}</div>
                  )}
                </div>
              </div>
            ) : null}
          </Panel>

          <Panel
            title={copy("Review requests", "待处理确认")}
            eyebrow={copy("Candidate scoped", "候选人维度")}
            description={copy("Candidate communication approvals stay here. Broader AI changes belong in the AI Review Center.", "候选人沟通相关确认保留在这里，范围更广的 AI 变更放到 AI Review Center。")}
          >
            {selectedThread ? <PendingRuntimeApprovals approvals={selectedThread.runtimeApprovals} pendingActionId={pendingActionId} onApprove={onApprove} onReject={onReject} /> : null}
          </Panel>
        </div>
      </div>
    </div>
  );
}
