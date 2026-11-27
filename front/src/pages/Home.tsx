import { useMemo, useState } from "preact/hooks";
import { ApiError, openAllocation, type Schemas } from "../api/client";
import { useAction, useResource } from "../api/hooks";
import { to } from "../links";
import type { PageProps } from "../routes";
import { navigate } from "../router";
import { AppPage } from "../shell/AppPage";
import { t, tFor } from "../strings";
import {
  Badge, Badges, Button, Card, ErrorNotice, Group, GroupHead, Hero, ListRow, Loading, PageBody, Section, Stack, Table, TargetHead, Text,
  Tile, Tiles, phaseTone, roundTileLook, type Column,
} from "../ui";
import { botRoundProblems, roundTitle } from "./roundText";
import { wargameHost, wargameLead, wargameName } from "./wargameText";

type Problem = Schemas["LearnerProblemSummary"];
type Wargame = Schemas["LearnerWargame"];
type RoundLine = Schemas["RoundLine"];
type Side = Schemas["PlayerSideEnum"];

const sideLabel = (side: string) => tFor("side", side);

interface Catalogue {
  wargames: Array<{ wargame: string; rounds: Problem[] }>;
}

function catalogueOf(wargames: Wargame[] | undefined, problems: Problem[] | undefined): Catalogue {
  const rounds = botRoundProblems(problems ?? []);
  const order = (wargames ?? []).map((wargame) => wargame.id);
  for (const problem of rounds) if (!order.includes(problem.wargame)) order.push(problem.wargame);
  return {
    wargames: order.map((wargame) => ({ wargame, rounds: rounds.filter((problem) => problem.wargame === wargame) })),
  };
}

function humanSides(line: RoundLine): Side[] {
  return line.players.filter((player) => player.client === "human" && player.username !== null).map((player) => player.side);
}

function openSides(line: RoundLine): Side[] {
  return line.players.filter((player) => player.client === "human" && player.username === null).map((player) => player.side);
}

function MyPlayers({ rounds }: { rounds: RoundLine[] }) {
  if (!rounds.length) return <Card pad="md"><Text tone="muted">{t("home.my_players_none")}</Text></Card>;
  return (
    <Card list>
      {rounds.map((line) => {
        const sides = humanSides(line);
        const first = sides[0] ?? "defence";
        return (
          <ListRow key={`r${line.round}`} id={t("round.name", { round: line.round })} href={to.player(line.round, first)}
            main={<><Text tone="heading">{roundTitle(line)}</Text><Text tone="muted" small>{tFor("matchup", line.matchup)}</Text></>}
            side={<>
              <Badge tone={phaseTone(line.phase)}>{tFor("phase", line.phase)}</Badge>
              {sides.map((side) => (
                <Button key={side} tone="ghost" small href={to.player(line.round, side)}>{t(side === "attack" ? "page.attack" : "page.defence")}</Button>
              ))}
            </>} />
        );
      })}
    </Card>
  );
}

function Joinable({ rounds }: { rounds: RoundLine[] }) {
  const join = useAction("post", "/api/rounds/{round_id}/players/{side}/join/");
  const take = async (round: number, side: Side) => {
    const joined = await join.run({ params: { round_id: String(round), side } });
    if (joined) navigate(to.player(round, joined.side));
  };
  return (
    <Stack gap="sm">
      <ErrorNotice error={join.error} />
      <Card list>
        {rounds.map((line) => (
          <ListRow key={line.round} id={t("round.name", { round: line.round })}
            main={<><Text tone="heading">{roundTitle(line)}</Text><Text tone="muted" small>{tFor("matchup", line.matchup)}</Text></>}
            side={openSides(line).map((side) => (
              <Badges key={side}>
                <Badge tone="warn">{t("home.player_open", { side: sideLabel(side) })}</Badge>
                <Button tone="primary" small busy={join.busy} onClick={() => void take(line.round, side)}>{t("player.join")}</Button>
              </Badges>
            ))} />
        ))}
      </Card>
    </Stack>
  );
}

