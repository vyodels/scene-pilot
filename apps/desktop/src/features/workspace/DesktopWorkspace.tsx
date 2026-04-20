import React, { startTransition, useCallback, useEffect, useMemo, useState } from "react";
import type {
  ApplicationTransitionPayload,
  RecruitmentStateMachine,
} from "@scene-pilot/shared";
import { getFunnelMilestone } from "@scene-pilot/shared";
import { AppLayout, Panel, SectionTabs, Sidebar, StatusBadge, TopBar } from "../../components";
import { ChatOverlay, FloatingBubble, useChatOverlay } from "../chat-overlay";
import { apiClient } from "../../lib/api";
import { formatDateTime } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import type {
  AgentSnapshot,
  ApplicationThreadRecord,
  DashboardSummary,
  JobDescriptionSummaryRecord,
  McpPresetTemplateRecord,
  McpServerRecord,
  SettingsSnapshot,
  WorkspaceTab,
} from "../../lib/types";
import { CandidatesKanbanView, type CandidatesKanbanTab } from "../candidates/CandidatesKanbanView";
import { DashboardView } from "../dashboard/DashboardView";
import { buildApplicationViewModels, type ApplicationViewModel } from "../kanban-shared/kanbanUtils";
import { SettingsView } from "../settings/SettingsView";

const emptySettings: SettingsSnapshot = {
  locale: "en-US",
  timezone: "Asia/Shanghai",
  intranetEnabled: false,
  desktopApprovalsOnly: true,
  autonomyEnabled: false,
  skillHealthAutonomyEnabled: false,
  skillHealthAutonomyIntervalSeconds: 300,
  providers: [],
  intranetSync: {
    enabled: false,
    apiPath: "/api/recruit-agent/sync",
    timeoutSeconds: 10,
  },
  platform: {
    name: "本地执行配置",
    account: "未连接",
    cooldownDays: 30,
    allowOutboundMessaging: false,
    maxConcurrentRuns: 1,
    minFunnelCandidates: 0,
  },
};

const emptyAgent: AgentSnapshot = {
  status: "idle",
  activeTask: "waiting_for_backend",
  browserLock: "free",
  uptime: "00:00:00",
  queueDepth: 0,
  tokenBudgetUsed: 0,
  health: "warning",
};

const emptySummary: DashboardSummary = {
  metrics: [],
  pipeline: [],
  timeline: [],
  alerts: [],
  applications: [],
  applicationFollowUpSummaryDefinitions: [],
  playbooks: [],
  skills: [],
  approvals: [],
  agent: emptyAgent,
  settings: emptySettings,
};

function funnelStageDefinitions(copy: (en: string, zh: string) => string): Array<{ label: string; phases: string[] }> {
  return [
    { label: copy("Discovery & AI screening", "发现与 AI 在线评估"), phases: ["A"] },
    { label: copy("Outreach", "发起沟通与建立对话"), phases: ["B"] },
    { label: copy("Resume & evaluation", "获取简历与评估"), phases: ["C", "D", "E"] },
    { label: copy("Contact acquired", "获取联系方式"), phases: ["F"] },
    { label: copy("Interview & outcome", "面试与结果"), phases: ["G", "H"] },
  ];
}

function resolveFunnelStageDepth(model: ApplicationViewModel, stages: Array<{ label: string; phases: string[] }>): number {
  const depthByPhase = new Map<string, number>();
  stages.forEach((stage, index) => {
    stage.phases.forEach((phase) => depthByPhase.set(phase, index));
  });
  const currentDepth = model.currentNode?.phase && model.currentNode.phase !== "Z"
    ? (depthByPhase.get(model.currentNode.phase) ?? -1)
    : -1;
  const deepestDepth = getFunnelMilestone(model.deepestMilestone)?.phase
    ? (depthByPhase.get(getFunnelMilestone(model.deepestMilestone)?.phase ?? "") ?? -1)
    : -1;
  return Math.max(currentDepth, deepestDepth);
}

interface JdWorkspaceGroup {
  key: string;
  jobDescriptionId?: string | null;
  job: JobDescriptionSummaryRecord;
  applications: ApplicationViewModel[];
  macroCounts: Record<string, number>;
}

