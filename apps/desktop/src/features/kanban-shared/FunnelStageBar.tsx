import React, { useEffect, useMemo, useRef, useState } from "react";

export interface FunnelStageItem {
  milestoneId: string;
  label: string;
  count: number;
}

interface FunnelStageBarProps {
  items: FunnelStageItem[];
  activeMilestoneId: string;
  onSelect(milestoneId: string): void;
}

function estimateFunnelItemWidth(label: string): number {
  const contentWidth = Array.from(label).reduce((total, char) => {
    if (/[A-Za-z0-9]/.test(char)) {
      return total + 8;
    }
    if (char === "·" || char === "-" || char === " ") {
      return total + 5;
    }
    return total + 12;
  }, 0);
  return contentWidth + 30;
}

function splitItemsIntoRows(items: FunnelStageItem[], availableWidth: number): FunnelStageItem[][] {
  const rows: FunnelStageItem[][] = [];
  let currentRow: FunnelStageItem[] = [];
  let currentWidth = 0;
  const maxWidth = Math.max(availableWidth, 720);
  const connectorWidth = 18;

  for (const item of items) {
    const itemWidth = estimateFunnelItemWidth(`${item.label}-${item.count}`);
    const nextWidth = currentRow.length ? currentWidth + connectorWidth + itemWidth : currentWidth + itemWidth;
    if (currentRow.length && nextWidth > maxWidth) {
      rows.push(currentRow);
      currentRow = [item];
      currentWidth = itemWidth;
      continue;
    }
    currentRow.push(item);
    currentWidth = nextWidth;
  }

  if (currentRow.length) {
    rows.push(currentRow);
  }

  return rows;
}

export function FunnelStageBar({ items, activeMilestoneId, onSelect }: FunnelStageBarProps): JSX.Element {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [containerWidth, setContainerWidth] = useState(1200);

  useEffect(() => {
    if (!containerRef.current || typeof ResizeObserver === "undefined") {
      return undefined;
    }
    const observer = new ResizeObserver((entries) => {
      const nextWidth = entries[0]?.contentRect.width ?? 0;
      if (nextWidth > 0) {
        setContainerWidth(nextWidth);
      }
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  const rows = useMemo(() => splitItemsIntoRows(items, containerWidth - 8), [containerWidth, items]);

  return (
    <div ref={containerRef} className="funnel-stage-bar">
      {rows.map((row, rowIndex) => (
        <div key={`funnel-row-${rowIndex + 1}`} className="funnel-stage-bar__row">
          {rowIndex > 0 ? <span className="funnel-stage-bar__row-prefix">→</span> : null}
          <div className="funnel-stage-bar__row-items">
            {row.map((item, index) => {
              const selected = item.milestoneId === activeMilestoneId;
              return (
                <React.Fragment key={item.milestoneId}>
                  <button
                    type="button"
                    className="funnel-stage-bar__item"
                    data-active={selected}
                    onClick={() => onSelect(item.milestoneId)}
                  >
                    <span className="funnel-stage-bar__text">{item.label}-{item.count}</span>
                  </button>
                  {index < row.length - 1 ? <span className="funnel-stage-bar__connector">→</span> : null}
                </React.Fragment>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
