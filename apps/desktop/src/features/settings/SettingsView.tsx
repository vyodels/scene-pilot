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

const theme = {
  colors: {
    background: "var(--bg-page)",
    panel: "var(--bg-card)",
    border: "var(--border-line)",
    text: "var(--text-primary)",
    muted: "var(--text-secondary)",
    positive: "var(--success)",
    warning: "var(--warning)",
    critical: "var(--danger)",
    accent: "var(--brand-primary)",
    accentSoft: "var(--brand-primary-soft)",
  },
  radius: {
    xl: "var(--radius-lg)",
    lg: "var(--radius-md)",
    md: "var(--radius-sm)",
    sm: "var(--radius-xs)",
  },
  shadow: "var(--shadow-pop)",
} as const;

function translateSettingLabel(value: string): string {
  const table: Record<string, string> = {
    "Recruiting scene profile": "招聘场景配置",
    "Runtime scene profile": "招聘策略配置",
    "Primary OpenAI API": "主模型接口",
    "Fallback Anthropic": "备用模型接口",
  };
  return table[value] ?? value;
}

const inputStyle = {
  width: "100%",
  borderRadius: theme.radius.sm,
  border: `1px solid ${theme.colors.border}`,
  background: theme.colors.panel,
  color: theme.colors.text,
  minHeight: "var(--space-8)",
  padding: "0 var(--space-3)",
} as const;

const providerHintStyle = {
  color: theme.colors.muted,
  fontSize: "var(--font-size-xs)",
  lineHeight: 1.6,
} as const;

const buttonStyle = {
  ...inputStyle,
  cursor: "pointer",
  padding: "0 var(--space-4)",
  width: "auto",
} as const;

const dangerButtonStyle = {
  ...buttonStyle,
  border: `1px solid ${theme.colors.critical}`,
  color: theme.colors.critical,
} as const;

