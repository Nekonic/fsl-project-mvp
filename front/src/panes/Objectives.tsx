import { useEffect } from "preact/hooks";
import { useResource } from "../api/hooks";
import { errorText, t } from "../strings";
import { AsideCard, AsideHead, Badge, Badges, ErrorNotice, Loading, Pane, RowLine, Stack, Text } from "../ui";
import type { PaneProps, Side } from "./types";

export interface ObjectiveShown {
  key: string;
  name: string;
  state: "kept" | "lost";
  seen?: boolean;
}

const STATE_PATH = {
  attack: "/api/rounds/{round_id}/attack/state/",
  defence: "/api/rounds/{round_id}/defence/state/",
} as const;

const CHANGING_EVENTS = ["objective.lost", "round.started", "round.ended"];

const objectiveReaders = new Set<(round: number) => void>();

export function objectivesChanged(round: number): void {
  objectiveReaders.forEach((reader) => reader(round));
}

export function useObjectives(round: number, side: Side) {
  const state = useResource(STATE_PATH[side], { params: { round_id: round } }, { refreshOn: { round, kinds: CHANGING_EVENTS } });
  const { reload } = state;
  useEffect(() => {
    const reader = (changed: number) => {
      if (changed === round) reload();
    };
    objectiveReaders.add(reader);
    return () => {
      objectiveReaders.delete(reader);
    };
  }, [round, reload]);
  const objectives: ObjectiveShown[] = state.data?.objectives ?? [];
  return { objectives, error: state.error, loading: state.loading && !state.data };
}

function ObjectiveBadges({ objective }: { objective: ObjectiveShown }) {
  return (
    <Badges>
      {objective.state === "lost" ? <Badge tone="danger">{t("objective.lost")}</Badge> : <Badge>{t("objective.kept")}</Badge>}
      {objective.state === "lost" && objective.seen !== undefined && (
        objective.seen ? <Badge tone="info">{t("objective.seen")}</Badge> : <Badge tone="muted">{t("objective.unseen")}</Badge>
      )}
    </Badges>
  );
}

function ObjectiveCard({ objective }: { objective: ObjectiveShown }) {
  return (
    <AsideCard title={objective.name} lost={objective.state === "lost"}>
      <Text mono tiny tone="faint">{objective.key}</Text>
      <ObjectiveBadges objective={objective} />
    </AsideCard>
  );
}

export function Objectives({ round, side, placement }: PaneProps) {
  const { objectives, error, loading } = useObjectives(round, side);
  const lost = objectives.filter((objective) => objective.state === "lost").length;
  const tally = t("objective.tally", { lost, total: objectives.length });
  const body = loading ? <Loading>{t("common.loading")}</Loading> : error ? <ErrorNotice error={error} /> : null;

  if (placement === "aside") {
    return (
      <AsideCard title={t("pane.objectives")} meta={tally}>
        {body ?? objectives.map((objective) => (
          <RowLine key={objective.key}>
            <span>{objective.name}</span>
            {objective.state === "lost" ? <Badge tone="danger">{t("objective.lost")}</Badge> : <Badge tone="muted">{t("objective.kept")}</Badge>}
          </RowLine>
        ))}
      </AsideCard>
    );
  }
  if (placement === "aside-lead") {
    return (
      <>
        <AsideHead title={t("pane.objectives")} value={tally} />
        {body ?? objectives.map((objective) => <ObjectiveCard key={objective.key} objective={objective} />)}
      </>
    );
  }
  return (
    <Pane title={t("pane.objectives")} meta={tally}>
      {body ?? (error ? errorText(error) : <Stack gap="sm">{objectives.map((objective) => <ObjectiveCard key={objective.key} objective={objective} />)}</Stack>)}
    </Pane>
  );
}
