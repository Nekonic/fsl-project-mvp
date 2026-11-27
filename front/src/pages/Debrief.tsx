import type { Schemas } from "../api/client";
import { useResource } from "../api/hooks";
import { withStoppedEarly } from "../botRun";
import { clockSeconds, count, ro } from "../format";
import { to } from "../links";
import { ScoreReport } from "../panes/Score";
import type { PageProps } from "../routes";
import { AppPage } from "../shell/AppPage";
import { hasString, t, tFor, type StringParams } from "../strings";
import {
  Button, Card, CardHead, Code, ErrorNotice, Hero, Loading, Notice, PageBody, Prose, Section, Stack, Table, Task, Text, type Column,
} from "../ui";

type DebriefShown = Schemas["Debrief"];
type CardShown = Schemas["CardShown"];
type ScoreShown = Schemas["Score"];

export interface BotLine {
  side: string;
  step: string;
  model: string;
  status: string;
  exit: string;
  cost_usd: number | null;
  turns: number | null;
  refusals: number;
  closing: string;
  left_of_round_s?: number | null;
}

export interface TimelineRow {
  lane: string;
  kind: string;
  at: string | null;
  [field: string]: unknown;
}

interface ObjectiveMark {
  key: string;
  detected: boolean;
  responded: boolean;
}

const LANES = ["attack", "defence"] as const;

function text(row: TimelineRow, field: string): string {
  const value = row[field];
  return value === null || value === undefined || value === "" ? "—" : String(value);
}

function engineOf(row: TimelineRow): string {
  return tFor("engine", text(row, "engine"));
}

function mark(on: boolean): string {
  return t(on ? "mark.yes" : "mark.no");
}

function paramsOf(row: TimelineRow, marks: ObjectiveMark[]): StringParams {
  const params: StringParams = {};
  for (const [field, value] of Object.entries(row)) {
    if (typeof value === "string" || typeof value === "number") params[field] = value;
  }
  for (const field of ["origin", "case", "ip", "tool", "exit_code", "signature", "command", "name", "version"]) params[field] = text(row, field);
  if (typeof row.case === "string" && typeof row.title === "string" && row.title) params.case = row.title;
  if ("engine" in row) params.engine = engineOf(row);
  if (row.kind === "rule.tested") params.result = t(row.passed ? "debrief.test.passed" : "debrief.test.failed");
  if (row.kind === "origin.switched") params.ro = ro(text(row, "ip"));
  if (row.kind === "case.judged") params.verdict = tFor("verdict", text(row, "verdict"));
  if (row.kind === "bot_note") params.note = tFor("debrief.note", text(row, "note"));
  if (typeof row.count === "number") params.count = count(row.count);
  if (typeof row.alerts === "number") params.alerts = count(row.alerts);
  const objective = row.kind === "objective.lost" ? marks.find((one) => one.key === row.key) : undefined;
  if (objective) params.name = `${text(row, "name")} · ${t("debrief.marks", { detected: mark(objective.detected), responded: mark(objective.responded) })}`;
  return params;
}

const HTTP_STATUS = /^\d{3}$/;

export function accessRefusal(row: TimelineRow): boolean {
  const rule = typeof row.rule === "string" ? row.rule : "";
  return row.kind === "alerts" && row.engine === "waf" && HTTP_STATUS.test(rule)
    && typeof row.signature === "string" && row.signature.startsWith(`${rule} `);
}

export function rowText(row: TimelineRow, marks: ObjectiveMark[] = []): string {
  const params = paramsOf(row, marks);
  if (accessRefusal(row)) return t("debrief.row.access_refusals", { ...params, status: text(row, "rule") });
  if (row.kind === "alerts" && typeof row.rules === "number" && row.rules > 1) {
    return t("debrief.row.alerts_rules", { ...params, others: count(row.rules - 1) });
  }
  return tFor("debrief.row", row.kind, params);
}

function laneCell(row: TimelineRow, lane: string, marks: ObjectiveMark[]) {
  if (row.lane !== lane && row.lane !== "both") return null;
  const said = rowText(row, marks);
  if (row.kind === "bot_note") return <Text small tone={row.note === "refused" || row.note === "denied" ? "warn" : "muted"}>{said}</Text>;
  if (row.lane === "both") return <Text strong tone="danger">{said}</Text>;
  return <Text>{said}</Text>;
}

function Timeline({ rows, marks }: { rows: TimelineRow[]; marks: ObjectiveMark[] }) {
  const columns: Column<TimelineRow>[] = [
    { key: "at", label: t("debrief.col.at"), kind: "mono", cell: (row) => clockSeconds(row.at) },
    ...LANES.map((lane): Column<TimelineRow> => ({
      key: lane, label: t(`side.${lane}.team`), kind: "wrap", cell: (row) => laneCell(row, lane, marks),
    })),
  ];
  return (
    <Task title={t("debrief.timeline")}>
      <Stack gap="sm">
        <Text tone="muted" small>{t("debrief.timeline_lead")}</Text>
        <Table columns={columns} rows={rows} rowKey={(_, index) => index} variant="compact" empty={t("debrief.timeline_none")} />
      </Stack>
    </Task>
  );
}

