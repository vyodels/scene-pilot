import React from "react";
import type { ReactNode } from "react";

interface AppLayoutProps {
  sidebar: ReactNode;
  topbar: ReactNode;
  children: ReactNode;
}

export function AppLayout({ sidebar, topbar, children }: AppLayoutProps): JSX.Element {
  return (
    <div className="app-layout">
      <div className="app-layout__sidebar">{sidebar}</div>
      <div className="app-layout__main">
        <div className="app-layout__topbar">{topbar}</div>
        <main className="app-layout__content">{children}</main>
      </div>
    </div>
  );
}
