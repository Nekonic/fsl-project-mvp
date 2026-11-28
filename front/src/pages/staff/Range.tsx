import { useEffect, useState } from "preact/hooks";
import { api, ApiError, waitUntil, type Schemas } from "../../api/client";
import { useResource, useRowAction } from "../../api/hooks";
import { count } from "../../format";
import type { PageProps } from "../../routes";
import { AppPage } from "../../shell/AppPage";
import { wargameName } from "../../wargame";
import { errorLine, errorText, t, tFor } from "../../strings";
import { Badge, Button, Card, CardHead, ErrorNotice, Loading, PageBody, Progress, Row, Section, Stack, Table, Text, type BadgeTone, type Column, type DotTone, ServerDots, OpRow, RowActions } from "../../ui";

type SlotLine = Schemas["SlotLine"];
type SlotStanding = Schemas["SlotStanding"];
type Server = Schemas["Server"];
type Wargame = Schemas["Wargame"];
type ProbeProgress = Schemas["ProbeProgress"];
type Fabric = Schemas["Fabric"];

const PROBE_READ_EVERY_MS = 3_000;
const HOSTS = ["kali", "waf", "infra", "target"];

type SlotState = "allocated" | "idle" | "running" | "failed";

const SLOT_TONE: Record<SlotState, BadgeTone> = { allocated: "info", idle: "ok", running: "warn", failed: "danger" };
const PROBE_TONE: Record<string, BadgeTone> = { recording: "warn", done: "ok", failed: "danger" };
const SERVER_TONE: Record<string, DotTone> = { ACTIVE: "ok", BUILD: "warn", REBUILD: "warn", ERROR: "danger" };

function slotStateOf(slot: SlotLine): SlotState {
  if (slot.allocation !== null) return "allocated";
  if (slot.refill.state === "running" || slot.refill.state === "failed") return slot.refill.state;
  return "idle";
}

function WargameName({ id, wargames }: { id: string; wargames: Map<string, Wargame> }) {
  const found = wargames.get(id);
  return (
    <Row>
      {found && <Text strong tone="heading">{wargameName(found.id)}</Text>}
      <Text mono small tone="muted">{id}</Text>
    </Row>
  );
}

function Servers({ standing }: { standing: SlotStanding | undefined }) {
  if (!standing) return <Text tone="faint">—</Text>;
  const byHost = new Map(standing.servers.map((server) => [server.host, server]));
  const hosts = [...HOSTS.filter((host) => byHost.has(host)), ...standing.servers.map((server) => server.host).filter((host) => !HOSTS.includes(host))];
  const shown: Array<[string, Server | undefined]> = (hosts.length ? hosts : HOSTS).map((host) => [host, byHost.get(host)]);
  return (
    <ServerDots servers={shown.map(([host, server]) => ({
      host, title: server ? `${server.server} ${server.status}` : undefined, tone: server ? SERVER_TONE[server.status] ?? "off" : "off",
    }))} />
  );
}

function SlotProblems({ standing, slot }: { standing: SlotStanding | undefined; slot: SlotLine }) {
  const lines = [...(standing?.blocked ?? []), ...(standing?.failures ?? []), ...(slot.refill.state === "failed" && slot.refill.reason ? [slot.refill.reason] : [])];
  if (!lines.length) return null;
  return (
    <Stack gap="sm">
      {lines.map((line, index) => <Text key={index} mono tiny tone="danger">{line}</Text>)}
    </Stack>
  );
}

function SlotsCard({ slots, pool, wargames, probeAllocations }: {
  slots: SlotLine[];
  pool: Map<number, SlotStanding>;
  wargames: Map<string, Wargame>;
  probeAllocations: Set<number>;
}) {
  const columns: Column<SlotLine>[] = [
    { key: "slot", label: t("lobby.slot"), kind: "key", cell: (slot) => t("slot.stack", { slot: slot.slot }) },
    { key: "wargame", label: t("col.wargame"), kind: "nowrap", cell: (slot) => <WargameName id={slot.wargame} wargames={wargames} /> },
    {
      key: "state", label: t("col.state"),
      cell: (slot) => {
        const state = slotStateOf(slot);
        return (
          <Stack gap="sm">
            <Row><Badge tone={SLOT_TONE[state]}>{tFor("range.slot_state", state)}</Badge></Row>
            <SlotProblems standing={pool.get(slot.slot)} slot={slot} />
          </Stack>
        );
      },
    },
    {
      key: "allocation", label: t("range.col.allocation"), kind: "nowrap",
      cell: (slot) => slot.allocation === null
        ? <Text tone="faint">—</Text>
        : t(probeAllocations.has(slot.allocation) ? "range.allocation_probe" : "allocation.name", { allocation: slot.allocation }),
    },
    { key: "servers", label: t("range.col.servers"), cell: (slot) => <Servers standing={pool.get(slot.slot)} /> },
  ];
  return (
    <Card>
      <CardHead title={t("range.slots")} meta={<Badge>{count(slots.length)}</Badge>} />
      <Table variant="grid" columns={columns} rows={slots} rowKey={(slot) => slot.slot} empty={<Text tone="muted">{t("range.slots_none")}</Text>} />
    </Card>
  );
}

