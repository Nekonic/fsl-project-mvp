import type { Schemas } from "../api/client";
import { wargameName } from "./wargameText";

type Problem = Schemas["LearnerProblemSummary"];

const BOT_MATCHUPS = ["def_vs_bot", "atk_vs_bot"];

export function botRoundProblems(problems: Problem[]): Problem[] {
  return problems.filter((problem) => problem.matchups.some((one) => BOT_MATCHUPS.includes(one)));
}

export function roundTitle(line: { problem_title: string | null; wargame: string }): string {
  return line.problem_title ?? wargameName(line.wargame);
}
