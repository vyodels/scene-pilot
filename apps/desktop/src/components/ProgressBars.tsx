import React from "react";
import { theme } from "../lib/theme";
import type { PipelineStage } from "../lib/types";

interface ProgressBarsProps {
  stages: PipelineStage[];
}

export function ProgressBars({ stages }: ProgressBarsProps): JSX.Element {
  return (
    <div style={{ display: "grid", gap: "10px" }}>
      {stages.map((stage) => {
        const target = stage.target ?? Math.max(stage.value, 1);
        const width = `${Math.min(100, Math.round((stage.value / target) * 100))}%`;
        return (
          <div key={stage.label} style={{ display: "grid", gap: "6px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: "8px", fontSize: "13px" }}>
              <span>{stage.label}</span>
              <span style={{ color: theme.colors.muted }}>
                {stage.value}/{target}
              </span>
            </div>
            <div style={{ height: "10px", borderRadius: "999px", background: "rgba(255,255,255,0.08)", overflow: "hidden" }}>
              <div style={{ width, height: "100%", borderRadius: "999px", background: "linear-gradient(90deg, rgba(122,167,255,0.9), rgba(93,216,163,0.9))" }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

