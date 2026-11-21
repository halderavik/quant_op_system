import { describe, expect, it } from "vitest";
import { lineDiff } from "./lineDiff";

describe("lineDiff", () => {
  it("keeps equal lines side by side and pairs changed ones", () => {
    const rows = lineDiff("<radio>\n  <title>A</title>\n</radio>", "<radio>\n  <title>B</title>\n</radio>");
    expect(rows.map((row) => row.kind)).toEqual(["same", "changed", "same"]);
    expect(rows[1]).toEqual({ left: "  <title>A</title>", right: "  <title>B</title>", kind: "changed" });
  });

  it("shows lines only one side has", () => {
    const rows = lineDiff("a\nc", "a\nb\nc");
    expect(rows).toEqual([
      { left: "a", right: "a", kind: "same" },
      { left: null, right: "b", kind: "right" },
      { left: "c", right: "c", kind: "same" },
    ]);
  });

  it("ignores indentation when matching and handles an empty side", () => {
    expect(lineDiff("  x", "x")[0].kind).toBe("same");
    expect(lineDiff("", "x")).toEqual([{ left: null, right: "x", kind: "right" }]);
  });
});
