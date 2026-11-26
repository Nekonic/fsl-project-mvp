import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/preact";
import { afterEach, describe, expect, it, vi } from "vitest";
import { score } from "../../mock/fixtures/result";
import { t, tFor } from "../strings";
import { playerFacts } from "../console/RoundHeader";
import { IdsRules } from "./IdsRules";
import { nodeLabel, zoneCaption } from "./Map";
import { Objectives, objectivesChanged } from "./Objectives";
import { presetKibana } from "./Kibana";
import { rememberTest, RuleTestTable } from "./RuleTestTable";
import { ScoreReport } from "./Score";
import { wargameLabel } from "./staff/catalog";
import { VERDICT_NOTICE_MS, VerdictNotices } from "./Verdicts";
import { Waf } from "./Waf";

const objectives = [
  { key: "objective-a", name: "Objective A", state: "lost", seen: false },
  { key: "objective-b", name: "Objective B", state: "kept", seen: false },
];

function answering(body: unknown) {
  return vi.fn(async () => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Objectives", () => {
  it("shows each objective with its Korean state and the tally", async () => {
    vi.stubGlobal("fetch", answering({ objectives }));
    render(<Objectives round={41} side="defence" placement="aside-lead" />);
    await waitFor(() => expect(screen.getByText("Objective A")).toBeTruthy());
    expect(screen.getByText(t("objective.tally", { lost: 1, total: 2 }))).toBeTruthy();
    expect(screen.getAllByText(t("objective.lost")).length).toBe(1);
    expect(screen.getByText(t("objective.unseen"))).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/\b(TP|FP|FN|TN)\b/);
  });

  it("reads the objectives again when another pane says they changed", async () => {
    const fetched = answering({ objectives });
    vi.stubGlobal("fetch", fetched);
    render(<Objectives round={42} side="attack" placement="aside-lead" />);
    await waitFor(() => expect(screen.getByText("Objective A")).toBeTruthy());
    const reads = () => (fetched.mock.calls as unknown as Array<[RequestInfo | URL]>).filter(([url]) => String(url).endsWith("/attack/state/")).length;
    expect(reads()).toBe(1);
    objectivesChanged(42);
    await waitFor(() => expect(reads()).toBe(2));
  });

  it("shows the API's refusal in Korean", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ errors: [{ path: "", code: "not_a_player" }] }), { status: 403 })));
    render(<Objectives round={41} side="attack" placement="main" />);
    await waitFor(() => expect(screen.getByText(t("error.not_a_player"))).toBeTruthy());
  });
});

function cellsOf(text: string): string[] {
  const row = screen.getByText(text).closest("tr");
  if (!row) throw new Error(`no row holds ${text}`);
  return [...row.querySelectorAll("td")].map((cell) => cell.textContent ?? "");
}

