import { cleanup, fireEvent, render, screen } from "@testing-library/preact";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HEARTBEAT_EVERY_MS } from "../api/follow";
import { SessionContext } from "../api/hooks";
import { t, tFor } from "../strings";
import { Access } from "./Access";
import { DebriefReport, rowText } from "./Debrief";
import { safeNext } from "./Login";
import { Result } from "./Result";
import { RoundAttack } from "./RoundAttack";
import { RoundDefence } from "./RoundDefence";
import { RoundHeader, NOT_STARTED_READ_EVERY_MS } from "../console/RoundHeader";
import { setHash } from "../router";
import { RoundLobby } from "./RoundLobby";
import { wargameName } from "../wargame";

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
    lobbyWith([{ round: 70, wargame: "board", problem: 9, problem_title: "Draft problem", matchup: "atk_vs_bot", phase: "created", players: [human("attack", null), human("defence", "learner-one")] }]);
    expect(await screen.findByText("Draft problem")).toBeTruthy();
    expect(screen.queryByText(t("player.join"))).toBeNull();
  });

  it("shows no problem for a pvp round, which opens from the wargame", async () => {
    lobbyWith([{ round: 73, wargame: "board", problem: null, problem_title: null, matchup: "pvp", phase: "created", players: [human("attack", "learner-two"), human("defence", "learner-one")] }]);
    const row = (await screen.findByText(t("round.name", { round: 73 }))).closest("tr");
    expect(row?.textContent).toContain("—");
    expect(row?.textContent).not.toContain(wargameName("board"));
  });

  it("links a running round to the console of the player's own seat", async () => {
    lobbyWith([{ round: 71, wargame: "board", problem: null, problem_title: null, matchup: "pvp", phase: "running", players: [human("attack", "learner-two"), human("defence", "learner-one")] }]);
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
      if (url === "/api/problems/7/") return json({ id: 7, wargame: "board", side: "both", title: "Board problem", summary: "Short summary", matchups: ["def_vs_bot"], bot_steps: [], body });
      if (url.startsWith("/api/problems/")) return json([{ id: 7, wargame: "board", side: "both", title: "Board problem", summary: "Short summary", matchups: ["def_vs_bot"], bot_steps: [] }]);
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

describe("RoundLobby start", () => {
  it("says the round is starting while the start call runs", async () => {
    let started: (value: Response) => void = () => undefined;
    const round = { round: 81, wargame: "board", problem: null, problem_title: null, matchup: "pvp", phase: "created",
      players: [{ side: "attack", client: "human", username: "a", bot_name: "", step: "", bot_run: null, left_of_round_s: null },
        { side: "defence", client: "human", username: "b", bot_name: "", step: "", bot_run: null, left_of_round_s: null }] };
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/start/") && init?.method === "POST") return new Promise<Response>((resolve) => { started = resolve; });
      if (url.includes("/events/")) return Promise.resolve(json({ events: [], next: 0 }));
      if (url.endsWith("/heartbeat/")) return Promise.resolve(json({ expires_at: "2026-01-01T00:30:00Z" }));
      if (url.startsWith("/api/problems/") || url.startsWith("/api/bot-steps/")) return Promise.resolve(json([]));
      return Promise.resolve(json({ allocation: 66, wargame: "board", slot: 1, ready: true, expires_at: "2026-01-01T00:30:00Z", closed: null, rounds: [round] }));
    }));
    render(<RoundLobby params={{ allocation: "66" }} />);
    (await screen.findByText(t("lobby.start"))).closest("button")?.click();
    expect(await screen.findByText(t("lobby.starting"))).toBeTruthy();
    expect(screen.getByText(tFor("phase", "starting"))).toBeTruthy();
    expect(screen.queryByText(tFor("phase", "created"))).toBeNull();
    started(json({ round: 81, phase: "running" }));
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
      return json({ allocation: 64, wargame: "board", slot: 1, ready: true, expires_at: "2026-01-01T00:30:00Z", closed: null, rounds: [{ round: 72, problem: 9, problem_title: "Problem", matchup: "pve", phase: "running", players }] });
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

describe("debrief alert lines", () => {
  it("names a WAF access refusal by its status rather than the raw request line", () => {
    const row = { lane: "defence", kind: "alerts", at: null, engine: "waf", rule: "403", signature: "403 GET / HTTP/1.1", count: 1, rules: 1 };
    expect(rowText(row)).toBe(`${tFor("engine", "waf")} 접근 차단 1건 · 응답 코드 403`);
    expect(rowText(row)).not.toContain("HTTP/1.1");
  });

  it("says how many other rules a case's alert line folds in", () => {
    const row = { lane: "defence", kind: "alerts", at: null, engine: "waf", rule: "949110", signature: "Anomaly Score", count: 1982, rules: 4 };
    expect(rowText(row)).toBe(`${tFor("engine", "waf")} 알림 1,982건 · Anomaly Score 외 룰 3개`);
  });
});

describe("debrief origin change", () => {
  it("picks 으로 or 로 by how the address's last digit is read", () => {
    const switched = (ip: string) => rowText({ lane: "attack", kind: "origin.switched", at: null, ip });
    expect(switched("181.8.0.10")).toBe("출발지를 181.8.0.10으로 변경");
    expect(switched("5.188.10.13")).toBe("출발지를 5.188.10.13으로 변경");
    expect(switched("5.188.10.12")).toBe("출발지를 5.188.10.12로 변경");
    expect(switched("5.188.10.11")).toBe("출발지를 5.188.10.11로 변경");
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

describe("attack console of a wargame that takes no loot", () => {
  it("leaves the loot pane out of the rail and the side column", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/rounds/82/attack/state/") {
        return json({ round: 82, matchup: "pvp", phase: "running", started: null, ends_at: null, end_reason: "",
          brief: { title: "Corp", summary: "", body: "" }, target: { public_url: "http://corp.com/", hosts: ["corp.com"] },
          objectives: [], origins: [], remaining: { origin: null, left: 0, total: 0, spent: [] }, takes_loot: false });
      }
      if (url.startsWith("/api/rounds/82/events/")) return json({ events: [], next: 0 });
      return new Response(JSON.stringify({ errors: [{ path: "", code: "not_found" }] }), { status: 404, headers: { "Content-Type": "application/json" } });
    }));
    render(<RoundAttack params={{ round: "82" }} />);
    for (let turn = 0; turn < 4; turn += 1) await settle();
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).not.toContain(t("pane.loot"));
    expect(screen.queryByText(t("loot.title"))).toBeNull();
  });
});

describe("result of a round the viewer only played", () => {
  it("does not ask for an allocation the viewer does not operate", async () => {
    const asked: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      asked.push(url);
      if (url === "/api/rounds/81/") {
        return json({ round: 81, allocation: 9, wargame: "board", problem: null, matchup: "pvp", phase: "ended", players: [],
          started: null, ends_at: null, ended: null, end_reason: "ended_by_operator", operated: false });
      }
      if (url.startsWith("/api/rounds/81/events/")) return json({ events: [], next: 0 });
      return new Response(JSON.stringify({ errors: [{ path: "", code: "round_running" }] }), { status: 409, headers: { "Content-Type": "application/json" } });
    }));
    render(<Result params={{ round: "81" }} />);
    for (let turn = 0; turn < 4; turn += 1) await settle();
    expect(asked).toContain("/api/rounds/81/");
    expect(asked.filter((url) => url.startsWith("/api/allocations/"))).toEqual([]);
  });
});


