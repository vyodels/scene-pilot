import React, { useEffect, useMemo, useState } from "react";
import { Panel, StatusBadge } from "../../components";
import { formatCompactDate } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { theme } from "../../lib/theme";
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
  onTransitionState(
    candidateId: string,
    payload: {
      toStatus: string;
      phaseKey?: string;
      phaseLabel?: string;
      stageKey?: string;
      stageLabel?: string;
      note?: string;
      source?: string;
      actor?: string;
      metadata?: Record<string, unknown>;
      interviewRound?: number;
      contactChannels?: string[];
    },
  ): Promise<void> | void;
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

const buttonStyle: React.CSSProperties = {
  border: `1px solid ${theme.colors.border}`,
  borderRadius: "12px",
  background: "rgba(255,255,255,0.04)",
  color: theme.colors.text,
  padding: "9px 12px",
  cursor: "pointer",
  fontWeight: 700,
};

const inputStyle: React.CSSProperties = {
  width: "100%",
  borderRadius: "12px",
  border: `1px solid ${theme.colors.border}`,
  background: "rgba(7,12,22,0.9)",
  color: theme.colors.text,
  padding: "10px 12px",
  fontSize: "14px",
};

const textareaStyle: React.CSSProperties = {
  width: "100%",
  minHeight: "96px",
  borderRadius: "14px",
  border: `1px solid ${theme.colors.border}`,
  background: "rgba(7,12,22,0.9)",
  color: theme.colors.text,
  padding: "10px 12px",
  lineHeight: 1.6,
  resize: "vertical",
};

function bubbleStyle(direction: string): React.CSSProperties {
  if (direction === "outbound") {
    return {
      justifySelf: "end",
      background: "rgba(122,167,255,0.16)",
      border: "1px solid rgba(122,167,255,0.22)",
    };
  }
  if (direction === "inbound") {
    return {
      justifySelf: "start",
      background: "rgba(93,216,163,0.10)",
      border: "1px solid rgba(93,216,163,0.18)",
    };
  }
  return {
    justifySelf: "center",
    background: "rgba(255,255,255,0.05)",
    border: "1px solid rgba(255,255,255,0.10)",
  };
}

