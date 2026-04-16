import React from "react";
import type { CandidateTransitionPayload, RecruitmentStateMachine } from "@scene-pilot/shared";
import { useI18n } from "../../lib/i18n";
import type { CandidateRecord, CandidateThreadRecord } from "../../lib/types";
import { FunnelKanbanView } from "../funnel-kanban/FunnelKanbanView";
import { StatusKanbanView } from "../status-kanban/StatusKanbanView";

export type CandidatesKanbanTab = "funnel" | "status";

interface CandidatesKanbanViewProps {
  candidates: CandidateRecord[];
  threads: CandidateThreadRecord[];
  stateMachine?: RecruitmentStateMachine | null;
  activeTab: CandidatesKanbanTab;
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
  activeTab,
  onOpenCandidate,
  onCreateEntry,
  onTransition,
}: CandidatesKanbanViewProps): JSX.Element {
  const { copy } = useI18n();

  if (!stateMachine) {
    return (
      <section className="candidate-table__empty">
        {copy("State machine configuration is not available yet.", "状态机配置尚未加载。")}
      </section>
    );
  }

  return (
    activeTab === "funnel" ? (
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
    )
  );
}
