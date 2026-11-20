import { useEffect, useMemo, useState } from "preact/hooks";
import { waitForLease, type Schemas } from "../api/client";
import { holdLease } from "../api/follow";
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

type Lease = Schemas["LeaseDetail"];
type RoundLine = Schemas["RoundLine"];
type SeatLine = Schemas["SeatLine"];
type Side = Schemas["SeatSideEnum"];
type Matchup = Schemas["MatchupEnum"];
type SeatKind = "user" | "bot" | "open";
type SeatAsk = Schemas["SeatAskRequest"];


const SIDES: Side[] = ["attack", "defence"];
const MATCHUPS: Matchup[] = ["pvp", "def_vs_bot", "atk_vs_bot"];
const SEAT_KINDS: SeatKind[] = ["user", "bot", "open"];
const SEATS_FOR: Record<Matchup, Record<Side, SeatKind>> = {
  pvp: { attack: "open", defence: "open" },
  def_vs_bot: { attack: "bot", defence: "open" },
  atk_vs_bot: { attack: "open", defence: "bot" },
};
const INLINE_PATHS = ["problem", "matchup", ...SIDES.flatMap((side) => [`seats.${side}`, `seats.${side}.username`, `seats.${side}.bot.name`])];
const ROUND_KINDS_THAT_CHANGE = ["seat.joined", "round.started", "round.ended"];

function seatOf(line: RoundLine, side: Side): SeatLine | undefined {
  return line.seats.find((seat) => seat.side === side);
}

interface SeatCellProps {
  line: RoundLine;
  side: Side;
  joining: boolean;
  onJoin: (round: number, side: Side) => void;
}

function SeatCell({ line, side, joining, onJoin }: SeatCellProps) {
  const seat = seatOf(line, side);
  if (!seat) return <Text tone="faint">{t("lobby.seat.none")}</Text>;
  if (seat.client === "bot") {
    return <Stack gap="sm"><Text strong tone="heading">{t("lobby.seat.bot")}</Text><Text mono small tone="muted">{seat.bot_name}</Text></Stack>;
  }
  if (seat.username !== null) {
    return (
      <Stack gap="sm">
        <Text strong mono tone="heading">{seat.username}</Text>
        <Text small tone="muted"><Dot tone="ok" /> {t("lobby.seat.joined")}</Text>
      </Stack>
    );
  }
  return (
    <Stack gap="sm">
      <Text small tone="muted"><Dot tone="warn" /> {t("lobby.seat.open")}</Text>
      {line.phase === "created" && <Button tone="ghost" small busy={joining} onClick={() => onJoin(line.round, side)}>{t("seat.join")}</Button>}
    </Stack>
  );
}

interface RoundsProps {
  lease: Lease;
  titleOf: (problem: number) => string;
  onChanged: () => void;
}

