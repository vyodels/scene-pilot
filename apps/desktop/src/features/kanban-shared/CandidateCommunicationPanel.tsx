import React, { useMemo, useState } from "react";
import type { ApplicationTransitionPayload, HumanActionDefinition, RecruitmentStateMachine } from "@recruit-agent/shared";
import { FormTextarea, StatusBadge, ToolbarInput, ToolbarRefreshButton } from "../../components";
import { formatCompactDate } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { ChatInputArea } from "./ChatInputArea";
import { ChatMessageFeed } from "./ChatMessageFeed";
import { CandidateDetailDrawer } from "./CandidateDetailDrawer";
import { ManualStatusOverrideDrawer } from "./ManualStatusOverrideDrawer";
import { deriveHumanActionsForNode, nodeTone } from "./kanbanUtils";
import { StatusTimeline } from "./StatusTimeline";
import type { ApplicationViewModel } from "./kanbanUtils";

interface CandidateCommunicationPanelProps {
  applications: ApplicationViewModel[];
  selectedApplicationId: string;
  stateMachine: RecruitmentStateMachine;
  onSelectApplication(applicationId: string): void;
  onClose(): void;
  onOpenFullCockpit(applicationId: string): void;
  onRefresh?(): Promise<unknown> | void;
  onCreateEntry(
    applicationId: string,
    payload: { direction: string; content: string; messageType?: string; platform?: string },
  ): Promise<unknown> | void;
  onTransition(applicationId: string, payload: ApplicationTransitionPayload): Promise<unknown> | void;
  operatorProfile?: {
    nickname: string;
    avatarUrl?: string | null;
  };
}

function asObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

interface PendingActionState {
  action: HumanActionDefinition;
  note: string;
}