interface Operation {
  id: "fill" | "empty" | "leftovers" | "fabric_build" | "fabric_remove";
  tone: "primary" | "danger" | "ghost";
  confirm?: boolean;
  send: () => Promise<unknown>;
}

function OperationsCard({ notCloud, onRange, onPool }: { notCloud: ApiError | undefined; onRange: (slots: SlotLine[]) => void; onPool: () => void }) {
  const [busy, setBusy] = useState<Operation["id"] | undefined>(undefined);
  const [failed, setFailed] = useState<ApiError | undefined>(undefined);
  const [done, setDone] = useState<Operation["id"] | undefined>(undefined);
  const [fabric, setFabric] = useState<Fabric | undefined>(undefined);
  const groups: Array<{ title: "range.pool" | "range.fabric"; operations: Operation[] }> = [
    {
      title: "range.pool",
      operations: [
        { id: "fill", tone: "primary", send: async () => onRange((await api.post("/api/staff/range/pool/")).slots) },
        { id: "empty", tone: "danger", confirm: true, send: () => api.delete("/api/staff/range/pool/") },
        { id: "leftovers", tone: "ghost", confirm: true, send: () => api.delete("/api/staff/range/leftovers/") },
      ],
    },
    {
      title: "range.fabric",
      operations: [
        { id: "fabric_build", tone: "primary", send: async () => setFabric(await api.post("/api/staff/range/fabric/")) },
        { id: "fabric_remove", tone: "danger", confirm: true, send: async () => { await api.delete("/api/staff/range/fabric/"); setFabric(undefined); } },
      ],
    },
  ];
  const run = async (operation: Operation) => {
    if (operation.confirm && !window.confirm(tFor("range.confirm", operation.id))) return;
    setBusy(operation.id);
    setFailed(undefined);
    setDone(undefined);
    try {
      await operation.send();
      setDone(operation.id);
      onPool();
    } catch (error) {
      setFailed(error instanceof ApiError ? error : new ApiError(0, [{ path: "", code: "network" }]));
    } finally {
      setBusy(undefined);
    }
  };
  return (
    <Card>
      {groups.map((group) => (
        <OpRow key={group.title} title={t(group.title)} actions={group.operations.map((operation) => (
          <Button key={operation.id} small tone={operation.tone} busy={busy === operation.id} disabled={busy !== undefined && busy !== operation.id}
            onClick={() => void run(operation)}>
            {tFor("range.op", operation.id)}
          </Button>
        ))} />
      ))}
      {fabric && (
        <OpRow>
          <Badge tone={fabric.clean ? "ok" : "warn"}>{t(fabric.clean ? "range.fabric_clean" : "range.fabric_dirty")}</Badge>
          <Text mono small tone="muted">{fabric.present.join(" · ")}</Text>
        </OpRow>
      )}
      {notCloud && !failed && <OpRow><Text small tone="danger">{errorText(notCloud)}</Text></OpRow>}
      {(failed || done) && (
        <OpRow>
          {failed ? <Text small tone="danger">{errorText(failed)}</Text> : done && <Text small tone="ok">{tFor("range.op_done", done)}</Text>}
        </OpRow>
      )}
    </Card>
  );
}

function useProbeProgress(allocation: number | undefined): ProbeProgress | undefined {
  const [progress, setProgress] = useState<ProbeProgress | undefined>(undefined);
  useEffect(() => {
    if (allocation === undefined) return undefined;
    const abort = new AbortController();
    void waitUntil(
      () => api.get("/api/staff/probes/{allocation_id}/", { params: { allocation_id: allocation }, signal: abort.signal }),
      (shown) => shown.state !== "recording",
      { every: PROBE_READ_EVERY_MS, signal: abort.signal, onRead: setProgress },
    ).catch(() => undefined);
    return () => abort.abort();
  }, [allocation]);
  return progress;
}

