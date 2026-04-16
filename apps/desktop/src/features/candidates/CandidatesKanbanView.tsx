import React from "react";
import type { CandidateTransitionPayload, RecruitmentStateMachine } from "@scene-pilot/shared";
import { useI18n } from "../../lib/i18n";
import type { CandidateFollowUpSummaryDefinition, CandidateRecord, CandidateThreadRecord } from "../../lib/types";
import { FunnelKanbanView } from "../funnel-kanban/FunnelKanbanView";
import { StatusKanbanView } from "../status-kanban/StatusKanbanView";

export type CandidatesKanbanTab = "funnel" | "status" | "jd";

interface CandidatesKanbanViewProps {
  candidates: CandidateRecord[];
  threads: CandidateThreadRecord[];
  stateMachine?: RecruitmentStateMachine | null;
  summaryDefinitions?: CandidateFollowUpSummaryDefinition[];
  activeTab: CandidatesKanbanTab;
  jdContent?: React.ReactNode;
  preferredCandidateId?: string;
  preferredConversationToken?: number;
  onOpenCandidate(candidateId: string): void;
  onRefresh?(): Promise<unknown> | void;
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
  summaryDefinitions = [],
  activeTab,
  jdContent,
  preferredCandidateId,
  preferredConversationToken,
  onOpenCandidate,
  onRefresh,
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
    activeTab === "jd" ? (
      <>{jdContent ?? null}</>
    ) : activeTab === "funnel" ? (
      <FunnelKanbanView
        candidates={candidates}
        threads={threads}
        stateMachine={stateMachine}
        preferredCandidateId={preferredCandidateId}
        preferredConversationToken={preferredConversationToken}
        onOpenCandidate={onOpenCandidate}
        onRefresh={onRefresh}
        onCreateEntry={onCreateEntry}
        onTransition={onTransition}
      />
    ) : (
      <StatusKanbanView
        candidates={candidates}
        threads={threads}
        stateMachine={stateMachine}
        summaryDefinitions={summaryDefinitions}
        preferredCandidateId={preferredCandidateId}
        preferredConversationToken={preferredConversationToken}
        onOpenCandidate={onOpenCandidate}
        onRefresh={onRefresh}
        onCreateEntry={onCreateEntry}
        onTransition={onTransition}
      />
    )
  );
}
