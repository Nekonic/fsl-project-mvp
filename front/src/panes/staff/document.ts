import type { Schemas } from "../../api/client";
import { errorLine, type ShownError } from "../../strings";

export type StoredDocument = Schemas["StoredDocument"];
export type DocumentBody = Schemas["DocumentRequest"];
export type ProblemBody = Schemas["ProblemFieldsRequest"];
export type SetupBody = Schemas["RoundSetupRequest"];
export type InlinePosture = Schemas["InlinePostureRequest"];
export type Posture = Schemas["Posture"];
export type PostureBody = Schemas["PostureRequest"];
export type Matchup = Schemas["MatchupsEnum"];
export type ProblemSide = Schemas["ProblemSideEnum"];

export const MATCHUPS: Matchup[] = ["pvp", "def_vs_bot", "atk_vs_bot"];
export const SIDES: ProblemSide[] = ["attack", "defence", "both"];

export interface Draft {
  problem: ProblemBody;
  round: SetupBody;
  start_posture: InlinePosture | null;
}

export function blankSetup(): SetupBody {
  return { matchups: ["pvp"], probe_cases: [], objectives: [], benign_every_s: 60, time_limit_s: 1800 };
}

export function blankDraft(wargame: string): Draft {
  return {
    problem: { kind: "round", wargame, side: "defence", title: "", summary: "", body: "", published: false },
    round: blankSetup(),
    start_posture: null,
  };
}

export function draftOf(stored: StoredDocument): Draft {
  const { kind, wargame, side, title, summary, body, published } = stored.problem;
  return {
    problem: { kind, wargame, side, title, summary, body, published },
    round: stored.round ? { ...stored.round } : blankSetup(),
    start_posture: stored.start_posture ?? null,
  };
}

export function built(draft: Draft): DocumentBody {
  return { problem: draft.problem, round: draft.round, start_posture: draft.start_posture };
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
