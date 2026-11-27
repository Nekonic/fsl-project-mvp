import { cleanup, render } from "@testing-library/preact";
import { afterEach, describe, expect, it } from "vitest";
import { t } from "../strings";
import { lootOf, SubmissionRow } from "./Loot";

afterEach(() => {
  cleanup();
});

describe("loot format", () => {
  it("reads the three accepted shapes", () => {
    expect(lootOf(`{"admin": "h1"}`)).toEqual({ admin: "h1" });
    expect(lootOf(`[["admin", "h1"]]`)).toEqual([["admin", "h1"]]);
    expect(lootOf(`[{"username": "admin", "hash": "h1"}]`)).toEqual([{ username: "admin", hash: "h1" }]);
  });

  it("refuses text that is not JSON or holds no username and hash pair", () => {
    for (const text of ["not json", "7", "[]", "{}", `[["admin"]]`, `[{"name": "admin"}]`, `"admin:h1"`]) expect(lootOf(text)).toBeUndefined();
  });
});

describe("loot result row", () => {
  it("says a miss once", () => {
    const row = render(<SubmissionRow submission={{ at: "2026-01-01T00:00:00Z", lost: false, objectives: [] }} />);
    expect(row.container.textContent?.split(t("loot.no_match")).length).toBe(2);
    expect(row.container.textContent).not.toContain(t("objective.lost"));
  });

  it("names what fell beside the lost mark", () => {
    const row = render(<SubmissionRow submission={{ at: "2026-01-01T00:00:00Z", lost: true, objectives: ["Board admin account"] }} />);
    expect(row.container.textContent).toContain("Board admin account");
    expect(row.container.textContent).toContain(t("objective.lost"));
    expect(row.container.textContent).not.toContain(t("loot.no_match"));
  });
});