function stepName(step: string | null | undefined): string {
  return step ? tFor("bot_step", step) : "—";
}

function Bots({ bots }: { bots: BotLine[] }) {
  const columns: Column<BotLine>[] = [
    { key: "side", label: t("debrief.col.side"), kind: "nowrap", cell: (bot) => tFor("side", bot.side) },
    { key: "step", label: t("debrief.col.step"), kind: "nowrap", cell: (bot) => stepName(bot.step) },
    { key: "model", label: t("debrief.col.model"), kind: "mono", cell: (bot) => bot.model },
    { key: "exit", label: t("debrief.col.exit"), kind: "nowrap", cell: (bot) => withStoppedEarly(bot, bot.exit ? tFor("bot_exit", bot.exit) : tFor("bot_run", bot.status)) },
    { key: "cost", label: t("debrief.col.cost"), kind: "num", cell: (bot) => (bot.cost_usd === null ? "—" : t("debrief.cost", { cost: bot.cost_usd.toFixed(2) })) },
    { key: "turns", label: t("debrief.col.turns"), kind: "num", cell: (bot) => (bot.turns === null ? "—" : count(bot.turns)) },
    { key: "refusals", label: t("debrief.col.refusals"), kind: "num", cell: (bot) => count(bot.refusals) },
  ];
  return (
    <Task title={t("debrief.bots")}>
      <Table columns={columns} rows={bots} rowKey={(bot) => bot.side} empty={t("debrief.no_bot")} />
    </Task>
  );
}

function AttackCard({ card }: { card: CardShown }) {
  return (
    <Card pad="md">
      <CardHead title={t("debrief.card")} meta={<Text mono>{card.technique}</Text>}
        actions={<Button tone="link" small href={card.url} external>{t("debrief.card_link")}</Button>} />
      <Stack gap="sm">
        <Text tone="muted" small>{t("debrief.card_lead")}</Text>
        <Text strong tone="heading">{`${card.technique} ${card.name}`}</Text>
        <Prose>{card.quote}</Prose>
        <Text tiny tone="faint">{t("debrief.card_version", { release: card.release, version: card.object_version })}</Text>
        <Text tiny tone="faint">{hasString(card.notice) ? t(card.notice) : card.notice}</Text>
      </Stack>
    </Card>
  );
}

function Closing({ bots }: { bots: BotLine[] }) {
  if (!bots.length) return null;
  return (
    <Card pad="md">
      <CardHead title={t("debrief.closing")} />
      <Stack gap="sm">
        <Text tone="muted" small>{t("debrief.closing_lead")}</Text>
        {bots.map((bot) => (
          <Stack key={bot.side} gap="sm">
            <Text strong small>{`${tFor("side", bot.side)} · ${stepName(bot.step)}`}</Text>
            {bot.closing.trim() ? <Code wrap>{bot.closing}</Code> : <Text tone="faint">{t("debrief.closing_none")}</Text>}
          </Stack>
        ))}
      </Stack>
    </Card>
  );
}

export function DebriefReport({ debrief }: { debrief: DebriefShown }) {
  const bots = debrief.bots as BotLine[];
  const rows = debrief.timeline as TimelineRow[];
  const marks = debrief.objectives as ObjectiveMark[];
  return (
    <Stack gap="lg">
      {debrief.pending && <Notice tone="warn">{t("debrief.pending")}</Notice>}
      {debrief.matchup !== "pvp" && <Bots bots={bots} />}
      {debrief.card && <AttackCard card={debrief.card} />}
      <Closing bots={bots} />
      <Timeline rows={rows} marks={marks} />
      {debrief.score ? (
        <Section title={t("debrief.score")}>
          <ScoreReport score={debrief.score as ScoreShown} />
        </Section>
      ) : null}
    </Stack>
  );
}

export function stepsLine(steps: Record<string, string | null | undefined>): string {
  return LANES.filter((side) => steps[side]).map((side) => `${tFor("side", side)} ${stepName(steps[side])}`).join(" · ");
}

export function Debrief({ params }: PageProps) {
  const round = Number(params.round);
  const shown = useResource("/api/rounds/{round_id}/debrief/", { params: { round_id: round } });
  const name = t("round.name", { round });
  const debrief = shown.data;
  const lead = debrief ? [[tFor("matchup", debrief.matchup), stepsLine(debrief.steps)].filter(Boolean).join(" · ")] : [];
  return (
    <AppPage title={t("page.debrief")} crumbs={[{ label: name, href: to.result(round) }, { label: t("page.debrief") }]}>
      <Hero icon="shield" title={`${t("page.debrief")} · ${name}`} lead={lead}
        actions={<Button tone="ghost" href={to.result(round)}>{t("result.crumb")}</Button>} />
      <PageBody>
        {shown.error?.has("round_running") && <Notice tone="warn">{t("debrief.running")}</Notice>}
        {shown.error && !shown.error.has("round_running") && <ErrorNotice error={shown.error} />}
        {!debrief && !shown.error && <Loading>{t("common.loading")}</Loading>}
        {debrief && <DebriefReport debrief={debrief} />}
      </PageBody>
    </AppPage>
  );
}
