import { useEffect, useState } from "preact/hooks";
import { holdLease } from "../api/follow";
import { useAction, useResource } from "../api/hooks";
import { to } from "../links";
import type { Side } from "../panes/types";
import { t, tFor } from "../strings";
import { Badge, Banner, Button, ErrorNotice, RoundBar } from "../ui";
import { clock } from "../format";

const FORFEIT_PATH = {
  attack: "/api/rounds/{round_id}/attack/forfeit/",
  defence: "/api/rounds/{round_id}/defence/forfeit/",
} as const;

const ROUND_EVENTS = ["round.started", "round.ended", "seat.joined"];

export function useRound(round: number) {
  const shown = useResource("/api/rounds/{round_id}/", { params: { round_id: round } }, { refreshOn: { round, kinds: ROUND_EVENTS } });
  const problemId = shown.data?.problem;
  const problem = useResource("/api/problems/{problem_id}/", problemId ? { params: { problem_id: problemId } } : null);
  useEffect(() => holdLease(round, shown.data?.lease), [round, shown.data?.lease]);
  return { round: shown.data, problem: problem.data, error: shown.error, reload: shown.reload };
}

export interface RoundHeaderProps {
  round: number;
  side: Side;
}

export function RoundHeader({ round, side }: RoundHeaderProps) {
  const { round: shown, problem, error, reload } = useRound(round);
  const forfeit = useAction("post", FORFEIT_PATH[side]);
  const [asking, setAsking] = useState(false);
  const ended = shown?.phase === "ended";
  const what = [t("round.name", { round }), problem?.title, shown ? tFor("matchup", shown.matchup) : undefined].filter(Boolean).join(" · ");

  const giveUp = async () => {
    if (!asking) {
      setAsking(true);
      return;
    }
    setAsking(false);
    if (await forfeit.run({ params: { round_id: round } })) reload();
  };

  return (
    <>
      <RoundBar
        side={side}
        sideLabel={t(side === "attack" ? "side.attack.team" : "side.defence.team")}
        what={what}
        badges={shown && <Badge tone={shown.phase === "running" ? "ok" : "muted"}>{tFor("phase", shown.phase)}</Badge>}
        facts={shown?.ends_at && !ended ? [{ label: t("round.ends_at"), value: clock(shown.ends_at), mono: true }] : []}
        actions={!ended && shown?.phase === "running" && (
          <Button tone="danger" small busy={forfeit.busy} onClick={() => void giveUp()}>
            {asking ? t("round.forfeit_confirm") : t("round.forfeit")}
          </Button>
        )}
      />
      {forfeit.error && <ErrorNotice error={forfeit.error} />}
      {error && <ErrorNotice error={error} />}
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
