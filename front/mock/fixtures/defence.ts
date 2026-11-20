import type { components } from "../../src/api/schema";
import { minutesFromNow, refuse, reply } from "../fixture";

type RuleTestResult = components["schemas"]["RuleTestResult"];
type RuleError = components["schemas"]["RuleError"];
type WafPosture = components["schemas"]["WafPostureRequest"];

const idsText = [
  "# Suricata rules for this network. sids 9000000-9999999.",
  "",
  "alert http $EXTERNAL_NET any -> $HOME_NET any (msg:\"SQLi attempt - URI\"; flow:established,to_server; http.uri; pcre:\"/(\\x27[\\s+]*(or|and)[\\s+]*[\\x27\\d]|union[\\s+]+select)/i\"; classtype:web-application-attack; sid:9000001; rev:3;)",
  "",
  "alert http $EXTERNAL_NET any -> $HOME_NET any (msg:\"XSS attempt - script tag or event handler\"; flow:established,to_server; http.uri; pcre:\"/(<script|%3cscript|javascript:)/i\"; classtype:web-application-attack; sid:9000003; rev:2;)",
  "",
  "alert http $EXTERNAL_NET any -> $HOME_NET any (msg:\"path traversal attempt\"; flow:established,to_server; http.uri.raw; pcre:\"/(\\.\\.(%2f|%5c|[\\/\\\\])|%2e%2e)/i\"; classtype:web-application-attack; sid:9000004; rev:3;)",
  "",
  "alert http $EXTERNAL_NET any -> $HOME_NET any (msg:\"SQLi attempt - sort parameter\"; flow:established,to_server; http.uri; content:\"sort=\"; nocase; pcre:\"/sort=[^&]*(\\(select|case[\\s+]+when|sleep\\()/i\"; classtype:web-application-attack; sid:9000005; rev:1;)",
].join("\n");

const posture = {
  paranoia: 1,
  thresholds: { inbound: 5, outbound: 4 },
  detection_only: false,
  exclusions: [{ tag: "attack-sqli", target: "ARGS:sort", path: "/" }],
};

const CRS_TARGET = /^(ARGS|ARGS_NAMES|REQUEST_COOKIES|REQUEST_HEADERS|REQUEST_BODY)(:[\w.-]+)?$/;

function unbalancedLines(text: string): RuleError[] {
  return text.split("\n").flatMap((line, index) => {
    if (!line.startsWith("alert")) return [];
    const opened = (line.match(/\(/g) ?? []).length - (line.match(/\\\(/g) ?? []).length;
    const closed = (line.match(/\)/g) ?? []).length - (line.match(/\\\)/g) ?? []).length;
    return opened === closed ? [] : [{ path: "text", code: "suricata_syntax", line: index + 1, message: "invalid character in pcre" }];
  });
}

function refusedPosture(asked: WafPosture | undefined): RuleError[] {
  return (asked?.exclusions ?? []).flatMap((one, index) =>
    one.target && !CRS_TARGET.test(one.target) ? [{ path: `exclusions[${index}].target`, code: "crs_refused", line: null, message: "unknown variable" }] : [],
  );
}

const benign = ["board-normal-search", "board-normal-search-with-apostrophe", "board-normal-post-list", "board-normal-sort", "board-normal-comment"];

function idsResult(test: number, errors: RuleError[]): RuleTestResult {
  if (errors.length) return { test, ok: false, errors, cases: [], totals: { tp: 0, fn: 0, fp: 0, tn: 0 }, untested: [], against_applied: [] };
  return {
    test,
    ok: true,
    errors: [],
    cases: [
      { case: "board-sqli-search", malicious: true, verdict: "tp", corroborated: true, recorded_run: false, alerts: [{ rule: "9000001", signature: "SQLi attempt - URI" }] },
      { case: "board-xss-script-tag-in-search", malicious: true, verdict: "tp", corroborated: true, recorded_run: false, alerts: [{ rule: "9000003", signature: "XSS attempt - script tag or event handler" }] },
      { case: "board-sqli-orderby-sqlmap-probe", malicious: true, verdict: "tp", corroborated: true, recorded_run: true, alerts: [{ rule: "9000005", signature: "SQLi attempt - sort parameter" }] },
      { case: "board-path-traversal-static", malicious: true, verdict: "tp", corroborated: false, recorded_run: false, alerts: [{ rule: "9000004", signature: "path traversal attempt" }] },
      ...benign.map((name) => ({ case: name, malicious: false, verdict: "tn" as const, corroborated: null, recorded_run: false, alerts: [] })),
    ],
    totals: { tp: 4, fn: 0, fp: 0, tn: benign.length },
    untested: [],
    against_applied: [{ case: "board-sqli-orderby-sqlmap-probe", was: "fn", now: "tp" }],
  };
}