describe("ScoreReport", () => {
  it("marks each lost objective detected and responded with the response time, heads them with the objective score and counts the four verdicts", () => {
    render(<ScoreReport score={score} />);
    expect(cellsOf("Board accounts, partial")).toEqual(["Board accounts, partial", t("objective.lost"), t("mark.yes"), t("mark.yes"), t("result.weight_half"), t("result.seconds", { seconds: "42" })]);
    expect(cellsOf("Board admin account")).toEqual(["Board admin account", t("objective.kept"), "—", "—", "—", "—"]);
    expect(screen.getByText(t("result.objective_points", { points: "1" }))).toBeTruthy();
    expect(screen.getByText(t("result.objective_points_rule"))).toBeTruthy();
    const verdicts = ["tp", "fn", "fp", "tn"].map((verdict, index) => `${tFor("verdict", verdict)} ${[2, 1, 0, 6][index]}`);
    expect(screen.getByText(verdicts.join(" · "))).toBeTruthy();
  });

  it("shows a pending mark instead of detection, response and weight until the judge", () => {
    render(<ScoreReport score={{ ...score, pending: true }} />);
    const pending = t("mark.pending");
    expect(cellsOf("Board accounts, partial")).toEqual(["Board accounts, partial", t("objective.lost"), pending, pending, pending, "—"]);
    expect(screen.getByText(t("result.objective_points_pending", { points: "1" }))).toBeTruthy();
  });

  it("folds every firing of a case into one row with its count and keeps the API's totals", () => {
    const fired = { case: "board-normal-search", verdict: "tn" as const, alerts: 0, corroborated: null };
    const perCase = [...Array.from({ length: 11 }, () => fired), { ...fired, verdict: "fp" as const, alerts: 2 }];
    render(<ScoreReport score={{ ...score, outcomes: { ...score.outcomes, per_case: perCase, totals: { tp: 0, fn: 0, fp: 1, tn: 11 } } }} />);
    const cells = cellsOf("board-normal-search");
    expect(screen.getAllByText("board-normal-search").length).toBe(1);
    expect(cells[2]).toBe("12");
    expect(cells[3]).toContain(t("result.verdict_times", { verdict: tFor("verdict", "tn"), count: "11" }));
    expect(cells[3]).toContain(t("result.verdict_times", { verdict: tFor("verdict", "fp"), count: "1" }));
    expect(screen.getByText(["tp", "fn", "fp", "tn"].map((verdict, index) => `${tFor("verdict", verdict)} ${[0, 0, 1, 11][index]}`).join(" · "))).toBeTruthy();
  });

  it("counts the free actions per origin and shows no explanatory note", () => {
    render(<ScoreReport score={score} />);
    expect(screen.getByRole("columnheader", { name: t("result.actions") })).toBeTruthy();
    expect(cellsOf("5.188.10.10")[1]).toBe("998");
    expect(cellsOf("181.8.0.10")[1]).toBe("12");
    expect(document.body.textContent).not.toContain("one_case_one_decision");
  });
});

describe("Map labels", () => {
  it("names zones and devices through the string table", () => {
    expect(zoneCaption({ id: "board", caption: "database", owner: "board", subnet: "172.18.0.0/24", box: [0, 0, 1, 1] })).toBe(`${t("topology.zone.database", { owner: "board" })} 172.18.0.0/24`);
    expect(nodeLabel({ id: "router", kind: "router", name: "router" })).toBe(t("topology.name.router"));
    expect(nodeLabel({ id: "board.com", kind: "server", name: "board.com" })).toBe("board.com");
    expect(nodeLabel({ id: "a", kind: "address", text: "10.0.0.1", more: 2 })).toBe(t("topology.address_more", { address: "10.0.0.1", more: 2 }));
  });
});

describe("Kibana preset", () => {
  it("marks Kibana's first-run callouts seen and forgets the last search", () => {
    const kept = new Map<string, string>();
    const store = {
      setItem: (key: string, value: string) => void kept.set(key, value),
      getItem: (key: string) => kept.get(key) ?? null,
      removeItem: (key: string) => void kept.delete(key),
    } as unknown as Storage;
    store.setItem("discover:searchText", "left over");
    presetKibana(store);
    expect(kept.size).toBeGreaterThan(0);
    expect([...kept.values()].every((value) => value === "true")).toBe(true);
    expect(store.getItem("discover:searchText")).toBeNull();
  });
});

