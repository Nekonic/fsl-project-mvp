import { describe, expect, it } from "vitest";
import { t, type StringKey } from "../strings";

const OBJECTIVE_WORDS: StringKey[] = [
  "objective.lost", "objective.kept", "objective.tally", "end_reason.all_objectives_lost", "result.achieved",
  "debrief.row.objective.lost", "result.objective_points_rule", "error.objective_fallen", "loot.no_match",
];

describe("objective wording", () => {
  it("speaks of an objective the attacker achieved, which fits a state change as well as stolen data", () => {
    for (const key of OBJECTIVE_WORDS) {
      expect(t(key)).not.toContain("탈취");
    }
    expect(t("objective.lost")).toContain("달성");
    expect(t("objective.tally", { lost: 1, total: 3 })).toBe("달성 1 / 3");
  });
});
