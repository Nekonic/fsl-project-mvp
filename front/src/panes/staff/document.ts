import type { Schemas } from "../../api/client";
import { errorLine, t, type ShownError, type StringKey } from "../../strings";

export type StoredDocument = Schemas["StoredDocument"];
export type DocumentBody = Schemas["DocumentRequest"];
export type ProblemBody = Schemas["ProblemFieldsRequest"];
export type SetupBody = Schemas["RoundSetupRequest"];
export type InlinePosture = Schemas["InlinePostureRequest"];
export type Posture = Schemas["Posture"];
export type PostureBody = Schemas["PostureRequest"];
export type Matchup = Schemas["MatchupsEnum"];
export type ProblemSide = Schemas["ProblemSideEnum"];

export const MATCHUPS: Matchup[] = ["def_vs_bot", "atk_vs_bot"];
export const SIDES: ProblemSide[] = ["attack", "defence", "both"];

export interface Draft {
  problem: ProblemBody;
  round: SetupBody;
  start_posture: InlinePosture | null;
}

export function blankSetup(): SetupBody {
  return { matchups: ["def_vs_bot"], probe_cases: [], objectives: [], benign_every_s: 60, time_limit_s: 1800 };
}

export function blankDraft(wargame: string): Draft {
  return {
    problem: { wargame, side: "defence", title: "", summary: "", body: "", published: false },
    round: blankSetup(),
    start_posture: null,
  };
}

export function draftOf(stored: StoredDocument): Draft {
  const { wargame, side, title, summary, body, published } = stored.problem;
  return {
    problem: { wargame, side, title, summary, body, published },
    round: stored.round ? { ...stored.round } : blankSetup(),
    start_posture: stored.start_posture ?? null,
  };
}

export function built(draft: Draft): DocumentBody {
  return { problem: draft.problem, round: draft.round, start_posture: draft.start_posture };
}

const FIELD_NAMES: Array<[string, StringKey]> = [
  ["problem.wargame", "col.wargame"],
  ["problem.side", "staff.problem.side"],
  ["problem.title", "staff.problem.title"],
  ["problem.summary", "staff.problem.summary"],
  ["problem.body", "staff.problem.body"],
  ["problem.published", "staff.publish"],
  ["start_posture", "staff.problem.start_posture"],
  ["round.posture", "staff.problem.start_posture"],
  ["round.matchups", "staff.round.matchups"],
  ["round.bot_steps", "staff.round.bot_steps"],
  ["round.cards", "staff.round.cards"],
  ["round.probe_cases", "staff.round.probe_cases"],
  ["round.objectives", "staff.round.objectives"],
  ["round.benign_every_s", "staff.round.benign_every"],
  ["round.time_limit_s", "staff.round.time_limit"],
];

export function fieldName(path: string): string {
  const found = FIELD_NAMES.find(([prefix]) => path === prefix || path.startsWith(`${prefix}.`) || path.startsWith(`${prefix}[`));
  if (!found) return path;
  const [prefix, key] = found;
  const index = /^\[(\d+)\]/.exec(path.slice(prefix.length));
  return index ? t("staff.field.nth", { field: t(key), n: Number(index[1]) + 1 }) : t(key);
}

export function errorsUnder(errors: ShownError[], prefix: string): ShownError[] {
  return errors.filter((error) => error.path === prefix || error.path.startsWith(`${prefix}.`) || error.path.startsWith(`${prefix}[`));
}

export function textUnder(errors: ShownError[], prefix: string): string | undefined {
  const found = errorsUnder(errors, prefix);
  return found.length ? found.map(errorLine).join(" ") : undefined;
}

export function asShownErrors(errors: Array<Record<string, unknown>>): ShownError[] {
  return errors.map((error) => ({
    path: typeof error.path === "string" ? error.path : "",
    code: typeof error.code === "string" ? error.code : "invalid",
    line: typeof error.line === "number" ? error.line : undefined,
    params: error.params && typeof error.params === "object" ? (error.params as Record<string, unknown>) : undefined,
  }));
}

export function filledFiles(files: Record<string, string>): Record<string, string> {
  return Object.fromEntries(Object.entries(files).filter(([, text]) => text.trim() !== ""));
}

export function ruleCount(rules: string): number {
  return rules.split("\n").filter((line) => line.trim() && !line.trim().startsWith("#")).length;
}

export function postureInline(posture: Posture): InlinePosture {
  return { name: posture.name, suricata_rules: posture.suricata_rules, waf_files: posture.waf_files };
}

export function downloadJson(name: string, value: unknown): void {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }));
  link.download = name;
  link.click();
  URL.revokeObjectURL(link.href);
}

export function readJsonFile(file: File): Promise<unknown> {
  return file.text().then((text) => JSON.parse(text) as unknown);
}
