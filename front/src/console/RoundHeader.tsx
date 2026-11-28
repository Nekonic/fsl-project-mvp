import { useEffect } from "preact/hooks";
import { holdAllocation } from "../api/follow";
import { useAction, useResource } from "../api/hooks";
import { to } from "../links";
import type { Side } from "../panes/types";
import type { Schemas } from "../api/client";
import { t, tFor } from "../strings";
import { Badge, Banner, Button, ConfirmButton, ErrorNotice, RoundBar } from "../ui";
import { botRunText } from "../botRun";
import { clock } from "../format";
import { wargameName } from "../pages/wargameText";

const FORFEIT_PATH = {
  attack: "/api/rounds/{round_id}/attack/forfeit/",
  defence: "/api/rounds/{round_id}/defence/forfeit/",
} as const;

const ROUND_EVENTS = ["round.started", "round.ended", "player.joined"];
const BOT_RUN_UNSETTLED = new Set(["queued", "running"]);
export const BOT_RUN_READ_EVERY_MS = 15_000;
export const NOT_STARTED_READ_EVERY_MS = 5_000;
const NOT_STARTED = new Set(["created", "starting"]);

export function useRound(round: number) {
  const shown = useResource("/api/rounds/{round_id}/", { params: { round_id: round } }, { refreshOn: { round, kinds: ROUND_EVENTS } });
  const problemId = shown.data?.problem;
  const problem = useResource("/api/problems/{problem_id}/", problemId ? { params: { problem_id: problemId } } : null);
  useEffect(() => holdAllocation(round, shown.data?.allocation), [round, shown.data?.allocation]);
  const botUnsettled = Boolean(shown.data?.players.some((player) => player.bot_run !== null && BOT_RUN_UNSETTLED.has(player.bot_run)));
  const reloadRound = shown.reload;
  useEffect(() => {
    if (!botUnsettled) return undefined;
    const timer = setInterval(reloadRound, BOT_RUN_READ_EVERY_MS);
    return () => clearInterval(timer);
  }, [botUnsettled, reloadRound]);
  const notStarted = Boolean(shown.data && NOT_STARTED.has(shown.data.phase));
  useEffect(() => {
    if (!notStarted) return undefined;
    const timer = setInterval(reloadRound, NOT_STARTED_READ_EVERY_MS);
    return () => clearInterval(timer);
  }, [notStarted, reloadRound]);
  return { round: shown.data, problem: problem.data, error: shown.error, reload: shown.reload };
}

type PlayerLine = Schemas["PlayerLine"];

const SIDE_ORDER: Side[] = ["attack", "defence"];

function playerWho(player: PlayerLine): string {
  if (player.client === "bot") {
    const who = t("round.player_bot", { name: player.step ? tFor("bot_step", player.step) : player.bot_name });
    return player.bot_run ? `${who} · ${botRunText(player)}` : who;
  }
  return player.username ?? t("round.player_open");
}

export function playerFacts(players: PlayerLine[]) {
  return SIDE_ORDER.flatMap((side) => players.filter((player) => player.side === side))
    .map((player) => ({ label: t(`side.${player.side}`), value: playerWho(player), mono: player.client !== "bot" && player.username !== null }));
}

export interface RoundHeaderProps {
  round: number;
  side: Side;
}

export function RoundHeader({ round, side }: RoundHeaderProps) {
  const { round: shown, problem, error, reload } = useRound(round);
  const forfeit = useAction("post", FORFEIT_PATH[side]);
  const ended = shown?.phase === "ended";
  const title = problem?.title ?? (shown && shown.problem === null ? wargameName(shown.wargame) : undefined);
  const what = [t("round.name", { round }), title, shown ? tFor("matchup", shown.matchup) : undefined].filter(Boolean).join(" · ");

  const giveUp = async () => {
    if (await forfeit.run({ params: { round_id: round } })) reload();
  };

  return (
    <>
      <RoundBar
        side={side}
        sideLabel={t(side === "attack" ? "side.attack.team" : "side.defence.team")}
        what={what}
        badges={shown && <Badge tone={shown.phase === "running" ? "ok" : "muted"}>{tFor("phase", shown.phase)}</Badge>}
        facts={[
          ...(shown ? playerFacts(shown.players) : []),
          ...(shown?.ends_at && !ended ? [{ label: t("round.ends_at"), value: clock(shown.ends_at), mono: true }] : []),
        ]}
        actions={!ended && shown?.phase === "running" && (
          <ConfirmButton tone="danger" small busy={forfeit.busy} confirm={t("round.forfeit_confirm")} onConfirm={() => void giveUp()}>
            {t("round.forfeit")}
          </ConfirmButton>
        )}
      />
      {forfeit.error && <ErrorNotice error={forfeit.error} />}
      {error && <ErrorNotice error={error} />}
      {shown?.phase === "created" && <Banner title={t("round.created_banner")} detail={t("round.created_detail")} />}
      {shown?.phase === "starting" && <Banner title={t("round.starting_banner")} detail={t("round.starting_detail")} />}
      {ended && shown && (
        <Banner
          title={t("round.ended_banner")}
          detail={[shown.ended ? clock(shown.ended) : "", tFor("end_reason", shown.end_reason)].filter(Boolean).join(" · ")}
          action={<Button tone="primary" small href={to.result(round, side)}>{t("round.see_result")}</Button>}
        />
      )}
    </>
  );
}
