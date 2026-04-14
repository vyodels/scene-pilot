import React from "react";
import { Panel } from "../../components";
import { useI18n } from "../../lib/i18n";
import type { CandidateRecord, WorkflowDefinition } from "../../lib/types";
import { CandidatesView } from "../candidates/CandidatesView";
import { WorkflowsView } from "../workflows/WorkflowsView";

interface RecruitingOpsViewProps {
  candidates: CandidateRecord[];
  workflows: WorkflowDefinition[];
}

export function RecruitingOpsView({ candidates, workflows }: RecruitingOpsViewProps): JSX.Element {
  const { copy } = useI18n();

  return (
    <div style={{ display: "grid", gap: "18px" }}>
      <Panel
        title={copy("Recruiting scene profile", "招聘场景画像")}
        eyebrow={copy("Scene-specific workspace", "场景专属工作区")}
        description={copy("Recruiting remains available as the first reusable scene profile. Its workflows and operator state now run on top of the shared runtime.", "招聘仍然作为首个可复用的场景画像保留，其工作流和操作状态都运行在同一套通用运行时之上。")}
      >
        <CandidatesView candidates={candidates} />
      </Panel>
      <Panel
        title={copy("Recruiting workflows", "招聘工作流")}
        eyebrow={copy("Workflow nodes and versions", "工作流节点与版本")}
        description={copy("These remain visible while the system shifts to runtime-authored plans and reusable templates.", "在系统迁移到运行时编写计划和可复用模板的过程中，这些视图仍然保留。")}
      >
        <WorkflowsView workflows={workflows} />
      </Panel>
    </div>
  );
}
