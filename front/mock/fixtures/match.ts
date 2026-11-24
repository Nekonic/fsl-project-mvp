import { minutesFromNow, reply } from "../fixture";

const address = (source: string, zone: string, text: string, x: number, y: number, label: string) => ({
  id: `address:${source}:switch:${zone}`, kind: "address", text, x, y, label, zone,
});

export const topology = {
  zones: [
    { id: "internet", caption: "internet", subnet: "", box: [-230, -110, 260, 110] },
    { id: "dmz", caption: "dmz", subnet: "10.30.0.0/24", box: [430, -110, 900, 110] },
    { id: "web", caption: "web", subnet: "10.30.128.0/24", box: [430, 210, 900, 430] },
    { id: "board", caption: "database", owner: "board", subnet: "172.18.0.0/24", box: [960, 210, 1290, 430] },
    { id: "mgmt", caption: "mgmt", subnet: "172.29.0.0/24", box: [-230, 210, 260, 430] },
  ],
  nodes: [
    { id: "kali", kind: "kali", name: "kali", x: -120, y: 0, label: "below" },
    { id: "switch:internet", kind: "switch", zone: "internet", x: 150, y: 0 },
    { id: "router", kind: "router", name: "router", x: 345, y: 0, label: "below" },
    { id: "switch:dmz", kind: "switch", zone: "dmz", x: 540, y: 0 },
    { id: "waf", kind: "waf", name: "waf", x: 790, y: 0, label: "below" },
    { id: "switch:web", kind: "switch", zone: "web", x: 540, y: 320 },
    { id: "board.com", kind: "server", name: "board.com", x: 790, y: 320, label: "below" },
    { id: "switch:board", kind: "switch", zone: "board", x: 1040, y: 320 },
    { id: "board-db", kind: "database", name: "board-db", x: 1200, y: 320, label: "below" },
    { id: "switch:mgmt", kind: "switch", zone: "mgmt", x: 150, y: 320 },
    { id: "log-server", kind: "logs", name: "log-server", x: -120, y: 320, label: "below" },
    { id: "ids", kind: "sensor", zone: "mgmt", x: 345, y: 320, label: "below" },
    address("kali", "internet", "121.134.88.41", -88, -13, "right"),
    address("router", "internet", "121.134.88.42", 313, -13, "left"),
    address("router", "dmz", "10.30.0.1", 377, -13, "right"),
    address("waf", "dmz", "10.30.0.247", 758, -13, "left"),
    address("waf", "web", "10.30.128.247", 796, 52, "right"),
    address("board.com", "web", "10.30.128.59", 758, 307, "left"),
    address("board.com", "board", "172.18.0.3", 822, 307, "right"),
    address("board-db", "board", "172.18.0.2", 1168, 307, "left"),
    address("log-server", "mgmt", "172.29.0.10", -88, 307, "right"),
  ],
  edges: [
    { id: "link:kali:switch:internet", kind: "link", source: "kali", target: "switch:internet" },
    { id: "link:router:switch:internet", kind: "link", source: "router", target: "switch:internet" },
    { id: "link:router:switch:dmz", kind: "link", source: "router", target: "switch:dmz" },
    { id: "link:waf:switch:dmz", kind: "link", source: "waf", target: "switch:dmz" },
    { id: "link:waf:switch:web", kind: "link", source: "waf", target: "switch:web", route: [[790, 170], [540, 170]] },
    { id: "link:board.com:switch:web", kind: "link", source: "board.com", target: "switch:web" },
    { id: "link:board.com:switch:board", kind: "link", source: "board.com", target: "switch:board" },
    { id: "link:board-db:switch:board", kind: "link", source: "board-db", target: "switch:board" },
    { id: "link:log-server:switch:mgmt", kind: "link", source: "log-server", target: "switch:mgmt" },
    { id: "link:ids:switch:mgmt", kind: "link", source: "ids", target: "switch:mgmt" },
    { id: "mirror:ids:switch:web", kind: "mirror", source: "ids", target: "switch:web" },
  ],
};

const started = minutesFromNow(-20);
const endsAt = minutesFromNow(10);

const runningRound = {
  round: 41, allocation: 12, problem: 7, kind: "round", matchup: "pvp", phase: "running" as const,
  players: [
    { side: "attack" as const, client: "human", username: "learner-two", bot_name: "", step: "", bot_run: null },
    { side: "defence" as const, client: "human", username: "learner-one", bot_name: "", step: "", bot_run: null },
  ],
  started, ends_at: endsAt, ended: null, end_reason: "",
};

export const fixtures = [
  reply("get", "/api/rounds/{round_id}/", (asked) => ({ ...runningRound, round: Number(asked.params.round_id) })),
  reply("get", "/api/rounds/{round_id}/", (asked) => ({
    ...runningRound, round: Number(asked.params.round_id), phase: "ended" as const, ended: minutesFromNow(-1), end_reason: "time_limit",
  }), { variant: "ended" }),
  reply("get", "/api/rounds/{round_id}/events/", (asked) => ({ events: [], next: Number(asked.query.get("after") ?? 0) })),
  reply("get", "/api/rounds/{round_id}/topology/", topology),
  reply("post", "/api/allocations/{allocation_id}/heartbeat/", { expires_at: minutesFromNow(30) }),
  reply("get", "/api/problems/{problem_id}/", (asked) => ({
    id: Number(asked.params.problem_id), kind: "round", wargame: "board", side: "both",
    title: "Board wargame", summary: "Placeholder summary", body: "Placeholder body",
    matchups: ["pvp", "def_vs_bot", "atk_vs_bot"], bot_steps: ["1", "2", "3"],
  })),
  reply("post", "/api/rounds/{round_id}/attack/forfeit/", { ended: minutesFromNow(0), reason: "forfeit_attack" }),
  reply("post", "/api/rounds/{round_id}/defence/forfeit/", { ended: minutesFromNow(0), reason: "forfeit_defence" }),
];
