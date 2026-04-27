import React, { useEffect, useMemo, useState } from "react";
import type { ApplicationTransitionPayload, HumanActionDefinition, RecruitmentStateMachine } from "@recruit-agent/shared";
import { SectionTabs, StatusBadge } from "../../components";
import { formatCompactDate } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import {
  applicationScopedLabel,
  deriveHumanActionsForNode,
  getContactChannels,
  getContactDetails,
  getResumeArtifactSummaries,
  nodeTone,
} from "./kanbanUtils";
import { StatusTimeline } from "./StatusTimeline";
import type { ApplicationViewModel } from "./kanbanUtils";

interface CandidateDetailDrawerProps {
  open: boolean;
  record: ApplicationViewModel | null;
  stateMachine: RecruitmentStateMachine;
  initialTab?: DetailTab;
  onClose(): void;
  onTransition(applicationId: string, payload: ApplicationTransitionPayload): Promise<unknown> | void;
  onRequestOverride(): void;
}

export type DetailTab = "profile" | "resume" | "scores" | "history" | "contact";

interface PendingActionState {
  action: HumanActionDefinition;
  note: string;
}

function asObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function pickString(value: unknown): string | undefined {
  if (typeof value !== "string") {
    return undefined;
  }
  const trimmed = value.trim();
  return trimmed ? trimmed : undefined;
}

function contactChannelLabel(
  channel: string,
  copy: (en: string, zh: string) => string,
): string {
  switch (channel) {
    case "phone":
      return copy("Phone", "电话");
    case "wechat":
      return copy("WeChat", "微信");
    case "email":
      return copy("Email", "邮箱");
    default:
      return copy("Other", "其他");
  }
}

function summarizeSource(
  source: string,
  copy: (en: string, zh: string) => string,
): string {
  const trimmed = source.trim();
  const normalized = trimmed.toLowerCase();
  if (normalized === "profile") {
    return copy("Application profile", "投递记录资料");
  }
  if (normalized.startsWith("resume artifact")) {
    const detail = trimmed.replace(/^resume artifact/i, "").replace(/^[\s·-]+/, "").trim();
    return detail ? `${copy("Resume artifact", "简历制品")} · ${detail}` : copy("Resume artifact", "简历制品");
  }
  if (normalized === "operator") {
    return copy("Operator", "人工");
  }
  if (normalized === "agent") {
    return "Agent";
  }
  if (normalized === "system") {
    return copy("System", "系统");
  }
  if (normalized === "site") {
    return copy("Site import", "站点导入");
  }
  if (normalized === "unknown") {
    return "—";
  }
  return trimmed;
}