function providerHostExample(kind: ProviderConfig["kind"]): { example: string; noteEn: string; noteZh: string } {
  if (kind === "anthropic") {
    return {
      example: "https://api.anthropic.com",
      noteEn: "Only fill the host/base URL. Do not include a concrete endpoint path.",
      noteZh: "只填写 host/base URL，不要填写具体接口路径。",
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
    protocol: "mcp_jsonrpc",
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
    gap: "var(--space-3)",
    alignItems: "center",
  } as const;

  return (
    <div style={{ display: "grid", gap: "var(--space-5)", gridTemplateColumns: "repeat(auto-fit, minmax(var(--layout-right-panel-width), 1fr))", minWidth: 0, background: theme.colors.background, padding: "var(--space-5)", borderRadius: theme.radius.xl }}>
      <Panel title={copy("Workspace settings", "工作台设置")} eyebrow={copy("Local-first", "本地优先")} description={copy("Core workspace settings and review gates.", "工作台核心设置与复核门控。")}>
        <div style={{ display: "grid", gap: "var(--space-3)" }}>
          <StatusBadge tone={draft.desktopApprovalsOnly ? "warning" : "neutral"}>{draft.desktopApprovalsOnly ? copy("desktop review only", "仅桌面复核") : copy("mixed review mode", "混合复核模式")}</StatusBadge>
          <StatusBadge tone={draft.intranetEnabled ? "positive" : "neutral"}>{draft.intranetEnabled ? copy("intranet sync enabled", "已启用内网同步") : copy("no intranet sync", "未启用内网同步")}</StatusBadge>
          <StatusBadge tone={draft.autonomyEnabled ? "positive" : "neutral"}>
            {draft.autonomyEnabled
              ? copy("autonomous loop enabled", "已启用自主运行")
              : copy("autonomous loop disabled", "自主运行未启用")}
          </StatusBadge>
          <StatusBadge tone={draft.skillHealthAutonomyEnabled ? "positive" : "neutral"}>
            {draft.skillHealthAutonomyEnabled
              ? copy(`review checks every ${draft.skillHealthAutonomyIntervalSeconds}s`, `复核检查每 ${draft.skillHealthAutonomyIntervalSeconds} 秒执行一次`)
              : copy("review checks idle", "复核检查未启用")}
          </StatusBadge>
          <div style={{ color: theme.colors.muted, fontSize: "var(--font-size-sm)" }}>
            {copy("Locale", "语言区域")} {draft.locale} · {copy("Timezone", "时区")} {draft.timezone}
          </div>
          <label style={{ display: "flex", alignItems: "center", gap: "var(--space-3)", fontSize: "var(--font-size-base)" }}>
            <input
              type="checkbox"
              checked={draft.intranetEnabled}
              onChange={(event) => setDraft((current) => ({ ...current, intranetEnabled: event.target.checked }))}
            />
            {copy("Enable intranet sync", "启用内网同步")}
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: "var(--space-3)", fontSize: "var(--font-size-base)" }}>
            <input
              type="checkbox"
              checked={draft.desktopApprovalsOnly}
              onChange={(event) => setDraft((current) => ({ ...current, desktopApprovalsOnly: event.target.checked }))}
            />
            {copy("Keep reviews desktop-only", "复核仅在桌面端完成")}
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: "var(--space-3)", fontSize: "var(--font-size-base)" }}>
            <input
              type="checkbox"
              checked={draft.autonomyEnabled}
              onChange={(event) => setDraft((current) => ({ ...current, autonomyEnabled: event.target.checked }))}
            />
            {copy("Enable autonomous sourcing loop", "启用自主补人循环")}
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: "var(--space-3)", fontSize: "var(--font-size-base)" }}>
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
            {copy("Enable periodic review checks", "启用周期性复核检查")}
          </label>
          <label style={{ display: "grid", gap: "var(--space-2)", fontSize: "var(--font-size-sm)", color: theme.colors.muted }}>
            {copy("Review check interval (seconds)", "复核检查间隔（秒）")}
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
      <Panel title={copy("Recruiting profile", "招聘配置")} eyebrow={translateSettingLabel(draft.platform.name)} description={copy("Current recruiting account and contact policy.", "当前招聘账号与联络策略。")}>
        <div style={{ display: "grid", gap: "var(--space-3)" }}>
          <label style={{ display: "grid", gap: "var(--space-2)", fontSize: "var(--font-size-sm)", color: theme.colors.muted }}>
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
          <label style={{ display: "grid", gap: "var(--space-2)", fontSize: "var(--font-size-sm)", color: theme.colors.muted }}>
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
          <label style={{ display: "grid", gap: "var(--space-2)", fontSize: "var(--font-size-sm)", color: theme.colors.muted }}>
            {copy("Max concurrent sessions", "最大并发会话")}
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
          <label style={{ display: "grid", gap: "var(--space-2)", fontSize: "var(--font-size-sm)", color: theme.colors.muted }}>
            {copy("Minimum funnel candidates before auto sourcing", "触发自主补人的最小漏斗人数")}
            <input
              type="number"
              min={0}
              value={draft.platform.minFunnelCandidates}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  platform: {
                    ...current.platform,
                    minFunnelCandidates: Math.max(0, Number(event.target.value || 0)),
                  },
                }))
              }
              style={inputStyle}
            />
          </label>
          <StatusBadge tone={draft.platform.allowOutboundMessaging ? "positive" : "warning"}>
            {draft.platform.allowOutboundMessaging ? copy("outreach enabled", "外联已启用") : copy("outreach gated", "外联受控")}
          </StatusBadge>
          <label style={{ display: "flex", alignItems: "center", gap: "var(--space-3)", fontSize: "var(--font-size-base)" }}>
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
            {copy("Allow outreach messages", "允许外联消息")}
          </label>
        </div>
      </Panel>
      <Panel title={copy("Model endpoints", "模型接口")} eyebrow={copy("Model routing", "模型路由")} description={copy("Endpoint preferences and local deployment targets.", "接口偏好与本地部署目标。")}>
        <div style={{ display: "grid", gap: "var(--space-3)" }}>
          {draft.providers.map((provider, index) => {
            const hint = providerHostExample(provider.kind);
            return (
              <article key={provider.name} style={{ padding: "var(--space-4)", borderRadius: theme.radius.xl, background: "var(--bg-page)", border: `1px solid ${theme.colors.border}` }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--space-2)" }}>
                  <strong>{translateSettingLabel(provider.name)}</strong>
                  <StatusBadge tone={provider.enabled ? "positive" : "neutral"}>{translateUiToken(provider.kind.replace(/-/g, "_"), copy)}</StatusBadge>
                </div>
                <div style={{ display: "grid", gap: "var(--space-3)", marginTop: "var(--space-3)" }}>
                  <label style={{ display: "flex", alignItems: "center", gap: "var(--space-3)", fontSize: "var(--font-size-base)" }}>
                    <input
                      type="checkbox"
                      checked={provider.enabled}
                      onChange={(event) => updateProvider(index, { enabled: event.target.checked })}
                    />
                    {copy("Enable this endpoint", "启用该接口")}
                  </label>
                  <label style={{ display: "grid", gap: "var(--space-2)", fontSize: "var(--font-size-sm)", color: theme.colors.muted }}>
                    {copy("Model", "模型")}
                    <input
                      type="text"
                      value={provider.model}
                      onChange={(event) => updateProvider(index, { model: event.target.value })}
                      style={inputStyle}
                      placeholder={provider.kind === "anthropic" ? "claude-sonnet-4" : "gpt-5.4"}
                    />
                  </label>
                  <label style={{ display: "grid", gap: "var(--space-2)", fontSize: "var(--font-size-sm)", color: theme.colors.muted }}>
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
                  <label style={{ display: "grid", gap: "var(--space-2)", fontSize: "var(--font-size-sm)", color: theme.colors.muted }}>
                    {copy("Response wait time (seconds)", "响应等待时间（秒）")}
                    <input
                      type="number"
                      min={1}
                      step={1}
                      value={provider.timeoutSeconds}
                      onChange={(event) =>
                        updateProvider(index, {
                          timeoutSeconds: Math.max(1, Number(event.target.value || provider.timeoutSeconds || 180)),
                        })
                      }
                      style={inputStyle}
                    />
                    <span style={providerHintStyle}>
                      {copy(
                        "Long-running strategy, review, and tool-planning calls should have more headroom. Streamed providers keep the connection alive while tokens arrive.",
                        "长耗时的策略、复核和工具规划调用需要更大的等待预算；支持流式的 provider 会在 token 到达时持续保持连接。",
                      )}
                    </span>
                  </label>
                  <label style={{ display: "grid", gap: "var(--space-2)", fontSize: "var(--font-size-sm)", color: theme.colors.muted }}>
                    {copy("Access key", "访问密钥")}
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
        title={copy("Tool connections", "工具连接")}
        eyebrow={copy("Connected tools", "连接工具")}
        description={copy(
          "Register external tools, install presets, and make them available in the workspace.",
          "注册外部工具、安装预置模板，并让它们可在工作台中使用。",
        )}
      >
        <div style={{ display: "grid", gap: "var(--space-4)" }}>
          <div style={{ display: "grid", gap: "var(--space-2)" }}>
            <strong style={{ fontSize: "var(--font-size-sm)" }}>{copy("Connection templates", "连接模板")}</strong>
            {mcpPresets.map((preset) => (
              <div key={preset.key} style={{ ...compactRowStyle, gridTemplateColumns: "minmax(0, 1.1fr) minmax(0, 1.4fr) auto" }}>
                <div>
                  <div style={{ fontWeight: 600 }}>{preset.name}</div>
                  <div style={providerHintStyle}>{preset.description}</div>
                </div>
                <div style={providerHintStyle}>
                  {copy("Example endpoint", "示例地址")} {preset.endpointExample}
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
                  style={buttonStyle}
                >
                  {copy("Install", "安装")}
                </button>
              </div>
            ))}
          </div>
          <div style={{ display: "grid", gap: "var(--space-2)" }}>
            <strong style={{ fontSize: "var(--font-size-sm)" }}>{copy("Saved connections", "已保存连接")}</strong>
            {mcpServers.length ? (
              mcpServers.map((server) => {
                const serverDraft = serverDrafts[server.id] ?? {
                  name: server.name,
                  endpoint: server.endpoint,
                  enabled: server.enabled,
                };
                return (
                  <div key={server.id} style={{ display: "grid", gap: "var(--space-2)", padding: "var(--space-3)", border: `1px solid ${theme.colors.border}`, borderRadius: theme.radius.md, background: "var(--bg-page)" }}>
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
                      <label style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", fontSize: "var(--space-3)" }}>
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
                        {copy("on", "开启")}
                      </label>
                      <StatusBadge tone={server.healthStatus === "healthy" ? "positive" : server.healthStatus === "unhealthy" ? "critical" : "warning"}>
                        {server.healthStatus}
                      </StatusBadge>
                      <div style={{ display: "flex", gap: "var(--space-2)", justifyContent: "flex-end" }}>
                        <button
                          type="button"
                          onClick={() =>
                            onUpdateMcpServer(server.id, {
                              name: serverDraft.name,
                              endpoint: serverDraft.endpoint,
                              enabled: serverDraft.enabled,
                            })
                          }
                          style={buttonStyle}
                        >
                          {copy("Save", "保存")}
                        </button>
                        <button
                          type="button"
                          onClick={() => onHealthcheckMcpServer(server.id)}
                          style={buttonStyle}
                        >
                          {copy("Check status", "检查状态")}
                        </button>
                        <button
                          type="button"
                          onClick={() => onDeleteMcpServer(server.id)}
                          style={dangerButtonStyle}
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
              <div style={providerHintStyle}>{copy("No tool connections yet.", "当前还没有工具连接。")}</div>
            )}
          </div>
          <div style={{ display: "grid", gap: "var(--space-2)" }}>
            <strong style={{ fontSize: "var(--font-size-sm)" }}>{copy("Add custom connection", "新增自定义连接")}</strong>
            <div style={{ display: "grid", gap: "var(--space-2)", gridTemplateColumns: "repeat(2, minmax(0, 1fr))" }}>
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
                placeholder={copy("Connection endpoint", "连接地址")}
                value={customServer.endpoint}
                onChange={(event) => setCustomServer((current) => ({ ...current, endpoint: event.target.value }))}
                style={inputStyle}
              />
              <select
                value={customServer.protocol}
                onChange={(event) => setCustomServer((current) => ({ ...current, protocol: event.target.value }))}
                style={inputStyle}
              >
                <option value="mcp_jsonrpc">mcp_jsonrpc</option>
                <option value="json_socket_tool_call">json_socket_tool_call</option>
                <option value="json_socket_browser_command">json_socket_browser_command</option>
              </select>
            </div>
            <textarea
              value={customServer.toolsJson}
              onChange={(event) => setCustomServer((current) => ({ ...current, toolsJson: event.target.value }))}
              style={{ ...inputStyle, minHeight: "calc(var(--space-12) + var(--space-12) + var(--space-6))", fontFamily: "var(--font-mono)", padding: "var(--space-3)" }}
              placeholder='[{"name":"custom_tool","description":"...","parameters":{"type":"object"},"capabilities":["browser"]}]'
            />
            {mcpError ? <div style={{ ...providerHintStyle, color: theme.colors.critical }}>{mcpError}</div> : null}
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
                style={buttonStyle}
              >
                {copy("Add connection", "创建连接")}
              </button>
            </div>
          </div>
        </div>
        <div style={{ marginTop: "var(--space-4)", display: "flex", justifyContent: "flex-end" }}>
          <button
            type="button"
            onClick={() =>
              onSave({
                intranetEnabled: draft.intranetEnabled,
                desktopApprovalsOnly: draft.desktopApprovalsOnly,
                autonomyEnabled: draft.autonomyEnabled,
                skillHealthAutonomyEnabled: draft.skillHealthAutonomyEnabled,
                skillHealthAutonomyIntervalSeconds: draft.skillHealthAutonomyIntervalSeconds,
                platform: draft.platform,
                providers: draft.providers,
              })
            }
            disabled={saving}
            style={{
              border: `1px solid ${theme.colors.accent}`,
              borderRadius: theme.radius.sm,
              background: "var(--brand-primary-soft)",
              color: theme.colors.text,
              padding: "0 var(--space-4)",
              cursor: "pointer",
              fontWeight: 600,
            }}
          >
            {saving ? copy("Saving...", "保存中...") : copy("Save settings", "保存设置")}
          </button>
        </div>
      </Panel>
    </div>
  );
}