describe("Waf", () => {
  const HTTP = "/etc/waf/http.conf";
  const SETUP = "/etc/waf/crs-setup.conf";

  function wafAnswering(recorded: boolean) {
    const sent: Array<{ url: string; body: unknown }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const reply = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
      if (init?.method === "POST") {
        sent.push({ url, body: JSON.parse(String(init.body)) });
        return reply({ ok: true, errors: [] });
      }
      if (url.includes("/events/")) return reply({ events: [], next: 0 });
      if (url.endsWith("/waf/versions/")) {
        return reply([{ version: 2, applied_at: "2026-11-21T10:00:00Z", tested: null, same_as_tested: false, sha: "9be1c04f7a3d2e58aa", source: "terminal" }]);
      }
      return reply({ files: [{ path: SETUP, text: "deny all;\n" }, { path: HTTP, text: "" }], sha: "9be1c04f7a3d2e58aa", version: 2, recorded });
    }));
    return sent;
  }

  it("shows the current text of each file, the version history with where it came from, and checks only the changed file", async () => {
    document.cookie = "cr_csrf=token";
    const sent = wafAnswering(true);
    render(<Waf round={7} side="defence" placement="main" />);

    const editor = await screen.findByLabelText("crs-setup.conf");
    expect((editor as HTMLTextAreaElement).value).toBe("deny all;\n");
    expect(await screen.findByText(t("versions.source.terminal"))).toBeTruthy();
    expect(screen.getByText("9be1c04f7a3d")).toBeTruthy();
    expect(screen.queryByText(t("waf.not_running"))).toBeNull();

    fireEvent.input(editor, { target: { value: "deny 203.0.113.9;\n" } });
    fireEvent.click(screen.getByText(t("common.validate")));

    await waitFor(() => expect(sent.length).toBe(1));
    expect(sent[0]?.url).toContain("/api/rounds/7/defence/waf/check/");
    expect(sent[0]?.body).toEqual({ files: { [SETUP]: "deny 203.0.113.9;\n" } });
  });

  it.each([true, false])("offers apply only after a test of the edited files passed (passed: %s)", async (passed) => {
    document.cookie = "cr_csrf=token";
    wafAnswering(true);
    const answered = vi.mocked(fetch).getMockImplementation()!;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST" && String(input).endsWith("/waf/test/")) {
        return new Response(JSON.stringify({ test: 5, ok: true, passed, failed_benign: passed ? [] : ["board-normal-search"], untested_benign: [], errors: [], cases: [], totals: { tp: 0, fn: 0, fp: passed ? 0 : 1, tn: 0 }, untested: [], against_applied: [] }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      return answered(input, init);
    }));
    render(<Waf round={7} side="defence" placement="main" />);

    fireEvent.input(await screen.findByLabelText("crs-setup.conf"), { target: { value: "deny 203.0.113.9;\n" } });
    const apply = screen.getByText(t("rules.apply")).closest("button")!;
    expect(apply.disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: t("rules.test") }));

    if (passed) await waitFor(() => expect(screen.getByText(t("rule_test.passed.waf"))).toBeTruthy());
    else await waitFor(() => expect(screen.getByText(t("rule_test.failed_benign", { cases: "board-normal-search" }))).toBeTruthy());
    expect(apply.disabled).toBe(!passed);
  });

  it("says when the files on the WAF are not the recorded version", async () => {
    wafAnswering(false);
    render(<Waf round={7} side="defence" placement="main" />);

    expect(await screen.findByText(t("waf.not_running"))).toBeTruthy();
  });
});

describe("VerdictNotices", () => {
  type Judged = { id: number; kind: string; at: string; player_side: null; body: Record<string, unknown> };

  function judgedEvent(id: number, body: Record<string, unknown>): Judged {
    return { id, kind: "case.judged", at: "2026-11-21T10:00:00Z", player_side: null, body };
  }

  function servingEvents(backlog: Judged[]) {
    const released = [...backlog];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const after = Number(new URL(String(input), "http://localhost").searchParams.get("after") ?? 0);
      const events = released.filter((event) => event.id > after);
      const next = events.length ? events[events.length - 1]!.id : after;
      return new Response(JSON.stringify({ events, next }), { status: 200, headers: { "Content-Type": "application/json" } });
    }));
    return (fresh: Judged[]) => released.push(...fresh);
  }

  const line = (name: string, verdict: string) => t("verdict_notice.line", { case: name, verdict: tFor("verdict", verdict) });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows only cases judged after the page opened, leaves out normal traffic that passed, newest first", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const release = servingEvents([judgedEvent(1, { case: "board-sqli-old", verdict: "tp", alerts: 1, corroborated: true })]);
    render(<VerdictNotices round={1041} />);
    await vi.advanceTimersByTimeAsync(0);
    release([
      judgedEvent(2, { case: "board-sqli-search", verdict: "tp", alerts: 3, corroborated: false }),
      judgedEvent(3, { case: "board-normal-post-list", verdict: "tn", alerts: 0, corroborated: null }),
      judgedEvent(4, { case: "board-normal-search", verdict: "fp", alerts: 1, corroborated: null }),
    ]);
    await vi.advanceTimersByTimeAsync(3_000);

    const first = screen.getByText(line("board-normal-search", "fp"));
    const second = screen.getByText(line("board-sqli-search", "tp"));
    expect(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText(`${t("verdict_notice.alerts", { count: 3 })} · ${t("verdict_notice.not_corroborated")}`)).toBeTruthy();
    expect(screen.queryByText(line("board-sqli-old", "tp"))).toBeNull();
    expect(screen.queryByText(line("board-normal-post-list", "tn"))).toBeNull();
  });

  it("closes a notice on request and every other one by itself after a few seconds", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const release = servingEvents([]);
    render(<VerdictNotices round={1042} />);
    await vi.advanceTimersByTimeAsync(0);
    release([
      judgedEvent(1, { case: "board-sqli-search", verdict: "tp", alerts: 3, corroborated: true }),
      judgedEvent(2, { case: "board-normal-search", verdict: "fp", alerts: 1, corroborated: null }),
    ]);
    await vi.advanceTimersByTimeAsync(3_000);

    fireEvent.click(screen.getAllByText(t("verdict_notice.close"))[0] as HTMLElement);
    await vi.advanceTimersByTimeAsync(0);
    expect(screen.queryByText(line("board-normal-search", "fp"))).toBeNull();
    expect(screen.getByText(line("board-sqli-search", "tp"))).toBeTruthy();
    await vi.advanceTimersByTimeAsync(VERDICT_NOTICE_MS);
    expect(screen.queryByText(line("board-sqli-search", "tp"))).toBeNull();
  });
});