function Rounds({ lease, titleOf, onChanged }: RoundsProps) {
  const join = useAction("post", "/api/rounds/{round_id}/seats/{side}/join/");
  const start = useAction("post", "/api/rounds/{round_id}/start/");
  const end = useAction("post", "/api/rounds/{round_id}/end/");
  const joinSeat = async (round: number, side: Side) => {
    if (await join.run({ params: { round_id: String(round), side } })) onChanged();
  };
  const startRound = async (round: number) => {
    if (await start.run({ params: { round_id: round } })) onChanged();
  };
  const endRound = async (round: number) => {
    if (await end.run({ params: { round_id: round } })) onChanged();
  };
  const closed = lease.closed !== null;

  const columns: Column<RoundLine>[] = [
    { key: "round", label: t("col.round"), kind: "strong", cell: (line) => t("round.name", { round: line.round }) },
    { key: "problem", label: t("col.problem"), kind: "nowrap", cell: (line) => titleOf(line.problem) },
    { key: "matchup", label: t("col.matchup"), kind: "nowrap", cell: (line) => tFor("matchup", line.matchup) },
    ...SIDES.map((side): Column<RoundLine> => ({
      key: side, label: t(`col.${side}_seat`),
      cell: (line) => <SeatCell line={line} side={side} joining={join.busy} onJoin={(round, chosen) => void joinSeat(round, chosen)} />,
    })),
    { key: "phase", label: t("col.state"), cell: (line) => <Badge tone={phaseTone(line.phase)}>{tFor("phase", line.phase)}</Badge> },
    {
      key: "act", label: "", kind: "end",
      cell: (line) => {
        if (line.phase === "created") {
          return <Button tone="primary" small busy={start.busy} disabled={closed || !lease.ready} onClick={() => void startRound(line.round)}>{t("lobby.start")}</Button>;
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
        <Table columns={columns} rows={lease.rounds} rowKey={(line) => line.round} empty={t("lobby.rounds_none")} />
      </Stack>
    </Task>
  );
}

interface SeatChoice {
  kind: SeatKind;
  username: string;
  bot: string;
}

function askOf(choice: SeatChoice): SeatAsk {
  if (choice.kind === "bot") return { bot: { name: choice.bot.trim() } };
  if (choice.kind === "user") return { username: choice.username.trim() };
  return { open: true };
}

interface SeatPickProps {
  side: Side;
  choice: SeatChoice;
  errors: Record<string, string>;
  onChoice: (choice: SeatChoice) => void;
}

function SeatPick({ side, choice, errors, onChoice }: SeatPickProps) {
  return (
    <Card pad="md">
      <Stack gap="sm">
        <Text strong tone="heading" small>{t(`col.${side}_seat`)}</Text>
        <Choices inline name={`seat-${side}`} value={choice.kind} onValue={(kind) => onChoice({ ...choice, kind: kind as SeatKind })}
          options={SEAT_KINDS.map((kind) => ({ value: kind, label: t(`lobby.seat_kind.${kind}`) }))} />
        {choice.kind === "bot" && (
          <Field label={t("lobby.bot_name")} error={errors[`seats.${side}.bot.name`] ?? errors[`seats.${side}`]}>
            <Input mono spellcheck={false} value={choice.bot} onValue={(bot) => onChoice({ ...choice, bot })} />
          </Field>
        )}
        {choice.kind === "user" && (
          <Field label={t("lobby.username")} error={errors[`seats.${side}.username`] ?? errors[`seats.${side}`]}>
            <Input mono spellcheck={false} value={choice.username} onValue={(username) => onChoice({ ...choice, username })} />
          </Field>
        )}
      </Stack>
    </Card>
  );
}

interface CreateRoundProps {
  lease: Lease;
  problems: Schemas["LearnerProblemSummary"][];
  onCreated: () => void;
}

function CreateRound({ lease, problems, onCreated }: CreateRoundProps) {
  const fitting = problems.filter((problem) => problem.wargame === lease.wargame && problem.kind !== "lesson");
  const [problem, setProblem] = useState("");
  const [matchup, setMatchup] = useState<Matchup>("pvp");
  const [seats, setSeats] = useState<Record<Side, SeatChoice>>({
    attack: { kind: "open", username: "", bot: "" },
    defence: { kind: "open", username: "", bot: "" },
  });
  const [tokens, setTokens] = useState<Array<{ side: string; token: string; bot: string }>>([]);
  const [copied, setCopied] = useState("");
  const create = useAction("post", "/api/leases/{lease_id}/rounds/");

  const chosen = problem || String(fitting[0]?.id ?? "");
  const unended = lease.rounds.some((line) => line.phase !== "ended");
  const closed = lease.closed !== null;
  const blocked = closed || !lease.ready || unended || !chosen;
  const errors = fieldErrors(create.error);

  const pickMatchup = (next: Matchup) => {
    setMatchup(next);
    setSeats((was) => ({
      attack: { ...was.attack, kind: SEATS_FOR[next].attack },
      defence: { ...was.defence, kind: SEATS_FOR[next].defence },
    }));
  };

  const submit = async () => {
    if (blocked) return;
    const made = await create.run({
      params: { lease_id: lease.lease },
      body: { problem: Number(chosen), matchup, seats: { attack: askOf(seats.attack), defence: askOf(seats.defence) } },
    });
    if (!made) return;
    setTokens(Object.entries(made.bot_tokens).map(([side, token]) => ({
      side, token, bot: made.seats.find((seat) => seat.side === side)?.bot_name ?? "",
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

  const reason = closed ? t("lobby.closed_notice") : !lease.ready ? t("lobby.not_ready") : unended ? t("error.round_open") : !fitting.length ? t("lobby.no_match_problem") : "";

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
              <SeatPick key={side} side={side} choice={seats[side]} errors={errors}
                onChoice={(choice) => setSeats((was) => ({ ...was, [side]: choice }))} />
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
  const leaseId = Number(params.lease);
  const [liveRound, setLiveRound] = useState<number | null>(null);
  const lease = useResource("/api/leases/{lease_id}/", { params: { lease_id: leaseId } }, {
    refreshOn: liveRound ? { round: liveRound, kinds: ROUND_KINDS_THAT_CHANGE } : undefined,
  });
  const problems = useResource("/api/problems/", {});
  const close = useAction("post", "/api/leases/{lease_id}/close/");
  const shown = lease.data;
  const live = shown?.rounds.find((line) => line.phase !== "ended")?.round ?? null;

  useEffect(() => {
    setLiveRound(live);
    if (live) holdLease(live, leaseId);
  }, [live, leaseId]);

  useEffect(() => {
    if (!shown || shown.ready || shown.closed !== null) return undefined;
    const abort = new AbortController();
    waitForLease(leaseId, { signal: abort.signal, onRead: lease.setData }).catch(() => undefined);
    return () => abort.abort();
  }, [leaseId, shown?.ready, shown?.closed]);

  const titleOf = useMemo(() => {
    const byId = new Map((problems.data ?? []).map((one) => [one.id, one.title]));
    return (problem: number) => byId.get(problem) ?? t("home.problem_no", { problem });
  }, [problems.data]);

  const giveBack = async () => {
    if (await close.run({ params: { lease_id: leaseId } })) navigate(to.home());
  };

  const name = t("lease.name", { lease: leaseId });
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
          <ErrorNotice error={lease.error ?? close.error} />
          {!shown && lease.loading && <Loading>{t("common.loading")}</Loading>}
          {shown && (
            <>
              <Rounds lease={shown} titleOf={titleOf} onChanged={lease.reload} />
              <CreateRound lease={shown} problems={problems.data ?? []} onCreated={lease.reload} />
            </>
          )}
        </Stack>
      </PageBody>
    </AppPage>
  );
}
