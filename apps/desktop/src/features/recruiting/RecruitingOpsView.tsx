import React from "react";
import { Panel } from "../../components";
import type { CandidateRecord, WorkflowDefinition } from "../../lib/types";
import { CandidatesView } from "../candidates/CandidatesView";
import { WorkflowsView } from "../workflows/WorkflowsView";

interface RecruitingOpsViewProps {
  candidates: CandidateRecord[];
  workflows: WorkflowDefinition[];
}

export function RecruitingOpsView({ candidates, workflows }: RecruitingOpsViewProps): JSX.Element {
  return (
    <div style={{ display: "grid", gap: "18px" }}>
      <Panel
        title="Recruiting domain pack"
        eyebrow="Domain-specific workspace"
        description="Recruiting stays available as the first domain pack. Its workflows and operator state now sit on top of the same general runtime."
      >
        <CandidatesView candidates={candidates} />
      </Panel>
      <Panel
        title="Recruiting workflows"
        eyebrow="Pack templates and nodes"
        description="These remain visible while the system shifts to runtime-authored plans and reusable templates."
      >
        <WorkflowsView workflows={workflows} />
      </Panel>
    </div>
  );
}
