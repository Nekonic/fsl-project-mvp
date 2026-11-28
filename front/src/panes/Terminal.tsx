import type { ComponentChildren } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import { useResource } from "../api/hooks";
import { errorText, t, type StringKey } from "../strings";
import { Button, FrameEmpty, Pane } from "../ui";
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

export const TERMINAL_CHECK_EVERY_MS = 300;
export const TERMINAL_RETRY_AFTER_MS = 2_000;
export const TERMINAL_RETRIES = 5;
export const TERMINAL_GIVE_UP_MS = 30_000;

interface ShellWindow extends Window {
  term?: { buffer?: { active?: { length?: number; getLine?: (row: number) => { translateToString?: (trim?: boolean) => string } | undefined } } };
}

export type ShellState = "connecting" | "ready" | "refused";

export function shellStateOf(frame: HTMLIFrameElement | null): ShellState {
  const shown = frame?.contentWindow as ShellWindow | null | undefined;
  let page: Document | null | undefined;
  try {
    page = frame?.contentDocument;
  } catch {
    return "connecting";
  }
  if (!page || !page.body) return "connecting";
  if (!page.querySelector(".xterm")) {
    const gatewayPage = !page.querySelector("script");
    return gatewayPage && /\b5\d\d\b/.test(page.body.textContent ?? "") ? "refused" : "connecting";
  }
  const buffer = shown?.term?.buffer?.active;
  if (buffer?.getLine) {
    for (let row = 0; row < Math.min(buffer.length ?? 0, 200); row += 1) {
      if (buffer.getLine(row)?.translateToString?.(true).trim()) return "ready";
    }
    return "connecting";
  }
  const rows = page.querySelector(".xterm-rows, .xterm-accessibility");
  return rows && (rows.textContent ?? "").trim() ? "ready" : "connecting";
}

export function ShellFrame({ src, title }: { src: string; title: string }) {
  const frame = useRef<HTMLIFrameElement>(null);
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<ShellState>("connecting");
  const [gaveUp, setGaveUp] = useState(false);
  useEffect(() => {
    setState("connecting");
    setGaveUp(false);
    const began = Date.now();
    let retry: ReturnType<typeof setTimeout> | undefined;
    const timer = setInterval(() => {
      const now = shellStateOf(frame.current);
      if (now === "ready") {
        setState("ready");
        clearInterval(timer);
      } else if (now === "refused" && retry === undefined && attempt < TERMINAL_RETRIES) {
        retry = setTimeout(() => setAttempt((was) => was + 1), TERMINAL_RETRY_AFTER_MS);
        clearInterval(timer);
      } else if (Date.now() - began > TERMINAL_GIVE_UP_MS || (now === "refused" && attempt >= TERMINAL_RETRIES)) {
        setGaveUp(true);
        clearInterval(timer);
      }
    }, TERMINAL_CHECK_EVERY_MS);
    return () => {
      clearInterval(timer);
      if (retry !== undefined) clearTimeout(retry);
    };
  }, [src, attempt]);
  return (
    <div class="term-holder">
      <iframe key={attempt} ref={frame} class="term-frame" src={src} title={title} />
      {state !== "ready" && (
        <div class="term-connecting" role="status">
          {gaveUp
            ? <>{t("terminal.unreachable")} <Button small tone="ghost" onClick={() => setAttempt((was) => was + 1)}>{t("terminal.retry")}</Button></>
            : t("terminal.connecting")}
        </div>
      )}
    </div>
  );
}

export function Terminal({ round, box, actions }: TerminalProps) {
  const grant = useResource(TERMINAL_PATH[box], { params: { round_id: round } }, { refreshOn: { round, kinds: SHELL_ENDING_EVENTS } });
  const title = t(TITLE[box]);
  return (
    <Pane dark scroll={false} title={title} actions={actions}>
      {grant.data
        ? <ShellFrame src={grant.data.ws_url} title={title} />
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
