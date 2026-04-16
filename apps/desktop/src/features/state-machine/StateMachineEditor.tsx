import React, { useEffect, useMemo, useState } from "react";
import { funnelMilestones } from "@scene-pilot/shared";
import type {
  HumanActionDefinition,
  RecruitmentStateMachine,
  StateCriteriaOptimizationReport,
  RecruitmentStateMachineVersionRecord,
  RecruitmentStateMachineUpdatePayload,
  StateCriteriaRef,
  StateNode,
  StateRetryPolicy,
} from "@scene-pilot/shared";
import { Panel, StatusBadge } from "../../components";
import { apiClient } from "../../lib/api";
import { formatCompactDate } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import type { SkillRecord } from "../../lib/types";

interface StateMachineEditorProps {
  stateMachine: RecruitmentStateMachine | null;
  skills: SkillRecord[];
  onSave(payload: RecruitmentStateMachineUpdatePayload): Promise<unknown> | void;
}

type DiffSummary = {
  addedNodes: string[];
  removedNodes: string[];
  changedNodes: string[];
  addedTransitions: string[];
  removedTransitions: string[];
};

function isConfigurableNode(node: StateNode): boolean {
  return !node.isTransient && (node.defaultWaitingParty === "AI" || node.defaultWaitingParty === "HUMAN");
}

function supportsRetryPolicy(node: StateNode): boolean {
  return (
    !node.isTransient &&
    !node.isTerminal &&
    !node.isSoftTerminal &&
    node.defaultWaitingParty === "CANDIDATE"
  );
}

function cloneStateMachine(stateMachine: RecruitmentStateMachine): RecruitmentStateMachine {
  return JSON.parse(JSON.stringify(stateMachine)) as RecruitmentStateMachine;
}

function ensureExecutionConfig(node: StateNode): NonNullable<StateNode["executionConfig"]> {
  return (
    node.executionConfig ?? {
      mode: node.defaultWaitingParty === "AI" ? "ai_auto" : "human_required",
    }
  );
}

function ensureCriteriaRef(node: StateNode): StateCriteriaRef {
  return ensureExecutionConfig(node).criteriaRef ?? { type: "skill" };
}

function ensureRetryPolicy(node: StateNode): StateRetryPolicy {
  return (
    node.retryPolicy ?? {
      maxRetries: 2,
      retryAfterHours: 48,
      closeAfterHours: 120,
    }
  );
}

function withExecutionConfig(
  node: StateNode,
  updater: (executionConfig: NonNullable<StateNode["executionConfig"]>) => NonNullable<StateNode["executionConfig"]>,
): StateNode {
  return {
    ...node,
    executionConfig: updater(ensureExecutionConfig(node)),
  };
}

function withCriteriaRef(
  node: StateNode,
  updater: (criteriaRef: StateCriteriaRef) => StateCriteriaRef,
): StateNode {
  const executionConfig = ensureExecutionConfig(node);
  return {
    ...node,
    executionConfig: {
      ...executionConfig,
      criteriaRef: updater(executionConfig.criteriaRef ?? { type: "skill" }),
    },
  };
}

function withRetryPolicy(
  node: StateNode,
  updater: (retryPolicy: StateRetryPolicy) => StateRetryPolicy,
): StateNode {
  return {
    ...node,
    retryPolicy: updater(ensureRetryPolicy(node)),
  };
}

function defaultHumanAction(index: number): HumanActionDefinition {
  return {
    label: `操作 ${index + 1}`,
    toStatus: "archived",
    style: "default",
  };
}

function computeDiff(
  left: RecruitmentStateMachineVersionRecord | null,
  right: RecruitmentStateMachineVersionRecord | null,
): DiffSummary {
  if (!left || !right) {
    return { addedNodes: [], removedNodes: [], changedNodes: [], addedTransitions: [], removedTransitions: [] };
  }

  const leftNodeMap = new Map(left.nodes.map((node) => [node.id, node]));
  const rightNodeMap = new Map(right.nodes.map((node) => [node.id, node]));
  const leftTransitionIds = new Set([...left.transitions, ...left.globalTransitions].map((item) => item.id));
  const rightTransitionIds = new Set([...right.transitions, ...right.globalTransitions].map((item) => item.id));

  const addedNodes = right.nodes.filter((node) => !leftNodeMap.has(node.id)).map((node) => node.label);
  const removedNodes = left.nodes.filter((node) => !rightNodeMap.has(node.id)).map((node) => node.label);
  const changedNodes = right.nodes
    .filter((node) => {
      const previous = leftNodeMap.get(node.id);
      return previous != null && JSON.stringify(previous) !== JSON.stringify(node);
    })
    .map((node) => node.label);

  const addedTransitions = [...rightTransitionIds].filter((id) => !leftTransitionIds.has(id));
  const removedTransitions = [...leftTransitionIds].filter((id) => !rightTransitionIds.has(id));
  return { addedNodes, removedNodes, changedNodes, addedTransitions, removedTransitions };
}

