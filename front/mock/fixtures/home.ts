import { minutesFromNow, refuse, reply } from "../fixture";

const lessonTitles = [
  "Lesson placeholder one", "Lesson placeholder two", "Lesson placeholder three",
  "Lesson placeholder four", "Lesson placeholder five", "Lesson placeholder six",
];

export const problems = [
  ...lessonTitles.map((title, index) => ({
    id: index + 1, kind: "lesson", wargame: "board", side: index === 3 || index === 4 ? "both" : "defence",
    title, summary: `Placeholder summary for ${title.toLowerCase()}`,
  })),
  { id: 7, kind: "match", wargame: "board", side: "both", title: "Board wargame", summary: "Placeholder summary for the board match" },
  { id: 8, kind: "match", wargame: "corp", side: "both", title: "Corp wargame", summary: "Placeholder summary for the corp match" },
];

const human = (side: "attack" | "defence", username: string | null) => ({ side, client: "human", username, bot_name: "" });
const bot = (side: "attack" | "defence", name: string) => ({ side, client: "bot", username: null, bot_name: name });

const mine = [
  { round: 41, problem: 7, kind: "match", matchup: "pvp", phase: "running" as const, seats: [human("attack", "learner-two"), human("defence", "learner-one")] },
  { round: 40, problem: 7, kind: "match", matchup: "def_vs_bot", phase: "ended" as const, seats: [bot("attack", "claude-code"), human("defence", "learner-one")] },
];

const joinable = [
  { round: 42, problem: 7, kind: "match", matchup: "pvp", phase: "created" as const, seats: [human("attack", "learner-three"), human("defence", null)] },
];

const lessons = [
  { round: 38, problem: 5, phase: "ready" as const, passed_order: 3 },
  { round: 37, problem: 1, phase: "ended" as const, passed_order: 6 },
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
  reply("get", "/api/lessons/", lessons),
  reply("get", "/api/lessons/", [], { variant: "empty-home" }),
  reply("post", "/api/lessons/", (asked) => ({ round: 50 + (asked.body?.problem ?? 0), lease: 30, phase: "waiting_slot" as const }), { status: 201 }),
  reply("post", "/api/leases/", (asked) => ({
    lease: 7, wargame: asked.body?.wargame ?? "board", slot: 2, ready: false, expires_at: minutesFromNow(120), closed: null,
  }), { status: 201 }),
  refuse("post", "/api/leases/", 400, [{ path: "wargame", code: "unknown_wargame" }], { variant: "lease-refused" }),
  reply("post", "/api/rounds/{round_id}/seats/{side}/join/", (asked) => ({ seat: 90, side: asked.params.side === "attack" ? "attack" as const : "defence" as const })),
  refuse("post", "/api/rounds/{round_id}/seats/{side}/join/", 409, [{ path: "", code: "seat_taken" }], { variant: "seat-taken" }),
];
