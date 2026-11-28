import { useEffect, useRef, useState } from "preact/hooks";

export interface Place {
  path: string;
  search: URLSearchParams;
  hash: string;
}

const listeners = new Set<() => void>();
const leaveGuards = new Set<() => string | null>();

function here(): Place {
  return { path: location.pathname, search: new URLSearchParams(location.search), hash: location.hash.slice(1) };
}

function told(): void {
  listeners.forEach((listener) => listener());
}

if (typeof window !== "undefined") window.addEventListener("popstate", told);

export function mayLeave(): boolean {
  for (const guard of leaveGuards) {
    const warning = guard();
    if (warning && !window.confirm(warning)) return false;
  }
  return true;
}

export function useLeaveGuard(warning: string | null): () => void {
  const held = useRef(warning);
  held.current = warning;
  useEffect(() => {
    const guard = () => held.current;
    const unloading = (event: BeforeUnloadEvent) => {
      if (!held.current) return;
      event.preventDefault();
      event.returnValue = held.current;
    };
    leaveGuards.add(guard);
    window.addEventListener("beforeunload", unloading);
    return () => {
      leaveGuards.delete(guard);
      window.removeEventListener("beforeunload", unloading);
    };
  }, []);
  return () => {
    held.current = null;
  };
}

export function navigate(to: string, replace = false): void {
  if (to === location.pathname + location.search + location.hash) return;
  if (!mayLeave()) return;
  if (replace) history.replaceState(null, "", to);
  else history.pushState(null, "", to);
  if (!to.includes("#") || to.split("#")[0] !== location.pathname) window.scrollTo(0, 0);
  told();
}

export function setHash(hash: string): void {
  history.replaceState(null, "", `${location.pathname}${location.search}${hash ? `#${hash}` : ""}`);
  told();
}

export function usePlace(): Place {
  const [place, setPlace] = useState(here);
  useEffect(() => {
    const changed = () => setPlace(here());
    listeners.add(changed);
    return () => {
      listeners.delete(changed);
    };
  }, []);
  return place;
}

export type Params = Record<string, string>;

export function matched(pattern: string, path: string): Params | null {
  const want = pattern.split("/").filter(Boolean);
  const got = path.split("/").filter(Boolean);
  if (want.length !== got.length) return null;
  const params: Params = {};
  for (let index = 0; index < want.length; index += 1) {
    const part = want[index] as string;
    const value = got[index] as string;
    if (part.startsWith(":")) params[part.slice(1)] = decodeURIComponent(value);
    else if (part !== value) return null;
  }
  return params;
}

export function followLink(event: MouseEvent, href: string): void {
  if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  if (!href.startsWith("/")) return;
  event.preventDefault();
  navigate(href);
}

export function usePaneShownAgain(pane: string, onShown: () => void): void {
  const place = usePlace();
  const shown = place.hash === pane;
  const was = useRef(shown);
  const latest = useRef(onShown);
  latest.current = onShown;
  useEffect(() => {
    if (shown && !was.current) latest.current();
    was.current = shown;
  }, [shown]);
}
