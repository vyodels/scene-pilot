import React, { useEffect, useMemo, useState } from "react";
import { ProgressBars, StatusBadge, Timeline } from "../../components";
import { formatCompactDate } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { translateUiToken } from "../../lib/uiText";
import type {
  AgentEvent,
  AgentQueueItem,
  AgentSnapshot,
  DashboardSummary,
  ExecutionGraphProjectionRecord,
  ExecutionTraceRecord,
  GoalSpecRecord,
  RuntimeEpisodeReplay,
  RuntimeWorkspaceData,
  SyncBacklogItem,
  SyncStatusSnapshot,
} from "../../lib/types";

interface WorkbenchViewProps {
  summary: DashboardSummary;
  data: RuntimeWorkspaceData;
  agent: AgentSnapshot;
  events: AgentEvent[];
  selectedEpisodeId?: string;
  replay?: RuntimeEpisodeReplay | null;
  syncStatus?: SyncStatusSnapshot | null;
  syncBacklog?: SyncBacklogItem[];
  queueItems?: AgentQueueItem[];
  goals?: GoalSpecRecord[];
  traces?: ExecutionTraceRecord[];
  graphs?: ExecutionGraphProjectionRecord[];
  runningAction?: boolean;
  syncingAction?: boolean;
  onOpenCommunications?(filter?: string, applicationId?: string): void;
  onOpenJdWorkspace?(): void;
  onOpenAiReview?(): void;
}

type ApplicationLane = "review" | "followUp" | "resume" | "interview" | "decision" | "blocked" | "active";

const laneOrder: Record<ApplicationLane, number> = {
  review: 0,
  followUp: 1,
  resume: 2,
  interview: 3,
  decision: 4,
  blocked: 5,
  active: 6,
};

function normalize(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9\u4e00-\u9fff]+/gi, "");
}

function classifyApplicationLane(application: DashboardSummary["applications"][number]): ApplicationLane {
  const status = normalize(`${application.currentStatus} ${application.stageKey} ${application.nextAction} ${application.summary}`);
  if (/(rejected|cooldown|blocked|archived)/.test(status)) {
    return "blocked";
  }
  if (/(offer|hired|accepted|decision|pass|passed|selected)/.test(status)) {
    return "decision";
  }
  if (/(interview|schedule|scheduled|onsite|screeningcall|phoneinterview)/.test(status)) {
    return "interview";
  }
  if (!application.resumeAvailable || /(resume_requested|resume_pending|waiting_resume|needresume)/.test(status)) {
    return "resume";
  }
  if (/(contact_required|contact_needed|waiting_reply|pending_communication|communicating|outreach|followup)/.test(status)) {
    return "followUp";
  }
  if (/(review|screen|assessment|triage|new|pending)/.test(status)) {
    return "review";
  }
  return "active";
}

function applicationLaneTone(lane: ApplicationLane): "positive" | "neutral" | "warning" | "critical" {
  switch (lane) {
    case "blocked":
      return "critical";
    case "review":
    case "followUp":
    case "resume":
      return "warning";
    case "interview":
    case "decision":
      return "positive";
    default:
      return "neutral";
  }
}

function applicationLaneLabel(lane: ApplicationLane, copy: (en: string, zh: string) => string): string {
  switch (lane) {
    case "review":
      return copy("Needs review", "待审查");
    case "followUp":
      return copy("Waiting for reply", "待回复");
    case "resume":
      return copy("Waiting for resume", "待简历");
    case "interview":
      return copy("Interview queue", "面试阶段");
    case "decision":
      return copy("Decision queue", "决策阶段");
    case "blocked":
      return copy("Blocked", "阻塞");
    default:
      return copy("Active", "推进中");
  }
}

function presentRecruitingText(text: string, copy: (en: string, zh: string) => string): string {
  const cleaned = text
    .trim()
    .replace(/^Review template candidate for\s*/i, copy("Candidate review: ", "候选人待复核："))
    .replace(/^Goal intake failed to compile an executable plan:\s*/i, copy("Plan generation failed: ", "计划生成失败："))
    .replace(/^Runtime execution completed for recruiting\.?\s*/i, "")
    .replace(/\s+/g, " ")
    .trim();
  return cleaned || copy("System update", "系统更新");
}

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

