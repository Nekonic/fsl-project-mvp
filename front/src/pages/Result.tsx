import { useResource } from "../api/hooks";
import { clock } from "../format";
import { to } from "../links";
import { Score } from "../panes/Score";
import type { Side } from "../panes/types";
import { usePlace } from "../router";
import type { PageProps } from "../routes";
import { AppPage } from "../shell/AppPage";
import { t, tFor } from "../strings";
import { Button, ErrorNotice, Hero, PageBody } from "../ui";
import { wargameName } from "./wargameText";

const ROUND_EVENTS = ["round.ended"];

function sideFrom(value: string | null): Side {
  return value === "attack" ? "attack" : "defence";
}

function useResultRound(round: number) {
  const shown = useResource("/api/rounds/{round_id}/", { params: { round_id: round } }, { refreshOn: { round, kinds: ROUND_EVENTS } });
  const problemId = shown.data?.problem;
  const problem = useResource("/api/problems/{problem_id}/", problemId ? { params: { problem_id: problemId } } : null);
  const allocationId = shown.data?.operated ? shown.data.allocation : undefined;
  const allocation = useResource("/api/allocations/{allocation_id}/", allocationId ? { params: { allocation_id: allocationId } } : null);
  return { round: shown.data, problem: problem.data, allocation: allocation.data, error: shown.error };
}

export function Result({ params }: PageProps) {
  const round = Number(params.round);
  const place = usePlace();
  const side = sideFrom(place.search.get("side"));
  const { round: shown, problem, allocation, error } = useResultRound(round);
  const ended = shown?.phase === "ended";
  const span = shown?.started && shown.ended ? `${clock(shown.started)}–${clock(shown.ended)}` : "";
  const title = problem?.title ?? (shown && shown.problem === null ? wargameName(shown.wargame) : undefined);
  const lead = [title, span, shown?.end_reason ? tFor("end_reason", shown.end_reason) : ""].filter(Boolean).join(" · ");
  const nextRound = allocation && !allocation.closed ? <Button tone="primary" href={to.allocation(allocation.allocation)}>{t("result.next_round")}</Button> : null;

  return (
    <AppPage
      title={t("page.result")}
      crumbs={[...(title ? [{ label: title }] : []), { label: t("result.crumb") }]}
    >
      {ended && (
        <Hero
          icon="shield"
          title={t("round.name", { round })}
          lead={lead ? [lead] : []}
          actions={<>
            {nextRound}
            <Button tone="ghost" href={to.debrief(round)}>{t("result.debrief")}</Button>
            <Button tone="ghost" href={to.home()}>{t("common.to_home")}</Button>
          </>}
        />
      )}
      <PageBody>
        {error && <ErrorNotice error={error} />}
        <Score round={round} side={side} placement="main" />
      </PageBody>
    </AppPage>
  );
}
