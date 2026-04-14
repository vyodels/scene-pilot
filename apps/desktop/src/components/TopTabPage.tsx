import React from "react";
import { SectionTabs, type SectionTabItem } from "./SectionTabs";

interface TopTabPageProps {
  items: SectionTabItem[];
  active: string;
  onChange(key: string): void;
  children: React.ReactNode;
}

export function TopTabPage({ items, active, onChange, children }: TopTabPageProps): JSX.Element {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "10px", minWidth: 0 }}>
      <div style={{ position: "sticky", top: "76px", zIndex: 12, alignSelf: "stretch", flex: "0 0 auto" }}>
        <SectionTabs items={items} active={active} onChange={onChange} variant="topbar" />
      </div>
      <div style={{ display: "grid", gap: "12px", minWidth: 0, alignContent: "start" }}>{children}</div>
    </div>
  );
}
