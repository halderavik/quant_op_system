import { describe, expect, it } from "vitest";
import {
  addQuestion,
  applyOverride,
  bookTables,
  deleteQuestion,
  duplicateTable,
  exceptionLines,
  filterTables,
  moveQuestion,
  provenanceRows,
  tabspecIssues,
  visibleAssignments,
} from "./model";

describe("crosstab book", () => {
  const tables = [
    { table_id: "T1", title: "Trust by gender" },
    { table_id: "T2", title: "Age by region" },
  ];

  it("switches among tables in the book", () => {
    const book = bookTables({ tables, table: tables[0] });
    expect(filterTables(book, "region")).toEqual([tables[1]]);
  });

  it("returns an empty list when the search misses", () => {
    expect(filterTables(bookTables({ tables }), "quota")).toEqual([]);
  });

  it("keeps exception lines beside the tables that ran", () => {
    const lines = exceptionLines({ tables, exceptions: [{ table_id: "T9", message: "Missing variable" }] });
    expect(lines).toEqual(["T9: Missing variable"]);
    expect(bookTables({ tables })).toHaveLength(2);
  });
});

describe("structural edits", () => {
  it("reorders questions", () => {
    const content = { questions: [{ id: "Q1", text: "A" }, { id: "Q2", text: "B" }] };
    const moved = moveQuestion(content, 1, -1);
    expect((moved.questions as { id: string }[]).map((question) => question.id)).toEqual(["Q2", "Q1"]);
  });

  it("can remove the last question for the server to flag", () => {
    const content = addQuestion({ questions: [] });
    const emptied = deleteQuestion(content, 0);
    expect(emptied.questions).toEqual([]);
  });

  it("copies a table under a new id", () => {
    const content = {
      banners: [{ id: "b1" }],
      tables: [{ id: "T1", title: "Trust", banner_ids: ["b1"] }],
    };
    const copied = duplicateTable(content, 0);
    const tables = copied.tables as { id: string }[];
    expect(tables).toHaveLength(2);
    expect(tables[1].id).not.toBe("T1");
    expect(tabspecIssues(copied)).toEqual([]);
  });

  it("flags a duplicate id and a missing banner", () => {
    const issues = tabspecIssues({
      banners: [{ id: "b1" }],
      tables: [
        { id: "T1", title: "A", banner_ids: ["missing"] },
        { id: "T1", title: "B", banner_ids: [] },
      ],
    });
    expect(issues.some((issue) => issue.includes("duplicated"))).toBe(true);
    expect(issues.some((issue) => issue.includes("missing"))).toBe(true);
  });
});

describe("review and provenance", () => {
  it("filters the review queue", () => {
    const rows = visibleAssignments(
      [
        { source_row_id: 1, response_text: "Slow service", review_required: true },
        { source_row_id: 2, response_text: "Great quality", review_required: false },
      ],
      "quality",
      false,
    );
    expect(rows).toHaveLength(1);
    expect(rows[0].source_row_id).toBe(2);
  });

  it("keeps the model codes when a reviewer override is applied", () => {
    const row = applyOverride({ source_row_id: 1, assigned_code_ids: ["C01"] }, ["C02"], "negative");
    expect(row.assigned_code_ids).toEqual(["C01"]);
    expect(row.human_overrides?.code_ids).toEqual(["C02"]);
  });

  it("shows the subprocess fallback warning", () => {
    const rows = provenanceRows(
      {
        provenance: {
          isolation: "subprocess_fallback",
          warning: "This is reduced isolation, not a secure sandbox.",
          job_id: "job-1",
        },
      },
      3,
    );
    expect(rows.find((row) => row.label === "Warning")?.value).toContain("not a secure sandbox");
    expect(rows.find((row) => row.label === "Artifact version")?.value).toBe("3");
  });
});
