/** Display helpers covered by a unit test. */

export function saveLabel(state: "saved" | "unsaved" | "conflict" | "saving"): string {
  if (state === "saving") return "Saving";
  if (state === "unsaved") return "Unsaved changes";
  if (state === "conflict") return "Conflict — reload this version";
  return "Saved";
}

export function artifactTitle(type: string, name: string): string {
  return `${name || type}`;
}

const TYPE_LABELS: Record<string, string> = {
  questionnaire: "Questionnaire",
  decipher_survey: "Decipher survey",
  tabspec: "Tab spec",
  crosstab: "Crosstab",
  analysis: "Analysis",
  chart: "Chart",
  codeframe: "Codeframe",
  coding: "Coding",
  note: "Note",
};

export function artifactTypeLabel(type: string): string {
  return TYPE_LABELS[type] ?? type;
}

export function validationLabel(status: string): string {
  if (status === "passed") return "Passed";
  if (status === "passed_with_warnings") return "Passed with warnings";
  if (status === "failed") return "Needs attention";
  if (status === "pending") return "Pending";
  return status;
}
