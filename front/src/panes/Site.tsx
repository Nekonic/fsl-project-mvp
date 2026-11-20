import { useEffect, useRef, useState } from "preact/hooks";
import { api, type Schemas } from "../api/client";
import { useEvents, useResource } from "../api/hooks";
import { clockSeconds, count } from "../format";
import { errorText, t } from "../strings";
import { Button, ErrorNotice, FrameEmpty, Input, Pane, PaneHeader, Select, Table, Text, type Column, SiteSplit, SideList, SiteBar, SiteAddress, SiteFrame } from "../ui";
import type { PaneProps, Side } from "./types";

type SiteRequest = Schemas["SiteRequest"];

export const SITE_PORT = 8002;

const STATE_PATH = {
  attack: "/api/rounds/{round_id}/attack/state/",
  defence: "/api/rounds/{round_id}/defence/state/",
} as const;

const REQUEST_EVENTS = ["action.sent", "round.started"];

export function siteBase(round: number, host: string): string {
  return `${location.protocol}//${location.hostname}:${SITE_PORT}/site/${round}/${host}`;
}

function shownAddress(round: number, host: string, framePath: string): string {
  const prefix = `/site/${round}/${host}`;
  const rest = framePath.startsWith(prefix) ? framePath.slice(prefix.length) : framePath;
  return `http://${host}${rest.startsWith("/") ? rest : `/${rest}`}`;
}

function pathFromAddress(host: string, typed: string): string {
  const text = typed.trim();
  try {
    const parsed = new URL(text.includes("://") ? text : `http://${host}${text.startsWith("/") ? "" : "/"}${text}`);
    return `${parsed.pathname}${parsed.search}`;
  } catch {
    return "/";
  }
}

function requestPath(url: string): string {
  try {
    const parsed = new URL(url, "http://site.invalid");
    return `${parsed.pathname}${parsed.search}`;
  } catch {
    return url;
  }
}

function useTargetHosts(round: number, side: Side) {
  const state = useResource(STATE_PATH[side], { params: { round_id: round } });
  return { hosts: state.data?.target.hosts ?? [], error: state.error };
}

function useSiteRequests(round: number) {
  const first = useResource("/api/rounds/{round_id}/site/requests/", { params: { round_id: round } });
  const [later, setLater] = useState<SiteRequest[]>([]);
  const known = [...later, ...(first.data ?? [])];
  const newest = useRef(0);
  newest.current = known.reduce((most, request) => Math.max(most, request.id), 0);

  useEvents(first.data ? round : null, REQUEST_EVENTS, () => {
    void api.get("/api/rounds/{round_id}/site/requests/", { params: { round_id: round }, query: { after: newest.current } })
      .then((fresh) => {
        if (fresh.length) setLater((was) => [...fresh.filter((request) => !was.some((seen) => seen.id === request.id)), ...was]);
      })
      .catch(() => undefined);
  });

  const rows = [...known].sort((one, other) => other.id - one.id);
  return { rows, error: first.error, loading: first.loading && !first.data };
}

const columns: Column<SiteRequest>[] = [
  { key: "at", label: t("col.time"), kind: "mono", cell: (request) => clockSeconds(request.at) },
  { key: "request", label: t("site.column.request"), kind: "cut", cell: (request) => <Text mono>{`${request.method} ${requestPath(request.url)}`}</Text>, title: (request) => request.url },
  { key: "status", label: t("site.column.status"), kind: "end", cell: (request) => <Text mono>{request.status}</Text> },
];

function RequestList({ round }: { round: number }) {
  const { rows, error, loading } = useSiteRequests(round);
  return (
    <SideList>
      <PaneHeader title={t("site.requests")} meta={t("site.request_count", { count: count(rows.length) })} />
      {loading
        ? <Text tone="muted">{t("common.loading")}</Text>
        : error
          ? <ErrorNotice error={error} />
          : <Table variant="compact" columns={columns} rows={rows} rowKey={(request) => request.id} empty={t("site.no_requests")} />}
    </SideList>
  );
}

interface AddressBarProps {
  host: string;
  hosts: string[];
  address: string;
  onHost: (host: string) => void;
  onGo: (path: string) => void;
  onReload: () => void;
}

function AddressBar({ host, hosts, address, onHost, onGo, onReload }: AddressBarProps) {
  const [typed, setTyped] = useState(address);
  useEffect(() => setTyped(address), [address]);
  return (
    <SiteBar>
      <Button small label={t("site.reload")} onClick={onReload}>↻</Button>
      {hosts.length > 1 && <Select value={host} options={hosts.map((one) => ({ value: one, label: one }))} onValue={onHost} label={t("site.host")} />}
      <SiteAddress warning={address.startsWith("http://") ? t("site.not_secure") : undefined}>
        <Input mono value={typed} onValue={setTyped} aria-label={t("site.address")} spellcheck={false}
          onKeyDown={(event) => { if (event.key === "Enter") onGo(pathFromAddress(host, typed)); }} />
      </SiteAddress>
    </SiteBar>
  );
}

export function Site({ round, side }: PaneProps) {
  const { hosts, error } = useTargetHosts(round, side);
  const [chosenHost, setChosenHost] = useState<string | null>(null);
  const host = chosenHost && hosts.includes(chosenHost) ? chosenHost : hosts[0];
  const [path, setPath] = useState("/");
  const [shownPath, setShownPath] = useState<string | null>(null);
  const [loads, setLoads] = useState(0);
  const frame = useRef<HTMLIFrameElement>(null);

  useEffect(() => {
    const heard = (message: MessageEvent) => {
      if (!frame.current || message.source !== frame.current.contentWindow) return;
      const said = message.data as { site?: unknown } | null;
      if (said && typeof said.site === "string") setShownPath(said.site);
    };
    window.addEventListener("message", heard);
    return () => window.removeEventListener("message", heard);
  }, []);

  const go = (next: string) => {
    setPath(next);
    setShownPath(null);
    setLoads((was) => was + 1);
  };

  const address = host ? (shownPath ? shownAddress(round, host, shownPath) : `http://${host}${path}`) : "";
  const reload = () => go(host && shownPath ? pathFromAddress(host, shownAddress(round, host, shownPath)) : path);

  return (
    <Pane scroll={false}>
      {host && <AddressBar host={host} hosts={hosts} address={address} onHost={(next) => { setChosenHost(next); go("/"); }} onGo={go} onReload={reload} />}
      <SiteSplit>
        {host
          ? <SiteFrame key={`${host}-${loads}`} frameRef={frame} src={`${siteBase(round, host)}${path}`} title={t("pane.site")} />
          : <FrameEmpty title={t("pane.site")}>{error ? errorText(error) : t("common.loading")}</FrameEmpty>}
        <RequestList round={round} />
      </SiteSplit>
    </Pane>
  );
}
