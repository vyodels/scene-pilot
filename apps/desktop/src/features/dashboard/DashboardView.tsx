import React from "react";
import { MetricCard, Panel, ProgressBars, Timeline, StatusBadge } from "../../components";
import { useI18n } from "../../lib/i18n";
import { translateUiToken } from "../../lib/uiText";
import type { DashboardSummary } from "../../lib/types";

interface DashboardViewProps {
  summary: DashboardSummary;
}

function translateDashboardText(value: string): string {
  const table: Record<string, string> = {
    "Candidates screened": "已筛选候选人",
    "Past 7 days": "过去 7 天",
    "Reply rate": "回复率",
    "Outreach to response": "外联到回复",
    "Budget used": "已用预算",
    "Token spend this week": "本周 Token 支出",
    "Manual approvals": "人工审批",
    "1 pending": "1 个待处理",
    "Human gate queue": "人工关卡队列",
    Discovery: "发现",
    Screening: "初筛",
    Communication: "沟通",
    Scoring: "评分",
    "Human review": "人工审查",
    "Workflow node advanced": "工作流节点已推进",
    "Moved Mia Chen into the screening step.": "已将 Mia Chen 移入初筛步骤。",
    "Approval pending": "审批待处理",
    "Resume screening Skill is waiting for review.": "resume screening Skill 正在等待审查。",
    "Cooldown applied": "已应用冷却期",
    "Luna Wang was marked to avoid repeat outreach.": "Luna Wang 已被标记为避免重复外联。",
    "Selector drift detected": "检测到选择器漂移",
    "Talent pool packaging requires a refresh before full automation.": "人才库封装在恢复完全自动化前需要先刷新。",
    "Approve resume screening Skill": "批准 resume screening Skill",
    "Review the new initial screening strategy before it can become active.": "在其生效前审查新的 initial screening 策略。",
    "Activate talent pool handoff": "激活人才库交接",
    "Enables the workflow path from scoring to human review.": "启用从评分到人工审查的工作流路径。",
    "Allow local package inspection command": "允许本地包检查命令",
    "Registers a safe command under whitelist control.": "在白名单控制下注册一个安全命令。",
  };
  return table[value] ?? value;
}

export function DashboardView({ summary }: DashboardViewProps): JSX.Element {
  const { copy } = useI18n();
  const spend = summary.metrics.find((item) => item.label === "Budget used");
  const localizedMetrics = summary.metrics.map((metric) => ({
    ...metric,
    label: translateDashboardText(metric.label),
    caption: translateDashboardText(metric.caption),
    delta: translateDashboardText(metric.delta),
  }));
  const localizedPipeline = summary.pipeline.map((stage) => ({
    ...stage,
    label: translateDashboardText(stage.label),
  }));
  const localizedTimeline = summary.timeline.map((event) => ({
    ...event,
    label: translateDashboardText(event.label),
    detail: translateDashboardText(event.detail),
  }));
  const localizedAlerts = summary.alerts.map((event) => ({
    ...event,
    label: translateDashboardText(event.label),
    detail: translateDashboardText(event.detail),
  }));
  const localizedApprovals = summary.approvals.map((item) => ({
    ...item,
    title: translateDashboardText(item.title),
    detail: translateDashboardText(item.detail),
  }));

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
            <div style={{ color: "rgba(233,239,255,0.7)", fontSize: "12px", letterSpacing: "0.18em", textTransform: "uppercase" }}>
              {copy("Live command center", "实时指挥中心")}
            </div>
            <h2 style={{ margin: "8px 0 6px", fontSize: "34px", lineHeight: 1.05 }}>
              {copy("Workflow health and operator signals are visible at a glance.", "工作流健康状态和操作信号一眼可见。")}
            </h2>
            <p style={{ margin: 0, maxWidth: "760px", color: "rgba(233,239,255,0.78)", lineHeight: 1.6 }}>
              {copy(
                "The console keeps workflow creation, supervised trials, approvals, reusable Skills, and live operations visible in one place.",
                "控制台会把工作流创建、受监督试跑、审批、可复用 Skills，以及实时运行情况集中展示在同一个界面里。",
              )}
            </p>
          </div>
          {spend ? <StatusBadge tone={spend.tone === "warning" ? "warning" : "neutral"}>{spend.value}</StatusBadge> : null}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: "14px" }}>
          {localizedMetrics.map((metric) => (
            <MetricCard key={metric.label} {...metric} />
          ))}
        </div>
      </section>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.1fr) minmax(320px, 0.9fr)", gap: "18px", alignItems: "start" }}>
        <Panel title={copy("Workflow throughput", "工作流吞吐")} eyebrow={copy("Operational throughput", "运行吞吐")} description={copy("Current workflow load and headroom against the active target capacity.", "当前工作流负载与目标容量余量。")}>
          <ProgressBars stages={localizedPipeline} />
        </Panel>
        <Panel title={copy("Live events", "实时事件")} eyebrow={copy("Recent state changes", "最新状态变化")} description={copy("The latest runtime, workflow, and supervision events that matter to an operator.", "对操作员最重要的运行时、工作流与监督事件。")}>
          <Timeline events={localizedTimeline} />
        </Panel>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: "18px" }}>
        <Panel title={copy("Alerts", "告警")} eyebrow={copy("Safety and drift", "安全与漂移")} description={copy("Warnings that should block further automation or trigger a workflow revision review.", "需要阻止继续自动化或触发工作流修订审查的告警。")}>
          <Timeline events={localizedAlerts} />
        </Panel>
        <Panel title={copy("Human review queue", "人工审查队列")} eyebrow={copy("Approval gates", "审批关卡")} description={copy("Items waiting for approval before a workflow version, revision suggestion, or skill can become active.", "工作流版本、修订建议或 skill 在生效前等待审批的事项。")}>
          <div style={{ display: "grid", gap: "12px" }}>
            {localizedApprovals.map((item) => (
              <article key={item.id} style={{ padding: "14px", borderRadius: "16px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "8px", alignItems: "start" }}>
                  <strong>{item.title}</strong>
                  <StatusBadge tone={item.status === "pending" ? "warning" : item.status === "approved" ? "positive" : "critical"}>{translateUiToken(item.status, copy)}</StatusBadge>
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
