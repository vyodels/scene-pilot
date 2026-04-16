import React, { useMemo, useState } from "react";
import type { CandidateTransitionPayload, RecruitmentStateMachine } from "@scene-pilot/shared";
import { SectionTabs, StatusBadge } from "../../components";
import { useI18n } from "../../lib/i18n";
import { deriveHumanActionsForNode, nodeTone } from "./kanbanUtils";
import { StatusTimeline } from "./StatusTimeline";
import type { CandidateViewModel } from "./kanbanUtils";

interface CandidateDetailDrawerProps {
  open: boolean;
  record: CandidateViewModel | null;
  stateMachine: RecruitmentStateMachine;
  onClose(): void;
  onTransition(candidateId: string, payload: CandidateTransitionPayload): Promise<unknown> | void;
  onRequestOverride(): void;
}

type DetailTab = "profile" | "resume" | "scores" | "history" | "contact";

function asObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

export function CandidateDetailDrawer({
  open,
  record,
  stateMachine,
  onClose,
  onTransition,
  onRequestOverride,
}: CandidateDetailDrawerProps): JSX.Element | null {
  const { copy } = useI18n();
  const [activeTab, setActiveTab] = useState<DetailTab>("profile");

  const currentNode = record?.currentNode;
  const actions = useMemo(
    () => (currentNode ? deriveHumanActionsForNode(currentNode, stateMachine) : []),
    [currentNode, stateMachine],
  );

  if (!open || !record) {
    return null;
  }

  const aiScores = asObject(record.candidate.aiScores);

  return (
    <div className="drawer-backdrop">
      <aside className="drawer">
        <header className="drawer__header">
          <div>
            <div className="drawer__eyebrow">{copy("Candidate detail", "候选人详情")}</div>
            <h2 className="drawer__title">{record.candidate.name}</h2>
            <p className="drawer__description">
              {record.candidate.title} · {record.candidate.location}
            </p>
          </div>
          <button type="button" className="drawer__close" onClick={onClose}>
            ×
          </button>
        </header>

        <div className="drawer__body">
          <div className="drawer__status-row">
            <StatusBadge tone={nodeTone(currentNode)}>{currentNode?.label ?? record.currentStatus}</StatusBadge>
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
              <div><strong>{copy("Role", "应聘岗位")}</strong><span>{record.candidate.jdTitle}</span></div>
              <div><strong>{copy("Platform", "平台")}</strong><span>{record.candidate.platform}</span></div>
              <div><strong>{copy("Experience", "工作年限")}</strong><span>{record.candidate.experienceYears || "—"}</span></div>
              <div><strong>{copy("Deepest milestone", "最深里程碑")}</strong><span>{record.deepestMilestone ?? "—"}</span></div>
              <div className="drawer__full-row">
                <strong>{copy("Summary", "摘要")}</strong>
                <span>{record.candidate.summary || copy("No summary available.", "暂无摘要。")}</span>
              </div>
            </div>
          ) : null}

          {activeTab === "resume" ? (
            <div className="drawer__stack">
              <div className="drawer__card">
                <strong>{copy("Online profile", "在线资料")}</strong>
                <p>{record.candidate.summary || copy("No online profile summary.", "暂无在线资料摘要。")}</p>
              </div>
              {record.thread?.resumeArtifacts.length ? (
                record.thread.resumeArtifacts.map((artifact) => (
                  <div key={artifact.id} className="drawer__card">
                    <strong>{artifact.fileName || artifact.filePath || copy("Stored artifact", "已入库简历")}</strong>
                    <p>{artifact.extractedText || copy("No extracted text available.", "暂无提取文本。")}</p>
                  </div>
                ))
              ) : (
                <div className="drawer__empty">{copy("No offline resume artifacts yet.", "暂无线下简历制品。")}</div>
              )}
            </div>
          ) : null}

          {activeTab === "scores" ? (
            <div className="drawer__stack">
              <div className="drawer__grid">
                <div><strong>{copy("Online", "在线")}</strong><span>{typeof aiScores.overall === "number" ? `${Math.round(Number(aiScores.overall))}/100` : `${Math.round(record.candidate.matchScore)}/100`}</span></div>
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
            <StatusTimeline transitions={record.thread?.statusTransitions ?? []} />
          ) : null}

          {activeTab === "contact" ? (
            <div className="drawer__grid">
              <div><strong>{copy("Summary", "联系方式摘要")}</strong><span>{record.contactSummary}</span></div>
              <div><strong>{copy("Channels", "渠道")}</strong><span>{record.thread?.stateSnapshot.contactChannels.join(", ") || "—"}</span></div>
              <div className="drawer__full-row">
                <strong>{copy("Contact snapshot", "联系快照")}</strong>
                <span>{JSON.stringify(record.candidate.contactInfo ?? {}, null, 2)}</span>
              </div>
            </div>
          ) : null}
        </div>

        <footer className="drawer__footer drawer__footer--spread">
          <div className="drawer__actions">
            {actions.map((action) => (
              <button
                key={action.label}
                type="button"
                className="drawer__button"
                data-style={action.style}
                onClick={() =>
                  void onTransition(record.candidate.id, {
                    actor: "recruiter",
                    toStatus: action.toStatus,
                    trigger: action.label,
                    note: action.requiresNote ? copy("Changed from detail drawer.", "从详情抽屉发起。") : undefined,
                    metadata: { initiated_from: "candidate_detail_drawer" },
                  })
                }
              >
                {action.label}
              </button>
            ))}
          </div>
          <button type="button" className="drawer__button" onClick={onRequestOverride}>
            {copy("Manual status override…", "人工修改状态…")}
          </button>
        </footer>
      </aside>
    </div>
  );
}
