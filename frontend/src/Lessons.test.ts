import { describe, expect, it } from "vitest";
import type { ProgrammingLesson } from "./api";
import { shortValue, visibleLessons } from "./Lessons";

const lesson = (id: string, status: "active" | "disabled", rule: string): ProgrammingLesson => ({
  id,
  status,
  stage: id === "b" ? "extraction" : "programming",
  rule,
  field: "programming.row_condition",
  question_type: "grid",
  example_instruction: "ASK BRANDS AWARE IN qAID",
  example_before: { value: null },
  example_after: { value: { source: "qAID", column: 1 } },
  support: 2,
  updated_at: "2026-11-17T00:00:00",
});

describe("learned rules", () => {
  const lessons = [lesson("a", "active", "Pipe aware brands from the Yes column"), lesson("b", "disabled", "Shuffle brand lists")];

  it("filters by status and every search word", () => {
    expect(visibleLessons(lessons, "active", "").map((item) => item.id)).toEqual(["a"]);
    expect(visibleLessons(lessons, "all", "brand").map((item) => item.id)).toEqual(["a", "b"]);
    expect(visibleLessons(lessons, "all", "yes column").map((item) => item.id)).toEqual(["a"]);
    expect(visibleLessons(lessons, "disabled", "aware").map((item) => item.id)).toEqual(["b"]);
    expect(visibleLessons(lessons, "active", "shuffle").map((item) => item.id)).toEqual([]);
  });

  it("filters by kind of rule", () => {
    expect(visibleLessons(lessons, "all", "", "extraction").map((item) => item.id)).toEqual(["b"]);
    expect(visibleLessons(lessons, "all", "", "programming").map((item) => item.id)).toEqual(["a"]);
  });

  it("shows stored values briefly", () => {
    expect(shortValue(null)).toBe("not set");
    expect(shortValue(true)).toBe("yes");
    expect(shortValue({ source: "qAID", column: 1 })).toBe('{"source":"qAID","column":1}');
  });
});
