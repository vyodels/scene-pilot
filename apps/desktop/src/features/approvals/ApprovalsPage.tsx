import { useEffect, useState } from "react";
import { Panel, StatusBadge } from "../../components";
import { apiClient } from "../../lib/api";
import { formatCompactDate } from "../../lib/format";
import type { ApprovalItem } from "../../lib/types";
import { ApprovalsView } from "./ApprovalsView";

export function ApprovalsPage() {
  const [approvals, setApprovals] = useState<ApprovalItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefreshedAt, setLastRefreshedAt] = useState<string | null>(null);
  const [pendingActionId, setPendingActionId] = useState<string>();

  const loadApprovals = async () => {
    setLoading(true);
    try {
      const items = await apiClient.listApprovals();
      setApprovals(items);
      setError(null);
      setLastRefreshedAt(new Date().toISOString());
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load approvals.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadApprovals();
  }, []);

  const handleApprove = async (id: string) => {
    setPendingActionId(id);
    try {
      await apiClient.approveItem(id);
      await loadApprovals();
    } finally {
      setPendingActionId(undefined);
    }
  };

  const handleReject = async (id: string) => {
    setPendingActionId(id);
    try {
      await apiClient.rejectItem(id, "Rejected from approvals page.");
      await loadApprovals();
    } finally {
      setPendingActionId(undefined);
    }
  };

  if (loading && approvals.length === 0) {
    return (
      <Panel title="Approval queue" eyebrow="Human gates" description="Loading approvals from the local backend...">
        <div style={{ color: "rgba(233,239,255,0.72)", fontSize: "14px" }}>Synchronizing approval state.</div>
      </Panel>
    );
  }

  return (
    <div style={{ display: "grid", gap: "16px" }}>
      {error ? (
        <Panel
          title="Approval queue"
          eyebrow="Human gates"
          description="The desktop client could not refresh approval data from the backend."
          actions={<StatusBadge tone="critical">error</StatusBadge>}
        >
          <div style={{ display: "grid", gap: "12px" }}>
            <div style={{ color: "rgba(233,239,255,0.78)", lineHeight: 1.6 }}>{error}</div>
            <button
              type="button"
              onClick={() => void loadApprovals()}
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
            ? "Refreshing approval queue..."
            : lastRefreshedAt
              ? `Last refreshed ${formatCompactDate(lastRefreshedAt)}`
              : "Approval queue is loaded from the backend."}
        </div>
        <button
          type="button"
          onClick={() => void loadApprovals()}
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

      <ApprovalsView approvals={approvals} pendingActionId={pendingActionId} onApprove={handleApprove} onReject={handleReject} />
    </div>
  );
}
