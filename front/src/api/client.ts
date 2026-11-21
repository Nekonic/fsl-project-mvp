import type { components, paths } from "./schema";
import type { ShownError } from "../strings";

export type Schemas = components["schemas"];
export type ErrorCode = Schemas["ErrorCodeEnum"] | "timeout" | "network";
export type Method = "get" | "post" | "put" | "patch" | "delete";

type Defined<T> = Exclude<T, undefined>;
type OperationOf<P extends keyof paths, M extends Method> = Defined<paths[P][M]>;

export type PathsWith<M extends Method> = {
  [P in keyof paths]: [Defined<paths[P][M]>] extends [never] ? never : P;
}[keyof paths];

type ParametersOf<O> = O extends { parameters: infer Parameters } ? Parameters : Record<string, never>;
type Slot<O, Name extends "path" | "query"> = ParametersOf<O> extends { [K in Name]?: infer Value } ? Defined<Value> : never;

export type PathParams<P extends keyof paths, M extends Method> = [Slot<OperationOf<P, M>, "path">] extends [never]
  ? Record<string, never>
  : Slot<OperationOf<P, M>, "path">;

export type QueryOf<P extends keyof paths, M extends Method> = [Slot<OperationOf<P, M>, "query">] extends [never]
  ? Record<string, never>
  : Slot<OperationOf<P, M>, "query">;

type JsonBody<Body> = Body extends { content: { "application/json": infer Json } } ? Json : never;
export type BodyOf<P extends keyof paths, M extends Method> = OperationOf<P, M> extends { requestBody?: infer Body }
  ? JsonBody<Defined<Body>>
  : never;

type ResponsesOf<O> = O extends { responses: infer Responses } ? Responses : never;
type JsonOf<Response> = Response extends { content: { "application/json": infer Json } } ? Json : undefined;
type SuccessCode<Responses> = Extract<keyof Responses, 200 | 201 | 202 | 204>;
export type Ok<P extends keyof paths, M extends Method> = JsonOf<ResponsesOf<OperationOf<P, M>>[SuccessCode<ResponsesOf<OperationOf<P, M>>>]>;

export interface CallInit<P extends keyof paths, M extends Method> {
  params?: PathParams<P, M>;
  query?: Partial<QueryOf<P, M>>;
  body?: BodyOf<P, M>;
  signal?: AbortSignal;
}

export class ApiError extends Error {
  readonly status: number;
  readonly errors: ShownError[];
  constructor(status: number, errors: ShownError[]) {
    super(errors.map((error) => error.code).join(",") || String(status));
    this.status = status;
    this.errors = errors;
  }

  get code(): string {
    return this.errors[0]?.code ?? "unavailable";
  }

  has(code: ErrorCode): boolean {
    return this.errors.some((error) => error.code === code);
  }

  param(name: string): unknown {
    for (const error of this.errors) {
      if (error.params && name in error.params) return error.params[name];
    }
    return undefined;
  }
}

export const REQUEST_TIMEOUT_MS = 90_000;
export const CSRF_COOKIE = "cr_csrf";
export const CSRF_HEADER = "X-CSRFToken";

type SignedOutListener = () => void;
const signedOutListeners = new Set<SignedOutListener>();

export function onSignedOut(listener: SignedOutListener): () => void {
  signedOutListeners.add(listener);
  return () => signedOutListeners.delete(listener);
}

function cookie(name: string): string {
  const found = document.cookie.split("; ").find((part) => part.startsWith(`${name}=`));
  return found ? decodeURIComponent(found.slice(name.length + 1)) : "";
}

export function urlOf(path: string, params?: unknown, query?: unknown): string {
  const values = (params ?? {}) as Record<string, string | number>;
  const filled = path.replace(/\{(\w+)\}/g, (_, name: string) => {
    const value = values[name];
    if (value === undefined) throw new Error(`missing path parameter ${name} for ${path}`);
    return encodeURIComponent(String(value));
  });
  const search = new URLSearchParams();
  for (const [name, value] of Object.entries((query ?? {}) as Record<string, unknown>)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(name, String(value));
  }
  const said = search.toString();
  return said ? `${filled}?${said}` : filled;
}

let csrfRenewal: Promise<void> | null = null;

export function renewCsrf(): Promise<void> {
  if (!csrfRenewal) {
    const timeout = new AbortController();
    const timer = setTimeout(() => timeout.abort(), REQUEST_TIMEOUT_MS);
    csrfRenewal = fetch("/api/auth/csrf/", { credentials: "same-origin", signal: timeout.signal })
      .then(() => undefined, () => undefined)
      .finally(() => {
        clearTimeout(timer);
        csrfRenewal = null;
      });
  }
  return csrfRenewal;
}

async function errorsOf(response: Response): Promise<{ errors: ShownError[] }> {
  try {
    const said = await response.json();
    if (said && Array.isArray(said.errors)) return said;
  } catch {
    return { errors: [{ path: "", code: response.status >= 500 ? "server_error" : "malformed" }] };
  }
  return { errors: [{ path: "", code: response.status >= 500 ? "server_error" : "malformed" }] };
}

function bodyOf(text: string, status: number): unknown {
  if (!text) return undefined;
  try {
    return JSON.parse(text);
  } catch {
    throw new ApiError(status, [{ path: "", code: "malformed" }]);
  }
}

