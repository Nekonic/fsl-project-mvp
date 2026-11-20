import type { ComponentChildren } from "preact";
import { cx } from "./classes";
import { Link } from "./Button";
import { Icon } from "./Icon";

export interface Crumb {
  label: ComponentChildren;
  href?: string;
}

export interface NavLink {
  label: ComponentChildren;
  href?: string;
  current?: boolean;
  onClick?: () => void;
}

export interface TopNavProps {
  brand: ComponentChildren;
  home: string;
  crumbs?: Crumb[];
  links?: NavLink[];
}

export function TopNav({ brand, home, crumbs = [], links = [] }: TopNavProps) {
  return (
    <header class="topnav">
      <Link href={home} className="topnav-brand"><Icon name="brand" size={22} /><span>{brand}</span></Link>
      {crumbs.length > 0 && (
        <nav class="topnav-crumbs">
          {crumbs.map((crumb, index) => {
            const last = index === crumbs.length - 1;
            return [
              index > 0 && <span key={`s${index}`} aria-hidden="true">/</span>,
              crumb.href && !last
                ? <Link key={index} href={crumb.href}>{crumb.label}</Link>
                : <span key={index} aria-current={last ? "page" : undefined}>{crumb.label}</span>,
            ];
          })}
        </nav>
      )}
      <nav class="topnav-links">
        {links.map((link, index) => link.href
          ? <Link key={index} href={link.href} current={link.current}>{link.label}</Link>
          : <button key={index} type="button" onClick={link.onClick}>{link.label}</button>)}
      </nav>
    </header>
  );
}

export interface PageShellProps {
  topnav: ComponentChildren;
  console?: boolean;
  children: ComponentChildren;
}

export function PageShell({ topnav, console, children }: PageShellProps) {
  return (
    <div class={cx("app", console && "app-console")}>
      {topnav}
      <main class="app-main">{children}</main>
    </div>
  );
}

export interface PageBodyProps {
  narrow?: boolean;
  children: ComponentChildren;
}

export function PageBody({ narrow, children }: PageBodyProps) {
  return (
    <div class="page-wrap page-body">
      {narrow ? <section class="page-narrow">{children}</section> : children}
    </div>
  );
}
