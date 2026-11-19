/** What the chat did with a request, and the other actions the person can pick instead. */

export type RedoOption = { action: string; label: string };

const DONE_LABEL: Record<string, string> = {
  create_questionnaire: "Questionnaire",
  revise_questionnaire: "Questionnaire edit",
  program_decipher: "Decipher programming",
  run_analysis: "Analysis",
  run_crosstab: "Tables",
  run_saved_tabspec: "Tables from the tab spec",
  build_tabspec: "Tab spec",
  general_task: "Note or answer",
  clean_data: "Data cleaning",
  buy_sample: "Sample purchase",
  use_connector: "Connected tool",
};

const OPTIONS: Record<string, RedoOption> = {
  import_exact: { action: "import_exact", label: "Import the questionnaire as written" },
  draft_reference: { action: "draft_reference", label: "Draft a new questionnaire from it" },
  revise_questionnaire: { action: "revise_questionnaire", label: "Edit the current questionnaire" },
  program_decipher: { action: "program_decipher", label: "Program it in Decipher" },
  run_analysis: { action: "run_analysis", label: "Run an analysis" },
  run_crosstab: { action: "run_crosstab", label: "Run tables" },
  general_task: { action: "general_task", label: "Just answer" },
};

/** The action label for a reply, or "" when the action is not known. */
export function doneLabel(intent: string | undefined, content: string): string {
  if (!intent) return "";
  if (intent === "create_questionnaire") {
    return /exactly as written/i.test(content) ? "Questionnaire imported as written" : "Questionnaire drafted";
  }
  return DONE_LABEL[intent] ?? "";
}

/** Up to three other actions that make sense instead of the one the chat chose. */
export function redoOptions(intent: string | undefined, content: string): RedoOption[] {
  if (!intent) return [];
  const imported = intent === "create_questionnaire" && /exactly as written/i.test(content);
  const byIntent: Record<string, string[]> = {
    create_questionnaire: imported
      ? ["draft_reference", "general_task"]
      : ["import_exact", "revise_questionnaire", "general_task"],
    revise_questionnaire: ["import_exact", "draft_reference", "general_task"],
    program_decipher: ["revise_questionnaire", "general_task"],
    general_task: ["import_exact", "draft_reference", "revise_questionnaire"],
    run_analysis: ["run_crosstab", "general_task"],
    run_crosstab: ["run_analysis", "general_task"],
    use_connector: ["import_exact", "general_task"],
  };
  return (byIntent[intent] ?? ["general_task"]).filter((key) => key !== intent).slice(0, 3).map((key) => OPTIONS[key]);
}
