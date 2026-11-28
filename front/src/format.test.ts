import { describe, expect, it } from "vitest";
import { clock, clockSeconds, day } from "./format";

describe("shown times", () => {
  it("shows a UTC instant in Korea Standard Time whatever the browser's zone", () => {
    expect(clock("2026-11-28T15:42:17Z")).toBe("00:42");
    expect(clockSeconds("2026-11-28T01:42:17Z")).toBe("10:42:17");
    expect(day("2026-11-28T15:42:17Z")).toBe("2026-11-29");
  });
});
