/** A line-by-line diff of two short texts, aligned for a side-by-side view. */

export type DiffKind = "same" | "changed" | "left" | "right";

export type DiffRow = { left: string | null; right: string | null; kind: DiffKind };

/**
 * Align the lines of two texts with a longest-common-subsequence match.
 * Lines only on one side are paired up as "changed" when they sit in the same gap.
 */
export function lineDiff(leftText: string, rightText: string): DiffRow[] {
  const a = leftText ? leftText.split("\n") : [];
  const b = rightText ? rightText.split("\n") : [];
  const key = (line: string) => line.trim();
  const table: number[][] = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      table[i][j] = key(a[i]) === key(b[j]) ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);
    }
  }
  const rows: DiffRow[] = [];
  let lefts: string[] = [];
  let rights: string[] = [];
  const flush = () => {
    const shared = Math.min(lefts.length, rights.length);
    for (let k = 0; k < shared; k += 1) rows.push({ left: lefts[k], right: rights[k], kind: "changed" });
    for (const line of lefts.slice(shared)) rows.push({ left: line, right: null, kind: "left" });
    for (const line of rights.slice(shared)) rows.push({ left: null, right: line, kind: "right" });
    lefts = [];
    rights = [];
  };
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (key(a[i]) === key(b[j])) {
      flush();
      rows.push({ left: a[i], right: b[j], kind: "same" });
      i += 1;
      j += 1;
    } else if (table[i + 1][j] >= table[i][j + 1]) {
      lefts.push(a[i]);
      i += 1;
    } else {
      rights.push(b[j]);
      j += 1;
    }
  }
  lefts.push(...a.slice(i));
  rights.push(...b.slice(j));
  flush();
  return rows;
}
