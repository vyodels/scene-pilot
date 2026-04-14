import React, { useState } from "react";
import { Panel, StatusBadge } from "../../components";
import { clampText, formatCompactDate } from "../../lib/format";
import type { CandidateRecord } from "../../lib/types";

interface CandidatesViewProps {
  candidates: CandidateRecord[];
}

export function CandidatesView({ candidates }: CandidatesViewProps): JSX.Element {
  const [selectedId, setSelectedId] = useState(candidates[0]?.id ?? "");
  const selected = candidates.find((candidate) => candidate.id === selectedId) ?? candidates[0];

  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.2fr) minmax(320px, 0.8fr)", gap: "18px", alignItems: "start" }}>
      <Panel title="Candidate pipeline" eyebrow="Boss直聘" description="The current working set ordered by screening readiness.">
        <div style={{ display: "grid", gap: "10px" }}>
          {candidates.map((candidate) => (
            <button
              key={candidate.id}
              type="button"
              onClick={() => setSelectedId(candidate.id)}
              style={{
                cursor: "pointer",
                width: "100%",
                textAlign: "left",
                padding: "14px",
                borderRadius: "16px",
                border: `1px solid ${candidate.id === selectedId ? "rgba(122,167,255,0.38)" : "rgba(255,255,255,0.08)"}`,
                background: candidate.id === selectedId ? "rgba(122,167,255,0.12)" : "rgba(255,255,255,0.02)",
                color: "inherit",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: "10px", alignItems: "start" }}>
                <div>
                  <div style={{ fontSize: "16px", fontWeight: 700 }}>{candidate.name}</div>
                  <div style={{ color: "rgba(233,239,255,0.72)", fontSize: "13px" }}>
                    {candidate.title} · {candidate.location} · {candidate.platform}
                  </div>
                </div>
                <StatusBadge tone={candidate.status === "cooldown" || candidate.status === "rejected" ? "neutral" : candidate.status === "screening" ? "positive" : "warning"}>
                  {candidate.matchScore}%
                </StatusBadge>
              </div>
              <div style={{ marginTop: "10px", color: "rgba(233,239,255,0.72)", fontSize: "13px" }}>
                {clampText(candidate.summary, 140)}
              </div>
            </button>
          ))}
        </div>
      </Panel>

      <Panel title={selected?.name ?? "No candidate selected"} eyebrow="Selected profile" description="Detailed context for the active working item.">
        {selected ? (
          <div style={{ display: "grid", gap: "14px" }}>
            <div style={{ display: "grid", gap: "8px" }}>
              <StatusBadge tone={selected.status === "cooldown" ? "neutral" : selected.status === "screening" ? "positive" : "warning"}>{selected.status}</StatusBadge>
              <div style={{ fontSize: "22px", fontWeight: 800 }}>{selected.title}</div>
              <div style={{ color: "rgba(233,239,255,0.72)", fontSize: "13px" }}>
                {selected.location} · {selected.experienceYears} years · JD: {selected.jdTitle}
              </div>
            </div>
            <div style={{ display: "grid", gap: "8px" }}>
              <strong>Next action</strong>
              <p style={{ margin: 0, color: "rgba(233,239,255,0.72)", lineHeight: 1.6 }}>{selected.nextAction}</p>
            </div>
            <div style={{ display: "grid", gap: "8px" }}>
              <strong>Resume and audit</strong>
              <p style={{ margin: 0, color: "rgba(233,239,255,0.72)", lineHeight: 1.6 }}>{selected.resumeAvailable ? "Resume is available for scoring and review." : "Resume is pending capture from the communication step."}</p>
              <div style={{ color: "rgba(233,239,255,0.6)", fontSize: "12px" }}>
                {selected.lastContactedAt ? `Last contacted ${formatCompactDate(selected.lastContactedAt)}` : "No outbound contact yet"}
              </div>
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
              {selected.tags.map((tag) => (
                <StatusBadge key={tag} tone="neutral">
                  {tag}
                </StatusBadge>
              ))}
            </div>
          </div>
        ) : null}
      </Panel>
    </div>
  );
}

