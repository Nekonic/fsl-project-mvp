import { cleanup, render } from "@testing-library/preact";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HEARTBEAT_EVERY_MS } from "../api/follow";
import { safeNext } from "./Login";
import { RoundLobby } from "./RoundLobby";

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

function allocationAnswering(allocation: number, closed: string | null) {
  const beats: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/heartbeat/") && init?.method === "POST") {
      beats.push(url);
      return json({ expires_at: "2026-01-01T00:30:00Z" });
    }
    if (url.startsWith("/api/problems/") || url.startsWith("/api/bot-steps/")) return json([]);
    return json({ allocation, wargame: "board", slot: 1, ready: true, expires_at: "2026-01-01T00:30:00Z", closed, rounds: [] });
  }));
  return beats;
}

async function settle(): Promise<void> {
  for (let turn = 0; turn < 5; turn += 1) await Promise.resolve();
}

beforeEach(() => {
  document.cookie = "cr_csrf=token";
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("RoundLobby", () => {
  it("holds an open allocation from load until it leaves the page", async () => {
    const beats = allocationAnswering(61, null);
    const page = render(<RoundLobby params={{ allocation: "61" }} />);
    await vi.waitFor(() => expect(beats).toEqual(["/api/allocations/61/heartbeat/"]));
    vi.advanceTimersByTime(HEARTBEAT_EVERY_MS);
    await vi.waitFor(() => expect(beats.length).toBe(2));
    page.unmount();
    vi.advanceTimersByTime(HEARTBEAT_EVERY_MS * 3);
    await settle();
    expect(beats.length).toBe(2);
  });

  it("never beats for a closed allocation", async () => {
    const beats = allocationAnswering(62, "2026-01-01T00:10:00Z");
    const page = render(<RoundLobby params={{ allocation: "62" }} />);
    await vi.waitFor(() => expect(page.container.textContent).toContain("62"));
    vi.advanceTimersByTime(HEARTBEAT_EVERY_MS * 3);
    await settle();
    expect(beats).toEqual([]);
  });
});

describe("safeNext", () => {
  const site = "http://range.example:8002";

  it("keeps a console path", () => {
    expect(safeNext("/rounds/12/attack", site)).toBe("/rounds/12/attack");
  });

  it("keeps a site pane address on exactly the configured site origin", () => {
    expect(safeNext("http://range.example:8002/site/12/board.com/posts/1/", site)).toBe("http://range.example:8002/site/12/board.com/posts/1/");
    expect(safeNext("https://site.example/site/12/board.com/", "https://site.example")).toBe("https://site.example/site/12/board.com/");
  });

  it.each([
    [null, site],
    ["//evil.example/", site],
    ["/\\evil.example/", site],
    ["/login/?next=/", site],
    ["http://evil.example/site/12/board.com/", site],
    ["https://range.example:8002/site/12/board.com/", site],
    ["http://range.example:8000/site/12/board.com/", site],
    ["http://range.example:8002/login/", site],
    ["http://range.example:8002/site/../login/", site],
    ["javascript:alert(1)", site],
    ["http://range.example:8002/site/12/board.com/", undefined],
  ])("sends %s home", (next, origin) => {
    expect(safeNext(next, origin)).toBe("/");
  });
});