describe("access page profile download", () => {
  it("saves the issued profile as a conf file named after the account, only while it is shown", async () => {
    const profile = "[Interface]\nPrivateKey = secret\n";
    const row = { public_key: "pub", server_public_key: "srv", address: "10.200.0.2", port: 51820, endpoint: "range:51820",
      targets: [], created: "2026-01-01T00:00:00Z", attached_round: null };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/vpn/profile/" && init?.method === "POST") return json({ ...row, profile });
      if (url === "/api/vpn/profile/") return json(row);
      return json([]);
    }));
    const saved: { name: string; blob: Blob }[] = [];
    let made: Blob | undefined;
    vi.stubGlobal("URL", class extends URL {
      static override createObjectURL(blob: Blob): string { made = blob; return "blob:profile"; }
      static override revokeObjectURL(): undefined { return undefined; }
    });
    const clicks = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      if (made) saved.push({ name: this.download, blob: made });
    });
    render(
      <SessionContext.Provider value={{ me: { user: "kim/a b", approved: true, is_staff: false, site_origin: "" }, loading: false, reload: () => undefined }}>
        <Access params={{}} />
      </SessionContext.Provider>,
    );
    for (let turn = 0; turn < 4; turn += 1) await settle();
    expect(screen.queryByText(t("access.vpn.download"))).toBeNull();
    fireEvent.click(screen.getByText(t("access.vpn.reissue")));
    fireEvent.click(await screen.findByText(t("access.vpn.download")));
    const [file] = saved;
    expect(saved.map((each) => each.name)).toEqual(["cr-kimab.conf"]);
    expect(file?.blob.type).toBe("text/plain");
    expect(await file?.blob.text()).toBe(profile);
    clicks.mockRestore();
  });
});

