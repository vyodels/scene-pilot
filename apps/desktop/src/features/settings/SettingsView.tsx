import React, { useEffect, useState } from "react";
import { Panel, StatusBadge } from "../../components";
import { useI18n } from "../../lib/i18n";
import { translateUiToken } from "../../lib/uiText";
import type { McpPresetTemplateRecord, McpServerRecord, ProviderConfig, SettingsSnapshot } from "../../lib/types";

interface SettingsViewProps {
  settings: SettingsSnapshot;
  mcpPresets: McpPresetTemplateRecord[];
  mcpServers: McpServerRecord[];
  saving?: boolean;
  onSave(settings: Partial<SettingsSnapshot>): Promise<void> | void;
  onInstallMcpPreset(
    presetKey: string,
    payload?: { serverKey?: string; name?: string; endpoint?: string },
  ): Promise<void> | void;
  onCreateMcpServer(payload: {
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
  }): Promise<void> | void;
  onUpdateMcpServer(
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
  ): Promise<void> | void;
  onDeleteMcpServer(serverId: string): Promise<void> | void;
  onHealthcheckMcpServer(serverId: string): Promise<void> | void;
}

function translateSettingLabel(value: string): string {
  const table: Record<string, string> = {
    "Recruiting scene profile": "招聘场景配置",
    "Runtime scene profile": "内部执行配置",
    "Primary OpenAI API": "主 OpenAI 接口",
    "Fallback Anthropic": "备用 Anthropic 接口",
  };
  return table[value] ?? value;
}

const inputStyle = {
  width: "100%",
  borderRadius: "12px",
  border: "1px solid rgba(255,255,255,0.12)",
  background: "rgba(255,255,255,0.03)",
  color: "inherit",
  padding: "10px 12px",
} as const;

const providerHintStyle = {
  color: "rgba(233,239,255,0.6)",
  fontSize: "12px",
  lineHeight: 1.6,
} as const;

function providerHostExample(kind: ProviderConfig["kind"]): { example: string; noteEn: string; noteZh: string } {
  if (kind === "anthropic") {
    return {
      example: "https://api.anthropic.com",
      noteEn: "Only fill the host/base URL. Do not include a concrete endpoint path. Anthropic stays config-only for now.",
      noteZh: "只填写 host/base URL，不要填写具体接口路径。Anthropic 结构先保留，内部调用后续再接。",
    };
  }
  return {
    example: "https://api.openai.com/v1 / https://openrouter.ai/api/v1 / http://127.0.0.1:8317/v1",
    noteEn: "Only fill the base path, for example `/v1`. Do not include concrete endpoints like `/chat/completions` or `/responses`.",
    noteZh: "只填写到基础路径，例如 `/v1`；不要填写 `/chat/completions`、`/responses` 这类具体接口。",
  };
}