function isPresentText(value: string | null | undefined): value is string {
  return Boolean(value && value.trim());
}

function jobGroupKey(job: Pick<JobDescriptionSummaryRecord, "jobDescriptionId" | "title">): string {
  return job.jobDescriptionId || job.title || "unknown-jd";
}

function JdWorkspaceSurface({
  applications,
  jobDescriptions,
}: {
  applications: ApplicationViewModel[];
  jobDescriptions: JobDescriptionSummaryRecord[];
}): JSX.Element {
  const { copy } = useI18n();
  const funnelStages = useMemo(() => funnelStageDefinitions(copy), [copy]);
  const jdGroups = useMemo((): JdWorkspaceGroup[] => {
    const groupedApplications = new Map<string, ApplicationViewModel[]>();
    for (const application of applications) {
      const key = jobGroupKey({
        jobDescriptionId: application.application.jobDescriptionId,
        title: application.application.jobDescription.title || copy("Unassigned role", "未分配岗位"),
      });
      const existing = groupedApplications.get(key) ?? [];
      existing.push(application);
      groupedApplications.set(key, existing);
    }

    const groups = jobDescriptions.map((job) => {
      const key = jobGroupKey(job);
      const grouped = groupedApplications.get(key) ?? [];
      const macroCounts = grouped.reduce<Record<string, number>>((accumulator, application) => {
        const depth = resolveFunnelStageDepth(application, funnelStages);
        for (let index = 0; index <= depth; index += 1) {
          const stage = funnelStages[index];
          if (!stage) {
            continue;
          }
          accumulator[stage.label] = (accumulator[stage.label] ?? 0) + 1;
        }
        return accumulator;
      }, {});
      return {
        key,
        jobDescriptionId: job.jobDescriptionId,
        job,
        applications: grouped,
        macroCounts,
      };
    });

    return groups.sort((left, right) => {
      const countDiff = right.applications.length - left.applications.length;
      if (countDiff !== 0) {
        return countDiff;
      }
      return left.job.title.localeCompare(right.job.title, "zh-CN");
    });
  }, [applications, copy, jobDescriptions]);
  const [selectedJdKey, setSelectedJdKey] = useState<string | null>(null);

  useEffect(() => {
    if (!jdGroups.length) {
      setSelectedJdKey(null);
      return;
    }
    if (!selectedJdKey || !jdGroups.some((group) => group.key === selectedJdKey)) {
      setSelectedJdKey(jdGroups[0]?.key ?? null);
    }
  }, [jdGroups, selectedJdKey]);

  const selectedGroup = useMemo(
    () => jdGroups.find((group) => group.key === selectedJdKey) ?? jdGroups[0] ?? null,
    [jdGroups, selectedJdKey],
  );

  const detailRows = selectedGroup ? [
    { label: copy("Location", "地点"), value: selectedGroup.job.location },
    { label: copy("Compensation", "薪资"), value: selectedGroup.job.compensationText },
    { label: copy("Company", "公司"), value: selectedGroup.job.companyName },
    { label: copy("Department", "部门"), value: selectedGroup.job.department },
    { label: copy("Employment type", "用工类型"), value: selectedGroup.job.employmentType },
    {
      label: copy("Headcount", "招聘人数"),
      value: selectedGroup.job.headcount != null ? String(selectedGroup.job.headcount) : null,
    },
    { label: copy("Experience", "经验要求"), value: selectedGroup.job.experienceRequirement },
    { label: copy("Education", "学历要求"), value: selectedGroup.job.educationRequirement },
    { label: copy("Source", "来源"), value: selectedGroup.job.source },
    { label: copy("Status", "状态"), value: selectedGroup.job.status },
    {
      label: copy("Created", "创建时间"),
      value: selectedGroup.job.createdAt != null ? formatDateTime(selectedGroup.job.createdAt) : null,
    },
    {
      label: copy("Updated", "更新时间"),
      value: selectedGroup.job.updatedAt != null ? formatDateTime(selectedGroup.job.updatedAt) : null,
    },
  ].filter((item) => isPresentText(item.value)) : [];

  return (
    <div style={{ display: "grid", gap: "var(--space-4)" }}>
      {!jdGroups.length ? (
        <Panel
          title={copy("JD management", "JD 管理")}
          eyebrow={copy("Roles", "岗位")}
          description={copy("No job description has been synced into the workspace yet.", "当前还没有同步到工作区的 JD。")}
        >
          <div
            style={{
              padding: "var(--space-4)",
              borderRadius: "var(--radius-md)",
              border: "1px dashed var(--border-line)",
              background: "var(--bg-subtle)",
              color: "var(--text-secondary)",
              fontSize: "var(--font-size-sm)",
              lineHeight: 1.6,
            }}
          >
            {copy("Once a JD is synced, its business details and funnel summary will appear here.", "JD 同步后，这里会展示该岗位的业务详情和漏斗摘要。")}
          </div>
        </Panel>
      ) : (
        <div
          style={{
            display: "grid",
            gap: "var(--space-4)",
            gridTemplateColumns: "minmax(320px, 420px) minmax(0, 1fr)",
            alignItems: "start",
          }}
        >
          <div style={{ display: "grid", gap: "var(--space-3)" }}>
            {jdGroups.map((group) => (
              <button
                key={group.key}
                type="button"
                onClick={() => setSelectedJdKey(group.key)}
                style={{
                  textAlign: "left",
                  padding: "var(--space-4)",
                  borderRadius: "var(--radius-md)",
                  border: selectedJdKey === group.key ? "1px solid var(--brand-primary)" : "1px solid var(--border-line)",
                  background: selectedJdKey === group.key ? "var(--brand-primary-soft)" : "var(--bg-card)",
                  cursor: "pointer",
                }}
              >
                <div style={{ fontWeight: 600, color: "var(--text-primary)" }}>{group.job.title}</div>
                <div
                  style={{
                    marginTop: "var(--space-2)",
                    fontSize: "var(--font-size-sm)",
                    color: "var(--text-secondary)",
                    lineHeight: 1.6,
                  }}
                >
                  {group.job.summary || group.job.description || copy("No JD summary available yet.", "当前还没有 JD 摘要。")}
                </div>
                <div
                  style={{
                    display: "flex",
                    gap: "var(--space-2)",
                    flexWrap: "wrap",
                    marginTop: "var(--space-3)",
                  }}
                >
                  <StatusBadge tone="neutral">
                    {copy(`${group.applications.length} applications`, `${group.applications.length} 条申请`)}
                  </StatusBadge>
                  {group.job.compensationText ? <StatusBadge tone="neutral">{group.job.compensationText}</StatusBadge> : null}
                  {group.job.location ? <StatusBadge tone="neutral">{group.job.location}</StatusBadge> : null}
                </div>
              </button>
            ))}
          </div>

          <Panel
            key={selectedGroup?.key || "jd-detail"}
            title={selectedGroup?.job.title || copy("JD detail", "JD 详情")}
            eyebrow={copy("JD detail", "JD 详情")}
            description={copy("Business details and funnel summary of the selected role.", "当前选中岗位的业务详情与漏斗摘要。")}
          >
            {selectedGroup ? (
              <div style={{ display: "grid", gap: "var(--space-4)" }}>
                <div
                  style={{
                    display: "flex",
                    gap: "var(--space-2)",
                    flexWrap: "wrap",
                  }}
                >
                  <StatusBadge tone="neutral">
                    {copy(`${selectedGroup.applications.length} applications`, `${selectedGroup.applications.length} 条申请`)}
                  </StatusBadge>
                  {selectedGroup.job.status ? <StatusBadge tone="neutral">{selectedGroup.job.status}</StatusBadge> : null}
                  {selectedGroup.job.source ? <StatusBadge tone="neutral">{selectedGroup.job.source}</StatusBadge> : null}
                </div>

                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                    gap: "var(--space-3)",
                  }}
                >
                  {detailRows.map((item) => (
                    <div
                      key={item.label}
                      style={{
                        padding: "var(--space-3)",
                        borderRadius: "var(--radius-md)",
                        border: "1px solid var(--border-line)",
                        background: "var(--bg-subtle)",
                      }}
                    >
                      <div style={{ fontSize: "var(--font-size-xs)", color: "var(--text-secondary)" }}>{item.label}</div>
                      <div style={{ marginTop: "var(--space-1)", color: "var(--text-primary)", lineHeight: 1.5 }}>{item.value}</div>
                    </div>
                  ))}
                </div>

                {selectedGroup.job.summary ? (
                  <div>
                    <div style={{ fontSize: "var(--font-size-xs)", color: "var(--text-secondary)" }}>{copy("Summary", "摘要")}</div>
                    <div style={{ marginTop: "var(--space-1)", color: "var(--text-regular)", lineHeight: 1.7 }}>{selectedGroup.job.summary}</div>
                  </div>
                ) : null}

                {selectedGroup.job.description ? (
                  <div>
                    <div style={{ fontSize: "var(--font-size-xs)", color: "var(--text-secondary)" }}>{copy("Description", "描述")}</div>
                    <div style={{ marginTop: "var(--space-1)", color: "var(--text-regular)", lineHeight: 1.7 }}>{selectedGroup.job.description}</div>
                  </div>
                ) : null}

                {selectedGroup.job.requirements ? (
                  <div>
                    <div style={{ fontSize: "var(--font-size-xs)", color: "var(--text-secondary)" }}>{copy("Requirements", "要求")}</div>
                    <div style={{ marginTop: "var(--space-1)", color: "var(--text-regular)", lineHeight: 1.7 }}>{selectedGroup.job.requirements}</div>
                  </div>
                ) : null}

                {selectedGroup.job.benefitTags.length ? (
                  <div>
                    <div style={{ fontSize: "var(--font-size-xs)", color: "var(--text-secondary)" }}>{copy("Benefits", "福利标签")}</div>
                    <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap", marginTop: "var(--space-2)" }}>
                      {selectedGroup.job.benefitTags.map((tag) => (
                        <StatusBadge key={tag} tone="neutral">{tag}</StatusBadge>
                      ))}
                    </div>
                  </div>
                ) : null}

                <div>
                  <div style={{ fontSize: "var(--font-size-xs)", color: "var(--text-secondary)" }}>{copy("Funnel snapshot", "漏斗快照")}</div>
                  <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap", marginTop: "var(--space-2)" }}>
                    {Object.entries(selectedGroup.macroCounts).length ? Object.entries(selectedGroup.macroCounts).map(([label, count]) => (
                      <StatusBadge key={label} tone="neutral">
                        {label} · {count}
                      </StatusBadge>
                    )) : (
                      <StatusBadge tone="neutral">{copy("No candidate yet", "暂无候选人")}</StatusBadge>
                    )}
                  </div>
                </div>
              </div>
            ) : (
                <div
                  style={{
                    padding: "var(--space-4)",
                    borderRadius: "var(--radius-md)",
                    border: "1px dashed var(--border-line)",
                    background: "var(--bg-subtle)",
                    color: "var(--text-secondary)",
                    fontSize: "var(--font-size-sm)",
                    lineHeight: 1.6,
                  }}
                >
                  {copy(
                    "Select a JD card on the left to inspect its details.",
                    "请先在左侧选择一个 JD 查看详情。",
                  )}
                </div>
            )}
          </Panel>
        </div>
      )}
    </div>
  );
}

