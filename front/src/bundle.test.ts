import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";
import server from "@strings/server.json";

const DIST = join(process.cwd(), "dist");
const built = existsSync(DIST);

function bundled(folder: string): string {
  return readdirSync(folder, { withFileTypes: true })
    .map((entry) => (entry.isDirectory() ? bundled(join(folder, entry.name)) : /\.(js|css|html)$/.test(entry.name) ? readFileSync(join(folder, entry.name), "utf-8") : ""))
    .join("\n");
}

describe.skipIf(!built)("the built bundle (front/dist, made by npm run build)", () => {
  it("carries no key of strings/server.json", () => {
    const text = bundled(DIST);
    expect(Object.keys(server).filter((key) => text.includes(key))).toEqual([]);
  });

  it("carries the console strings", () => {
    expect(bundled(DIST)).toContain("error.not_signed_in");
  });
});
