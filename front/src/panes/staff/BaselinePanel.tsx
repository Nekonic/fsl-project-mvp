import { useState } from "preact/hooks";
import { api, ApiError, type Schemas } from "../../api/client";
import { useResource } from "../../api/hooks";
import { count } from "../../format";
import { t, tFor } from "../../strings";
import { Badge, Button, EditorBand, ErrorNotice, Row, Stack, Table, Text, type BadgeTone, type Column } from "../../ui";
import type { SetupBody } from "./document";

type BaselineLine = Schemas["BaselineLine"];
type HumanSide = BaselineLine["human_side"];

const HUMAN_SIDE_OF: Record<string, HumanSide> = { def_vs_bot: "defence", atk_vs_bot: "attack" };
const HELD = ["current", "running"];
const STATUS_TONE: Record<BaselineLine["status"], BadgeTone> = { running: "warn", current: "ok", stale: "muted", failed: "danger" };

export function wantedBaselines(setup: SetupBody | null | undefined): Array<{ human_side: HumanSide; step: string }> {
  if (!setup) return [];
  const sides = [...new Set(setup.matchups.map((matchup) => HUMAN_SIDE_OF[matchup]).filter((side): side is HumanSide => Boolean(side)))].sort();
  return sides.flatMap((human_side) => (setup.bot_steps ?? []).map((step) => ({ human_side, step })));
}

function spreadText(line: BaselineLine): string {
  const { low, median, high } = line.spread;
  return low === null || median === null || high === null ? "—" : `${count(low)} · ${count(median)} · ${count(high)}`;
}

export interface BaselinePanelProps {
  problemId: number | null;
  saved: SetupBody | null | undefined;
}

export function BaselinePanel({ problemId, saved }: BaselinePanelProps) {
  const lines = useResource("/api/problems/{problem_id}/baselines/", problemId ? { params: { problem_id: problemId } } : null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<ApiError | undefined>(undefined);

  if (!problemId) {
    return <EditorBand title={t("staff.baseline.title")}><Text tone="muted" small>{t("staff.baseline.save_first")}</Text></EditorBand>;
  }

  const held = lines.data ?? [];
  const wanted = wantedBaselines(saved);
  const missing = wanted.filter((pair) => !held.some((line) => line.human_side === pair.human_side && line.step === pair.step && HELD.includes(line.status)));

  const runAll = async () => {
    setBusy(true);
    setFailed(undefined);
    try {
      for (const pair of missing) {
        await api.post("/api/problems/{problem_id}/baselines/", { params: { problem_id: problemId }, body: { ...pair, rounds: 20 } });
      }
    } catch (refused) {
      if (refused instanceof ApiError) setFailed(refused);
    } finally {
      setBusy(false);
      lines.reload();
    }
  };

  const columns: Column<BaselineLine>[] = [
    { key: "side", label: t("staff.baseline.col.side"), kind: "nowrap", cell: (line) => tFor("side", line.human_side) },
    { key: "step", label: t("staff.baseline.col.step"), kind: "nowrap", cell: (line) => tFor("bot_step", line.step) },
    { key: "status", label: t("staff.baseline.col.status"), cell: (line) => <Badge tone={STATUS_TONE[line.status]}>{tFor("baseline_status", line.status)}</Badge> },
    {
      key: "progress", label: t("staff.baseline.col.progress"), kind: "nowrap",
      cell: (line) => t("staff.baseline.progress", { counted: line.counted, wanted: line.wanted, attempted: line.attempted, max: line.attempts_max }),
    },
    { key: "spread", label: t("staff.baseline.col.spread"), kind: "mono", cell: spreadText },
  ];

  const state = !wanted.length ? t("staff.baseline.none_wanted") : missing.length ? t("staff.baseline.missing", { count: missing.length }) : t("staff.baseline.all_current");

  return (
    <EditorBand title={t("staff.baseline.title")}>
      <Stack gap="sm">
        <Text tone="muted" small>{t("staff.baseline.lead")}</Text>
        <Row>
          <Text small strong>{state}</Text>
          {missing.length > 0 && <Button small tone="primary" busy={busy} onClick={() => void runAll()}>{t("staff.baseline.run")}</Button>}
        </Row>
        {failed && <ErrorNotice error={failed} />}
        {lines.error && <ErrorNotice error={lines.error} />}
        <Table columns={columns} rows={held} rowKey={(line) => line.baseline} variant="compact" empty={t("staff.baseline.none")} />
      </Stack>
    </EditorBand>
  );
}
