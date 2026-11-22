import { useResource } from "../api/hooks";
import type { Schemas } from "../api/client";
import { count } from "../format";
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
  lost: boolean;
  detected: boolean;
  responded: boolean;
  responseSeconds: number | null;
}

const SCORE_EVENTS = ["round.ended", "round.judged"];

const VERDICT_TONE: Record<Verdict, TextTone> = { tp: "ok", tn: "ok", fn: "danger", fp: "danger" };

const VERDICT_ORDER: Verdict[] = ["tp", "fn", "fp", "tn"];

const ATTACK_VERDICTS: Verdict[] = ["tp", "fn"];

function isAttackCase(line: CaseLine): boolean {
  return ATTACK_VERDICTS.includes(line.verdict);
}

function objectiveLines(score: ScoreShown): ObjectiveLine[] {
  return [
    ...score.objectives.lost.map((objective) => ({
      key: objective.key, name: objective.name, lost: true, detected: objective.detected, responded: objective.responded,
      responseSeconds: objective.response_seconds,
    })),
    ...score.objectives.kept.map((objective) => ({
      key: objective.key, name: objective.name, lost: false, detected: false, responded: false, responseSeconds: null,
    })),
  ];
}

function Mark({ on, tone }: { on: boolean; tone: TextTone }) {
  return <Text tone={on ? tone : "muted"} strong>{t(on ? "mark.yes" : "mark.no")}</Text>;
}

function Objectives({ score }: { score: ScoreShown }) {
  const columns: Column<ObjectiveLine>[] = [
    { key: "name", label: t("result.objective"), kind: "strong", cell: (line) => line.name, title: (line) => line.key },
    { key: "lost", label: t("result.achieved"), kind: "nowrap", cell: (line) => <Mark on={line.lost} tone="danger" /> },
    { key: "detected", label: t("result.detected"), kind: "nowrap", cell: (line) => (line.lost ? <Mark on={line.detected} tone="ok" /> : <Text tone="faint">—</Text>) },
    { key: "responded", label: t("result.responded"), kind: "nowrap", cell: (line) => (line.lost ? <Mark on={line.responded} tone="ok" /> : <Text tone="faint">—</Text>) },
    { key: "response", label: t("result.response_time"), kind: "num", cell: (line) => (line.responseSeconds === null ? <Text tone="faint">—</Text> : t("result.seconds", { seconds: count(Math.round(line.responseSeconds)) })) },
  ];
  return (
    <Task title={t("result.objectives_title")} side={<Text strong>{t("result.objective_points", { points: count(score.objectives.weighted) })}</Text>}>
      <Table columns={columns} rows={objectiveLines(score)} rowKey={(line) => line.key} empty={t("result.no_objectives")} />
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

function VerdictCell({ line }: { line: CaseLine }) {
  return (
    <Stack gap="sm">
      <Text tone={VERDICT_TONE[line.verdict]}>{tFor("verdict", line.verdict)}</Text>
      {line.alerts > 0 && <Text tone="muted" small>{t("result.alerts", { count: count(line.alerts) })}</Text>}
    </Stack>
  );
}

function CorroboratedCell({ line }: { line: CaseLine }) {
  if (line.corroborated === null || line.verdict !== "tp") return <Text tone="faint">—</Text>;
  return line.corroborated ? <>{t("corroborated.yes")}</> : <Text tone="warn">{t("corroborated.no")}</Text>;
}

function CaseOutcomes({ score }: { score: ScoreShown }) {
  const columns: Column<CaseLine>[] = [
    { key: "case", label: t("col.case"), kind: "key", cell: (line) => line.case },
    { key: "kind", label: t("col.case_kind"), kind: "nowrap", cell: (line) => t(isAttackCase(line) ? "case_kind.attack" : "case_kind.benign") },
    { key: "verdict", label: t("col.verdict"), kind: "nowrap", cell: (line) => <VerdictCell line={line} /> },
    { key: "corroborated", label: t("col.corroborated"), kind: "nowrap", cell: (line) => <CorroboratedCell line={line} /> },
  ];
  const ordered = [...score.outcomes.per_case].sort((one, other) => Number(isAttackCase(other)) - Number(isAttackCase(one)));
  return (
    <Task title={t("result.cases_title")}>
      <Table columns={columns} rows={ordered} rowKey={(line) => line.case} empty={t("result.no_cases")} />
    </Task>
  );
}

function FreeActions({ score }: { score: ScoreShown }) {
  const columns: Column<OriginActivity>[] = [
    { key: "ip", label: t("col.origin_ip"), kind: "mono", cell: (origin) => <Text tone="heading" mono>{origin.ip}</Text> },
    { key: "actions", label: t("result.actions"), kind: "num", cell: (origin) => count(origin.actions) },
    { key: "alerts", label: t("col.alerts"), kind: "num", cell: (origin) => count(origin.alerts) },
    { key: "refused", label: t("col.blocked"), kind: "num", cell: (origin) => count(origin.refused) },
  ];
  return (
    <Task title={t("result.free_title")}>
      <Table columns={columns} rows={score.free_actions.by_origin} rowKey={(origin) => origin.ip} empty={t("result.no_free_actions")} />
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
