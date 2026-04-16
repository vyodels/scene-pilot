import React from "react";

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
  allCount?: number;
  onSelect(statusId: string): void;
  showOverview?: boolean;
}

export function StatusChain({
  rows,
  globalTerminalItems,
  activeStatus,
  allCount,
  onSelect,
  showOverview = true,
}: StatusChainProps): JSX.Element {
  return (
    <div className="status-chain">
      {showOverview && allCount != null ? (
        <div className="status-chain__overview">
          <button
            type="button"
            className="status-chain__node"
            data-active={activeStatus === "all"}
            onClick={() => onSelect("all")}
          >
            <span className="status-chain__text">全部-{allCount}</span>
          </button>
        </div>
      ) : null}

      {rows.map((row, rowIndex) => (
        <div key={row.key} className="status-chain__row-block">
          <div className="status-chain__row-head">
            {rowIndex > 0 ? <span className="status-chain__row-prefix">→</span> : null}
            <div className="status-chain__row-grid">
              {row.items.map((item, index) => (
                <React.Fragment key={item.statusId}>
                  <div
                    className="status-chain__grid-node"
                    style={{
                      gridColumn: String(index * 2 + 1),
                      gridRow: "1",
                    }}
                  >
                    <button
                      type="button"
                      className="status-chain__node"
                      data-active={activeStatus === item.statusId}
                      data-emphasized={item.emphasized ? "true" : undefined}
                      onClick={() => onSelect(item.statusId)}
                    >
                      <span className="status-chain__text" data-tone={item.tone}>
                        {item.label}-{item.count}
                      </span>
                    </button>
                  </div>
                  {index < row.items.length - 1 ? (
                    <span
                      className="status-chain__connector"
                      style={{
                        gridColumn: String(index * 2 + 2),
                        gridRow: "1",
                      }}
                    >
                      →
                    </span>
                  ) : null}
                  {item.branches?.length ? (
                    <div
                      className="status-chain__grid-branches"
                      style={{
                        gridColumn: String(index * 2 + 1),
                        gridRow: "2",
                      }}
                    >
                      {item.branches.map((branch) => (
                        <div key={`${item.statusId}:${branch.statusId}`} className="status-chain__branch-item">
                          <span className="status-chain__branch-connector">└→</span>
                          <button
                            type="button"
                            className="status-chain__branch"
                            data-active={activeStatus === branch.statusId}
                            data-tone={branch.tone}
                            onClick={() => onSelect(branch.statusId)}
                          >
                            <span className="status-chain__branch-text">
                              {branch.label}-{branch.count}
                            </span>
                          </button>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </React.Fragment>
              ))}
            </div>
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
              data-tone={item.tone}
              onClick={() => onSelect(item.statusId)}
            >
              <span className="status-chain__global-text">{item.label}-{item.count}</span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
