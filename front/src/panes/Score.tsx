import type { ComponentChild } from "preact";
import { useResource } from "../api/hooks";
import type { Schemas } from "../api/client";
import { caseLabel, count } from "../format";
import { to } from "../links";
import { t, tFor } from "../strings";
import {
  Button, Columns, ErrorNotice, Loading, Notice, Stack, Table, Task, Text, type Column, type TextTone,
} from "../ui";
import type { PaneProps } from "./types";

type ScoreShown = Schemas["Score"];
type CaseLine = Schemas["CaseLine"];
type Verdict = CaseLine["verdict"];
type OriginActivity = Schemas["OriginActivity"];

interface ObjectiveLine {
  key: string;
  name: string;
  difficulty: number;
  lost: boolean;
  detected: boolean;
  responded: boolean;
  responseSeconds: number | null;
}

const SCORE_EVENTS = ["round.ended", "round.judged"];

const VERDICT_TONE: Record<Verdict, TextTone> = { tp: "ok", tn: "ok", fn: "danger", fp: "danger" };

const VERDICT_ORDER: Verdict[] = ["tp", "fn", "fp", "tn"];

const ATTACK_VERDICTS: Verdict[] = ["tp", "fn"];

const RESPONDED_SHARE = 0.5;

function isAttackCase(line: CaseLine): boolean {
  return ATTACK_VERDICTS.includes(line.verdict);
}

function objectiveLines(score: ScoreShown): ObjectiveLine[] {
  return [
    ...score.objectives.lost.map((objective) => ({
      key: objective.key, name: objective.name, difficulty: objective.difficulty, lost: true, detected: objective.detected, responded: objective.responded,
      responseSeconds: objective.response_seconds,
    })),
    ...score.objectives.kept.map((objective) => ({
      key: objective.key, name: objective.name, difficulty: objective.difficulty, lost: false, detected: false, responded: false, responseSeconds: null,
    })),
  ];
}

function Mark({ on, tone }: { on: boolean; tone: TextTone }) {
  return <Text tone={on ? tone : "muted"} strong>{t(on ? "mark.yes" : "mark.no")}</Text>;
}

function Undecided() {
  return <Text tone="warn">{t("mark.pending")}</Text>;
}

function Faint() {
  return <Text tone="faint">—</Text>;
}

function Taken({ lost }: { lost: boolean }) {
  return lost ? <Text tone="danger" strong>{t("objective.lost")}</Text> : <Text tone="muted">{t("objective.kept")}</Text>;
}

function Weight({ line }: { line: ObjectiveLine }) {
  return line.responded
    ? <Text tone="ok">{t("result.weight_half", { points: count(line.difficulty * RESPONDED_SHARE) })}</Text>
    : <Text tone="danger">{t("result.weight_full", { points: count(line.difficulty) })}</Text>;
}

function Objectives({ score }: { score: ScoreShown }) {
  const { pending } = score;
  const judged = (line: ObjectiveLine, shown: () => ComponentChild) => {
    if (!line.lost) return <Faint />;
    return pending ? <Undecided /> : shown();
  };
  const columns: Column<ObjectiveLine>[] = [
    { key: "name", label: t("result.objective"), kind: "strong", cell: (line) => line.name, title: (line) => line.key },
    { key: "difficulty", label: t("result.difficulty"), kind: "num", cell: (line) => count(line.difficulty) },
    { key: "lost", label: t("result.achieved"), kind: "nowrap", cell: (line) => <Taken lost={line.lost} /> },
    { key: "detected", label: t("result.detected"), kind: "nowrap", cell: (line) => judged(line, () => <Mark on={line.detected} tone="ok" />) },
    { key: "responded", label: t("result.responded"), kind: "nowrap", cell: (line) => judged(line, () => <Mark on={line.responded} tone="ok" />) },
    { key: "weight", label: t("result.weight"), kind: "nowrap", cell: (line) => judged(line, () => <Weight line={line} />) },
    {
      key: "response", label: t("result.response_time"), kind: "num",
      cell: (line) => (pending || line.responseSeconds === null ? <Faint /> : t("result.seconds", { seconds: count(Math.round(line.responseSeconds)) })),
    },
  ];
  return (
    <Task title={t("result.objectives_title")} side={<Text strong>{t(pending ? "result.objective_points_pending" : "result.objective_points", { points: count(score.objectives.weighted) })}</Text>}>
      <Stack gap="sm">
        <Table columns={columns} rows={objectiveLines(score)} rowKey={(line) => line.key} empty={t("result.no_objectives")} />
        <Text tone="muted" small>{t("result.objective_points_rule")}</Text>
      </Stack>
    </Task>
  );
}

function DetectionTotals({ score }: { score: ScoreShown }) {
  const { totals } = score.outcomes;
  return (
    <Task title={t("result.detection_title")}>
      <Text strong>{VERDICT_ORDER.map((verdict) => `${tFor("verdict", verdict)} ${count(totals[verdict])}`).join(" · ")}</Text>
    </Task>
  );
}

