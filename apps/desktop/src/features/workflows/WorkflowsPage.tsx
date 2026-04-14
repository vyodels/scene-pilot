import { useEffect, useState } from "react";
import { Panel, StatusBadge } from "../../components";
import { apiClient } from "../../lib/api";
import { formatCompactDate } from "../../lib/format";
import type { WorkflowDefinition } from "../../lib/types";
import { WorkflowsView } from "./WorkflowsView";

export function WorkflowsPage() {
  const [workflows, setWorkflows] = useState<WorkflowDefinition[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefreshedAt, setLastRefreshedAt] = useState<string | null>(null);

  const loadWorkflows = async () => {
    setLoading(true);
    try {
      const items = await apiClient.listWorkflows();
      setWorkflows(items);
      setError(null);
      setLastRefreshedAt(new Date().toISOString());
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load workflows.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadWorkflows();
  }, []);

  if (loading && workflows.length === 0) {
    return (
      <Panel title="Workflow definitions" eyebrow="Pipeline orchestration" description="Loading workflows from the local backend...">
        <div style={{ color: "rgba(233,239,255,0.72)", fontSize: "14px" }}>Synchronizing workflow state.</div>
      </Panel>
    );
  }

  return (
    <div style={{ display: "grid", gap: "16px" }}>
      {error ? (
        <Panel
          title="Workflow definitions"
          eyebrow="Pipeline orchestration"
          description="The desktop client could not refresh workflow data from the backend."
          actions={<StatusBadge tone="critical">error</StatusBadge>}
        >
          <div style={{ display: "grid", gap: "12px" }}>
            <div style={{ color: "rgba(233,239,255,0.78)", lineHeight: 1.6 }}>{error}</div>
            <button
              type="button"
              onClick={() => void loadWorkflows()}
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
            ? "Refreshing workflow definitions..."
            : lastRefreshedAt
              ? `Last refreshed ${formatCompactDate(lastRefreshedAt)}`
              : "Workflow definitions are loaded from the backend."}
        </div>
        <button
          type="button"
          onClick={() => void loadWorkflows()}
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

      <WorkflowsView workflows={workflows} />
    </div>
  );
}