export function DesktopWorkspace(): JSX.Element {
  const { copy } = useI18n();
  const { open, isOpen } = useChatOverlay();
  const [tab, setTab] = useState<WorkspaceTab>("home");
  const [summary, setSummary] = useState<DashboardSummary>(emptySummary);
  const [jobDescriptions, setJobDescriptions] = useState<JobDescriptionSummaryRecord[]>([]);
  const [applicationThreads, setApplicationThreads] = useState<ApplicationThreadRecord[]>([]);
  const [stateMachine, setStateMachine] = useState<RecruitmentStateMachine | null>(null);
  const [mcpPresets, setMcpPresets] = useState<McpPresetTemplateRecord[]>([]);
  const [mcpServers, setMcpServers] = useState<McpServerRecord[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [settingsLoaded, setSettingsLoaded] = useState(false);
  const [transport, setTransport] = useState(apiClient.describe().transport);
  const [errorMessage, setErrorMessage] = useState<string>();
  const [candidateWorkspaceFocus, setCandidateWorkspaceFocus] = useState<{
    applicationId?: string;
    conversationToken: number;
  }>({
    applicationId: undefined,
    conversationToken: 0,
  });
  const [candidateKanbanTab, setCandidateKanbanTab] = useState<CandidatesKanbanTab>("funnel");

  const loadCoreWorkspace = useCallback(async () => {
    setRefreshing(true);
    try {
      const [nextSummary, nextThreads, nextStateMachine, nextJobDescriptions] = await Promise.all([
        apiClient.getDashboardSummary(),
        apiClient.listApplicationThreads(),
        apiClient.getStateMachine(),
        apiClient.listJobDescriptions(),
      ]);

      startTransition(() => {
        setSummary(nextSummary);
        setJobDescriptions(nextJobDescriptions);
        setApplicationThreads(nextThreads);
        setStateMachine(nextStateMachine);
      });
      setTransport("http");
      setErrorMessage(undefined);
    } catch (error) {
      setTransport("offline");
      setErrorMessage(error instanceof Error ? error.message : copy("Failed to refresh workspace.", "刷新工作区失败。"));
    } finally {
      setRefreshing(false);
    }
  }, [copy]);

  const loadSettingsWorkspace = useCallback(async () => {
    try {
      const [nextPresets, nextServers] = await Promise.all([
        apiClient.listMcpPresets(),
        apiClient.listMcpServers(),
      ]);
      setMcpPresets(nextPresets);
      setMcpServers(nextServers);
      setSettingsLoaded(true);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : copy("Failed to load settings tools.", "加载设置工具失败。"));
    }
  }, [copy]);

  const refreshWorkspace = useCallback(async () => {
    await loadCoreWorkspace();
    if (tab === "settings" || settingsLoaded) {
      await loadSettingsWorkspace();
    }
  }, [loadCoreWorkspace, loadSettingsWorkspace, settingsLoaded, tab]);

  useEffect(() => {
    void loadCoreWorkspace();

    const interval = window.setInterval(() => {
      void loadCoreWorkspace();
    }, 10000);

    return () => {
      window.clearInterval(interval);
    };
  }, [loadCoreWorkspace]);

  useEffect(() => {
    if (tab === "settings" && !settingsLoaded) {
      void loadSettingsWorkspace();
    }
  }, [loadSettingsWorkspace, settingsLoaded, tab]);

  const sectionMeta = useMemo(
    (): Record<WorkspaceTab, { eyebrow: string; title: string; description: string }> => ({
      home: {
        eyebrow: copy("Today", "今日工作"),
        title: copy("Home", "首页"),
        description: copy(
          "Start from recruiter queues, blocked items, and the next actions that matter today.",
          "从招聘待办、阻塞事项和今天最重要的下一步动作开始。",
        ),
      },
      candidates: {
        eyebrow: copy("Candidate pipeline", "候选人漏斗"),
        title: copy("Candidates", "候选人"),
        description: copy(
          "Review, triage, and progress active candidates through the hiring workflow.",
          "在招聘工作流中审阅、分流并推进活跃候选人。",
        ),
      },
      settings: {
        eyebrow: copy("Tools and connections", "工具与连接"),
        title: copy("Settings", "设置"),
        description: copy(
          "Configure model access, external tools, sync preferences, and local review rules.",
          "配置模型接入、外部工具、同步偏好和本地复核规则。",
        ),
      },
    }),
    [copy],
  );

  const candidateKanbanModels = useMemo(
    () => (stateMachine ? buildApplicationViewModels(summary.applications, applicationThreads, stateMachine) : []),
    [applicationThreads, stateMachine, summary.applications],
  );

  const counts = useMemo(
    () =>
      ({
        candidates: candidateKanbanModels.length,
        settings: mcpServers.filter((server) => !server.enabled || !/healthy/i.test(server.healthStatus)).length,
      }) satisfies Partial<Record<WorkspaceTab, number>>,
    [candidateKanbanModels.length, mcpServers],
  );

  const candidateKanbanTabItems = useMemo(
    () => [
      {
        key: "funnel",
        label: copy("Candidate funnel", "候选人漏斗"),
        count: candidateKanbanModels.length,
      },
      {
        key: "status",
        label: copy("Candidate follow-up", "候选人跟进"),
        count: candidateKanbanModels.filter((item) => {
          const node = item.currentNode;
          if (!node || node.uiConfig?.showInKanban === false || node.isTransient) {
            return false;
          }
          if (["no_response", "cooldown", "archived", "candidate_withdrew"].includes(item.currentStatus)) {
            return false;
          }
          return node.phase !== "Z" && (((!node.isTerminal && !node.isSoftTerminal) || node.isSuccess));
        }).length,
      },
      {
        key: "jd",
        label: copy("JD management", "JD 管理"),
        count: new Set(
          candidateKanbanModels.map(
            (application) => application.application.jobDescription.title || copy("Unassigned role", "未分配岗位"),
          ),
        ).size,
      },
    ],
    [candidateKanbanModels, copy],
  );

  const handleSaveSettings = async (patch: Partial<SettingsSnapshot>) => {
    setSettingsSaving(true);
    try {
      const nextSettings = await apiClient.updateSettings(patch);
      startTransition(() => {
        setSummary((current) => ({ ...current, settings: nextSettings }));
      });
      await loadCoreWorkspace();
    } finally {
      setSettingsSaving(false);
    }
  };

  const handleInstallMcpPreset = async (
    presetKey: string,
    payload?: { serverKey?: string; name?: string; endpoint?: string },
  ) => {
    await apiClient.installMcpPreset(presetKey, payload);
    await loadSettingsWorkspace();
  };

  const handleCreateMcpServer = async (payload: {
    serverKey: string;
    name: string;
    transportKind: string;
    protocol: string;
    endpoint: string;
    enabled?: boolean;
    tools?: Array<{
      name: string;
      description: string;
      parameters?: Record<string, unknown>;
      capabilities?: string[];
      enabled?: boolean;
      riskLevel?: string;
      remoteName?: string | null;
      toolMetadata?: Record<string, unknown>;
    }>;
  }) => {
    await apiClient.createMcpServer(payload);
    await loadSettingsWorkspace();
  };

  const handleUpdateMcpServer = async (
    serverId: string,
    payload: Partial<{
      serverKey: string;
      name: string;
      transportKind: string;
      protocol: string;
      endpoint: string;
      enabled: boolean;
      tools: Array<{
        name: string;
        description: string;
        parameters?: Record<string, unknown>;
        capabilities?: string[];
        enabled?: boolean;
        riskLevel?: string;
        remoteName?: string | null;
        toolMetadata?: Record<string, unknown>;
      }>;
    }>,
  ) => {
    await apiClient.updateMcpServer(serverId, payload);
    await loadSettingsWorkspace();
  };

  const handleDeleteMcpServer = async (serverId: string) => {
    await apiClient.deleteMcpServer(serverId);
    await loadSettingsWorkspace();
  };

  const handleHealthcheckMcpServer = async (serverId: string) => {
    await apiClient.healthcheckMcpServer(serverId);
    await loadSettingsWorkspace();
  };

  const handleCreateApplicationEntry = async (
    applicationId: string,
    payload: { direction: string; content: string; messageType?: string; platform?: string },
  ) => {
    await apiClient.createApplicationEntry(applicationId, payload);
    await loadCoreWorkspace();
  };

  const handleTransitionApplicationState = async (
    applicationId: string,
    payload: ApplicationTransitionPayload,
  ) => {
    await apiClient.transitionApplicationState(applicationId, payload);
    await loadCoreWorkspace();
  };

  const resolveApplicationId = (subjectId?: string) => {
    const normalized = String(subjectId ?? "").trim();
    if (!normalized) {
      return undefined;
    }
    const direct = summary.applications.find(
      (application) => application.id === normalized || application.applicationId === normalized,
    );
    if (direct) {
      return direct.applicationId || direct.id;
    }
    const byPerson = summary.applications.find((application) => application.personId === normalized);
    return byPerson ? byPerson.applicationId || byPerson.id : undefined;
  };

  const openApplicationWorkspace = (statusFilter?: string, applicationIdLike?: string) => {
    const applicationId = resolveApplicationId(applicationIdLike);
    setCandidateKanbanTab(statusFilter === "application" || applicationId ? "status" : "funnel");
    setCandidateWorkspaceFocus((current) => ({
      applicationId,
      conversationToken: applicationId ? current.conversationToken + 1 : current.conversationToken,
    }));
    setTab("candidates");
  };

  const openJdManagement = () => {
    setCandidateKanbanTab("jd");
    setTab("candidates");
  };

  const openAgents = (panel: "conversation" | "config" | "approvals", agent: "assistant" | "autonomous") => {
    open({
      agentKind: agent,
      panel,
    });
  };

  const content = (() => {
    switch (tab) {
      case "home":
        return (
          <DashboardView
            summary={summary}
            onOpenCandidates={() => setTab("candidates")}
            onOpenJdWorkspace={openJdManagement}
            onOpenCommunications={() => openApplicationWorkspace("active")}
            onOpenAgentApprovals={() => openAgents("approvals", "autonomous")}
            onOpenAgentConfig={() => openAgents("config", "assistant")}
          />
        );
      case "candidates":
        return (
          <CandidatesKanbanView
            applications={summary.applications}
            threads={applicationThreads}
            stateMachine={stateMachine}
            summaryDefinitions={summary.applicationFollowUpSummaryDefinitions}
            activeTab={candidateKanbanTab}
            preferredApplicationId={candidateWorkspaceFocus.applicationId}
            preferredConversationToken={candidateWorkspaceFocus.conversationToken}
            onOpenApplication={(applicationId) => openApplicationWorkspace("application", applicationId)}
            onRefresh={() => void refreshWorkspace()}
            onCreateEntry={handleCreateApplicationEntry}
            onTransition={handleTransitionApplicationState}
            jdContent={
              <JdWorkspaceSurface
                applications={candidateKanbanModels}
                jobDescriptions={jobDescriptions}
              />
            }
          />
        );
      case "settings":
        return (
          <SettingsView
            settings={summary.settings}
            mcpPresets={mcpPresets}
            mcpServers={mcpServers}
            saving={settingsSaving}
            onSave={handleSaveSettings}
            onInstallMcpPreset={handleInstallMcpPreset}
            onCreateMcpServer={handleCreateMcpServer}
            onUpdateMcpServer={handleUpdateMcpServer}
            onDeleteMcpServer={handleDeleteMcpServer}
            onHealthcheckMcpServer={handleHealthcheckMcpServer}
          />
        );
      default:
        return <DashboardView summary={summary} stateMachine={stateMachine} />;
    }
  })();

  return (
    <>
      <AppLayout
        sidebar={
          <Sidebar
            active={tab}
            onChange={setTab}
            counts={counts}
            agentsOpen={isOpen}
            agentStatus={summary.agent.status}
            agentCount={summary.approvals.filter((approval) => approval.status === "pending").length}
            onOpenAgents={() => openAgents("conversation", "assistant")}
          />
        }
        topbar={
          <TopBar
            settings={summary.settings}
            transport={transport}
            sectionEyebrow={sectionMeta[tab].eyebrow}
            sectionTitle={sectionMeta[tab].title}
            hideSectionSummary={tab === "candidates"}
            leadingContent={
              tab === "candidates" ? (
                <div className="workspace-topbar__candidate-tabs">
                  <SectionTabs
                    variant="topbar"
                    items={candidateKanbanTabItems}
                    active={candidateKanbanTab}
                    onChange={(key) => setCandidateKanbanTab(key as CandidatesKanbanTab)}
                  />
                </div>
              ) : undefined
            }
            onRefresh={() => void refreshWorkspace()}
            refreshing={refreshing}
          />
        }
      >
        {errorMessage ? (
          <div
            style={{
              borderRadius: "var(--radius-md)",
              border: "1px solid var(--danger)",
              background: "var(--danger-soft)",
              color: "var(--danger)",
              padding: "var(--space-3) var(--space-4)",
              fontSize: "var(--font-size-sm)",
              lineHeight: "var(--line-height-base)",
            }}
          >
            {errorMessage}
          </div>
        ) : null}
        {content}
      </AppLayout>

      <FloatingBubble
        status={summary.agent.status}
        pendingCount={summary.approvals.filter((approval) => approval.status === "pending").length}
      />
      <ChatOverlay transport={transport} workspaceAgent={summary.agent} />
    </>
  );
}
