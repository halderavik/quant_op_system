/** Pure edits for the artifact panel. Components and tests share these functions. */

export type FlowIssue = {
  severity: string;
  code: string;
  message: string;
  question_id?: string | null;
};

export type OptionDraft = { code: string | number; label: string };

export type QuestionDraft = {
  id?: string;
  text?: string;
  type?: string;
  instruction?: string;
  programmer_notes?: string[];
  options?: OptionDraft[];
};

export type TableDraft = {
  id?: string;
  title?: string;
  table_type?: string;
  banner_ids?: string[];
  banner_plans?: string[];
  row_variable_names?: string[];
  section?: string;
  plan_type?: string;
  stub_label?: string;
  base_text?: string;
  row_instruction?: string;
  notes?: string[];
  needs_confirmation?: boolean;
};

export type CrosstabTable = {
  table_id?: string;
  title?: string;
  columns?: { id: string; label: string }[];
  rows?: {
    label: string;
    cells: Record<
      string,
      {
        display_value?: string;
        unweighted_base?: number;
        unweighted_numerator?: number;
        significance_letters?: string;
        weighted_base?: number;
      }
    >;
  }[];
  footnotes?: string[];
};

export type CodeDraft = {
  id: string;
  label: string;
  parent_id?: string | null;
  definition?: string;
  include_examples?: string[];
  exclude_examples?: string[];
};

export type NetDraft = { id: string; label: string; child_ids: string[] };

export type AssignmentDraft = {
  source_row_id: number;
  respondent_id?: string;
  response_text?: string;
  assigned_code_ids?: string[];
  sentiment?: string | null;
  review_required?: boolean;
  substantive?: boolean;
  human_overrides?: { code_ids: string[]; sentiment?: string | null; note?: string | null } | null;
};

export function questionsOf(content: Record<string, unknown>): QuestionDraft[] {
  return Array.isArray(content.questions) ? (content.questions as QuestionDraft[]) : [];
}

export function modulesOf(content: Record<string, unknown>): { id?: string; title?: string; question_ids?: string[] }[] {
  return Array.isArray(content.modules)
    ? (content.modules as { id?: string; title?: string; question_ids?: string[] }[])
    : [];
}

export function withQuestions(content: Record<string, unknown>, questions: QuestionDraft[]): Record<string, unknown> {
  return { ...content, questions };
}

export function moveItem<T>(items: T[], index: number, direction: -1 | 1): T[] {
  const target = index + direction;
  if (target < 0 || target >= items.length) return items.slice();
  const copy = items.slice();
  const [item] = copy.splice(index, 1);
  copy.splice(target, 0, item);
  return copy;
}

export function nextQuestionId(questions: QuestionDraft[]): string {
  const numbers = questions.map((question) => {
    const match = String(question.id ?? "").match(/(\d+)/);
    return match ? Number(match[1]) : 0;
  });
  return `Q${Math.max(0, ...numbers) + 1}`;
}

export function addQuestion(content: Record<string, unknown>): Record<string, unknown> {
  const questions = questionsOf(content);
  const id = nextQuestionId(questions);
  return withQuestions(content, [
    ...questions,
    { id, type: "single_select", text: "New question", options: [{ code: 1, label: "Yes" }] },
  ]);
}

export function deleteQuestion(content: Record<string, unknown>, index: number): Record<string, unknown> {
  const questions = questionsOf(content).slice();
  const removed = questions[index];
  questions.splice(index, 1);
  const modules = modulesOf(content).map((module) => ({
    ...module,
    question_ids: (module.question_ids ?? []).filter((questionId) => questionId !== removed?.id),
  }));
  return { ...content, questions, modules };
}

export function moveQuestion(content: Record<string, unknown>, index: number, direction: -1 | 1): Record<string, unknown> {
  return withQuestions(content, moveItem(questionsOf(content), index, direction));
}

export function updateQuestionText(content: Record<string, unknown>, index: number, text: string): Record<string, unknown> {
  return updateQuestionField(content, index, { text });
}

export function updateQuestionField(
  content: Record<string, unknown>,
  index: number,
  patch: Partial<QuestionDraft>,
): Record<string, unknown> {
  const questions = questionsOf(content).slice();
  questions[index] = { ...questions[index], ...patch };
  return withQuestions(content, questions);
}

export function addOption(content: Record<string, unknown>, index: number): Record<string, unknown> {
  const questions = questionsOf(content).slice();
  const options = [...(questions[index].options ?? [])];
  const codes = options.map((option) => Number(option.code)).filter((code) => !Number.isNaN(code));
  options.push({ code: Math.max(0, ...codes) + 1, label: "New option" });
  questions[index] = { ...questions[index], options };
  return withQuestions(content, questions);
}