const sectionStyle: React.CSSProperties = {
  display: "grid",
  gap: "var(--space-4)",
  padding: "var(--space-5)",
  border: "1px solid var(--border-line)",
  borderRadius: "var(--radius-lg)",
  background: "var(--bg-card)",
};

const splitStyle: React.CSSProperties = {
  display: "grid",
  gap: "var(--space-4)",
  gridTemplateColumns: "minmax(0, 1.2fr) minmax(320px, 0.8fr)",
  alignItems: "start",
};

const panelHeaderStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "start",
  justifyContent: "space-between",
  gap: "var(--space-3)",
  flexWrap: "wrap",
};

const titleStyle: React.CSSProperties = {
  margin: 0,
  fontSize: "var(--font-size-lg)",
  lineHeight: "var(--line-height-tight)",
  fontWeight: "var(--font-weight-bold)",
};

const descriptionStyle: React.CSSProperties = {
  margin: 0,
  color: "var(--text-secondary)",
  fontSize: "var(--font-size-sm)",
  lineHeight: "var(--line-height-base)",
};

const actionButtonStyle: React.CSSProperties = {
  minHeight: "32px",
  border: "1px solid var(--border-input)",
  borderRadius: "var(--radius-sm)",
  background: "var(--bg-card)",
  color: "var(--text-primary)",
  padding: "0 var(--space-4)",
  fontWeight: "var(--font-weight-medium)",
  cursor: "pointer",
};

const primaryButtonStyle: React.CSSProperties = {
  ...actionButtonStyle,
  borderColor: "var(--brand-primary)",
  background: "var(--brand-primary)",
  color: "var(--text-inverse)",
};

const queueGridStyle: React.CSSProperties = {
  display: "grid",
  gap: "var(--space-3)",
};

const queueButtonStyle: React.CSSProperties = {
  width: "100%",
  textAlign: "left",
  border: "1px solid var(--border-line)",
  borderRadius: "var(--radius-md)",
  background: "var(--bg-subtle)",
  padding: "var(--space-4)",
  color: "var(--text-primary)",
  cursor: "pointer",
  display: "grid",
  gap: "var(--space-2)",
};

const filterButtonStyle: React.CSSProperties = {
  minHeight: "32px",
  border: "1px solid var(--border-line)",
  borderRadius: "var(--radius-full)",
  background: "var(--bg-card)",
  color: "var(--text-secondary)",
  padding: "0 var(--space-3)",
  fontSize: "var(--font-size-sm)",
  fontWeight: "var(--font-weight-medium)",
  cursor: "pointer",
};

