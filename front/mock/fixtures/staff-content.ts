import type { components } from "../../src/api/schema";
import { refuse, reply, type FieldError } from "../fixture";

type Stored = components["schemas"]["StoredDocument"];
type Posture = components["schemas"]["Posture"];
type DocumentBody = components["schemas"]["DocumentRequest"];

const UPDATED = "2026-11-19T05:30:00Z";
const FILES = { "/etc/nginx/modsecurity/crs/crs-setup.conf": "SecDefaultAction \"phase:1,log,auditlog,pass\"\n" };
const WIDE_FILES = { ...FILES, "/etc/nginx/modsecurity/crs/rules/REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf": "SecRule REQUEST_FILENAME \"@beginsWith /\" \"id:10001,phase:1,pass,nolog,ctl:ruleRemoveTargetByTag=attack-sqli;ARGS:sort\"\n" };
const RULES = [
  "alert http $EXTERNAL_NET any -> $HOME_NET any (msg:\"SQLi attempt - URI\"; flow:established,to_server; http.uri; pcre:\"/union[\\s+]+select/i\"; classtype:web-application-attack; sid:9000001; rev:2;)",
  "",
  "alert http $EXTERNAL_NET any -> $HOME_NET any (msg:\"XSS attempt\"; flow:established,to_server; http.uri; pcre:\"/<script/i\"; classtype:web-application-attack; sid:9000003; rev:2;)",
].join("\n");

const postures: Posture[] = [
  { id: 1, wargame: "board", name: "default", suricata_rules: RULES, waf_files: FILES },
  { id: 2, wargame: "board", name: "wide-sort-exclusion", suricata_rules: RULES, waf_files: WIDE_FILES },
  { id: 3, wargame: "corp", name: "default", suricata_rules: RULES, waf_files: FILES },
];

const lessonTitles = [
  "Lesson placeholder one", "Lesson placeholder two", "Lesson placeholder three",
  "Lesson placeholder four", "Lesson placeholder five", "Lesson placeholder six",
];

function lesson(id: number, title: string): Stored {
  return {
    problem: {
      id, kind: "lesson", wargame: "board", side: id === 4 || id === 5 ? "both" : "defence", title,
      summary: `Placeholder summary for ${title.toLowerCase()}`, body: "Placeholder problem body.\n\nSecond paragraph.",
      published: true, revision: id + 2, author: "staff-one", updated: UPDATED,
    },
    steps: [
      { order: 1, body: "Placeholder step one: run the tool from the Kali terminal.", opens: "terminal_kali", check: { kind: "kali", params: { command_has: "sqlmap" } }, hints: [] },
      { order: 2, body: "Placeholder step two: find the rule id in Kibana.", opens: "kibana", check: { kind: "answer", params: { accept: ["913100"], normalise: "text" } }, hints: ["Placeholder hint one.", "Placeholder hint two."] },
      { order: 3, body: "Placeholder step three: run it again with another agent.", opens: "terminal_kali", check: { kind: "kali", params: { command_has: "--random-agent" } }, hints: [] },
      { order: 4, body: "Placeholder step four: find the alert in the alert list.", opens: "alerts", check: { kind: "alert_seen", params: { engine: "waf" } }, hints: ["Placeholder hint."] },
      { order: 5, body: "Placeholder step five: write and test an IDS rule.", opens: "ids_rules", check: { kind: "rule_test", params: { engine: "ids", case: "board-sqli-orderby-sqlmap-tamper" } }, hints: ["Placeholder hint."] },
      { order: 6, body: "Placeholder step six: apply the tested rule.", opens: "ids_rules", check: { kind: "rule_applied", params: { engine: "ids", same_as_tested: true } }, hints: [] },
    ],
    round: null,
    start_posture: id === 6 ? { name: "wide-sort-exclusion", suricata_rules: RULES, waf_files: WIDE_FILES } : { name: "default", suricata_rules: RULES, waf_files: FILES },
  };
}

function wargameRound(id: number, wargame: string, title: string): Stored {
  return {
    problem: { id, kind: "round", wargame, side: "both", title, summary: "Placeholder summary for the match.", body: "", published: true, revision: 3, author: "staff-one", updated: UPDATED },
    steps: [],
    round: {
      matchups: ["pvp", "def_vs_bot", "atk_vs_bot"], posture: "default",
      probe_cases: [`${wargame}-sqli-search`, `${wargame}-xss-script-tag-in-search`, `${wargame}-sqli-orderby-sqlmap-probe`, `${wargame}-path-traversal-static`, `${wargame}-normal-sort`],
      objectives: [`${wargame}-auth-user-partial`, `${wargame}-auth-user-admin`, `${wargame}-auth-user-full`],
      traffic: null, benign_every_s: 60, time_limit_s: 1800,
    },
    start_posture: null,
  };
}

const documents = new Map<number, Stored>([
  ...lessonTitles.map((title, index) => [index + 1, lesson(index + 1, title)] as [number, Stored]),
  [7, wargameRound(7, "board", "Board wargame")],
  [8, wargameRound(8, "corp", "Corp wargame")],
]);
let nextProblem = 9;
let nextPosture = 4;

