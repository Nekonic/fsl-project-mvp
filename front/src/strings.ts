import table from "@strings/console.json";
import { clock } from "./format";

export type StringKey = keyof typeof table;
export type StringParams = Record<string, string | number | null | undefined>;

const strings: Record<string, string> = table;

export function hasString(key: string): key is StringKey {
  return Object.prototype.hasOwnProperty.call(strings, key);
}

function filled(text: string, params?: StringParams): string {
  if (!params) return text;
  return text.replace(/\{(\w+)\}/g, (whole, name: string) => {
    const value = params[name];
    return value === undefined || value === null ? whole : String(value);
  });
}

export const REFERENCE = /\{@([\w.-]+)\}/g;

function resolved(key: string, through: string[] = []): string {
  const text = strings[key] ?? key;
  const seen = [...through, key];
  return text.replace(REFERENCE, (whole, named: string) => (hasString(named) && !seen.includes(named) ? resolved(named, seen) : whole));
}

export function t(key: StringKey, params?: StringParams): string {
  return filled(resolved(key), params);
}

export function tFor(prefix: string, code: string, params?: StringParams, fallback?: StringKey): string {
  const key = `${prefix}.${code}`;
  if (hasString(key)) return t(key, params);
  return fallback ? t(fallback, params) : code;
}

export interface ShownError {
  path: string;
  code: string;
  line?: number;
  params?: Record<string, unknown>;
}

export interface ErrorShape {
  errors: ShownError[];
}

const TIME_PARAMS = new Set(["until"]);

function shownParam(name: string, value: unknown): string | null | undefined {
  if (value === null || value === undefined) return value;
  if (TIME_PARAMS.has(name) && typeof value === "string") return clock(value);
  return String(value);
}

function asParams(params: Record<string, unknown> | undefined): StringParams | undefined {
  if (!params) return undefined;
  return Object.fromEntries(Object.entries(params).map(([name, value]) => [name, shownParam(name, value)])) as StringParams;
}

export function errorLine(error: ShownError): string {
  const said = tFor("error", error.code, asParams(error.params), "error.unknown");
  return error.line ? t("error.at_line", { line: error.line, message: said }) : said;
}

export function errorLines(shape: ErrorShape | null | undefined): string[] {
  return (shape?.errors ?? []).map(errorLine);
}

export function errorText(shape: ErrorShape | null | undefined): string {
  const lines = errorLines(shape);
  return lines.length ? lines.join(" ") : t("error.unknown");
}

export function fieldErrors(shape: ErrorShape | null | undefined): Record<string, string> {
  const byPath: Record<string, string> = {};
  for (const error of shape?.errors ?? []) {
    const path = error.path || "";
    byPath[path] = byPath[path] ? `${byPath[path]} ${errorLine(error)}` : errorLine(error);
  }
  return byPath;
}

export function formErrors(shape: ErrorShape | null | undefined, fields: string[]): string[] {
  return (shape?.errors ?? []).filter((error) => !fields.includes(error.path)).map(errorLine);
}
