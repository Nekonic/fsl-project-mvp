import { cleanup, render, screen, waitFor } from "@testing-library/preact";
import { afterEach, describe, expect, it, vi } from "vitest";
import { blockingScore, score } from "../../mock/fixtures/result";
import { t, tFor } from "../strings";
import { nodeLabel, zoneCaption } from "./Map";
import { Objectives } from "./Objectives";
import { presetKibana } from "./Kibana";
import { ScoreReport } from "./Score";

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
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ errors: [{ path: "", code: "not_seated" }] }), { status: 403 })));
    render(<Objectives round={41} side="attack" placement="main" />);
    await waitFor(() => expect(screen.getByText(t("error.not_seated"))).toBeTruthy());
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
    expect(screen.queryByText(t("result.posture_drift"))).toBeNull();
  });

  it("warns when the defence posture drifted", () => {
    render(<ScoreReport score={blockingScore} />);
    expect(screen.getByText(t("result.posture_drift"))).toBeTruthy();
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
