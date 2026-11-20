import { useResource } from "../api/hooks";
import { errorText, t } from "../strings";
import { Frame, FrameEmpty, Pane } from "../ui";
import type { PaneProps } from "./types";

const KIBANA_ALREADY_SEEN: Record<string, string> = {
  "discover:docExplorerUpdateCalloutClosed": "true",
  "discover:docExplorerCalloutClosed": "true",
  "data.noDataPopover": "true",
};
const KIBANA_LEFT_FROM_BEFORE = ["discover:searchText"];

export function presetKibana(store: Storage | undefined = globalThis.localStorage): void {
  try {
    if (!store) return;
    Object.entries(KIBANA_ALREADY_SEEN).forEach(([key, value]) => store.setItem(key, value));
    KIBANA_LEFT_FROM_BEFORE.forEach((key) => store.removeItem(key));
  } catch {
    return;
  }
}

export function Kibana({ round }: PaneProps) {
  const space = useResource("/api/rounds/{round_id}/defence/kibana/", { params: { round_id: round } }, { refreshOn: { round, kinds: ["round.started"] } });
  if (space.data) presetKibana();
  return (
    <Pane scroll={false}>
      {space.data
        ? <Frame src={space.data.space_url} title={t("pane.kibana")} />
        : <FrameEmpty title={t("pane.kibana")}>{space.error ? errorText(space.error) : t("common.loading")}</FrameEmpty>}
    </Pane>
  );
}
