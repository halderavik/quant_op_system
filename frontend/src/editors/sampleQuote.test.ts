import { describe, expect, it } from "vitest";
import { quotaCellLabel } from "./sampleQuote";

describe("quotaCellLabel", () => {
  it("names a planned quota cell", () => {
    expect(quotaCellLabel({ labels: ["Female", "18–24"], places: 50 })).toBe(
      "Female · 18–24: 50 planned",
    );
  });

  it("names an unweighted audience as one cell", () => {
    expect(quotaCellLabel({ labels: [], places: 400 })).toBe("All eligible: 400 planned");
  });

  it("does not invent places when the cell is empty", () => {
    expect(quotaCellLabel({})).toBe("All eligible: 0 planned");
  });
});
