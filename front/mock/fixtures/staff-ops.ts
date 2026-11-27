import type { components } from "../../src/api/schema";
import { minutesFromNow, refuse, reply } from "../fixture";

type Account = components["schemas"]["Account"];
type SlotStanding = components["schemas"]["SlotStanding"];

const accounts: Account[] = [
  { username: "pending-one", approved: false, is_staff: false, joined: "2026-11-20T09:12:00Z" },
  { username: "admin", approved: true, is_staff: true, joined: "2026-10-02T08:00:00Z" },
  { username: "learner-one", approved: true, is_staff: false, joined: "2026-11-03T10:00:00Z" },
  { username: "learner-two", approved: true, is_staff: false, joined: "2026-11-03T11:00:00Z" },
  { username: "learner-three", approved: true, is_staff: false, joined: "2026-11-12T12:00:00Z" },
];

function accountWith(username: string | undefined, approved: boolean): Account {
  const found: Account = accounts.find((account) => account.username === username) ?? accounts[0]!;
  return { ...found, approved };
}

const HOSTS = ["kali", "waf", "infra", "target"];

const WAF_FILES = [
  "/etc/nginx/modsecurity/crs/crs-setup.conf",
  "/etc/nginx/modsecurity/crs/rules/REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf",
  "/etc/nginx/modsecurity/crs/rules/RESPONSE-999-EXCLUSION-RULES-AFTER-CRS.conf",
  "/etc/nginx/defence/http.conf",
  "/etc/nginx/defence/board.com.conf",
  "/etc/nginx/defence/corp.com.conf",
];

function standing(slot: number, wargame: string, status: string, failures: string[] = []): SlotStanding {
  return { slot, wargame, servers: HOSTS.map((host) => ({ host, server: `cr-slot-${slot}-${host}`, status })), blocked: [], failures };
}

const slots = [
  { slot: 1, wargame: "board", allocation: 6, refill: { state: "idle", reason: "" } },
  { slot: 2, wargame: "board", allocation: 7, refill: { state: "idle", reason: "" } },
  { slot: 3, wargame: "board", allocation: null, refill: { state: "running", reason: "" } },
  { slot: 4, wargame: "corp", allocation: 9, refill: { state: "idle", reason: "" } },
  { slot: 5, wargame: "corp", allocation: null, refill: { state: "idle", reason: "" } },
];

let probeReads = 0;

const BOARD_CARDS = [
  { id: "A1", technique: "T1595.002", name: "Active Scanning: Vulnerability Scanning" },
  { id: "A3", technique: "T1190", name: "Exploit Public-Facing Application" },
  { id: "A4", technique: "T1212", name: "Exploitation for Credential Access" },
];
const CORP_CARDS = [
  { id: "A1", technique: "T1595.002", name: "Active Scanning: Vulnerability Scanning" },
  { id: "A7", technique: "T1068", name: "Exploitation for Privilege Escalation" },
];

export const fixtures = [
  reply("get", "/api/staff/users/", accounts),
  reply("post", "/api/staff/users/{username}/approve/", (asked) => accountWith(asked.params.username, true)),
  reply("post", "/api/staff/users/{username}/disable/", (asked) => accountWith(asked.params.username, false)),
  refuse("post", "/api/staff/users/{username}/disable/", 409, [{ path: "", code: "own_account" }], { variant: "own-account" }),
  reply("get", "/api/staff/blocks/", [
    { id: 11, kind: "address", value: "192.0.2.31", username: "admin", reason: "failures", failures: 10, created: minutesFromNow(-20), until: minutesFromNow(25) },
    { id: 12, kind: "fingerprint", value: "a41f9c0e", username: "learner-three", reason: "failures", failures: 5, created: minutesFromNow(-10), until: minutesFromNow(12) },
  ]),
  reply("delete", "/api/staff/blocks/{block_id}/", undefined),

  reply("get", "/api/staff/range/", { slots }),
  reply("get", "/api/staff/range/pool/", {
    slots: [
      standing(1, "board", "ACTIVE"),
      standing(2, "board", "ACTIVE"),
      standing(3, "board", "BUILD"),
      standing(4, "corp", "ACTIVE"),
      standing(5, "corp", "ACTIVE"),
    ],
  }),
  refuse("get", "/api/staff/range/pool/", 409, [{ path: "", code: "range_not_cloud" }], { variant: "not-cloud" }),
  reply("post", "/api/staff/range/pool/", { slots }),
  refuse("post", "/api/staff/range/pool/", 409, [{ path: "", code: "range_not_cloud" }], { variant: "not-cloud" }),
  reply("delete", "/api/staff/range/pool/", undefined),
  reply("delete", "/api/staff/range/leftovers/", undefined),
  reply("post", "/api/staff/range/fabric/", { present: ["cr-fabric-net", "cr-fabric-router"], clean: true }),
  reply("delete", "/api/staff/range/fabric/", undefined),

  reply("get", "/api/staff/wargames/", [
    { id: "board", title: "Community board", image: "board:1", public_url: "", hosts: HOSTS, objective_model: "loot", case_file: "redteam/cases/board.yaml", default_traffic: null, waf_files: WAF_FILES, cards: BOARD_CARDS, objectives: [{ key: "board-auth-user-partial", name: "게시판 계정 일부 탈취" }] },
    { id: "corp", title: "Corporate site", image: "corp:1", public_url: "", hosts: HOSTS, objective_model: "effect", case_file: "redteam/cases/corp.yaml", default_traffic: null, waf_files: WAF_FILES, cards: CORP_CARDS, objectives: [] },
  ]),
  reply("post", "/api/staff/wargames/{wargame_id}/probes/record/", () => {
    probeReads = 0;
    return { allocation: 9 };
  }, { status: 202 }),
  refuse("post", "/api/staff/wargames/{wargame_id}/probes/record/", 409, [{ path: "", code: "probe_running" }], { variant: "probe-running" }),
  reply("get", "/api/staff/probes/{allocation_id}/", (asked) => {
    probeReads += 1;
    const done = ["benign-home", "benign-search", "sqli-login", "xss-comment", "path-traversal", "cmd-injection"].slice(0, Math.min(6, probeReads));
    return {
      allocation: Number(asked.params.allocation_id),
      wargame: "corp",
      state: probeReads >= 7 ? "done" : "recording",
      total: 7,
      done,
      failed: probeReads >= 7 ? [{ case: "upload-shell", code: "tool_unavailable" }] : [],
    };
  }),
];
