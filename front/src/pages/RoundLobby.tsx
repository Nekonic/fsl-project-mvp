import { useEffect, useState } from "preact/hooks";
import { waitForAllocation, type Schemas } from "../api/client";
import { holdAllocation } from "../api/follow";
import { useAction, useResource, useSession } from "../api/hooks";
import { to } from "../links";
import type { PageProps } from "../routes";
import { navigate } from "../router";
import { AppPage } from "../shell/AppPage";
import { clock } from "../format";
import { fieldErrors, t, tFor } from "../strings";
import {
  Badge, Button, Card, Choices, Code, Columns, Dot, ErrorNotice, Field, Form, FormActions, Hero, Input, Label, Loading, Notice, PageBody,
  Row, Select, Stack, Table, Task, Text, phaseTone, type Column,
} from "../ui";
import { wargameHost, wargameName } from "./wargameText";

type Allocation = Schemas["AllocationDetail"];
type RoundLine = Schemas["RoundLine"];
type PlayerLine = Schemas["PlayerLine"];
type Side = Schemas["PlayerSideEnum"];
type Matchup = Schemas["MatchupsEnum"];
type PlayerKind = "user" | "bot" | "driven" | "open";
type PlayerAsk = Schemas["PlayerAskRequest"];
type StepLine = Schemas["StepLine"];
type Problem = Schemas["LearnerProblemSummary"];

const SIDES: Side[] = ["attack", "defence"];
const MATCHUPS: Matchup[] = ["pvp", "def_vs_bot", "atk_vs_bot"];
const HUMAN_KINDS: PlayerKind[] = ["user", "open"];
const PLAYERS_FOR: Record<Matchup, Record<Side, PlayerKind>> = {
  pvp: { attack: "open", defence: "open" },
  def_vs_bot: { attack: "bot", defence: "open" },
  atk_vs_bot: { attack: "open", defence: "bot" },
};
const INLINE_PATHS = ["problem", "matchup", ...SIDES.flatMap((side) => [`players.${side}`, `players.${side}.username`, `players.${side}.bot.name`, `players.${side}.bot.step`, `players.${side}.bot`])];
const ROUND_KINDS_THAT_CHANGE = ["player.joined", "round.started", "round.ended"];

function playerOf(line: RoundLine, side: Side): PlayerLine | undefined {
  return line.players.find((player) => player.side === side);
}

export function seatOfUser(line: RoundLine, username: string | undefined): Side | undefined {
  if (!username) return undefined;
  return line.players.find((player) => player.client !== "bot" && player.username === username)?.side;
}

interface PlayerCellProps {
  line: RoundLine;
  side: Side;
  seated: boolean;
  joining: boolean;
  onJoin: (round: number, side: Side) => void;
}

function PlayerCell({ line, side, seated, joining, onJoin }: PlayerCellProps) {
  const player = playerOf(line, side);
  if (!player) return <Text tone="faint">{t("lobby.player.none")}</Text>;
  if (player.client === "bot") {
    return (
      <Stack gap="sm">
        <Text strong tone="heading">{player.step ? t("lobby.player.step", { step: tFor("bot_step", player.step) }) : t("lobby.player.bot")}</Text>
        {!player.step && <Text mono small tone="muted">{player.bot_name}</Text>}
        {player.bot_run && <Text small tone="muted">{tFor("bot_run", player.bot_run)}</Text>}
      </Stack>
    );
  }
  if (player.username !== null) {
    return (
      <Stack gap="sm">
        <Text strong mono tone="heading">{player.username}</Text>
        <Text small tone="muted"><Dot tone="ok" /> {t("lobby.player.joined")}</Text>
      </Stack>
    );
  }
  return (
    <Stack gap="sm">
      <Text small tone="muted"><Dot tone="warn" /> {t("lobby.player.open")}</Text>
      {line.phase === "created" && !seated && <Button tone="ghost" small busy={joining} onClick={() => onJoin(line.round, side)}>{t("player.join")}</Button>}
    </Stack>
  );
}

interface RoundsProps {
  allocation: Allocation;
  onChanged: () => void;
}