export function SettingsView({
  settings,
  mcpPresets,
  mcpServers,
  saving,
  onSave,
  onInstallMcpPreset,
  onCreateMcpServer,
  onUpdateMcpServer,
  onDeleteMcpServer,
  onHealthcheckMcpServer,
}: SettingsViewProps): JSX.Element {
  const { copy } = useI18n();
  const [draft, setDraft] = useState(settings);
  const [serverDrafts, setServerDrafts] = useState<Record<string, { name: string; endpoint: string; enabled: boolean }>>({});
  const [mcpError, setMcpError] = useState<string>();
  const [customServer, setCustomServer] = useState({
    serverKey: "",
    name: "",
    endpoint: "",
    protocol: "json_socket_tool_call",
    toolsJson: "[]",
  });

  useEffect(() => {
    setDraft(settings);
  }, [settings]);

  useEffect(() => {
    setServerDrafts(
      Object.fromEntries(
        mcpServers.map((server) => [
          server.id,
          {
            name: server.name,
            endpoint: server.endpoint,
            enabled: server.enabled,
          },
        ]),
      ),
    );
  }, [mcpServers]);

  const updateProvider = (index: number, patch: Partial<ProviderConfig>) => {
    setDraft((current) => ({
      ...current,
      providers: current.providers.map((provider, providerIndex) =>
        providerIndex === index ? { ...provider, ...patch } : provider,
      ),
    }));
  };

  const compactRowStyle = {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1.1fr) minmax(0, 1.4fr) auto auto auto",
    gap: "10px",
    alignItems: "center",
  } as const;

  return (
    <div style={{ display: "grid", gap: "18px", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))" }}>
      <Panel title={copy("Execution settings", "执行设置")} eyebrow={copy("Local-first", "本地优先")} description={copy("Base workspace settings and safety gates.", "工作台基础设置与安全控制。")}>
        <div style={{ display: "grid", gap: "10px" }}>
          <StatusBadge tone={draft.desktopApprovalsOnly ? "warning" : "neutral"}>{draft.desktopApprovalsOnly ? copy("desktop approvals only", "仅桌面审批") : copy("mixed approvals", "混合审批")}</StatusBadge>
          <StatusBadge tone={draft.intranetEnabled ? "positive" : "neutral"}>{draft.intranetEnabled ? copy("intranet sync enabled", "已启用内网同步") : copy("no intranet sync", "未启用内网同步")}</StatusBadge>
          <StatusBadge tone={draft.skillHealthAutonomyEnabled ? "positive" : "neutral"}>
            {draft.skillHealthAutonomyEnabled
              ? copy(`skill health autonomy every ${draft.skillHealthAutonomyIntervalSeconds}s`, `skill health 巡检每 ${draft.skillHealthAutonomyIntervalSeconds} 秒执行一次`)
              : copy("skill health autonomy idle", "skill health 巡检未启用")}
          </StatusBadge>
          <div style={{ color: "rgba(233,239,255,0.72)", fontSize: "13px" }}>
            {copy("Locale", "语言区域")} {draft.locale} · {copy("Timezone", "时区")} {draft.timezone}
          </div>
          <label style={{ display: "flex", alignItems: "center", gap: "10px", fontSize: "14px" }}>
            <input
              type="checkbox"
              checked={draft.intranetEnabled}
              onChange={(event) => setDraft((current) => ({ ...current, intranetEnabled: event.target.checked }))}
            />
            {copy("Enable intranet sync", "启用内网同步")}
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: "10px", fontSize: "14px" }}>
            <input
              type="checkbox"
              checked={draft.desktopApprovalsOnly}
              onChange={(event) => setDraft((current) => ({ ...current, desktopApprovalsOnly: event.target.checked }))}
            />
            {copy("Keep approvals desktop-only", "审批仅在桌面端完成")}
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: "10px", fontSize: "14px" }}>
            <input
              type="checkbox"
              checked={draft.skillHealthAutonomyEnabled}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  skillHealthAutonomyEnabled: event.target.checked,
                }))
              }
            />
            {copy("Enable periodic skill health autonomy", "启用周期性 skill health 巡检")}
          </label>
          <label style={{ display: "grid", gap: "6px", fontSize: "13px", color: "rgba(233,239,255,0.72)" }}>
            {copy("Skill health autonomy interval (seconds)", "skill health 巡检间隔（秒）")}
            <input
              type="number"
              min={1}
              value={draft.skillHealthAutonomyIntervalSeconds ?? 300}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  skillHealthAutonomyIntervalSeconds: Number(event.target.value || current.skillHealthAutonomyIntervalSeconds || 300),
                }))
              }
              style={inputStyle}
            />
          </label>
        </div>
      </Panel>
      <Panel title={copy("Platform profile", "平台配置")} eyebrow={translateSettingLabel(draft.platform.name)} description={copy("Current platform account and contact policy.", "当前平台账号与联络策略。")}>
        <div style={{ display: "grid", gap: "10px" }}>
          <label style={{ display: "grid", gap: "6px", fontSize: "13px", color: "rgba(233,239,255,0.72)" }}>
            {copy("Account", "账号")}
            <input
              type="text"
              value={draft.platform.account}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  platform: { ...current.platform, account: event.target.value },
                }))
              }
              style={inputStyle}
            />
          </label>
          <label style={{ display: "grid", gap: "6px", fontSize: "13px", color: "rgba(233,239,255,0.72)" }}>
            {copy("Cooldown days", "冷却天数")}
            <input
              type="number"
              min={1}
              value={draft.platform.cooldownDays}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  platform: {
                    ...current.platform,
                    cooldownDays: Number(event.target.value || current.platform.cooldownDays),
                  },
                }))
              }
              style={inputStyle}
            />
          </label>
          <label style={{ display: "grid", gap: "6px", fontSize: "13px", color: "rgba(233,239,255,0.72)" }}>
            {copy("Max concurrent AgentRuns", "最大并发 AgentRun")}
            <input
              type="number"
              min={1}
              value={draft.platform.maxConcurrentRuns}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  platform: {
                    ...current.platform,
                    maxConcurrentRuns: Math.max(1, Number(event.target.value || current.platform.maxConcurrentRuns || 1)),
                  },
                }))
              }
              style={inputStyle}
            />
          </label>
          <StatusBadge tone={draft.platform.allowOutboundMessaging ? "positive" : "warning"}>
            {draft.platform.allowOutboundMessaging ? copy("outbound messaging on", "允许外发消息") : copy("outbound messaging gated", "外发消息受控")}
          </StatusBadge>
          <label style={{ display: "flex", alignItems: "center", gap: "10px", fontSize: "14px" }}>
            <input
              type="checkbox"
              checked={draft.platform.allowOutboundMessaging}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  platform: { ...current.platform, allowOutboundMessaging: event.target.checked },
                }))
              }
            />
            {copy("Allow outbound messaging", "允许外发消息")}
          </label>
        </div>
      </Panel>
      <Panel title={copy("Providers", "模型提供方")} eyebrow={copy("LLM routing", "LLM 路由")} description={copy("Provider preferences and deployment targets.", "模型提供方偏好与部署目标。")}>
        <div style={{ display: "grid", gap: "10px" }}>
          {draft.providers.map((provider, index) => {
            const hint = providerHostExample(provider.kind);
            return (
              <article key={provider.name} style={{ padding: "14px", borderRadius: "16px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "8px" }}>
                  <strong>{translateSettingLabel(provider.name)}</strong>
                  <StatusBadge tone={provider.enabled ? "positive" : "neutral"}>{translateUiToken(provider.kind.replace(/-/g, "_"), copy)}</StatusBadge>
                </div>
                <div style={{ display: "grid", gap: "10px", marginTop: "10px" }}>
                  <label style={{ display: "flex", alignItems: "center", gap: "10px", fontSize: "14px" }}>
                    <input
                      type="checkbox"
                      checked={provider.enabled}
                      onChange={(event) => updateProvider(index, { enabled: event.target.checked })}
                    />
                    {copy("Enable this provider", "启用该提供方")}
                  </label>
                  <label style={{ display: "grid", gap: "6px", fontSize: "13px", color: "rgba(233,239,255,0.72)" }}>
                    {copy("Model", "模型")}
                    <input
                      type="text"
                      value={provider.model}
                      onChange={(event) => updateProvider(index, { model: event.target.value })}
                      style={inputStyle}
                      placeholder={provider.kind === "anthropic" ? "claude-sonnet-4" : "gpt-5.4"}
                    />
                  </label>
                  <label style={{ display: "grid", gap: "6px", fontSize: "13px", color: "rgba(233,239,255,0.72)" }}>
                    {copy("Host / Base URL", "Host / Base URL")}
                    <input
                      type="text"
                      value={provider.baseUrl ?? ""}
                      onChange={(event) => updateProvider(index, { baseUrl: event.target.value })}
                      style={inputStyle}
                      placeholder={hint.example}
                    />
                    <span style={providerHintStyle}>
                      {copy(`Example: ${hint.example}`, `示例：${hint.example}`)}
                    </span>
                    <span style={providerHintStyle}>{copy(hint.noteEn, hint.noteZh)}</span>
                  </label>
                  <label style={{ display: "grid", gap: "6px", fontSize: "13px", color: "rgba(233,239,255,0.72)" }}>
                    {copy("API key", "API Key")}
                    <input
                      type="password"
                      value={provider.apiKey ?? ""}
                      onChange={(event) => updateProvider(index, { apiKey: event.target.value })}
                      style={inputStyle}
                      placeholder={provider.kind === "anthropic" ? "sk-ant-..." : "sk-..."}
                      autoComplete="off"
                    />
                    <span style={providerHintStyle}>
                      {copy(
                        "The key is stored locally in the backend settings store and reused after restart.",
                        "Key 会保存到本地后端设置存储中，重启后仍会继续使用。",
                      )}
                    </span>
                  </label>
                </div>
              </article>
            );
          })}
        </div>
      </Panel>
      <Panel
        title={copy("MCP registry", "MCP 注册中心")}
        eyebrow={copy("External capabilities", "外部能力")}
        description={copy(
          "Register real MCP servers, install presets, and expose external tools to the Recruit Agent runtime.",
          "注册真实 MCP 服务、安装预置模板，并把外部工具暴露给 Recruit Agent runtime。",
        )}
      >
        <div style={{ display: "grid", gap: "14px" }}>
          <div style={{ display: "grid", gap: "8px" }}>
            <strong style={{ fontSize: "13px" }}>{copy("Preset templates", "预置模板")}</strong>
            {mcpPresets.map((preset) => (
              <div key={preset.key} style={{ ...compactRowStyle, gridTemplateColumns: "minmax(0, 1.1fr) minmax(0, 1.4fr) auto" }}>
                <div>
                  <div style={{ fontWeight: 600 }}>{preset.name}</div>
                  <div style={providerHintStyle}>{preset.description}</div>
                </div>
                <div style={providerHintStyle}>
                  {copy("Endpoint example", "示例地址")} {preset.endpointExample}
                </div>
                <button
                  type="button"
                  onClick={() =>
                    onInstallMcpPreset(preset.key, {
                      serverKey: preset.key,
                      name: preset.name,
                      endpoint: preset.endpointExample,
                    })
                  }
                  style={{ ...inputStyle, cursor: "pointer", padding: "8px 12px", width: "auto" }}
                >
                  {copy("Install", "安装")}
                </button>
              </div>
            ))}
          </div>
          <div style={{ display: "grid", gap: "8px" }}>
            <strong style={{ fontSize: "13px" }}>{copy("Registered servers", "已注册服务")}</strong>
            {mcpServers.length ? (
              mcpServers.map((server) => {
                const serverDraft = serverDrafts[server.id] ?? {
                  name: server.name,
                  endpoint: server.endpoint,
                  enabled: server.enabled,
                };
                return (
                  <div key={server.id} style={{ display: "grid", gap: "8px", padding: "10px 12px", border: "1px solid rgba(255,255,255,0.08)", borderRadius: "14px" }}>
                    <div style={compactRowStyle}>
                      <input
                        type="text"
                        value={serverDraft.name}
                        onChange={(event) =>
                          setServerDrafts((current) => ({
                            ...current,
                            [server.id]: { ...serverDraft, name: event.target.value },
                          }))
                        }
                        style={inputStyle}
                      />
                      <input
                        type="text"
                        value={serverDraft.endpoint}
                        onChange={(event) =>
                          setServerDrafts((current) => ({
                            ...current,
                            [server.id]: { ...serverDraft, endpoint: event.target.value },
                          }))
                        }
                        style={inputStyle}
                      />
                      <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "12px" }}>
                        <input
                          type="checkbox"
                          checked={serverDraft.enabled}
                          onChange={(event) =>
                            setServerDrafts((current) => ({
                              ...current,
                              [server.id]: { ...serverDraft, enabled: event.target.checked },
                            }))
                          }
                        />
                        {copy("enabled", "启用")}
                      </label>
                      <StatusBadge tone={server.healthStatus === "healthy" ? "positive" : server.healthStatus === "unhealthy" ? "critical" : "warning"}>
                        {server.healthStatus}
                      </StatusBadge>
                      <div style={{ display: "flex", gap: "8px", justifyContent: "flex-end" }}>
                        <button
                          type="button"
                          onClick={() =>
                            onUpdateMcpServer(server.id, {
                              name: serverDraft.name,
                              endpoint: serverDraft.endpoint,
                              enabled: serverDraft.enabled,
                            })
                          }
                          style={{ ...inputStyle, cursor: "pointer", padding: "8px 12px", width: "auto" }}
                        >
                          {copy("Save", "保存")}
                        </button>
                        <button
                          type="button"
                          onClick={() => onHealthcheckMcpServer(server.id)}
                          style={{ ...inputStyle, cursor: "pointer", padding: "8px 12px", width: "auto" }}
                        >
                          {copy("Health check", "健康检查")}
                        </button>
                        <button
                          type="button"
                          onClick={() => onDeleteMcpServer(server.id)}
                          style={{ ...inputStyle, cursor: "pointer", padding: "8px 12px", width: "auto", color: "#ffb4b4" }}
                        >
                          {copy("Delete", "删除")}
                        </button>
                      </div>
                    </div>
                    <div style={providerHintStyle}>
                      {server.serverKey} · {server.transportKind} · {server.protocol} · {copy("tools", "工具")} {server.tools.length}
                      {server.healthError ? ` · ${server.healthError}` : ""}
                    </div>
                  </div>
                );
              })
            ) : (
              <div style={providerHintStyle}>{copy("No MCP servers registered yet.", "当前还没有注册任何 MCP 服务。")}</div>
            )}
          </div>
          <div style={{ display: "grid", gap: "8px" }}>
            <strong style={{ fontSize: "13px" }}>{copy("Custom MCP server", "新增自定义 MCP")}</strong>
            <div style={{ display: "grid", gap: "8px", gridTemplateColumns: "repeat(2, minmax(0, 1fr))" }}>
              <input
                type="text"
                placeholder={copy("Server key", "服务 key")}
                value={customServer.serverKey}
                onChange={(event) => setCustomServer((current) => ({ ...current, serverKey: event.target.value }))}
                style={inputStyle}
              />
              <input
                type="text"
                placeholder={copy("Display name", "显示名称")}
                value={customServer.name}
                onChange={(event) => setCustomServer((current) => ({ ...current, name: event.target.value }))}
                style={inputStyle}
              />
              <input
                type="text"
                placeholder={copy("Endpoint", "连接地址")}
                value={customServer.endpoint}
                onChange={(event) => setCustomServer((current) => ({ ...current, endpoint: event.target.value }))}
                style={inputStyle}
              />
              <select
                value={customServer.protocol}
                onChange={(event) => setCustomServer((current) => ({ ...current, protocol: event.target.value }))}
                style={inputStyle}
              >
                <option value="json_socket_tool_call">json_socket_tool_call</option>
                <option value="json_socket_browser_command">json_socket_browser_command</option>
              </select>
            </div>
            <textarea
              value={customServer.toolsJson}
              onChange={(event) => setCustomServer((current) => ({ ...current, toolsJson: event.target.value }))}
              style={{ ...inputStyle, minHeight: "120px", fontFamily: "monospace" }}
              placeholder='[{"name":"browser_click","description":"...","parameters":{"type":"object"},"capabilities":["browser"]}]'
            />
            {mcpError ? <div style={{ ...providerHintStyle, color: "#ffb4b4" }}>{mcpError}</div> : null}
            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <button
                type="button"
                onClick={() => {
                  try {
                    const tools = JSON.parse(customServer.toolsJson || "[]") as Array<{
                      name: string;
                      description: string;
                      parameters?: Record<string, unknown>;
                      capabilities?: string[];
                      enabled?: boolean;
                      riskLevel?: string;
                      remoteName?: string | null;
                      toolMetadata?: Record<string, unknown>;
                    }>;
                    setMcpError(undefined);
                    void onCreateMcpServer({
                      serverKey: customServer.serverKey.trim(),
                      name: customServer.name.trim(),
                      transportKind: "unix_socket",
                      protocol: customServer.protocol,
                      endpoint: customServer.endpoint.trim(),
                      enabled: true,
                      tools,
                    });
                  } catch (error) {
                    setMcpError(error instanceof Error ? error.message : copy("Invalid tools JSON.", "工具 JSON 无效。"));
                  }
                }}
                style={{ ...inputStyle, cursor: "pointer", padding: "8px 12px", width: "auto" }}
              >
                {copy("Create MCP server", "创建 MCP 服务")}
              </button>
            </div>
          </div>
        </div>
        <div style={{ marginTop: "14px", display: "flex", justifyContent: "flex-end" }}>
          <button
            type="button"
            onClick={() =>
              onSave({
                intranetEnabled: draft.intranetEnabled,
                desktopApprovalsOnly: draft.desktopApprovalsOnly,
                skillHealthAutonomyEnabled: draft.skillHealthAutonomyEnabled,
                skillHealthAutonomyIntervalSeconds: draft.skillHealthAutonomyIntervalSeconds,
                platform: draft.platform,
                providers: draft.providers,
              })
            }
            disabled={saving}
            style={{
              border: "1px solid rgba(255,255,255,0.12)",
              borderRadius: "12px",
              background: "rgba(122,167,255,0.18)",
              color: "#eef3ff",
              padding: "10px 14px",
              cursor: "pointer",
              fontWeight: 700,
            }}
          >
            {saving ? copy("Saving...", "保存中...") : copy("Save settings", "保存设置")}
          </button>
        </div>
      </Panel>
    </div>
  );
}
