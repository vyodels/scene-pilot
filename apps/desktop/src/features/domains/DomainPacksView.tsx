import React from "react";
import { Panel, StatusBadge } from "../../components";
import { useI18n } from "../../lib/i18n";
import { theme } from "../../lib/theme";
import { translateUiToken } from "../../lib/uiText";
import type { DomainPackRecord } from "../../lib/types";

interface DomainPacksViewProps {
  domainPacks: DomainPackRecord[];
}

export function DomainPacksView({ domainPacks }: DomainPacksViewProps): JSX.Element {
  const { copy } = useI18n();

  return (
    <div style={{ display: "grid", gap: "18px", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))" }}>
      {domainPacks.map((pack) => (
        <Panel
          key={pack.key}
          title={pack.name}
          eyebrow={translateUiToken(pack.key, copy)}
          description={pack.description}
          actions={
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              <StatusBadge tone="neutral">{copy(`${pack.templateKeys.length} templates`, `${pack.templateKeys.length} 个模板`)}</StatusBadge>
              <StatusBadge tone={pack.maturity === "beta" ? "positive" : "warning"}>{translateUiToken(pack.maturity, copy)}</StatusBadge>
              <StatusBadge tone="neutral">v{pack.version}</StatusBadge>
            </div>
          }
        >
          <div style={{ display: "grid", gap: "12px" }}>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              <StatusBadge tone="neutral">{pack.runtimeOnly ? copy("runtime only", "仅运行时") : copy("packaged", "已打包")}</StatusBadge>
              <StatusBadge tone="neutral">
                {copy(`${pack.activeTemplateCount}/${pack.templateCount || pack.templateKeys.length} active templates`, `${pack.activeTemplateCount}/${pack.templateCount || pack.templateKeys.length} 个活动模板`)}
              </StatusBadge>
              {pack.defaultCapabilities.map((capability) => (
                <StatusBadge key={capability} tone="neutral">
                  {translateUiToken(capability, copy)}
                </StatusBadge>
              ))}
            </div>
            {pack.compilerHints.length ? (
              <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                {copy("Compiler hints", "编译提示")}: {pack.compilerHints.join(" · ")}
              </div>
            ) : null}
            {pack.sceneExpectations.length ? (
              <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                {copy("Scene expectations", "场景预期")}: {pack.sceneExpectations.join(" · ")}
              </div>
            ) : null}
            {Object.keys(pack.qualityGates).length ? (
              <div style={{ color: theme.colors.muted, fontSize: "13px", lineHeight: 1.6 }}>
                {copy("Quality gates", "质量门槛")}: {Object.entries(pack.qualityGates).map(([key, value]) => `${translateUiToken(key, copy)}=${typeof value === "string" ? translateUiToken(value, copy) : String(value)}`).join(" · ")}
              </div>
            ) : null}
            <div>
              <div style={{ color: theme.colors.muted, fontSize: "12px", textTransform: "uppercase", letterSpacing: "0.14em" }}>{copy("Sample tasks", "示例任务")}</div>
              <div style={{ display: "grid", gap: "8px", marginTop: "10px" }}>
                {pack.sampleTasks.map((task) => (
                  <div key={task} style={{ color: "rgba(233,239,255,0.76)", fontSize: "13px", lineHeight: 1.5 }}>
                    {task}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </Panel>
      ))}
    </div>
  );
}
