import React, { useEffect, useState } from "react";
import { Panel, StatusBadge } from "../../components";
import { useI18n } from "../../lib/i18n";
import { translateUiToken } from "../../lib/uiText";
import type { SettingsSnapshot } from "../../lib/types";

interface SettingsViewProps {
  settings: SettingsSnapshot;
  saving?: boolean;
  onSave(settings: Partial<SettingsSnapshot>): Promise<void> | void;
}

function translateSettingLabel(value: string): string {
  const table: Record<string, string> = {
    "Recruiting scene profile": "招聘场景画像",
    "Runtime scene profile": "运行时场景画像",
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

export function SettingsView({ settings, saving, onSave }: SettingsViewProps): JSX.Element {
  const { copy } = useI18n();
  const [draft, setDraft] = useState(settings);

  useEffect(() => {
    setDraft(settings);
  }, [settings]);

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
          {draft.providers.map((provider) => (
            <article key={provider.name} style={{ padding: "14px", borderRadius: "16px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: "8px" }}>
                <strong>{translateSettingLabel(provider.name)}</strong>
                <StatusBadge tone={provider.enabled ? "positive" : "neutral"}>{translateUiToken(provider.kind.replace(/-/g, "_"), copy)}</StatusBadge>
              </div>
              <div style={{ color: "rgba(233,239,255,0.72)", fontSize: "13px", marginTop: "6px" }}>{provider.model}</div>
            </article>
          ))}
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
