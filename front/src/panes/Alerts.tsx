import { useCallback, useEffect, useRef, useState } from "preact/hooks";
import { api, ApiError, type Schemas } from "../api/client";
import { useEvents, useResource } from "../api/hooks";
import { clock, clockSeconds, count } from "../format";
import { t, tFor } from "../strings";
import { Badge, Button, ErrorNotice, Field, Filters, Form, Input, Loading, Pane, PaneSection, Select, Table, Text, type Column } from "../ui";
import type { PaneProps } from "./types";

type Alert = Schemas["Alert"];
type TrafficOrigin = Schemas["TrafficOrigin"];
type EngineFilter = "" | "ids" | "waf";

interface AlertFilter {
  engine: EngineFilter;
  rule: string;
  src: string;
}

const NO_FILTER: AlertFilter = { engine: "", rule: "", src: "" };
const ALERT_EVENTS = ["alert.seen"];
const COUNT_EVENTS = ["alert.seen", "round.ended"];

const ENGINE_OPTIONS = [
  { value: "", label: t("alerts.engine.all") },
  { value: "ids", label: t("engine.ids") },
  { value: "waf", label: t("engine.waf") },
];

function queryOf(filter: AlertFilter, after: number) {
  return {
    after,
    ...(filter.engine ? { engine: filter.engine } : {}),
    ...(filter.rule.trim() ? { rule: filter.rule.trim() } : {}),
    ...(filter.src.trim() ? { src: filter.src.trim() } : {}),
  };
}

export function useAlertFeed(round: number, filter: AlertFilter) {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [error, setError] = useState<ApiError | undefined>(undefined);
  const [loading, setLoading] = useState(true);
  const [more, setMore] = useState(false);
  const cursor = useRef(0);
  const asked = useRef(0);

  const fetchFrom = useCallback(async (fresh: boolean) => {
    const ask = fresh ? ++asked.current : asked.current;
    if (fresh) cursor.current = 0;
    setLoading(true);
    try {
      const said = await api.get("/api/rounds/{round_id}/defence/alerts/", { params: { round_id: round }, query: queryOf(filter, cursor.current) });
      if (ask !== asked.current) return;
      cursor.current = said.next;
      setAlerts((was) => {
        const known = fresh ? new Map<number, Alert>() : new Map(was.map((one) => [one.id, one]));
        said.alerts.forEach((one) => known.set(one.id, one));
        return [...known.values()].sort((a, b) => b.id - a.id);
      });
      setMore(said.alerts.length > 0);
      setError(undefined);
    } catch (failed) {
      if (ask === asked.current) setError(failed instanceof ApiError ? failed : new ApiError(0, [{ path: "", code: "network" }]));
    } finally {
      if (ask === asked.current) setLoading(false);
    }
  }, [round, filter]);

  useEffect(() => {
    void fetchFrom(true);
  }, [fetchFrom]);

  useEvents(round, ALERT_EVENTS, () => void fetchFrom(false));

  return { alerts, error, loading, more, loadMore: () => void fetchFrom(false) };
}

const ALERT_COLUMNS: Column<Alert>[] = [
  { key: "time", label: t("col.time"), kind: "mono", cell: (row) => clockSeconds(row.time) },
  { key: "engine", label: t("col.engine"), cell: (row) => <Badge tone={row.engine === "ids" ? "info" : "neutral"}>{tFor("engine", row.engine)}</Badge> },
  { key: "rule", label: t("alerts.col.rule"), kind: "mono", cell: (row) => row.rule },
  { key: "signature", label: t("alerts.col.signature"), kind: "wrap", cell: (row) => row.signature },
  { key: "src", label: t("col.origin_ip"), kind: "mono", cell: (row) => row.src_ip ?? <Text tone="faint">—</Text> },
  { key: "uri", label: t("alerts.col.uri"), kind: "break", cell: (row) => <Text mono small>{row.uri}</Text> },
  { key: "blocked", label: t("col.blocked"), cell: (row) => (row.blocked ? <Badge tone="danger">{t("alerts.blocked")}</Badge> : <Text tone="faint">—</Text>) },
];

const TRAFFIC_COLUMNS: Column<TrafficOrigin>[] = [
  { key: "ip", label: t("col.origin_ip"), kind: "mono", cell: (row) => row.ip },
  { key: "requests", label: t("traffic.col.requests"), kind: "num", cell: (row) => count(row.requests) },
  { key: "refused", label: t("col.blocked"), kind: "num", cell: (row) => count(row.refused) },
  { key: "last", label: t("traffic.col.last_at"), kind: "num", cell: (row) => clock(row.last_at) },
];

function TrafficByOrigin({ round }: { round: number }) {
  const traffic = useResource("/api/rounds/{round_id}/defence/traffic/", { params: { round_id: round } }, { refreshOn: { round, kinds: COUNT_EVENTS } });
  return (
    <PaneSection title={t("traffic.title")} ruled actions={<Button small onClick={traffic.reload}>{t("alerts.refresh")}</Button>}>
      {traffic.loading && !traffic.data ? <Loading>{t("common.loading")}</Loading>
        : traffic.error ? <ErrorNotice error={traffic.error} />
        : <Table columns={TRAFFIC_COLUMNS} rows={[...(traffic.data?.by_origin ?? [])].sort((a, b) => b.requests - a.requests)} rowKey={(row) => row.ip}
          variant="grid" empty={t("traffic.none")} />}
    </PaneSection>
  );
}

function AlertTotal({ round }: { round: number }) {
  const state = useResource("/api/rounds/{round_id}/defence/state/", { params: { round_id: round } }, { refreshOn: { round, kinds: COUNT_EVENTS } });
  if (!state.data) return null;
  return <>{t("alerts.total")} <Text mono tone="heading" strong>{count(state.data.alerts_total)}</Text></>;
}

export function Alerts({ round }: PaneProps) {
  const [draft, setDraft] = useState<AlertFilter>(NO_FILTER);
  const [filter, setFilter] = useState<AlertFilter>(NO_FILTER);
  const feed = useAlertFeed(round, filter);

  return (
    <Pane title={t("pane.alerts")} meta={<AlertTotal round={round} />}>
      <Form onSubmit={() => setFilter({ ...draft })}>
        <Filters>
          <Field label={t("col.engine")}>
            <Select value={draft.engine} options={ENGINE_OPTIONS} onValue={(value) => setDraft({ ...draft, engine: value as EngineFilter })} />
          </Field>
          <Field label={t("alerts.col.rule")}>
            <Input mono value={draft.rule} placeholder="9000001" onValue={(value) => setDraft({ ...draft, rule: value })} />
          </Field>
          <Field label={t("col.origin_ip")}>
            <Input mono value={draft.src} placeholder="5.188.10.10" onValue={(value) => setDraft({ ...draft, src: value })} />
          </Field>
          <Button type="submit">{t("alerts.search")}</Button>
        </Filters>
      </Form>
      <PaneSection>
        {feed.error && <ErrorNotice error={feed.error} />}
        {feed.loading && !feed.alerts.length ? <Loading>{t("common.loading")}</Loading>
          : <Table columns={ALERT_COLUMNS} rows={feed.alerts} rowKey={(row) => row.id} variant="grid" empty={t("alerts.none")} />}
        {feed.more && <span><Button small busy={feed.loading} onClick={feed.loadMore}>{t("alerts.more")}</Button></span>}
      </PaneSection>
      <TrafficByOrigin round={round} />
    </Pane>
  );
}