describe("RoundLobby slot", () => {
  it("names the range slot by its number, never by the stack name", async () => {
    allocationAnswering(67, null);
    const page = render(<RoundLobby params={{ allocation: "67" }} />);
    expect(await screen.findByText(t("slot.name", { slot: 1 }))).toBeTruthy();
    expect(page.container.textContent).not.toContain("cr-slot");
  });
});

function roundAnswering(round: number, phases: string[]) {
  const asked: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    asked.push(url);
    if (url.includes("/events/")) return json({ events: [], next: 0 });
    if (url.endsWith(`/api/rounds/${round}/`)) {
      const phase = phases.length > 1 ? phases.shift() : phases[0];
      return json({ round, wargame: "board", problem: null, matchup: "pvp", phase, allocation: null, ends_at: null, ended: null, end_reason: "", players: [] });
    }
    if (url.includes("/defence/alerts/")) return json({ alerts: [], next: 0, more: false, total: 0 });
    if (url.includes("/defence/traffic/")) return json({ by_origin: [], next: "" });
    return json([]);
  }));
  return asked;
}

describe("RoundHeader before the round runs", () => {
  it("says the round waits for the operator, then that it is starting, without a reload", async () => {
    roundAnswering(91, ["created", "starting"]);
    render(<RoundHeader round={91} side="defence" />);
    expect(await screen.findByText(t("round.created_banner"))).toBeTruthy();
    vi.advanceTimersByTime(NOT_STARTED_READ_EVERY_MS);
    expect(await screen.findByText(t("round.starting_banner"))).toBeTruthy();
    expect(screen.getByText(t("round.starting_detail"))).toBeTruthy();
    expect(screen.queryByText(t("round.created_banner"))).toBeNull();
  });
});

describe("defence console", () => {
  it("opens on the alerts and loads Kibana only once its tab is opened", async () => {
    history.replaceState(null, "", "/rounds/92/defence");
    const asked = roundAnswering(92, ["running"]);
    render(<RoundDefence params={{ round: "92" }} />);
    await vi.waitFor(() => expect(asked.some((url) => url.includes("/defence/alerts/"))).toBe(true));
    await settle();
    expect(asked.some((url) => url.includes("/defence/kibana/"))).toBe(false);
    setHash("kibana");
    await vi.waitFor(() => expect(asked.some((url) => url.includes("/defence/kibana/"))).toBe(true));
    history.replaceState(null, "", "/");
  });
});
