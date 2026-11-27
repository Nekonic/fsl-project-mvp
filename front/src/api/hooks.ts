import { createContext } from "preact";
import { useCallback, useContext, useEffect, useRef, useState } from "preact/hooks";
import { ApiError, call, type CallInit, type Method, type Ok, type PathsWith, type Schemas } from "./client";
import { follow, type RoundEvent } from "./follow";

export interface Resource<T> {
  data: T | undefined;
  error: ApiError | undefined;
  loading: boolean;
  reload: () => void;
  setData: (data: T) => void;
}

export interface Following {
  round: number;
  kinds: string[];
}

export interface ResourceOptions {
  refreshOn?: Following;
}

function refusesTheViewer(error: ApiError): boolean {
  return error.status >= 400 && error.status < 500 && error.status !== 429;
}

function asApiError(error: unknown): ApiError | undefined {
  if (error instanceof DOMException && error.name === "AbortError") return undefined;
  if (error instanceof ApiError) return error;
  return new ApiError(0, [{ path: "", code: "network" }]);
}

export function useEvents(round: number | null | undefined, kinds: string[] | null, onEvents: (events: RoundEvent[], backlog: boolean) => void, replay = false): void {
  const handler = useRef(onEvents);
  handler.current = onEvents;
  const wanted = kinds ? kinds.join(",") : "";
  useEffect(() => {
    if (!round) return undefined;
    const only = wanted ? new Set(wanted.split(",")) : null;
    return follow(round, (events, backlog) => {
      const matching = only ? events.filter((event) => only.has(event.kind)) : events;
      if (matching.length) handler.current(matching, backlog);
    }, replay);
  }, [round, wanted, replay]);
}

export function useEventCount(following: Following | undefined): number {
  const [count, setCount] = useState(0);
  useEvents(following?.round, following?.kinds ?? [], (_events, backlog) => {
    if (!backlog) setCount((was) => was + 1);
  });
  return following ? count : 0;
}

export function useResource<P extends PathsWith<"get">>(path: P, init: CallInit<P, "get"> | null, options: ResourceOptions = {}): Resource<Ok<P, "get">> {
  const [data, setData] = useState<Ok<P, "get"> | undefined>(undefined);
  const [error, setError] = useState<ApiError | undefined>(undefined);
  const [loading, setLoading] = useState(init !== null);
  const [asked, setAsked] = useState(0);
  const changed = useEventCount(options.refreshOn);
  const key = init === null ? null : JSON.stringify({ path, params: init.params, query: init.query });
  const latest = useRef(init);
  latest.current = init;

  useEffect(() => {
    if (key === null || latest.current === null) {
      setLoading(false);
      return undefined;
    }
    const abort = new AbortController();
    setLoading(true);
    call("get", path, { ...latest.current, signal: abort.signal })
      .then((said) => {
        if (abort.signal.aborted) return;
        setData(said as Ok<P, "get">);
        setError(undefined);
      })
      .catch((failed: unknown) => {
        const shown = asApiError(failed);
        if (!shown || abort.signal.aborted) return;
        setError(shown);
        if (refusesTheViewer(shown)) setData(undefined);
      })
      .finally(() => {
        if (!abort.signal.aborted) setLoading(false);
      });
    return () => abort.abort();
  }, [key, asked, changed]);

  const reload = useCallback(() => setAsked((was) => was + 1), []);
  return { data, error, loading, reload, setData };
}

export interface Action<M extends Method, P extends PathsWith<M>> {
  run: (init?: CallInit<P, M>) => Promise<Ok<P, M> | undefined>;
  busy: boolean;
  error: ApiError | undefined;
  data: Ok<P, M> | undefined;
  reset: () => void;
}

export function useAction<M extends Exclude<Method, "get">, P extends PathsWith<M>>(method: M, path: P): Action<M, P> {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | undefined>(undefined);
  const [data, setData] = useState<Ok<P, M> | undefined>(undefined);
  const run = useCallback(
    async (init?: CallInit<P, M>) => {
      setBusy(true);
      setError(undefined);
      try {
        const said = await call(method, path, init);
        setData(said);
        return said;
      } catch (failed) {
        setError(asApiError(failed));
        return undefined;
      } finally {
        setBusy(false);
      }
    },
    [method, path],
  );
  const reset = useCallback(() => {
    setError(undefined);
    setData(undefined);
  }, []);
  return { run, busy, error, data, reset };
}

export type Me = Schemas["Me"];
export interface Session {
  me: Me | undefined;
  loading: boolean;
  reload: () => void;
}

export const SessionContext = createContext<Session>({ me: undefined, loading: true, reload: () => undefined });

export function useSession(): Session {
  return useContext(SessionContext);
}

export interface RowAction<Id, M extends Exclude<Method, "get">, P extends PathsWith<M>> {
  run: (id: Id, init?: CallInit<P, M>) => Promise<{ ok: boolean; data?: Ok<P, M> }>;
  busyFor: (id: Id) => boolean;
  errorFor: (id: Id) => ApiError | undefined;
}

export function useRowAction<Id, M extends Exclude<Method, "get">, P extends PathsWith<M>>(method: M, path: P): RowAction<Id, M, P> {
  const [busy, setBusy] = useState<Id | undefined>(undefined);
  const [failed, setFailed] = useState<{ id: Id; error: ApiError } | undefined>(undefined);
  return {
    run: async (id, init) => {
      setBusy(id);
      setFailed(undefined);
      try {
        return { ok: true, data: await call(method, path, init) };
      } catch (error) {
        setFailed({ id, error: error instanceof ApiError ? error : new ApiError(0, [{ path: "", code: "network" }]) });
        return { ok: false };
      } finally {
        setBusy(undefined);
      }
    },
    busyFor: (id) => busy === id,
    errorFor: (id) => (failed && failed.id === id ? failed.error : undefined),
  };
}
