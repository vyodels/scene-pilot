import React, { useMemo } from "react";
import { ProgressBars, StatusBadge, Timeline } from "../../components";
import { formatCompactDate } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { translateUiToken } from "../../lib/uiText";
import type { ApplicationRecord, DashboardSummary } from "../../lib/types";

interface DashboardViewProps {
  summary: DashboardSummary;
  onOpenCandidates?(): void;
  onOpenJdWorkspace?(): void;
  onOpenCommunications?(filter?: string, applicationId?: string): void;
  onOpenAiReview?(): void;
  onOpenAiStrategy?(): void;
}

type ApplicationLane = "review" | "followUp" | "resume" | "interview" | "decision" | "blocked" | "active";

interface ApplicationLaneMeta {
  tone: "positive" | "neutral" | "warning" | "critical";
}

const laneMeta: Record<ApplicationLane, ApplicationLaneMeta> = {
  review: { tone: "warning" },
  followUp: { tone: "warning" },
  resume: { tone: "warning" },
  interview: { tone: "positive" },
  decision: { tone: "positive" },
  blocked: { tone: "critical" },
  active: { tone: "neutral" },
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

const sectionStyle: React.CSSProperties = {
  display: "grid",
  gap: "var(--space-4)",
  padding: "var(--space-5)",
  border: "1px solid var(--border-line)",
  borderRadius: "var(--radius-lg)",
  background: "var(--bg-card)",
};

const panelHeaderStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "start",
  justifyContent: "space-between",
  gap: "var(--space-4)",
  flexWrap: "wrap",
};

const titleStyle: React.CSSProperties = {
  margin: 0,
  fontSize: "var(--font-size-lg)",
  lineHeight: "var(--line-height-tight)",
  fontWeight: "var(--font-weight-bold)",
  color: "var(--text-primary)",
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

const metricGridStyle: React.CSSProperties = {
  display: "grid",
  gap: "var(--space-3)",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
};

const metricCardStyle: React.CSSProperties = {
  display: "grid",
  gap: "var(--space-2)",
  padding: "var(--space-4)",
  border: "1px solid var(--border-line)",
  borderRadius: "var(--radius-md)",
  background: "var(--bg-card)",
};

const metricValueStyle: React.CSSProperties = {
  fontSize: "30px",
  lineHeight: 1,
  fontWeight: "var(--font-weight-bold)",
  color: "var(--text-primary)",
};

const metricCaptionStyle: React.CSSProperties = {
  margin: 0,
  color: "var(--text-secondary)",
  fontSize: "var(--font-size-sm)",
  lineHeight: "var(--line-height-base)",
};

const splitGridStyle: React.CSSProperties = {
  display: "grid",
  gap: "var(--space-4)",
  gridTemplateColumns: "minmax(0, 1.35fr) minmax(320px, 0.85fr)",
  alignItems: "start",
};

const candidateListStyle: React.CSSProperties = {
  display: "grid",
  gap: "var(--space-3)",
};

const candidateButtonStyle: React.CSSProperties = {
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

function normalize(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9\u4e00-\u9fff]+/gi, "");
}

