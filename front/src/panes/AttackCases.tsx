import { useAction, useResource } from "../api/hooks";
import type { Schemas } from "../api/client";
import { count } from "../format";
import { t } from "../strings";
import { AsideCard, Badge, Button, ErrorNotice, Loading, Pane, RowLine, Text } from "../ui";
import { attackWritesOpen, useAttackState } from "./Origins";
import type { PaneProps } from "./types";

type CaseEntry = Schemas["CaseEntry"];
type Fired = Schemas["Fired"];

const REFUSED_STATUSES = [400, 403];

function FiredBadge({ fired, refused }: { fired: Fired; refused: number[] }) {
  if (fired.run !== null) return <Badge tone="info">{t("cases.tool_started")}</Badge>;
  if (fired.status === null) return <Badge tone="muted">{t("cases.sent")}</Badge>;
  return <Badge mono tone={refused.includes(fired.status) ? "danger" : "ok"}>{fired.status}</Badge>;
}

function CaseRow({ entry, round, open, refused }: { entry: CaseEntry; round: number; open: boolean; refused: number[] }) {
  const fire = useAction("post", "/api/rounds/{round_id}/attack/cases/");
  return (
    <>
      <RowLine>
        <span>
          <Text mono tiny tone="heading" title={entry.title}>{entry.case}</Text>
          {fire.data && <> <FiredBadge fired={fire.data} refused={refused} /></>}
        </span>
        {entry.kind === "tool" && <Badge>{t("cases.kind.tool")}</Badge>}
        <Button small busy={fire.busy} disabled={!open} onClick={() => void fire.run({ params: { round_id: round }, body: { case: entry.case } })}>
          {t("cases.fire")}
        </Button>
      </RowLine>
      {fire.error && <ErrorNotice error={fire.error} />}
    </>
  );
}

export function AttackCases({ round, placement }: PaneProps) {
  const cases = useResource("/api/rounds/{round_id}/attack/cases/", { params: { round_id: round } });
  const state = useAttackState(round);
  const declared = (cases.data ?? []).filter((entry) => entry.malicious);
  const open = attackWritesOpen(state.data);

  const body = !cases.data
    ? cases.error ? <ErrorNotice error={cases.error} /> : <Loading>{t("common.loading")}</Loading>
    : declared.length === 0
      ? <Text tone="muted">{t("cases.none")}</Text>
      : declared.map((entry) => <CaseRow key={entry.case} entry={entry} round={round} open={open} refused={REFUSED_STATUSES} />);

  if (placement === "main") {
    return <Pane title={t("pane.cases")} meta={cases.data ? count(declared.length) : undefined}>{body}</Pane>;
  }
  return <AsideCard title={t("pane.cases")} meta={cases.data ? count(declared.length) : undefined}>{body}</AsideCard>;
}
