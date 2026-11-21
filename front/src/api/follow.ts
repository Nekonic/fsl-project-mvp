import { api, ApiError, type Schemas } from "./client";

export type RoundEvent = Schemas["Event"];
export type EventListener = (events: RoundEvent[]) => void;

export const FOLLOW_EVERY_MS = 3_000;
export const FOLLOW_BACKOFF_LIMIT_MS = 30_000;
export const FOLLOW_PAGES_PER_READ = 25;
export const HEARTBEAT_EVERY_MS = 60_000;
const STOPPING = new Set(["unknown_round", "not_a_player", "not_signed_in"]);
const ALLOCATION_GONE = new Set(["allocation_closed", "unknown_allocation", "not_operator", "not_a_player", "not_signed_in"]);

class Follower {
  readonly round: number;
  private cursor: number | undefined;
  private listeners = new Set<EventListener>();
  private seen: RoundEvent[] = [];
  private pollTimer: ReturnType<typeof setTimeout> | null = null;
  private failures = 0;
  private ended = false;
  private running = false;

  constructor(round: number) {
    this.round = round;
  }

  subscribe(listener: EventListener, replay: boolean): () => void {
    this.listeners.add(listener);
    if (replay && this.seen.length) listener(this.seen);
    this.start();
    return () => {
      this.listeners.delete(listener);
      if (!this.listeners.size) this.stop();
    };
  }

  private start(): void {
    if (this.running || this.ended) return;
    this.running = true;
    void this.poll();
  }

  private stop(): void {
    this.running = false;
    if (this.pollTimer) clearTimeout(this.pollTimer);
    this.pollTimer = null;
    if (followers.get(this.round) === this) followers.delete(this.round);
  }

  private next(delay: number): void {
    if (!this.running || this.ended) return;
    this.pollTimer = setTimeout(() => void this.poll(), delay);
  }

  private async readBacklog(): Promise<RoundEvent[]> {
    const fresh: RoundEvent[] = [];
    for (let page = 0; page < FOLLOW_PAGES_PER_READ && this.running; page += 1) {
      const said = await api.get("/api/rounds/{round_id}/events/", {
        params: { round_id: this.round },
        query: this.cursor === undefined ? {} : { after: this.cursor },
      });
      this.cursor = said.next;
      if (!said.events.length) break;
      fresh.push(...said.events);
    }
    return fresh;
  }

  private async poll(): Promise<void> {
    try {
      const fresh = await this.readBacklog();
      this.failures = 0;
      if (fresh.length && this.running) {
        this.seen = [...this.seen, ...fresh];
        if (fresh.some((event) => event.kind === "round.ended")) this.ended = true;
        this.listeners.forEach((listener) => listener(fresh));
      }
      this.next(FOLLOW_EVERY_MS);
    } catch (error) {
      if (error instanceof ApiError && error.errors.some((one) => STOPPING.has(one.code))) {
        this.stop();
        return;
      }
      this.failures += 1;
      this.next(Math.min(FOLLOW_EVERY_MS * 2 ** this.failures, FOLLOW_BACKOFF_LIMIT_MS));
    }
  }
}

const followers = new Map<number, Follower>();

function followerOf(round: number): Follower {
  let found = followers.get(round);
  if (!found) {
    found = new Follower(round);
    followers.set(round, found);
  }
  return found;
}

export function follow(round: number, listener: EventListener, replay = false): () => void {
  return followerOf(round).subscribe(listener, replay);
}

interface HeldAllocation {
  holders: number;
  timer: ReturnType<typeof setInterval>;
}

const heldAllocations = new Map<number, HeldAllocation>();

function dropAllocation(allocation: number): void {
  const held = heldAllocations.get(allocation);
  if (!held) return;
  clearInterval(held.timer);
  heldAllocations.delete(allocation);
}

function beat(allocation: number): void {
  api.post("/api/allocations/{allocation_id}/heartbeat/", { params: { allocation_id: allocation } }).catch((error: unknown) => {
    if (error instanceof ApiError && error.errors.some((one) => ALLOCATION_GONE.has(one.code))) dropAllocation(allocation);
  });
}

function nothingHeld(): void {
  return undefined;
}

export function holdAllocation(allocation: number | null | undefined): () => void;
export function holdAllocation(round: number | null | undefined, allocation: number | null | undefined): () => void;
export function holdAllocation(...given: Array<number | null | undefined>): () => void {
  const allocation = given[given.length - 1];
  if (!allocation) return nothingHeld;
  let held = heldAllocations.get(allocation);
  if (held) {
    held.holders += 1;
  } else {
    held = { holders: 1, timer: setInterval(() => beat(allocation), HEARTBEAT_EVERY_MS) };
    heldAllocations.set(allocation, held);
    beat(allocation);
  }
  const mine = held;
  let released = false;
  return () => {
    if (released || heldAllocations.get(allocation) !== mine) return;
    released = true;
    mine.holders -= 1;
    if (mine.holders <= 0) dropAllocation(allocation);
  };
}