function classifyApplication(application: ApplicationRecord): ApplicationLane {
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

function laneTone(lane: ApplicationLane): "positive" | "neutral" | "warning" | "critical" {
  return laneMeta[lane].tone;
}

function laneLabel(lane: ApplicationLane, copy: (en: string, zh: string) => string): string {
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

function metricTone(count: number): "positive" | "neutral" | "warning" {
  return count > 0 ? "warning" : "neutral";
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

function pickPlaybookLabel(playbook: DashboardSummary["playbooks"][number]): string {
  return `${playbook.name}${playbook.version ? ` · ${playbook.version}` : ""}`;
}

export function DashboardView({
  summary,
  onOpenCandidates,
  onOpenJdWorkspace,
  onOpenCommunications,
  onOpenAiReview,
  onOpenAiStrategy,
}: DashboardViewProps): JSX.Element {
  const { copy } = useI18n();

  const prioritizedApplications = useMemo(() => {
    return [...summary.applications].sort((left, right) => {
      const laneDiff =
        ({
          review: 0,
          followUp: 1,
          resume: 2,
          interview: 3,
          decision: 4,
          blocked: 5,
          active: 6,
        } satisfies Record<ApplicationLane, number>)[classifyApplication(left)] -
        ({
          review: 0,
          followUp: 1,
          resume: 2,
          interview: 3,
          decision: 4,
          blocked: 5,
          active: 6,
        } satisfies Record<ApplicationLane, number>)[classifyApplication(right)];
      if (laneDiff !== 0) {
        return laneDiff;
      }
      if (right.matchScore !== left.matchScore) {
        return right.matchScore - left.matchScore;
      }
      return left.person.name.localeCompare(right.person.name);
    });
  }, [summary.applications]);

  const laneCounts = useMemo(() => {
    return summary.applications.reduce<Record<ApplicationLane, number>>(
      (acc, application) => {
        acc[classifyApplication(application)] += 1;
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

  const attentionCount = laneCounts.review + laneCounts.followUp + laneCounts.resume + laneCounts.interview + laneCounts.decision;
  const pendingApprovals = summary.approvals.filter((item) => item.status === "pending");
  const activePlaybooks = summary.playbooks.filter((item) => item.status === "active");
  const topAlerts = summary.alerts.slice(0, 4).map((event) => ({
    ...event,
    label: presentRecruitingText(event.label.replace(/^Goal /, "Task "), copy),
    detail: presentRecruitingText(event.detail, copy),
  }));
  const focusMetrics: Array<{ label: string; value: string; caption: string; tone: "positive" | "neutral" | "warning" }> = [
    {
      label: copy("Needs review", "待审查"),
      value: String(laneCounts.review),
      caption: copy("New or triage candidates waiting for screening.", "新入队或待分流的候选人。"),
      tone: metricTone(laneCounts.review),
    },
    {
      label: copy("Waiting for reply", "等待回复"),
      value: String(laneCounts.followUp),
      caption: copy("Candidates that need a recruiter follow-up.", "需要招聘方继续跟进的候选人。"),
      tone: metricTone(laneCounts.followUp),
    },
    {
      label: copy("Waiting for resume", "等待简历"),
      value: String(laneCounts.resume),
      caption: copy("Import or source data still needs resume evidence.", "导入或来源数据仍缺少简历证据。"),
      tone: metricTone(laneCounts.resume),
    },
    {
      label: copy("Interview / decision", "面试 / 决策"),
      value: String(laneCounts.interview + laneCounts.decision),
      caption: copy("Candidates moving toward interviews or final decisions.", "进入面试或最终决策阶段的候选人。"),
      tone: metricTone(laneCounts.interview + laneCounts.decision),
    },
    {
      label: copy("Blocked", "阻塞"),
      value: String(laneCounts.blocked),
      caption: copy("Items that need a human intervention first.", "需要先有人介入处理的事项。"),
      tone: laneCounts.blocked > 0 ? "warning" : "neutral",
    },
  ];

  return (
    <div style={pageStyle}>
      <section style={heroStyle}>
        <div style={panelHeaderStyle}>
          <div style={{ display: "grid", gap: "var(--space-2)", maxWidth: "800px" }}>
            <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-xs)", letterSpacing: "0.16em", textTransform: "uppercase" }}>
              {copy("Recruiting home", "招聘首页")}
            </div>
            <h1 style={{ margin: 0, fontSize: "var(--font-size-lg)", lineHeight: "var(--line-height-tight)", fontWeight: "var(--font-weight-bold)" }}>
              {copy("Today at a glance", "今日待办一眼可见")}
            </h1>
            <p style={descriptionStyle}>
              {copy(
                "Focus here when you want to see which candidates need review, who is waiting for a reply, and where to jump next.",
                "你可以先在这里看清哪些候选人需要审查、谁在等待回复，以及下一步该去哪个页面。",
              )}
            </p>
          </div>

          <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap", justifyContent: "end" }}>
            <button type="button" style={primaryButtonStyle} onClick={onOpenCandidates}>
              {copy("Open pipeline", "打开候选人管道")}
            </button>
            <button type="button" style={actionButtonStyle} onClick={onOpenJdWorkspace}>
              {copy("JD workspace", "JD 工作区")}
            </button>
            <button type="button" style={actionButtonStyle} onClick={() => onOpenCommunications?.("active")}>
              {copy("Candidate follow-up", "候选人跟进")}
            </button>
          </div>
        </div>

        <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
          <StatusBadge tone={attentionCount > 0 ? "warning" : "positive"}>{copy(`${attentionCount} items need attention`, `${attentionCount} 项待处理`)}</StatusBadge>
          <StatusBadge tone={summary.agent.health === "healthy" ? "positive" : summary.agent.health === "warning" ? "warning" : "critical"}>
            {translateUiToken(summary.agent.status, copy)}
          </StatusBadge>
          <StatusBadge tone="neutral">{copy(summary.settings.platform.account, summary.settings.platform.account)}</StatusBadge>
          <StatusBadge tone={summary.settings.intranetEnabled ? "positive" : "neutral"}>
            {summary.settings.intranetEnabled ? copy("intranet sync on", "内网同步开启") : copy("local only", "仅本地")}
          </StatusBadge>
          <StatusBadge tone={summary.settings.desktopApprovalsOnly ? "warning" : "neutral"}>{copy("desktop approvals", "桌面确认")}</StatusBadge>
        </div>
      </section>

      <div style={metricGridStyle}>
        {focusMetrics.map((metric) => (
          <article key={metric.label} style={metricCardStyle}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--space-2)", alignItems: "start" }}>
              <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)" }}>{metric.label}</div>
              <StatusBadge tone={metric.tone}>{copy("Today", "今日")}</StatusBadge>
            </div>
            <div style={metricValueStyle}>{metric.value}</div>
            <p style={metricCaptionStyle}>{metric.caption}</p>
          </article>
        ))}
      </div>

      <div style={splitGridStyle}>
        <section style={sectionStyle}>
          <div style={panelHeaderStyle}>
            <div>
              <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-xs)", letterSpacing: "0.14em", textTransform: "uppercase" }}>
                {copy("Candidate queue", "候选人队列")}
              </div>
              <h2 style={titleStyle}>{copy("Highest-priority candidates", "最高优先级候选人")}</h2>
            </div>
            <StatusBadge tone="neutral">{copy(`${summary.applications.length} total`, `共 ${summary.applications.length} 条申请`)}</StatusBadge>
          </div>
          <p style={descriptionStyle}>
            {copy("Open a candidate from here to continue follow-up and communication in the candidate workspace.", "从这里打开候选人，继续在候选人工作台里完成审阅、跟进和沟通。")}
          </p>

          <div style={candidateListStyle}>
            {prioritizedApplications.slice(0, 6).map((application) => {
              const lane = classifyApplication(application);
              const stateSnapshot = application.stateSnapshot;
              return (
                <button
                  key={application.id}
                  type="button"
                  onClick={() => onOpenCommunications?.("candidate", application.id)}
                  style={candidateButtonStyle}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--space-3)", alignItems: "start", flexWrap: "wrap" }}>
                    <div style={{ display: "grid", gap: "var(--space-1)" }}>
                      <strong style={{ fontSize: "var(--font-size-base)" }}>{application.person.name}</strong>
                      <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)", lineHeight: "var(--line-height-base)" }}>
                        {application.person.title} · {application.jobDescription.title} · {application.person.location}
                      </div>
                    </div>
                    <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
                      <StatusBadge tone={laneTone(lane)}>{laneLabel(lane, copy)}</StatusBadge>
                      <StatusBadge tone="neutral">{copy(`score ${application.matchScore}`, `分数 ${application.matchScore}`)}</StatusBadge>
                    </div>
                  </div>
                  <div style={{ color: "var(--text-regular)", fontSize: "var(--font-size-sm)", lineHeight: "var(--line-height-base)" }}>
                    {application.nextAction}
                  </div>
                  <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
                    <StatusBadge tone={stateSnapshot?.contactAcquired ? "positive" : "warning"}>
                      {stateSnapshot?.contactAcquired ? copy("Contact ready", "联系方式已到位") : copy("Needs contact", "需要联系方式")}
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
          </div>
        </section>

        <section style={sectionStyle}>
          <div style={panelHeaderStyle}>
            <div>
              <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-xs)", letterSpacing: "0.14em", textTransform: "uppercase" }}>
                {copy("Signals", "信号")}
              </div>
              <h2 style={titleStyle}>{copy("Pipeline and blockers", "管道与阻塞")}</h2>
            </div>
          </div>
          <p style={descriptionStyle}>
            {copy("Use this column to check funnel balance, recent activity, and open review items.", "通过这一栏查看漏斗平衡、最近动态与待处理审查项。")}
          </p>
          <ProgressBars stages={summary.pipeline} />
          <div style={{ display: "grid", gap: "var(--space-3)" }}>
            {activePlaybooks.length ? (
              <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
                {activePlaybooks.slice(0, 3).map((playbook) => (
                  <StatusBadge key={playbook.id} tone="neutral">
                    {pickPlaybookLabel(playbook)}
                  </StatusBadge>
                ))}
              </div>
            ) : null}
            {summary.approvals.length ? (
              <div style={{ display: "grid", gap: "var(--space-2)" }}>
                {pendingApprovals.slice(0, 3).map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => {
                      if (item.relatedCandidateId) {
                        onOpenCommunications?.("candidate", item.relatedCandidateId);
                        return;
                      }
                      onOpenAiReview?.();
                    }}
                    style={{
                      ...candidateButtonStyle,
                      padding: "var(--space-3)",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--space-2)" }}>
                      <strong style={{ fontSize: "var(--font-size-sm)" }}>{presentRecruitingText(item.title, copy)}</strong>
                      <StatusBadge tone={item.status === "pending" ? "warning" : item.status === "approved" ? "positive" : "critical"}>
                        {translateUiToken(item.status, copy)}
                      </StatusBadge>
                    </div>
                    <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)", lineHeight: "var(--line-height-base)" }}>{presentRecruitingText(item.detail, copy)}</div>
                  </button>
                ))}
              </div>
            ) : (
              <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)" }}>{copy("No approval is waiting right now.", "当前没有待处理审批。")}</div>
            )}
          </div>
        </section>
      </div>

      <div style={splitGridStyle}>
        <section style={sectionStyle}>
          <div style={panelHeaderStyle}>
            <div>
              <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-xs)", letterSpacing: "0.14em", textTransform: "uppercase" }}>
                {copy("Latest activity", "最近动态")}
              </div>
              <h2 style={titleStyle}>{copy("Recent updates that matter", "值得关注的最新变化")}</h2>
            </div>
          </div>
          <Timeline events={topAlerts} />
        </section>

        <section style={sectionStyle}>
          <div style={panelHeaderStyle}>
            <div>
              <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-xs)", letterSpacing: "0.14em", textTransform: "uppercase" }}>
                {copy("Today’s shortcuts", "今日快捷入口")}
              </div>
              <h2 style={titleStyle}>{copy("Jump into the right workspace", "快速进入对应工作区")}</h2>
            </div>
          </div>
          <div style={{ display: "grid", gap: "var(--space-2)" }}>
            <button type="button" style={actionButtonStyle} onClick={onOpenCandidates}>
              {copy("Open candidate pipeline", "打开候选人管道")}
            </button>
            <button type="button" style={actionButtonStyle} onClick={onOpenJdWorkspace}>
              {copy("Open JD workspace", "打开 JD 工作区")}
            </button>
            <button type="button" style={actionButtonStyle} onClick={() => onOpenCommunications?.("active")}>
              {copy("Open candidate workspace", "打开候选人工作台")}
            </button>
            <button type="button" style={actionButtonStyle} onClick={onOpenAiReview}>
              {copy("Open AI review center", "打开 AI 审查中心")}
            </button>
            <button type="button" style={actionButtonStyle} onClick={onOpenAiStrategy}>
              {copy("Open AI strategy", "打开 AI 策略")}
            </button>
          </div>
          <div style={{ display: "grid", gap: "var(--space-2)", marginTop: "var(--space-2)" }}>
            <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)" }}>
              {copy("Current account", "当前账号")}: {summary.settings.platform.account}
            </div>
            <div style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-sm)" }}>
              {copy("Agent uptime", "运行时长")}: {summary.agent.uptime}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
