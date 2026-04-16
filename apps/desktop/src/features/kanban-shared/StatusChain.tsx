import React from "react";
import { StatusBadge } from "../../components";

export interface StatusChainBranchItem {
  statusId: string;
  label: string;
  count: number;
  tone: "positive" | "neutral" | "warning" | "critical";
}

export interface StatusChainNodeItem {
  statusId: string;
  label: string;
  count: number;
  tone: "positive" | "neutral" | "warning" | "critical";
  emphasized?: boolean;
  branches?: StatusChainBranchItem[];
}

export interface StatusChainRow {
  key: string;
  items: StatusChainNodeItem[];
}

interface StatusChainProps {
  rows: StatusChainRow[];
  globalTerminalItems: StatusChainBranchItem[];
  activeStatus: string;
  allCount: number;
  onSelect(statusId: string): void;
}

export function StatusChain({
  rows,
  globalTerminalItems,
  activeStatus,
  allCount,
  onSelect,
}: StatusChainProps): JSX.Element {
  return (
    <div className="status-chain">
      <div className="status-chain__overview">
        <button
          type="button"
          className="status-chain__node"
          data-active={activeStatus === "all"}
          onClick={() => onSelect("all")}
        >
          <span className="status-chain__label">全部</span>
          <span className="status-chain__count">{allCount}</span>
        </button>
      </div>

      {rows.map((row, rowIndex) => (
        <div key={row.key} className="status-chain__row-block">
          <div className="status-chain__row">
            {rowIndex > 0 ? <span className="status-chain__row-prefix">›</span> : null}
            {row.items.map((item, index) => (
              <React.Fragment key={item.statusId}>
                <div className="status-chain__item-group">
                  <button
                    type="button"
                    className="status-chain__node"
                    data-active={activeStatus === item.statusId}
                    data-emphasized={item.emphasized ? "true" : undefined}
                    onClick={() => onSelect(item.statusId)}
                  >
                    <span className="status-chain__label">{item.label}</span>
                    <span className="status-chain__count" data-tone={item.tone}>
                      {item.count}
                    </span>
                  </button>
                  {item.branches?.length ? (
                    <div className="status-chain__branches">
                      {item.branches.map((branch) => (
                        <button
                          key={branch.statusId}
                          type="button"
                          className="status-chain__branch"
                          data-active={activeStatus === branch.statusId}
                          data-tone={branch.tone}
                          onClick={() => onSelect(branch.statusId)}
                        >
                          <span className="status-chain__branch-label">{branch.label}</span>
                          <span className="status-chain__branch-count">{branch.count}</span>
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
                {index < row.items.length - 1 ? <span className="status-chain__connector">›</span> : null}
              </React.Fragment>
            ))}
          </div>
        </div>
      ))}

      {globalTerminalItems.length ? (
        <div className="status-chain__global-terminal">
          {globalTerminalItems.map((item) => (
            <button
              key={item.statusId}
              type="button"
              className="status-chain__global-pill"
              data-active={activeStatus === item.statusId}
              onClick={() => onSelect(item.statusId)}
            >
              <span>{item.label}</span>
              <StatusBadge tone={item.tone}>{item.count}</StatusBadge>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
