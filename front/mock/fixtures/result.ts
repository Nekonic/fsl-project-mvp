import { refuse, reply } from "../fixture";

export const score = {
  objectives: {
    lost: [{ key: "board-auth-user-partial", name: "Board accounts, partial", seen: false, attributed_marker: "m-7f3a" }],
    kept: [
      { key: "board-auth-user-admin", name: "Board admin account" },
      { key: "board-auth-user-full", name: "Board accounts, all" },
    ],
    weighted: 2,
  },
  outcomes: {
    per_case: [
      { case: "board-sqli-search", verdict: "tp" as const, alerts: 3, corroborated: true },
      { case: "board-xss-script-tag-in-search", verdict: "tp" as const, alerts: 3, corroborated: true },
      { case: "board-sqli-orderby-sqlmap-skip-waf", verdict: "fn" as const, alerts: 0, corroborated: null },
      { case: "board-normal-search", verdict: "tn" as const, alerts: 0, corroborated: null },
      { case: "board-normal-search-with-apostrophe", verdict: "tn" as const, alerts: 0, corroborated: null },
      { case: "board-normal-post-list", verdict: "tn" as const, alerts: 0, corroborated: null },
      { case: "board-normal-sort", verdict: "tn" as const, alerts: 0, corroborated: null },
      { case: "board-normal-search-korean", verdict: "tn" as const, alerts: 0, corroborated: null },
      { case: "board-normal-comment", verdict: "tn" as const, alerts: 0, corroborated: null },
    ],
    totals: { tp: 2, fp: 0, fn: 1, tn: 6 },
    note: "one_case_one_decision",
  },
  free_actions: {
    by_origin: [
      { ip: "5.188.10.10", actions: 998, alerts: 1996, refused: 998 },
      { ip: "181.8.0.10", actions: 12, alerts: 0, refused: 0 },
    ],
  },
};

export const blockingScore = {
  ...score,
  objectives: { lost: [], kept: [...score.objectives.kept, { key: "board-auth-user-partial", name: "Board accounts, partial" }], weighted: 0 },
  outcomes: {
    ...score.outcomes,
    per_case: score.outcomes.per_case.map((line) => (line.verdict === "tn" ? { ...line, verdict: "fp" as const, alerts: 4 } : line)),
    totals: { tp: 2, fp: 6, fn: 1, tn: 0 },
  },
};

export const fixtures = [
  reply("get", "/api/rounds/{round_id}/score/", score),
  reply("get", "/api/rounds/{round_id}/score/", blockingScore, { variant: "score-blocking" }),
  refuse("get", "/api/rounds/{round_id}/score/", 409, [{ path: "", code: "round_running" }], { variant: "round-running" }),
];