export function updateOption(
  content: Record<string, unknown>,
  questionIndex: number,
  optionIndex: number,
  patch: Partial<OptionDraft>,
): Record<string, unknown> {
  const questions = questionsOf(content).slice();
  const options = [...(questions[questionIndex].options ?? [])];
  options[optionIndex] = { ...options[optionIndex], ...patch };
  questions[questionIndex] = { ...questions[questionIndex], options };
  return withQuestions(content, questions);
}

export function deleteOption(content: Record<string, unknown>, questionIndex: number, optionIndex: number): Record<string, unknown> {
  const questions = questionsOf(content).slice();
  const options = [...(questions[questionIndex].options ?? [])];
  options.splice(optionIndex, 1);
  questions[questionIndex] = { ...questions[questionIndex], options };
  return withQuestions(content, questions);
}

export function moveOption(
  content: Record<string, unknown>,
  questionIndex: number,
  optionIndex: number,
  direction: -1 | 1,
): Record<string, unknown> {
  const questions = questionsOf(content).slice();
  const options = moveItem(questions[questionIndex].options ?? [], optionIndex, direction);
  questions[questionIndex] = { ...questions[questionIndex], options };
  return withQuestions(content, questions);
}

export function moveQuestionToModule(content: Record<string, unknown>, questionId: string, moduleId: string): Record<string, unknown> {
  const modules = modulesOf(content).map((module) => ({
    ...module,
    question_ids: (module.question_ids ?? []).filter((item) => item !== questionId),
  }));
  const index = modules.findIndex((module) => module.id === moduleId);
  if (index >= 0) {
    modules[index] = { ...modules[index], question_ids: [...(modules[index].question_ids ?? []), questionId] };
  }
  return { ...content, modules };
}

export function tablesOf(content: Record<string, unknown>): TableDraft[] {
  return Array.isArray(content.tables) ? (content.tables as TableDraft[]) : [];
}

export function bannersOf(content: Record<string, unknown>): { id?: string }[] {
  return Array.isArray(content.banners) ? (content.banners as { id?: string }[]) : [];
}

export function duplicateTable(content: Record<string, unknown>, index: number): Record<string, unknown> {
  const tables = tablesOf(content).slice();
  const source = tables[index];
  if (!source) return content;
  const taken = new Set(tables.map((table) => table.id));
  let suffix = 2;
  let id = `${source.id ?? "T"}-copy`;
  while (taken.has(id)) {
    id = `${source.id ?? "T"}-copy-${suffix}`;
    suffix += 1;
  }
  tables.splice(index + 1, 0, { ...source, id, title: `${source.title ?? "Table"} copy` });
  return { ...content, tables };
}

export function insertTable(content: Record<string, unknown>, index: number): Record<string, unknown> {
  const tables = tablesOf(content).slice();
  const taken = new Set(tables.map((table) => table.id));
  let number = tables.length + 1;
  let id = `T${number}`;
  while (taken.has(id)) {
    number += 1;
    id = `T${number}`;
  }
  tables.splice(index + 1, 0, { id, title: "New table", table_type: "categorical", banner_ids: [] });
  return { ...content, tables };
}

export function deleteTable(content: Record<string, unknown>, index: number): Record<string, unknown> {
  const tables = tablesOf(content).slice();
  tables.splice(index, 1);
  return { ...content, tables };
}

export function sortTables(content: Record<string, unknown>): Record<string, unknown> {
  const tables = tablesOf(content).slice().sort((left, right) => String(left.title ?? "").localeCompare(String(right.title ?? "")));
  return { ...content, tables };
}

export function updateTableTitle(content: Record<string, unknown>, index: number, title: string): Record<string, unknown> {
  return updateTableField(content, index, "title", title);
}

export function updateTableField(
  content: Record<string, unknown>,
  index: number,
  field: keyof TableDraft,
  value: string,
): Record<string, unknown> {
  const tables = tablesOf(content).slice();
  const current = { ...tables[index] };
  if (field === "banner_plans") {
    current.banner_plans = value
      .split("+")
      .map((part) => part.trim().toUpperCase())
      .filter((part) => part === "A" || part === "B");
  } else if (field === "notes") {
    current.notes = value ? [value] : [];
  } else if (field === "stub_label") {
    current.stub_label = value;
    current.row_variable_names = value
      .split(",")
      .map((part) => part.trim())
      .filter(Boolean);
  } else if (
    field === "section" ||
    field === "title" ||
    field === "plan_type" ||
    field === "base_text" ||
    field === "row_instruction" ||
    field === "table_type"
  ) {
    current[field] = value;
  }
  tables[index] = current;
  return { ...content, tables };
}

export function bannerPlanLabel(table: TableDraft): string {
  if (table.banner_plans && table.banner_plans.length > 0) return table.banner_plans.join(" + ");
  return (table.banner_ids ?? []).join(", ");
}

