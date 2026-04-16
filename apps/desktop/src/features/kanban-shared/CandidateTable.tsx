import React, { useMemo, useState } from "react";
import type { CandidateTransitionPayload, HumanActionDefinition, RecruitmentStateMachine } from "@scene-pilot/shared";
import { StatusBadge } from "../../components";
import { formatCompactDate } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { deriveHumanActionsForNode, nodeTone } from "./kanbanUtils";
import type { CandidateViewModel } from "./kanbanUtils";

interface CandidateTableProps {
  title: string;
  count: number;
  description?: string;
  candidates: CandidateViewModel[];
  stateMachine: RecruitmentStateMachine;
  emptyMessage: string;
  onOpenDetail(candidateId: string): void;
  onOpenCommunication(candidateId: string): void;
  onTransition(candidateId: string, payload: CandidateTransitionPayload): Promise<unknown> | void;
}

interface PendingNoteAction {
  candidateId: string;
  action: HumanActionDefinition;
}

export function CandidateTable({
  title,
  count,
  description,
  candidates,
  stateMachine,
  emptyMessage,
  onOpenDetail,
  onOpenCommunication,
  onTransition,
}: CandidateTableProps): JSX.Element {
  const { copy } = useI18n();
  const [pendingNoteAction, setPendingNoteAction] = useState<PendingNoteAction | null>(null);
  const [noteDraft, setNoteDraft] = useState("");
  const [submittingKey, setSubmittingKey] = useState<string>();

  const sortedCandidates = useMemo(
    () =>
      [...candidates].sort((left, right) => {
        if (left.humanRequired !== right.humanRequired) {
          return left.humanRequired ? -1 : 1;
        }
        if (right.candidate.matchScore !== left.candidate.matchScore) {
          return right.candidate.matchScore - left.candidate.matchScore;
        }
        return left.candidate.name.localeCompare(right.candidate.name);
      }),
    [candidates],
  );

  const submitAction = async (candidateId: string, action: HumanActionDefinition, note?: string) => {
    const key = `${candidateId}:${action.toStatus}:${action.label}`;
    setSubmittingKey(key);
    try {
      await onTransition(candidateId, {
        actor: "recruiter",
        toStatus: action.toStatus,
        trigger: action.label,
        note: note?.trim() || undefined,
        metadata: {
          initiated_from: "candidate_table",
        },
      });
      setPendingNoteAction(null);
      setNoteDraft("");
    } finally {
      setSubmittingKey(undefined);
    }
  };

  return (
    <section className="candidate-table-surface">
      <header className="candidate-table-surface__header">
        <div>
          <h2 className="candidate-table-surface__title">
            {title} · {count}
          </h2>
          {description ? <p className="candidate-table-surface__description">{description}</p> : null}
        </div>
      </header>

      {sortedCandidates.length ? (
        <div className="candidate-table">
          <div className="candidate-table__header">
            <span>{copy("Name", "姓名")}</span>
            <span>{copy("Current title", "当前职位")}</span>
            <span>{copy("Role", "应聘岗位")}</span>
            <span>{copy("Online resume", "在线简历")}</span>
            <span>{copy("Offline resume", "线下简历")}</span>
            <span>{copy("Contact", "联系方式")}</span>
            <span>{copy("Current status", "当前状态")}</span>
            <span>{copy("Actions", "操作")}</span>
          </div>

          {sortedCandidates.map((record) => {
            const currentNode = record.currentNode;
            const actions =
              currentNode?.executionConfig?.mode === "human_required"
                ? deriveHumanActionsForNode(currentNode, stateMachine)
                : [];

            return (
              <div
                key={record.candidate.id}
                className="candidate-table__row"
                data-human-required={record.humanRequired ? "true" : undefined}
              >
                <div className="candidate-table__cell candidate-table__cell--identity">
                  <strong>{record.candidate.name}</strong>
                  <span className="candidate-table__meta">
                    {record.candidate.platform} · {record.candidate.location}
                  </span>
                  {record.latestActivityAt ? (
                    <span className="candidate-table__meta">
                      {copy("Updated", "最近更新")} {formatCompactDate(record.latestActivityAt)}
                    </span>
                  ) : null}
                </div>
                <div className="candidate-table__cell">
                  <span>{record.candidate.title}</span>
                  <span className="candidate-table__meta">
                    {copy("Match", "匹配度")} {Math.round(record.candidate.matchScore)}
                  </span>
                </div>
                <div className="candidate-table__cell">
                  <span>{record.candidate.jdTitle}</span>
                  {record.candidate.tags.length ? (
                    <span className="candidate-table__meta">{record.candidate.tags.slice(0, 2).join(" / ")}</span>
                  ) : null}
                </div>
                <div className="candidate-table__cell">
                  <span>{record.onlineResumeAvailable ? copy("View", "查看") : "—"}</span>
                </div>
                <div className="candidate-table__cell">
                  <span>{record.offlineResumeAvailable ? copy("Stored", "已入库") : "—"}</span>
                </div>
                <div className="candidate-table__cell">
                  <span>{record.contactSummary}</span>
                </div>
                <div className="candidate-table__cell candidate-table__cell--status">
                  <StatusBadge tone={nodeTone(currentNode)}>
                    {currentNode?.label ?? record.currentStatus}
                  </StatusBadge>
                  {record.humanRequired ? <StatusBadge tone="warning">{copy("Waiting on you", "等待你操作")}</StatusBadge> : null}
                </div>
                <div className="candidate-table__cell candidate-table__cell--actions">
                  <div className="candidate-table__actions">
                    {actions.map((action) => {
                      const actionKey = `${record.candidate.id}:${action.toStatus}:${action.label}`;
                      return (
                        <button
                          key={actionKey}
                          type="button"
                          className="candidate-table__action"
                          data-style={action.style}
                          disabled={submittingKey === actionKey}
                          onClick={() => {
                            if (action.requiresNote) {
                              setPendingNoteAction({ candidateId: record.candidate.id, action });
                              setNoteDraft("");
                              return;
                            }
                            void submitAction(record.candidate.id, action);
                          }}
                        >
                          {action.label}
                        </button>
                      );
                    })}
                    <button
                      type="button"
                      className="candidate-table__detail"
                      onClick={() => onOpenDetail(record.candidate.id)}
                    >
                      {copy("Details", "详情")}
                    </button>
                    <button
                      type="button"
                      className="candidate-table__detail"
                      onClick={() => onOpenCommunication(record.candidate.id)}
                    >
                      {copy("Open conversation", "打开沟通")}
                    </button>
                  </div>

                  {pendingNoteAction?.candidateId === record.candidate.id ? (
                    <div className="candidate-table__note-popover">
                      <div className="candidate-table__note-header">
                        <strong>{pendingNoteAction.action.label}</strong>
                        <span>{copy("Note required", "需要备注")}</span>
                      </div>
                      <textarea
                        className="candidate-table__note-input"
                        value={noteDraft}
                        onChange={(event) => setNoteDraft(event.target.value)}
                        rows={3}
                        placeholder={copy("Add context for the transition.", "请补充本次流转的备注。")}
                      />
                      <div className="candidate-table__note-actions">
                        <button
                          type="button"
                          className="candidate-table__action"
                          data-style="default"
                          onClick={() => {
                            setPendingNoteAction(null);
                            setNoteDraft("");
                          }}
                        >
                          {copy("Cancel", "取消")}
                        </button>
                        <button
                          type="button"
                          className="candidate-table__action"
                          data-style={pendingNoteAction.action.style}
                          disabled={!noteDraft.trim() || submittingKey != null}
                          onClick={() => void submitAction(record.candidate.id, pendingNoteAction.action, noteDraft)}
                        >
                          {copy("Confirm", "确认")}
                        </button>
                      </div>
                    </div>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="candidate-table__empty">{emptyMessage}</div>
      )}
    </section>
  );
}