function ProblemTiles({ catalogue }: { catalogue: Catalogue }) {
  const [opening, setOpening] = useState<string | null>(null);
  const [openError, setOpenError] = useState<ApiError | undefined>(undefined);
  const openRange = async (wargame: string) => {
    setOpening(wargame);
    setOpenError(undefined);
    try {
      const allocation = await openAllocation(wargame);
      navigate(to.allocation(allocation.allocation));
    } catch (failed) {
      setOpenError(failed instanceof ApiError ? failed : new ApiError(0, [{ path: "", code: "network" }]));
    } finally {
      setOpening(null);
    }
  };

  return (
    <Stack gap="lg">
      <ErrorNotice error={openError} />
      {catalogue.wargames
        .map((group) => (
          <Group key={group.wargame}>
            <TargetHead eyebrow={t("home.target")} title={wargameName(group.wargame)} text={wargameLead(group.wargame) || undefined}
              tag={wargameHost(group.wargame) ? <Badge mono>{wargameHost(group.wargame)}</Badge> : undefined} />
            <Group>
              <GroupHead title={t("kind.round")} sub={t("home.rounds_count", { n: group.rounds.length })} />
              <Tiles>
                <Tile icon={roundTileLook.icon} tone={roundTileLook.tone} label={t("matchup.pvp")} title={t("home.pvp_title")} text={t("home.pvp_lead")}
                  action={<Button tone="primary" small busy={opening === group.wargame} disabled={opening !== null && opening !== group.wargame}
                    onClick={() => void openRange(group.wargame)}>{t("home.open_range")}</Button>} />
                {group.rounds.map((problem) => (
                  <Tile key={problem.id} icon={roundTileLook.icon} tone={roundTileLook.tone} label={t("kind.round")} title={problem.title} text={problem.summary}
                    foot={<Badge>{sideLabel(problem.side)}</Badge>}
                    action={<Button tone="primary" small busy={opening === problem.wargame} disabled={opening !== null && opening !== problem.wargame}
                      onClick={() => void openRange(problem.wargame)}>{t("home.open_range")}</Button>} />
                ))}
              </Tiles>
            </Group>
          </Group>
        ))}
    </Stack>
  );
}

interface PastLine {
  key: string;
  name: string;
  problem: string;
  href: string;
}

function Past({ lines }: { lines: PastLine[] }) {
  const columns: Column<PastLine>[] = [
    { key: "name", label: t("col.round"), kind: "strong", cell: (line) => line.name },
    { key: "problem", label: t("col.problem"), kind: "wrap", cell: (line) => line.problem },
    {
      key: "result", label: t("col.result"), kind: "end",
      cell: (line) => <Button tone="link" small href={line.href}>{t("round.see_result")}</Button>,
    },
  ];
  return (
    <Card pad="sm">
      <Table columns={columns} rows={lines} rowKey={(line) => line.key} empty={t("home.past_none")} />
    </Card>
  );
}

export function Home(_props: PageProps) {
  const problems = useResource("/api/problems/", {});
  const wargames = useResource("/api/wargames/", {});
  const mineRounds = useResource("/api/rounds/", { query: { mine: true } });
  const joinable = useResource("/api/rounds/", { query: { state: "joinable" } });

  const catalogue = useMemo(() => catalogueOf(wargames.data, problems.data), [wargames.data, problems.data]);
  const roundsMine = mineRounds.data ?? [];
  const roundsOpen = roundsMine.filter((line) => line.phase !== "ended");
  const mineIds = new Set(roundsMine.map((line) => line.round));
  const joinableShown = (joinable.data ?? []).filter((line) => !mineIds.has(line.round) && openSides(line).length > 0);
  const past: PastLine[] = roundsMine.filter((line) => line.phase === "ended").map((line) => ({
    key: `r${line.round}`, name: t("round.name", { round: line.round }), problem: roundTitle(line), href: to.result(line.round),
  }));

  const all = botRoundProblems(problems.data ?? []);
  const stats = [
    { value: all.length, label: t("kind.round") },
    { value: catalogue.wargames.length, label: t("home.stat.wargames") },
  ];

  return (
    <AppPage title={t("page.home")}>
      <Hero title={t("page.home")} stats={problems.data ? stats : []} art />
      <PageBody>
        <Stack gap="lg">
          <Section title={t("home.my_players")}>
            {mineRounds.loading
              ? <Loading>{t("common.loading")}</Loading>
              : <MyPlayers rounds={roundsOpen} />}
          </Section>
          {joinableShown.length > 0 && (
            <Section title={t("home.joinable")}>
              <Joinable rounds={joinableShown} />
            </Section>
          )}
          <Section title={t("home.problems")} large>
            <ErrorNotice error={problems.error ?? wargames.error} />
            {problems.loading && !problems.data && <Loading>{t("common.loading")}</Loading>}
            {wargames.data && !catalogue.wargames.length && <Text tone="muted">{t("home.problems_none")}</Text>}
            <ProblemTiles catalogue={catalogue} />
          </Section>
          <Section title={t("home.past")}>
            <Past lines={past} />
          </Section>
        </Stack>
      </PageBody>
    </AppPage>
  );
}