export function WorkbenchView({
  summary,
  data,
  agent,
  events,
  selectedEpisodeId,
  replay,
  syncStatus,
  syncBacklog = [],
  queueItems = [],
  goals = [],
  traces = [],
  graphs = [],
  runningAction,
  syncingAction,
  onOpenCommunications,
  onOpenJdWorkspace,
  onOpenAiReview,
}: WorkbenchViewProps): JSX.Element {
  const { copy } = useI18n();
  const [statusFilter, setStatusFilter] = useState<ApplicationLane | "all">("all");
  const [selectedApplicationId, setSelectedApplicationId] = useState<string | undefined>(summary.applications[0]?.id);

  const rankedApplications = useMemo(() => {
    return [...summary.applications].sort((left, right) => {
      const laneDiff = laneOrder[classifyApplicationLane(left)] - laneOrder[classifyApplicationLane(right)];
      if (laneDiff !== 0) {
        return laneDiff;
      }
      if (right.matchScore !== left.matchScore) {
        return right.matchScore - left.matchScore;
      }
      return left.person.name.localeCompare(right.person.name);
    });
  }, [summary.applications]);

  const filteredApplications = useMemo(() => {
    if (statusFilter === "all") {
      return rankedApplications;
    }
    return rankedApplications.filter((application) => classifyApplicationLane(application) === statusFilter);
  }, [rankedApplications, statusFilter]);

  useEffect(() => {
    if (!filteredApplications.length) {
      setSelectedApplicationId(undefined);
      return;
    }
    if (!selectedApplicationId || !filteredApplications.some((application) => application.id === selectedApplicationId)) {
      setSelectedApplicationId(filteredApplications[0].id);
    }
  }, [filteredApplications, selectedApplicationId]);

  const selectedApplication = filteredApplications.find((application) => application.id === selectedApplicationId) ?? null;
  const selectedLane = selectedApplication ? classifyApplicationLane(selectedApplication) : null;

  const queueCounts = useMemo(() => {
    return summary.applications.reduce<Record<ApplicationLane, number>>(
      (acc, application) => {
        acc[classifyApplicationLane(application)] += 1;
        return acc;
      },
      {
        review: 0,
        followUp: 0,
        resume: 0,
        interview: 0,
        decision: 0,
        blocked: 0,
        active: 0,
      },
    );
  }, [summary.applications]);

  const activityTimeline = useMemo(
    () =>
      events.slice(-8).map((event) => ({
        id: event.id,
        label: translateUiToken(event.source, copy),
        detail: event.message,
        at: event.at,
        tone:
          event.level === "error"
            ? ("critical" as const)
            : event.level === "warning"
              ? ("warning" as const)
              : event.level === "success"
                ? ("positive" as const)
                : ("neutral" as const),
      })),
    [copy, events],
  );

  const latestGoal = goals[0] ?? null;
  const latestTrace = traces[0] ?? null;
  const latestGraph = graphs[0] ?? null;
  const latestEpisode = data.episodes.find((episode) => episode.id === selectedEpisodeId) ?? data.episodes[0] ?? null;

  const activeRequests = queueItems.filter((item) => item.status !== "completed").slice(0, 4);
  const pendingSync = syncBacklog.filter((item) => item.status !== "completed").slice(0, 4);

  return (
    <div style={pageStyle}>
      <section style={heroStyle}>
        <div style={panelHeaderStyle}>
          <div style={{ display: "grid", gap: "var(--space-2)", maxWidth: "820px" }}>
            <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-xs)", letterSpacing: "0.16em", textTransform: "uppercase" }}>
              {copy("Candidate pipeline", "候选人管道")}
            </div>
            <h1 style={{ margin: 0, fontSize: "var(--font-size-lg)", lineHeight: "var(--line-height-tight)", fontWeight: "var(--font-weight-bold)" }}>
              {copy("Queue-first candidate work", "以队列为中心的候选人工作台")}
            </h1>
            <p style={descriptionStyle}>
              {copy(
                "Use this page to keep the queue moving: review candidates, send them forward, and keep the next action visible.",
                "在这个页面里你可以持续推进队列：审查候选人、推动下一步，并始终看见下一步动作。",
              )}
            </p>
          </div>

          <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap", justifyContent: "end" }}>
            <button type="button" style={primaryButtonStyle} onClick={() => onOpenCommunications?.("active")}>
              {copy("Open workspace", "打开候选人工作台")}
            </button>
            <button type="button" style={actionButtonStyle} onClick={onOpenJdWorkspace}>
              {copy("JD workspace", "JD 工作区")}
            </button>
            <button type="button" style={actionButtonStyle} onClick={onOpenAiReview}>
              {copy("Review center", "审查中心")}
            </button>
          </div>
        </div>

        <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
          <StatusBadge tone={summary.agent.health === "healthy" ? "positive" : summary.agent.health === "warning" ? "warning" : "critical"}>
            {translateUiToken(summary.agent.status, copy)}
          </StatusBadge>
          <StatusBadge tone={queueCounts.review > 0 ? "warning" : "positive"}>{copy(`${queueCounts.review} need review`, `${queueCounts.review} 待审查`)}</StatusBadge>
          <StatusBadge tone={queueCounts.followUp > 0 ? "warning" : "neutral"}>{copy(`${queueCounts.followUp} need follow-up`, `${queueCounts.followUp} 待跟进`)}</StatusBadge>
          <StatusBadge tone={queueCounts.resume > 0 ? "warning" : "neutral"}>{copy(`${queueCounts.resume} need resume`, `${queueCounts.resume} 待简历`)}</StatusBadge>
          <StatusBadge tone={syncStatus?.remoteAvailable ? "positive" : "neutral"}>
            {syncStatus?.remoteAvailable ? copy("sync available", "同步可用") : copy("local only", "仅本地")}
          </StatusBadge>
        </div>
      </section>

      <div style={{ display: "grid", gap: "var(--space-3)", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
        {[
          {
            label: copy("Active candidates", "活跃候选人"),
            value: String(queueCounts.review + queueCounts.followUp + queueCounts.resume + queueCounts.interview + queueCounts.decision + queueCounts.active),
            caption: copy("Candidates ready to move forward", "可继续推进的候选人"),
          },
          {
            label: copy("Interview / decision", "面试 / 决策"),
            value: String(queueCounts.interview + queueCounts.decision),
            caption: copy("Near-term hiring actions", "短期内需要处理的招聘动作"),
          },
          {
            label: copy("Blocked items", "阻塞事项"),
            value: String(queueCounts.blocked),
            caption: copy("Need a human decision first", "需要先有人介入"),
          },
          {
            label: copy("System tasks", "系统任务"),
            value: String(activeRequests.length + pendingSync.length),
            caption: copy("Open queue and sync work", "待处理的队列与同步工作"),
          },
        ].map((metric) => (
          <article
            key={metric.label}
            style={{
              display: "grid",
              gap: "var(--space-2)",
              padding: "var(--space-4)",
              border: "1px solid var(--border-line)",
              borderRadius: "var(--radius-md)",
              background: "var(--bg-card)",
            }}
          >
            <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)" }}>{metric.label}</div>
            <div style={{ fontSize: "30px", lineHeight: 1, fontWeight: "var(--font-weight-bold)" }}>{metric.value}</div>
            <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)", lineHeight: "var(--line-height-base)" }}>{metric.caption}</div>
          </article>
        ))}
      </div>

      <div style={splitStyle}>
        <section style={sectionStyle}>
          <div style={panelHeaderStyle}>
            <div>
              <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-xs)", letterSpacing: "0.14em", textTransform: "uppercase" }}>
                {copy("Filter queue", "筛选队列")}
              </div>
              <h2 style={titleStyle}>{copy("Candidates to process now", "当前要处理的候选人")}</h2>
            </div>
            <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
              {(["all", "review", "followUp", "resume", "interview", "decision", "blocked"] as const).map((lane) => (
                <button
                  key={lane}
                  type="button"
                  onClick={() => setStatusFilter(lane)}
                  style={{
                    ...filterButtonStyle,
                    borderColor: statusFilter === lane ? "var(--brand-primary)" : "var(--border-line)",
                    color: statusFilter === lane ? "var(--brand-primary)" : "var(--text-secondary)",
                    background: statusFilter === lane ? "var(--brand-primary-soft)" : "var(--bg-card)",
                  }}
                >
                  {lane === "all" ? copy("All", "全部") : applicationLaneLabel(lane, copy)}
                </button>
              ))}
            </div>
          </div>

          <div style={queueGridStyle}>
            {filteredApplications.map((application) => {
              const lane = classifyApplicationLane(application);
              return (
                <button
                  key={application.id}
                  type="button"
                  onClick={() => setSelectedApplicationId(application.id)}
                  style={{
                    ...queueButtonStyle,
                    borderColor: application.id === selectedApplicationId ? "var(--brand-primary)" : "var(--border-line)",
                    background: application.id === selectedApplicationId ? "var(--brand-primary-soft)" : "var(--bg-subtle)",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--space-3)", flexWrap: "wrap", alignItems: "start" }}>
                    <div style={{ display: "grid", gap: "var(--space-1)" }}>
                      <strong style={{ fontSize: "var(--font-size-base)" }}>{application.person.name}</strong>
                      <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)", lineHeight: "var(--line-height-base)" }}>
                        {application.person.title} · {application.jobDescription.title} · {application.person.location}
                      </div>
                    </div>
                    <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
                      <StatusBadge tone={applicationLaneTone(lane)}>{applicationLaneLabel(lane, copy)}</StatusBadge>
                      <StatusBadge tone="neutral">{copy(`score ${application.matchScore}`, `分数 ${application.matchScore}`)}</StatusBadge>
                    </div>
                  </div>
                  <div style={{ color: "var(--text-regular)", fontSize: "var(--font-size-sm)", lineHeight: "var(--line-height-base)" }}>
                    {application.nextAction}
                  </div>
                  <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
                    <StatusBadge tone={application.stateSnapshot?.contactAcquired ? "positive" : "warning"}>
                      {application.stateSnapshot?.contactAcquired ? copy("Contact ready", "联系方式已到位") : copy("Needs contact", "需要联系方式")}
                    </StatusBadge>
                    <StatusBadge tone={application.resumeAvailable ? "positive" : "warning"}>
                      {application.resumeAvailable ? copy("Resume ready", "简历已到位") : copy("Resume pending", "简历待补")}
                    </StatusBadge>
                    {application.person.tags.slice(0, 3).map((tag) => (
                      <StatusBadge key={tag} tone="neutral">
                        {tag}
                      </StatusBadge>
                    ))}
                  </div>
                </button>
              );
            })}
            {!filteredApplications.length ? <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)" }}>{copy("No candidates match the current filter.", "当前筛选没有候选人。")}</div> : null}
          </div>
        </section>

        <section style={sectionStyle}>
          <div style={panelHeaderStyle}>
            <div>
              <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-xs)", letterSpacing: "0.14em", textTransform: "uppercase" }}>
                {copy("Selected candidate", "当前候选人")}
              </div>
              <h2 style={titleStyle}>{selectedApplication?.person.name ?? copy("Pick a candidate", "请选择候选人")}</h2>
            </div>
            {selectedApplication ? <StatusBadge tone={applicationLaneTone(selectedLane ?? "active")}>{applicationLaneLabel(selectedLane ?? "active", copy)}</StatusBadge> : null}
          </div>

          {selectedApplication ? (
            <div style={{ display: "grid", gap: "var(--space-4)" }}>
              <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
                <StatusBadge tone="neutral">{selectedApplication.jobDescription.title}</StatusBadge>
                <StatusBadge tone="neutral">{selectedApplication.person.location}</StatusBadge>
                <StatusBadge tone={selectedApplication.resumeAvailable ? "positive" : "warning"}>
                  {selectedApplication.resumeAvailable ? copy("Resume ready", "简历已到位") : copy("Resume pending", "简历待补")}
                </StatusBadge>
                <StatusBadge tone={selectedApplication.stateSnapshot?.contactAcquired ? "positive" : "warning"}>
                  {selectedApplication.stateSnapshot?.contactAcquired ? copy("Contact ready", "联系方式已到位") : copy("Contact missing", "联系方式缺失")}
                </StatusBadge>
              </div>

              <div style={{ display: "grid", gap: "var(--space-2)" }}>
                <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)" }}>
                  {copy("Current next step", "当前下一步")}
                </div>
                <div style={{ fontSize: "var(--font-size-base)", lineHeight: "var(--line-height-base)" }}>{selectedApplication.nextAction}</div>
              </div>

              <div style={{ display: "grid", gap: "var(--space-2)" }}>
                <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)" }}>
                  {copy("Candidate summary", "候选人摘要")}
                </div>
                <div style={{ color: "var(--text-regular)", fontSize: "var(--font-size-sm)", lineHeight: "var(--line-height-base)" }}>
                  {selectedApplication.summary}
                </div>
              </div>

              <div style={{ display: "grid", gap: "var(--space-2)" }}>
                <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)" }}>{copy("Signals", "信号")}</div>
                <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
                  {selectedApplication.person.tags.map((tag) => (
                    <StatusBadge key={tag} tone="neutral">
                      {tag}
                    </StatusBadge>
                  ))}
                </div>
              </div>

              <div style={{ display: "grid", gap: "var(--space-2)" }}>
                <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)" }}>
                  {copy("Quick actions", "快捷操作")}
                </div>
                <div style={{ display: "grid", gap: "var(--space-2)" }}>
                  <button type="button" style={primaryButtonStyle} onClick={() => onOpenCommunications?.("candidate", selectedApplication.id)}>
                    {copy("Open workspace", "打开候选人工作台")}
                  </button>
                  <button type="button" style={actionButtonStyle} onClick={onOpenJdWorkspace}>
                    {copy("Open JD workspace", "打开 JD 工作区")}
                  </button>
                </div>
              </div>

              <div style={{ display: "grid", gap: "var(--space-2)" }}>
                <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)" }}>{copy("Recruiter notes", "招聘备注")}</div>
                <div style={{ fontSize: "var(--font-size-sm)", color: "var(--text-regular)", lineHeight: "var(--line-height-base)" }}>
                  {copy(
                    "Keep the candidate card open in the workspace if you need to send a message, adjust the state, or add an assessment.",
                    "如果需要发消息、调整状态或补充评估，请在候选人工作台里打开这张卡。",
                  )}
                </div>
              </div>
            </div>
          ) : (
            <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)" }}>{copy("No candidate selected.", "尚未选择候选人。")}</div>
          )}
        </section>
      </div>

      <div style={splitStyle}>
        <section style={sectionStyle}>
          <div style={panelHeaderStyle}>
            <div>
              <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-xs)", letterSpacing: "0.14em", textTransform: "uppercase" }}>
                {copy("Pipeline snapshot", "管道概览")}
              </div>
              <h2 style={titleStyle}>{copy("Current funnel shape", "当前漏斗形态")}</h2>
            </div>
          </div>
          <ProgressBars stages={summary.pipeline} />
          <div style={{ display: "grid", gap: "var(--space-2)" }}>
            <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)" }}>
              {copy("Queue depth", "队列深度")}: {agent.queueDepth}
            </div>
            <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)" }}>
              {copy("Sync status", "同步状态")}:
              {" "}
              {syncStatus ? copy(syncStatus.remoteAvailable ? "available" : "offline", syncStatus.remoteAvailable ? "可用" : "离线") : copy("unknown", "未知")}
            </div>
            {syncStatus ? (
              <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)" }}>
                {copy("Pending sync", "待同步")}: {syncStatus.pendingCount}
              </div>
            ) : null}
          </div>
        </section>

        <section style={sectionStyle}>
          <div style={panelHeaderStyle}>
            <div>
              <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-xs)", letterSpacing: "0.14em", textTransform: "uppercase" }}>
                {copy("Recent actions", "最近动作")}
              </div>
              <h2 style={titleStyle}>{copy("System work log", "系统工作记录")}</h2>
            </div>
          </div>
          <div style={{ display: "grid", gap: "var(--space-3)" }}>
            {latestGoal ? (
              <article style={queueButtonStyle}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--space-2)", flexWrap: "wrap" }}>
                  <strong>{latestGoal.title}</strong>
                  <StatusBadge tone={/blocked|failed/i.test(latestGoal.status) ? "warning" : "neutral"}>{translateUiToken(latestGoal.status, copy)}</StatusBadge>
                </div>
                <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)", lineHeight: "var(--line-height-base)" }}>
                  {presentRecruitingText(latestGoal.summary ?? latestGoal.goalText, copy)}
                </div>
              </article>
            ) : null}

            {latestEpisode ? (
              <article style={queueButtonStyle}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--space-2)", flexWrap: "wrap" }}>
                  <strong>{copy("Latest activity record", "最近活动记录")}</strong>
                  <StatusBadge tone={/(confirmed|completed)/i.test(latestEpisode.status) ? "positive" : /(pending|awaiting|running)/i.test(latestEpisode.status) ? "warning" : "critical"}>
                    {translateUiToken(latestEpisode.status, copy)}
                  </StatusBadge>
                </div>
                <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)", lineHeight: "var(--line-height-base)" }}>
                  {presentRecruitingText(latestEpisode.resultSummary ?? copy("No summary yet.", "暂无摘要"), copy)}
                </div>
              </article>
            ) : null}

            {latestTrace ? (
              <article style={queueButtonStyle}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--space-2)", flexWrap: "wrap" }}>
                  <strong>{copy("Latest execution note", "最近执行记录")}</strong>
                  <StatusBadge tone="neutral">{translateUiToken(latestTrace.status, copy)}</StatusBadge>
                </div>
                <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)", lineHeight: "var(--line-height-base)" }}>
                  {presentRecruitingText(latestTrace.summary ?? latestTrace.title, copy)}
                </div>
                {latestGraph?.renderedText ? (
                  <pre
                    style={{
                      margin: 0,
                      marginTop: "var(--space-2)",
                      padding: "var(--space-3)",
                      borderRadius: "var(--radius-sm)",
                      background: "var(--bg-page)",
                      overflowX: "auto",
                      fontFamily: "var(--font-mono)",
                      fontSize: "var(--font-size-xs)",
                      color: "var(--text-regular)",
                    }}
                  >
                    {latestGraph.renderedText}
                  </pre>
                ) : null}
              </article>
            ) : null}

            <details style={{ border: "1px solid var(--border-line)", borderRadius: "var(--radius-md)", padding: "var(--space-3)", background: "var(--bg-subtle)" }}>
              <summary style={{ cursor: "pointer", fontWeight: "var(--font-weight-medium)" }}>{copy("Open queue and sync items", "展开队列与同步项")}</summary>
              <div style={{ display: "grid", gap: "var(--space-3)", marginTop: "var(--space-3)" }}>
                {activeRequests.length ? (
                  <div style={{ display: "grid", gap: "var(--space-2)" }}>
                    {activeRequests.map((item) => (
                      <article key={item.taskId} style={queueButtonStyle}>
                        <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--space-2)" }}>
                          <strong>{item.taskType}</strong>
                          <StatusBadge tone="neutral">{item.status}</StatusBadge>
                        </div>
                        <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)" }}>
                          {item.applicationId ?? item.personId ?? copy("global request", "全局请求")} · {copy(`priority ${item.priority}`, `优先级 ${item.priority}`)}
                        </div>
                      </article>
                    ))}
                  </div>
                ) : null}
                {pendingSync.length ? (
                  <div style={{ display: "grid", gap: "var(--space-2)" }}>
                    {pendingSync.map((item) => (
                      <article key={item.id} style={queueButtonStyle}>
                        <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--space-2)" }}>
                          <strong>{item.entityType}</strong>
                          <StatusBadge tone={item.status === "pending" ? "warning" : item.status === "failed" ? "critical" : "positive"}>
                            {item.status}
                          </StatusBadge>
                        </div>
                        <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)", lineHeight: "var(--line-height-base)" }}>{item.payloadSummary}</div>
                      </article>
                    ))}
                  </div>
                ) : null}
                {!activeRequests.length && !pendingSync.length ? (
                  <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)" }}>{copy("No background items are waiting.", "当前没有等待处理的后台项。")}</div>
                ) : null}
              </div>
            </details>
          </div>
        </section>
      </div>

      <section style={sectionStyle}>
        <div style={panelHeaderStyle}>
          <div>
            <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-xs)", letterSpacing: "0.14em", textTransform: "uppercase" }}>
              {copy("Recent activity", "最近活动")}
            </div>
            <h2 style={titleStyle}>{copy("Signals that changed today", "今天发生变化的信号")}</h2>
          </div>
        </div>
        <Timeline events={activityTimeline} />
      </section>
    </div>
  );
}
