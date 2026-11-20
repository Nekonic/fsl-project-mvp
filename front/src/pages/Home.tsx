import { useMemo, useState } from "preact/hooks";
import { ApiError, openLease, type Schemas } from "../api/client";
import { useAction, useResource } from "../api/hooks";
import { to } from "../links";
import type { PageProps } from "../routes";
import { navigate } from "../router";
import { AppPage } from "../shell/AppPage";
import { t, tFor } from "../strings";
import {
  Badge, Badges, Button, Card, ErrorNotice, Group, GroupHead, Hero, ListRow, Loading, PageBody, Section, Stack, Table, Tabs, TargetHead, Text,
  Tile, Tiles, lessonTileLook, phaseTone, roundTileLook, type Column,
} from "../ui";
import { wargameHost, wargameLead, wargameName } from "./wargameText";

type Problem = Schemas["LearnerProblemSummary"];
type RoundLine = Schemas["RoundLine"];
type LessonLine = Schemas["LessonLine"];
type Side = Schemas["SeatSideEnum"];
type Shown = "all" | "lesson" | "round";

const isLesson = (problem: Problem) => problem.kind === "lesson";
const sideLabel = (side: string) => tFor("side", side);

interface Catalogue {
  titleOf: (problem: number) => string;
  wargames: Array<{ wargame: string; lessons: Problem[]; rounds: Problem[] }>;
}

function catalogueOf(problems: Problem[] | undefined): Catalogue {
  const byId = new Map((problems ?? []).map((problem) => [problem.id, problem]));
  const order: string[] = [];
  for (const problem of problems ?? []) if (!order.includes(problem.wargame)) order.push(problem.wargame);
  return {
    titleOf: (problem) => byId.get(problem)?.title ?? t("home.problem_no", { problem }),
    wargames: order.map((wargame) => {
      const own = (problems ?? []).filter((problem) => problem.wargame === wargame);
      return { wargame, lessons: own.filter(isLesson), rounds: own.filter((problem) => !isLesson(problem)) };
    }),
  };
}

function humanSides(line: RoundLine): Side[] {
  return line.seats.filter((seat) => seat.client === "human" && seat.username !== null).map((seat) => seat.side);
}

function openSides(line: RoundLine): Side[] {
  return line.seats.filter((seat) => seat.client === "human" && seat.username === null).map((seat) => seat.side);
}

function MySeats({ rounds, lessons, catalogue }: { rounds: RoundLine[]; lessons: LessonLine[]; catalogue: Catalogue }) {
  if (!rounds.length && !lessons.length) return <Card pad="md"><Text tone="muted">{t("home.my_seats_none")}</Text></Card>;
  return (
    <Card list>
      {rounds.map((line) => {
        const sides = humanSides(line);
        const first = sides[0] ?? "defence";
        return (
          <ListRow key={`r${line.round}`} id={t("round.name", { round: line.round })} href={to.seat(line.round, first)}
            main={<><Text tone="heading">{catalogue.titleOf(line.problem)}</Text><Text tone="muted" small>{tFor("matchup", line.matchup)}</Text></>}
            side={<>
              <Badge tone={phaseTone(line.phase)}>{tFor("phase", line.phase)}</Badge>
              {sides.map((side) => (
                <Button key={side} tone="ghost" small href={to.seat(line.round, side)}>{t(side === "attack" ? "page.attack" : "page.defence")}</Button>
              ))}
            </>} />
        );
      })}
      {lessons.map((line) => (
        <ListRow key={`l${line.round}`} id={t("home.lesson_name", { round: line.round })} href={to.lesson(line.round)}
          main={<><Text tone="heading">{catalogue.titleOf(line.problem)}</Text>{line.passed_order > 0 && <Text tone="muted" small>{t("home.passed_steps", { n: line.passed_order })}</Text>}</>}
          side={<Button tone="primary" small href={to.lesson(line.round)}>{t("home.resume_lesson")}</Button>} />
      ))}
    </Card>
  );
}

