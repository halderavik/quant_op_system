import { describe, expect, it } from "vitest";
import type { QualityPoint } from "./api";
import { compareWindows, formatRate, trendSummaries } from "./learningTrend";

const point = (kind: QualityPoint["kind"], extra: Partial<QualityPoint>): QualityPoint => ({
  kind,
  project: "P",
  created_at: "2026-11-17T00:00:00",
  questions: 20,
  ...extra,
});

describe("learning trend", () => {
  it("compares the latest window with the earlier ones", () => {
    expect(compareWindows([4, 4, 2, 1], 2)).toEqual({ recent: 1.5, earlier: 4 });
    expect(compareWindows([3], 2)).toEqual({ recent: 3, earlier: null });
  });

  it("counts re-reads and corrections per 10 questions", () => {
    const summaries = trendSummaries(
      [
        point("import_quality", { reread_parts: 4 }),
        point("import_quality", { reread_parts: 0 }),
        point("approval_corrections", { extraction: 2, programming: 6 }),
      ],
      1,
    );
    expect(summaries[0]).toEqual({ label: "Parts of the file re-read per 10 questions", count: 2, recent: 0, earlier: 2 });
    expect(summaries[2].recent).toBe(3);
    expect(formatRate(null)).toBe("-");
  });
});