export function StateMachineEditor({
  stateMachine,
  skills,
  onSave,
}: StateMachineEditorProps): JSX.Element {
  const { copy } = useI18n();
  const [draft, setDraft] = useState<RecruitmentStateMachine | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string>();
  const [changeSummary, setChangeSummary] = useState("");
  const [versions, setVersions] = useState<RecruitmentStateMachineVersionRecord[]>([]);
  const [compareLeftVersion, setCompareLeftVersion] = useState<number>();
  const [compareRightVersion, setCompareRightVersion] = useState<number>();
  const [compareLeft, setCompareLeft] = useState<RecruitmentStateMachineVersionRecord | null>(null);
  const [compareRight, setCompareRight] = useState<RecruitmentStateMachineVersionRecord | null>(null);
  const [criteriaSuggestions, setCriteriaSuggestions] = useState<StateCriteriaOptimizationReport[]>([]);
  const [saving, setSaving] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string>();
  const [draggingNodeId, setDraggingNodeId] = useState<string>();

  useEffect(() => {
    if (!stateMachine) {
      setDraft(null);
      setSelectedNodeId(undefined);
      return;
    }
    setDraft(cloneStateMachine(stateMachine));
    setSelectedNodeId((current) => current && stateMachine.nodes.some((node) => node.id === current) ? current : stateMachine.nodes[0]?.id);
  }, [stateMachine]);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const nextVersions = await apiClient.listStateMachineVersions();
        if (!active) {
          return;
        }
        setVersions(nextVersions);
        setCompareRightVersion((current) => current ?? nextVersions[0]?.version);
        setCompareLeftVersion((current) => current ?? nextVersions[1]?.version ?? nextVersions[0]?.version);
      } catch (error) {
        if (active) {
          setErrorMessage(error instanceof Error ? error.message : copy("Failed to load state machine versions.", "加载状态机版本失败。"));
        }
      }
    })();
    return () => {
      active = false;
    };
  }, [copy, stateMachine?.version]);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const reports = await apiClient.listStateMachineCriteriaSuggestions();
        if (active) {
          setCriteriaSuggestions(reports);
        }
      } catch (error) {
        if (active) {
          setErrorMessage(error instanceof Error ? error.message : copy("Failed to load optimization suggestions.", "加载优化建议失败。"));
        }
      }
    })();
    return () => {
      active = false;
    };
  }, [copy, stateMachine?.version]);

  useEffect(() => {
    let active = true;
    if (!compareLeftVersion) {
      setCompareLeft(null);
      return;
    }
    void (async () => {
      const payload = await apiClient.getStateMachineVersion(compareLeftVersion);
      if (active) {
        setCompareLeft(payload);
      }
    })();
    return () => {
      active = false;
    };
  }, [compareLeftVersion]);

  useEffect(() => {
    let active = true;
    if (!compareRightVersion) {
      setCompareRight(null);
      return;
    }
    void (async () => {
      const payload = await apiClient.getStateMachineVersion(compareRightVersion);
      if (active) {
        setCompareRight(payload);
      }
    })();
    return () => {
      active = false;
    };
  }, [compareRightVersion]);

  const selectedNode = draft?.nodes.find((node) => node.id === selectedNodeId) ?? null;
  const selectedExecutionConfig = selectedNode ? ensureExecutionConfig(selectedNode) : null;
  const selectedCriteriaRef = selectedNode ? ensureCriteriaRef(selectedNode) : null;
  const selectedRetryPolicy = selectedNode && supportsRetryPolicy(selectedNode) ? ensureRetryPolicy(selectedNode) : null;
  const selectedCriteriaReport = useMemo(
    () => criteriaSuggestions.find((item) => item.nodeId === selectedNodeId) ?? null,
    [criteriaSuggestions, selectedNodeId],
  );
  const diffSummary = useMemo(() => computeDiff(compareLeft, compareRight), [compareLeft, compareRight]);

  const groupedNodes = useMemo(() => {
    const source = draft?.nodes ?? [];
    const groups = new Map<string, StateNode[]>();
    for (const node of source) {
      const current = groups.get(node.phase) ?? [];
      current.push(node);
      groups.set(node.phase, current);
    }
    return [...groups.entries()].map(([phase, nodes]) => ({
      phase,
      nodes: [...nodes].sort((left, right) => left.sortOrder - right.sortOrder),
    }));
  }, [draft?.nodes]);

  const transitionsForNode = useMemo(() => {
    if (!draft || !selectedNode) {
      return [];
    }
    return [...draft.transitions, ...draft.globalTransitions].filter(
      (transition) => transition.fromState === selectedNode.id || transition.toState === selectedNode.id,
    );
  }, [draft, selectedNode]);

  const updateSelectedNode = (updater: (node: StateNode) => StateNode) => {
    if (!draft || !selectedNodeId) {
      return;
    }
    setDraft({
      ...draft,
      nodes: draft.nodes.map((node) => (node.id === selectedNodeId ? updater(node) : node)),
    });
  };

  const reorderNode = (targetNodeId: string) => {
    if (!draft || !draggingNodeId || draggingNodeId === targetNodeId) {
      return;
    }
    const nodes = [...draft.nodes];
    const fromIndex = nodes.findIndex((node) => node.id === draggingNodeId);
    const toIndex = nodes.findIndex((node) => node.id === targetNodeId);
    if (fromIndex < 0 || toIndex < 0) {
      return;
    }
    const [moved] = nodes.splice(fromIndex, 1);
    nodes.splice(toIndex, 0, moved);
    const reordered = nodes.map((node, index) => ({ ...node, sortOrder: (index + 1) * 10 }));
    setDraft({ ...draft, nodes: reordered });
    setDraggingNodeId(undefined);
  };

  const handleSave = async () => {
    if (!draft) {
      return;
    }
    setSaving(true);
    setErrorMessage(undefined);
    try {
      await onSave({
        updatedBy: "desktop-user",
        changeSummary: changeSummary.trim() || undefined,
        nodes: draft.nodes,
        transitions: draft.transitions,
        globalTransitions: draft.globalTransitions,
        versionMetadata: {
          source: "state_machine_editor",
        },
      });
      setChangeSummary("");
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : copy("Failed to save state machine.", "保存状态机失败。"));
    } finally {
      setSaving(false);
    }
  };

  const applyCriteriaSuggestion = (report: StateCriteriaOptimizationReport, suggestionIndex: number) => {
    const suggestion = report.suggestions[suggestionIndex];
    if (!suggestion) {
      return;
    }
    updateSelectedNode((node) =>
      withCriteriaRef(node, () => ({
        ...suggestion.proposedCriteriaRef,
      })),
    );
  };

  return (
    <div style={{ display: "grid", gap: "var(--space-5)" }}>
      {errorMessage ? (
        <div className="state-machine-editor__error">{errorMessage}</div>
      ) : null}

      <Panel
        title={copy("State machine editor", "状态机编辑器")}
        eyebrow={copy("Versioned workflow", "版本化工作流")}
        description={copy(
          "Configure node execution mode, AI criteria, and human actions. Agent runs will pick up the new version automatically.",
          "配置节点执行方式、AI 判断标准和人工动作。保存后 Agent 下次运行会自动感知新版本。",
        )}
        actions={
          <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
            <StatusBadge tone="neutral">
              {stateMachine ? `v${stateMachine.version}` : copy("Not loaded", "未加载")}
            </StatusBadge>
            <button type="button" className="state-machine-editor__primary" onClick={() => void handleSave()} disabled={!draft || saving}>
              {saving ? copy("Saving...", "保存中...") : copy("Save and publish", "保存并发布")}
            </button>
          </div>
        }
      >
        <div className="state-machine-editor__layout">
          <aside className="state-machine-editor__node-list">
            <div className="state-machine-editor__node-header">
              <strong>{copy("Nodes", "节点列表")}</strong>
              <span>{copy("Drag to reorder", "拖拽调整顺序")}</span>
            </div>
            {groupedNodes.map((group) => (
              <div key={group.phase} className="state-machine-editor__phase-group">
                <div className="state-machine-editor__phase-label">{group.phase}</div>
                <div className="state-machine-editor__phase-items">
                  {group.nodes.map((node) => (
                    <button
                      key={node.id}
                      type="button"
                      draggable
                      className="state-machine-editor__node-item"
                      data-active={node.id === selectedNodeId}
                      onDragStart={() => setDraggingNodeId(node.id)}
                      onDragOver={(event) => event.preventDefault()}
                      onDrop={() => reorderNode(node.id)}
                      onClick={() => setSelectedNodeId(node.id)}
                    >
                      <span className="state-machine-editor__node-icon">
                        {node.isTerminal ? "×" : node.isSoftTerminal ? "~" : node.isTransient ? "↝" : isConfigurableNode(node) ? "⚙" : "•"}
                      </span>
                      <span className="state-machine-editor__node-copy">
                        <strong>{node.label}</strong>
                        <span>{node.id}</span>
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </aside>

          <div className="state-machine-editor__detail">
            {selectedNode ? (
              <>
                <div className="state-machine-editor__detail-header">
                  <div>
                    <div className="state-machine-editor__eyebrow">{copy("Edit node", "编辑节点")}</div>
                    <h3>{selectedNode.label}</h3>
                  </div>
                  <StatusBadge tone={selectedExecutionConfig?.mode === "human_required" ? "warning" : "positive"}>
                    {selectedExecutionConfig?.mode ?? copy("Not configurable", "不可配置")}
                  </StatusBadge>
                </div>

                <div className="state-machine-editor__form-grid">
                  <label className="state-machine-editor__field">
                    <span>ID</span>
                    <input value={selectedNode.id} readOnly className="state-machine-editor__input" />
                  </label>
                  <label className="state-machine-editor__field">
                    <span>{copy("Display label", "显示名称")}</span>
                    <input
                      value={selectedNode.label}
                      onChange={(event) => updateSelectedNode((node) => ({ ...node, label: event.target.value }))}
                      className="state-machine-editor__input"
                    />
                  </label>
                  <label className="state-machine-editor__field">
                    <span>{copy("Phase", "阶段")}</span>
                    <input
                      value={selectedNode.phase}
                      onChange={(event) => updateSelectedNode((node) => ({ ...node, phase: event.target.value }))}
                      className="state-machine-editor__input"
                    />
                  </label>
                  <label className="state-machine-editor__field">
                    <span>{copy("Phase label", "阶段名称")}</span>
                    <input
                      value={selectedNode.phaseLabel}
                      onChange={(event) => updateSelectedNode((node) => ({ ...node, phaseLabel: event.target.value }))}
                      className="state-machine-editor__input"
                    />
                  </label>
                  <label className="state-machine-editor__field">
                    <span>{copy("Waiting party", "默认等待方")}</span>
                    <select
                      value={selectedNode.defaultWaitingParty}
                      onChange={(event) =>
                        updateSelectedNode((node) => ({
                          ...node,
                          defaultWaitingParty: event.target.value as StateNode["defaultWaitingParty"],
                        }))
                      }
                      className="state-machine-editor__input"
                    >
                      <option value="AI">AI</option>
                      <option value="CANDIDATE">{copy("Candidate", "候选人")}</option>
                      <option value="HUMAN">{copy("Human", "人工")}</option>
                      <option value="AUTO">AUTO</option>
                    </select>
                  </label>
                  <label className="state-machine-editor__field">
                    <span>{copy("Milestone", "里程碑")}</span>
                    <select
                      value={selectedNode.milestoneId ?? ""}
                      onChange={(event) =>
                        updateSelectedNode((node) => ({
                          ...node,
                          milestoneId: event.target.value || undefined,
                        }))
                      }
                      className="state-machine-editor__input"
                    >
                      <option value="">{copy("None", "无")}</option>
                      {funnelMilestones.map((milestone) => (
                        <option key={milestone.id} value={milestone.id}>
                          {milestone.id} · {milestone.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="state-machine-editor__field state-machine-editor__field--full">
                    <span>{copy("Description", "说明")}</span>
                    <textarea
                      value={selectedNode.description ?? ""}
                      onChange={(event) => updateSelectedNode((node) => ({ ...node, description: event.target.value }))}
                      className="state-machine-editor__textarea"
                      rows={4}
                    />
                  </label>
                </div>

                <div className="state-machine-editor__flags">
                  {[
                    { key: "isTerminal", label: copy("Terminal", "终止态") },
                    { key: "isSoftTerminal", label: copy("Soft terminal", "软终止态") },
                    { key: "isTransient", label: copy("Transient", "过渡态") },
                    { key: "isSuccess", label: copy("Success", "成功态") },
                  ].map((flag) => (
                    <label key={flag.key} className="state-machine-editor__checkbox">
                      <input
                        type="checkbox"
                        checked={Boolean(selectedNode[flag.key as keyof StateNode])}
                        onChange={(event) =>
                          updateSelectedNode((node) => ({
                            ...node,
                            [flag.key]: event.target.checked,
                          }))
                        }
                      />
                      <span>{flag.label}</span>
                    </label>
                  ))}
                  <label className="state-machine-editor__checkbox">
                    <input
                      type="checkbox"
                      checked={selectedNode.uiConfig?.showInKanban !== false}
                      onChange={(event) =>
                        updateSelectedNode((node) => ({
                          ...node,
                          uiConfig: {
                            ...node.uiConfig,
                            showInKanban: event.target.checked,
                          },
                        }))
                      }
                    />
                    <span>{copy("Show in status board", "在工作台看板显示")}</span>
                  </label>
                  <label className="state-machine-editor__checkbox">
                    <input
                      type="checkbox"
                      checked={Boolean(selectedNode.uiConfig?.showInFunnel)}
                      onChange={(event) =>
                        updateSelectedNode((node) => ({
                          ...node,
                          uiConfig: {
                            ...node.uiConfig,
                            showInFunnel: event.target.checked,
                          },
                        }))
                      }
                    />
                    <span>{copy("Count in funnel", "在漏斗看板计数")}</span>
                  </label>
                </div>

                <Panel
                  title={copy("Execution config", "执行方式")}
                  eyebrow={copy("AI or human", "AI / 人工")}
                  description={copy(
                    "AI/HUMAN nodes can switch execution mode. Candidate-waiting nodes configure retry policy here.",
                    "AI/HUMAN 节点可切换执行方式；等待候选人回复的节点也在这里配置自动重试策略。",
                  )}
                  dense
                >
                  {isConfigurableNode(selectedNode) || supportsRetryPolicy(selectedNode) ? (
                    <div className="state-machine-editor__stack">
                      {isConfigurableNode(selectedNode) ? (
                        <>
                          <div className="state-machine-editor__mode-switch">
                            <label className="state-machine-editor__radio">
                              <input
                                type="radio"
                                checked={(selectedExecutionConfig?.mode ?? "human_required") === "human_required"}
                                disabled={Boolean(selectedExecutionConfig?.locked)}
                                onChange={() => updateSelectedNode((node) => withExecutionConfig(node, (executionConfig) => ({ ...executionConfig, mode: "human_required" })))}
                              />
                              <span>{copy("Human required", "人工介入")}</span>
                            </label>
                            <label className="state-machine-editor__radio">
                              <input
                                type="radio"
                                checked={(selectedExecutionConfig?.mode ?? "human_required") === "ai_auto"}
                                disabled={Boolean(selectedExecutionConfig?.locked)}
                                onChange={() => updateSelectedNode((node) => withExecutionConfig(node, (executionConfig) => ({ ...executionConfig, mode: "ai_auto" })))}
                              />
                              <span>{copy("AI auto", "AI 自动")}</span>
                            </label>
                            {selectedExecutionConfig?.locked ? <StatusBadge tone="warning">{copy("Locked", "锁定")}</StatusBadge> : null}
                          </div>

                          {(selectedExecutionConfig?.mode ?? "human_required") === "human_required" ? (
                            <div className="state-machine-editor__stack">
                              <div className="state-machine-editor__subheader">
                                <strong>{copy("Human actions", "人工动作")}</strong>
                                <button
                                  type="button"
                                  className="state-machine-editor__button"
                                  onClick={() =>
                                    updateSelectedNode((node) =>
                                      withExecutionConfig(node, (executionConfig) => ({
                                        ...executionConfig,
                                        humanActions: [
                                          ...(executionConfig.humanActions ?? []),
                                          defaultHumanAction(executionConfig.humanActions?.length ?? 0),
                                        ],
                                      })),
                                    )
                                  }
                                >
                                  {copy("Add action", "添加操作")}
                                </button>
                              </div>
                              {(selectedExecutionConfig?.humanActions ?? []).map((action, index) => (
                                <div key={`${action.label}-${index}`} className="state-machine-editor__action-row">
                                  <input
                                    value={action.label}
                                    onChange={(event) =>
                                      updateSelectedNode((node) =>
                                        withExecutionConfig(node, (executionConfig) => ({
                                          ...executionConfig,
                                          humanActions: (executionConfig.humanActions ?? []).map((item, itemIndex) =>
                                            itemIndex === index ? { ...item, label: event.target.value } : item,
                                          ),
                                        })),
                                      )
                                    }
                                    className="state-machine-editor__input"
                                    placeholder={copy("Label", "文字")}
                                  />
                                  <select
                                    value={action.toStatus}
                                    onChange={(event) =>
                                      updateSelectedNode((node) =>
                                        withExecutionConfig(node, (executionConfig) => ({
                                          ...executionConfig,
                                          humanActions: (executionConfig.humanActions ?? []).map((item, itemIndex) =>
                                            itemIndex === index ? { ...item, toStatus: event.target.value } : item,
                                          ),
                                        })),
                                      )
                                    }
                                    className="state-machine-editor__input"
                                  >
                                    {draft?.nodes.map((option) => (
                                      <option key={option.id} value={option.id}>
                                        {option.label}
                                      </option>
                                    ))}
                                  </select>
                                  <select
                                    value={action.style}
                                    onChange={(event) =>
                                      updateSelectedNode((node) =>
                                        withExecutionConfig(node, (executionConfig) => ({
                                          ...executionConfig,
                                          humanActions: (executionConfig.humanActions ?? []).map((item, itemIndex) =>
                                            itemIndex === index ? { ...item, style: event.target.value as HumanActionDefinition["style"] } : item,
                                          ),
                                        })),
                                      )
                                    }
                                    className="state-machine-editor__input"
                                  >
                                    <option value="primary">{copy("Primary", "主色")}</option>
                                    <option value="default">{copy("Default", "默认")}</option>
                                    <option value="danger">{copy("Danger", "危险")}</option>
                                  </select>
                                  <label className="state-machine-editor__checkbox">
                                    <input
                                      type="checkbox"
                                      checked={Boolean(action.requiresNote)}
                                      onChange={(event) =>
                                        updateSelectedNode((node) =>
                                          withExecutionConfig(node, (executionConfig) => ({
                                            ...executionConfig,
                                            humanActions: (executionConfig.humanActions ?? []).map((item, itemIndex) =>
                                              itemIndex === index ? { ...item, requiresNote: event.target.checked } : item,
                                            ),
                                          })),
                                        )
                                      }
                                    />
                                    <span>{copy("Requires note", "必填备注")}</span>
                                  </label>
                                </div>
                              ))}
                            </div>
                          ) : (
                            <div className="state-machine-editor__stack">
                              <div className="state-machine-editor__subheader">
                                <strong>{copy("AI criteria", "AI 评估标准")}</strong>
                                {selectedCriteriaReport?.suggestions.length ? (
                                  <StatusBadge tone="warning">
                                    {copy(
                                      `${selectedCriteriaReport.suggestions.length} optimization suggestion(s)`,
                                      `${selectedCriteriaReport.suggestions.length} 条优化建议`,
                                    )}
                                  </StatusBadge>
                                ) : null}
                              </div>
                              <label className="state-machine-editor__field">
                                <span>{copy("Criteria type", "标准类型")}</span>
                                <select
                                  value={selectedCriteriaRef?.type ?? "skill"}
                                  onChange={(event) =>
                                    updateSelectedNode((node) =>
                                      withCriteriaRef(node, (criteriaRef) => ({
                                        ...criteriaRef,
                                        type: event.target.value as StateCriteriaRef["type"],
                                      })),
                                    )
                                  }
                                  className="state-machine-editor__input"
                                >
                                  <option value="skill">Skill</option>
                                  <option value="prompt">Prompt</option>
                                  <option value="rule">{copy("Rule", "规则表达式")}</option>
                                </select>
                              </label>
                              {(selectedCriteriaRef?.type ?? "skill") === "skill" ? (
                                <label className="state-machine-editor__field">
                                  <span>Skill</span>
                                  <select
                                    value={selectedCriteriaRef?.skillId ?? ""}
                                    onChange={(event) =>
                                      updateSelectedNode((node) =>
                                        withCriteriaRef(node, (criteriaRef) => ({
                                          ...criteriaRef,
                                          type: "skill",
                                          skillId: event.target.value,
                                        })),
                                      )
                                    }
                                    className="state-machine-editor__input"
                                  >
                                    <option value="">{copy("Select a skill", "选择 Skill")}</option>
                                    {skills.map((skill) => (
                                      <option key={skill.id} value={skill.skillId || skill.id}>
                                        {skill.name}
                                      </option>
                                    ))}
                                  </select>
                                </label>
                              ) : null}
                              {(selectedCriteriaRef?.type ?? "skill") === "prompt" ? (
                                <label className="state-machine-editor__field">
                                  <span>{copy("Prompt text", "Prompt 文本")}</span>
                                  <textarea
                                    value={selectedCriteriaRef?.promptText ?? ""}
                                    onChange={(event) =>
                                      updateSelectedNode((node) =>
                                        withCriteriaRef(node, (criteriaRef) => ({
                                          ...criteriaRef,
                                          type: "prompt",
                                          promptText: event.target.value,
                                        })),
                                      )
                                    }
                                    rows={4}
                                    className="state-machine-editor__textarea"
                                  />
                                </label>
                              ) : null}
                              {(selectedCriteriaRef?.type ?? "skill") === "rule" ? (
                                <label className="state-machine-editor__field">
                                  <span>{copy("Rule expression", "规则表达式")}</span>
                                  <input
                                    value={selectedCriteriaRef?.ruleExpression ?? ""}
                                    onChange={(event) =>
                                      updateSelectedNode((node) =>
                                        withCriteriaRef(node, (criteriaRef) => ({
                                          ...criteriaRef,
                                          type: "rule",
                                          ruleExpression: event.target.value,
                                        })),
                                      )
                                    }
                                    className="state-machine-editor__input"
                                  />
                                </label>
                              ) : null}
                              <label className="state-machine-editor__field">
                                <span>{copy("Pass threshold", "通过阈值")}</span>
                                <input
                                  type="number"
                                  value={selectedCriteriaRef?.passThreshold ?? ""}
                                  onChange={(event) =>
                                    updateSelectedNode((node) =>
                                      withCriteriaRef(node, (criteriaRef) => ({
                                        ...criteriaRef,
                                        passThreshold: event.target.value ? Number(event.target.value) : undefined,
                                      })),
                                    )
                                  }
                                  className="state-machine-editor__input"
                                />
                              </label>

                              <div className="state-machine-editor__suggestion-block">
                                <div className="state-machine-editor__suggestion-metrics">
                                  <span>{copy("Sample", "样本")} · {selectedCriteriaReport?.metrics.sampleSize ?? 0}</span>
                                  <span>
                                    {copy("Override", "覆盖率")} · {selectedCriteriaReport?.metrics.overrideRate != null
                                      ? `${Math.round((selectedCriteriaReport.metrics.overrideRate ?? 0) * 100)}%`
                                      : copy("N/A", "暂无")}
                                  </span>
                                  <span>
                                    {copy("Accuracy", "准确率")} · {selectedCriteriaReport?.metrics.accuracyRate != null
                                      ? `${Math.round((selectedCriteriaReport.metrics.accuracyRate ?? 0) * 100)}%`
                                      : copy("N/A", "暂无")}
                                  </span>
                                </div>
                                {selectedCriteriaReport ? (
                                  <>
                                    <div className="state-machine-editor__suggestion-summary">{selectedCriteriaReport.summary}</div>
                                    {selectedCriteriaReport.suggestions.length ? (
                                      <div className="state-machine-editor__suggestion-list">
                                        {selectedCriteriaReport.suggestions.map((
                                          suggestion: StateCriteriaOptimizationReport["suggestions"][number],
                                          index: number,
                                        ) => (
                                          <div key={`${suggestion.kind}-${index}`} className="state-machine-editor__suggestion-card">
                                            <div className="state-machine-editor__subheader">
                                              <strong>{suggestion.summary}</strong>
                                              <StatusBadge tone={suggestion.kind === "switch_skill" ? "warning" : "neutral"}>
                                                {suggestion.kind === "switch_skill" ? copy("Switch skill", "切换 Skill") : copy("Adjust threshold", "调阈值")}
                                              </StatusBadge>
                                            </div>
                                            <div className="state-machine-editor__suggestion-copy">
                                              <span>{suggestion.rationale}</span>
                                              {suggestion.suggestedSkillName ? (
                                                <span>{copy("Suggested skill", "建议 Skill")} · {suggestion.suggestedSkillName}</span>
                                              ) : null}
                                              {suggestion.proposedCriteriaRef.passThreshold != null ? (
                                                <span>{copy("Suggested threshold", "建议阈值")} · {suggestion.proposedCriteriaRef.passThreshold}</span>
                                              ) : null}
                                            </div>
                                            <div className="state-machine-editor__suggestion-actions">
                                              <button
                                                type="button"
                                                className="state-machine-editor__button"
                                                onClick={() => applyCriteriaSuggestion(selectedCriteriaReport, index)}
                                              >
                                                {copy("Apply to draft", "应用到草稿")}
                                              </button>
                                            </div>
                                          </div>
                                        ))}
                                      </div>
                                    ) : (
                                      <div className="state-machine-editor__empty">
                                        {copy("No criteria optimization suggestion for this node yet.", "当前节点还没有可采纳的 criteriaRef 优化建议。")}
                                      </div>
                                    )}
                                  </>
                                ) : (
                                  <div className="state-machine-editor__empty">
                                    {copy("No optimization data for this node yet.", "当前节点还没有足够的优化统计数据。")}
                                  </div>
                                )}
                              </div>
                            </div>
                          )}
                        </>
                      ) : null}

                      {supportsRetryPolicy(selectedNode) ? (
                        <div className="state-machine-editor__stack">
                          <div className="state-machine-editor__subheader">
                            <strong>{copy("Retry policy", "自动重试策略")}</strong>
                            <StatusBadge tone="warning">{copy("Waiting on candidate", "等待候选人")}</StatusBadge>
                          </div>
                          <div className="state-machine-editor__suggestion-copy">
                            <span>
                              {copy(
                                "The runtime will retry this node automatically. After the configured close window passes without a reply, it will close to no_response.",
                                "运行时会先自动重试该节点；如果在配置的关闭时限内仍未收到回复，就会自动关闭到 no_response。",
                              )}
                            </span>
                          </div>
                          <label className="state-machine-editor__field">
                            <span>{copy("Max retries", "最大重试次数")}</span>
                            <input
                              type="number"
                              min={0}
                              value={selectedRetryPolicy?.maxRetries ?? 0}
                              onChange={(event) =>
                                updateSelectedNode((node) =>
                                  withRetryPolicy(node, (retryPolicy) => ({
                                    ...retryPolicy,
                                    maxRetries: Math.max(Number(event.target.value || 0), 0),
                                  })),
                                )
                              }
                              className="state-machine-editor__input"
                            />
                          </label>
                          <label className="state-machine-editor__field">
                            <span>{copy("Retry after (hours)", "每次重试间隔（小时）")}</span>
                            <input
                              type="number"
                              min={1}
                              value={selectedRetryPolicy?.retryAfterHours ?? 48}
                              onChange={(event) =>
                                updateSelectedNode((node) =>
                                  withRetryPolicy(node, (retryPolicy) => ({
                                    ...retryPolicy,
                                    retryAfterHours: Math.max(Number(event.target.value || 1), 1),
                                  })),
                                )
                              }
                              className="state-machine-editor__input"
                            />
                          </label>
                          <label className="state-machine-editor__field">
                            <span>{copy("Close after (hours)", "自动关闭时限（小时）")}</span>
                            <input
                              type="number"
                              min={1}
                              value={selectedRetryPolicy?.closeAfterHours ?? 120}
                              onChange={(event) =>
                                updateSelectedNode((node) =>
                                  withRetryPolicy(node, (retryPolicy) => ({
                                    ...retryPolicy,
                                    closeAfterHours: Math.max(Number(event.target.value || 1), 1),
                                  })),
                                )
                              }
                              className="state-machine-editor__input"
                            />
                          </label>
                        </div>
                      ) : null}
                    </div>
                  ) : (
                    <div className="state-machine-editor__empty">
                      {copy("This node is not configurable because it is transient or intentionally closed by design.", "该节点为过渡态，或属于默认关闭态，因此不提供运行策略配置。")}
                    </div>
                  )}
                </Panel>

                <Panel
                  title={copy("Legal transitions", "合法转换")}
                  eyebrow={copy("Read only", "只读")}
                  description={copy("Transitions attached to the selected node.", "与当前节点关联的合法转换。")}
                  dense
                >
                  <div className="state-machine-editor__transition-list">
                    {transitionsForNode.map((transition) => (
                      <div key={transition.id} className="state-machine-editor__transition-item">
                        <strong>{transition.label ?? transition.id}</strong>
                        <span>
                          {transition.fromState} → {transition.toState}
                        </span>
                        <span>{transition.condition ?? copy("No condition", "无条件说明")}</span>
                      </div>
                    ))}
                    {!transitionsForNode.length ? (
                      <div className="state-machine-editor__empty">{copy("No transitions linked to this node.", "当前节点没有关联转换。")}</div>
                    ) : null}
                  </div>
                </Panel>
              </>
            ) : (
              <div className="state-machine-editor__empty">{copy("Select a node to edit.", "请选择一个节点开始编辑。")}</div>
            )}
          </div>
        </div>
      </Panel>

      <Panel
        title={copy("Version history", "版本历史")}
        eyebrow={copy("Read only history", "只读历史")}
        description={copy(
          "Compare two saved versions to see node and transition changes before publishing another update.",
          "对比两个已发布版本，查看节点和转换的变化，再决定是否发布新版本。",
        )}
      >
        <div className="state-machine-editor__history-grid">
          <label className="state-machine-editor__field">
            <span>{copy("Base version", "基准版本")}</span>
            <select value={compareLeftVersion ?? ""} onChange={(event) => setCompareLeftVersion(Number(event.target.value))} className="state-machine-editor__input">
              {versions.map((version) => (
                <option key={version.version} value={version.version}>
                  v{version.version} · {formatCompactDate(version.publishedAt)}
                </option>
              ))}
            </select>
          </label>
          <label className="state-machine-editor__field">
            <span>{copy("Compare to", "对比版本")}</span>
            <select value={compareRightVersion ?? ""} onChange={(event) => setCompareRightVersion(Number(event.target.value))} className="state-machine-editor__input">
              {versions.map((version) => (
                <option key={version.version} value={version.version}>
                  v{version.version} · {formatCompactDate(version.publishedAt)}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="state-machine-editor__history-meta">
          <div>
            <strong>{copy("Base", "基准")}</strong>
            <span>{compareLeft ? `v${compareLeft.version} · ${compareLeft.updatedBy}` : "—"}</span>
            <span>{compareLeft?.changeSummary || copy("No summary", "无变更摘要")}</span>
          </div>
          <div>
            <strong>{copy("Target", "目标")}</strong>
            <span>{compareRight ? `v${compareRight.version} · ${compareRight.updatedBy}` : "—"}</span>
            <span>{compareRight?.changeSummary || copy("No summary", "无变更摘要")}</span>
          </div>
        </div>
        <div className="state-machine-editor__diff-grid">
          <div className="state-machine-editor__diff-card">
            <strong>{copy("Added nodes", "新增节点")}</strong>
            <ul>{diffSummary.addedNodes.map((item) => <li key={item}>{item}</li>)}</ul>
          </div>
          <div className="state-machine-editor__diff-card">
            <strong>{copy("Removed nodes", "删除节点")}</strong>
            <ul>{diffSummary.removedNodes.map((item) => <li key={item}>{item}</li>)}</ul>
          </div>
          <div className="state-machine-editor__diff-card">
            <strong>{copy("Changed nodes", "变更节点")}</strong>
            <ul>{diffSummary.changedNodes.map((item) => <li key={item}>{item}</li>)}</ul>
          </div>
          <div className="state-machine-editor__diff-card">
            <strong>{copy("Transition diff", "转换变更")}</strong>
            <ul>
              {diffSummary.addedTransitions.map((item) => <li key={`add-${item}`}>+ {item}</li>)}
              {diffSummary.removedTransitions.map((item) => <li key={`remove-${item}`}>- {item}</li>)}
            </ul>
          </div>
        </div>

        <label className="state-machine-editor__field">
          <span>{copy("Change summary", "变更摘要")}</span>
          <textarea
            value={changeSummary}
            onChange={(event) => setChangeSummary(event.target.value)}
            rows={3}
            className="state-machine-editor__textarea"
            placeholder={copy("Describe what changed in this version.", "简要描述这次版本修改内容。")}
          />
        </label>
      </Panel>
    </div>
  );
}
