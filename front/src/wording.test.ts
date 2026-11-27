import { describe, expect, it } from "vitest";
import { t } from "./strings";

describe("console wording", () => {
  it("gives the home 1:1 card a title that does not repeat its label", () => {
    expect(t("home.pvp_title")).not.toBe(t("matchup.pvp"));
  });

  it("names the lobby player choice by what it asks for, a username", () => {
    expect(t("lobby.player_kind.user")).toContain("아이디");
  });

  it("says the WAF test replays HTTP requests only and where a tool case is checked instead", () => {
    const said = t("rule_test.untested.tool_case");
    expect(said).toContain("HTTP");
    expect(said).toContain("IDS");
  });

  it("states the points a lost objective added as points with the reason", () => {
    expect(t("result.weight_full", { points: 4 })).toBe("4점 (대응 없음)");
    expect(t("result.weight_half", { points: 1 })).toBe("1점 (대응해서 절반)");
  });
});