export interface CaseGroup {
  case: string;
  title: string;
  attack: boolean;
  firings: number;
  verdicts: Array<{ verdict: Verdict; firings: number }>;
  alerts: number;
  corroborated: boolean | null;
}

export function caseGroups(lines: CaseLine[]): CaseGroup[] {
  const byCase = new Map<string, CaseLine[]>();
  for (const line of lines) byCase.set(line.case, [...(byCase.get(line.case) ?? []), line]);
  const groups = [...byCase.entries()].map(([name, held]): CaseGroup => {
    const detected = held.filter((line) => line.verdict === "tp" && line.corroborated !== null);
    return {
      case: name,
      title: caseLabel({ case: name, title: held.map((line) => (line as { title?: string | null }).title).find(Boolean) }),
      attack: held.some(isAttackCase),
      firings: held.length,
      verdicts: VERDICT_ORDER.map((verdict) => ({ verdict, firings: held.filter((line) => line.verdict === verdict).length }))
        .filter((one) => one.firings > 0),
      alerts: held.reduce((sum, line) => sum + line.alerts, 0),
      corroborated: detected.length ? detected.every((line) => line.corroborated) : null,
    };
  });
  return groups.sort((one, other) => Number(other.attack) - Number(one.attack));
}

function VerdictCell({ group }: { group: CaseGroup }) {
  return (
    <Stack gap="sm">
      {group.verdicts.map((one) => (
        <Text key={one.verdict} tone={VERDICT_TONE[one.verdict]}>
          {group.firings > 1 ? t("result.verdict_times", { verdict: tFor("verdict", one.verdict), count: count(one.firings) }) : tFor("verdict", one.verdict)}
        </Text>
      ))}
      {group.alerts > 0 && <Text tone="muted" small>{t("result.alerts", { count: count(group.alerts) })}</Text>}
    </Stack>
  );
}

function CorroboratedCell({ group }: { group: CaseGroup }) {
  if (group.corroborated === null) return <Faint />;
  return group.corroborated ? <>{t("corroborated.yes")}</> : <Text tone="warn">{t("corroborated.no")}</Text>;
}

function CaseOutcomes({ score }: { score: ScoreShown }) {
  const columns: Column<CaseGroup>[] = [
    { key: "case", label: t("col.case"), kind: "key", cell: (group) => group.title },
    { key: "kind", label: t("col.case_kind"), kind: "nowrap", cell: (group) => t(group.attack ? "case_kind.attack" : "case_kind.benign") },
    { key: "firings", label: t("result.firings"), kind: "num", cell: (group) => count(group.firings) },
    { key: "verdict", label: t("col.verdict"), kind: "nowrap", cell: (group) => <VerdictCell group={group} /> },
    { key: "corroborated", label: t("col.corroborated"), kind: "nowrap", cell: (group) => <CorroboratedCell group={group} /> },
  ];
  return (
    <Task title={t("result.cases_title")}>
      <Table columns={columns} rows={caseGroups(score.outcomes.per_case)} rowKey={(group) => group.case} empty={t("result.no_cases")} />
    </Task>
  );
}

function FreeActions({ score }: { score: ScoreShown }) {
  const columns: Column<OriginActivity>[] = [
    { key: "ip", label: t("col.origin_ip"), kind: "mono", cell: (origin) => <Text tone="heading" mono>{origin.ip}</Text> },
    { key: "actions", label: t("result.actions"), kind: "num", cell: (origin) => count(origin.actions) },
    { key: "alerts", label: t("col.alerts"), kind: "num", cell: (origin) => count(origin.alerts) },
    { key: "refused", label: t("result.refused_alerts"), kind: "num", cell: (origin) => count(origin.refused) },
  ];
  return (
    <Task title={t("result.free_title")}>
      <Stack gap="sm">
        <Text tone="muted" small>{t("result.free_lead")}</Text>
        <Table columns={columns} rows={score.free_actions.by_origin} rowKey={(origin) => origin.ip} empty={t("result.no_free_actions")} />
      </Stack>
    </Task>
  );
}

export function ScoreReport({ score }: { score: ScoreShown }) {
  return (
    <Stack gap="sm">
      {score.pending && <Notice tone="warn">{t("score.pending")}</Notice>}
      <Columns shape="main-side">
        <Objectives score={score} />
        <DetectionTotals score={score} />
      </Columns>
      <CaseOutcomes score={score} />
      <FreeActions score={score} />
    </Stack>
  );
}

export function Score({ round, side }: PaneProps) {
  const score = useResource("/api/rounds/{round_id}/score/", { params: { round_id: round } }, { refreshOn: { round, kinds: SCORE_EVENTS } });
  if (score.error?.has("round_running")) {
    return (
      <Notice
        tone="danger"
        action={<Button tone="ghost" small href={to.player(round, side)}>{t(side === "attack" ? "page.attack" : "page.defence")}</Button>}
      >
        {t("error.round_running")}
      </Notice>
    );
  }
  if (score.error) return <ErrorNotice error={score.error} />;
  if (!score.data) return <Loading>{t("common.loading")}</Loading>;
  return <ScoreReport score={score.data} />;
}
