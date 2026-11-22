import { useState } from "preact/hooks";
import { useAction, useEvents, useResource } from "../api/hooks";
import type { Schemas } from "../api/client";
import { clock, count } from "../format";
import { t, tFor } from "../strings";
import { AsideCard, AsideHead, Banner, Button, ErrorNotice, KeyValue, Loading, Pane, Stack, Text } from "../ui";
import type { PaneProps } from "./types";

export const ORIGIN_EVENTS = ["origin.spent", "origin.switched", "origins.spent", "action.sent", "round.started", "round.ended"];
const BELOW_FLOOR = "limit.below_floor";
const SHARED_KEY = "limit.shared_key";

export type AttackState = Schemas["AttackState"];
type Remaining = Schemas["Remaining"];
type OriginLine = Schemas["OriginLine"];

export function useAttackState(round: number) {
  return useResource("/api/rounds/{round_id}/attack/state/", { params: { round_id: round } }, { refreshOn: { round, kinds: ORIGIN_EVENTS } });
}

export function attackWritesOpen(state: AttackState | undefined): boolean {
  return state?.phase === "running" && state.remaining.left > 0;
}

const REGION_NAMES = new Intl.DisplayNames(["ko"], { type: "region" });

function regionName(label: string): string {
  if (!/^[A-Z]{2}$/.test(label)) return label;
  try {
    return REGION_NAMES.of(label) ?? label;
  } catch {
    return label;
  }
}

function originName(remaining: Remaining): string {
  return remaining.origin ? [remaining.origin.ip, regionName(remaining.origin.label)].filter(Boolean).join(" · ") : t("common.none");
}

function spentLine(origin: OriginLine): string {
  const by = origin.spent_by ? tFor("origins.spent_by", origin.spent_by) : "";
  return [origin.ip, clock(origin.spent_at), by].filter(Boolean).join(" · ");
}

function SpentList({ state }: { state: AttackState }) {
  const spent = state.origins.filter((origin) => origin.spent_at);
  if (!spent.length) return <Text tone="muted">{t("common.none")}</Text>;
  return (
    <Stack gap="sm">
      {spent.map((origin) => <Text key={origin.ip} mono>{spentLine(origin)}</Text>)}
    </Stack>
  );
}

function OriginsCard({ state, round, onChanged }: { state: AttackState; round: number; onChanged: () => void }) {
  const next = useAction("post", "/api/rounds/{round_id}/attack/origins/next/");
  const giveUpOrigin = async () => {
    if (await next.run({ params: { round_id: round } })) onChanged();
  };
  return (
    <AsideCard>
      <KeyValue items={[[t("origins.spent"), <SpentList state={state} />]]} />
      <Text small tone="muted">{t("origins.rule")}</Text>
      {attackWritesOpen(state) && (
        <span>
          <Button small busy={next.busy} onClick={() => void giveUpOrigin()}>{t("origins.next")}</Button>
        </span>
      )}
      {next.error && <ErrorNotice error={next.error} />}
    </AsideCard>
  );
}

function leftValue(remaining: Remaining): string {
  return `${count(remaining.left)} / ${count(remaining.total)}`;
}

export function Origins({ round, placement }: PaneProps) {
  const state = useAttackState(round);
  const shown = state.data;

  if (!shown) {
    const waiting = state.error ? <ErrorNotice error={state.error} /> : <Loading>{t("common.loading")}</Loading>;
    return placement === "main" ? <Pane title={t("pane.origins")}>{waiting}</Pane> : <AsideCard title={t("pane.origins")}>{waiting}</AsideCard>;
  }

  const remaining = shown.remaining;
  const current = <KeyValue items={[[t("origins.current"), <Text mono>{originName(remaining)}</Text>], [t("origins.left"), <Text mono>{leftValue(remaining)}</Text>]]} />;
  const origins = <OriginsCard state={shown} round={round} onChanged={state.reload} />;

  if (placement === "aside-lead") {
    return (
      <>
        <AsideHead title={t("origins.left")} value={<Text mono>{leftValue(remaining)}</Text>} sub={[t("origins.current"), <Text mono>{originName(remaining)}</Text>]} />
        {origins}
      </>
    );
  }
  if (placement === "aside") {
    return (
      <>
        <AsideCard title={t("pane.origins")} meta={<Text mono>{leftValue(remaining)}</Text>}>{current}</AsideCard>
        {origins}
      </>
    );
  }
  return (
    <Pane title={t("pane.origins")} meta={<Text mono>{leftValue(remaining)}</Text>}>
      {current}
      {origins}
    </Pane>
  );
}

export function OriginsSpentBanner({ round }: { round: number }) {
  const state = useAttackState(round);
  if (!state.data || state.data.remaining.left > 0 || state.data.phase === "ended") return null;
  return <Banner tone="danger" title={t("error.origins_spent")} />;
}

export function LimitWarningBanner({ round }: { round: number }) {
  const [warned, setWarned] = useState<{ kind: string; zone: string; rate: number; floor: number } | null>(null);
  useEvents(round, [BELOW_FLOOR, SHARED_KEY], (events) => {
    const last = events[events.length - 1];
    if (!last?.body) return;
    const body = last.body;
    setWarned({ kind: last.kind, zone: String(body.zone ?? ""), rate: Number(body.rate_rpm ?? 0), floor: Number(body.floor_rpm ?? 0) });
  }, true);
  if (!warned) return null;
  if (warned.kind === SHARED_KEY) return <Banner title={t("origins.shared_key")} detail={t("origins.shared_key.detail", warned)} />;
  return <Banner title={t("origins.below_floor")} detail={t("origins.below_floor.detail", warned)} />;
}
