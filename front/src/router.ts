import { useEffect, useState } from "preact/hooks";

export interface Place {
  path: string;
  search: URLSearchParams;
  hash: string;
}

const listeners = new Set<() => void>();

function here(): Place {
  return { path: location.pathname, search: new URLSearchParams(location.search), hash: location.hash.slice(1) };
}

function told(): void {
  listeners.forEach((listener) => listener());
}

if (typeof window !== "undefined") window.addEventListener("popstate", told);

export function navigate(to: string, replace = false): void {
  if (to === location.pathname + location.search + location.hash) return;
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
