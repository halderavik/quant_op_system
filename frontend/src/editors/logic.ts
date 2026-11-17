/** Plain-language descriptions of a question's programmed logic, for review before programming. */

export type Expr = {
  kind?: "cmp" | "bool";
  op: string;
  ref?: string;
  value?: unknown;
  row?: string | number | null;
  aggregate?: string | null;
  value_ref?: string | null;
  value_row?: string | number | null;
  args?: Expr[];
};

type OptionLite = { code: string | number; label: string; exclusive?: boolean; anchor?: boolean; terminate?: boolean; open_text?: boolean };

export type QuestionLite = {
  id?: string;
  type?: string;
  options?: OptionLite[];
  matrix_items?: string[];
  required?: boolean;
  randomize_options?: boolean;
  display_if?: Expr | null;
  programming?: Record<string, unknown> | null;
};

type DerivedLite = { id: string; label?: string; values?: { code: string | number; label: string; when?: Expr | null; terminate?: boolean }[] };

export type Catalog = Record<string, { options: OptionLite[]; rows: string[]; type?: string }>;

export type LogicLine = { label: string; text: string; todo?: boolean };

const OPS: Record<string, string> = { eq: "=", ne: "≠", gt: ">", gte: "≥", lt: "<", lte: "≤", in: "is one of", not_in: "is not one of" };

export function buildCatalog(questions: QuestionLite[], derived: DerivedLite[]): Catalog {
  const catalog: Catalog = {};
  for (const q of questions) {
    if (q.id) catalog[q.id] = { options: q.options ?? [], rows: q.matrix_items ?? [], type: q.type };
  }
  for (const d of derived) {
    catalog[d.id] = { options: (d.values ?? []).map((v) => ({ code: v.code, label: v.label })), rows: [], type: "derived" };
  }
  return catalog;
}

function optionText(catalog: Catalog, ref: string, code: unknown): string {
  const option = catalog[ref]?.options.find((o) => String(o.code) === String(code));
  return option ? `${code} (${option.label})` : String(code);
}

function rowText(catalog: Catalog, ref: string, row: string | number): string {
  const entry = catalog[ref];
  if (!entry) return `row ${row}`;
  if (entry.rows.length) return `"${entry.rows[Number(row) - 1] ?? `row ${row}`}"`;
  const option = entry.options.find((o) => String(o.code) === String(row));
  return option ? `"${option.label}"` : `row ${row}`;
}

/** "S7 = 1 (Yes)", "qAID "Boursin" = 1 (Yes)", "S9: more than 1 selected", "C2 > C1". */
export function describeExpr(expr: Expr | null | undefined, catalog: Catalog): string {
  if (!expr) return "always";
  if (expr.kind === "bool" || expr.args) {
    const parts = (expr.args ?? []).map((arg) => {
      const text = describeExpr(arg, catalog);
      return arg.args && arg.args.length > 1 ? `(${text})` : text;
    });
    if (expr.op === "not") return `not ${parts[0] ?? ""}`;
    return parts.join(expr.op === "and" ? " and " : " or ");
  }
  const ref = expr.ref ?? "?";
  const subject = expr.row != null ? `${ref} ${rowText(catalog, ref, expr.row)}` : ref;
  if (expr.op === "answered") return `${subject} is answered`;
  if (expr.op === "not_answered") return `${subject} is not answered`;
  if (expr.aggregate === "count") return `${ref}: number selected ${OPS[expr.op] ?? expr.op} ${String(expr.value)}`;
  if (expr.value_ref) {
    const other = expr.value_row != null ? `${expr.value_ref} ${rowText(catalog, expr.value_ref, expr.value_row)}` : expr.value_ref;
    return `${subject} ${OPS[expr.op] ?? expr.op} ${other}`;
  }
  const kind = catalog[ref]?.type;
  const numeric = kind === "numeric" || kind === "allocation";
  const show = (value: unknown) => (numeric && expr.row == null ? String(value) : optionText(catalog, ref, value));
  const value = Array.isArray(expr.value) ? expr.value.map(show).join(", ") : show(expr.value);
  return `${subject} ${OPS[expr.op] ?? expr.op} ${value}`;
}

function codesText(question: QuestionLite, codes: unknown[]): string {
  return codes
    .map((code) => {
      const option = (question.options ?? []).find((o) => String(o.code) === String(code));
      return option ? `${code} ${option.label}` : String(code);
    })
    .join("; ");
}

