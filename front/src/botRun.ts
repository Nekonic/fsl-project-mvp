import { t, tFor } from "./strings";

export interface BotRunLine {
  bot_run: string | null;
  left_of_round_s?: number | null;
}

export function withStoppedEarly(line: { left_of_round_s?: number | null }, state: string): string {
  return typeof line.left_of_round_s === "number" ? `${state} · ${t("bot.stopped_early")}` : state;
}

export function botRunText(line: BotRunLine): string {
  return line.bot_run ? withStoppedEarly(line, tFor("bot_run", line.bot_run)) : "";
}
