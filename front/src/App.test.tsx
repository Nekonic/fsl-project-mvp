import { cleanup, fireEvent, render, screen } from "@testing-library/preact";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { t } from "./strings";

interface Asked {
  url: string;
  method: string;
}

function json(status: number, body: unknown): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const notSignedIn = () => json(401, { errors: [{ path: "", code: "not_signed_in" }] });

function server(signedIn: { value: boolean }, refuse: (url: string) => boolean = () => false) {
  const asked: Asked[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    asked.push({ url, method });
    if (url === "/api/auth/logout/") {
      signedIn.value = false;
      return json(204, null);
    }
    if (!signedIn.value || refuse(url)) return notSignedIn();
    if (url === "/api/me/") return json(200, { user: "learner", is_staff: false, approved: true, site_origin: "" });
    return json(200, []);
  }));
  return asked;
}

async function settle(): Promise<void> {
  for (let turn = 0; turn < 20; turn += 1) await new Promise((resolve) => setTimeout(resolve, 0));
}

beforeEach(() => {
  document.cookie = "cr_csrf=token";
  history.replaceState(null, "", "/");
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("signing out", () => {
  it("ends the session, lands on the sign-in page once and asks for nothing more", async () => {
    const signedIn = { value: true };
    const asked = server(signedIn);
    render(<App />);
    await settle();
    fireEvent.click(await screen.findByText(t("auth.sign_out")));
    await settle();
    expect(asked.filter((one) => one.url === "/api/auth/logout/" && one.method === "POST")).toHaveLength(1);
    expect(location.pathname).toBe("/login");
    expect(location.search).toBe("");
    expect(screen.getByRole("button", { name: t("auth.submit") })).toBeTruthy();
    const settled = asked.length;
    await settle();
    await new Promise((resolve) => setTimeout(resolve, 50));
    await settle();
    expect(asked.slice(settled)).toEqual([]);
    expect(asked.filter((one) => one.url.startsWith("/api/") && !["/api/me/", "/api/auth/logout/", "/api/auth/csrf/"].includes(one.url.split("?")[0]!)).length).toBeLessThanOrEqual(4);
  });

  it("keeps the pane of a console page in the address it sends a signed-out viewer back to", async () => {
    server({ value: false });
    history.replaceState(null, "", "/rounds/483/defence#waf");
    render(<App />);
    await settle();
    expect(location.pathname).toBe("/login");
    expect(new URLSearchParams(location.search).get("next")).toBe("/rounds/483/defence#waf");
  });

  it("sends the viewer to sign in once when any call says the session is gone", async () => {
    const signedIn = { value: true };
    const asked = server(signedIn, (url) => url.startsWith("/api/rounds/"));
    render(<App />);
    await settle();
    await settle();
    expect(location.pathname).toBe("/login");
    const settled = asked.length;
    await new Promise((resolve) => setTimeout(resolve, 50));
    await settle();
    expect(asked.slice(settled)).toEqual([]);
    expect(asked.filter((one) => one.url === "/api/problems/").length).toBe(1);
  });
});
