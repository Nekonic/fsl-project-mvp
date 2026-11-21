import { useEffect, useMemo, useState } from "preact/hooks";
import { waitForAllocation, type Schemas } from "../api/client";
import { holdAllocation } from "../api/follow";
import { useAction, useResource } from "../api/hooks";
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
type Matchup = Schemas["MatchupEnum"];
type PlayerKind = "user" | "bot" | "open";
type PlayerAsk = Schemas["PlayerAskRequest"];


const SIDES: Side[] = ["attack", "defence"];
const MATCHUPS: Matchup[] = ["pvp", "def_vs_bot", "atk_vs_bot"];
const PLAYER_KINDS: PlayerKind[] = ["user", "bot", "open"];
const PLAYERS_FOR: Record<Matchup, Record<Side, PlayerKind>> = {
  pvp: { attack: "open", defence: "open" },
  def_vs_bot: { attack: "bot", defence: "open" },
  atk_vs_bot: { attack: "open", defence: "bot" },
};
const INLINE_PATHS = ["problem", "matchup", ...SIDES.flatMap((side) => [`players.${side}`, `players.${side}.username`, `players.${side}.bot.name`])];
const ROUND_KINDS_THAT_CHANGE = ["player.joined", "round.started", "round.ended"];

function playerOf(line: RoundLine, side: Side): PlayerLine | undefined {
  return line.players.find((player) => player.side === side);
}

interface PlayerCellProps {
  line: RoundLine;
  side: Side;
  joining: boolean;
  onJoin: (round: number, side: Side) => void;
}

function PlayerCell({ line, side, joining, onJoin }: PlayerCellProps) {
  const player = playerOf(line, side);
  if (!player) return <Text tone="faint">{t("lobby.player.none")}</Text>;
  if (player.client === "bot") {
    return <Stack gap="sm"><Text strong tone="heading">{t("lobby.player.bot")}</Text><Text mono small tone="muted">{player.bot_name}</Text></Stack>;
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
      {line.phase === "created" && <Button tone="ghost" small busy={joining} onClick={() => onJoin(line.round, side)}>{t("player.join")}</Button>}
    </Stack>
  );
}

interface RoundsProps {
  allocation: Allocation;
  titleOf: (problem: number) => string;
  onChanged: () => void;
}

function Rounds({ allocation, titleOf, onChanged }: RoundsProps) {
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
    { key: "problem", label: t("col.problem"), kind: "nowrap", cell: (line) => titleOf(line.problem) },
    { key: "matchup", label: t("col.matchup"), kind: "nowrap", cell: (line) => tFor("matchup", line.matchup) },
    ...SIDES.map((side): Column<RoundLine> => ({
      key: side, label: t(`col.${side}_player`),
      cell: (line) => <PlayerCell line={line} side={side} joining={join.busy} onJoin={(round, chosen) => void joinPlayer(round, chosen)} />,
    })),
    { key: "phase", label: t("col.state"), cell: (line) => <Badge tone={phaseTone(line.phase)}>{tFor("phase", line.phase)}</Badge> },
    {
      key: "act", label: "", kind: "end",
      cell: (line) => {
        if (line.phase === "created") {
          return <Button tone="primary" small busy={start.busy} disabled={closed || !allocation.ready} onClick={() => void startRound(line.round)}>{t("lobby.start")}</Button>;
        }
        if (line.phase === "running" || line.phase === "starting") {
          return <Button tone="ghost" small busy={end.busy} disabled={line.phase === "starting"} onClick={() => void endRound(line.round)}>{t("lobby.end")}</Button>;
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
}

function askOf(choice: PlayerChoice): PlayerAsk {
  if (choice.kind === "bot") return { bot: { name: choice.bot.trim() } };
  if (choice.kind === "user") return { username: choice.username.trim() };
  return { open: true };
}

interface PlayerPickProps {
  side: Side;
  choice: PlayerChoice;
  errors: Record<string, string>;
  onChoice: (choice: PlayerChoice) => void;
}

function PlayerPick({ side, choice, errors, onChoice }: PlayerPickProps) {
  return (
    <Card pad="md">
      <Stack gap="sm">
        <Text strong tone="heading" small>{t(`col.${side}_player`)}</Text>
        <Choices inline name={`player-${side}`} value={choice.kind} onValue={(kind) => onChoice({ ...choice, kind: kind as PlayerKind })}
          options={PLAYER_KINDS.map((kind) => ({ value: kind, label: t(`lobby.player_kind.${kind}`) }))} />
        {choice.kind === "bot" && (
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
  problems: Schemas["LearnerProblemSummary"][];
  onCreated: () => void;
}

function CreateRound({ allocation, problems, onCreated }: CreateRoundProps) {
  const fitting = problems.filter((problem) => problem.wargame === allocation.wargame && problem.kind !== "lesson");
  const [problem, setProblem] = useState("");
  const [matchup, setMatchup] = useState<Matchup>("pvp");
  const [players, setPlayers] = useState<Record<Side, PlayerChoice>>({
    attack: { kind: "open", username: "", bot: "" },
    defence: { kind: "open", username: "", bot: "" },
  });
  const [tokens, setTokens] = useState<Array<{ side: string; token: string; bot: string }>>([]);
  const [copied, setCopied] = useState("");
  const create = useAction("post", "/api/allocations/{allocation_id}/rounds/");

  const chosen = problem || String(fitting[0]?.id ?? "");
  const unended = allocation.rounds.some((line) => line.phase !== "ended");
  const closed = allocation.closed !== null;
  const blocked = closed || !allocation.ready || unended || !chosen;
  const errors = fieldErrors(create.error);

  const pickMatchup = (next: Matchup) => {
    setMatchup(next);
    setPlayers((was) => ({
      attack: { ...was.attack, kind: PLAYERS_FOR[next].attack },
      defence: { ...was.defence, kind: PLAYERS_FOR[next].defence },
    }));
  };

  const submit = async () => {
    if (blocked) return;
    const made = await create.run({
      params: { allocation_id: allocation.allocation },
      body: { problem: Number(chosen), matchup, players: { attack: askOf(players.attack), defence: askOf(players.defence) } },
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

  const reason = closed ? t("lobby.closed_notice") : !allocation.ready ? t("lobby.not_ready") : unended ? t("error.round_open") : !fitting.length ? t("lobby.no_match_problem") : "";

  return (
    <Task title={t("lobby.create")}>
      <Form onSubmit={() => void submit()}>
        <Stack>
          {tokens.map((one) => (
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
              options={MATCHUPS.map((one) => ({ value: one, label: tFor("matchup", one) }))} />
            {errors.matchup && <Text tone="danger" small>{errors.matchup}</Text>}
          </Stack>
          <Columns shape="two">
            {SIDES.map((side) => (
              <PlayerPick key={side} side={side} choice={players[side]} errors={errors}
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

  const titleOf = useMemo(() => {
    const byId = new Map((problems.data ?? []).map((one) => [one.id, one.title]));
    return (problem: number) => byId.get(problem) ?? t("home.problem_no", { problem });
  }, [problems.data]);

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
              <Rounds allocation={shown} titleOf={titleOf} onChanged={allocation.reload} />
              <CreateRound allocation={shown} problems={problems.data ?? []} onCreated={allocation.reload} />
            </>
          )}
        </Stack>
      </PageBody>
    </AppPage>
  );
}