function Rounds({ allocation, onChanged }: RoundsProps) {
  const username = useSession().me?.user;
  const join = useAction("post", "/api/rounds/{round_id}/players/{side}/join/");
  const start = useAction("post", "/api/rounds/{round_id}/start/");
  const end = useAction("post", "/api/rounds/{round_id}/end/");
  const joinPlayer = async (round: number, side: Side) => {
    if (await join.run({ params: { round_id: String(round), side } })) onChanged();
  };
  const startRound = async (round: number) => {
    if (await start.run({ params: { round_id: round } })) onChanged();
  };
  const endRound = async (round: number) => {
    if (await end.run({ params: { round_id: round } })) onChanged();
  };
  const closed = allocation.closed !== null;

  const columns: Column<RoundLine>[] = [
    { key: "round", label: t("col.round"), kind: "strong", cell: (line) => t("round.name", { round: line.round }) },
    { key: "problem", label: t("col.problem"), kind: "nowrap", cell: (line) => line.problem_title },
    { key: "matchup", label: t("col.matchup"), kind: "nowrap", cell: (line) => tFor("matchup", line.matchup) },
    ...SIDES.map((side): Column<RoundLine> => ({
      key: side, label: t(`col.${side}_player`),
      cell: (line) => <PlayerCell line={line} side={side} seated={seatOfUser(line, username) !== undefined} joining={join.busy} onJoin={(round, chosen) => void joinPlayer(round, chosen)} />,
    })),
    { key: "phase", label: t("col.state"), cell: (line) => <Badge tone={phaseTone(line.phase)}>{tFor("phase", line.phase)}</Badge> },
    {
      key: "act", label: "", kind: "end",
      cell: (line) => {
        if (line.phase === "created") {
          return <Button tone="primary" small busy={start.busy} disabled={closed || !allocation.ready} onClick={() => void startRound(line.round)}>{t("lobby.start")}</Button>;
        }
        if (line.phase === "running" || line.phase === "starting") {
          const mine = seatOfUser(line, username);
          return (
            <Row>
              {mine && <Button tone="primary" small href={to.player(line.round, mine)}>{t(mine === "attack" ? "page.attack" : "page.defence")}</Button>}
              <Button tone="ghost" small busy={end.busy} disabled={line.phase === "starting"} onClick={() => void endRound(line.round)}>{t("lobby.end")}</Button>
            </Row>
          );
        }
        return <Button tone="link" small href={to.result(line.round)}>{t("round.see_result")}</Button>;
      },
    },
  ];

  return (
    <Task title={t("lobby.rounds")}>
      <Stack>
        <ErrorNotice error={join.error ?? start.error ?? end.error} />
        <Table columns={columns} rows={allocation.rounds} rowKey={(line) => line.round} empty={t("lobby.rounds_none")} />
      </Stack>
    </Task>
  );
}

interface PlayerChoice {
  kind: PlayerKind;
  username: string;
  bot: string;
  step: string;
}

function askOf(choice: PlayerChoice): PlayerAsk {
  if (choice.kind === "bot") return { bot: { step: choice.step } };
  if (choice.kind === "driven") return { bot: { name: choice.bot.trim() } };
  if (choice.kind === "user") return { username: choice.username.trim() };
  return { open: true };
}

function stepLabel(step: StepLine, side: Side): string {
  const pace = step[side].pace;
  return `${tFor("bot_step", step.id)} · ${t("lobby.step_pace", { minutes: Math.round(pace.window_s / 60), count: pace.per_window })}`;
}

interface PlayerPickProps {
  side: Side;
  botSide: boolean;
  staff: boolean;
  steps: StepLine[];
  choice: PlayerChoice;
  errors: Record<string, string>;
  onChoice: (choice: PlayerChoice) => void;
}

function PlayerPick({ side, botSide, staff, steps, choice, errors, onChoice }: PlayerPickProps) {
  const kinds: PlayerKind[] = botSide ? (staff ? ["bot", "driven"] : ["bot"]) : HUMAN_KINDS;
  const stepError = errors[`players.${side}.bot.step`] ?? errors[`players.${side}.bot`] ?? errors[`players.${side}`];
  return (
    <Card pad="md">
      <Stack gap="sm">
        <Text strong tone="heading" small>{t(`col.${side}_player`)}</Text>
        {kinds.length > 1 && (
          <Choices inline name={`player-${side}`} value={choice.kind} onValue={(kind) => onChoice({ ...choice, kind: kind as PlayerKind })}
            options={kinds.map((kind) => ({ value: kind, label: t(`lobby.player_kind.${kind}`) }))} />
        )}
        {choice.kind === "bot" && (
          <Stack gap="sm">
            <Label>{t("lobby.step")}</Label>
            {steps.length
              ? <Choices name={`step-${side}`} value={choice.step} onValue={(step) => onChoice({ ...choice, step })}
                options={steps.map((step) => ({ value: step.id, label: stepLabel(step, side) }))} />
              : <Text tone="muted" small>{t("lobby.step_none")}</Text>}
            {stepError && <Text tone="danger" small>{stepError}</Text>}
          </Stack>
        )}
        {choice.kind === "driven" && (
          <Field label={t("lobby.bot_name")} error={errors[`players.${side}.bot.name`] ?? errors[`players.${side}`]}>
            <Input mono spellcheck={false} value={choice.bot} onValue={(bot) => onChoice({ ...choice, bot })} />
          </Field>
        )}
        {choice.kind === "user" && (
          <Field label={t("lobby.username")} error={errors[`players.${side}.username`] ?? errors[`players.${side}`]}>
            <Input mono spellcheck={false} value={choice.username} onValue={(username) => onChoice({ ...choice, username })} />
          </Field>
        )}
      </Stack>
    </Card>
  );
}

