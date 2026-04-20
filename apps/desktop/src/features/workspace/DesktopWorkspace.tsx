import React, { startTransition, useCallback, useEffect, useMemo, useState } from "react";
import type {
  ApplicationTransitionPayload,
  RecruitmentStateMachine,
} from "@scene-pilot/shared";
import { AppLayout, Panel, SectionTabs, Sidebar, StatusBadge, TopBar } from "../../components";
import { ChatOverlay, FloatingBubble, useChatOverlay } from "../chat-overlay";
import { apiClient } from "../../lib/api";
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
import { buildApplicationViewModels } from "../kanban-shared/kanbanUtils";
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

function resolveMacroStage(status: string, stageKey: string, resumeAvailable: boolean): string {
  const fingerprint = `${status} ${stageKey}`.toLowerCase();
  if (/(rejected|cooldown|archive)/i.test(fingerprint)) {
    return "Archived";
  }
  if (/(offer|decision|hired|accepted|final)/i.test(fingerprint)) {
    return "Decision";
  }
  if (/(interview|schedule)/i.test(fingerprint)) {
    return "Interview";
  }
  if (resumeAvailable || /(resume|profile|attachment)/i.test(fingerprint)) {
    return "Resume";
  }
  if (/(contact|reply|message|communicat|outreach)/i.test(fingerprint)) {
    return "Outreach";
  }
  if (/(review|screen|assessment|probe|score)/i.test(fingerprint)) {
    return "Review";
  }
  return "New";
}

function macroStageTone(stage: string): "positive" | "neutral" | "warning" | "critical" {
  if (stage === "Archived") {
    return "critical";
  }
  if (stage === "Decision" || stage === "Interview") {
    return "positive";
  }
  if (stage === "Review" || stage === "Outreach" || stage === "Resume") {
    return "warning";
  }
  return "neutral";
}

const surfaceRowButtonStyle: React.CSSProperties = {
  textAlign: "left",
  padding: "var(--space-4)",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--border-line)",
  background: "var(--bg-card)",
  cursor: "pointer",
};

