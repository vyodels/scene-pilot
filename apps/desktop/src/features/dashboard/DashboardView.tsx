import React from "react";
import { MetricCard, Panel, ProgressBars, Timeline, StatusBadge } from "../../components";
import type { DashboardSummary } from "../../lib/types";

interface DashboardViewProps {
  summary: DashboardSummary;
}

export function DashboardView({ summary }: DashboardViewProps): JSX.Element {
  const spend = summary.metrics.find((item) => item.label === "Budget used");

  return (
    <div style={{ display: "grid", gap: "18px" }}>
      <section
        style={{
          display: "grid",
          gap: "16px",
          padding: "22px",
          borderRadius: "28px",
          background: "linear-gradient(135deg, rgba(122,167,255,0.16), rgba(93,216,163,0.10) 55%, rgba(255,255,255,0.03))",
          border: "1px solid rgba(255,255,255,0.08)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "12px", flexWrap: "wrap" }}>
          <div>
            <div style={{ color: "rgba(233,239,255,0.7)", fontSize: "12px", letterSpacing: "0.18em", textTransform: "uppercase" }}>Live command center</div>
            <h2 style={{ margin: "8px 0 6px", fontSize: "34px", lineHeight: 1.05 }}>General automation runtime health is visible at a glance.</h2>
            <p style={{ margin: 0, maxWidth: "760px", color: "rgba(233,239,255,0.78)", lineHeight: 1.6 }}>
              The workspace keeps task compilation, supervised trials, approvals, and reusable skills visible in one place while preserving domain-pack operations like recruiting.
            </p>
          </div>
          {spend ? <StatusBadge tone={spend.tone === "warning" ? "warning" : "neutral"}>{spend.value}</StatusBadge> : null}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: "14px" }}>
          {summary.metrics.map((metric) => (
            <MetricCard key={metric.label} {...metric} />
          ))}
        </div>
      </section>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.1fr) minmax(320px, 0.9fr)", gap: "18px", alignItems: "start" }}>
        <Panel title="Pack throughput" eyebrow="Operational throughput" description="Current domain-pack volume and headroom against the active target capacity.">
          <ProgressBars stages={summary.pipeline} />
        </Panel>
        <Panel title="Live events" eyebrow="Recent state changes" description="The latest runtime, workflow, and supervision events that matter to an operator.">
          <Timeline events={summary.timeline} />
        </Panel>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: "18px" }}>
        <Panel title="Alerts" eyebrow="Safety and drift" description="Warnings that should block further automation or trigger a workflow patch review.">
          <Timeline events={summary.alerts} />
        </Panel>
        <Panel title="Human review queue" eyebrow="Approval gates" description="Items waiting for approval before a template, patch, or skill can become active.">
          <div style={{ display: "grid", gap: "12px" }}>
            {summary.approvals.map((item) => (
              <article key={item.id} style={{ padding: "14px", borderRadius: "16px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "8px", alignItems: "start" }}>
                  <strong>{item.title}</strong>
                  <StatusBadge tone={item.status === "pending" ? "warning" : item.status === "approved" ? "positive" : "critical"}>{item.status}</StatusBadge>
                </div>
                <p style={{ margin: "8px 0 0", color: "rgba(233,239,255,0.7)", fontSize: "13px", lineHeight: 1.5 }}>{item.detail}</p>
              </article>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}
