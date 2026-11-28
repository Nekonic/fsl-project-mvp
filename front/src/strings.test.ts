import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";
import table from "@strings/console.json";
import { errorLine, errorText, hasString, REFERENCE, t } from "./strings";

const SRC = join(process.cwd(), "src");
const REPO = join(SRC, "..", "..");
const ABBREVIATION = /\b(TP|FP|FN|TN)\b/;

function sourceFiles(folder: string): string[] {
  return readdirSync(folder).flatMap((name) => {
    const path = join(folder, name);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name) && name !== "schema.d.ts" ? [path] : [];
  });
}

const sources = sourceFiles(SRC).map((path) => ({ path: relative(SRC, path), text: readFileSync(path, "utf-8") }));

function found(pattern: RegExp): Array<{ path: string; key: string }> {
  return sources.flatMap(({ path, text }) => [...text.matchAll(pattern)].map((match) => ({ path, key: match[1] as string })));
}

function errorCodesInSchema(): string[] {
  const schema = readFileSync(join(REPO, "openapi", "schema.yaml"), "utf-8");
  const block = schema.split(/\n {4}ErrorCodeEnum:\n/)[1];
  if (!block) throw new Error("openapi/schema.yaml has no ErrorCodeEnum");
  const codes: string[] = [];
  for (const line of block.split("\n").slice(2)) {
    const item = /^ {6}- (\S+)$/.exec(line);
    if (!item) break;
    codes.push((item[1] as string).replace(/^["']|["']$/g, ""));
  }
  return codes;
}

describe("console strings", () => {
  it("has every key a t() call names", () => {
    const missing = found(/\bt\(\s*["'`]([^"'`$]+)["'`]/g).filter(({ key }) => !hasString(key));
    expect(missing).toEqual([]);
  });

  it("has keys under every prefix a tFor() call names", () => {
    const keys = Object.keys(table);
    const empty = found(/\btFor\(\s*["'`]([^"'`$]+)["'`]/g).filter(({ key }) => !keys.some((one) => one.startsWith(`${key}.`)));
    expect(empty).toEqual([]);
  });

  it("has every label key the layouts and the nav name", () => {
    const missing = found(/\blabel: ["']([a-z_]+\.[\w.-]+)["']/g).filter(({ key }) => !hasString(key));
    expect(missing).toEqual([]);
  });

  it("names every error code of the schema", () => {
    const codes = errorCodesInSchema();
    expect(codes.length).toBeGreaterThan(50);
    expect(codes.filter((code) => !hasString(`error.${code}`))).toEqual([]);
  });

  it("names the verdicts in Korean, never as TP, FP, FN or TN", () => {
    for (const verdict of ["tp", "fn", "fp", "tn"]) {
      expect(hasString(`verdict.${verdict}`)).toBe(true);
    }
    expect(Object.entries(table).filter(([, value]) => ABBREVIATION.test(value))).toEqual([]);
  });

  it("puts no TP, FP, FN or TN abbreviation into rendered markup", () => {
    const shown = sources.filter(({ path }) => path.endsWith(".tsx")).flatMap(({ path, text }) =>
      [...text.matchAll(/>([^<>{}]*)</g)].filter((match) => ABBREVIATION.test(match[1] as string)).map(() => path));
    expect(shown).toEqual([]);
  });

  it("resolves every key a value refers to with {@key}", () => {
    const references = Object.entries(table).flatMap(([key, value]) => [...value.matchAll(REFERENCE)].map((match) => ({ key, named: match[1] as string })));
    expect(references.filter(({ key, named }) => !hasString(named) || named === key)).toEqual([]);
    expect(Object.keys(table).filter((key) => t(key as keyof typeof table).includes("{@"))).toEqual([]);
  });

  it("fills parameters and lines", () => {
    expect(t("round.name", { round: 41 })).toContain("41");
    expect(errorLine({ path: "text", code: "suricata_syntax", line: 16 })).toContain("16");
    expect(errorText({ errors: [{ path: "", code: "password_too_short", params: { min_length: 8 } }] })).toContain("8");
    expect(errorText({ errors: [{ path: "", code: "no_such_code" }] })).toBe(t("error.unknown"));
  });

  it("shows a sign-in block's end in Seoul time", () => {
    const said = errorLine({ path: "", code: "sign_in_blocked", params: { until: "2026-11-28T06:49:00.123456+00:00", retry_after: 600 } });
    expect(said).toContain("15:49");
    expect(said).not.toContain("2026-11-28T");
  });
});