describe("RuleTestTable", () => {
  it("folds repeated alerts of one rule into one line with a count", () => {
    const alert = { rule: "942100", signature: "SQL Injection Attack Detected via libinjection" };
    render(<RuleTestTable cases={[{ case: "board-sqli-search", malicious: true, verdict: "tp", corroborated: true, recorded_run: false, alerts: [alert, alert, alert, { rule: "949110", signature: "Inbound Anomaly Score Exceeded" }] }]} />);
    expect(screen.getAllByText("942100").length).toBe(1);
    expect(screen.getByText(t("rule_test.alert_times", { count: 3 }))).toBeTruthy();
    expect(screen.getByText("949110")).toBeTruthy();
  });
});

describe("IdsRules", () => {
  it("shows the last test of the rules on the sensor after a reload", async () => {
    const rules = "alert http any any -> any any (msg:\"sqli\"; sid:1000001;)\n";
    rememberTest(51, "ids", rules, 9);
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const reply = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url.includes("/events/")) return reply({ events: [], next: 0 });
      if (url.endsWith("/versions/")) return reply([]);
      if (url.endsWith("/tests/9/")) return reply({ test: 9, ok: true, passed: true, failed_benign: [], untested_benign: [], errors: [], cases: [], totals: { tp: 1, fn: 0, fp: 0, tn: 6 }, untested: [], against_applied: [] });
      return reply({ text: rules, version: 1, recorded: true });
    }));
    render(<IdsRules round={51} side="defence" placement="main" />);

    expect(await screen.findByText(t("rule_test.numbered", { test: 9 }))).toBeTruthy();
    expect(screen.getByText(t("rule_test.passed.ids"))).toBeTruthy();
    expect(screen.queryByText(t("rule_test.not_yet.ids"))).toBeNull();
  });
});

describe("RoundHeader players", () => {
  it("says how the opponent bot's run ended", () => {
    const facts = playerFacts([
      { side: "attack", client: "bot", username: null, bot_name: "claude-code", step: "2", bot_run: "failed" },
      { side: "defence", client: "human", username: "learner-one", bot_name: "", step: "", bot_run: null },
    ]);
    expect(facts[0]?.value).toBe(`${t("round.player_bot", { name: tFor("bot_step", "2") })} · ${tFor("bot_run", "failed")}`);
    expect(facts[1]?.value).toBe("learner-one");
  });
});

describe("staff wargame label", () => {
  it("names the wargame in Korean beside its id", () => {
    expect(wargameLabel([{ id: "board", title: "Board" } as Parameters<typeof wargameLabel>[0][number]], "board")).toBe(`${t("wargame.board")} · board`);
  });
});
