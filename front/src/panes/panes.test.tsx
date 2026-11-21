import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/preact";
import { afterEach, describe, expect, it, vi } from "vitest";
import { score } from "../../mock/fixtures/result";
import { t, tFor } from "../strings";
import { nodeLabel, zoneCaption } from "./Map";
import { Objectives } from "./Objectives";
import { presetKibana } from "./Kibana";
import { ScoreReport } from "./Score";
import { VerdictNotices } from "./Verdicts";
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
  it("marks each objective achieved and detected, heads them with the objective score and counts the four verdicts", () => {
    render(<ScoreReport score={score} />);
    expect(cellsOf("Board accounts, partial")).toEqual(["Board accounts, partial", t("mark.yes"), t("mark.no")]);
    expect(cellsOf("Board admin account")).toEqual(["Board admin account", t("mark.no"), "—"]);
    expect(screen.getByText(t("result.objective_points", { points: "2" }))).toBeTruthy();
    const verdicts = ["tp", "fn", "fp", "tn"].map((verdict, index) => `${tFor("verdict", verdict)} ${[2, 1, 0, 6][index]}`);
    expect(screen.getByText(verdicts.join(" · "))).toBeTruthy();
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

  it("says when the files on the WAF are not the recorded version", async () => {
    wafAnswering(false);
    render(<Waf round={7} side="defence" placement="main" />);

    expect(await screen.findByText(t("waf.not_running"))).toBeTruthy();
  });
});

describe("VerdictNotices", () => {
  function judgedEvent(id: number, body: Record<string, unknown>) {
    return { id, kind: "case.judged", at: "2026-11-21T10:00:00Z", player_side: null, body };
  }

  it("shows each judged case as a notice in Korean, newest first, and closes one on request", async () => {
    let served = false;
    vi.stubGlobal("fetch", vi.fn(async () => {
      const events = served ? [] : [
        judgedEvent(1, { action: "1", case: "board-sqli-search", verdict: "tp", alerts: 3, corroborated: false }),
        judgedEvent(2, { action: "benign-4", case: "board-normal-search", verdict: "fp", alerts: 1, corroborated: null }),
      ];
      served = true;
      return new Response(JSON.stringify({ events, next: 2 }), { status: 200, headers: { "Content-Type": "application/json" } });
    }));
    render(<VerdictNotices round={41} />);

    const first = await screen.findByText(t("verdict_notice.line", { case: "board-normal-search", verdict: tFor("verdict", "fp") }));
    const second = screen.getByText(t("verdict_notice.line", { case: "board-sqli-search", verdict: tFor("verdict", "tp") }));
    expect(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText(`${t("verdict_notice.alerts", { count: 3 })} · ${t("verdict_notice.not_corroborated")}`)).toBeTruthy();
    expect(screen.getByText(t("verdict_notice.alerts", { count: 1 }))).toBeTruthy();

    fireEvent.click(screen.getAllByText(t("verdict_notice.close"))[0] as HTMLElement);
    await waitFor(() => expect(screen.queryByText(t("verdict_notice.line", { case: "board-normal-search", verdict: tFor("verdict", "fp") }))).toBeNull());
    expect(screen.getByText(t("verdict_notice.line", { case: "board-sqli-search", verdict: tFor("verdict", "tp") }))).toBeTruthy();
  });
});