export function CandidateCommunicationPanel({
  applications,
  selectedApplicationId,
  stateMachine,
  onSelectApplication,
  onClose,
  onOpenFullCockpit,
  onRefresh,
  onCreateEntry,
  onTransition,
  operatorProfile,
}: CandidateCommunicationPanelProps): JSX.Element | null {
  const { copy } = useI18n();
  const [search, setSearch] = useState("");
  const [detailOpen, setDetailOpen] = useState(false);
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [pendingAction, setPendingAction] = useState<PendingActionState | null>(null);
  const [sending, setSending] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [runningActionKey, setRunningActionKey] = useState<string>();

  const filteredApplications = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    if (!keyword) {
      return applications;
    }
    return applications.filter((item) =>
      `${item.application.person.name} ${item.application.jobDescription.title} ${item.currentStatusLabel}`
        .toLowerCase()
        .includes(keyword),
    );
  }, [applications, search]);

  const selectedRecord =
    filteredApplications.find((item) => item.application.id === selectedApplicationId) ??
    applications.find((item) => item.application.id === selectedApplicationId) ??
    null;

  const currentActions = useMemo(
    () => (selectedRecord?.currentNode ? deriveHumanActionsForNode(selectedRecord.currentNode, stateMachine) : []),
    [selectedRecord, stateMachine],
  );

  if (!selectedRecord) {
    return null;
  }

  const aiScores = asObject(selectedRecord.application.aiScores);
  const onlineScore =
    typeof aiScores.overall === "number" ? Number(aiScores.overall) : undefined;
  const offlineScore = selectedRecord.thread?.scorecards[0]?.scoreTotal;

  const submitHumanAction = async (action: HumanActionDefinition, note?: string) => {
    const key = `${action.label}:${action.toStatus}`;
    setRunningActionKey(key);
    try {
      await onTransition(selectedRecord.application.id, {
        actor: "recruiter",
        toStatus: action.toStatus,
        trigger: action.label,
        note: note?.trim() || undefined,
        metadata: { initiated_from: "candidate_communication_panel" },
      });
      setPendingAction(null);
    } finally {
      setRunningActionKey(undefined);
    }
  };

  return (
    <>
      <section className="candidate-communication-panel">
        <aside className="candidate-communication-panel__rail">
          <div className="candidate-communication-panel__search">
            <ToolbarInput
              className="candidate-communication-panel__search-input"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={copy("Search candidates", "搜索候选人")}
            />
          </div>

          <div className="candidate-communication-panel__candidate-list">
            {filteredApplications.map((item) => (
              <button
                key={item.application.id}
                type="button"
                className="candidate-communication-panel__candidate-item"
                data-active={item.application.id === selectedRecord.application.id}
                onClick={() => onSelectApplication(item.application.id)}
              >
                <div className="candidate-communication-panel__candidate-head">
                  <strong>{item.application.person.name}</strong>
                  {item.humanRequired ? <span className="candidate-communication-panel__attention">⚡</span> : null}
                </div>
                <div className="candidate-communication-panel__candidate-meta">
                  <span>{item.currentStatusLabel}</span>
                  <StatusBadge tone={nodeTone(item.currentNode)}>{item.application.jobDescription.title}</StatusBadge>
                </div>
              </button>
            ))}
          </div>

          <button type="button" className="candidate-communication-panel__close" onClick={onClose}>
            {copy("Close panel", "关闭面板")}
          </button>
        </aside>

        <div className="candidate-communication-panel__center">
          <header className="candidate-communication-panel__toolbar">
            <div>
              <strong>{selectedRecord.application.platform}</strong>
              <span>
                {copy("Last synced", "最后同步")}{" "}
                {selectedRecord.latestActivityAt ? formatCompactDate(selectedRecord.latestActivityAt) : "—"}
              </span>
            </div>
            <ToolbarRefreshButton
              refreshing={refreshing}
              disabled={!onRefresh}
              label={copy("Refresh", "刷新")}
              refreshingLabel={copy("Refreshing...", "刷新中...")}
              onClick={async () => {
                if (!onRefresh) {
                  return;
                }
                setRefreshing(true);
                try {
                  await onRefresh();
                } finally {
                  setRefreshing(false);
                }
              }}
            />
          </header>

          <div className="candidate-communication-panel__feed">
            <ChatMessageFeed record={selectedRecord} operatorProfile={operatorProfile} />
          </div>

          <ChatInputArea
            record={selectedRecord}
            sending={sending}
            onSubmit={async ({ content, messageType }) => {
              setSending(true);
              try {
                await onCreateEntry(selectedRecord.application.id, {
                  direction: "outbound",
                  content,
                  messageType,
                  platform: selectedRecord.application.platform,
                });
              } finally {
                setSending(false);
              }
            }}
          />
        </div>

        <aside className="candidate-communication-panel__side">
          <div className="candidate-communication-panel__profile">
            <h3>{selectedRecord.application.person.name}</h3>
            <p>
              {selectedRecord.application.person.title} · {selectedRecord.application.person.location}
            </p>
            <p>{copy("Role", "应聘")}：{selectedRecord.application.jobDescription.title}</p>
          </div>

          <div className="candidate-communication-panel__section">
            <div className="candidate-communication-panel__section-title">{copy("AI scores", "AI 评分")}</div>
            <div className="candidate-communication-panel__metric">
              <span>{copy("Online", "在线")}</span>
              <strong>{onlineScore != null ? `${onlineScore}/100` : copy("Pending", "待获取")}</strong>
            </div>
            <div className="candidate-communication-panel__metric">
              <span>{copy("Offline", "线下")}</span>
              <strong>{offlineScore != null ? `${offlineScore}` : copy("Pending", "待评分")}</strong>
            </div>
          </div>

          <div className="candidate-communication-panel__section">
            <div className="candidate-communication-panel__section-title">{copy("Tags", "标签")}</div>
            <div className="candidate-communication-panel__tag-list">
              {selectedRecord.application.person.tags.length ? (
                selectedRecord.application.person.tags.map((tag) => <StatusBadge key={tag} tone="neutral">{tag}</StatusBadge>)
              ) : (
                <span className="candidate-communication-panel__placeholder">{copy("No tags yet.", "暂无标签。")}</span>
              )}
            </div>
          </div>

          <div className="candidate-communication-panel__section">
            <div className="candidate-communication-panel__section-title">{copy("Contact", "联系方式")}</div>
            <div className="candidate-communication-panel__fact-list">
              <span>{copy("Summary", "摘要")}：{selectedRecord.contactSummary}</span>
              <span>{copy("Channels", "渠道")}：{selectedRecord.thread?.stateSnapshot.contactChannels.join(", ") || "—"}</span>
            </div>
          </div>

          <div className="candidate-communication-panel__section">
            <div className="candidate-communication-panel__section-title">{copy("Quick actions", "快捷操作")}</div>
            <div className="candidate-communication-panel__action-list">
              {currentActions.length ? (
                currentActions.map((action) => {
                  const key = `${action.label}:${action.toStatus}`;
                  return (
                    <button
                      key={key}
                      type="button"
                      className="candidate-communication-panel__action"
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
                      {action.label}
                    </button>
                  );
                })
              ) : (
                <span className="candidate-communication-panel__placeholder">
                  {copy("This node is handled automatically by AI.", "当前节点默认由 AI 自动推进。")}
                </span>
              )}
              <button type="button" className="candidate-communication-panel__action" onClick={() => setDetailOpen(true)}>
                {copy("Details", "详情")}
              </button>
              <button type="button" className="candidate-communication-panel__action" onClick={() => setOverrideOpen(true)}>
                {copy("Manual status override…", "人工修改状态…")}
              </button>
            </div>

            {pendingAction ? (
              <div className="candidate-communication-panel__note-box">
                <strong>{pendingAction.action.label}</strong>
                <FormTextarea
                  className="candidate-communication-panel__note-input"
                  rows={3}
                  value={pendingAction.note}
                  onChange={(event) => setPendingAction({ ...pendingAction, note: event.target.value })}
                  placeholder={copy("Add the note required by this action.", "请填写该动作要求的备注。")}
                />
                <div className="candidate-communication-panel__note-actions">
                  <button type="button" className="candidate-communication-panel__action" onClick={() => setPendingAction(null)}>
                    {copy("Cancel", "取消")}
                  </button>
                  <button
                    type="button"
                    className="candidate-communication-panel__action"
                    data-style={pendingAction.action.style}
                    disabled={!pendingAction.note.trim() || runningActionKey != null}
                    onClick={() => void submitHumanAction(pendingAction.action, pendingAction.note)}
                  >
                    {copy("Confirm", "确认")}
                  </button>
                </div>
              </div>
            ) : null}
          </div>

          <div className="candidate-communication-panel__section">
            <div className="candidate-communication-panel__section-title">{copy("Status timeline", "状态时间线")}</div>
            <StatusTimeline
              transitions={selectedRecord.thread?.statusTransitions ?? []}
              stateMachine={stateMachine}
              compact
              maxItems={5}
              onShowMore={() => setDetailOpen(true)}
            />
          </div>

          <button
            type="button"
            className="candidate-communication-panel__full-link"
            onClick={() => onOpenFullCockpit(selectedRecord.application.id)}
          >
            {copy("Locate in application workspace ↗", "在投递记录工作区中定位 ↗")}
          </button>
        </aside>
      </section>

      <CandidateDetailDrawer
        open={detailOpen}
        record={selectedRecord}
        stateMachine={stateMachine}
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
    </>
  );
}
