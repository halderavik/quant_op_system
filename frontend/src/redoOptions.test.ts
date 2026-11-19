import { describe, expect, it } from "vitest";
import { doneLabel, redoOptions } from "./redoOptions";

describe("redo options", () => {
  it("names what was done and offers the likely alternatives", () => {
    const imported = "Imported Coffee from coffee.docx exactly as written: 6 questions.";
    expect(doneLabel("create_questionnaire", imported)).toBe("Questionnaire imported as written");
    expect(redoOptions("create_questionnaire", imported).map((o) => o.action)).toEqual(["draft_reference", "general_task"]);
    expect(redoOptions("general_task", "Saved your note.").map((o) => o.action)).toEqual([
      "import_exact",
      "draft_reference",
      "revise_questionnaire",
    ]);
  });

  it("shows nothing when the action is unknown", () => {
    expect(doneLabel(undefined, "x")).toBe("");
    expect(redoOptions(undefined, "x")).toEqual([]);
  });
});
