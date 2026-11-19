import { describe, expect, it } from "vitest";

import {
  earlierIds,
  fromDraft,
  highlight,
  setNumber,
  setOptionFlag,
  setRowFilter,
  setShowIf,
  toDraft,
} from "./logicEdit";

describe("show-if editing", () => {
  it("round-trips a simple and/or condition", () => {
    const expr = { kind: "bool" as const, op: "and", args: [
      { kind: "cmp" as const, op: "eq", ref: "S1", value: 1 },
      { kind: "cmp" as const, op: "in", ref: "S2", value: [2, 3] },
    ] };
    const draft = toDraft(expr);
    expect(draft).toEqual({ join: "and", conditions: [
      { ref: "S1", op: "eq", values: ["1"] },
      { ref: "S2", op: "in", values: ["2", "3"] },
    ] });
    expect(fromDraft(draft!)).toEqual(expr);
  });

  it("switches between one value and several", () => {
    expect(fromDraft({ join: "and", conditions: [{ ref: "S1", op: "eq", values: ["1", "2"] }] })).toEqual({ kind: "cmp", op: "in", ref: "S1", value: [1, 2] });
    expect(fromDraft({ join: "and", conditions: [{ ref: "S1", op: "not_in", values: ["4"] }] })).toEqual({ kind: "cmp", op: "ne", ref: "S1", value: 4 });
  });

  it("leaves out incomplete rows and clears when none are left", () => {
    expect(fromDraft({ join: "or", conditions: [{ ref: "", op: "eq", values: ["1"] }, { ref: "S1", op: "eq", values: [] }] })).toBeNull();
    expect(setShowIf({ id: "Q2", display_if: { op: "eq", ref: "S1", value: 1 } }, { join: "and", conditions: [] }).display_if).toBeNull();
  });

  it("refuses logic the pickers cannot show", () => {
    expect(toDraft({ op: "eq", ref: "Q1", row: 2, value: 1 })).toBeNull();
    expect(toDraft({ kind: "bool", op: "or", args: [{ kind: "bool", op: "and", args: [] }] })).toBeNull();
    expect(toDraft(null)).toEqual({ join: "and", conditions: [] });
  });
});

describe("other settings", () => {
  it("sets and clears numbers", () => {
    const set = setNumber({ id: "S3", programming: { min_value: 1 } }, "max_value", "99");
    expect(set.programming).toEqual({ min_value: 1, max_value: 99 });
    expect(setNumber(set, "min_value", "").programming?.min_value).toBeNull();
  });

  it("keeps the grid column only while the source is unchanged", () => {
    const q = { id: "Q5", programming: { row_condition: { source: "Q4", mode: "selected", column: 1 } } };
    expect(setRowFilter(q, "Q4", "not_selected").programming?.row_condition).toEqual({ source: "Q4", mode: "not_selected", column: 1 });
    expect(setRowFilter(q, "Q3", "selected").programming?.row_condition).toEqual({ source: "Q3", mode: "selected", column: null });
    expect(setRowFilter(q, "", "selected").programming?.row_condition).toBeNull();
  });

  it("flags one option", () => {
    const q = { id: "S1", options: [{ code: 1, label: "Yes" }, { code: 2, label: "No" }] };
    expect(setOptionFlag(q, 1, "terminate", true).options?.[1]).toEqual({ code: 2, label: "No", terminate: true });
  });

  it("offers only earlier questions", () => {
    expect(earlierIds(["S1", "S2", "Q1"], "Q1")).toEqual(["S1", "S2"]);
  });
});

describe("source highlight", () => {
  it("marks the wording despite different spacing", () => {
    const parts = highlight("S2.  What is   your age?\n1. Under 18", "What is your age?");
    expect(parts.find((p) => p.match)?.text).toBe("What is   your age?");
    expect(parts.map((p) => p.text).join("")).toBe("S2.  What is   your age?\n1. Under 18");
  });

  it("returns the excerpt unchanged when the wording is not found", () => {
    expect(highlight("abc", "xyz")).toEqual([{ text: "abc", match: false }]);
  });
});
