import { minutesFromNow, refuse, reply } from "../fixture";

const human = (side: "attack" | "defence", user: number | null) => ({ side, client: "human", user, bot_name: "" });
const bot = (side: "attack" | "defence", name: string) => ({ side, client: "bot", user: null, bot_name: name });

const waiting = { round: 43, problem: 7, kind: "match", matchup: "def_vs_bot", phase: "created" as const, seats: [bot("attack", "claude-code"), human("defence", 3)] };
const finished = { round: 40, problem: 7, kind: "match", matchup: "pvp", phase: "ended" as const, seats: [human("attack", 2), human("defence", null)] };

interface LeaseShape {
  ready?: boolean;
  closed?: string | null;
  rounds?: Array<typeof waiting | typeof finished>;
}

const lease = (id: string | undefined, shape: LeaseShape = {}) => ({
  lease: Number(id ?? 7), wargame: "board", slot: 2, ready: shape.ready ?? true, expires_at: minutesFromNow(110),
  closed: shape.closed ?? null, rounds: shape.rounds ?? [waiting, finished],
});

export const fixtures = [
  reply("get", "/api/leases/{lease_id}/", (asked) => lease(asked.params.lease_id)),
  reply("get", "/api/leases/{lease_id}/", (asked) => lease(asked.params.lease_id, { rounds: [finished] }), { variant: "lease-free" }),
  reply("get", "/api/leases/{lease_id}/", (asked) => lease(asked.params.lease_id, { ready: false, rounds: [] }), { variant: "lease-starting" }),
  reply("get", "/api/leases/{lease_id}/", (asked) => lease(asked.params.lease_id, { closed: minutesFromNow(-1) }), { variant: "lease-closed" }),
  refuse("get", "/api/leases/{lease_id}/", 403, [{ path: "", code: "not_operator" }], { variant: "not-operator" }),
  reply("post", "/api/leases/{lease_id}/close/", { closed: minutesFromNow(0) }),
  reply("post", "/api/leases/{lease_id}/rounds/", (asked) => {
    const seats = asked.body?.seats ?? {};
    const seatOf = (side: "attack" | "defence") => {
      const ask = seats[side];
      return ask?.bot ? bot(side, ask.bot.name) : human(side, ask?.user ?? null);
    };
    const made = [seatOf("attack"), seatOf("defence")];
    return {
      round: 44, seats: made,
      bot_tokens: Object.fromEntries(made.filter((seat) => seat.client === "bot").map((seat) => [seat.side, "cr_seat_placeholder_token"])),
    };
  }, { status: 201 }),
  refuse("post", "/api/leases/{lease_id}/rounds/", 400, [{ path: "matchup", code: "matchup_not_allowed" }], { variant: "matchup-refused" }),
  reply("post", "/api/rounds/{round_id}/start/", { phase: "starting" as const }),
  refuse("post", "/api/rounds/{round_id}/start/", 409, [{ path: "", code: "seats_open" }], { variant: "seats-open" }),
  refuse("post", "/api/rounds/{round_id}/start/", 409, [{ path: "", code: "objective_fallen" }], { variant: "objective-fallen" }),
  reply("post", "/api/rounds/{round_id}/end/", { ended: minutesFromNow(0), reason: "ended_by_operator" as const }),
];
