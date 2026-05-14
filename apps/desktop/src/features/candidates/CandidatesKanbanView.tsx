import React from "react";
import type { ApplicationTransitionPayload, RecruitmentStateMachine } from "@recruit-agent/shared";
import { useI18n } from "../../lib/i18n";
import type { ApplicationFollowUpSummaryDefinition, ApplicationRecord, ApplicationThreadRecord, SettingsSnapshot } from "../../lib/types";
import { FunnelKanbanView } from "../funnel-kanban/FunnelKanbanView";
import { StatusKanbanView } from "../status-kanban/StatusKanbanView";

export type CandidatesKanbanTab = "funnel" | "status" | "jd";

export interface ApplicationWorkspaceFilter {
  label?: string;
  applicationIds?: string[];
  jobTitle?: string;
  statusId?: string;
  summaryKey?: string;
  milestoneId?: string;
}

interface CandidatesKanbanViewProps {
  applications: ApplicationRecord[];
  threads: ApplicationThreadRecord[];
  stateMachine?: RecruitmentStateMachine | null;
  summaryDefinitions?: ApplicationFollowUpSummaryDefinition[];
  activeTab: CandidatesKanbanTab;
  jdContent?: React.ReactNode;
  preferredApplicationId?: string;
  preferredConversationToken?: number;
  preferredFilter?: ApplicationWorkspaceFilter;
  preferredFilterToken?: number;
  onOpenApplication(applicationId: string): void;
  onRefresh?(): Promise<unknown> | void;
  onCreateEntry(
    applicationId: string,
    payload: { direction: string; content: string; messageType?: string; platform?: string },
  ): Promise<unknown> | void;
  onTransition(applicationId: string, payload: ApplicationTransitionPayload): Promise<unknown> | void;
  onOpenDashboard(): void;
  operatorProfile?: SettingsSnapshot["userProfile"];
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
  preferredFilter,
  preferredFilterToken,
  onOpenApplication,
  onRefresh,
  onCreateEntry,
  onTransition,
  onOpenDashboard,
  operatorProfile,
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
        preferredFilter={preferredFilter}
        preferredFilterToken={preferredFilterToken}
        onOpenApplication={onOpenApplication}
        onRefresh={onRefresh}
        onCreateEntry={onCreateEntry}
        onTransition={onTransition}
        operatorProfile={operatorProfile}
      />
    ) : (
      <StatusKanbanView
        applications={applications}
        threads={threads}
        stateMachine={stateMachine}
        summaryDefinitions={summaryDefinitions}
        preferredApplicationId={preferredApplicationId}
        preferredConversationToken={preferredConversationToken}
        preferredFilter={preferredFilter}
        preferredFilterToken={preferredFilterToken}
        onOpenApplication={onOpenApplication}
        onRefresh={onRefresh}
        onCreateEntry={onCreateEntry}
        onTransition={onTransition}
        onOpenDashboard={onOpenDashboard}
      />
    )
  );
}
