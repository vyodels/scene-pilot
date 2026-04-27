import React from "react";

export interface ScoreMetric {
  label: string;
  value: number;
}

export function candidateInitial(name: string): string {
  const trimmed = name.trim();
  return trimmed ? Array.from(trimmed)[0] ?? "投" : "投";
}

export function CandidateAvatar({
  name,
  active,
  attention,
  title,
  onClick,
}: {
  name: string;
  active?: boolean;
  attention?: boolean;
  title?: string;
  onClick?: () => void;
}): JSX.Element {
  const content = (
    <>
      {candidateInitial(name)}
      {attention ? <span aria-hidden="true" /> : null}
    </>
  );

  if (onClick) {
    return (
      <button
        type="button"
        className="application-followup-avatar"
        data-active={active}
        onClick={onClick}
        aria-label={title ?? name}
        title={title ?? name}
      >
        {content}
      </button>
    );
  }

  return (
    <span className="application-followup-avatar" data-active={active} title={title ?? name}>
      {content}
    </span>
  );
}

export function ApplicationRecordCard({
  name,
  time,
  location,
  age,
  experienceYears,
  education,
  jobTitle,
  jobLocation,
  statusLabel,
  statusTone,
  active,
  attention,
  onClick,
}: {
  name: string;
  time: string;
  location: string;
  age: string;
  experienceYears: string;
  education: string;
  jobTitle: string;
  jobLocation: string;
  statusLabel: string;
  statusTone: "positive" | "neutral" | "warning" | "critical";
  active?: boolean;
  attention?: boolean;
  onClick(): void;
}): JSX.Element {
  const resolvedJobLocation = jobLocation.trim();

  return (
    <button
      type="button"
      className="application-followup-record"
      data-active={active ? "true" : undefined}
      onClick={onClick}
    >
      <CandidateAvatar name={name} attention={attention} />
      <span className="application-followup-record__main">
        <span className="application-followup-record__topline">
          <strong>{name}</strong>
          <time>{time || "—"}</time>
        </span>
        <span className="application-followup-record__profile-line">
          <span>{location}</span>
          <span>{age}</span>
          <span>{experienceYears}</span>
          <span>{education}</span>
        </span>
        <span className="application-followup-record__application-line">
          <span data-kind="job">{jobTitle}</span>
          {resolvedJobLocation && resolvedJobLocation !== "—" ? (
            <span data-kind="location">{resolvedJobLocation}</span>
          ) : null}
          <span data-kind="status" data-tone={statusTone}>{statusLabel}</span>
        </span>
      </span>
    </button>
  );
}

export function ScoreBars({ metrics }: { metrics: ScoreMetric[] }): JSX.Element {
  return (
    <div className="application-followup-score-bars">
      {metrics.map((metric) => (
        <div key={metric.label} className="application-followup-score-bars__row">
          <span>{metric.label}</span>
          <div className="application-followup-score-bars__track" aria-hidden="true">
            <span style={{ width: `${metric.value}%` }} />
          </div>
          <strong>{metric.value}</strong>
        </div>
      ))}
    </div>
  );
}

function FollowUpPanelHeader({
  label,
  expanded,
  collapsedSummary,
  disabled,
  onToggle,
}: {
  label: string;
  expanded: boolean;
  collapsedSummary?: React.ReactNode;
  disabled?: boolean;
  onToggle(): void;
}): JSX.Element {
  const hasCollapsedSummary =
    collapsedSummary !== undefined && collapsedSummary !== null && collapsedSummary !== false;

  return (
    <button
      type="button"
      className="application-followup-panel-header"
      aria-expanded={expanded}
      data-disabled={disabled ? "true" : undefined}
      onClick={onToggle}
    >
      <span className="application-followup-panel-header__label">{label}</span>
      <span
        className="application-followup-panel-header__summary"
        aria-hidden={!hasCollapsedSummary || expanded ? "true" : undefined}
      >
        {!expanded && hasCollapsedSummary ? collapsedSummary : null}
      </span>
      <i aria-hidden="true">{expanded ? "⌃" : "⌄"}</i>
    </button>
  );
}

export function ApplicationScoreCard({
  label,
  score,
  quality,
  metrics,
  primary,
  expanded = true,
  collapsedSummary,
  disabled,
  onClick,
  onToggle,
}: {
  label: string;
  score: React.ReactNode;
  quality: string;
  metrics: ScoreMetric[];
  primary?: boolean;
  expanded?: boolean;
  collapsedSummary?: React.ReactNode;
  disabled?: boolean;
  onClick(): void;
  onToggle?: () => void;
}): JSX.Element {
  return (
    <section
      className="application-followup-score-card"
      data-primary={primary ? "true" : undefined}
      data-disabled={disabled ? "true" : undefined}
    >
      <FollowUpPanelHeader
        label={label}
        expanded={expanded}
        collapsedSummary={collapsedSummary}
        disabled={disabled}
        onToggle={onToggle ?? onClick}
      />
      {expanded ? (
        <button type="button" className="application-followup-score-card__body" disabled={disabled} onClick={onClick}>
          <strong>{score}</strong>
          <em>{quality}</em>
          <ScoreBars metrics={metrics} />
        </button>
      ) : null}
    </section>
  );
}

export function FollowUpInfoCard({
  title,
  detail,
  meta,
  onClick,
}: {
  title: string;
  detail: React.ReactNode;
  meta?: React.ReactNode;
  onClick?: () => void;
}): JSX.Element {
  const content = (
    <>
      <strong>{title}</strong>
      <span>{detail}</span>
      {meta ? <small>{meta}</small> : null}
    </>
  );

  if (onClick) {
    return (
      <button type="button" className="application-followup-info-card" onClick={onClick}>
        {content}
      </button>
    );
  }

  return <div className="application-followup-info-card">{content}</div>;
}

export function FollowUpCollapsiblePanel({
  label,
  expanded,
  children,
  collapsedSummary,
  disabled,
  actionLabel,
  onToggle,
  onAction,
}: {
  label: string;
  expanded: boolean;
  children: React.ReactNode;
  collapsedSummary?: React.ReactNode;
  disabled?: boolean;
  actionLabel: string;
  onToggle(): void;
  onAction(): void;
}): JSX.Element {
  return (
    <section className="application-followup-side-panel" data-disabled={disabled ? "true" : undefined}>
      <FollowUpPanelHeader
        label={label}
        expanded={expanded}
        collapsedSummary={collapsedSummary}
        disabled={disabled}
        onToggle={onToggle}
      />
      {expanded ? (
        <div>
          <div className="application-followup-side-panel__body">{children}</div>
          <button type="button" disabled={disabled} onClick={onAction}>
            {actionLabel}
          </button>
        </div>
      ) : null}
    </section>
  );
}
