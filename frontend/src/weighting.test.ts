import { describe, expect, it } from "vitest";
import { targetSum } from "./WeightingPanel";

describe("targetSum", () => {
  it("adds targets and treats blanks as zero", () => {
    const category = { codes: [1], origin: "user" as const, source_ids: [], note: "" };
    const dimension = {
      variable: "Q17",
      label: "Gender",
      note: "",
      categories: [
        { ...category, label: "Woman", target_share: 50.6 },
        { ...category, label: "Man", target_share: 49.4 },
        { ...category, label: "Other", target_share: null },
      ],
    };
    expect(targetSum(dimension)).toBeCloseTo(100);
  });
});
