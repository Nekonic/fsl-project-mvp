import type { ComponentChildren } from "preact";
import { useEffect } from "preact/hooks";
import { api } from "../api/client";
import { useSession } from "../api/hooks";
import { to } from "../links";
import { brandLabel, homeCrumb, signOutLabel, topNav } from "../nav";
import { navigate, usePlace } from "../router";
import { t } from "../strings";
import { PageShell, TopNav, type Crumb, type NavLink } from "../ui";

export interface AppPageProps {
  title?: string;
  crumbs?: Crumb[];
  console?: boolean;
  bare?: boolean;
  children: ComponentChildren;
}

export async function signOut(): Promise<void> {
  try {
    await api.post("/api/auth/logout/");
  } finally {
    navigate(to.login(), true);
  }
}

export function AppPage({ title, crumbs, console, bare, children }: AppPageProps) {
  const { me } = useSession();
  const place = usePlace();
  useEffect(() => {
    document.title = title ? `${title} · ${t(brandLabel)}` : t(brandLabel);
  }, [title]);
  const links: NavLink[] = bare || !me
    ? []
    : [
      ...topNav.filter((entry) => !entry.staff || me.is_staff).map((entry) => ({
        label: t(entry.label), href: entry.href, current: place.path.startsWith(entry.href),
      })),
      { label: t(signOutLabel), onClick: () => void signOut() },
    ];
  const shownCrumbs = crumbs && crumbs.length ? [{ label: t(homeCrumb), href: to.home() }, ...crumbs] : [];
  return (
    <PageShell console={console} topnav={<TopNav brand={t(brandLabel)} home={to.home()} crumbs={shownCrumbs} links={links} />}>
      {children}
    </PageShell>
  );
}
