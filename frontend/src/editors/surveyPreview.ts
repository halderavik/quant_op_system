/** Pure helpers for the respondent preview. The walk itself stays on the server. */

export type PreviewRow = {
  label: string;
  text: string;
  exclusive: boolean;
  open: boolean;
  randomize: boolean;
};

export type PreviewColumn = { label: string; text: string };

export type PreviewScreen = {
  status: "question" | "terminated" | "complete" | "error";
  label: string | null;
  element: string | null;
  title: string;
  comment: string | null;
  required: boolean;
  atleast: number | null;
  rows: PreviewRow[];
  cols: PreviewColumn[];
  choices: PreviewColumn[];
  shuffle: boolean;
  verify: string | null;
  check: "none" | "date" | "total100";
  warning: string | null;
  message: string;
};

export type PreviewAnswer = {
  rows: string[];
  cells: Record<string, string>;
  value: string;
  row_values: Record<string, string>;
  open_text: Record<string, string>;
};

export type PreviewPayload = {
  rows?: string[];
  cells?: Record<string, string>;
  value?: string;
  row_values?: Record<string, string>;
  open_text?: Record<string, string>;
};

export function emptyAnswer(): PreviewAnswer {
  return { rows: [], cells: {}, value: "", row_values: {}, open_text: {} };
}

export function toggleRow(rows: PreviewRow[], selected: string[], label: string): string[] {
  const row = rows.find((item) => item.label === label);
  if (!row) return selected;
  if (selected.includes(label)) return selected.filter((item) => item !== label);
  if (row.exclusive) return [label];
  const exclusive = new Set(rows.filter((item) => item.exclusive).map((item) => item.label));
  return [...selected.filter((item) => !exclusive.has(item)), label];
}

export function shuffleRows<T extends { randomize: boolean }>(rows: T[], random: () => number): T[] {
  const next = rows.slice();
  const slots: number[] = [];
  const movable: T[] = [];
  next.forEach((row, index) => {
    if (row.randomize) {
      slots.push(index);
      movable.push(row);
    }
  });
  for (let index = movable.length - 1; index > 0; index -= 1) {
    const swap = Math.floor(random() * (index + 1));
    const current = movable[index];
    movable[index] = movable[swap];
    movable[swap] = current;
  }
  slots.forEach((slot, index) => {
    next[slot] = movable[index];
  });
  return next;
}

export function toPayload(answer: PreviewAnswer): PreviewPayload {
  const payload: PreviewPayload = {};
  if (answer.rows.length > 0) payload.rows = answer.rows;
  const cells = filled(answer.cells);
  if (Object.keys(cells).length > 0) payload.cells = cells;
  if (answer.value.trim() !== "") payload.value = answer.value.trim();
  const rowValues = filled(answer.row_values);
  if (Object.keys(rowValues).length > 0) payload.row_values = rowValues;
  const openText = filled(answer.open_text);
  if (Object.keys(openText).length > 0) payload.open_text = openText;
  return payload;
}

export function answerReady(screen: PreviewScreen, answer: PreviewAnswer): boolean {
  if (screen.status !== "question") return true;
  if (screen.element === "html" || screen.element === "loop") return true;
  if (screen.element === "checkbox") {
    const minimum = screen.atleast ?? (screen.required ? 1 : 0);
    return answer.rows.length >= minimum && opensReady(screen, answer);
  }
  if (screen.element === "radio" && screen.cols.length > 0) {
    if (!screen.required) return true;
    return screen.rows.every((row) => Boolean(answer.cells[row.label]));
  }
  if (screen.element === "select") return ranksReady(screen, answer);
  if (screen.element === "radio") {
    if (screen.required && answer.rows.length === 0) return false;
    return opensReady(screen, answer);
  }
  if (screen.element === "number" && screen.rows.length > 0) return numbersReady(screen, answer);
  return valueReady(screen, answer);
}

export function answerHint(screen: PreviewScreen, answer: PreviewAnswer): string {
  if (screen.status !== "question" || answerReady(screen, answer)) return "";
  if (screen.check === "date" && answer.value.trim() !== "") return "Enter a date as YYYY-MM-DD.";
  if (screen.check === "total100") return "The numbers need to total 100.";
  if (screen.element === "number" && screen.verify) return "Enter a number in the allowed range.";
  if (screen.element === "select") return "Give each row a different rank.";
  return "Answer this question to continue.";
}

function filled(values: Record<string, string>): Record<string, string> {
  return Object.fromEntries(Object.entries(values).filter(([, value]) => value.trim() !== ""));
}

function opensReady(screen: PreviewScreen, answer: PreviewAnswer): boolean {
  return screen.rows.every(
    (row) => !row.open || !answer.rows.includes(row.label) || (answer.open_text[row.label] ?? "").trim() !== "",
  );
}

function ranksReady(screen: PreviewScreen, answer: PreviewAnswer): boolean {
  const used = new Set<string>();
  for (const row of screen.rows) {
    const choice = (answer.row_values[row.label] ?? "").trim();
    if (screen.required && choice === "") return false;
    if (choice === "") continue;
    if (used.has(choice)) return false;
    used.add(choice);
  }
  return true;
}

function numbersReady(screen: PreviewScreen, answer: PreviewAnswer): boolean {
  const values = screen.rows.map((row) => (answer.row_values[row.label] ?? "").trim());
  const entered = values.filter((value) => value !== "");
  if ((screen.required || screen.check === "total100") && entered.length !== values.length) return false;
  const numbers = entered.map(Number);
  if (numbers.some((value) => Number.isNaN(value))) return false;
  const range = rangeOf(screen.verify);
  if (range && numbers.some((value) => value < range.min || value > range.max)) return false;
  if (screen.check === "total100") {
    const total = numbers.reduce((sum, value) => sum + value, 0);
    if (total !== 100) return false;
  }
  return true;
}

function valueReady(screen: PreviewScreen, answer: PreviewAnswer): boolean {
  const value = answer.value.trim();
  if (value === "") return !screen.required;
  if (screen.element === "number") {
    const parsed = Number(value);
    if (Number.isNaN(parsed)) return false;
    const range = rangeOf(screen.verify);
    if (range && (parsed < range.min || parsed > range.max)) return false;
  }
  if (screen.check === "date") return /^\d{4}-\d{2}-\d{2}$/.test(value);
  return true;
}

function rangeOf(verify: string | null): { min: number; max: number } | null {
  if (!verify) return null;
  const match = /^range\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)$/.exec(verify);
  if (!match) return null;
  return { min: Number(match[1]), max: Number(match[2]) };
}
