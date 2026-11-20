import type { IncomingMessage, ServerResponse } from "node:http";
import type { Plugin, ViteDevServer } from "vite";
import type { Answer, Fixture } from "./fixture";

const VARIANT_COOKIE = "mock_variant";
const VARIANT_ROUTE = "/__mock/variant/";

const STAND_INS = [
  {
    prefix: "/vm-terminal/",
    page: (path: string) => `<!doctype html><body style="margin:0;background:#0B1020;color:#D1D5DB;font:13px/1.6 monospace;padding:12px 14px"><span style="color:#4ADE80">${path.includes("/attack/") ? "kali@kali" : "analyst@waf"}</span>:~$ </body>`,
  },
  {
    prefix: "/kibana/",
    page: () => `<!doctype html><body style="margin:0;display:flex;align-items:center;justify-content:center;height:100vh;background:#F8FAFC;color:#556275;font:13px sans-serif">Kibana Discover stand-in</body>`,
  },
];

function patternOf(path: string): RegExp {
  const source = path.replace(/[.*+?^$()|[\]\\]/g, "\\$&").replace(/\\?\{(\w+)\\?\}/g, "(?<$1>[^/]+)");
  return new RegExp(`^${source}$`);
}

function cookieOf(request: IncomingMessage, name: string): string {
  const found = (request.headers.cookie ?? "").split(/;\s*/).find((part) => part.startsWith(`${name}=`));
  return found ? decodeURIComponent(found.slice(name.length + 1)) : "";
}

async function bodyOf(request: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  for await (const chunk of request) chunks.push(chunk as Buffer);
  const text = Buffer.concat(chunks).toString("utf-8");
  if (!text) return undefined;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function answered(response: ServerResponse, answer: Answer): void {
  response.statusCode = answer.status;
  for (const [name, value] of Object.entries(answer.headers ?? {})) response.setHeader(name, value);
  if (answer.status === 204 || answer.body === undefined) {
    response.end();
    return;
  }
  response.setHeader("Content-Type", "application/json");
  response.end(JSON.stringify(answer.body));
}

export function chosen(fixtures: Fixture[], method: string, path: string, variant: string) {
  const fitting = fixtures
    .filter((fixture) => fixture.method === method)
    .map((fixture) => ({ fixture, found: patternOf(fixture.path).exec(path) }))
    .filter((one) => one.found);
  const pick = fitting.find((one) => variant && one.fixture.variant === variant) ?? fitting.find((one) => !one.fixture.variant);
  return pick ? { fixture: pick.fixture, params: { ...(pick.found?.groups ?? {}) } } : null;
}

async function served(server: ViteDevServer, request: IncomingMessage, response: ServerResponse): Promise<boolean> {
  const url = new URL(request.url ?? "/", "http://mock");
  if (url.pathname.startsWith(VARIANT_ROUTE)) {
    const variant = decodeURIComponent(url.pathname.slice(VARIANT_ROUTE.length));
    response.statusCode = 302;
    response.setHeader("Set-Cookie", `${VARIANT_COOKIE}=${encodeURIComponent(variant)}; Path=/`);
    response.setHeader("Location", url.searchParams.get("to") ?? "/");
    response.end();
    return true;
  }
  const standIn = STAND_INS.find((one) => url.pathname.startsWith(one.prefix));
  if (standIn) {
    response.setHeader("Content-Type", "text/html; charset=utf-8");
    response.end(standIn.page(url.pathname));
    return true;
  }
  if (!url.pathname.startsWith("/api/")) return false;
  const loaded = (await server.ssrLoadModule("/mock/fixtures/index.ts")) as { fixtures: Fixture[] };
  const method = (request.method ?? "GET").toLowerCase();
  const variant = cookieOf(request, VARIANT_COOKIE);
  const pick = chosen(loaded.fixtures, method, url.pathname, variant);
  if (!pick) {
    answered(response, { status: 404, body: { errors: [{ path: "", code: "not_found" }] } });
    server.config.logger.warn(`mock api: no fixture for ${method.toUpperCase()} ${url.pathname}`);
    return true;
  }
  const body = method === "get" ? undefined : await bodyOf(request);
  const answer = pick.fixture.answer({ params: pick.params, query: url.searchParams, body, variant });
  if (url.pathname === "/api/auth/csrf/") response.setHeader("Set-Cookie", "cr_csrf=mock-csrf-token; Path=/");
  answered(response, answer);
  return true;
}

export function mockApi(): Plugin {
  return {
    name: "cr-mock-api",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        served(server, request, response)
          .then((done) => {
            if (!done) next();
          })
          .catch((failure: unknown) => next(failure));
      });
    },
  };
}
