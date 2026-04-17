import React, { useEffect, useMemo, useState } from "react";
import type { ApplicationTransitionPayload, RecruitmentStateMachine } from "@scene-pilot/shared";
import { StatusBadge } from "../../components";
import { useI18n } from "../../lib/i18n";
import type { ApplicationViewModel } from "./kanbanUtils";

interface ManualStatusOverrideDrawerProps {
  open: boolean;
  record: ApplicationViewModel | null;
  stateMachine: RecruitmentStateMachine;
  onClose(): void;
  onSubmit(applicationId: string, payload: ApplicationTransitionPayload): Promise<unknown> | void;
}

export function ManualStatusOverrideDrawer({
  open,
  record,
  stateMachine,
  onClose,
  onSubmit,
}: ManualStatusOverrideDrawerProps): JSX.Element | null {
  const { copy } = useI18n();
  const [targetStatus, setTargetStatus] = useState("");
  const [overrideReason, setOverrideReason] = useState("");
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!record) {
      return;
    }
    setTargetStatus(record.currentStatus);
    setOverrideReason("");
    setNote("");
  }, [record]);

  const statusOptions = useMemo(() => {
    if (!record) {
      return [];
    }
    const allowed = new Set(record.thread?.availableStatuses ?? []);
    for (const node of stateMachine.nodes) {
      allowed.add(node.id);
    }
    return stateMachine.nodes.filter((node) => allowed.has(node.id) && !node.isTransient);
  }, [record, stateMachine.nodes]);

  if (!open || !record) {
    return null;
  }

  const currentNode = stateMachine.nodes.find((node) => node.id === record.currentStatus);
  const targetNode = stateMachine.nodes.find((node) => node.id === targetStatus);

  return (
    <div className="drawer-backdrop">
      <aside className="drawer drawer--narrow">
        <header className="drawer__header">
          <div>
            <div className="drawer__eyebrow">{copy("Manual override", "人工修改状态")}</div>
            <h2 className="drawer__title">{record.application.person.name}</h2>
          </div>
          <button type="button" className="drawer__close" onClick={onClose}>
            ×
          </button>
        </header>

        <div className="drawer__body">
          <div className="drawer__preview">
            <StatusBadge tone="neutral">{currentNode?.label ?? record.currentStatus}</StatusBadge>
            <span>→</span>
            <StatusBadge tone="warning">{targetNode?.label ?? targetStatus ?? copy("Select target", "选择目标状态")}</StatusBadge>
          </div>

          <label className="drawer__field">
            <span>{copy("Target status", "目标状态")}</span>
            <select
              className="drawer__select"
              value={targetStatus}
              onChange={(event) => setTargetStatus(event.target.value)}
            >
              {statusOptions.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>

          <label className="drawer__field">
            <span>{copy("Override reason", "覆盖理由")}</span>
            <textarea
              className="drawer__textarea"
              rows={4}
              value={overrideReason}
              onChange={(event) => setOverrideReason(event.target.value)}
              placeholder={copy("Explain why the state must be overridden.", "说明为什么需要人工覆盖当前状态。")}
            />
          </label>

          <label className="drawer__field">
            <span>{copy("Operator note", "备注")}</span>
            <textarea
              className="drawer__textarea"
              rows={3}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder={copy("Optional extra context.", "补充可选说明。")}
            />
          </label>
        </div>

        <footer className="drawer__footer">
          <button type="button" className="drawer__button" onClick={onClose}>
            {copy("Cancel", "取消")}
          </button>
          <button
            type="button"
            className="drawer__button drawer__button--primary"
            disabled={!targetStatus || !overrideReason.trim() || submitting}
            onClick={async () => {
              setSubmitting(true);
              try {
                await onSubmit(record.application.id, {
                  actor: "recruiter_override",
                  toStatus: targetStatus,
                  trigger: "manual_override",
                  overrideReason: overrideReason.trim(),
                  note: note.trim() || undefined,
                  metadata: {
                    initiated_from: "manual_status_override_drawer",
                    from_status: record.currentStatus,
                  },
                });
                onClose();
              } finally {
                setSubmitting(false);
              }
            }}
          >
            {copy("Apply override", "确认覆盖")}
          </button>
        </footer>
      </aside>
    </div>
  );
}
