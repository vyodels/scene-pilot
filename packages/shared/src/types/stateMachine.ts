export type StateWaitingParty = "AI" | "CANDIDATE" | "HUMAN" | "AUTO";
export type StateExecutionMode = "ai_auto" | "human_required";
export type StateCriteriaRefType = "skill" | "prompt" | "rule";
export type HumanActionStyle = "primary" | "default" | "danger";
export type TransitionTrigger = "auto" | "agent" | "human" | "system";
export type TransitionActor = "agent" | "recruiter" | "system";
export type TransitionHistoryActor = "agent" | "agent_override" | "system" | "recruiter" | "recruiter_override";

export interface StateCriteriaRef {
  type: StateCriteriaRefType;
  skillId?: string;
  promptText?: string;
  ruleExpression?: string;
  passThreshold?: number;
}

export interface HumanActionDefinition {
  label: string;
  toStatus: string;
  style: HumanActionStyle;
  requiresNote?: boolean;
}

export interface StateRetryPolicy {
  maxRetries: number;
  retryAfterHours: number;
  closeAfterHours: number;
}

export interface StateExecutionConfig {
  mode: StateExecutionMode;
  criteriaRef?: StateCriteriaRef;
  humanActions?: HumanActionDefinition[];
  locked?: boolean;
}

export interface StateNodeUiConfig {
  color?: "default" | "warning" | "success" | "danger" | "info";
  showInKanban?: boolean;
  showInFunnel?: boolean;
}

export interface StateNode {
  id: string;
  label: string;
  phase: string;
  phaseLabel: string;
  defaultWaitingParty: StateWaitingParty;
  isTerminal: boolean;
  isSuccess: boolean;
  isSoftTerminal: boolean;
  isTransient: boolean;
  milestoneId?: string;
  sortOrder: number;
  description?: string;
  executionConfig?: StateExecutionConfig;
  retryPolicy?: StateRetryPolicy;
  uiConfig?: StateNodeUiConfig;
}

export interface StateTransition {
  id: string;
  fromState: string;
  toState: string;
  trigger: TransitionTrigger;
  condition?: string;
  requiresNote?: boolean;
  label?: string;
  allowedActors?: TransitionActor[];
}

export interface RecruitmentStateMachine {
  version: number;
  updatedAt: string;
  updatedBy: string;
  nodes: StateNode[];
  transitions: StateTransition[];
  globalTransitions: StateTransition[];
}

export interface RecruitmentStateMachineVersionRecord extends RecruitmentStateMachine {
  changeSummary?: string | null;
  versionMetadata?: Record<string, unknown>;
  publishedAt: string;
  createdAt: string;
}

export interface RecruitmentStateMachineUpdatePayload {
  updatedBy: string;
  changeSummary?: string;
  nodes: StateNode[];
  transitions: StateTransition[];
  globalTransitions: StateTransition[];
  versionMetadata?: Record<string, unknown>;
}

export interface StateCriteriaOptimizationMetrics {
  sampleSize: number;
  aiDecisionCount: number;
  recruiterOverrideCount: number;
  accuracyRate?: number;
  overrideRate?: number;
  deeperOverrideCount: number;
  shallowerOverrideCount: number;
}

export interface StateCriteriaOptimizationSuggestion {
  kind: "adjust_threshold" | "switch_skill";
  summary: string;
  rationale: string;
  confidence: "low" | "medium" | "high";
  proposedCriteriaRef: StateCriteriaRef;
  suggestedSkillId?: string;
  suggestedSkillName?: string;
}

export interface StateCriteriaOptimizationReport {
  nodeId: string;
  nodeLabel: string;
  currentCriteriaRef?: StateCriteriaRef;
  currentSkillId?: string;
  currentSkillName?: string;
  metrics: StateCriteriaOptimizationMetrics;
  suggestions: StateCriteriaOptimizationSuggestion[];
  summary: string;
}

export interface CandidateStatusTransition {
  id: string;
  candidateId: string;
  fromStatus: string;
  toStatus: string;
  fromStatusLabel: string;
  toStatusLabel: string;
  actor: TransitionHistoryActor;
  actorId?: string;
  trigger: string;
  note?: string;
  overrideReason?: string;
  isOverride: boolean;
  milestoneUpdated?: string;
  metadata?: Record<string, unknown>;
  createdAt: string;
}

interface CandidateTransitionPayloadBase {
  toStatus: string;
  trigger: string;
  note?: string;
  phaseKey?: string;
  phaseLabel?: string;
  stageKey?: string;
  stageLabel?: string;
  actorId?: string;
  metadata?: Record<string, unknown>;
  interviewRound?: number;
  contactChannels?: string[];
}

export type CandidateTransitionPayload =
  | (CandidateTransitionPayloadBase & {
      actor: TransitionActor;
    })
  | (CandidateTransitionPayloadBase & {
      actor: "recruiter_override" | "agent_override";
      overrideReason: string;
    });