/** Every piece of logic the survey will be programmed with, then the open to-dos. */
export function logicLines(question: QuestionLite, catalog: Catalog): LogicLine[] {
  const spec = (question.programming ?? {}) as Record<string, any>;
  const lines: LogicLine[] = [];
  lines.push({ label: "Shown", text: spec.hidden ? "never (hidden question)" : question.display_if ? `when ${describeExpr(question.display_if, catalog)}` : "to everyone who reaches it" });
  if (spec.row_condition) {
    const rc = spec.row_condition;
    const mode = rc.mode === "not_selected" ? "not chosen" : rc.mode === "positive" ? "given a number above 0" : "chosen";
    const column = rc.column != null ? ` with ${optionText(catalog, rc.source, rc.column)}` : "";
    lines.push({ label: "Rows", text: `only those ${mode} at ${rc.source}${column}` });
  }
  if (question.required === false) lines.push({ label: "Answer", text: "optional" });
  const ranges: string[] = [];
  if (spec.min_value != null || spec.max_value != null) ranges.push(`from ${spec.min_value ?? "any"} to ${spec.max_value ?? "any"}`);
  if (spec.total != null) ranges.push(`must add up to ${spec.total}`);
  if (spec.min_chars) ranges.push(`at least ${spec.min_chars} characters`);
  if (spec.min_choices || spec.max_choices) ranges.push(`choose ${spec.min_choices ?? 1}${spec.max_choices ? ` to ${spec.max_choices}` : " or more"}`);
  if (spec.boxes) ranges.push(`${spec.boxes} boxes filled in order`);
  if (spec.dropdown) ranges.push("drop-down list");
  if (spec.single_line) ranges.push("single-line text");
  if (spec.multiple) ranges.push("several answers per row");
  if (ranges.length) lines.push({ label: "Entry", text: ranges.join("; ") });
  const order: string[] = [];
  if (question.randomize_options) order.push("randomized");
  if (spec.randomize_columns) order.push("columns randomized");
  if (spec.same_order_as) order.push(`same order as ${spec.same_order_as}`);
  if ((spec.keep_together ?? []).length) order.push(`kept together: ${(spec.keep_together as unknown[][]).map((g) => g.join("+")).join(", ")}`);
  const anchored = (question.options ?? []).filter((o) => o.anchor).map((o) => o.code);
  if (anchored.length) order.push(`anchored: ${codesText(question, anchored)}`);
  if (order.length) lines.push({ label: "Order", text: order.join("; ") });
  const exclusive = (question.options ?? []).filter((o) => o.exclusive).map((o) => o.code);
  if (exclusive.length && question.type === "multi_select") lines.push({ label: "Exclusive", text: codesText(question, exclusive) });
  const others = (question.options ?? []).filter((o) => o.open_text).map((o) => o.code);
  if (others.length) lines.push({ label: "Specify box", text: codesText(question, others) });
  if ((spec.noanswer_codes ?? []).length) lines.push({ label: "No-answer box", text: codesText(question, spec.noanswer_codes) });
  const terminates: string[] = [];
  const flagged = (timing: boolean | undefined) => (timing ? "immediately" : "flag, at the end of the screener if set");
  const optionTerms = (question.options ?? []).filter((o) => o.terminate).map((o) => o.code);
  if (optionTerms.length) terminates.push(`if ${codesText(question, optionTerms)} (${flagged(spec.terminate_immediately)})`);
  if (spec.terminate_when) terminates.push(`if ${describeExpr(spec.terminate_when, catalog)} (${flagged(spec.terminate_immediately)})`);
  for (const rule of spec.terminate_rules ?? []) terminates.push(`if ${describeExpr(rule.when, catalog)} (${flagged(rule.immediately)})`);
  if (terminates.length) lines.push({ label: "Terminate", text: terminates.join("; ") });
  if (spec.autofill) lines.push({ label: "Autopunch", text: `${codesText(question, [spec.autofill.code])}${spec.autofill.when ? ` when ${describeExpr(spec.autofill.when, catalog)}` : ""}` });
  for (const pipe of spec.pipes ?? []) lines.push({ label: "Piping", text: `${pipe.placeholder} shows the answer to ${pipe.source}` });
  for (const check of spec.validations ?? []) lines.push({ label: "Check", text: `error "${check.message}" when ${describeExpr(check.error_when, catalog)}` });
  if ((spec.confirm_codes ?? []).length) lines.push({ label: "Ask again", text: `once for ${codesText(question, spec.confirm_codes)}: "${spec.confirm_message ?? ""}"` });
  for (const option of spec.option_conditions ?? []) lines.push({ label: "Option shown", text: `${codesText(question, [option.code])} only when ${describeExpr(option.when, catalog)}` });
  for (const todo of spec.unresolved ?? []) lines.push({ label: "To-do", text: String(todo), todo: true });
  return lines;
}

export function derivedLines(variable: DerivedLite, catalog: Catalog): LogicLine[] {
  return (variable.values ?? []).map((value) => ({
    label: `${value.code} ${value.label}`,
    text: (value.when ? `when ${describeExpr(value.when, catalog)}` : "assigned by the programmer") + (value.terminate ? " - terminates" : ""),
    todo: !value.when,
  }));
}
