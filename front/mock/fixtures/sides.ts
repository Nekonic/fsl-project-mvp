import { minutesFromNow, reply } from "../fixture";

const objectives = [
  { key: "board-auth-user-partial", name: "Board accounts, partial", state: "lost" as const },
  { key: "board-auth-user-admin", name: "Board admin account", state: "kept" as const },
  { key: "board-auth-user-full", name: "Board accounts, all", state: "kept" as const },
];

const brief = { title: "Board wargame", summary: "Placeholder summary", body: "Placeholder body" };
const target = { public_url: "http://board.com/", hosts: ["board.com"] };

export const remaining = {
  origin: { id: "ar-1", label: "AR", ip: "181.8.0.10" },
  left: 29,
  total: 30,
  spent: ["5.188.10.10"],
};

const roundState = (round: number) => ({
  round, matchup: "pvp", phase: "running", started: minutesFromNow(-20), ends_at: minutesFromNow(10), end_reason: "", brief, target,
});

export const fixtures = [
  reply("get", "/api/rounds/{round_id}/attack/state/", (asked) => ({
    ...roundState(Number(asked.params.round_id)),
    objectives,
    origins: [
      { id: "ru-1", label: "RU", ip: "5.188.10.10", spent_at: minutesFromNow(-12), spent_by: "deny" },
      { id: "ar-1", label: "AR", ip: "181.8.0.10", spent_at: null, spent_by: "" },
    ],
    remaining,
    takes_loot: true,
  })),
  reply("get", "/api/rounds/{round_id}/defence/state/", (asked) => ({
    ...roundState(Number(asked.params.round_id)),
    objectives: objectives.map((objective) => ({ ...objective, seen: false })),
    ids: { version: 2 },
    waf: { version: 2 },
    alerts_total: 2002,
  })),
  reply("get", "/api/rounds/{round_id}/attack/terminal/", (asked) => ({
    ws_url: `/vm-terminal/attack/${asked.params.round_id}/`,
    ssh: { host: "range.example", port: 2222, user: "kali", private_key: "placeholder-key", expires_at: minutesFromNow(10), target_host: "kali", target_user: "kali" },
    remaining,
  })),
  reply("get", "/api/rounds/{round_id}/defence/waf/terminal/", (asked) => ({
    ws_url: `/vm-terminal/defence/${asked.params.round_id}/`,
    ssh: { host: "range.example", port: 2222, user: "analyst", private_key: "placeholder-key", expires_at: minutesFromNow(10), target_host: "waf", target_user: "analyst" },
  })),
  reply("get", "/api/rounds/{round_id}/defence/ids/terminal/", (asked) => ({
    ws_url: `/vm-terminal/ids/${asked.params.round_id}/`,
    ssh: { host: "range.example", port: 2222, user: "analyst", private_key: "placeholder-key", expires_at: minutesFromNow(10), target_host: "sensor", target_user: "analyst" },
  })),
  reply("get", "/api/rounds/{round_id}/defence/kibana/", (asked) => ({ space_url: `/kibana/s/round-${asked.params.round_id}/app/discover` })),
];
