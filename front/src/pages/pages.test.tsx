import { cleanup, render, screen } from "@testing-library/preact";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HEARTBEAT_EVERY_MS } from "../api/follow";
import { SessionContext } from "../api/hooks";
import { t, tFor } from "../strings";
import { DebriefReport, rowText } from "./Debrief";
import { safeNext } from "./Login";
import { RoundLobby } from "./RoundLobby";
import { wargameName } from "./wargameText";

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

describe("RoundLobby rounds", () => {
  const learner = { user: "learner-one", approved: true, is_staff: false, site_origin: "" };

  function human(side: string, username: string | null) {
    return { side, client: "human", username, bot_name: "", step: "", bot_run: null };
  }

  function lobbyWith(rounds: unknown[]) {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/events/")) return json({ events: [], next: 0 });
      if (url.endsWith("/heartbeat/")) return json({ expires_at: "2026-01-01T00:30:00Z" });
      if (url.startsWith("/api/problems/") || url.startsWith("/api/bot-steps/")) return json([]);
      return json({ allocation: 63, wargame: "board", slot: 1, ready: true, expires_at: "2026-01-01T00:30:00Z", closed: null, rounds });
    }));
    return render(
      <SessionContext.Provider value={{ me: learner, loading: false, reload: () => undefined }}>
        <RoundLobby params={{ allocation: "63" }} />
      </SessionContext.Provider>,
    );
  }

  it("names an unpublished problem by the title on the round line and offers no second seat to a seated player", async () => {
    lobbyWith([{ round: 70, wargame: "board", problem: 9, problem_title: "Draft problem", kind: "round", matchup: "atk_vs_bot", phase: "created", players: [human("attack", null), human("defence", "learner-one")] }]);
    expect(await screen.findByText("Draft problem")).toBeTruthy();
    expect(screen.queryByText(t("player.join"))).toBeNull();
  });

  it("names a pvp round by its wargame", async () => {
    lobbyWith([{ round: 73, wargame: "board", problem: null, problem_title: null, kind: "round", matchup: "pvp", phase: "created", players: [human("attack", "learner-two"), human("defence", "learner-one")] }]);
    expect(await screen.findByText(wargameName("board"))).toBeTruthy();
  });

  it("links a running round to the console of the player's own seat", async () => {
    lobbyWith([{ round: 71, wargame: "board", problem: null, problem_title: null, kind: "round", matchup: "pvp", phase: "running", players: [human("attack", "learner-two"), human("defence", "learner-one")] }]);
    const link = (await screen.findByText(t("page.defence"))).closest("a");
    expect(link?.getAttribute("href")).toBe("/rounds/71/defence");
    expect(screen.queryByText(t("page.attack"))).toBeNull();
  });
});

describe("RoundLobby problem body", () => {
  it("shows the chosen problem's body as text with its line breaks, never as markup", async () => {
    const body = "Situation line\nGoal <b>line</b>";
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/events/")) return json({ events: [], next: 0 });
      if (url.endsWith("/heartbeat/")) return json({ expires_at: "2026-01-01T00:30:00Z" });
      if (url.startsWith("/api/bot-steps/")) return json([]);
      if (url === "/api/problems/7/") return json({ id: 7, kind: "round", wargame: "board", side: "both", title: "Board problem", summary: "Short summary", matchups: ["def_vs_bot"], bot_steps: [], body });
      if (url.startsWith("/api/problems/")) return json([{ id: 7, kind: "round", wargame: "board", side: "both", title: "Board problem", summary: "Short summary", matchups: ["def_vs_bot"], bot_steps: [] }]);
      return json({ allocation: 65, wargame: "board", slot: 1, ready: true, expires_at: "2026-01-01T00:30:00Z", closed: null, rounds: [] });
    }));
    render(<RoundLobby params={{ allocation: "65" }} />);
    (await screen.findByLabelText(tFor("matchup", "def_vs_bot"))).click();
    const shown = await screen.findByText((_, node) => node?.classList.contains("prose") === true && node.textContent === body);
    expect(shown.querySelector("b")).toBeNull();
    expect(screen.getByText(t("lobby.problem_body"))).toBeTruthy();
  });
});

