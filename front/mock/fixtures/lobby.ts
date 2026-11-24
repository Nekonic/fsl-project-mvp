import { minutesFromNow, refuse, reply } from "../fixture";

const human = (side: "attack" | "defence", username: string | null) => ({ side, client: "human", username, bot_name: "", step: "", bot_run: null });
const bot = (side: "attack" | "defence", name: string) => ({ side, client: "bot", username: null, bot_name: name, step: "", bot_run: null });

const waiting = { round: 43, problem: 7, kind: "round", matchup: "def_vs_bot", phase: "created" as const, players: [bot("attack", "claude-code"), human("defence", "learner-one")] };
const finished = { round: 40, problem: 7, kind: "round", matchup: "pvp", phase: "ended" as const, players: [human("attack", "learner-two"), human("defence", null)] };

interface AllocationShape {
  ready?: boolean;
  closed?: string | null;
  rounds?: Array<typeof waiting | typeof finished>;
}

const allocation = (id: string | undefined, shape: AllocationShape = {}) => ({
  allocation: Number(id ?? 7), wargame: "board", slot: 2, ready: shape.ready ?? true, expires_at: minutesFromNow(110),
  closed: shape.closed ?? null, rounds: shape.rounds ?? [waiting, finished],
});

export const fixtures = [
  reply("get", "/api/allocations/{allocation_id}/", (asked) => allocation(asked.params.allocation_id)),
  reply("get", "/api/allocations/{allocation_id}/", (asked) => allocation(asked.params.allocation_id, { rounds: [finished] }), { variant: "allocation-free" }),
  reply("get", "/api/allocations/{allocation_id}/", (asked) => allocation(asked.params.allocation_id, { ready: false, rounds: [] }), { variant: "allocation-starting" }),
  reply("get", "/api/allocations/{allocation_id}/", (asked) => allocation(asked.params.allocation_id, { closed: minutesFromNow(-1) }), { variant: "allocation-closed" }),
  refuse("get", "/api/allocations/{allocation_id}/", 403, [{ path: "", code: "not_operator" }], { variant: "not-operator" }),
  reply("post", "/api/allocations/{allocation_id}/close/", { closed: minutesFromNow(0) }),
  reply("post", "/api/allocations/{allocation_id}/rounds/", (asked) => {
    const players = asked.body?.players ?? {};
    const playerOf = (side: "attack" | "defence") => {
      const ask = players[side];
      return ask?.bot ? bot(side, ask.bot.name ?? "") : human(side, ask?.username ?? null);
    };
    const made = [playerOf("attack"), playerOf("defence")];
    return {
      round: 44, players: made,
      bot_tokens: Object.fromEntries(made.filter((player) => player.client === "bot").map((player) => [player.side, "cr_player_placeholder_token"])),
    };
  }, { status: 201 }),
  refuse("post", "/api/allocations/{allocation_id}/rounds/", 400, [{ path: "matchup", code: "matchup_not_allowed" }], { variant: "matchup-refused" }),
  reply("post", "/api/rounds/{round_id}/start/", { phase: "starting" as const }),
  refuse("post", "/api/rounds/{round_id}/start/", 409, [{ path: "", code: "players_open" }], { variant: "players-open" }),
  refuse("post", "/api/rounds/{round_id}/start/", 409, [{ path: "", code: "objective_fallen" }], { variant: "objective-fallen" }),
  reply("post", "/api/rounds/{round_id}/end/", { ended: minutesFromNow(0), reason: "ended_by_operator" as const }),
];