export function tabspecIssues(content: Record<string, unknown>): string[] {
  const issues: string[] = [];
  const tables = tablesOf(content);
  const seen = new Set<string>();
  const banners = new Set(bannersOf(content).map((banner) => banner.id).filter(Boolean));
  tables.forEach((table) => {
    const id = String(table.id ?? "");
    if (!id) issues.push("A table is missing an id.");
    if (id && seen.has(id)) issues.push(`Table id ${id} is duplicated.`);
    seen.add(id);
    (table.banner_ids ?? []).forEach((bannerId) => {
      if (!banners.has(bannerId)) issues.push(`Table ${id} references banner ${bannerId}, which is not on the spec.`);
    });
    if (table.needs_confirmation) issues.push(`Table ${id} needs a confirmed base before it can run.`);
  });
  return issues;
}

export function bookTables(content: Record<string, unknown>): CrosstabTable[] {
  if (Array.isArray(content.tables) && content.tables.length > 0) return content.tables as CrosstabTable[];
  if (content.table && typeof content.table === "object") return [content.table as CrosstabTable];
  return [];
}

export function filterTables(tables: CrosstabTable[], query: string): CrosstabTable[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return tables;
  return tables.filter((table) => `${table.table_id ?? ""} ${table.title ?? ""}`.toLowerCase().includes(needle));
}

export function exceptionLines(content: Record<string, unknown>): string[] {
  if (!Array.isArray(content.exceptions)) return [];
  return content.exceptions.map((item) => {
    if (typeof item === "string") return item;
    const row = item as { table_id?: string; message?: string; reason?: string };
    return [row.table_id, row.message || row.reason].filter(Boolean).join(": ");
  });
}

export function codesOf(content: Record<string, unknown>): CodeDraft[] {
  return Array.isArray(content.codes) ? (content.codes as CodeDraft[]) : [];
}

export function netsOf(content: Record<string, unknown>): NetDraft[] {
  return Array.isArray(content.nets) ? (content.nets as NetDraft[]) : [];
}

export function addCode(content: Record<string, unknown>): Record<string, unknown> {
  const codes = codesOf(content);
  const numbers = codes.map((code) => Number(String(code.id).replace(/\D/g, "")) || 0);
  const id = `C${String(Math.max(0, ...numbers) + 1).padStart(2, "0")}`;
  return { ...content, codes: [...codes, { id, label: "New code", definition: "", include_examples: [], exclude_examples: [] }] };
}

export function updateCode(content: Record<string, unknown>, index: number, patch: Partial<CodeDraft>): Record<string, unknown> {
  const codes = codesOf(content).slice();
  codes[index] = { ...codes[index], ...patch };
  return { ...content, codes };
}

export function deleteCode(content: Record<string, unknown>, index: number): Record<string, unknown> {
  const codes = codesOf(content).slice();
  const removed = codes[index]?.id;
  codes.splice(index, 1);
  const nets = netsOf(content).map((net) => ({
    ...net,
    child_ids: net.child_ids.filter((child) => child !== removed),
  }));
  return { ...content, codes, nets };
}

export function reparentCode(content: Record<string, unknown>, index: number, parentId: string): Record<string, unknown> {
  return updateCode(content, index, { parent_id: parentId || null });
}

export function assignmentsOf(content: Record<string, unknown>): AssignmentDraft[] {
  return Array.isArray(content.assignments) ? (content.assignments as AssignmentDraft[]) : [];
}

export function visibleAssignments(rows: AssignmentDraft[], query: string, reviewOnly: boolean): AssignmentDraft[] {
  const needle = query.trim().toLowerCase();
  return rows.filter((row) => {
    if (reviewOnly && !row.review_required) return false;
    if (!needle) return true;
    return `${row.response_text ?? ""} ${row.respondent_id ?? ""}`.toLowerCase().includes(needle);
  });
}

export function applyOverride(row: AssignmentDraft, codeIds: string[], sentiment: string): AssignmentDraft {
  return {
    ...row,
    human_overrides: {
      code_ids: codeIds,
      sentiment: sentiment || null,
    },
  };
}

export function provenanceRows(content: Record<string, unknown>, version?: number): { label: string; value: string }[] {
  const provenance = (content.provenance ?? {}) as Record<string, unknown>;
  const checks = Array.isArray(provenance.validation)
    ? (provenance.validation as { id?: string; status?: string }[])
    : [];
  return [
    { label: "Artifact version", value: String(version ?? provenance.artifact_version ?? "—") },
    { label: "Dataset", value: String(provenance.dataset_id ?? "—") },
    { label: "Job", value: String(provenance.job_id ?? "—") },
    { label: "Isolation", value: String(provenance.isolation ?? "—") },
    { label: "Warning", value: String(provenance.warning ?? "—") },
    {
      label: "Validation",
      value: checks.length ? checks.map((check) => `${check.id ?? "check"}: ${check.status ?? ""}`).join("; ") : "—",
    },
  ];
}
