import React, { useEffect, useMemo, useRef, useState } from "react";
import type { ApplicationTransitionPayload, HumanActionDefinition, RecruitmentStateMachine } from "@recruit-agent/shared";
import { FormTextarea, StatusBadge, ToolbarInput, ToolbarRefreshButton, ToolbarSelect } from "../../components";
import { apiClient } from "../../lib/api";
import { formatChineseMessageTime, formatCompactDate } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { CandidateDetailDrawer, type DetailTab } from "../kanban-shared/CandidateDetailDrawer";
import { ChatMessageFeed } from "../kanban-shared/ChatMessageFeed";
import { ManualStatusOverrideDrawer } from "../kanban-shared/ManualStatusOverrideDrawer";
import { StatusTimeline } from "../kanban-shared/StatusTimeline";
import {
  ApplicationRecordCard,
  ApplicationScoreCard,
  CandidateAvatar,
  FollowUpCollapsiblePanel,
  FollowUpInfoCard,
  ScoreBars,
  type ScoreMetric,
} from "../kanban-shared/ApplicationFollowUpPrimitives";
import {
  applicationScopedLabel,
  deriveHumanActionsForNode,
  getResumeArtifactSummaries,
  nodeTone,
  type ApplicationViewModel,
} from "../kanban-shared/kanbanUtils";

type WorkspaceTab = "chat" | "records" | "interview" | "feedback" | "notes";
type SidePanelKey =
  | "aiScore"
  | "onlineScore"
  | "offlineScore"
  | "currentRole"
  | "onlineResume"
  | "offlineResume"
  | "deliveryHistory"
  | "statusHistory"
  | "quickActions";
type SidebarStatusFilter = string;
type CommunicationTemplateKey = "application_greeting" | "job_share" | "wechat_request";

interface ApplicationFollowUpWorkspaceProps {
  applications: ApplicationViewModel[];
  selectedApplicationId?: string;
  stateMachine: RecruitmentStateMachine;
  onSelectApplication(applicationId: string): void;
  onOpenFullCockpit(applicationId: string): void;
  onOpenDashboard(): void;
  onRefresh?(): Promise<unknown> | void;
  onCreateEntry(
    applicationId: string,
    payload: { direction: string; content: string; messageType?: string; platform?: string },
  ): Promise<unknown> | void;
  onTransition(applicationId: string, payload: ApplicationTransitionPayload): Promise<unknown> | void;
}

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

function pickNumber(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
}

function clampScore(value: number | undefined, fallback = 0): number {
  const resolved = value ?? fallback;
  return Math.max(0, Math.min(100, Math.round(resolved)));
}

function pickScore(source: Record<string, unknown>, keys: string[]): number | undefined {
  for (const key of keys) {
    const value = pickNumber(source[key]);
    if (value != null) {
      return value;
    }
  }
  return undefined;
}

function scoreText(score: number | undefined): string | number {
  return score == null ? "—" : score;
}

function qualityLabel(score: number | undefined, copy: (en: string, zh: string) => string): string {
  if (score == null) {
    return copy("Not available", "待获取");
  }
  if (score >= 85) {
    return copy("Excellent", "优秀");
  }
  if (score >= 70) {
    return copy("Good", "良好");
  }
  if (score >= 55) {
    return copy("Watch", "关注");
  }
  return copy("Pending", "待完善");
}

function scoreFromRecord(record: ApplicationViewModel): number | undefined {
  const aiScores = asObject(record.application.aiScores);
  const explicitScore = pickScore(aiScores, ["overall", "total", "score"]);
  if (explicitScore != null) {
    return clampScore(explicitScore);
  }
  return undefined;
}

function optionalScore(source: Record<string, unknown>, keys: string[]): number | undefined {
  const value = pickScore(source, keys);
  return value != null ? clampScore(value) : undefined;
}

function scoreMetrics(
  record: ApplicationViewModel,
  copy: (en: string, zh: string) => string,
): ScoreMetric[] {
  const aiScores = asObject(record.application.aiScores);
  const scorecard = record.thread?.scorecards[0];
  const dimensionScores = asObject(scorecard?.dimensionScores);
  const metrics: ScoreMetric[] = [
    {
      label: copy("Role match", "岗位匹配度"),
      value: optionalScore(aiScores, ["roleMatch", "role_match", "job_match"]) ?? optionalScore(dimensionScores, ["roleMatch", "role_match"]),
    },
    {
      label: copy("Resume match", "履历匹配度"),
      value: optionalScore(aiScores, ["resumeMatch", "resume_match", "experience_match"]) ?? optionalScore(dimensionScores, ["resumeMatch", "resume_match"]),
    },
    {
      label: copy("Stability", "稳定性匹配度"),
      value: optionalScore(aiScores, ["stability", "stability_match"]) ?? optionalScore(dimensionScores, ["stability"]),
    },
    {
      label: copy("Potential", "潜力评分"),
      value: optionalScore(aiScores, ["potential", "potential_score"]) ?? optionalScore(dimensionScores, ["potential"]),
    },
  ];
  return metrics;
}

