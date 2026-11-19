/** Pure edits for a question's programming logic on the review screen. */

import type { Expr, QuestionLite } from "./logic";

export type ConditionDraft = { ref: string; op: string; values: string[] };
export type ShowIfDraft = { join: "and" | "or"; conditions: ConditionDraft[] };

const SIMPLE_OPS = new Set(["eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte", "answered", "not_answered"]);

function asValue(text: string): string | number {
  return /^-?\d+(\.\d+)?$/.test(text.trim()) ? Number(text) : text.trim();
}

function simple(expr: Expr): ConditionDraft | null {
  if (expr.args || expr.kind === "bool" || !expr.ref || !SIMPLE_OPS.has(expr.op)) return null;
  if (expr.row != null || expr.aggregate || expr.value_ref) return null;
  const raw = expr.value == null ? [] : Array.isArray(expr.value) ? expr.value : [expr.value];
  return { ref: expr.ref, op: expr.op, values: raw.map(String) };
}

/**
 * The show-if as editable rows, or null when it uses logic the pickers cannot show
 * (grid rows, counts, comparisons between questions, nested and/or).
 */
export function toDraft(expr: Expr | null | undefined): ShowIfDraft | null {
  if (!expr) return { join: "and", conditions: [] };
  const one = simple(expr);
  if (one) return { join: "and", conditions: [one] };
  if ((expr.op === "and" || expr.op === "or") && expr.args) {
    const conditions = expr.args.map(simple);
    if (conditions.every((c): c is ConditionDraft => c !== null)) return { join: expr.op, conditions };
  }
  return null;
}

function conditionExpr(condition: ConditionDraft): Expr | null {
  if (!condition.ref) return null;
  if (condition.op === "answered" || condition.op === "not_answered") return { kind: "cmp", op: condition.op, ref: condition.ref };
  const values = condition.values.filter((v) => v.trim() !== "").map(asValue);
  if (!values.length) return null;
  const many = values.length > 1;
  let op = condition.op;
  if (many && op === "eq") op = "in";
  if (many && op === "ne") op = "not_in";
  if (!many && op === "in") op = "eq";
  if (!many && op === "not_in") op = "ne";
  const list = op === "in" || op === "not_in";
  return { kind: "cmp", op, ref: condition.ref, value: list ? values : values[0] };
}

/** Rows back to an expression; incomplete rows are left out. */
export function fromDraft(draft: ShowIfDraft): Expr | null {
  const parts = draft.conditions.map(conditionExpr).filter((e): e is Expr => e !== null);
  if (!parts.length) return null;
  if (parts.length === 1) return parts[0];
  return { kind: "bool", op: draft.join, args: parts };
}

type Spec = Record<string, unknown>;

function withSpec(question: QuestionLite, update: Spec): QuestionLite {
  const programming: Spec = { ...(question.programming ?? {}), ...update };
  for (const [key, value] of Object.entries(update)) {
    if (value === undefined) delete programming[key];
  }
  return { ...question, programming };
}

export function setShowIf(question: QuestionLite, draft: ShowIfDraft): QuestionLite {
  return { ...question, display_if: fromDraft(draft) };
}

/** A number box: blank clears the setting. */
export function setNumber(question: QuestionLite, key: "min_value" | "max_value" | "total" | "min_chars", text: string): QuestionLite {
  const trimmed = text.trim();
  const value = trimmed === "" || Number.isNaN(Number(trimmed)) ? null : Number(trimmed);
  return withSpec(question, { [key]: value });
}

export function setRowFilter(question: QuestionLite, source: string, mode: string): QuestionLite {
  if (!source) return withSpec(question, { row_condition: null });
  const old = (question.programming?.row_condition as Spec | null | undefined) ?? {};
  const column = old.source === source ? old.column ?? null : null;
  return withSpec(question, { row_condition: { source, mode: mode || "selected", column } });
}

export function setOptionFlag(question: QuestionLite, optionIndex: number, flag: "terminate" | "anchor" | "exclusive", on: boolean): QuestionLite {
  const options = (question.options ?? []).map((option, index) => (index === optionIndex ? { ...option, [flag]: on } : option));
  return { ...question, options };
}

export function setRandomize(question: QuestionLite, on: boolean): QuestionLite {
  return { ...question, randomize_options: on };
}

export function setTerminateTiming(question: QuestionLite, immediately: boolean): QuestionLite {
  return withSpec(question, { terminate_immediately: immediately });
}

export function setRequired(question: QuestionLite, required: boolean): QuestionLite {
  return { ...question, required };
}

export function setSorted(question: QuestionLite, on: boolean): QuestionLite {
  return withSpec(question, { sort_alphabetically: on });
}

export function setHidden(question: QuestionLite, hidden: boolean): QuestionLite {
  return withSpec(question, { hidden });
}

/** Earlier questions a condition or row filter may point at. */
export function earlierIds(ids: string[], current: string | undefined): string[] {
  const at = current ? ids.indexOf(current) : -1;
  return at < 0 ? ids : ids.slice(0, at);
}

/** Split an excerpt so the question's wording can be highlighted where the file has it. */
export function highlight(excerpt: string, wording: string): { text: string; match: boolean }[] {
  const target = wording.trim().slice(0, 80);
  if (!target) return [{ text: excerpt, match: false }];
  const squash = (s: string) => s.replace(/\s+/g, " ").toLowerCase();
  const flat = squash(excerpt);
  const at = flat.indexOf(squash(target));
  if (at < 0) return [{ text: excerpt, match: false }];
  // Map the position in the squashed text back to the original text.
  let squashed = 0;
  let start = -1;
  let end = excerpt.length;
  let previousSpace = false;
  for (let i = 0; i < excerpt.length; i += 1) {
    const space = /\s/.test(excerpt[i]);
    if (space && previousSpace) continue;
    previousSpace = space;
    if (squashed === at && start < 0) start = i;
    squashed += 1;
    if (start >= 0 && squashed === at + squash(target).length) {
      end = i + 1;
      break;
    }
  }
  if (start < 0) return [{ text: excerpt, match: false }];
  return [
    { text: excerpt.slice(0, start), match: false },
    { text: excerpt.slice(start, end), match: true },
    { text: excerpt.slice(end), match: false },
  ].filter((part) => part.text);
}
