import React, { useMemo, useState } from "react";
import type { CandidateTransitionPayload, RecruitmentStateMachine } from "@scene-pilot/shared";
import { SectionTabs } from "../../components";
import { useI18n } from "../../lib/i18n";
import type { CandidateRecord, CandidateThreadRecord } from "../../lib/types";
import { buildCandidateViewModels } from "../kanban-shared/kanbanUtils";
import { FunnelKanbanView } from "../funnel-kanban/FunnelKanbanView";
import { StatusKanbanView } from "../status-kanban/StatusKanbanView";

interface CandidatesKanbanViewProps {
  candidates: CandidateRecord[];
  threads: CandidateThreadRecord[];
  stateMachine?: RecruitmentStateMachine | null;
  onOpenCandidate(candidateId: string): void;
  onCreateEntry(
    candidateId: string,
    payload: { direction: string; content: string; messageType?: string; platform?: string },
  ): Promise<unknown> | void;
  onTransition(candidateId: string, payload: CandidateTransitionPayload): Promise<unknown> | void;
}

export function CandidatesKanbanView({
  candidates,
  threads,
  stateMachine,
  onOpenCandidate,
  onCreateEntry,
  onTransition,
}: CandidatesKanbanViewProps): JSX.Element {
  const { copy } = useI18n();
  const [activeTab, setActiveTab] = useState<"funnel" | "status">("funnel");

  const models = useMemo(
    () => (stateMachine ? buildCandidateViewModels(candidates, threads, stateMachine) : []),
    [candidates, stateMachine, threads],
  );

  const humanPendingCount = models.filter((item) => item.humanRequired).length;

  if (!stateMachine) {
    return (
      <section className="candidate-table__empty">
        {copy("State machine configuration is not available yet.", "状态机配置尚未加载。")}
      </section>
    );
  }

  return (
    <div className="kanban-page">
      <SectionTabs
        items={[
          {
            key: "funnel",
            label: copy("Funnel board", "漏斗看板"),
            detail: copy("Track deepest milestones and drop-off annotations.", "按最深里程碑查看阶段转化与淘汰注释。"),
            count: candidates.length,
          },
          {
            key: "status",
            label: copy("Status board", "状态看板"),
            detail: copy("Render live state nodes and highlight human-required candidates.", "按实时状态节点查看候选人，并高亮等待人工处理的节点。"),
            count: humanPendingCount,
          },
        ]}
        active={activeTab}
        onChange={(key) => setActiveTab(key as "funnel" | "status")}
      />

      {activeTab === "funnel" ? (
        <FunnelKanbanView
          candidates={candidates}
          threads={threads}
          stateMachine={stateMachine}
          onOpenCandidate={onOpenCandidate}
          onCreateEntry={onCreateEntry}
          onTransition={onTransition}
        />
      ) : (
        <StatusKanbanView
          candidates={candidates}
          threads={threads}
          stateMachine={stateMachine}
          onOpenCandidate={onOpenCandidate}
          onCreateEntry={onCreateEntry}
          onTransition={onTransition}
        />
      )}
    </div>
  );
}