function onlineResumeScore(record: ApplicationViewModel): number | undefined {
  const aiScores = asObject(record.application.aiScores);
  const explicitScore = pickScore(aiScores, ["onlineResume", "online_resume", "online_resume_score", "resume"]);
  if (explicitScore != null) {
    return clampScore(explicitScore);
  }
  return undefined;
}

function offlineResumeScore(record: ApplicationViewModel): number | undefined {
  const scorecard = record.thread?.scorecards[0];
  return scorecard?.scoreTotal != null ? clampScore(scorecard.scoreTotal) : undefined;
}

function offlineResumeMetrics(record: ApplicationViewModel, copy: (en: string, zh: string) => string): ScoreMetric[] {
  const scorecard = record.thread?.scorecards[0];
  const dimensionScores = asObject(scorecard?.dimensionScores);
  return [
    {
      label: copy("Content match", "内容匹配度"),
      value: optionalScore(dimensionScores, ["contentMatch", "content_match", "content"]),
    },
    {
      label: copy("Information completeness", "信息完整度"),
      value: optionalScore(dimensionScores, ["informationCompleteness", "information_completeness", "completeness"]),
    },
    {
      label: copy("Key skills", "关键技能覆盖"),
      value: optionalScore(dimensionScores, ["keySkills", "key_skills", "skills"]),
    },
  ];
}