function wafResult(test: number, errors: RuleError[]): RuleTestResult {
  if (errors.length) return { test, ok: false, errors, cases: [], totals: { tp: 0, fn: 0, fp: 0, tn: 0 }, untested: [], against_applied: [] };
  return {
    test,
    ok: true,
    errors: [],
    cases: [
      { case: "board-sqli-search", malicious: true, verdict: "tp", corroborated: true, recorded_run: false, alerts: [{ rule: "942100", signature: "SQL Injection Attack Detected via libinjection" }] },
      { case: "board-xss-script-tag-in-search", malicious: true, verdict: "tp", corroborated: true, recorded_run: false, alerts: [{ rule: "941100", signature: "XSS Attack Detected via libinjection" }] },
      { case: "board-path-traversal-static", malicious: true, verdict: "fn", corroborated: null, recorded_run: false, alerts: [] },
      { case: "board-normal-search-with-apostrophe", malicious: false, verdict: "fp", corroborated: null, recorded_run: false, alerts: [{ rule: "942100", signature: "SQL Injection Attack Detected via libinjection" }] },
      ...benign.filter((name) => name !== "board-normal-search-with-apostrophe").map((name) => ({ case: name, malicious: false, verdict: "tn" as const, corroborated: null, recorded_run: false, alerts: [] })),
    ],
    totals: { tp: 2, fn: 1, fp: 1, tn: benign.length - 1 },
    untested: [{ case: "board-sqli-orderby-sqlmap", reason: "tool_case" }],
    against_applied: [],
  };
}

let nextTest = 13;
const idsHead = { version: 2 };
const wafHead = { version: 2 };

const alerts = [
  { engine: "ids", rule: "9000001", signature: "SQLi attempt - URI", uri: "/search/?q=' OR 1=1--", blocked: false, at: -18 },
  { engine: "waf", rule: "942100", signature: "SQL Injection Attack Detected via libinjection", uri: "/search/?q=' OR 1=1--", blocked: true, at: -18 },
  { engine: "ids", rule: "9000003", signature: "XSS attempt - script tag or event handler", uri: "/search/?q=<script>alert(1)</script>", blocked: false, at: -17 },
  { engine: "waf", rule: "941100", signature: "XSS Attack Detected via libinjection", uri: "/search/?q=<script>alert(1)</script>", blocked: true, at: -17 },
  { engine: "waf", rule: "913100", signature: "Found User-Agent associated with security scanner", uri: "/?sort=posts_post.id", blocked: true, at: -15 },
  { engine: "waf", rule: "949110", signature: "Inbound Anomaly Score Exceeded (Total Score: 5)", uri: "/?sort=posts_post.id", blocked: true, at: -11 },
].map((one, index) => ({
  id: index + 1,
  time: minutesFromNow(one.at),
  engine: one.engine,
  rule: one.rule,
  signature: one.signature,
  src_ip: "5.188.10.10",
  request_id: `marker-${index + 1}`,
  uri: one.uri,
  blocked: one.blocked,
}));

