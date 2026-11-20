import type { ComponentChildren } from "preact";
import { useResource } from "../api/hooks";
import type { Schemas } from "../api/client";
import { count } from "../format";
import { to } from "../links";
import { t, tFor } from "../strings";
import {
  Button, Columns, Divided, ErrorNotice, FootRow, Loading, Notice, Stack, Table, Task, Text, type Column, type TextTone,
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
  seen: boolean;
}

const SCORE_EVENTS = ["round.ended"];

const VERDICT_TONE: Record<Verdict, TextTone> = { tp: "ok", tn: "ok", fn: "danger", fp: "danger" };

const VERDICT_ORDER: Verdict[] = ["tp", "fn", "fp", "tn"];

const ATTACK_VERDICTS: Verdict[] = ["tp", "fn"];

function isAttackCase(line: CaseLine): boolean {
  return ATTACK_VERDICTS.includes(line.verdict);
}

function pointsFor(objective: ObjectiveLine): number {
  if (!objective.lost) return 0;
  return objective.seen ? 1 : 2;
}

function objectiveLines(score: ScoreShown): ObjectiveLine[] {
  return [
    ...score.objectives.lost.map((objective) => ({ key: objective.key, name: objective.name, lost: true, seen: objective.seen })),
    ...score.objectives.kept.map((objective) => ({ key: objective.key, name: objective.name, lost: false, seen: false })),
  ];
}

function ObjectiveOutcome({ objective }: { objective: ObjectiveLine }) {
  if (!objective.lost) return <Text tone="ok">{t("objective.kept")}</Text>;
  return <Text tone="danger">{[t("objective.lost"), t(objective.seen ? "objective.seen" : "objective.unseen")].join(" · ")}</Text>;
}

function LostObjectives({ score }: { score: ScoreShown }) {
  const lines = objectiveLines(score);
  const lost = score.objectives.lost.length;
  const columns: Column<ObjectiveLine>[] = [
    { key: "name", label: t("result.objective"), kind: "strong", cell: (line) => line.name, title: (line) => line.key },
    { key: "outcome", label: t("result.outcome"), cell: (line) => <ObjectiveOutcome objective={line} /> },
    { key: "points", label: t("result.points"), kind: "end", cell: (line) => pointsFor(line) },
  ];
  return (
    <Task
      title={t("result.objectives_title")}
      side={<Text tone={lost ? "danger" : "ok"} strong>{t("result.lost_tally", { lost, total: lines.length })}</Text>}
      foot={t("result.objectives_note")}
    >
      <Table
        columns={columns}
        rows={lines}
        rowKey={(line) => line.key}
        empty={t("result.no_objectives")}
        foot={<FootRow span={2} label={t("result.objective_points_total")} value={count(score.objectives.weighted)} />}
      />
    </Task>
  );
}

function CaseNamed({ name, suffix }: { name: string; suffix: string }) {
  return <Text tone="danger"><Text mono>{name}</Text>{suffix}</Text>;
}

function SummaryBlock({ headline, children }: { headline: ComponentChildren; children?: ComponentChildren }) {
  return (
    <Stack gap="sm">
      <Text tone="heading" strong>{headline}</Text>
      {children}
    </Stack>
  );
}

function DetectionSummary({ score }: { score: ScoreShown }) {
  const { totals, per_case: cases } = score.outcomes;
  const attackTotal = totals.tp + totals.fn;
  const benignTotal = totals.fp + totals.tn;
  const missed = cases.filter((line) => line.verdict === "fn");
  const falseAlarms = cases.filter((line) => line.verdict === "fp");
  const totalsLine = VERDICT_ORDER.map((verdict) => `${tFor("verdict", verdict)} ${count(totals[verdict])}`).join(" · ");
  return (
    <Task title={t("result.detection_title")}>
      <Divided>
        <SummaryBlock headline={attackTotal ? t("result.attack_summary", { total: attackTotal, tp: totals.tp }) : t("result.no_attack_cases")}>
          {missed.map((line) => <CaseNamed key={line.case} name={line.case} suffix={t("result.missed_suffix")} />)}
        </SummaryBlock>
        <SummaryBlock
          headline={!benignTotal
            ? t("result.no_benign_cases")
            : totals.fp
              ? t("result.benign_summary", { total: benignTotal, fp: totals.fp })
              : t("result.benign_all_passed", { total: benignTotal })}
        >
          {falseAlarms.map((line) => <CaseNamed key={line.case} name={line.case} suffix={t("result.false_alarm_suffix")} />)}
        </SummaryBlock>
        <Stack gap="sm"><Text tone="muted">{totalsLine}</Text></Stack>
      </Divided>
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
    <Task title={t("result.cases_title")} foot={tFor("result.note", score.outcomes.note)}>
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
    <Task title={t("result.free_title")} side={<Text tone="muted" small>{t("result.free_unscored")}</Text>}>
      <Table columns={columns} rows={score.free_actions.by_origin} rowKey={(origin) => origin.ip} empty={t("result.no_free_actions")} />
    </Task>
  );
}

export function ScoreReport({ score }: { score: ScoreShown }) {
  return (
    <Stack gap="sm">
      {score.posture_drift && <Notice tone="warn" title={t("result.posture_drift")} />}
      <Columns shape="main-side">
        <LostObjectives score={score} />
        <DetectionSummary score={score} />
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
        action={<Button tone="ghost" small href={to.seat(round, side)}>{t(side === "attack" ? "page.attack" : "page.defence")}</Button>}
      >
        {t("error.round_running")}
      </Notice>
    );
  }
  if (score.error) return <ErrorNotice error={score.error} />;
  if (!score.data) return <Loading>{t("common.loading")}</Loading>;
  return <ScoreReport score={score.data} />;
}