function renderFactValue(value: unknown): string {
  if (value == null || value === "") {
    return "—";
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

function pickFirstString(...values: unknown[]): string | undefined {
  for (const value of values) {
    const picked = pickString(value);
    if (picked) {
      return picked;
    }
  }
  return undefined;
}

function compactValue(value: string | number | null | undefined): string {
  if (value == null || value === "") {
    return "—";
  }
  return String(value);
}

function structuredFactsFromResumeSnapshot(value: unknown): Record<string, unknown> {
  const snapshot = asObject(value);
  return asObject(snapshot.structured_facts ?? snapshot.structuredFacts);
}

function numberFact(value: unknown): number | null {
  const numberValue = Number(value);
  return Number.isFinite(numberValue) && numberValue > 0 ? numberValue : null;
}

function ProfileFact({ label, value }: { label: string; value: React.ReactNode }): JSX.Element {
  return (
    <span className="application-followup-profile__fact">
      <strong>{label}</strong>
      <em>{value || "—"}</em>
    </span>
  );
}

function avatarUrlFromContactInfo(contactInfo: unknown): string | undefined {
  const record = asObject(contactInfo);
  return pickFirstString(
    record.avatarUrl,
    record.avatar_url,
    record.photoUrl,
    record.photo_url,
    record.imageUrl,
    record.image_url,
  );
}

function ageText(age: number | null | undefined): string {
  return age ? `${age}岁` : "—";
}

function educationText(education: string | null | undefined): string {
  return education || "—";
}

function experienceText(years: number | null | undefined, experience?: string | null): string {
  return years ? `${years}年` : experience || "—";
}

export function ApplicationFollowUpWorkspace({
  applications,
  selectedApplicationId,
  stateMachine,
  onSelectApplication,
  onOpenFullCockpit,
  onOpenDashboard,
  onRefresh,
  onCreateEntry,
  onTransition,
}: ApplicationFollowUpWorkspaceProps): JSX.Element {
  const { copy } = useI18n();
  const [sidebarSearch, setSidebarSearch] = useState("");
  const [sidebarStatusFilter, setSidebarStatusFilter] = useState<SidebarStatusFilter>("all");
  const [workspaceTab, setWorkspaceTab] = useState<WorkspaceTab>("chat");
  const [expandedPanels, setExpandedPanels] = useState<Record<SidePanelKey, boolean>>({
    aiScore: true,
    onlineScore: true,
    offlineScore: true,
    currentRole: false,
    onlineResume: false,
    offlineResume: false,
    deliveryHistory: false,
    statusHistory: false,
    quickActions: false,
  });
  const [draft, setDraft] = useState("");
  const [composerInputHeight, setComposerInputHeight] = useState(38);
  const [sending, setSending] = useState(false);
  const [renderingTemplate, setRenderingTemplate] = useState<CommunicationTemplateKey | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailTab, setDetailTab] = useState<DetailTab>("profile");
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [pendingAction, setPendingAction] = useState<PendingActionState | null>(null);
  const [runningActionKey, setRunningActionKey] = useState<string>();
  const composerTextareaRef = useRef<HTMLTextAreaElement | null>(null);

  const selectedRecord =
    applications.find((item) => item.application.id === selectedApplicationId) ??
    applications[0] ??
    null;

  useEffect(() => {
    setDraft("");
    setPendingAction(null);
  }, [selectedRecord?.application.id]);

  useEffect(() => {
    const textarea = composerTextareaRef.current;
    if (!textarea) {
      return;
    }
    textarea.style.height = "38px";
    const nextHeight = Math.min(Math.max(textarea.scrollHeight, 38), 120);
    textarea.style.height = `${nextHeight}px`;
    textarea.style.overflowY = textarea.scrollHeight > 120 ? "auto" : "hidden";
    setComposerInputHeight(nextHeight);
  }, [draft, selectedRecord?.application.id]);

  const filteredApplications = useMemo(() => {
    const keyword = sidebarSearch.trim().toLowerCase();
    return applications
      .filter((item) => {
        if (sidebarStatusFilter !== "all" && item.displayStatus !== sidebarStatusFilter) {
          return false;
        }
        if (!keyword) {
          return true;
        }
        return [
          item.application.person.name,
          item.application.person.title,
          item.application.person.location,
          item.application.jobDescription.title,
          item.currentStatusLabel,
          item.contactSummary,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase()
          .includes(keyword);
      })
      .sort((left, right) => {
        const rightTime = right.latestActivityAt ?? right.application.lastContactedAt ?? right.application.id;
        const leftTime = left.latestActivityAt ?? left.application.lastContactedAt ?? left.application.id;
        return rightTime.localeCompare(leftTime);
      });
  }, [applications, sidebarSearch, sidebarStatusFilter]);

  const sidebarStatusOptions = useMemo(() => {
    const optionByStatus = new Map<string, string>();
    for (const item of applications) {
      optionByStatus.set(item.displayStatus, item.displayStatusLabel || item.currentStatusLabel || item.displayStatus);
    }
    return Array.from(optionByStatus.entries()).sort((left, right) => left[1].localeCompare(right[1]));
  }, [applications]);

  if (!selectedRecord) {
    return (
      <section className="application-followup-workspace application-followup-workspace--empty">
        {copy("No data yet.", "还没有数据哦")}
      </section>
    );
  }

  const person = selectedRecord.application.person;
  const job = selectedRecord.application.jobDescription;
  const aiScore = scoreFromRecord(selectedRecord);
  const onlineScore = onlineResumeScore(selectedRecord);
  const offlineScore = offlineResumeScore(selectedRecord);
  const aiQuality = qualityLabel(aiScore, copy);
  const onlineQuality = qualityLabel(onlineScore, copy);
  const offlineQuality = qualityLabel(offlineScore, copy);
  const hasAiScore = aiScore != null;
  const hasOnlineScore = onlineScore != null;
  const hasOfflineScore = offlineScore != null;
  const metrics = scoreMetrics(selectedRecord, copy);
  const offlineMetrics = offlineResumeMetrics(selectedRecord, copy);
  const currentActions = selectedRecord.currentNode
    ? deriveHumanActionsForNode(selectedRecord.currentNode, stateMachine)
    : [];
  const resumeArtifacts = getResumeArtifactSummaries(selectedRecord.thread);
  const facts = asObject(selectedRecord.thread?.facts);
  const contactInfo = asObject(person.contactInfo);
  const resumeSnapshot = asObject(selectedRecord.application.resumeSnapshot);
  const structuredResumeFacts = structuredFactsFromResumeSnapshot(resumeSnapshot);
  const profilePhoto = avatarUrlFromContactInfo(contactInfo);
  const profileGender = pickFirstString(contactInfo.gender, contactInfo.sex, facts.gender, facts.sex);
  const profileAge = person.age ?? numberFact(structuredResumeFacts.age);
  const profileEducation = person.education || pickFirstString(structuredResumeFacts.education);
  const structuredExperienceYears = numberFact(structuredResumeFacts.experienceYears ?? structuredResumeFacts.experience_years);
  const structuredExperienceText = pickFirstString(structuredResumeFacts.experienceText, structuredResumeFacts.experience_text);
  const profileWorkStatus =
    pickFirstString(contactInfo.workStatus, contactInfo.work_status, facts.workStatus, facts.work_status) ??
    pickFirstString(structuredResumeFacts.workStatus, structuredResumeFacts.work_status);
  const profilePhone = pickFirstString(
    contactInfo.phone,
    contactInfo.mobile,
    contactInfo.telephone,
    contactInfo.maskedPhone,
    contactInfo.masked_phone,
  );
  const profileEmail = pickFirstString(contactInfo.email, contactInfo.mail);
  const profileSchool = pickFirstString(contactInfo.school, contactInfo.university, contactInfo.college, facts.school, facts.university);
  const profileMajor = pickFirstString(
    contactInfo.major,
    contactInfo.majorName,
    contactInfo.major_name,
    contactInfo.profession,
    contactInfo.specialty,
    contactInfo.speciality,
    facts.major,
    facts.profession,
  );
  const profileDistrict = pickFirstString(contactInfo.district, contactInfo.area, contactInfo.address, facts.district);
  const profileCurrentCompany = pickFirstString(
    contactInfo.company,
    contactInfo.currentCompany,
    contactInfo.current_company,
    facts.company,
    facts.currentCompany,
  );
  const profileCurrentRole = pickFirstString(contactInfo.currentRole, contactInfo.current_role, person.title);
  const profileDepartment = pickFirstString(
    contactInfo.department,
    contactInfo.businessUnit,
    contactInfo.business_unit,
    facts.department,
    facts.businessUnit,
    job.department,
  );
  const profileExpectedRole = pickFirstString(
    contactInfo.expectedRole,
    contactInfo.expected_role,
    contactInfo.targetRole,
    contactInfo.target_role,
    job.title,
  );
  const profileSource = pickFirstString(contactInfo.source, contactInfo.channel, selectedRecord.application.platform);
  const profileAvailability = pickFirstString(contactInfo.availability, contactInfo.availableAt, contactInfo.available_at);
  const profileUpdatedAt = selectedRecord.latestActivityAt ? formatChineseMessageTime(selectedRecord.latestActivityAt) : "—";
  const interviewPlan = asObject(selectedRecord.thread?.stateSnapshot.interviewPlan);
  const hasMessages = Boolean(selectedRecord.thread?.communicationLogs.length);

  const openDetail = (tab: DetailTab) => {
    setDetailTab(tab);
    setDetailOpen(true);
  };

  const togglePanel = (panel: SidePanelKey) => {
    setExpandedPanels((current) => ({ ...current, [panel]: !current[panel] }));
  };

  const sendMessage = async (content: string, messageType = "text") => {
    const trimmed = content.trim();
    if (!trimmed) {
      return;
    }
    setSending(true);
    try {
      await onCreateEntry(selectedRecord.application.id, {
        direction: "outbound",
        content: trimmed,
        messageType,
        platform: selectedRecord.application.platform,
      });
      setDraft("");
    } finally {
      setSending(false);
    }
  };

  const renderTemplate = async (templateKey: CommunicationTemplateKey) => {
    setRenderingTemplate(templateKey);
    try {
      return await apiClient.renderCommunicationTemplate(templateKey, {
        applicationId: selectedRecord.application.id,
      });
    } finally {
      setRenderingTemplate(null);
    }
  };

  const applyTemplateToDraft = async (templateKey: CommunicationTemplateKey) => {
    const rendered = await renderTemplate(templateKey);
    if (rendered.content.trim()) {
      setDraft(rendered.content);
    }
  };

  const sendTemplateMessage = async (templateKey: CommunicationTemplateKey) => {
    const rendered = await renderTemplate(templateKey);
    if (rendered.content.trim()) {
      await sendMessage(rendered.content, rendered.messageType);
    }
  };

  const submitHumanAction = async (action: HumanActionDefinition, note?: string) => {
    const actionLabel = applicationScopedLabel(action.label);
    const key = `${actionLabel}:${action.toStatus}`;
    setRunningActionKey(key);
    try {
      await onTransition(selectedRecord.application.id, {
        actor: "recruiter",
        toStatus: action.toStatus,
        trigger: actionLabel,
        note: note?.trim() || undefined,
        metadata: { initiated_from: "application_followup_workspace" },
      });
      setPendingAction(null);
    } finally {
      setRunningActionKey(undefined);
    }
  };

  const refresh = async () => {
    if (!onRefresh) {
      return;
    }
    setRefreshing(true);
    try {
      await onRefresh();
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <section className="application-followup-workspace">
      <aside className="application-followup-workspace__records">
        <button type="button" className="application-followup-dashboard-link" onClick={onOpenDashboard}>
          <span className="application-followup-dashboard-link__icon" aria-hidden="true">▣</span>
          <strong>{copy("Data board", "数据看板")}</strong>
          <span aria-hidden="true">›</span>
        </button>

        <div className="application-followup-records__title-row">
          <strong>{copy("In follow-up", "沟通中")} ({filteredApplications.length})</strong>
          <ToolbarSelect
            value={sidebarStatusFilter}
            onChange={(event) => setSidebarStatusFilter(event.target.value as SidebarStatusFilter)}
            aria-label={copy("Record filter", "投递记录筛选")}
          >
            <option value="all">{copy("All status filters", "全部状态筛选")}</option>
            {sidebarStatusOptions.map(([status, label]) => (
              <option key={status} value={status}>{label}</option>
            ))}
          </ToolbarSelect>
        </div>

        <label className="application-followup-records__search">
          <ToolbarInput
            value={sidebarSearch}
            onChange={(event) => setSidebarSearch(event.target.value)}
            aria-label={copy("Search application", "搜索投递记录")}
            placeholder={copy("Search applications", "搜索投递记录")}
          />
        </label>

        <div className="application-followup-records__list">
          {filteredApplications.map((item) => {
            const itemStructuredFacts = structuredFactsFromResumeSnapshot(item.application.resumeSnapshot);
            const itemExperienceYears =
              item.application.person.experienceYears ??
              numberFact(itemStructuredFacts.experienceYears ?? itemStructuredFacts.experience_years);
            const itemExperienceText = pickFirstString(itemStructuredFacts.experienceText, itemStructuredFacts.experience_text);
            return (
              <ApplicationRecordCard
                key={item.application.id}
                name={item.application.person.name}
                avatarUrl={avatarUrlFromContactInfo(item.application.person.contactInfo)}
                time={item.latestActivityAt ? formatChineseMessageTime(item.latestActivityAt) : "—"}
                location={compactValue(item.application.person.location)}
                age={ageText(item.application.person.age ?? numberFact(itemStructuredFacts.age))}
                experienceYears={experienceText(itemExperienceYears, itemExperienceText)}
                education={educationText(item.application.person.education || pickFirstString(itemStructuredFacts.education))}
                jobTitle={item.application.jobDescription.title || "—"}
                jobLocation={compactValue(item.application.jobDescription.location)}
                statusLabel={item.currentStatusLabel}
                statusTone={nodeTone(item.currentNode)}
                active={item.application.id === selectedRecord.application.id}
                attention={item.humanRequired}
                onClick={() => onSelectApplication(item.application.id)}
              />
            );
          })}
        </div>
      </aside>

      <main className="application-followup-workspace__main">
        <section className="application-followup-profile">
          <CandidateAvatar name={person.name} imageUrl={profilePhoto} />
          <div className="application-followup-profile__identity">
            <div className="application-followup-profile__title-row">
              <h2>{person.name}</h2>
              <StatusBadge tone={nodeTone(selectedRecord.currentNode)}>{selectedRecord.currentStatusLabel}</StatusBadge>
              {selectedRecord.humanRequired ? <StatusBadge tone="warning">{copy("Waiting on you", "等待人工")}</StatusBadge> : null}
              <span className="application-followup-profile__title-actions" aria-hidden="true">
                <i>☆</i>
                <i>↗</i>
                <i>…</i>
              </span>
            </div>
            <div className="application-followup-profile__meta">
              <span>{profileGender || "—"}</span>
              <span>{profileAge ? `${profileAge}岁` : "—"}</span>
              <span>{profileEducation || "—"}</span>
              <span>{experienceText(person.experienceYears ?? structuredExperienceYears, structuredExperienceText)}</span>
              <span>{profileWorkStatus || "—"}</span>
            </div>
            <div className="application-followup-profile__contact-grid">
              <button type="button" onClick={() => openDetail("contact")}>☎ {profilePhone || selectedRecord.contactSummary || "—"}</button>
              <span>✉ {profileEmail || "—"}</span>
              <span>◉ {profileSchool || "—"}{profileMajor ? ` · ${profileMajor}` : ""}</span>
              <span>⌂ {person.location || "—"}{profileDistrict ? ` · ${profileDistrict}` : ""}</span>
            </div>
          </div>
          <div className="application-followup-profile__info-column">
            <ProfileFact label={copy("Current company", "现公司")} value={profileCurrentCompany} />
            <ProfileFact label={copy("Current role", "当前职位")} value={profileCurrentRole} />
            <ProfileFact label={copy("Business unit", "所属业务组")} value={profileDepartment} />
            <ProfileFact label={copy("Expected role", "期望职位")} value={profileExpectedRole} />
          </div>
          <div className="application-followup-profile__info-column">
            <ProfileFact label={copy("Expected city", "期望城市")} value={job.location || person.location} />
            <ProfileFact label={copy("Expected salary", "期望薪资")} value={job.compensationText} />
            <ProfileFact label={copy("Experience", "工作年限")} value={experienceText(person.experienceYears ?? structuredExperienceYears, structuredExperienceText)} />
            <ProfileFact label={copy("Availability", "到岗时间")} value={profileAvailability} />
            <ProfileFact label={copy("Source", "来源渠道")} value={profileSource} />
            <ProfileFact label={copy("Updated", "更新时间")} value={profileUpdatedAt} />
          </div>
          <div className="application-followup-profile__job">
            <strong>{copy("Current role", "当前沟通岗位")}</strong>
            <span>{job.title}</span>
            <span>{job.location || "—"} · {job.compensationText || "—"}</span>
            <button type="button" onClick={() => onOpenFullCockpit(selectedRecord.application.id)}>
              {copy("Locate", "定位记录")}
            </button>
          </div>
          <div className="application-followup-profile__tags">
            {person.tags.slice(0, 8).map((tag) => <StatusBadge key={tag} tone="neutral">{tag}</StatusBadge>)}
            {person.tags.length > 8 ? <StatusBadge tone="neutral">+{person.tags.length - 8}</StatusBadge> : null}
          </div>
        </section>

        <section className="application-followup-tabs" aria-label={copy("Follow-up sections", "跟进分区")}>
          <div className="application-followup-tabs__list">
            {[
              ["chat", copy("Chat", "沟通聊天")],
              ["records", copy("Records", "沟通记录")],
              ["interview", copy("Interview", "面试安排")],
              ["feedback", copy("Feedback", "评价反馈")],
              ["notes", copy("Notes", "备注")],
            ].map(([key, label]) => (
              <button
                key={key}
                type="button"
                data-active={workspaceTab === key}
                onClick={() => setWorkspaceTab(key as WorkspaceTab)}
              >
                {label}
              </button>
            ))}
          </div>
        </section>

        <section className="application-followup-main-panel">
          <div className="application-followup-chat-surface">
            {workspaceTab === "chat" ? <ChatMessageFeed record={selectedRecord} /> : null}

            {workspaceTab === "records" ? (
              <div className="application-followup-info-stack">
                <StatusTimeline transitions={selectedRecord.thread?.statusTransitions ?? []} stateMachine={stateMachine} compact />
                {selectedRecord.thread?.stageEvents.length ? selectedRecord.thread.stageEvents.slice(0, 6).map((event) => (
                  <FollowUpInfoCard
                    key={event.id}
                    title={event.stageLabel || event.toStatus}
                    detail={event.note || event.source}
                    meta={formatCompactDate(event.createdAt)}
                    onClick={() => openDetail("history")}
                  />
                )) : null}
              </div>
            ) : null}

            {workspaceTab === "interview" ? (
              <div className="application-followup-info-stack">
                {Object.keys(interviewPlan).length ? Object.entries(interviewPlan).map(([key, value]) => (
                  <FollowUpInfoCard key={key} title={key} detail={renderFactValue(value)} />
                )) : (
                  <FollowUpInfoCard
                    title={copy("No interview plan yet", "暂无面试安排")}
                    detail={copy("Open status history to inspect previous scheduling signals.", "可打开状态历史查看过往安排信号。")}
                    onClick={() => openDetail("history")}
                  />
                )}
              </div>
            ) : null}

            {workspaceTab === "feedback" ? (
              <div className="application-followup-info-stack">
                {(selectedRecord.thread?.scorecards ?? []).map((scorecard) => (
                  <FollowUpInfoCard
                    key={scorecard.id}
                    title={`${scorecard.source} · ${scorecard.scoreTotal ?? copy("Pending", "待评分")}`}
                    detail={scorecard.summary || scorecard.verdict || copy("No scorecard summary.", "暂无评分摘要。")}
                    onClick={() => openDetail("scores")}
                  />
                ))}
                {(selectedRecord.thread?.assessments ?? []).map((assessment) => (
                  <FollowUpInfoCard
                    key={assessment.id}
                    title={`${assessment.assessmentType} · ${assessment.score ?? assessment.status}`}
                    detail={assessment.summary || assessment.decision || copy("No assessment summary.", "暂无评估摘要。")}
                    onClick={() => openDetail("scores")}
                  />
                ))}
                {!selectedRecord.thread?.scorecards.length && !selectedRecord.thread?.assessments.length ? (
                  <FollowUpInfoCard
                    title={copy("No detailed feedback yet", "暂无评价反馈")}
                    detail={copy("Open score detail to inspect currently available AI scoring.", "打开评分详情查看当前 AI 评分。")}
                    onClick={() => openDetail("scores")}
                  />
                ) : null}
              </div>
            ) : null}

            {workspaceTab === "notes" ? (
              <div className="application-followup-info-stack">
                <FollowUpInfoCard
                  title={copy("Latest note", "最近备注")}
                  detail={selectedRecord.thread?.stateSnapshot.latestNote || selectedRecord.application.summary || copy("No note yet.", "暂无备注。")}
                />
                {Object.entries(facts).slice(0, 6).map(([key, value]) => (
                  <FollowUpInfoCard key={key} title={key} detail={renderFactValue(value)} />
                ))}
              </div>
            ) : null}
          </div>

          <div className="application-followup-composer">
            <div className="application-followup-composer__tools">
              <button type="button" disabled={renderingTemplate != null} onClick={() => void applyTemplateToDraft("application_greeting")}>{copy("Phrases", "常用语")}</button>
              <button type="button" disabled={sending || renderingTemplate != null} onClick={() => void sendTemplateMessage("job_share")}>
                {copy("Send role", "发送职位")}
              </button>
              <button type="button" disabled={sending || renderingTemplate != null} onClick={() => void sendTemplateMessage("wechat_request")}>
                {copy("Exchange WeChat", "交换微信")}
              </button>
              <button type="button" onClick={() => openDetail("profile")}>{copy("More", "更多")}</button>
            </div>
            <div className="application-followup-composer__input-row">
              <FormTextarea
                ref={composerTextareaRef}
                rows={1}
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                placeholder={
                  hasMessages
                    ? copy("Write a message. Enter to send, Ctrl+Enter for newline.", "请输入消息，Enter 发送，Ctrl+Enter 换行")
                    : copy("Write the first message to start the conversation.", "输入第一条打招呼消息，开始沟通。")
                }
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.ctrlKey && !event.shiftKey) {
                    event.preventDefault();
                    void sendMessage(draft);
                  }
                }}
              />
              <button
                type="button"
                className="application-followup-composer__send-main"
                style={{ height: composerInputHeight }}
                disabled={sending || !draft.trim()}
                onClick={() => void sendMessage(draft)}
              >
                {sending ? copy("Sending...", "发送中...") : copy("Send", "发送")}
              </button>
            </div>
          </div>
        </section>
      </main>

      <aside className="application-followup-workspace__insights">
        <ApplicationScoreCard
          primary
          label={copy("AI comprehensive score", "AI 综合评分")}
          score={scoreText(aiScore)}
          quality={aiQuality}
          metrics={metrics}
          expanded={expandedPanels.aiScore}
          collapsedSummary={<><strong>{scoreText(aiScore)}</strong><span>{aiQuality}</span></>}
          disabled={!hasAiScore}
          onClick={() => openDetail("scores")}
          onToggle={() => togglePanel("aiScore")}
        />

        <div className="application-followup-side-panels">
          <FollowUpCollapsiblePanel
            label={copy("Online resume score", "在线简历评分")}
            expanded={expandedPanels.onlineScore}
            collapsedSummary={<><strong>{scoreText(onlineScore)}</strong><span>{onlineQuality}</span></>}
            disabled={!hasOnlineScore}
            actionLabel={copy("Open score detail", "打开评分详情")}
            onToggle={() => togglePanel("onlineScore")}
            onAction={() => openDetail("resume")}
          >
            <div className="application-followup-score-panel-body">
              <strong>{scoreText(onlineScore)}</strong>
              <span>{onlineQuality}</span>
              <ScoreBars metrics={metrics.slice(0, 3)} />
            </div>
          </FollowUpCollapsiblePanel>

          <FollowUpCollapsiblePanel
            label={copy("Offline resume score", "离线简历评分")}
            expanded={expandedPanels.offlineScore}
            collapsedSummary={<><strong>{scoreText(offlineScore)}</strong><span>{offlineQuality}</span></>}
            disabled={!hasOfflineScore}
            actionLabel={copy("Open score detail", "打开评分详情")}
            onToggle={() => togglePanel("offlineScore")}
            onAction={() => openDetail("scores")}
          >
            <div className="application-followup-score-panel-body">
              <strong>{scoreText(offlineScore)}</strong>
              <span>{offlineQuality}</span>
              <ScoreBars
                metrics={offlineMetrics}
              />
            </div>
          </FollowUpCollapsiblePanel>

          <FollowUpCollapsiblePanel
            label={copy("Current communication role", "当前沟通岗位")}
            expanded={expandedPanels.currentRole}
            collapsedSummary={<span>{job.title}</span>}
            actionLabel={copy("Locate application", "定位记录")}
            onToggle={() => togglePanel("currentRole")}
            onAction={() => onOpenFullCockpit(selectedRecord.application.id)}
          >
            <div className="application-followup-role-panel">
              <strong>{job.title}</strong>
              <span>{job.companyName || copy("No company yet", "暂无公司信息")}</span>
              <span>{job.location || "—"} · {job.compensationText || "—"}</span>
            </div>
          </FollowUpCollapsiblePanel>

          {[
            {
              key: "onlineResume" as const,
              label: copy("Online resume preview", "在线简历预览"),
              tab: "resume" as DetailTab,
              body: selectedRecord.application.summary || copy("No online profile summary yet.", "暂无在线资料摘要。"),
            },
            {
              key: "offlineResume" as const,
              label: copy("Offline resume preview", "离线简历预览"),
              tab: "resume" as DetailTab,
              body: resumeArtifacts.length
                ? resumeArtifacts.map((item) => item.title).join(" / ")
                : copy("No stored offline resume artifacts yet.", "暂无离线简历制品。"),
            },
            {
              key: "deliveryHistory" as const,
              label: copy("Application history", "历史投递记录"),
              tab: "history" as DetailTab,
              body: `${selectedRecord.thread?.stageEvents.length ?? 0} ${copy("stage events", "条阶段事件")}`,
            },
            {
              key: "statusHistory" as const,
              label: copy("Status transition history", "历史状态流转记录"),
              tab: "history" as DetailTab,
              body: `${selectedRecord.thread?.statusTransitions.length ?? 0} ${copy("transitions", "条状态流转")}`,
            },
          ].map((panel) => (
            <FollowUpCollapsiblePanel
              key={panel.key}
              label={panel.label}
              expanded={expandedPanels[panel.key]}
              collapsedSummary={<span>{panel.body}</span>}
              actionLabel={copy("Open detail", "打开详情")}
              onToggle={() => togglePanel(panel.key)}
              onAction={() => openDetail(panel.tab)}
            >
              {panel.body}
            </FollowUpCollapsiblePanel>
          ))}

          <FollowUpCollapsiblePanel
            label={copy("Quick actions", "快捷操作")}
            expanded={expandedPanels.quickActions}
            actionLabel={copy("Application detail", "投递记录详情")}
            onToggle={() => togglePanel("quickActions")}
            onAction={() => openDetail("profile")}
          >
            <div className="application-followup-actions application-followup-actions--inside-panel">
              {currentActions.map((action) => {
                const actionLabel = applicationScopedLabel(action.label);
                const key = `${actionLabel}:${action.toStatus}`;
                return (
                  <button
                    key={key}
                    type="button"
                    data-style={action.style}
                    disabled={runningActionKey === key}
                    onClick={() => {
                      if (action.requiresNote) {
                        setPendingAction({ action, note: "" });
                        return;
                      }
                      void submitHumanAction(action);
                    }}
                  >
                    {actionLabel}
                  </button>
                );
              })}
              <button type="button" onClick={() => setOverrideOpen(true)}>{copy("Manual override", "人工修改状态")}</button>
              <ToolbarRefreshButton
                onClick={() => void refresh()}
                refreshing={refreshing}
                label={copy("Refresh", "刷新")}
                refreshingLabel={copy("Refreshing...", "刷新中...")}
              />
            </div>
          </FollowUpCollapsiblePanel>
        </div>

        {pendingAction ? (
          <div className="application-followup-note-box">
            <strong>{applicationScopedLabel(pendingAction.action.label)}</strong>
            <FormTextarea
              rows={3}
              value={pendingAction.note}
              onChange={(event) => setPendingAction({ ...pendingAction, note: event.target.value })}
              placeholder={copy("Add the note required by this action.", "请填写该动作要求的备注。")}
            />
            <div>
              <button type="button" onClick={() => setPendingAction(null)}>{copy("Cancel", "取消")}</button>
              <button
                type="button"
                disabled={!pendingAction.note.trim() || runningActionKey != null}
                onClick={() => void submitHumanAction(pendingAction.action, pendingAction.note)}
              >
                {copy("Confirm", "确认")}
              </button>
            </div>
          </div>
        ) : null}
      </aside>

      <CandidateDetailDrawer
        open={detailOpen}
        record={selectedRecord}
        stateMachine={stateMachine}
        initialTab={detailTab}
        onClose={() => setDetailOpen(false)}
        onTransition={onTransition}
        onRequestOverride={() => {
          setDetailOpen(false);
          setOverrideOpen(true);
        }}
      />

      <ManualStatusOverrideDrawer
        open={overrideOpen}
        record={selectedRecord}
        stateMachine={stateMachine}
        onClose={() => setOverrideOpen(false)}
        onSubmit={onTransition}
      />
    </section>
  );
}