interface CreateRoundProps {
  allocation: Allocation;
  problems: Problem[];
  steps: StepLine[];
  onCreated: () => void;
}

function matchupsOf(problem: Problem | undefined): Matchup[] {
  const allowed = MATCHUPS.filter((one) => problem?.matchups.includes(one));
  return allowed.length ? allowed : MATCHUPS;
}

function stepsOf(problem: Problem | undefined, steps: StepLine[]): StepLine[] {
  return steps.filter((step) => problem?.bot_steps.includes(step.id));
}

function CreateRound({ allocation, problems, steps, onCreated }: CreateRoundProps) {
  const staff = Boolean(useSession().me?.is_staff);
  const fitting = problems.filter((problem) => problem.wargame === allocation.wargame);
  const [problem, setProblem] = useState("");
  const [picked, setMatchup] = useState<Matchup>("pvp");
  const [players, setPlayers] = useState<Record<Side, PlayerChoice>>({
    attack: { kind: "open", username: "", bot: "", step: "" },
    defence: { kind: "open", username: "", bot: "", step: "" },
  });
  const [tokens, setTokens] = useState<Array<{ side: string; token: string; bot: string }>>([]);
  const [copied, setCopied] = useState("");
  const create = useAction("post", "/api/allocations/{allocation_id}/rounds/");

  const chosen = problem || String(fitting[0]?.id ?? "");
  const chosenProblem = fitting.find((one) => String(one.id) === chosen);
  const allowed = matchupsOf(chosenProblem);
  const matchup = allowed.includes(picked) ? picked : (allowed[0] as Matchup);
  const offered = stepsOf(chosenProblem, steps);
  const seatOf = (side: Side): PlayerChoice => {
    const choice = players[side];
    const botSide = PLAYERS_FOR[matchup][side] === "bot";
    const kind = botSide ? (choice.kind === "driven" && staff ? "driven" : "bot") : (choice.kind === "user" ? "user" : "open");
    const step = offered.some((one) => one.id === choice.step) ? choice.step : (offered[0]?.id ?? "");
    return { ...choice, kind, step };
  };
  const unended = allocation.rounds.some((line) => line.phase !== "ended");
  const closed = allocation.closed !== null;
  const errors = fieldErrors(create.error);

  const pickMatchup = (next: Matchup) => {
    setMatchup(next);
    setPlayers((was) => ({
      attack: { ...was.attack, kind: PLAYERS_FOR[next].attack },
      defence: { ...was.defence, kind: PLAYERS_FOR[next].defence },
    }));
  };
  const seats = { attack: seatOf("attack"), defence: seatOf("defence") };
  const stepless = SIDES.some((side) => seats[side].kind === "bot" && !seats[side].step);
  const blocked = closed || !allocation.ready || unended || !chosen || stepless;

  const submit = async () => {
    if (blocked) return;
    const made = await create.run({
      params: { allocation_id: allocation.allocation },
      body: { problem: Number(chosen), matchup, players: { attack: askOf(seats.attack), defence: askOf(seats.defence) } },
    });
    if (!made) return;
    setTokens(Object.entries(made.bot_tokens).map(([side, token]) => ({
      side, token, bot: made.players.find((player) => player.side === side)?.bot_name ?? "",
    })));
    onCreated();
  };

  const copy = async (token: string) => {
    try {
      await navigator.clipboard.writeText(token);
      setCopied(token);
    } catch {
      setCopied("");
    }
  };

  const reason = closed ? t("lobby.closed_notice") : !allocation.ready ? t("lobby.not_ready") : unended ? t("error.round_open") : !fitting.length ? t("lobby.no_match_problem") : stepless ? t("lobby.step_none") : "";

  return (
    <Task title={t("lobby.create")}>
      <Form onSubmit={() => void submit()}>
        <Stack>
          {staff && tokens.map((one) => (
            <Notice key={one.side} tone="info" title={t("lobby.token_once")}
              detail={<>{tFor("side", one.side)}{one.bot && <> · <Text mono>{one.bot}</Text></>}</>}>
              <Row>
                <Code>{one.token}</Code>
                <Button tone="ghost" small onClick={() => void copy(one.token)}>{copied === one.token ? t("lobby.copied") : t("lobby.copy")}</Button>
              </Row>
            </Notice>
          ))}
          <Field label={t("col.problem")} error={errors.problem}>
            <Select value={chosen} onValue={setProblem} disabled={!fitting.length}
              options={fitting.map((one) => ({ value: String(one.id), label: one.title }))} />
          </Field>
          <Stack gap="sm">
            <Label>{t("col.matchup")}</Label>
            <Choices name="matchup" value={matchup} onValue={(next) => pickMatchup(next as Matchup)}
              options={allowed.map((one) => ({ value: one, label: tFor("matchup", one) }))} />
            {errors.matchup && <Text tone="danger" small>{errors.matchup}</Text>}
          </Stack>
          <Columns shape="two">
            {SIDES.map((side) => (
              <PlayerPick key={side} side={side} botSide={PLAYERS_FOR[matchup][side] === "bot"} staff={staff} steps={offered}
                choice={seats[side]} errors={errors}
                onChoice={(choice) => setPlayers((was) => ({ ...was, [side]: choice }))} />
            ))}
          </Columns>
          <ErrorNotice error={create.error && { errors: create.error.errors.filter((error) => !INLINE_PATHS.includes(error.path)) }} />
          <FormActions>
            <Button tone="primary" type="submit" busy={create.busy} disabled={blocked}>{t("lobby.create_submit")}</Button>
            {reason && <Text tone="muted" small>{reason}</Text>}
          </FormActions>
        </Stack>
      </Form>
    </Task>
  );
}

