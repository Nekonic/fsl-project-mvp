import { cleanup, render } from "@testing-library/preact";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FOLLOW_EVERY_MS } from "./follow";
import { useResource } from "./hooks";

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

function joined(id: number) {
  return { id, kind: "player.joined", at: "2026-01-01T00:00:00Z", player_side: "defence", body: {} };
}

function RoundRead({ round }: { round: number }) {
  useResource("/api/rounds/{round_id}/", { params: { round_id: round } }, { refreshOn: { round, kinds: ["player.joined"] } });
  return null;
}

async function settle(): Promise<void> {
  for (let turn = 0; turn < 20; turn += 1) await Promise.resolve();
}

beforeEach(() => {
  document.cookie = "cr_csrf=token";
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("useResource refreshOn", () => {
  it("does not read again for events that were already there when the page opened, only for new ones", async () => {
    const reads: string[] = [];
    let fresh = false;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith("/api/rounds/71/events/")) {
        if (!url.includes("after=")) return json({ events: [joined(1), joined(2)], next: 2 });
        if (fresh && url.includes("after=2")) return json({ events: [joined(3)], next: 3 });
        return json({ events: [], next: url.includes("after=3") ? 3 : 2 });
      }
      reads.push(url);
      return json({ round: 71 });
    }));
    render(<RoundRead round={71} />);
    await settle();
    await vi.advanceTimersByTimeAsync(10);
    await settle();
    expect(reads).toEqual(["/api/rounds/71/"]);
    fresh = true;
    await vi.advanceTimersByTimeAsync(FOLLOW_EVERY_MS + 10);
    await settle();
    await vi.advanceTimersByTimeAsync(10);
    await settle();
    expect(reads).toEqual(["/api/rounds/71/", "/api/rounds/71/"]);
  });
});