function listed() {
  return [...documents.values()].map((doc) => ({
    id: doc.problem.id, kind: doc.problem.kind, wargame: doc.problem.wargame, side: doc.problem.side,
    title: doc.problem.title, published: doc.problem.published, revision: doc.problem.revision, updated: doc.problem.updated,
  }));
}

function found(id: string | undefined): Stored {
  return documents.get(Number(id)) ?? (documents.get(1) as Stored);
}

function validation(body: DocumentBody | undefined): FieldError[] {
  const errors: FieldError[] = [];
  if (!body?.problem.title.trim()) errors.push({ path: "problem.title", code: "required" });
  (body?.steps ?? []).forEach((step, index) => {
    const named = step.check.params.case;
    if (typeof named === "string" && named.endsWith("-tamper")) errors.push({ path: `steps[${index}].check.params.case`, code: "not_recorded" });
  });
  (body?.round?.probe_cases ?? []).forEach((name, index) => {
    if (name.includes("-normal-")) errors.push({ path: `round.probe_cases[${index}]`, code: "not_malicious" });
  });
  return errors;
}

function stored(id: number, body: DocumentBody, revision: number): Stored {
  const doc: Stored = {
    problem: { ...body.problem, summary: body.problem.summary ?? "", body: body.problem.body ?? "", published: body.problem.published ?? false, id, revision, author: "staff-one", updated: new Date().toISOString() },
    steps: (body.steps ?? []).map((step) => ({ ...step, opens: step.opens ?? "none", check: step.check })),
    round: body.round ?? null,
    start_posture: body.start_posture ? { ...body.start_posture, suricata_rules: body.start_posture.suricata_rules ?? "" } : null,
  };
  documents.set(id, doc);
  return doc;
}

export const fixtures = [
  reply("get", "/api/staff/problems/", () => listed()),
  reply("get", "/api/staff/problems/{problem_id}/", (asked) => found(asked.params.problem_id)),
  reply("post", "/api/staff/problems/", (asked) => stored(nextProblem++, asked.body as DocumentBody, 1), { status: 201 }),
  reply("put", "/api/staff/problems/{problem_id}/", (asked) => {
    const was = found(asked.params.problem_id);
    const { base_revision: _base, ...body } = asked.body ?? { ...was, base_revision: 0 };
    return stored(was.problem.id, body as DocumentBody, was.problem.revision + 1);
  }),
  refuse("put", "/api/staff/problems/{problem_id}/", 409, [{ path: "", code: "stale_revision", params: { current_revision: 8 } }], { variant: "stale" }),
  reply("delete", "/api/staff/problems/{problem_id}/", undefined),
  refuse("delete", "/api/staff/problems/{problem_id}/", 409, [{ path: "", code: "in_use" }], { variant: "in-use" }),
  reply("get", "/api/staff/problems/{problem_id}/export/", (asked) => {
    const { problem, steps, round, start_posture } = found(asked.params.problem_id);
    const { id: _id, revision: _revision, author: _author, updated: _updated, ...fields } = problem;
    return { problem: fields, steps, round, start_posture };
  }),
  reply("post", "/api/staff/problems/import/", (asked) => stored(nextProblem++, asked.body as DocumentBody, 1), { status: 201 }),
  reply("post", "/api/staff/problems/validate/", (asked) => {
    const errors = validation(asked.body);
    return { ok: errors.length === 0, errors };
  }),
  reply("post", "/api/staff/steps/{problem_id}/{order}/try/", (asked) => (
    Number(asked.params.order) % 2 === 0
      ? { verdict: "passed" as const, detail_code: null, next: Number(asked.params.order) + 1 }
      : { verdict: "not_yet" as const, detail_code: "no_alert", next: null }
  )),
  reply("get", "/api/staff/postures/", () => postures),
  reply("get", "/api/staff/postures/{posture_id}/", (asked) => postures.find((posture) => posture.id === Number(asked.params.posture_id)) ?? (postures[0] as Posture)),
  reply("post", "/api/staff/postures/", (asked) => {
    const made: Posture = { id: nextPosture++, wargame: asked.body?.wargame ?? "board", name: asked.body?.name ?? "", suricata_rules: asked.body?.suricata_rules ?? "", waf_files: asked.body?.waf_files ?? {} };
    postures.push(made);
    return made;
  }, { status: 201 }),
  reply("put", "/api/staff/postures/{posture_id}/", (asked) => {
    const index = postures.findIndex((posture) => posture.id === Number(asked.params.posture_id));
    const was = postures[index] ?? (postures[0] as Posture);
    const now: Posture = { ...was, ...asked.body, suricata_rules: asked.body?.suricata_rules ?? was.suricata_rules, id: was.id };
    if (index >= 0) postures[index] = now;
    return now;
  }),
  refuse("put", "/api/staff/postures/{posture_id}/", 400, [{ path: "name", code: "name_taken" }], { variant: "name-taken" }),
];
