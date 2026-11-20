import { useAction, useResource } from "../api/hooks";
import type { Hp as HpBlock, Schemas } from "../api/client";
import { clock, count } from "../format";
import { t } from "../strings";
import { AsideCard, AsideHead, Banner, Button, ErrorNotice, KeyValue, Loading, Pane, Progress, Stack, Text } from "../ui";
import type { PaneProps } from "./types";

export const HP_EVENTS = ["origin.charged", "origin.spent", "origin.switched", "origins.spent", "action.sent", "round.started", "round.ended"];

export type AttackState = Schemas["AttackState"];
type OriginLine = Schemas["OriginLine"];

export function useAttackState(round: number) {
  return useResource("/api/rounds/{round_id}/attack/state/", { params: { round_id: round } }, { refreshOn: { round, kinds: HP_EVENTS } });
}

export function attackWritesOpen(state: AttackState | undefined): boolean {
  return state?.phase === "running" && state.hp.origins_left > 0;
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

function originName(hp: HpBlock): string {
  return hp.origin ? [hp.origin.ip, regionName(hp.origin.label)].filter(Boolean).join(" · ") : t("common.none");
}

function ruleLine(hp: HpBlock): string {
  return t("hp.rule", { per_request: hp.rule.per_request, refused_x: hp.rule.refused_x, burst_per_s: hp.rule.burst_per_s, burst_x: hp.rule.burst_x });
}

function spentOrigins(state: AttackState): Array<{ ip: string; at: string }> {
  const fromLines = state.origins.filter((origin: OriginLine) => origin.spent_at).map((origin) => ({ ip: origin.ip, at: clock(origin.spent_at) }));
  const named = new Set(fromLines.map((origin) => origin.ip));
  return [...fromLines, ...state.hp.spent.filter((ip) => !named.has(ip)).map((ip) => ({ ip, at: "" }))];
}

function SpentList({ state }: { state: AttackState }) {
  const spent = spentOrigins(state);
  if (!spent.length) return <Text tone="muted">{t("common.none")}</Text>;
  return (
    <Stack gap="sm">
      {spent.map((origin) => <Text key={origin.ip} mono>{[origin.ip, origin.at].filter(Boolean).join(" · ")}</Text>)}
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
      <KeyValue items={[
        [t("hp.origins_left"), <Text strong>{count(state.hp.origins_left)}</Text>],
        [t("hp.origins_spent"), <SpentList state={state} />],
      ]} />
      <Text small tone="muted">{ruleLine(state.hp)}</Text>
      {attackWritesOpen(state) && (
        <span>
          <Button small busy={next.busy} onClick={() => void giveUpOrigin()}>{t("hp.next_origin")}</Button>
        </span>
      )}
      {next.error && <ErrorNotice error={next.error} />}
    </AsideCard>
  );
}

function hpValue(hp: HpBlock): string {
  return `${count(Math.max(0, hp.left))} / ${count(hp.budget)}`;
}

export function Hp({ round, placement }: PaneProps) {
  const state = useAttackState(round);
  const shown = state.data;

  if (!shown) {
    const waiting = state.error ? <ErrorNotice error={state.error} /> : <Loading>{t("common.loading")}</Loading>;
    return placement === "main" ? <Pane title={t("pane.hp")}>{waiting}</Pane> : <AsideCard title={t("pane.hp")}>{waiting}</AsideCard>;
  }

  const hp = shown.hp;
  const meter = <Progress value={Math.max(0, hp.left)} max={hp.budget} label={t("pane.hp")} />;
  const origins = <OriginsCard state={shown} round={round} onChanged={state.reload} />;

  if (placement === "aside-lead") {
    return (
      <>
        <AsideHead title={t("pane.hp")} value={<Text mono>{hpValue(hp)}</Text>} sub={[t("hp.current_origin"), <Text mono>{originName(hp)}</Text>]} progress={meter} />
        {origins}
      </>
    );
  }
  if (placement === "aside") {
    return (
      <>
        <AsideCard title={t("pane.hp")} meta={<Text mono>{hpValue(hp)}</Text>}>
          <KeyValue items={[[t("hp.current_origin"), <Text mono>{originName(hp)}</Text>]]} />
          {meter}
        </AsideCard>
        {origins}
      </>
    );
  }
  return (
    <Pane title={t("pane.hp")} meta={<Text mono>{hpValue(hp)}</Text>}>
      <KeyValue items={[[t("hp.current_origin"), <Text mono>{originName(hp)}</Text>]]} />
      {meter}
      {origins}
    </Pane>
  );
}

export function OriginsSpentBanner({ round }: { round: number }) {
  const state = useAttackState(round);
  if (!state.data || state.data.hp.origins_left > 0 || state.data.phase === "ended") return null;
  return <Banner tone="danger" title={t("error.origins_spent")} />;
}