function ProbeState({ progress }: { progress: ProbeProgress | undefined }) {
  if (!progress) return <Text tone="faint">—</Text>;
  return (
    <Row>
      <Badge tone={PROBE_TONE[progress.state] ?? "neutral"}>{tFor("range.probe_state", progress.state)}</Badge>
      <Text small tone="muted">{t("allocation.name", { allocation: progress.allocation })}</Text>
    </Row>
  );
}

function ProbeCases({ progress }: { progress: ProbeProgress | undefined }) {
  if (!progress) return <Text tone="faint">—</Text>;
  const finished = progress.done.length + progress.failed.length;
  return (
    <Stack gap="sm">
      <Text mono>{`${count(finished)}/${count(progress.total)}`}</Text>
      {progress.state === "recording" && <Progress value={finished} max={progress.total} label={t("range.col.cases")} />}
      {progress.failed.map((failure) => (
        <Text key={failure.case} mono tiny tone="danger">{`${failure.case} ${errorLine({ path: "", code: failure.code })}`}</Text>
      ))}
    </Stack>
  );
}

function RecordingCard({ wargames, allocations, onAllocation }: { wargames: Wargame[]; allocations: Map<string, number>; onAllocation: (wargame: string, allocation: number) => void }) {
  const record = useRowAction<string, "post", "/api/staff/wargames/{wargame_id}/probes/record/">("post", "/api/staff/wargames/{wargame_id}/probes/record/");
  return (
    <Card>
      <CardHead title={t("range.recording")} />
      <Table variant="grid" rows={wargames} rowKey={(wargame) => wargame.id} empty={<Text tone="muted">{t("range.wargames_none")}</Text>}
        columns={[
          { key: "wargame", label: t("col.wargame"), kind: "nowrap", cell: (wargame) => <WargameName id={wargame.id} wargames={new Map([[wargame.id, wargame]])} /> },
          { key: "state", label: t("col.state"), kind: "nowrap", cell: (wargame) => <ProbeRow allocation={allocations.get(wargame.id)} part="state" /> },
          { key: "cases", label: t("range.col.cases"), cell: (wargame) => <ProbeRow allocation={allocations.get(wargame.id)} part="cases" /> },
          {
            key: "record", label: "", kind: "end",
            cell: (wargame) => (
              <RowActions error={record.errorFor(wargame.id) && errorText(record.errorFor(wargame.id))}>
                <Button small busy={record.busyFor(wargame.id)} onClick={() => void record.run(wargame.id, { params: { wargame_id: wargame.id } })
                  .then((said) => said.data && onAllocation(wargame.id, said.data.allocation))}>
                  {t("range.record")}
                </Button>
              </RowActions>
            ),
          },
        ]} />
    </Card>
  );
}

function ProbeRow({ allocation, part }: { allocation: number | undefined; part: "state" | "cases" }) {
  const progress = useProbeProgress(allocation);
  return part === "state" ? <ProbeState progress={progress} /> : <ProbeCases progress={progress} />;
}

export function Range(_props: PageProps) {
  const range = useResource("/api/staff/range/", {});
  const pool = useResource("/api/staff/range/pool/", {});
  const wargames = useResource("/api/staff/wargames/", {});
  const [probeAllocations, setProbeAllocations] = useState<Map<string, number>>(new Map());
  const byWargame = new Map((wargames.data ?? []).map((wargame) => [wargame.id, wargame]));
  const bySlot = new Map((pool.data?.slots ?? []).map((standing) => [standing.slot, standing]));
  const poolRefused = pool.error && !pool.error.has("range_not_cloud") ? pool.error : undefined;
  return (
    <AppPage title={t("page.staff.range")} crumbs={[{ label: t("page.staff.range") }]}>
      <PageBody>
        <Section title={t("page.staff.range")} large>
          <Stack>
            {range.error ? <ErrorNotice error={range.error} /> : !range.data ? <Loading>{t("common.loading")}</Loading> : (
              <SlotsCard slots={range.data.slots} pool={bySlot} wargames={byWargame} probeAllocations={new Set(probeAllocations.values())} />
            )}
            {poolRefused && <ErrorNotice error={poolRefused} />}
            <OperationsCard notCloud={pool.error?.has("range_not_cloud") ? pool.error : undefined} onRange={(slots) => range.setData({ slots })} onPool={() => { range.reload(); pool.reload(); }} />
            {wargames.error ? <ErrorNotice error={wargames.error} /> : !wargames.data ? <Loading>{t("common.loading")}</Loading> : (
              <RecordingCard wargames={wargames.data} allocations={probeAllocations}
                onAllocation={(wargame, allocation) => setProbeAllocations((was) => new Map(was).set(wargame, allocation))} />
            )}
          </Stack>
        </Section>
      </PageBody>
    </AppPage>
  );
}
