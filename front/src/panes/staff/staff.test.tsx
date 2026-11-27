import { cleanup, fireEvent, render } from "@testing-library/preact";
import { afterEach, describe, expect, it, vi } from "vitest";
import { navigate } from "../../router";
import { t } from "../../strings";
import { LineList } from "../../ui";
import { fieldName } from "./document";
import { ProblemEditor } from "./ProblemEditor";

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

const STORED = {
  problem: { id: 12, revision: 3, kind: "round", wargame: "board", side: "defence", title: "Placeholder round", summary: "", body: "", published: false },
  round: { matchups: ["def_vs_bot"], posture: null, probe_cases: [], objectives: [], benign_every_s: 60, time_limit_s: 900, bot_steps: [], cards: [] },
  start_posture: null,
};

function editorServer(validated: Array<Record<string, unknown>> = []) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.startsWith("/api/staff/problems/validate/")) return json({ ok: validated.length === 0, errors: validated });
    if (url.startsWith("/api/staff/problems/12/")) return json(STORED);
    if (url.startsWith("/api/staff/wargames/")) return json([{ id: "board", title: "board", cards: [], objectives: [] }]);
    return json([]);
  }));
}

async function editor() {
  const page = render(<ProblemEditor problemId={12} onSaved={() => undefined} onDeleted={() => undefined} />);
  await vi.waitFor(() => expect(page.container.querySelector("input")).not.toBeNull());
  return page;
}

function buttonNamed(root: Element, name: string): HTMLButtonElement {
  const found = [...root.querySelectorAll("button")].find((button) => button.textContent === name);
  if (!found) throw new Error(`no button ${name}`);
  return found;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  history.replaceState(null, "", "/");
});

describe("problem editor field names", () => {
  it("names a field in Korean rather than by its document path", () => {
    expect(fieldName("problem.title")).toBe(t("staff.problem.title"));
    expect(fieldName("round.probe_cases[1]")).toBe(t("staff.field.nth", { field: t("staff.round.probe_cases"), n: 2 }));
    expect(fieldName("round.posture")).toBe(t("staff.problem.start_posture"));
  });
});

describe("LineList", () => {
  it("disables the add button while the input is empty", () => {
    const page = render(<LineList lines={[]} removeLabel="x" onRemove={() => undefined} addLabel="add" placeholder="id" onAdd={() => undefined} />);
    expect(buttonNamed(page.container, "add").disabled).toBe(true);
    fireEvent.input(page.getByLabelText("id"), { target: { value: "case-one" } });
    expect(buttonNamed(page.container, "add").disabled).toBe(false);
  });

  it("shows the refusal and keeps the typed text when the add is refused", async () => {
    const added: string[] = [];
    const page = render(<LineList lines={[]} removeLabel="x" onRemove={() => undefined} addLabel="add" placeholder="id"
      onAdd={async (text) => { added.push(text); return "refused"; }} />);
    fireEvent.input(page.getByLabelText("id"), { target: { value: "no-such-case" } });
    fireEvent.click(buttonNamed(page.container, "add"));
    await vi.waitFor(() => expect(page.container.textContent).toContain("refused"));
    expect(added).toEqual(["no-such-case"]);
    expect((page.getByLabelText("id") as HTMLInputElement).value).toBe("no-such-case");
  });
});

describe("ProblemEditor", () => {
  it("shows the start defence setting once", async () => {
    editorServer();
    const page = await editor();
    const labels = [...page.container.querySelectorAll(".field-label, .label")]
      .filter((node) => node.textContent?.trim() === t("staff.problem.start_posture"));
    expect(labels.length).toBe(1);
  });

  it("refuses an unknown case at add time with the server's message", async () => {
    editorServer([{ path: "round.probe_cases[0]", code: "unknown_case" }]);
    const page = await editor();
    fireEvent.input(page.getByLabelText(t("staff.round.case_placeholder")), { target: { value: "no-such-case" } });
    fireEvent.click(buttonNamed(page.container, t("staff.round.case_add")));
    await vi.waitFor(() => expect(page.container.textContent).toContain(t("error.unknown_case")));
    expect(page.container.querySelector(".case-line")).toBeNull();
  });

  it("asks before leaving with unsaved edits and stays when the user declines", async () => {
    editorServer();
    history.replaceState(null, "", "/staff/problems/12");
    const page = await editor();
    const asked = vi.fn(() => false);
    vi.stubGlobal("confirm", asked);
    navigate("/staff/users");
    expect(asked).not.toHaveBeenCalled();
    history.replaceState(null, "", "/staff/problems/12");
    fireEvent.input(page.getByDisplayValue("Placeholder round"), { target: { value: "Changed" } });
    await vi.waitFor(() => expect(page.container.textContent).toContain("Changed"));
    navigate("/staff/users");
    expect(asked).toHaveBeenCalledWith(t("staff.unsaved"));
    expect(location.pathname).toBe("/staff/problems/12");
  });
});