async function send(method: Method, url: string, body: unknown, signal: AbortSignal | undefined, renewed: boolean): Promise<unknown> {
  if (signal?.aborted) throw abortedError();
  const writes = method !== "get";
  if (writes && !cookie(CSRF_COOKIE)) await renewCsrf();
  const timeout = new AbortController();
  const timer = setTimeout(() => timeout.abort(), REQUEST_TIMEOUT_MS);
  const aborted = () => timeout.abort();
  signal?.addEventListener("abort", aborted);
  let error: ApiError;
  try {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (writes) headers[CSRF_HEADER] = cookie(CSRF_COOKIE);
    const response = await fetch(url, {
      method: method.toUpperCase(),
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "same-origin",
      signal: timeout.signal,
    });
    if (response.ok) return response.status === 204 ? undefined : bodyOf(await response.text(), response.status);
    const { errors } = await errorsOf(response);
    error = new ApiError(response.status, errors);
  } catch (failed) {
    if (failed instanceof ApiError) throw failed;
    if (signal?.aborted) throw abortedError();
    throw new ApiError(0, [{ path: "", code: timeout.signal.aborted ? "timeout" : "network" }]);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", aborted);
  }
  if (writes && !renewed && error.has("csrf_failed")) {
    await renewCsrf();
    return send(method, url, body, signal, true);
  }
  if (error.has("not_signed_in")) signedOutListeners.forEach((listener) => listener());
  throw error;
}

export function call<M extends Method, P extends PathsWith<M>>(method: M, path: P, init: CallInit<P, M> = {}): Promise<Ok<P, M>> {
  return send(method, urlOf(path, init.params, init.query), init.body, init.signal, false) as Promise<Ok<P, M>>;
}

export const api = {
  get: <P extends PathsWith<"get">>(path: P, init?: CallInit<P, "get">) => call("get", path, init),
  post: <P extends PathsWith<"post">>(path: P, init?: CallInit<P, "post">) => call("post", path, init),
  put: <P extends PathsWith<"put">>(path: P, init?: CallInit<P, "put">) => call("put", path, init),
  delete: <P extends PathsWith<"delete">>(path: P, init?: CallInit<P, "delete">) => call("delete", path, init),
};

export const SLOT_WAIT_EVERY_MS = 5_000;
export const SLOT_WAIT_LIMIT_MS = 30 * 60_000;

function abortedError(): DOMException {
  return new DOMException("aborted", "AbortError");
}

function pause(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(abortedError());
      return;
    }
    const stopped = () => {
      clearTimeout(timer);
      reject(abortedError());
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", stopped);
      resolve();
    }, ms);
    signal?.addEventListener("abort", stopped, { once: true });
  });
}

const PASSING_STATUSES = new Set([0, 429, 502, 503, 504]);

function passes(error: unknown): boolean {
  return error instanceof ApiError && PASSING_STATUSES.has(error.status);
}

export interface WaitInit<T> {
  every?: number;
  within?: number;
  signal?: AbortSignal;
  onRead?: (value: T) => void;
}

export async function waitUntil<T>(read: () => Promise<T>, done: (value: T) => boolean, init: WaitInit<T> = {}): Promise<T> {
  const every = init.every ?? SLOT_WAIT_EVERY_MS;
  const until = Date.now() + (init.within ?? SLOT_WAIT_LIMIT_MS);
  for (;;) {
    if (init.signal?.aborted) throw abortedError();
    let value: T | undefined;
    try {
      value = await read();
    } catch (error) {
      if (init.signal?.aborted || !passes(error)) throw error;
    }
    if (init.signal?.aborted) throw abortedError();
    if (value !== undefined) {
      init.onRead?.(value);
      if (done(value)) return value;
    }
    if (Date.now() > until) throw new ApiError(0, [{ path: "", code: "timeout" }]);
    await pause(every, init.signal);
  }
}

export function waitForAllocation(allocation: number, init: WaitInit<Schemas["AllocationDetail"]> = {}) {
  return waitUntil(
    () => api.get("/api/allocations/{allocation_id}/", { params: { allocation_id: allocation }, signal: init.signal }),
    (shown) => shown.ready || shown.closed !== null,
    init,
  );
}

export function waitForLesson(round: number, init: WaitInit<Schemas["LessonShown"]> = {}) {
  return waitUntil(
    () => api.get("/api/lessons/{round_id}/", { params: { round_id: round }, signal: init.signal }),
    (shown) => shown.phase === "ready" || shown.phase === "ended",
    init,
  );
}

export async function openAllocation(wargame: string, init: WaitInit<Schemas["AllocationDetail"]> = {}) {
  const until = Date.now() + (init.within ?? SLOT_WAIT_LIMIT_MS);
  for (;;) {
    try {
      return await api.post("/api/allocations/", { body: { wargame }, signal: init.signal });
    } catch (error) {
      if (!(error instanceof ApiError) || !error.has("range_unavailable") || Date.now() > until) throw error;
      const retryAfter = Number(error.param("retry_after")) || SLOT_WAIT_EVERY_MS / 1000;
      await pause(retryAfter * 1000, init.signal);
    }
  }
}
