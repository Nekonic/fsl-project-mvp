import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, call, waitUntil } from "./client";
import { follow, holdLease, HEARTBEAT_EVERY_MS } from "./follow";

interface Answered {
  url: string;
  method: string;
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function answering(answer: (url: string, method: string) => Response) {
  const asked: Answered[] = [];
  const fetched = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    asked.push({ url, method });
    return answer(url, method);
  });
  vi.stubGlobal("fetch", fetched);
  return asked;
}

function eventsAfter(cursor: number, upTo: number, size: number) {
  const events = [];
  for (let id = cursor + 1; id <= Math.min(upTo, cursor + size); id += 1) {
    events.push({ id, kind: "alert.seen", at: "2026-01-01T00:00:00Z", seat_side: "defence", body: {} });
  }
  return { events, next: events.length ? events[events.length - 1]!.id : cursor };
}

beforeEach(() => {
  document.cookie = "cr_csrf=token";
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("follow", () => {
  it("reads the whole backlog before telling listeners, once", async () => {
    const asked = answering((url) => {
      const after = Number(new URL(url, "http://localhost").searchParams.get("after") ?? 0);
      return json(200, eventsAfter(after, 450, 200));
    });
    const batches: number[] = [];
    const stop = follow(901, (events) => batches.push(events.length));
    await vi.waitFor(() => expect(batches).toEqual([450]));
    expect(asked.filter((one) => one.url.includes("/events/")).length).toBe(4);
    stop();
  });
});

describe("holdLease", () => {
  it("beats while held, outlives a round's end and stops on the last release", async () => {
    vi.useFakeTimers();
    const asked = answering(() => json(200, { expires_at: "2026-01-01T00:30:00Z" }));
    const first = holdLease(77);
    const second = holdLease(5, 77);
    await vi.advanceTimersByTimeAsync(0);
    expect(asked.length).toBe(1);
    first();
    first();
    await vi.advanceTimersByTimeAsync(HEARTBEAT_EVERY_MS);
    expect(asked.length).toBe(2);
    second();
    await vi.advanceTimersByTimeAsync(HEARTBEAT_EVERY_MS * 3);
    expect(asked.length).toBe(2);
    expect(asked.every((one) => one.url === "/api/leases/77/heartbeat/" && one.method === "POST")).toBe(true);
  });

  it("stops beating once the lease is closed", async () => {
    vi.useFakeTimers();
    const asked = answering(() => json(409, { errors: [{ path: "", code: "lease_closed" }] }));
    holdLease(78);
    await vi.advanceTimersByTimeAsync(HEARTBEAT_EVERY_MS * 3);
    expect(asked.length).toBe(1);
  });
});

describe("client", () => {
  it("renews the CSRF cookie once and repeats the write", async () => {
    let writes = 0;
    const asked = answering((url) => {
      if (url === "/api/auth/csrf/") return json(200, { ok: true });
      writes += 1;
      return writes === 1 ? json(403, { errors: [{ path: "", code: "csrf_failed" }] }) : json(200, { expires_at: "x" });
    });
    await call("post", "/api/leases/{lease_id}/heartbeat/", { params: { lease_id: 3 } });
    expect(asked.map((one) => one.url)).toEqual(["/api/leases/3/heartbeat/", "/api/auth/csrf/", "/api/leases/3/heartbeat/"]);
  });

  it("keeps the hp block an attack route sends with its error", async () => {
    const hp = { origin: null, left: 0, budget: 100, origins_left: 0, spent: [], rule: {} };
    answering(() => json(409, { errors: [{ path: "", code: "origins_spent" }], hp }));
    const failed = await call("post", "/api/rounds/{round_id}/attack/origins/next/", { params: { round_id: 4 } }).catch((error: unknown) => error);
    expect(failed).toBeInstanceOf(ApiError);
    expect((failed as ApiError).code).toBe("origins_spent");
    expect((failed as ApiError).hp).toEqual(hp);
  });

  it("stops waiting when the wait is aborted between reads", async () => {
    vi.useFakeTimers();
    const abort = new AbortController();
    let reads = 0;
    const waiting = waitUntil(async () => {
      reads += 1;
      return false;
    }, (done) => done, { every: 1_000, signal: abort.signal }).catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(0);
    abort.abort();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(((await waiting) as DOMException).name).toBe("AbortError");
    expect(reads).toBe(1);
  });
});
