import React from "react";

export interface FunnelStageItem {
  milestoneId: string;
  label: string;
  count: number;
  annotation?: string;
}

interface FunnelStageBarProps {
  items: FunnelStageItem[];
  activeMilestoneId: string;
  onSelect(milestoneId: string): void;
}

export function FunnelStageBar({ items, activeMilestoneId, onSelect }: FunnelStageBarProps): JSX.Element {
  return (
    <div className="funnel-stage-bar">
      {items.map((item, index) => {
        const selected = item.milestoneId === activeMilestoneId;
        return (
          <React.Fragment key={item.milestoneId}>
            <button
              type="button"
              className="funnel-stage-bar__item"
              data-active={selected}
              onClick={() => onSelect(item.milestoneId)}
            >
              <span className="funnel-stage-bar__label">{item.label}</span>
              <span className="funnel-stage-bar__count">{item.count}</span>
              {item.annotation ? <span className="funnel-stage-bar__annotation">{item.annotation}</span> : null}
            </button>
            {index < items.length - 1 ? <span className="funnel-stage-bar__connector">›</span> : null}
          </React.Fragment>
        );
      })}
    </div>
  );
}
