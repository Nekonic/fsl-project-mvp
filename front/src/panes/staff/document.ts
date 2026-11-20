import type { Schemas } from "../../api/client";
import { errorLine, type ShownError } from "../../strings";

export type StoredDocument = Schemas["StoredDocument"];
export type DocumentBody = Schemas["DocumentRequest"];
export type ProblemBody = Schemas["ProblemFieldsRequest"];
export type StepBody = Schemas["StaffStepRequest"];
export type SetupBody = Schemas["RoundSetupRequest"];
export type InlinePosture = Schemas["InlinePostureRequest"];
export type Posture = Schemas["Posture"];
export type PostureBody = Schemas["PostureRequest"];
export type WafTuning = Schemas["WafPostureRequest"];
export type Exclusion = Schemas["ExclusionRequest"];
export type Opens = Schemas["OpensEnum"];
export type Matchup = Schemas["MatchupEnum"];
export type ProblemKind = Schemas["ProblemKindEnum"];
export type ProblemSide = Schemas["ProblemSideEnum"];

export const CHECK_KINDS = ["answer", "choice", "loot", "rule_test", "rule_applied", "alert_seen", "sent", "kali", "waf_changed"];
export const OPENS: Opens[] = ["kibana", "terminal_kali", "terminal_waf", "site", "map", "ids_rules", "waf", "alerts", "none"];
export const MATCHUPS: Matchup[] = ["pvp", "def_vs_bot", "atk_vs_bot"];
export const KINDS: ProblemKind[] = ["lesson", "round"];
export const SIDES: ProblemSide[] = ["attack", "defence", "both"];
export const PARANOIA_LEVELS = [1, 2, 3, 4];
export const HP_FIELDS = ["budget", "per_request", "refused_x", "burst_per_s", "burst_x"] as const;
export const ANSWERED_KINDS = ["answer", "choice"];

export interface StepDraft {
  body: string;
  opens: Opens;
  kind: string;
  paramsText: string;
  answer: unknown;
  hints: string[];
}

export interface Draft {
  problem: ProblemBody;
  steps: StepDraft[];
  round: SetupBody | null;
  start_posture: InlinePosture | null;
}

export const DEFAULT_HP = { budget: 3000, per_request: 1, refused_x: 3, burst_per_s: 10, burst_x: 2 };

export function blankSetup(): SetupBody {
  return { matchups: ["pvp"], probe_cases: [], objectives: [], hp: { ...DEFAULT_HP }, benign_every_s: 60, time_limit_s: 1800 };
}

export function blankStep(): StepDraft {
  return { body: "", opens: "none", kind: "answer", paramsText: "{}", answer: undefined, hints: [] };
}

export function blankDraft(wargame: string): Draft {
  return {
    problem: { kind: "lesson", wargame, side: "defence", title: "", summary: "", body: "", published: false },
    steps: [blankStep()],
    round: null,
    start_posture: null,
  };
}

function paramsText(params: Record<string, unknown>): string {
  return JSON.stringify(params);
}

export function draftOf(stored: StoredDocument): Draft {
  const { kind, wargame, side, title, summary, body, published } = stored.problem;
  return {
    problem: { kind, wargame, side, title, summary, body, published },
    steps: (stored.steps ?? []).slice().sort((one, two) => one.order - two.order).map((step) => ({
      body: step.body,
      opens: step.opens,
      kind: step.check.kind,
      paramsText: paramsText(step.check.params),
      answer: step.answer,
      hints: step.hints ?? [],
    })),
    round: stored.round ? { ...stored.round, hp: { ...stored.round.hp } } : null,
    start_posture: stored.start_posture ?? null,
  };
}

function parsedParams(text: string): Record<string, unknown> | null {
  try {
    const value: unknown = JSON.parse(text.trim() || "{}");
    return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

export interface Built {
  body: DocumentBody;
  errors: ShownError[];
}

export function built(draft: Draft): Built {
  const errors: ShownError[] = [];
  const steps: StepBody[] = draft.steps.map((step, index) => {
    const params = parsedParams(step.paramsText);
    if (params === null) errors.push({ path: `steps[${index}].check.params`, code: "malformed" });
    const shaped: StepBody = { order: index + 1, body: step.body, opens: step.opens, check: { kind: step.kind, params: params ?? {} }, hints: step.hints.filter((hint) => hint.trim()) };
    if (step.answer !== undefined) shaped.answer = step.answer;
    return shaped;
  });
  return { body: { problem: draft.problem, steps, round: draft.round, start_posture: draft.start_posture }, errors };
}

export function stepTitle(step: StepDraft): string {
  return step.body.split("\n")[0]?.trim() ?? "";
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

export function tuningOf(posture: { crs_tuning: Record<string, unknown> }): WafTuning {
  const tuning = posture.crs_tuning as Partial<WafTuning>;
  return {
    paranoia: typeof tuning.paranoia === "number" ? tuning.paranoia : 1,
    exclusions: Array.isArray(tuning.exclusions) ? tuning.exclusions : [],
    thresholds: tuning.thresholds ?? {},
    detection_only: tuning.detection_only ?? false,
  };
}

export function ruleCount(rules: string): number {
  return rules.split("\n").filter((line) => line.trim() && !line.trim().startsWith("#")).length;
}

export function postureInline(posture: Posture): InlinePosture {
  return { name: posture.name, suricata_rules: posture.suricata_rules, crs_tuning: posture.crs_tuning };
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