function statusTone(status: string): "positive" | "neutral" | "warning" | "critical" {
  if (/(rejected|cooldown|failed|critical)/i.test(status)) {
    return "critical";
  }
  if (/(waiting|pending|review|requested|schedule)/i.test(status)) {
    return "warning";
  }
  if (/(passed|received|completed|scheduled|acquired|offer)/i.test(status)) {
    return "positive";
  }
  return "neutral";
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
    return <div style={{ color: theme.colors.muted, fontSize: "13px" }}>{copy("No runtime confirmations are pending for this candidate.", "当前候选人没有待处理的运行时确认。")}</div>;
  }
  return (
    <div style={{ display: "grid", gap: "10px" }}>
      {approvals.map((approval) => (
        <article key={approval.id} style={{ borderRadius: "16px", border: `1px solid ${theme.colors.border}`, background: "rgba(255,255,255,0.03)", padding: "12px 14px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: "10px", alignItems: "start" }}>
            <div>
              <div style={{ fontWeight: 700 }}>{approval.title}</div>
              <div style={{ color: theme.colors.muted, fontSize: "13px", marginTop: "4px", lineHeight: 1.6 }}>{approval.detail}</div>
            </div>
            <StatusBadge tone={approval.status === "pending" ? "warning" : approval.status === "approved" ? "positive" : "critical"}>
              {translateUiToken(approval.status, copy)}
            </StatusBadge>
          </div>
          {approval.payload && Object.keys(approval.payload).length ? (
            <details style={{ marginTop: "10px" }}>
              <summary style={{ cursor: "pointer", color: theme.colors.muted, fontSize: "12px" }}>{copy("Show payload", "查看载荷")}</summary>
              <pre style={{ margin: "8px 0 0", whiteSpace: "pre-wrap", wordBreak: "break-word", color: "rgba(233,239,255,0.72)", fontSize: "11px", lineHeight: 1.6 }}>
                {JSON.stringify(approval.payload, null, 2)}
              </pre>
            </details>
          ) : null}
          {approval.status === "pending" ? (
            <div style={{ display: "flex", gap: "8px", marginTop: "12px" }}>
              <button type="button" onClick={() => void onApprove(approval.id)} disabled={pendingActionId === approval.id} style={buttonStyle}>
                {pendingActionId === approval.id ? copy("Working...", "处理中...") : copy("Approve", "确认")}
              </button>
              <button type="button" onClick={() => void onReject(approval.id)} disabled={pendingActionId === approval.id} style={{ ...buttonStyle, background: "rgba(255,122,122,0.12)", color: "#ffdede" }}>
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
    <article style={{ borderRadius: "14px", border: `1px solid ${theme.colors.border}`, background: "rgba(255,255,255,0.03)", padding: "12px 13px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: "8px", alignItems: "start" }}>
        <div>
          <strong>{item.assessmentType === "ai" ? copy("AI assessment", "AI 评估") : copy("Human assessment", "人工评估")}</strong>
          <div style={{ marginTop: "6px", color: theme.colors.muted, fontSize: "12px" }}>{item.stageKey ?? copy("No stage bound", "未绑定阶段")}</div>
        </div>
        <StatusBadge tone={statusTone(item.status)}>{translateUiToken(item.status, copy)}</StatusBadge>
      </div>
      <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", marginTop: "8px" }}>
        {item.decision ? <StatusBadge tone={statusTone(item.decision)}>{translateUiToken(item.decision, copy)}</StatusBadge> : null}
        {item.score != null ? <StatusBadge tone="neutral">{copy(`score ${item.score}`, `分数 ${item.score}`)}</StatusBadge> : null}
      </div>
      {item.summary ? <div style={{ marginTop: "8px", lineHeight: 1.6, fontSize: "13px" }}>{item.summary}</div> : null}
      <div style={{ marginTop: "8px", color: theme.colors.muted, fontSize: "12px" }}>{formatCompactDate(item.createdAt)}</div>
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
  const [statusFilter, setStatusFilter] = useState("all");
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
    if (preferredCandidateId && threads.some((item) => item.candidate.id === preferredCandidateId)) {
      setSelectedCandidateId(preferredCandidateId);
      return;
    }
    if (!selectedCandidateId || !threads.some((item) => item.candidate.id === selectedCandidateId)) {
      setSelectedCandidateId(threads[0].candidate.id);
    }
  }, [preferredCandidateId, selectedCandidateId, threads]);

  useEffect(() => {
    if (preferredStatusFilter) {
      setStatusFilter(preferredStatusFilter === "candidate" ? "all" : preferredStatusFilter);
    }
  }, [preferredStatusFilter]);

  const filteredThreads = useMemo(() => {
    switch (statusFilter) {
      case "waiting":
        return threads.filter((thread) => /(contact_required|contact_acquired|pending_communication|communicating|waiting_reply|resume_requested)/i.test(thread.candidate.status));
      case "active":
        return threads.filter((thread) => !/(rejected|cooldown)/i.test(thread.candidate.status));
      case "assessments":
        return threads.filter((thread) => /(assessment|review)/i.test(thread.candidate.status));
      case "interviews":
        return threads.filter((thread) => /(schedule|interview)/i.test(thread.candidate.status));
      default:
        return preferredCandidateId && preferredStatusFilter === "candidate"
          ? threads.filter((thread) => thread.candidate.id === preferredCandidateId)
          : threads;
    }
  }, [preferredCandidateId, preferredStatusFilter, statusFilter, threads]);

  const selectedThread = useMemo(
    () => filteredThreads.find((item) => item.candidate.id === selectedCandidateId) ?? filteredThreads[0] ?? null,
    [filteredThreads, selectedCandidateId],
  );

  const stageGroups = useMemo(() => {
    const workflowDefinition = (profile?.workflowDefinition ?? {}) as Record<string, unknown>;
    return Array.isArray(workflowDefinition.stage_groups)
      ? (workflowDefinition.stage_groups as Array<Record<string, unknown>>)
      : [];
  }, [profile]);

  useEffect(() => {
    if (!selectedThread) {
      setTransitionStatus("");
      setTransitionNote("");
      return;
    }
    setTransitionStatus(selectedThread.stateSnapshot.currentStageKey ?? selectedThread.candidate.status);
    setContactChannelsDraft(selectedThread.stateSnapshot.contactChannels.join(", "));
  }, [selectedThread]);

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
      toStatus: transitionStatus,
      stageKey: transitionStatus,
      stageLabel: transitionStatus,
      note: transitionNote.trim() || undefined,
      source: "operator",
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

  const rightColumn = selectedThread ? (
    <div style={{ display: "grid", gap: "18px" }}>
      <Panel
        title={copy("Candidate profile", "候选人资料")}
        eyebrow={copy("Scoped facts", "隔离事实")}
        description={copy("Communication, contact details, resume state, and assessments stay attached to this candidate only.", "沟通、联系方式、简历状态和评估都只绑定当前候选人。")}
      >
        <div style={{ display: "grid", gap: "10px" }}>
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
            <StatusBadge tone={statusTone(selectedThread.candidate.status)}>{translateUiToken(selectedThread.candidate.status, copy)}</StatusBadge>
            <StatusBadge tone="neutral">{selectedThread.candidate.jdTitle}</StatusBadge>
            <StatusBadge tone={selectedThread.stateSnapshot.contactAcquired ? "positive" : "warning"}>
              {selectedThread.stateSnapshot.contactAcquired ? copy("Contact acquired", "已拿到联系方式") : copy("Contact missing", "待拿联系方式")}
            </StatusBadge>
            <StatusBadge tone={selectedThread.candidate.resumeAvailable ? "positive" : "warning"}>
              {selectedThread.candidate.resumeAvailable ? copy("Resume received", "已收到简历") : copy("Resume pending", "待简历")}
            </StatusBadge>
          </div>
          <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.7 }}>
            {selectedThread.candidate.summary}
          </div>
          <div style={{ display: "grid", gap: "8px" }}>
            <div style={{ fontSize: "13px" }}>{copy("Contact channels", "联系方式")}: {selectedThread.stateSnapshot.contactChannels.length ? selectedThread.stateSnapshot.contactChannels.join(", ") : copy("none", "暂无")}</div>
            <div style={{ fontSize: "13px" }}>{copy("Phone", "手机号")}: {selectedThread.candidate.contactInfo && typeof selectedThread.candidate.contactInfo.phone === "string" ? selectedThread.candidate.contactInfo.phone : copy("unknown", "未知")}</div>
            <div style={{ fontSize: "13px" }}>{copy("WeChat", "微信")}: {selectedThread.candidate.contactInfo && typeof selectedThread.candidate.contactInfo.wechat === "string" ? selectedThread.candidate.contactInfo.wechat : copy("unknown", "未知")}</div>
            <div style={{ fontSize: "13px" }}>{copy("AI score", "AI 评分")}: {selectedThread.candidate.matchScore}</div>
            <div style={{ fontSize: "13px" }}>{copy("Match analysis", "匹配度分析")}: {selectedThread.candidate.nextAction}</div>
            <div style={{ fontSize: "13px" }}>{copy("Resume status", "简历状态")}: {translateUiToken(selectedThread.stateSnapshot.resumeStatus ?? "unknown", copy)}</div>
            <div style={{ fontSize: "13px" }}>{copy("Latest resume", "最近简历")}: {selectedThread.resumeArtifacts[0]?.fileName ?? copy("none", "暂无")}</div>
            <div style={{ fontSize: "13px" }}>{copy("Owner", "当前负责人")}: {selectedThread.assignments[0]?.assignee ?? copy("unassigned", "未分配")}</div>
          </div>
        </div>
      </Panel>

      <Panel
        title={copy("State transition", "状态流转")}
        eyebrow={copy("Operator override", "人工接管")}
        description={copy("The status machine is extensible. You can manually move a candidate to another stage and keep the full transition history.", "状态机可扩展。你可以手动把候选人切到任意阶段，并保留完整状态流转记录。")}
      >
        <div style={{ display: "grid", gap: "10px" }}>
          <label style={{ display: "grid", gap: "6px" }}>
            <span>{copy("Target status", "目标状态")}</span>
            <select value={transitionStatus} onChange={(event) => setTransitionStatus(event.target.value)} style={inputStyle}>
              {stageGroups.length
                ? stageGroups.map((group) => (
                    <optgroup key={String(group.id ?? group.name ?? "group")} label={String(group.name ?? group.id ?? "Stage group")}>
                      {Array.isArray(group.stages)
                        ? (group.stages as Array<Record<string, unknown>>).map((stage) => (
                            <option key={String(stage.key ?? stage.label)} value={String(stage.key ?? "")}>
                              {String(stage.label ?? stage.key ?? "")}
                            </option>
                          ))
                        : []}
                      {!Array.isArray(group.stages) && Array.isArray(group.default_rounds)
                        ? (group.default_rounds as Array<Record<string, unknown>>).flatMap((round) => {
                            const waitingKey = String(round.waiting_key ?? "");
                            const scheduledKey = String(round.scheduled_key ?? "");
                            const roundIndex = String(round.round ?? "");
                            return [
                              <option key={`${waitingKey}-${roundIndex}`} value={waitingKey}>
                                {copy(`Round ${roundIndex} waiting`, `等待预约第 ${roundIndex} 轮`)}
                              </option>,
                              <option key={`${scheduledKey}-${roundIndex}`} value={scheduledKey}>
                                {copy(`Round ${roundIndex} scheduled`, `第 ${roundIndex} 轮已预约`)}
                              </option>,
                            ];
                          })
                        : null}
                    </optgroup>
                  ))
                : selectedThread.availableStatuses.map((status) => (
                    <option key={status} value={status}>
                      {translateUiToken(status, copy)}
                    </option>
                  ))}
            </select>
          </label>
          <label style={{ display: "grid", gap: "6px" }}>
            <span>{copy("Contact channels", "联系方式渠道")}</span>
            <input value={contactChannelsDraft} onChange={(event) => setContactChannelsDraft(event.target.value)} style={inputStyle} placeholder={copy("phone, wechat", "phone, wechat")} />
          </label>
          <label style={{ display: "grid", gap: "6px" }}>
            <span>{copy("Interview round", "面试轮次")}</span>
            <input value={interviewRoundDraft} onChange={(event) => setInterviewRoundDraft(event.target.value)} style={inputStyle} />
          </label>
          <label style={{ display: "grid", gap: "6px" }}>
            <span>{copy("Operator note", "操作备注")}</span>
            <textarea value={transitionNote} onChange={(event) => setTransitionNote(event.target.value)} style={{ ...textareaStyle, minHeight: "80px" }} />
          </label>
          <button type="button" onClick={() => void handleTransition()} style={buttonStyle}>
            {copy("Apply transition", "应用流转")}
          </button>
        </div>
      </Panel>

      <Panel
        title={copy("Assessments", "评估")}
        eyebrow={copy("AI + human", "AI + 人工")}
        description={copy("AI assessment and human assessment are both stored and can be reviewed together.", "AI 评估和人工评估都会入库，并且可以一起查看。")}
      >
        <div style={{ display: "grid", gap: "12px" }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "10px" }}>
            <label style={{ display: "grid", gap: "6px" }}>
              <span>{copy("Type", "类型")}</span>
              <select value={assessmentType} onChange={(event) => setAssessmentType(event.target.value)} style={inputStyle}>
                <option value="manual">{copy("Human", "人工")}</option>
                <option value="ai">{copy("AI", "AI")}</option>
              </select>
            </label>
            <label style={{ display: "grid", gap: "6px" }}>
              <span>{copy("Decision", "结论")}</span>
              <select value={assessmentDecision} onChange={(event) => setAssessmentDecision(event.target.value)} style={inputStyle}>
                <option value="pass">{copy("Pass", "通过")}</option>
                <option value="review">{copy("Review", "待复核")}</option>
                <option value="reject">{copy("Reject", "淘汰")}</option>
              </select>
            </label>
          </div>
          <label style={{ display: "grid", gap: "6px" }}>
            <span>{copy("Score", "分数")}</span>
            <input value={assessmentScore} onChange={(event) => setAssessmentScore(event.target.value)} style={inputStyle} />
          </label>
          <label style={{ display: "grid", gap: "6px" }}>
            <span>{copy("Assessment summary", "评估摘要")}</span>
            <textarea value={assessmentSummary} onChange={(event) => setAssessmentSummary(event.target.value)} style={{ ...textareaStyle, minHeight: "84px" }} />
          </label>
          <button type="button" onClick={() => void handleAssessment()} style={buttonStyle}>
            {copy("Save assessment", "保存评估")}
          </button>
          <div style={{ display: "grid", gap: "10px" }}>
            {selectedThread.assessments.map((item) => (
              <AssessmentCard key={item.id} item={item} />
            ))}
          </div>
          <div style={{ display: "grid", gap: "8px" }}>
            <div style={{ display: "grid", gridTemplateColumns: "120px 96px minmax(0, 1fr)", gap: "8px", color: theme.colors.muted, fontSize: "12px" }}>
              <span>{copy("Scorecard", "评分卡")}</span>
              <span>{copy("Score", "分数")}</span>
              <span>{copy("Summary", "摘要")}</span>
            </div>
            {selectedThread.scorecards.slice(0, 4).map((item) => (
              <div key={item.id} style={{ display: "grid", gridTemplateColumns: "120px 96px minmax(0, 1fr)", gap: "8px", fontSize: "13px" }}>
                <span>{item.source}</span>
                <span>{item.scoreTotal ?? "-"}</span>
                <span style={{ color: theme.colors.muted }}>{item.summary ?? "-"}</span>
              </div>
            ))}
            {!selectedThread.scorecards.length ? <div style={{ color: theme.colors.muted, fontSize: "13px" }}>{copy("No scorecards yet.", "暂无评分卡。")}</div> : null}
          </div>
          <div style={{ display: "grid", gap: "8px" }}>
            <div style={{ display: "grid", gridTemplateColumns: "120px 100px minmax(0, 1fr)", gap: "8px", color: theme.colors.muted, fontSize: "12px" }}>
              <span>{copy("Decision", "评审结论")}</span>
              <span>{copy("Source", "来源")}</span>
              <span>{copy("Rationale", "理由")}</span>
            </div>
            {selectedThread.reviewDecisions.slice(0, 4).map((item) => (
              <div key={item.id} style={{ display: "grid", gridTemplateColumns: "120px 100px minmax(0, 1fr)", gap: "8px", fontSize: "13px" }}>
                <span>{translateUiToken(item.decision, copy)}</span>
                <span>{item.decisionSource}</span>
                <span style={{ color: theme.colors.muted }}>{item.rationale ?? "-"}</span>
              </div>
            ))}
            {!selectedThread.reviewDecisions.length ? <div style={{ color: theme.colors.muted, fontSize: "13px" }}>{copy("No review decisions yet.", "暂无评审结论。")}</div> : null}
          </div>
        </div>
      </Panel>

      <Panel
        title={copy("Structured facts", "结构化事实")}
        eyebrow={copy("Assignments · resume · sync", "负责人 · 简历 · 同步")}
        description={copy("These records are persisted under the candidate and stay available for isolated context loading.", "这些记录都会持久化到候选人名下，并用于隔离上下文加载。")}
      >
        <div style={{ display: "grid", gap: "12px" }}>
          <div style={{ display: "grid", gap: "8px" }}>
            <div style={{ display: "grid", gridTemplateColumns: "120px 120px minmax(0, 1fr)", gap: "8px", color: theme.colors.muted, fontSize: "12px" }}>
              <span>{copy("Assignee", "负责人")}</span>
              <span>{copy("Role", "角色")}</span>
              <span>{copy("Note", "备注")}</span>
            </div>
            {selectedThread.assignments.slice(0, 4).map((item) => (
              <div key={item.id} style={{ display: "grid", gridTemplateColumns: "120px 120px minmax(0, 1fr)", gap: "8px", fontSize: "13px" }}>
                <span>{item.assignee}</span>
                <span>{item.ownerRole}</span>
                <span style={{ color: theme.colors.muted }}>{item.note ?? "-"}</span>
              </div>
            ))}
          </div>
          <div style={{ display: "grid", gap: "8px" }}>
            <div style={{ display: "grid", gridTemplateColumns: "96px 120px minmax(0, 1fr)", gap: "8px", color: theme.colors.muted, fontSize: "12px" }}>
              <span>{copy("Type", "类型")}</span>
              <span>{copy("Source", "来源")}</span>
              <span>{copy("File", "文件")}</span>
            </div>
            {selectedThread.resumeArtifacts.slice(0, 4).map((item) => (
              <div key={item.id} style={{ display: "grid", gridTemplateColumns: "96px 120px minmax(0, 1fr)", gap: "8px", fontSize: "13px" }}>
                <span>{item.artifactType}</span>
                <span>{item.source}</span>
                <span style={{ color: theme.colors.muted }}>{item.fileName ?? item.filePath ?? "-"}</span>
              </div>
            ))}
          </div>
          <div style={{ display: "grid", gap: "8px" }}>
            <div style={{ display: "grid", gridTemplateColumns: "120px 100px minmax(0, 1fr)", gap: "8px", color: theme.colors.muted, fontSize: "12px" }}>
              <span>{copy("Destination", "目标")}</span>
              <span>{copy("Status", "状态")}</span>
              <span>{copy("External ref", "外部引用")}</span>
            </div>
            {selectedThread.syncRecords.slice(0, 4).map((item) => (
              <div key={item.id} style={{ display: "grid", gridTemplateColumns: "120px 100px minmax(0, 1fr)", gap: "8px", fontSize: "13px" }}>
                <span>{item.destination}</span>
                <span>{translateUiToken(item.status, copy)}</span>
                <span style={{ color: theme.colors.muted }}>{item.externalRef ?? "-"}</span>
              </div>
            ))}
          </div>
        </div>
      </Panel>

      <Panel
        title={copy("State timeline", "状态时间流")}
        eyebrow={copy("Stored history", "已存历史")}
        description={copy("Every transition stays attached to the candidate and remains available to the agent and operator.", "每次状态变更都会挂到候选人名下，并持续对 agent 和操作员可见。")}
      >
        <div style={{ display: "grid", gap: "10px", maxHeight: "320px", overflowY: "auto" }}>
          {selectedThread.stageEvents.length ? selectedThread.stageEvents.map((event) => (
            <article key={event.id} style={{ borderLeft: "2px solid rgba(122,167,255,0.35)", paddingLeft: "12px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: "8px" }}>
                <strong>{translateUiToken(event.toStatus, copy)}</strong>
                <span style={{ color: theme.colors.muted, fontSize: "12px" }}>{event.occurredAt ? formatCompactDate(event.occurredAt) : copy("now", "刚刚")}</span>
              </div>
              <div style={{ marginTop: "4px", color: theme.colors.muted, fontSize: "12px" }}>
                {event.fromStatus ? `${translateUiToken(event.fromStatus, copy)} -> ${translateUiToken(event.toStatus, copy)}` : translateUiToken(event.toStatus, copy)}
              </div>
              {event.note ? <div style={{ marginTop: "6px", fontSize: "13px", lineHeight: 1.6 }}>{event.note}</div> : null}
            </article>
          )) : <div style={{ color: theme.colors.muted }}>{copy("No state events yet.", "当前没有状态事件。")}</div>}
        </div>
      </Panel>

      <Panel title={copy("Runtime confirmations", "运行时确认")} eyebrow={copy("Candidate scoped", "候选人维度")} description={copy("Candidate communication confirmations stay in this window. Non-candidate evolution approvals belong in Evolution.", "候选人沟通确认留在这个窗口里，非候选人的演进审批放到 Evolution。")}>
        <PendingRuntimeApprovals approvals={selectedThread.runtimeApprovals} pendingActionId={pendingActionId} onApprove={onApprove} onReject={onReject} />
      </Panel>
    </div>
  ) : null;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "300px minmax(0, 1fr) 420px", gap: "18px" }}>
      <Panel title={copy("Candidate threads", "候选人沟通线程")} eyebrow={copy("Runtime inbox", "运行时收件箱")} description={copy("Each candidate keeps an isolated chat, isolated progress state, and isolated memory usage.", "每个候选人都有独立聊天、独立进度状态和独立 memory 使用边界。")}>
        <div style={{ display: "grid", gap: "10px" }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 128px", gap: "8px", marginBottom: "4px" }}>
            <div style={{ color: theme.colors.muted, fontSize: "12px", alignSelf: "center" }}>{copy("Click a count or candidate from elsewhere to jump into the filtered queue.", "点击其他页面的统计数字或候选人，可以直接跳到对应筛选列表。")}</div>
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} style={inputStyle}>
              <option value="all">{copy("All", "全部")}</option>
              <option value="waiting">{copy("Waiting communication", "待沟通")}</option>
              <option value="active">{copy("Active", "活跃")}</option>
              <option value="assessments">{copy("Assessments", "待评估")}</option>
              <option value="interviews">{copy("Interviews", "面试阶段")}</option>
            </select>
          </div>
          {filteredThreads.map((thread) => {
            const active = thread.candidate.id === selectedCandidateId;
            const pendingCount = thread.runtimeApprovals.filter((item) => item.status === "pending").length;
            return (
              <button
                key={thread.candidate.id}
                type="button"
                onClick={() => setSelectedCandidateId(thread.candidate.id)}
                style={{
                  cursor: "pointer",
                  textAlign: "left",
                  borderRadius: "14px",
                  border: `1px solid ${active ? "rgba(122,167,255,0.36)" : theme.colors.border}`,
                  background: active ? "rgba(122,167,255,0.12)" : "rgba(255,255,255,0.03)",
                  color: theme.colors.text,
                  padding: "12px 13px",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", gap: "8px", alignItems: "start" }}>
                  <strong>{thread.candidate.name}</strong>
                  {pendingCount ? <StatusBadge tone="warning">{pendingCount}</StatusBadge> : null}
                </div>
                <div style={{ color: theme.colors.muted, fontSize: "12px", marginTop: "6px", lineHeight: 1.6 }}>
                  {thread.candidate.jdTitle} · {translateUiToken(thread.candidate.status, copy)}
                </div>
                <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", marginTop: "8px" }}>
                  <StatusBadge tone={thread.stateSnapshot.contactAcquired ? "positive" : "warning"}>
                    {thread.stateSnapshot.contactAcquired ? copy("contact", "联系方式") : copy("need contact", "待联系方式")}
                  </StatusBadge>
                  <StatusBadge tone={thread.candidate.resumeAvailable ? "positive" : "warning"}>
                    {thread.candidate.resumeAvailable ? copy("resume", "简历") : copy("resume pending", "待简历")}
                  </StatusBadge>
                </div>
              </button>
            );
          })}
          {!filteredThreads.length ? <div style={{ color: theme.colors.muted, fontSize: "13px" }}>{copy("No candidates match the current filter.", "当前筛选下没有候选人。")}</div> : null}
        </div>
      </Panel>

      <Panel
        title={selectedThread?.candidate.name ?? copy("Conversation", "沟通详情")}
        eyebrow={copy("Candidate-isolated chat", "候选人隔离聊天")}
        description={selectedThread?.contextSummary ?? copy("Select a candidate to inspect the full conversation and take over the thread when needed.", "选择一个候选人查看完整沟通，并在需要时接管线程。")}
        actions={
          selectedThread ? (
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              <StatusBadge tone="neutral">{selectedThread.candidate.jdTitle}</StatusBadge>
              <StatusBadge tone={statusTone(selectedThread.candidate.status)}>{translateUiToken(selectedThread.candidate.status, copy)}</StatusBadge>
              <StatusBadge tone={selectedThread.runtimeApprovals.some((item) => item.status === "pending") ? "warning" : "positive"}>
                {copy(`${selectedThread.runtimeApprovals.filter((item) => item.status === "pending").length} pending`, `${selectedThread.runtimeApprovals.filter((item) => item.status === "pending").length} 个待确认`)}
              </StatusBadge>
            </div>
          ) : null
        }
      >
        {selectedThread ? (
          <div style={{ display: "grid", gap: "14px" }}>
            <div style={{ display: "grid", gap: "10px", maxHeight: "520px", overflowY: "auto", paddingRight: "4px" }}>
              {selectedThread.communicationLogs.length ? (
                selectedThread.communicationLogs.map((log) => (
                  <article
                    key={log.id}
                    style={{
                      ...bubbleStyle(log.direction),
                      maxWidth: "88%",
                      borderRadius: "16px",
                      padding: "10px 12px",
                      display: "grid",
                      gap: "4px",
                    }}
                  >
                    <div style={{ fontSize: "12px", color: theme.colors.muted }}>
                      {translateUiToken(log.direction, copy)} · {log.timestamp ? formatCompactDate(log.timestamp) : copy("now", "刚刚")}
                    </div>
                    <div style={{ lineHeight: 1.6 }}>{log.content}</div>
                  </article>
                ))
              ) : (
                <div style={{ color: theme.colors.muted }}>{copy("No messages yet.", "当前没有消息。")}</div>
              )}
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "140px 140px minmax(0, 1fr) auto", gap: "10px", alignItems: "end" }}>
              <label style={{ display: "grid", gap: "6px" }}>
                <span>{copy("Direction", "方向")}</span>
                <select value={direction} onChange={(event) => setDirection(event.target.value)} style={inputStyle}>
                  <option value="outbound">{copy("Outbound", "发出")}</option>
                  <option value="inbound">{copy("Inbound", "收到")}</option>
                  <option value="system">{copy("System", "系统")}</option>
                </select>
              </label>
              <label style={{ display: "grid", gap: "6px" }}>
                <span>{copy("Type", "类型")}</span>
                <select value={messageType} onChange={(event) => setMessageType(event.target.value)} style={inputStyle}>
                  <option value="text">{copy("Text", "文本")}</option>
                  <option value="note">{copy("Note", "备注")}</option>
                  <option value="approval">{copy("Approval", "确认")}</option>
                </select>
              </label>
              <label style={{ display: "grid", gap: "6px" }}>
                <span>{copy("Message", "消息")}</span>
                <textarea value={draft} onChange={(event) => setDraft(event.target.value)} style={textareaStyle} />
              </label>
              <button type="button" onClick={() => void handleSubmit()} style={buttonStyle}>
                {copy("Append", "追加记录")}
              </button>
            </div>
          </div>
        ) : (
          <div style={{ color: theme.colors.muted }}>{copy("No candidate selected.", "尚未选择候选人。")}</div>
        )}
      </Panel>

      {rightColumn ?? <div />}
    </div>
  );
}
