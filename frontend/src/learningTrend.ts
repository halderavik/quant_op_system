/** Summaries of how much reading and planning needed fixing, earlier versus recently. */

import type { QualityPoint } from "./api";

export type TrendSummary = {
  label: string;
  recent: number | null;
  earlier: number | null;
  count: number;
};

/** Per 10 questions, so short and long questionnaires compare fairly. */
function rate(point: QualityPoint, value: number): number {
  return (value / Math.max(point.questions ?? 0, 1)) * 10;
}

function average(values: number[]): number | null {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
}

/** The last ``window`` measurements against the ones before them. */
export function compareWindows(values: number[], window = 5): { recent: number | null; earlier: number | null } {
  const recent = values.slice(-window);
  const earlier = values.slice(0, Math.max(values.length - window, 0));
  return { recent: average(recent), earlier: average(earlier) };
}

export function trendSummaries(points: QualityPoint[], window = 5): TrendSummary[] {
  const imports = points.filter((point) => point.kind === "import_quality");
  const approvals = points.filter((point) => point.kind === "approval_corrections");
  const rows: [string, number[]][] = [
    ["Parts of the file re-read per 10 questions", imports.map((p) => rate(p, p.reread_parts ?? 0))],
    ["Reading corrections per 10 questions", approvals.map((p) => rate(p, p.extraction ?? 0))],
    ["Logic corrections per 10 questions", approvals.map((p) => rate(p, p.programming ?? 0))],
  ];
  return rows.map(([label, values]) => ({ label, count: values.length, ...compareWindows(values, window) }));
}

/** "1.2", or "-" when there is nothing to show. */
export function formatRate(value: number | null): string {
  return value === null ? "-" : value.toFixed(1);
}
