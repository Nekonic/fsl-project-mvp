import { useResource } from "../api/hooks";
import { errorText, t } from "../strings";
import { Frame, FrameEmpty, Pane } from "../ui";
import type { PaneProps, Side } from "./types";

const TERMINAL_PATH = {
  attack: "/api/rounds/{round_id}/attack/terminal/",
  defence: "/api/rounds/{round_id}/defence/terminal/",
} as const;

const SHELL_ENDING_EVENTS = ["round.started", "round.ended"];

export interface TerminalProps {
  round: number;
  side: Side;
}

export function Terminal({ round, side }: TerminalProps) {
  const grant = useResource(TERMINAL_PATH[side], { params: { round_id: round } }, { refreshOn: { round, kinds: SHELL_ENDING_EVENTS } });
  const title = side === "attack" ? t("terminal.attack.title") : t("terminal.defence.title");
  return (
    <Pane dark scroll={false} title={title}>
      {grant.data
        ? <Frame dark src={grant.data.ws_url} title={title} />
        : <FrameEmpty dark>{grant.error ? errorText(grant.error) : t("common.loading")}</FrameEmpty>}
    </Pane>
  );
}

export function TerminalKali({ round }: PaneProps) {
  return <Terminal round={round} side="attack" />;
}

export function TerminalWaf({ round }: PaneProps) {
  return <Terminal round={round} side="defence" />;
}
