import React, { useEffect, useState } from "react";
import { Panel, StatusBadge } from "../../components";
import type { SettingsSnapshot } from "../../lib/types";

interface SettingsViewProps {
  settings: SettingsSnapshot;
  saving?: boolean;
  onSave(settings: Partial<SettingsSnapshot>): Promise<void> | void;
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
  const [draft, setDraft] = useState(settings);

  useEffect(() => {
    setDraft(settings);
  }, [settings]);

  return (
    <div style={{ display: "grid", gap: "18px", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))" }}>
      <Panel title="Execution settings" eyebrow="Local-first" description="Base workspace settings and safety gates.">
        <div style={{ display: "grid", gap: "10px" }}>
          <StatusBadge tone={draft.desktopApprovalsOnly ? "warning" : "neutral"}>{draft.desktopApprovalsOnly ? "desktop approvals only" : "mixed approvals"}</StatusBadge>
          <StatusBadge tone={draft.intranetEnabled ? "positive" : "neutral"}>{draft.intranetEnabled ? "intranet sync enabled" : "no intranet sync"}</StatusBadge>
          <div style={{ color: "rgba(233,239,255,0.72)", fontSize: "13px" }}>
            Locale {draft.locale} · Timezone {draft.timezone}
          </div>
          <label style={{ display: "flex", alignItems: "center", gap: "10px", fontSize: "14px" }}>
            <input
              type="checkbox"
              checked={draft.intranetEnabled}
              onChange={(event) => setDraft((current) => ({ ...current, intranetEnabled: event.target.checked }))}
            />
            Enable intranet sync
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: "10px", fontSize: "14px" }}>
            <input
              type="checkbox"
              checked={draft.desktopApprovalsOnly}
              onChange={(event) => setDraft((current) => ({ ...current, desktopApprovalsOnly: event.target.checked }))}
            />
            Keep approvals desktop-only
          </label>
        </div>
      </Panel>
      <Panel title="Platform profile" eyebrow={draft.platform.name} description="Current platform account and contact policy.">
        <div style={{ display: "grid", gap: "10px" }}>
          <label style={{ display: "grid", gap: "6px", fontSize: "13px", color: "rgba(233,239,255,0.72)" }}>
            Account
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
            Cooldown days
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
            {draft.platform.allowOutboundMessaging ? "outbound messaging on" : "outbound messaging gated"}
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
            Allow outbound messaging
          </label>
        </div>
      </Panel>
      <Panel title="Providers" eyebrow="LLM routing" description="Provider preferences and deployment targets.">
        <div style={{ display: "grid", gap: "10px" }}>
          {draft.providers.map((provider) => (
            <article key={provider.name} style={{ padding: "14px", borderRadius: "16px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: "8px" }}>
                <strong>{provider.name}</strong>
                <StatusBadge tone={provider.enabled ? "positive" : "neutral"}>{provider.kind}</StatusBadge>
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
            {saving ? "Saving..." : "Save settings"}
          </button>
        </div>
      </Panel>
    </div>
  );
}
