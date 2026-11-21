import { minutesFromNow, refuse, reply } from "../fixture";

export const problems = [
  { id: 7, kind: "round", wargame: "board", side: "both", title: "Board wargame", summary: "Placeholder summary for the board match" },
  { id: 8, kind: "round", wargame: "corp", side: "both", title: "Corp wargame", summary: "Placeholder summary for the corp match" },
];

const human = (side: "attack" | "defence", username: string | null) => ({ side, client: "human", username, bot_name: "" });
const bot = (side: "attack" | "defence", name: string) => ({ side, client: "bot", username: null, bot_name: name });

const mine = [
  { round: 41, problem: 7, kind: "round", matchup: "pvp", phase: "running" as const, players: [human("attack", "learner-two"), human("defence", "learner-one")] },
  { round: 40, problem: 7, kind: "round", matchup: "def_vs_bot", phase: "ended" as const, players: [bot("attack", "claude-code"), human("defence", "learner-one")] },
];

const joinable = [
  { round: 42, problem: 7, kind: "round", matchup: "pvp", phase: "created" as const, players: [human("attack", "learner-three"), human("defence", null)] },
];

export const fixtures = [
  reply("get", "/api/problems/", problems),
  reply("get", "/api/problems/", [], { variant: "empty-home" }),
  reply("get", "/api/rounds/", (asked) => {
    if (asked.query.get("state") === "joinable") return joinable;
    if (asked.query.get("state") === "open") return mine.filter((line) => line.phase !== "ended");
    return mine;
  }),
  reply("get", "/api/rounds/", [], { variant: "empty-home" }),
  reply("post", "/api/allocations/", (asked) => ({
    allocation: 7, wargame: asked.body?.wargame ?? "board", slot: 2, ready: false, expires_at: minutesFromNow(120), closed: null,
  }), { status: 201 }),
  refuse("post", "/api/allocations/", 400, [{ path: "wargame", code: "unknown_wargame" }], { variant: "allocation-refused" }),
  reply("post", "/api/rounds/{round_id}/players/{side}/join/", (asked) => ({ player: 90, side: asked.params.side === "attack" ? "attack" as const : "defence" as const })),
  refuse("post", "/api/rounds/{round_id}/players/{side}/join/", 409, [{ path: "", code: "player_taken" }], { variant: "player-taken" }),
];