export function RoundLobby({ params }: PageProps) {
  const allocationId = Number(params.allocation);
  const [liveRound, setLiveRound] = useState<number | null>(null);
  const allocation = useResource("/api/allocations/{allocation_id}/", { params: { allocation_id: allocationId } }, {
    refreshOn: liveRound ? { round: liveRound, kinds: ROUND_KINDS_THAT_CHANGE } : undefined,
  });
  const problems = useResource("/api/problems/", {});
  const steps = useResource("/api/bot-steps/", {});
  const close = useAction("post", "/api/allocations/{allocation_id}/close/");
  const shown = allocation.data;
  const live = shown?.rounds.find((line) => line.phase !== "ended")?.round ?? null;

  const open = shown !== undefined && shown.closed === null;

  useEffect(() => setLiveRound(live), [live]);
  useEffect(() => (open ? holdAllocation(allocationId) : undefined), [open, allocationId]);

  useEffect(() => {
    if (!shown || shown.ready || shown.closed !== null) return undefined;
    const abort = new AbortController();
    waitForAllocation(allocationId, { signal: abort.signal, onRead: allocation.setData }).catch(() => undefined);
    return () => abort.abort();
  }, [allocationId, shown?.ready, shown?.closed]);

  const giveBack = async () => {
    if (await close.run({ params: { allocation_id: allocationId } })) navigate(to.home());
  };

  const name = t("allocation.name", { allocation: allocationId });
  const state = !shown ? null : shown.closed !== null
    ? <Badge tone="muted">{t("lobby.closed")}</Badge>
    : shown.ready ? <Badge tone="ok">{t("lobby.ready")}</Badge> : <Badge tone="warn">{t("lobby.preparing")}</Badge>;
  const host = shown ? wargameHost(shown.wargame) : "";
  const facts = shown
    ? [
      ...(shown.slot !== null ? [{ value: t("slot.name", { slot: shown.slot }), label: t("lobby.slot"), mono: true }] : []),
      { value: clock(shown.expires_at), label: t("lobby.expires") },
    ]
    : [];

  return (
    <AppPage title={name} crumbs={[{ label: name }]}>
      <Hero icon="swords" title={name} badge={state}
        lead={shown ? [[wargameName(shown.wargame), host].filter(Boolean).join(" · ")] : []}
        facts={facts}
        actions={shown && shown.closed === null
          ? <Button tone="ghost" busy={close.busy} onClick={() => void giveBack()}>{t("lobby.close")}</Button>
          : undefined} />
      <PageBody>
        <Stack>
          <ErrorNotice error={allocation.error ?? close.error} />
          {!shown && allocation.loading && <Loading>{t("common.loading")}</Loading>}
          {shown && (
            <>
              <Rounds allocation={shown} onChanged={allocation.reload} />
              <CreateRound allocation={shown} problems={problems.data ?? []} steps={steps.data ?? []} onCreated={allocation.reload} />
            </>
          )}
        </Stack>
      </PageBody>
    </AppPage>
  );
}