function JdWorkspaceSurface({
  applications,
  jobDescriptions,
  onOpenApplication,
}: {
  applications: DashboardSummary["applications"];
  jobDescriptions: JobDescriptionSummaryRecord[];
  onOpenApplication?(filter?: string, applicationId?: string): void;
}): JSX.Element {
  const { copy } = useI18n();
  const jdGroups = useMemo(() => {
    const groupedApplications = applications.reduce<
      Record<string, { title: string; jobDescriptionId?: string | null; applications: DashboardSummary["applications"] }>
    >((accumulator, application) => {
      const title = application.jobDescription.title || copy("Unassigned role", "未分配岗位");
      const key = application.jobDescriptionId || title;
      const existing = accumulator[key];
      if (existing) {
        existing.applications = [...existing.applications, application];
        return accumulator;
      }
      accumulator[key] = {
        title,
        jobDescriptionId: application.jobDescriptionId,
        applications: [application],
      };
      return accumulator;
    }, {});

    jobDescriptions.forEach((job) => {
      const title = job.title || copy("Untitled role", "未命名岗位");
      const key = job.jobDescriptionId || title;
      if (groupedApplications[key]) {
        groupedApplications[key].title = title;
        groupedApplications[key].jobDescriptionId = job.jobDescriptionId;
        return;
      }
      groupedApplications[key] = {
        title,
        jobDescriptionId: job.jobDescriptionId,
        applications: [],
      };
    });

    return Object.entries(groupedApplications).sort((left, right) => {
      const countDiff = right[1].applications.length - left[1].applications.length;
      if (countDiff !== 0) {
        return countDiff;
      }
      return left[1].title.localeCompare(right[1].title, "zh-CN");
    });
  }, [applications, copy, jobDescriptions]);

  return (
    <div style={{ display: "grid", gap: "var(--space-4)" }}>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(calc(var(--space-12) * 3 + var(--space-10) + var(--space-10) + var(--space-5) + var(--space-4)), 1fr))",
          gap: "var(--space-3)",
        }}
      >
        {jdGroups.slice(0, 4).map(([, group]) => {
          const macroCounts = group.applications.reduce<Record<string, number>>((accumulator, application) => {
            const stage = resolveMacroStage(
              application.currentStatus,
              application.stageKey,
              application.resumeAvailable,
            );
            accumulator[stage] = (accumulator[stage] ?? 0) + 1;
            return accumulator;
          }, {});
          return (
            <article
              key={group.jobDescriptionId || group.title}
              style={{
                padding: "var(--space-4)",
                borderRadius: "var(--radius-md)",
                background: "var(--bg-card)",
                border: "1px solid var(--border-line)",
              }}
            >
              <div style={{ fontWeight: 600, color: "var(--text-primary)" }}>{group.title}</div>
              <div
                style={{
                  marginTop: "var(--space-2)",
                  fontSize: "var(--font-size-sm)",
                  color: "var(--text-secondary)",
                }}
              >
                {copy(
                  `${group.applications.length} applications in this funnel.`,
                  `该漏斗下共有 ${group.applications.length} 条申请。`,
                )}
              </div>
              <div
                style={{
                  display: "flex",
                  gap: "var(--space-2)",
                  flexWrap: "wrap",
                  marginTop: "var(--space-3)",
                }}
              >
                {Object.entries(macroCounts).length ? Object.entries(macroCounts).map(([label, count]) => (
                  <StatusBadge key={label} tone={macroStageTone(label)}>
                    {label} · {count}
                  </StatusBadge>
                )) : (
                  <StatusBadge tone="neutral">{copy("No candidate yet", "暂无候选人")}</StatusBadge>
                )}
              </div>
            </article>
          );
        })}
      </div>

      <div style={{ display: "grid", gap: "var(--space-3)" }}>
        {jdGroups.map(([, group]) => (
          <Panel
            key={group.jobDescriptionId || group.title}
            title={group.title}
            eyebrow={copy("Role funnel", "岗位漏斗")}
            description={copy("Applications currently grouped under this role.", "当前归属到该岗位的申请。")}
          >
            <div style={{ display: "grid", gap: "var(--space-3)" }}>
              {group.applications.length ? group.applications.map((application) => {
                const macroStage = resolveMacroStage(
                  application.currentStatus,
                  application.stageKey,
                  application.resumeAvailable,
                );
                return (
                  <button
                    key={application.id}
                    type="button"
                    onClick={() => onOpenApplication?.("application", application.id)}
                    style={surfaceRowButtonStyle}
                  >
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        gap: "var(--space-3)",
                        alignItems: "start",
                      }}
                    >
                      <div>
                        <div style={{ fontWeight: 600, color: "var(--text-primary)" }}>{application.person.name}</div>
                        <div
                          style={{
                            marginTop: "var(--space-1)",
                            fontSize: "var(--font-size-sm)",
                            color: "var(--text-secondary)",
                          }}
                        >
                          {application.person.title} · {application.person.location}
                        </div>
                      </div>
                      <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap", justifyContent: "end" }}>
                        <StatusBadge tone={macroStageTone(macroStage)}>{macroStage}</StatusBadge>
                        <StatusBadge tone="neutral">{copy(`score ${application.matchScore}`, `分数 ${application.matchScore}`)}</StatusBadge>
                      </div>
                    </div>
                    <div
                      style={{
                        marginTop: "var(--space-2)",
                        fontSize: "var(--font-size-sm)",
                        color: "var(--text-regular)",
                        lineHeight: 1.6,
                      }}
                    >
                      {application.nextAction}
                    </div>
                  </button>
                );
              }) : (
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
                    "This JD has been synced into the workspace, but there are no candidate applications under it yet.",
                    "这个 JD 已同步到工作区，但其下还没有候选人申请。",
                  )}
                </div>
              )}
            </div>
          </Panel>
        ))}
      </div>
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

  const counts = useMemo(
    () =>
      ({
        candidates: summary.applications.filter((application) => !/(rejected|cooldown)/i.test(application.currentStatus)).length,
        settings: mcpServers.filter((server) => !server.enabled || !/healthy/i.test(server.healthStatus)).length,
      }) satisfies Partial<Record<WorkspaceTab, number>>,
    [mcpServers, summary.applications],
  );

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

  const candidateKanbanTabItems = useMemo(
    () => [
      {
        key: "funnel",
        label: copy("Candidate funnel", "候选人漏斗"),
        count: summary.applications.length,
      },
      {
        key: "status",
        label: copy("Candidate follow-up", "候选人跟进"),
        count: candidateKanbanModels.filter((item) => item.humanRequired).length,
      },
      {
        key: "jd",
        label: copy("JD management", "JD 管理"),
        count: new Set(
          summary.applications.map(
            (application) => application.jobDescription.title || copy("Unassigned role", "未分配岗位"),
          ),
        ).size,
      },
    ],
    [candidateKanbanModels, copy, summary.applications],
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
                applications={summary.applications}
                jobDescriptions={jobDescriptions}
                onOpenApplication={openApplicationWorkspace}
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
        return <DashboardView summary={summary} />;
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
