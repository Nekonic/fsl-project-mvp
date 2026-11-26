import type { components } from "../../src/api/schema";
import { minutesFromNow, refuse, reply } from "../fixture";
import { score } from "./result";

const pace = (per_window: number, min_gap_s: number) => ({ per_window, window_s: 300, min_gap_s });
const play = (model: string, per_window: number, min_gap_s: number) => ({ model, family: model.split("-")[1] ?? model, pace: pace(per_window, min_gap_s) });

const steps = [
  { id: "1", label: "bot_step.1", attack: play("claude-haiku-5-5", 4, 45), defence: play("claude-haiku-5-5", 4, 45) },
  { id: "2", label: "bot_step.2", attack: play("claude-haiku-5-5", 10, 15), defence: play("claude-sonnet-5-5", 10, 15) },
  { id: "3", label: "bot_step.3", attack: play("claude-haiku-5-5", 30, 3), defence: play("claude-opus-5-5", 30, 3) },
];

const card = {
  id: "A3", technique: "T1190", name: "Exploit Public-Facing Application",
  quote: "Placeholder quote of the technique page.",
  url: "https://attack.mitre.org/versions/v20/techniques/T1190/", object_version: "2.7", release: "v20.1", notice: "mitre.copyright",
};

const timeline = [
  { lane: "attack", kind: "bot_note", at: minutesFromNow(-29), note: "text", text: "Placeholder: reading the events first." },
  { lane: "attack", kind: "case", at: minutesFromNow(-28), case: "board-sqli-search", origin: "5.188.10.10", alerts: 3 },
  { lane: "defence", kind: "alerts", at: minutesFromNow(-28), engine: "waf", signature: "SQL Injection Attack Detected via libinjection", count: 3, until: minutesFromNow(-27) },
  { lane: "defence", kind: "rule.tested", at: minutesFromNow(-24), test: 3, engine: "waf", ok: true, passed: true },
  { lane: "defence", kind: "rule.applied", at: minutesFromNow(-23), engine: "waf", version: 2, source: "console" },
  { lane: "attack", kind: "bot_note", at: minutesFromNow(-22), note: "refused", text: "pace_limited retry_after_s=31" },
  { lane: "attack", kind: "origin.spent", at: minutesFromNow(-21), ip: "5.188.10.10", by: "deny" },
  { lane: "attack", kind: "origin.switched", at: minutesFromNow(-21), ip: "181.8.0.10" },
  { lane: "attack", kind: "free_actions", at: minutesFromNow(-15), origin: "181.8.0.10", count: 12, until: minutesFromNow(-12), alerts: 0 },
  { lane: "both", kind: "objective.lost", at: minutesFromNow(-11), key: "board-auth-user-partial", name: "Board accounts, partial" },
];

const debrief = {
  round: 40, matchup: "def_vs_bot", pending: false, steps: { attack: "2", defence: null }, card,
  bots: [{ side: "attack", step: "2", model: "claude-haiku-5-5", status: "finished", exit: "success", cost_usd: 0.84, turns: 61, refusals: 0, closing: "Placeholder closing statement of the bot." }],
  objectives: [{ key: "board-auth-user-partial", name: "Board accounts, partial", detected: true, responded: true, response_seconds: 42.4 }],
  timeline, score,
};

const standing = { baseline: 3, step: "2", n: 20, top_percent: 35 };

const recordLine = (record: number, round: number, withStanding: boolean) => ({
  record, round_number: round, problem: 7, problem_title: "Board wargame", matchup: "def_vs_bot", steps: { attack: "2" }, started: minutesFromNow(-90 - record),
  ended: minutesFromNow(-60 - record), end_reason: "time_limit", incomplete: false, baseline: null, standing: withStanding ? standing : null,
});

const baselines: Array<components["schemas"]["BaselineLine"]> = [
  { baseline: 3, human_side: "defence" as const, step: "1", status: "current" as const, profile_key: "a1b2c3", counted: 20, wanted: 20, attempted: 22, attempts_max: 30, exits: { success: 20, crashed: 2 }, spread: { n: 20, low: 0, median: 1, high: 3 } },
  { baseline: 4, human_side: "defence" as const, step: "2", status: "running" as const, profile_key: "d4e5f6", counted: 7, wanted: 20, attempted: 8, attempts_max: 30, exits: { success: 7 }, spread: { n: 7, low: 0, median: 2, high: 3 } },
];

export const fixtures = [
  reply("get", "/api/bot-steps/", steps),
  reply("get", "/api/rounds/{round_id}/debrief/", (asked) => ({ ...debrief, round: Number(asked.params.round_id) })),
  reply("get", "/api/rounds/{round_id}/debrief/", (asked) => ({ ...debrief, round: Number(asked.params.round_id), pending: true }), { variant: "debrief-pending" }),
  refuse("get", "/api/rounds/{round_id}/debrief/", 409, [{ path: "", code: "round_running" }], { variant: "round-running" }),
  reply("get", "/api/records/", [recordLine(12, 40, true), recordLine(11, 38, false)]),
  reply("get", "/api/records/", [], { variant: "records-empty" }),
  reply("get", "/api/records/{record_id}/", (asked) => ({
    ...recordLine(Number(asked.params.record_id), 40, true), card: "A3", score, debrief, bot: {},
  })),
  reply("get", "/api/problems/{problem_id}/baselines/", baselines),
  reply("post", "/api/problems/{problem_id}/baselines/", (asked) => ({
    ...(baselines[1] as components["schemas"]["BaselineLine"]), baseline: 5, human_side: asked.body?.human_side ?? "defence", step: asked.body?.step ?? "2", counted: 0, attempted: 0,
  }), { status: 201 }),
];
