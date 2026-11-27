import { useResource } from "../api/hooks";
import { wargameLead, wargameName } from "../pages/wargameText";
import { t } from "../strings";
import { AsideFold, ErrorNotice, Loading, Pane, Prose, Stack, Text } from "../ui";
import type { PaneProps } from "./types";

export interface ProblemWords {
  title: string;
  summary: string;
  body: string;
}

const STATE_PATH = {
  attack: "/api/rounds/{round_id}/attack/state/",
  defence: "/api/rounds/{round_id}/defence/state/",
} as const;

export function ProblemText({ problem }: { problem: ProblemWords }) {
  return (
    <Stack gap="sm">
      {problem.summary && <Text strong tone="heading">{problem.summary}</Text>}
      {problem.body.trim() ? <Prose>{problem.body}</Prose> : <Text tone="muted" small>{t("brief.none")}</Text>}
    </Stack>
  );
}

export function Brief({ round, side, placement }: PaneProps) {
  const state = useResource(STATE_PATH[side], { params: { round_id: round } });
  const pvp = state.data?.matchup === "pvp";
  const detail = useResource("/api/rounds/{round_id}/", pvp ? { params: { round_id: round } } : null);
  const wargame = detail.data?.wargame;
  const brief = pvp
    ? (wargame ? { title: wargameName(wargame), summary: t("matchup.pvp"), body: [wargameLead(wargame), t("brief.pvp")].filter(Boolean).join("\n") } : undefined)
    : state.data?.brief;
  const error = state.error ?? detail.error;
  const shown = brief
    ? <ProblemText problem={brief} />
    : error ? <ErrorNotice error={error} /> : <Loading>{t("common.loading")}</Loading>;
  if (placement === "main") return <Pane title={t("pane.brief")} meta={brief?.title}>{shown}</Pane>;
  return <AsideFold title={t("pane.brief")} meta={brief?.title}>{shown}</AsideFold>;
}