export const fixtures = [
  reply("get", "/api/rounds/{round_id}/defence/ids/rules/", () => ({ text: idsText, version: idsHead.version })),
  reply("get", "/api/rounds/{round_id}/defence/ids/rules/versions/", [
    { version: 2, applied_at: minutesFromNow(-6), tested: 12, same_as_tested: true },
    { version: 1, applied_at: minutesFromNow(-14), tested: null, same_as_tested: false },
  ]),
  reply("get", "/api/rounds/{round_id}/defence/ids/rules/versions/", [], { variant: "untested" }),
  reply("post", "/api/rounds/{round_id}/defence/ids/rules/check/", (asked) => {
    const errors = unbalancedLines(asked.body?.text ?? "");
    return { ok: errors.length === 0, errors };
  }),
  reply("post", "/api/rounds/{round_id}/defence/ids/rules/test/", (asked) => idsResult(nextTest++, unbalancedLines(asked.body?.text ?? ""))),
  refuse("post", "/api/rounds/{round_id}/defence/ids/rules/test/", 409, [{ path: "", code: "test_busy" }], { variant: "busy" }),
  reply("get", "/api/rounds/{round_id}/defence/ids/rules/tests/{test_id}/", (asked) => idsResult(Number(asked.params.test_id), [])),
  reply("post", "/api/rounds/{round_id}/defence/ids/rules/apply/", (asked) => {
    idsHead.version += 1;
    return { version: idsHead.version, applied_at: minutesFromNow(0), same_as_tested: asked.body?.tested !== null && asked.body?.tested !== undefined, sensors: [{ name: "cr-ids", ok: true }] };
  }),
  refuse("post", "/api/rounds/{round_id}/defence/ids/rules/apply/", 409, [{ path: "base_version", code: "stale_version", params: { current_version: 3 } }], { variant: "stale" }),
  reply("get", "/api/rounds/{round_id}/defence/ids/disabled/", [
    { sid: 2013028, original: "alert http any any -> any any (msg:\"ET POLICY curl User-Agent Outbound\"; sid:2013028; rev:4;)", reason: "noisy on benign traffic", expires_at: minutesFromNow(40) },
  ]),
  reply("post", "/api/rounds/{round_id}/defence/ids/disabled/", (asked) => ({ sid: asked.body?.sid ?? 0, expires_at: minutesFromNow(asked.body?.minutes ?? 60) }), { status: 201 }),
  reply("delete", "/api/rounds/{round_id}/defence/ids/disabled/{sid}/", undefined as never),
  reply("get", "/api/rounds/{round_id}/defence/waf/", () => ({ posture, version: wafHead.version })),
  reply("get", "/api/rounds/{round_id}/defence/waf/versions/", [
    { version: 2, applied_at: minutesFromNow(-9), tested: null, same_as_tested: false },
    { version: 1, applied_at: minutesFromNow(-14), tested: null, same_as_tested: false },
  ]),
  reply("post", "/api/rounds/{round_id}/defence/waf/check/", (asked) => {
    const errors = refusedPosture(asked.body?.posture);
    return { ok: errors.length === 0, errors };
  }),
  reply("post", "/api/rounds/{round_id}/defence/waf/test/", (asked) => wafResult(nextTest++, refusedPosture(asked.body?.posture))),
  reply("get", "/api/rounds/{round_id}/defence/waf/tests/{test_id}/", (asked) => wafResult(Number(asked.params.test_id), [])),
  reply("post", "/api/rounds/{round_id}/defence/waf/apply/", (asked) => {
    wafHead.version += 1;
    return { version: wafHead.version, applied_at: minutesFromNow(0), same_as_tested: asked.body?.tested !== null && asked.body?.tested !== undefined };
  }),
  reply("get", "/api/rounds/{round_id}/defence/alerts/", (asked) => {
    const after = Number(asked.query.get("after") ?? 0);
    const engine = asked.query.get("engine");
    const rule = asked.query.get("rule");
    const src = asked.query.get("src");
    const shown = alerts.filter((one) => one.id > after && (!engine || one.engine === engine) && (!rule || one.rule === rule) && (!src || one.src_ip === src));
    return { alerts: shown, next: shown.length ? Math.max(...shown.map((one) => one.id)) : after };
  }),
  reply("get", "/api/rounds/{round_id}/defence/traffic/", {
    by_origin: [
      { ip: "181.8.0.10", requests: 2012, refused: 0, last_at: minutesFromNow(-3) },
      { ip: "5.188.10.10", requests: 1000, refused: 1000, last_at: minutesFromNow(-11) },
      { ip: "175.192.0.11", requests: 31, refused: 0, last_at: minutesFromNow(-1) },
    ],
    next: "",
  }),
  reply("get", "/api/rounds/{round_id}/defence/probes/", [
    { case: "board-sqli-search", malicious: true, recorded: true, tool_case: false },
    { case: "board-sqli-orderby-sqlmap", malicious: true, recorded: true, tool_case: true },
    { case: "board-normal-search", malicious: false, recorded: true, tool_case: false },
  ]),
];
