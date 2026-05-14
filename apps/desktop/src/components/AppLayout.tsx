import React from "react";
import type { CSSProperties, ReactNode } from "react";

interface AppLayoutProps {
  sidebar: ReactNode;
  topbar?: ReactNode;
  hideTopbar?: boolean;
  sidebarExpanded?: boolean;
  children: ReactNode;
}

export function AppLayout({ sidebar, topbar, hideTopbar, sidebarExpanded, children }: AppLayoutProps): JSX.Element {
  const layoutStyle = {
    "--workspace-sidebar-width": sidebarExpanded ? "196px" : "var(--layout-sider-width)",
  } as CSSProperties;

  return (
    <div className="app-layout" data-sidebar-expanded={sidebarExpanded ? "true" : undefined} style={layoutStyle}>
      <div className="app-layout__sidebar">{sidebar}</div>
      <div className="app-layout__main" data-hide-topbar={hideTopbar ? "true" : undefined}>
        {hideTopbar ? null : <div className="app-layout__topbar">{topbar}</div>}
        <main className="app-layout__content">{children}</main>
      </div>
    </div>
  );
}
