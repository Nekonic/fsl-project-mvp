import type { ComponentChildren } from "preact";
import { useState } from "preact/hooks";
import { useResource } from "../api/hooks";
import { errorText, t, type StringKey } from "../strings";
import { Button, Frame, FrameEmpty, Pane } from "../ui";
import type { PaneProps } from "./types";

const TERMINAL_PATH = {
  attack: "/api/rounds/{round_id}/attack/terminal/",
  waf: "/api/rounds/{round_id}/defence/terminal/",
  ids: "/api/rounds/{round_id}/defence/ids/terminal/",
} as const;

type Box = keyof typeof TERMINAL_PATH;
type DefenceBox = Exclude<Box, "attack">;

const TITLE: Record<Box, StringKey> = {
  attack: "terminal.attack.title",
  waf: "terminal.defence.title",
  ids: "terminal.ids.title",
};

const SWITCH: Record<DefenceBox, StringKey> = { waf: "terminal.switch.waf", ids: "terminal.switch.ids" };

const SHELL_ENDING_EVENTS = ["round.started", "round.ended"];

export interface TerminalProps {
  round: number;
  box: Box;
  actions?: ComponentChildren;
}

export function Terminal({ round, box, actions }: TerminalProps) {
  const grant = useResource(TERMINAL_PATH[box], { params: { round_id: round } }, { refreshOn: { round, kinds: SHELL_ENDING_EVENTS } });
  const title = t(TITLE[box]);
  return (
    <Pane dark scroll={false} title={title} actions={actions}>
      {grant.data
        ? <Frame dark src={grant.data.ws_url} title={title} />
        : <FrameEmpty dark>{grant.error ? errorText(grant.error) : t("common.loading")}</FrameEmpty>}
    </Pane>
  );
}

export function TerminalKali({ round }: PaneProps) {
  return <Terminal round={round} box="attack" />;
}

export function TerminalWaf({ round }: PaneProps) {
  const [box, setBox] = useState<DefenceBox>("waf");
  const actions = (Object.keys(SWITCH) as DefenceBox[]).map((one) => (
    <Button key={one} small tone={one === box ? "dark" : "ghost"} onClick={() => setBox(one)}>{t(SWITCH[one])}</Button>
  ));
  return <Terminal key={box} round={round} box={box} actions={actions} />;
}