describe("RoundLobby create", () => {
  it("opens a pvp round from the wargame with no problem", async () => {
    const posted: unknown[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/events/")) return json({ events: [], next: 0 });
      if (url.endsWith("/heartbeat/")) return json({ expires_at: "2026-01-01T00:30:00Z" });
      if (url.endsWith("/rounds/") && init?.method === "POST") {
        posted.push(JSON.parse(String(init.body)));
        return new Response(JSON.stringify({ round: 80, players: [], bot_tokens: {} }), { status: 201, headers: { "Content-Type": "application/json" } });
      }
      if (url.startsWith("/api/problems/") || url.startsWith("/api/bot-steps/")) return json([]);
      return json({ allocation: 65, wargame: "board", slot: 1, ready: true, expires_at: "2026-01-01T00:30:00Z", closed: null, rounds: [] });
    }));
    render(<RoundLobby params={{ allocation: "65" }} />);
    const submit = (await screen.findByText(t("lobby.create_submit"))).closest("button");
    await vi.waitFor(() => expect(submit?.disabled).toBe(false));
    submit?.click();
    await vi.waitFor(() => expect(posted).toEqual([{ matchup: "pvp", players: { attack: { open: true }, defence: { open: true } } }]));
  });
});

describe("bot stopped early", () => {
  const bot = { side: "attack", client: "bot", username: null, bot_name: "claude-code", step: "", bot_run: "finished" };

  it("says in the lobby when the bot stopped before the round ended", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/events/")) return json({ events: [], next: 0 });
      if (url.endsWith("/heartbeat/")) return json({ expires_at: "2026-01-01T00:30:00Z" });
      if (url.startsWith("/api/problems/") || url.startsWith("/api/bot-steps/")) return json([]);
      const players = [{ ...bot, left_of_round_s: 600 }, { side: "defence", client: "human", username: "learner-one", bot_name: "", step: "", bot_run: null }];
      return json({ allocation: 64, wargame: "board", slot: 1, ready: true, expires_at: "2026-01-01T00:30:00Z", closed: null, rounds: [{ round: 72, problem: 9, problem_title: "Problem", kind: "round", matchup: "pve", phase: "running", players }] });
    }));
    render(<RoundLobby params={{ allocation: "64" }} />);
    expect(await screen.findByText(`${tFor("bot_run", "finished")} · ${t("bot.stopped_early")}`)).toBeTruthy();
  });

  it("says in the debrief bot line when the bot stopped before the round ended", () => {
    const line = { side: "attack", step: "2", model: "m", status: "finished", exit: "", cost_usd: null, turns: null, refusals: 0, closing: "", left_of_round_s: 600 };
    render(<DebriefReport debrief={{ pending: false, bots: [line], card: null, timeline: [], objectives: [], score: null } as unknown as Parameters<typeof DebriefReport>[0]["debrief"]} />);
    expect(screen.getByText(`${tFor("bot_run", "finished")} · ${t("bot.stopped_early")}`)).toBeTruthy();
  });
});

describe("debrief of a pvp round", () => {
  it("leaves out the opponent bot section, since both players are people", () => {
    render(<DebriefReport debrief={{ pending: false, matchup: "pvp", bots: [], card: null, timeline: [], objectives: [], score: null } as unknown as Parameters<typeof DebriefReport>[0]["debrief"]} />);
    expect(screen.queryByText(t("debrief.bots"))).toBeNull();
  });
});

describe("debrief case title", () => {
  it("names a judged case by its title in the timeline when the row carries one", () => {
    expect(rowText({ lane: "attack", kind: "case.judged", at: null, case: "board-sqli-search", title: "Search SQLi", verdict: "tp" }))
      .toBe(t("debrief.row.case.judged", { case: "Search SQLi", verdict: tFor("verdict", "tp") }));
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
