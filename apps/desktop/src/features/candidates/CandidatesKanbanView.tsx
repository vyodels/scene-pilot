import React from "react";
import type { CandidateTransitionPayload, RecruitmentStateMachine } from "@scene-pilot/shared";
import { useI18n } from "../../lib/i18n";
import type { ApplicationFollowUpSummaryDefinition, ApplicationRecord, ApplicationThreadRecord } from "../../lib/types";
import { FunnelKanbanView } from "../funnel-kanban/FunnelKanbanView";
import { StatusKanbanView } from "../status-kanban/StatusKanbanView";

export type CandidatesKanbanTab = "funnel" | "status" | "jd";

interface CandidatesKanbanViewProps {
  applications: ApplicationRecord[];
  threads: ApplicationThreadRecord[];
  stateMachine?: RecruitmentStateMachine | null;
  summaryDefinitions?: ApplicationFollowUpSummaryDefinition[];
  activeTab: CandidatesKanbanTab;
  jdContent?: React.ReactNode;
  preferredApplicationId?: string;
  preferredConversationToken?: number;
  onOpenApplication(applicationId: string): void;
  onRefresh?(): Promise<unknown> | void;
  onCreateEntry(
    applicationId: string,
    payload: { direction: string; content: string; messageType?: string; platform?: string },
  ): Promise<unknown> | void;
  onTransition(applicationId: string, payload: CandidateTransitionPayload): Promise<unknown> | void;
}

export function CandidatesKanbanView({
  applications,
  threads,
  stateMachine,
  summaryDefinitions = [],
  activeTab,
  jdContent,
  preferredApplicationId,
  preferredConversationToken,
  onOpenApplication,
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
        applications={applications}
        threads={threads}
        stateMachine={stateMachine}
        preferredApplicationId={preferredApplicationId}
        preferredConversationToken={preferredConversationToken}
        onOpenApplication={onOpenApplication}
        onRefresh={onRefresh}
        onCreateEntry={onCreateEntry}
        onTransition={onTransition}
      />
    ) : (
      <StatusKanbanView
        applications={applications}
        threads={threads}
        stateMachine={stateMachine}
        summaryDefinitions={summaryDefinitions}
        preferredApplicationId={preferredApplicationId}
        preferredConversationToken={preferredConversationToken}
        onOpenApplication={onOpenApplication}
        onRefresh={onRefresh}
        onCreateEntry={onCreateEntry}
        onTransition={onTransition}
      />
    )
  );
}
