import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, call, REQUEST_TIMEOUT_MS, RULE_TEST_TIMEOUT_MS, waitUntil } from "./client";
import { follow, FOLLOW_EVERY_MS, holdAllocation, HEARTBEAT_EVERY_MS } from "./follow";

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
    events.push({ id, kind: "alert.seen", at: "2026-01-01T00:00:00Z", player_side: "defence", body: {} });
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

  it("marks the events already there when it starts as backlog and later ones as fresh", async () => {
    let upTo = 3;
    answering((url) => {
      const after = Number(new URL(url, "http://localhost").searchParams.get("after") ?? 0);
      return json(200, eventsAfter(after, upTo, 200));
    });
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const told: Array<[number, boolean]> = [];
    const stop = follow(902, (events, backlog) => told.push([events.length, backlog]));
    await vi.advanceTimersByTimeAsync(0);
    upTo = 5;
    await vi.advanceTimersByTimeAsync(FOLLOW_EVERY_MS);
    expect(told).toEqual([[3, true], [2, false]]);
    stop();
  });

  it("asks only for the kinds its listeners want, in one read", async () => {
    const asked = answering(() => json(200, { events: [], next: 0 }));
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const stops = [
      follow(903, () => undefined, false, ["round.ended"]),
      follow(903, () => undefined, false, ["rule.applied", "round.ended"]),
    ];
    await vi.advanceTimersByTimeAsync(0);
    const reads = asked.filter((one) => one.url.includes("/events/")).map((one) => new URL(one.url, "http://localhost").searchParams.get("kinds"));
    expect(reads).toEqual(["round.ended,rule.applied"]);
    stops.forEach((stop) => stop());
  });

  it("asks for every kind when one listener wants them all", async () => {
    const asked = answering(() => json(200, { events: [], next: 0 }));
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const stops = [follow(904, () => undefined, false, ["round.ended"]), follow(904, () => undefined)];
    await vi.advanceTimersByTimeAsync(0);
    expect(asked.filter((one) => one.url.includes("/events/")).map((one) => one.url)).toEqual(["/api/rounds/904/events/"]);
    stops.forEach((stop) => stop());
  });
});

describe("holdAllocation", () => {
  it("beats while held, outlives a round's end and stops on the last release", async () => {
    vi.useFakeTimers();
    const asked = answering(() => json(200, { expires_at: "2026-01-01T00:30:00Z" }));
    const first = holdAllocation(77);
    const second = holdAllocation(5, 77);
    await vi.advanceTimersByTimeAsync(0);
    expect(asked.length).toBe(1);
    first();
    first();
    await vi.advanceTimersByTimeAsync(HEARTBEAT_EVERY_MS);
    expect(asked.length).toBe(2);
    second();
    await vi.advanceTimersByTimeAsync(HEARTBEAT_EVERY_MS * 3);
    expect(asked.length).toBe(2);
    expect(asked.every((one) => one.url === "/api/allocations/77/heartbeat/" && one.method === "POST")).toBe(true);
  });

  it("stops beating once the allocation is closed", async () => {
    vi.useFakeTimers();
    const asked = answering(() => json(409, { errors: [{ path: "", code: "allocation_closed" }] }));
    holdAllocation(78);
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
    await call("post", "/api/allocations/{allocation_id}/heartbeat/", { params: { allocation_id: 3 } });
    expect(asked.map((one) => one.url)).toEqual(["/api/allocations/3/heartbeat/", "/api/auth/csrf/", "/api/allocations/3/heartbeat/"]);
  });

  it("names the code an attack route refuses with", async () => {
    answering(() => json(409, { errors: [{ path: "", code: "origins_spent" }] }));
    const failed = await call("post", "/api/rounds/{round_id}/attack/origins/next/", { params: { round_id: 4 } }).catch((error: unknown) => error);
    expect(failed).toBeInstanceOf(ApiError);
    expect((failed as ApiError).code).toBe("origins_spent");
  });

  it("gives up on an ordinary call at the request timeout but lets a rule test run longer", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    vi.stubGlobal("fetch", vi.fn((_: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    })));
    const ordinary = call("get", "/api/rounds/{round_id}/score/", { params: { round_id: 1 } }).catch((error: unknown) => error);
    const ruleTest = call("post", "/api/rounds/{round_id}/defence/ids/rules/test/", { params: { round_id: 1 }, body: { text: "" }, timeoutMs: RULE_TEST_TIMEOUT_MS }).catch((error: unknown) => error);
    let settled = false;
    void ruleTest.then(() => { settled = true; });
    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS + 1);
    expect(((await ordinary) as ApiError).code).toBe("timeout");
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(RULE_TEST_TIMEOUT_MS);
    expect(((await ruleTest) as ApiError).code).toBe("timeout");
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
