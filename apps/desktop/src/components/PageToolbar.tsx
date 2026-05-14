import React from "react";
import type { HTMLAttributes, ReactNode } from "react";

function classNames(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(" ");
}

interface PageToolbarProps extends HTMLAttributes<HTMLElement> {
  children: ReactNode;
}

export function PageToolbar({ children, className, ...props }: PageToolbarProps): JSX.Element {
  return (
    <header className={classNames("page-toolbar", className)} {...props}>
      {children}
    </header>
  );
}

interface PageToolbarGroupProps extends HTMLAttributes<HTMLDivElement> {
  align?: "start" | "end";
  children: ReactNode;
}

export function PageToolbarGroup({ align = "start", children, className, ...props }: PageToolbarGroupProps): JSX.Element {
  return (
    <div className={classNames("page-toolbar__group", className)} data-align={align} {...props}>
      {children}
    </div>
  );
}
