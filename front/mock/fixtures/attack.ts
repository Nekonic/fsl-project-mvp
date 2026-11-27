import { minutesFromNow, refuse, reply } from "../fixture";
import { remaining } from "./sides";

const cases = [
  { case: "board-sqli-search", kind: "http" as const, malicious: true, title: "SQL injection in search" },
  { case: "board-sqli-login-bypass", kind: "http" as const, malicious: true, title: "Login bypass" },
  { case: "board-sqli-union-search", kind: "http" as const, malicious: true, title: "UNION search" },
  { case: "board-sqli-orderby-sqlmap", kind: "tool" as const, malicious: true, title: "sqlmap on sort" },
  { case: "board-sqli-orderby-sqlmap-tamper", kind: "tool" as const, malicious: true, title: "sqlmap with tamper" },
  { case: "board-xss-script-tag-in-search", kind: "http" as const, malicious: true, title: "Script tag in search" },
  { case: "board-xss-img-onerror-in-comment", kind: "http" as const, malicious: true, title: "img onerror in comment" },
  { case: "board-path-traversal-static", kind: "http" as const, malicious: true, title: "Path traversal on static" },
  { case: "board-benign-browse", kind: "http" as const, malicious: false, title: "Browse" },
];

const paths = ["/", "/posts/10/", "/search/?q=study", "/", "/posts/2/", "/?sort=title", "/posts/1/", "/accounts/login/", "/", "/favicon.ico", "/static/vendor/bootstrap.min.css", "/"];

const siteRequests = paths.map((path, index) => ({
  id: paths.length - index,
  at: minutesFromNow(-index * 0.1),
  method: "GET",
  url: `http://board.com${path}`,
  status: path === "/favicon.ico" ? 404 : 200,
  size: 4096,
}));

const spentAll = { ...remaining, origin: null, left: 0, spent: ["5.188.10.10", "181.8.0.10"] };

export const fixtures = [
  reply("get", "/api/rounds/{round_id}/attack/cases/", cases.map((entry) => ({ ...entry, last: null }))),
  reply("post", "/api/rounds/{round_id}/attack/cases/", (asked) => {
    const fired = cases.find((entry) => entry.case === asked.body?.case);
    return fired?.kind === "tool"
      ? { action: 901, marker: "mk-901", run: 31, status: null, remaining }
      : { action: 902, marker: "mk-902", run: null, status: fired?.case.includes("xss") ? 403 : 200, remaining };
  }),
  reply("get", "/api/rounds/{round_id}/site/requests/", (asked) => {
    const after = Number(asked.query.get("after") ?? 0);
    return siteRequests.filter((request) => request.id > after);
  }),
  reply("post", "/api/rounds/{round_id}/attack/loot/", (asked) => {
    const text = JSON.stringify(asked.body?.value ?? "");
    return text.includes("pbkdf2")
      ? {
        lost: true,
        objective: { key: "board-auth-user-admin", name: "Board admin account" },
        objectives: [
          { key: "board-auth-user-admin", name: "Board admin account" },
          { key: "board-auth-user-partial", name: "Board accounts, partial" },
        ],
        remaining,
      }
      : { lost: false, objective: null, objectives: [], remaining };
  }),
  reply("post", "/api/rounds/{round_id}/attack/origins/next/", { origin: { id: "br-1", label: "BR", ip: "177.8.0.10" }, remaining: { ...remaining, origin: { id: "br-1", label: "BR", ip: "177.8.0.10" }, left: 28 } }),
  refuse("post", "/api/rounds/{round_id}/attack/origins/next/", 409, [{ path: "", code: "origins_spent" }], { variant: "spent" }),
  refuse("post", "/api/rounds/{round_id}/attack/loot/", 409, [{ path: "", code: "loot_not_taken" }], { variant: "corp" }),
  reply("get", "/api/rounds/{round_id}/attack/state/", (asked) => ({
    round: Number(asked.params.round_id),
    matchup: "pvp",
    phase: "running",
    started: minutesFromNow(-20),
    ends_at: minutesFromNow(10),
    end_reason: "",
    brief: { title: "Board wargame", summary: "Placeholder summary", body: "Placeholder body" },
    target: { public_url: "http://board.com/", hosts: ["board.com"] },
    objectives: [
      { key: "board-auth-user-partial", name: "Board accounts, partial", state: "lost" as const },
      { key: "board-auth-user-admin", name: "Board admin account", state: "kept" as const },
      { key: "board-auth-user-full", name: "Board accounts, all", state: "kept" as const },
    ],
    origins: [
      { id: "ru-1", label: "RU", ip: "5.188.10.10", spent_at: minutesFromNow(-12), spent_by: "deny" },
      { id: "ar-1", label: "AR", ip: "181.8.0.10", spent_at: minutesFromNow(-2), spent_by: "limit_req" },
    ],
    remaining: spentAll,
    takes_loot: true,
  }), { variant: "spent" }),
];
