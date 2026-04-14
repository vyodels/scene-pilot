import { useEffect, useState } from "react";
import { Panel, StatusBadge } from "../../components";
import { apiClient } from "../../lib/api";
import { formatCompactDate } from "../../lib/format";
import type { SkillRecord } from "../../lib/types";
import { SkillsView } from "./SkillsView";

export function SkillsPage() {
  const [skills, setSkills] = useState<SkillRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefreshedAt, setLastRefreshedAt] = useState<string | null>(null);

  const loadSkills = async () => {
    setLoading(true);
    try {
      const items = await apiClient.listSkills();
      setSkills(items);
      setError(null);
      setLastRefreshedAt(new Date().toISOString());
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load skills.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadSkills();
  }, []);

  if (loading && skills.length === 0) {
    return (
      <Panel title="Skill registry" eyebrow="Learning gates" description="Loading skills from the local backend...">
        <div style={{ color: "rgba(233,239,255,0.72)", fontSize: "14px" }}>Synchronizing skill state.</div>
      </Panel>
    );
  }

  return (
    <div style={{ display: "grid", gap: "16px" }}>
      {error ? (
        <Panel
          title="Skill registry"
          eyebrow="Learning gates"
          description="The desktop client could not refresh skill data from the backend."
          actions={<StatusBadge tone="critical">error</StatusBadge>}
        >
          <div style={{ display: "grid", gap: "12px" }}>
            <div style={{ color: "rgba(233,239,255,0.78)", lineHeight: 1.6 }}>{error}</div>
            <button
              type="button"
              onClick={() => void loadSkills()}
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

      <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", alignItems: "center" }}>
        <div style={{ color: "rgba(233,239,255,0.72)", fontSize: "13px" }}>
          {loading
            ? "Refreshing skill registry..."
            : lastRefreshedAt
              ? `Last refreshed ${formatCompactDate(lastRefreshedAt)}`
              : "Skill registry is loaded from the backend."}
        </div>
        <button
          type="button"
          onClick={() => void loadSkills()}
          disabled={loading}
          style={{
            border: "1px solid rgba(255,255,255,0.12)",
            borderRadius: "12px",
            background: "rgba(122,167,255,0.18)",
            color: "#eef3ff",
            padding: "10px 14px",
            cursor: loading ? "not-allowed" : "pointer",
            fontWeight: 700,
          }}
        >
          {loading ? "Refreshing..." : "Refresh"}
        </button>
      </div>

      <SkillsView skills={skills} />
    </div>
  );
}
