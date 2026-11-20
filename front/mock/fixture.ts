import type { components } from "../src/api/schema";
import type { BodyOf, Method, Ok, PathsWith } from "../src/api/client";

export type FieldError = components["schemas"]["FieldError"];

export interface Asked<Body = unknown> {
  params: Record<string, string>;
  query: URLSearchParams;
  body: Body | undefined;
  variant: string;
}

export interface Answer {
  status: number;
  body?: unknown;
  headers?: Record<string, string>;
}

export interface Fixture {
  method: Method;
  path: string;
  variant?: string;
  answer: (asked: Asked) => Answer;
}

export interface FixtureOptions {
  status?: number;
  variant?: string;
}

export function reply<M extends Method, P extends PathsWith<M>>(
  method: M,
  path: P,
  body: Ok<P, M> | ((asked: Asked<BodyOf<P, M>>) => Ok<P, M>),
  options: FixtureOptions = {},
): Fixture {
  const status = options.status ?? (method === "delete" ? 204 : 200);
  return {
    method,
    path,
    variant: options.variant,
    answer: (asked) => ({ status, body: typeof body === "function" ? (body as (asked: Asked<BodyOf<P, M>>) => Ok<P, M>)(asked as Asked<BodyOf<P, M>>) : body }),
  };
}

export function refuse<M extends Method, P extends PathsWith<M>>(
  method: M,
  path: P,
  status: number,
  errors: FieldError[],
  options: Omit<FixtureOptions, "status"> & { hp?: components["schemas"]["HpBlock"] } = {},
): Fixture {
  return { method, path, variant: options.variant, answer: () => ({ status, body: { errors, ...(options.hp ? { hp: options.hp } : {}) } }) };
}

export function minutesFromNow(minutes: number): string {
  return new Date(Date.now() + minutes * 60_000).toISOString();
}
