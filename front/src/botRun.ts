import { t, tFor } from "./strings";

export interface BotRunLine {
  bot_run: string | null;
  stopped_early?: boolean | null;
}

export function withStoppedEarly(line: { stopped_early?: boolean | null }, state: string): string {
  return line.stopped_early === true ? `${state} · ${t("bot.stopped_early")}` : state;
}

export function botRunText(line: BotRunLine): string {
  return line.bot_run ? withStoppedEarly(line, tFor("bot_run", line.bot_run)) : "";
}
