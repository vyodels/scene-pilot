import { useEffect, useState } from "react";
import { Panel, StatusBadge } from "../../components";
import { apiClient } from "../../lib/api";
import { formatCompactDate } from "../../lib/format";
import type { SettingsSnapshot } from "../../lib/types";
import { SettingsView } from "./SettingsView";

export function SettingsPage() {
  const [settings, setSettings] = useState<SettingsSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefreshedAt, setLastRefreshedAt] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const loadSettings = async () => {
    setLoading(true);
    try {
      const nextSettings = await apiClient.getSettings();
      setSettings(nextSettings);
      setError(null);
      setLastRefreshedAt(new Date().toISOString());
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load settings.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadSettings();
  }, []);

  const handleSave = async (patch: Partial<SettingsSnapshot>) => {
    setSaving(true);
    try {
      const nextSettings = await apiClient.updateSettings(patch);
      setSettings(nextSettings);
      setLastRefreshedAt(new Date().toISOString());
      setError(null);
    } finally {
      setSaving(false);
    }
  };

  if (loading && settings === null) {
    return (
      <Panel title="Execution settings" eyebrow="Local-first" description="Loading workspace settings from the local backend...">
        <div style={{ color: "rgba(233,239,255,0.72)", fontSize: "14px" }}>Synchronizing settings state.</div>
      </Panel>
    );
  }

  if (settings === null) {
    return (
      <Panel
        title="Execution settings"
        eyebrow="Local-first"
        description="The desktop client could not load settings from the backend."
        actions={<StatusBadge tone="critical">error</StatusBadge>}
      >
        <div style={{ display: "grid", gap: "12px" }}>
          <div style={{ color: "rgba(233,239,255,0.78)", lineHeight: 1.6 }}>{error ?? "Unknown settings error."}</div>
          <button
            type="button"
            onClick={() => void loadSettings()}
            style={{
              alignSelf: "start",
              border: "1px solid rgba(255,255,255,0.12)",
              borderRadius: "12px",
              background: "rgba(122,167,255,0.18)",
              color: "#eef3ff",
              padding: "10px 14px",
              cursor: "pointer",
              fontWeight: 700,
            }}
          >
            Retry
          </button>
        </div>
      </Panel>
    );
  }

  return (
    <div style={{ display: "grid", gap: "16px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", alignItems: "center" }}>
        <div style={{ color: "rgba(233,239,255,0.72)", fontSize: "13px" }}>
          {lastRefreshedAt ? `Last refreshed ${formatCompactDate(lastRefreshedAt)}` : "Settings are loaded from the backend."}
        </div>
        <button
          type="button"
          onClick={() => void loadSettings()}
          disabled={loading || saving}
          style={{
            border: "1px solid rgba(255,255,255,0.12)",
            borderRadius: "12px",
            background: "rgba(122,167,255,0.18)",
            color: "#eef3ff",
            padding: "10px 14px",
            cursor: loading || saving ? "not-allowed" : "pointer",
            fontWeight: 700,
          }}
        >
          {loading ? "Refreshing..." : "Refresh"}
        </button>
      </div>
      {error ? (
        <Panel
          title="Execution settings"
          eyebrow="Local-first"
          description="The desktop client could not refresh settings from the backend."
          actions={<StatusBadge tone="critical">error</StatusBadge>}
        >
          <div style={{ display: "grid", gap: "12px" }}>
            <div style={{ color: "rgba(233,239,255,0.78)", lineHeight: 1.6 }}>{error}</div>
            <button
              type="button"
              onClick={() => void loadSettings()}
              style={{
                alignSelf: "start",
                border: "1px solid rgba(255,255,255,0.12)",
                borderRadius: "12px",
                background: "rgba(122,167,255,0.18)",
                color: "#eef3ff",
                padding: "10px 14px",
                cursor: "pointer",
                fontWeight: 700,
              }}
            >
              Retry
            </button>
          </div>
        </Panel>
      ) : null}
      <SettingsView settings={settings} saving={saving} onSave={handleSave} />
    </div>
  );
}
