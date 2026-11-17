import { describe, expect, it } from "vitest";
import { buildCatalog, describeExpr, logicLines, type QuestionLite } from "./logic";

const questions: QuestionLite[] = [
  { id: "S1", type: "single_select", options: [{ code: 1, label: "Yes" }, { code: 2, label: "No" }] },
  { id: "S3", type: "numeric", options: [{ code: 99, label: "Prefer not to answer" }] },
  { id: "qAID", type: "grid", matrix_items: ["Boursin", "Alouette"], options: [{ code: 1, label: "Yes" }, { code: 2, label: "No" }] },
  {
    id: "Q5",
    type: "multi_select",
    options: [{ code: 1, label: "Pop" }, { code: 99, label: "None of these", exclusive: true, anchor: true }],
    randomize_options: true,
    display_if: { kind: "bool", op: "and", args: [{ kind: "cmp", op: "eq", ref: "S1", value: 1 }, { kind: "cmp", op: "gte", ref: "S3", value: 18 }] },
    programming: {
      row_condition: { source: "qAID", mode: "selected", column: 1 },
      terminate_rules: [{ when: { kind: "cmp", op: "lt", ref: "S3", value: 18 }, immediately: true }],
      pipes: [{ placeholder: "[INSERT S1]", source: "S1" }],
      unresolved: ["Show product images"],
    },
  },
];

describe("logic descriptions", () => {
  const catalog = buildCatalog(questions, [{ id: "HV_PARENT", values: [{ code: 1, label: "Parent" }] }]);

  it("names codes with their labels and keeps typed numbers plain", () => {
    expect(describeExpr(questions[3].display_if, catalog)).toBe("S1 = 1 (Yes) and S3 ≥ 18");
    expect(describeExpr({ op: "eq", ref: "qAID", row: 1, value: 1 }, catalog)).toBe('qAID "Boursin" = 1 (Yes)');
    expect(describeExpr({ op: "eq", ref: "HV_PARENT", value: 1 }, catalog)).toBe("HV_PARENT = 1 (Parent)");
    expect(describeExpr({ op: "gt", ref: "C2", value_ref: "C1" }, catalog)).toBe("C2 > C1");
  });

  it("lists every piece of a question's logic and its to-dos", () => {
    const lines = logicLines(questions[3], catalog);
    const byLabel = Object.fromEntries(lines.map((line) => [line.label, line.text]));
    expect(byLabel.Shown).toBe("when S1 = 1 (Yes) and S3 ≥ 18");
    expect(byLabel.Rows).toBe("only those chosen at qAID with 1 (Yes)");
    expect(byLabel.Order).toContain("randomized");
    expect(byLabel.Exclusive).toBe("99 None of these");
    expect(byLabel.Terminate).toBe("if S3 < 18 (immediately)");
    expect(byLabel.Piping).toBe("[INSERT S1] shows the answer to S1");
    expect(lines.find((line) => line.todo)?.text).toBe("Show product images");
  });
});