function Joinable({ rounds, catalogue }: { rounds: RoundLine[]; catalogue: Catalogue }) {
  const join = useAction("post", "/api/rounds/{round_id}/seats/{side}/join/");
  const take = async (round: number, side: Side) => {
    const joined = await join.run({ params: { round_id: String(round), side } });
    if (joined) navigate(to.seat(round, joined.side));
  };
  return (
    <Stack gap="sm">
      <ErrorNotice error={join.error} />
      <Card list>
        {rounds.map((line) => (
          <ListRow key={line.round} id={t("round.name", { round: line.round })}
            main={<><Text tone="heading">{catalogue.titleOf(line.problem)}</Text><Text tone="muted" small>{tFor("matchup", line.matchup)}</Text></>}
            side={openSides(line).map((side) => (
              <Badges key={side}>
                <Badge tone="warn">{t("home.seat_open", { side: sideLabel(side) })}</Badge>
                <Button tone="primary" small busy={join.busy} onClick={() => void take(line.round, side)}>{t("seat.join")}</Button>
              </Badges>
            ))} />
        ))}
      </Card>
    </Stack>
  );
}

interface ProblemTilesProps {
  catalogue: Catalogue;
  shown: Shown;
  lessonsMine: LessonLine[];
}

function ProblemTiles({ catalogue, shown, lessonsMine }: ProblemTilesProps) {
  const lesson = useAction("post", "/api/lessons/");
  const [opening, setOpening] = useState<string | null>(null);
  const [openError, setOpenError] = useState<ApiError | undefined>(undefined);
  const started = (problem: number) => lessonsMine.find((line) => line.problem === problem && line.phase !== "ended");

  const startLesson = async (problem: number) => {
    const opened = await lesson.run({ body: { problem } });
    if (opened) navigate(to.lesson(opened.round));
  };
  const openRange = async (wargame: string) => {
    setOpening(wargame);
    setOpenError(undefined);
    try {
      const lease = await openLease(wargame);
      navigate(to.lease(lease.lease));
    } catch (failed) {
      setOpenError(failed instanceof ApiError ? failed : new ApiError(0, [{ path: "", code: "network" }]));
    } finally {
      setOpening(null);
    }
  };

  let lessonNo = 0;
  return (
    <Stack gap="lg">
      <ErrorNotice error={lesson.error} />
      <ErrorNotice error={openError} />
      {catalogue.wargames
        .filter((group) => shown === "all" || (shown === "lesson" ? group.lessons.length : group.rounds.length))
        .map((group) => (
          <Group key={group.wargame}>
            <TargetHead eyebrow={t("home.target")} title={wargameName(group.wargame)} text={wargameLead(group.wargame) || undefined}
              tag={wargameHost(group.wargame) ? <Badge mono>{wargameHost(group.wargame)}</Badge> : undefined} />
            {shown !== "round" && group.lessons.length > 0 && (
              <Group>
                <GroupHead title={t("kind.lesson")} sub={t("home.lessons_count", { n: group.lessons.length })} />
                <Tiles>
                  {group.lessons.map((problem) => {
                    lessonNo += 1;
                    const look = lessonTileLook(lessonNo);
                    const mine = started(problem.id);
                    return (
                      <Tile key={problem.id} icon={look.icon} tone={look.tone} label={t("home.lesson_no", { n: lessonNo })} title={problem.title} text={problem.summary}
                        foot={<>
                          <Badge>{sideLabel(problem.side)}</Badge>
                          {mine && mine.passed_order > 0 && <Text tone="faint">{t("home.passed_steps", { n: mine.passed_order })}</Text>}
                        </>}
                        action={mine
                          ? <Button tone="primary" small href={to.lesson(mine.round)}>{t("home.resume_lesson")}</Button>
                          : <Button tone="primary" small busy={lesson.busy} onClick={() => void startLesson(problem.id)}>{t("home.start_lesson")}</Button>} />
                    );
                  })}
                </Tiles>
              </Group>
            )}
            {shown !== "lesson" && group.rounds.length > 0 && (
              <Group>
                <GroupHead title={t("kind.round")} sub={t("home.rounds_count", { n: group.rounds.length })} />
                <Tiles>
                  {group.rounds.map((problem) => (
                    <Tile key={problem.id} icon={roundTileLook.icon} tone={roundTileLook.tone} label={t("kind.round")} title={problem.title} text={problem.summary}
                      foot={<Badge>{sideLabel(problem.side)}</Badge>}
                      action={<Button tone="primary" small busy={opening === problem.wargame} disabled={opening !== null && opening !== problem.wargame}
                        onClick={() => void openRange(problem.wargame)}>{t("home.open_range")}</Button>} />
                  ))}
                </Tiles>
              </Group>
            )}
          </Group>
        ))}
    </Stack>
  );
}

