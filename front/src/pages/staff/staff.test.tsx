import { cleanup, render } from "@testing-library/preact";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SessionContext } from "../../api/hooks";
import { t } from "../../strings";
import { Users } from "./Users";

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Users", () => {
  const me = { user: "operator", approved: true, is_staff: true, site_origin: "" };

  it("offers no disable button on the signed-in account's own row", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith("/api/staff/blocks/")) return json([]);
      return json([
        { username: "operator", approved: true, is_staff: true, joined: "2026-01-01T00:00:00Z" },
        { username: "learner-one", approved: true, is_staff: false, joined: "2026-01-02T00:00:00Z" },
      ]);
    }));
    const page = render(
      <SessionContext.Provider value={{ me, loading: false, reload: () => undefined }}>
        <Users params={{}} />
      </SessionContext.Provider>,
    );
    await vi.waitFor(() => expect(page.container.textContent).toContain("learner-one"));
    const disables = [...page.container.querySelectorAll("button")].filter((button) => button.textContent === t("users.disable"));
    expect(disables.length).toBe(1);
    expect(page.container.textContent).toContain(t("users.self"));
  });
});