export function CandidateDetailDrawer({
  open,
  record,
  stateMachine,
  initialTab = "profile",
  onClose,
  onTransition,
  onRequestOverride,
}: CandidateDetailDrawerProps): JSX.Element | null {
  const { copy } = useI18n();
  const [activeTab, setActiveTab] = useState<DetailTab>("profile");
  const [pendingAction, setPendingAction] = useState<PendingActionState | null>(null);
  const [submittingKey, setSubmittingKey] = useState<string>();

  const currentNode = record?.currentNode;
  const actions = useMemo(
    () => (currentNode ? deriveHumanActionsForNode(currentNode, stateMachine) : []),
    [currentNode, stateMachine],
  );
  const aiScores = asObject(record?.application.aiScores);
  const personContactInfo = asObject(record?.application.person.contactInfo);
  const contactDetails = useMemo(
    () => (record ? getContactDetails(record.application, record.thread) : []),
    [record],
  );
  const contactChannels = useMemo(
    () => (record ? getContactChannels(record.application, record.thread) : []),
    [record],
  );
  const resumeArtifacts = useMemo(
    () => (record ? getResumeArtifactSummaries(record.thread) : []),
    [record],
  );
  const latestTransitionSource = record?.thread?.stateSnapshot.latestTransitionSource?.trim() || "";
  const latestInteraction = record?.thread?.runtimeInteractions?.[0];
  const onlineResumeText =
    pickString(personContactInfo.onlineResumeText) ?? pickString(personContactInfo.online_resume_text);
  const primaryResumePath =
    pickString(personContactInfo.resumePath) ?? pickString(personContactInfo.resume_path);

  useEffect(() => {
    if (open) {
      setActiveTab(initialTab);
    }
  }, [initialTab, open, record?.application.id]);

  if (!open || !record) {
    return null;
  }

  const submitAction = async (action: HumanActionDefinition, note?: string) => {
    const actionLabel = applicationScopedLabel(action.label);
    const key = `${record.application.id}:${action.toStatus}:${actionLabel}`;
    setSubmittingKey(key);
    try {
      await onTransition(record.application.id, {
        actor: "recruiter",
        toStatus: action.toStatus,
        trigger: actionLabel,
        note: note?.trim() || undefined,
        metadata: { initiated_from: "candidate_detail_drawer" },
      });
      setPendingAction(null);
    } finally {
      setSubmittingKey(undefined);
    }
  };

  return (
    <div className="drawer-backdrop">
      <aside className="drawer">
        <header className="drawer__header">
          <div>
            <div className="drawer__eyebrow">{copy("Application detail", "投递记录详情")}</div>
            <h2 className="drawer__title">{record.application.person.name}</h2>
            <p className="drawer__description">
              {record.application.person.title} · {record.application.person.location}
            </p>
          </div>
          <button type="button" className="drawer__close" onClick={onClose}>
            ×
          </button>
        </header>

        <div className="drawer__body">
          <div className="drawer__status-row">
            <StatusBadge tone={nodeTone(currentNode)}>{record.currentStatusLabel}</StatusBadge>
            {record.humanRequired ? <StatusBadge tone="warning">{copy("Waiting on you", "等待你操作")}</StatusBadge> : null}
          </div>

          <SectionTabs
            items={[
              { key: "profile", label: copy("Basic info", "基本信息") },
              { key: "resume", label: copy("Resume", "简历") },
              { key: "scores", label: copy("AI scores", "AI 评分") },
              { key: "history", label: copy("Status history", "状态历史") },
              { key: "contact", label: copy("Contact", "联系方式") },
            ]}
            active={activeTab}
            onChange={(key) => setActiveTab(key as DetailTab)}
          />

          {activeTab === "profile" ? (
            <div className="drawer__grid">
              <div><strong>{copy("Role", "应聘岗位")}</strong><span>{record.application.jobDescription.title}</span></div>
              <div><strong>{copy("Platform", "平台")}</strong><span>{record.application.platform}</span></div>
              <div><strong>{copy("Experience", "工作年限")}</strong><span>{record.application.person.experienceYears || "—"}</span></div>
              <div><strong>{copy("Deepest milestone", "最深里程碑")}</strong><span>{record.deepestMilestoneLabel ?? "—"}</span></div>
              <div className="drawer__full-row">
                <strong>{copy("Summary", "摘要")}</strong>
                <span>{record.application.summary || copy("No summary available.", "暂无摘要。")}</span>
              </div>
            </div>
          ) : null}

          {activeTab === "resume" ? (
            <div className="drawer__stack">
              <div className="drawer__card">
                <strong>{copy("Resume overview", "简历概览")}</strong>
                <div className="drawer__grid">
                  <div>
                    <strong>{copy("Resume status", "简历状态")}</strong>
                    <span>
                      {record.application.resumeAvailable
                        ? copy("Resume evidence is available.", "已有简历证据。")
                        : copy("Resume evidence is still missing.", "简历证据仍待补充。")}
                    </span>
                  </div>
                  <div>
                    <strong>{copy("Stored artifacts", "已入库制品")}</strong>
                    <span>
                      {resumeArtifacts.length
                        ? copy(`${resumeArtifacts.length} artifacts`, `共 ${resumeArtifacts.length} 个制品`)
                        : copy("No stored artifact yet", "暂无已入库制品")}
                    </span>
                  </div>
                  <div className="drawer__full-row">
                    <strong>{copy("Online profile summary", "在线资料摘要")}</strong>
                    <span>
                      {onlineResumeText || record.application.summary || copy("No online profile summary.", "暂无在线资料摘要。")}
                    </span>
                  </div>
                  <div className="drawer__full-row">
                    <strong>{copy("Primary stored path", "主落地路径")}</strong>
                    <span>{primaryResumePath || copy("No stored path exposed yet.", "暂未暴露主路径。")}</span>
                  </div>
                </div>
              </div>
              {resumeArtifacts.length ? (
                resumeArtifacts.map((artifact) => (
                  <div key={artifact.id} className="drawer__card">
                    <strong>{artifact.title || copy("Stored artifact", "已入库简历")}</strong>
                    <div className="drawer__grid">
                      <div>
                        <strong>{copy("Source", "来源")}</strong>
                        <span>{summarizeSource(artifact.source, copy)}</span>
                      </div>
                      <div>
                        <strong>{copy("Recorded at", "获取时间")}</strong>
                        <span>{artifact.recordedAt ? formatCompactDate(artifact.recordedAt) : "—"}</span>
                      </div>
                      <div className="drawer__full-row">
                        <strong>{copy("Artifact path", "制品路径")}</strong>
                        <span>{artifact.path || copy("Path has not been stored yet.", "尚未记录路径。")}</span>
                      </div>
                      {artifact.contactSummary ? (
                        <div className="drawer__full-row">
                          <strong>{copy("Contact found in artifact", "制品内联系方式")}</strong>
                          <span>{artifact.contactSummary}</span>
                        </div>
                      ) : null}
                      {artifact.excerpt ? (
                        <div className="drawer__full-row">
                          <strong>{copy("Extracted excerpt", "提取摘要")}</strong>
                          <span>{artifact.excerpt}</span>
                        </div>
                      ) : null}
                    </div>
                  </div>
                ))
              ) : (
                <div className="drawer__empty">
                  {record.application.resumeAvailable
                    ? copy("Resume is marked as available, but no stored artifact/path is exposed yet.", "当前已标记有简历，但还没有暴露出可展示的制品或路径。")
                    : copy("No offline resume artifacts yet.", "暂无线下简历制品。")}
                </div>
              )}
            </div>
          ) : null}

          {activeTab === "scores" ? (
            <div className="drawer__stack">
              <div className="drawer__grid">
                <div><strong>{copy("Online", "在线")}</strong><span>{typeof aiScores.overall === "number" ? `${Math.round(Number(aiScores.overall))}/100` : `${Math.round(record.application.matchScore)}/100`}</span></div>
                <div><strong>{copy("Offline", "线下")}</strong><span>{record.thread?.scorecards[0]?.scoreTotal ?? copy("Pending", "待评分")}</span></div>
              </div>
              {record.thread?.scorecards.length ? (
                record.thread.scorecards.map((scorecard) => (
                  <div key={scorecard.id} className="drawer__card">
                    <strong>{scorecard.source}</strong>
                    <p>{scorecard.summary || copy("No scorecard summary.", "暂无评分卡摘要。")}</p>
                  </div>
                ))
              ) : null}
              {record.thread?.assessments.length ? (
                record.thread.assessments.map((assessment) => (
                  <div key={assessment.id} className="drawer__card">
                    <strong>{assessment.assessmentType}</strong>
                    <p>{assessment.summary || copy("No assessment summary.", "暂无评估摘要。")}</p>
                  </div>
                ))
              ) : null}
            </div>
          ) : null}

          {activeTab === "history" ? (
            <StatusTimeline transitions={record.thread?.statusTransitions ?? []} stateMachine={stateMachine} />
          ) : null}

          {activeTab === "contact" ? (
            <div className="drawer__stack">
              <div className="drawer__card">
                <strong>{copy("Contact overview", "联系方式概览")}</strong>
                <div className="drawer__grid">
                  <div>
                    <strong>{copy("Masked summary", "脱敏摘要")}</strong>
                    <span>{record.contactSummary}</span>
                  </div>
                  <div>
                    <strong>{copy("Channels", "渠道")}</strong>
                    <span>
                      {contactChannels.length
                        ? contactChannels.map((channel) => contactChannelLabel(channel, copy)).join(" / ")
                        : "—"}
                    </span>
                  </div>
                  <div>
                    <strong>{copy("Contact status", "联系状态")}</strong>
                    <span>
                      {record.thread?.stateSnapshot.contactAcquired
                        ? copy("Contact has been acquired.", "联系方式已获取。")
                        : copy("Contact details are still missing.", "联系方式仍待补充。")}
                    </span>
                  </div>
                  <div>
                    <strong>{copy("Latest source", "最近来源")}</strong>
                    <span>{latestTransitionSource ? summarizeSource(latestTransitionSource, copy) : "—"}</span>
                  </div>
                </div>
              </div>
              {contactDetails.length ? (
                contactDetails.map((detail, index) => (
                  <div key={`${detail.channel}:${detail.value}:${index}`} className="drawer__card">
                    <strong>{contactChannelLabel(detail.channel, copy)}</strong>
                    <div className="drawer__grid">
                      <div>
                        <strong>{copy("Masked value", "脱敏值")}</strong>
                        <span>{detail.value}</span>
                      </div>
                      <div>
                        <strong>{copy("Source", "来源")}</strong>
                        <span>{summarizeSource(detail.source, copy)}</span>
                      </div>
                      <div className="drawer__full-row">
                        <strong>{copy("Recorded at", "记录时间")}</strong>
                        <span>{detail.recordedAt ? formatCompactDate(detail.recordedAt) : "—"}</span>
                      </div>
                    </div>
                  </div>
                ))
              ) : (
                <div className="drawer__empty">
                  {copy("No contact value is exposed yet. Only channel-level state is available.", "目前还没有可展示的联系方式值，只拿到了渠道级状态。")}
                </div>
              )}
              <div className="drawer__card">
                <strong>{copy("Profile source snapshot", "资料来源快照")}</strong>
                <div className="drawer__grid">
                  <div>
                    <strong>{copy("Platform", "平台")}</strong>
                    <span>{record.application.platform}</span>
                  </div>
                  <div>
                    <strong>{copy("Last activity", "最近活动")}</strong>
                    <span>{record.latestActivityAt ? formatCompactDate(record.latestActivityAt) : "—"}</span>
                  </div>
                  <div className="drawer__full-row">
                    <strong>{copy("Latest acquisition record", "最近获取记录")}</strong>
                    <span>
                      {latestInteraction
                        ? `${latestInteraction.title} · ${latestInteraction.effectSummary || latestInteraction.status}`
                        : copy("No runtime acquisition record yet.", "暂未记录运行时获取事件。")}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          ) : null}
        </div>

        <footer className="drawer__footer drawer__footer--spread">
          <div className="drawer__actions">
            {actions.map((action) => {
              const actionLabel = applicationScopedLabel(action.label);
              return (
                <button
                  key={actionLabel}
                  type="button"
                  className="drawer__button"
                  data-style={action.style}
                  disabled={submittingKey === `${record.application.id}:${action.toStatus}:${actionLabel}`}
                  onClick={() => {
                    if (action.requiresNote) {
                      setPendingAction({ action, note: "" });
                      return;
                    }
                    void submitAction(action);
                  }}
                >
                  {actionLabel}
                </button>
              );
            })}
          </div>
          {pendingAction ? (
            <div className="drawer__note-box">
              <strong>{applicationScopedLabel(pendingAction.action.label)}</strong>
              <textarea
                className="drawer__textarea"
                rows={3}
                value={pendingAction.note}
                onChange={(event) => setPendingAction({ ...pendingAction, note: event.target.value })}
                placeholder={copy("Add the note required by this action.", "请填写该动作要求的备注。")}
              />
              <div className="drawer__note-actions">
                <button type="button" className="drawer__button" onClick={() => setPendingAction(null)}>
                  {copy("Cancel", "取消")}
                </button>
                <button
                  type="button"
                  className="drawer__button"
                  data-style={pendingAction.action.style}
                  disabled={!pendingAction.note.trim() || submittingKey != null}
                  onClick={() => void submitAction(pendingAction.action, pendingAction.note)}
                >
                  {copy("Confirm", "确认")}
                </button>
              </div>
            </div>
          ) : null}
          <button type="button" className="drawer__button" onClick={onRequestOverride}>
            {copy("Manual status override…", "人工修改状态…")}
          </button>
        </footer>
      </aside>
    </div>
  );
}