interface PastLine {
  key: string;
  name: string;
  problem: number;
  href?: string;
  result: "result" | "ended";
}

function Past({ lines, catalogue }: { lines: PastLine[]; catalogue: Catalogue }) {
  const columns: Column<PastLine>[] = [
    { key: "name", label: t("col.round"), kind: "strong", cell: (line) => line.name },
    { key: "problem", label: t("col.problem"), kind: "wrap", cell: (line) => catalogue.titleOf(line.problem) },
    {
      key: "result", label: t("col.result"), kind: "end",
      cell: (line) => line.href
        ? <Button tone="link" small href={line.href}>{t("round.see_result")}</Button>
        : <Text tone="muted">{t("phase.ended")}</Text>,
    },
  ];
  return (
    <Card pad="sm">
      <Table columns={columns} rows={lines} rowKey={(line) => line.key} empty={t("home.past_none")} />
    </Card>
  );
}

export function Home(_props: PageProps) {
  const [shown, setShown] = useState<Shown>("all");
  const problems = useResource("/api/problems/", {});
  const mineRounds = useResource("/api/rounds/", { query: { mine: true } });
  const joinable = useResource("/api/rounds/", { query: { state: "joinable" } });
  const lessons = useResource("/api/lessons/", { query: { mine: true } });

  const catalogue = useMemo(() => catalogueOf(problems.data), [problems.data]);
  const roundsMine = (mineRounds.data ?? []).filter((line) => line.kind !== "lesson");
  const roundsOpen = roundsMine.filter((line) => line.phase !== "ended");
  const lessonsMine = lessons.data ?? [];
  const lessonsOpen = lessonsMine.filter((line) => line.phase !== "ended");
  const mineIds = new Set(roundsMine.map((line) => line.round));
  const joinableShown = (joinable.data ?? []).filter((line) => !mineIds.has(line.round) && openSides(line).length > 0);
  const past: PastLine[] = [
    ...roundsMine.filter((line) => line.phase === "ended").map((line) => ({
      key: `r${line.round}`, name: t("round.name", { round: line.round }), problem: line.problem, href: to.result(line.round), result: "result" as const,
    })),
    ...lessonsMine.filter((line) => line.phase === "ended").map((line) => ({
      key: `l${line.round}`, name: t("home.lesson_name", { round: line.round }), problem: line.problem, result: "ended" as const,
    })),
  ];

  const all = problems.data ?? [];
  const stats = [
    { value: all.filter(isLesson).length, label: t("kind.lesson") },
    { value: all.filter((problem) => !isLesson(problem)).length, label: t("kind.round") },
    { value: catalogue.wargames.length, label: t("home.stat.wargames") },
  ];
  const tabs = [
    { id: "all", label: t("home.tab.all") },
    { id: "lesson", label: t("kind.lesson") },
    { id: "round", label: t("kind.round") },
  ];
  const showLessons = shown !== "round";
  const showRounds = shown !== "lesson";

  return (
    <AppPage title={t("page.home")}>
      <Hero title={t("page.home")} stats={problems.data ? stats : []} art />
      <Tabs tabs={tabs} value={shown} onChange={(id) => setShown(id as Shown)} />
      <PageBody>
        <Stack gap="lg">
          <Section title={t("home.my_seats")}>
            {mineRounds.loading && lessons.loading
              ? <Loading>{t("common.loading")}</Loading>
              : <MySeats rounds={showRounds ? roundsOpen : []} lessons={showLessons ? lessonsOpen : []} catalogue={catalogue} />}
          </Section>
          {showRounds && joinableShown.length > 0 && (
            <Section title={t("home.joinable")}>
              <Joinable rounds={joinableShown} catalogue={catalogue} />
            </Section>
          )}
          <Section title={t("home.problems")} large>
            <ErrorNotice error={problems.error} />
            {problems.loading && !problems.data && <Loading>{t("common.loading")}</Loading>}
            {problems.data && !problems.data.length && <Text tone="muted">{t("home.problems_none")}</Text>}
            <ProblemTiles catalogue={catalogue} shown={shown} lessonsMine={lessonsMine} />
          </Section>
          <Section title={t("home.past")}>
            <Past lines={past.filter((line) => (line.result === "ended" ? showLessons : showRounds))} catalogue={catalogue} />
          </Section>
        </Stack>
      </PageBody>
    </AppPage>
  );
}
