import { describe, expect, it } from "vitest";
import {
  artifactDownloads,
  groupOutputs,
  matchesQuery,
  nudgeWidth,
  outputMeta,
  outputStatus,
  runNumbers,
  stageOf,
  type OutputArtifact,
} from "./outputs";
import { nextPreference, resolveTheme } from "./theme";

function make(type: string, name: string, content: Record<string, unknown> = {}, status = "passed"): OutputArtifact {
  return { id: `${type}-${name}`, type, name, latest: { version: 2, content, stale: false, validation_status: status } };
}

describe("groupOutputs", () => {
  it("groups by stage in pipeline order and drops empty stages", () => {
    const groups = groupOutputs([
      make("crosstab", "Trust by gender"),
      make("questionnaire", "Brand survey"),
      make("tabspec", "Tab specification"),
      make("cleaning", "Fraud check"),
    ]);
    expect(groups.map((group) => group.id)).toEqual(["design", "fieldwork", "analysis"]);
    expect(groups[2].items.map((item) => item.type)).toEqual(["tabspec", "crosstab"]);
  });

  it("puts unknown types with notes", () => {
    expect(stageOf("mystery")).toBe("notes");
    expect(groupOutputs([make("mystery", "x")])[0].id).toBe("notes");
  });
});

describe("repeated runs", () => {
  it("numbers runs in creation order and lists the newest first", () => {
    const first = { ...make("cleaning", "Fraud check"), id: "a" };
    const second = { ...make("cleaning", "Fraud check"), id: "b" };
    const other = make("crosstab", "Trust");
    const runs = runNumbers([first, other, second]);
    expect(runs.get("a")).toEqual({ run: 1, of: 2, latest: false });
    expect(runs.get("b")).toEqual({ run: 2, of: 2, latest: true });
    expect(runs.has(other.id)).toBe(false);
    const groups = groupOutputs([first, other, second]);
    expect(groups[0].items.map((item) => item.id)).toEqual(["b", "a"]);
  });
});

describe("artifactDownloads", () => {
  it("offers the synthetic dataset as an SPSS file", () => {
    const synthetic = make("synthetic_data", "s", { export_file_id: "file-9" });
    expect(artifactDownloads(synthetic)).toEqual([{ label: "SPSS .sav", kind: "file", fileId: "file-9" }]);
    expect(artifactDownloads(make("synthetic_data", "s"))).toEqual([]);
  });

  it("exports questionnaires and tab specs on demand", () => {
    expect(artifactDownloads(make("questionnaire", "q")).map((item) => item.label)).toEqual(["DOCX", "PDF"]);
    expect(artifactDownloads(make("tabspec", "t", { export_file_id: "old" }))).toEqual([
      { label: "Excel", kind: "export", exporter: "tabspec" },
    ]);
  });

  it("lists stored files for other types", () => {
    expect(artifactDownloads(make("cleaning", "c", { export_file_id: "f1" }))).toEqual([
      { label: "Excel", kind: "file", fileId: "f1" },
    ]);
    expect(
      artifactDownloads(make("analysis", "a", { plan_file_id: "p", script_file_id: "s", workbook_file_id: "w" })).map(
        (item) => item.label,
      ),
    ).toEqual(["Workbook", "Plan", "Script"]);
    expect(artifactDownloads(make("decipher_survey", "d", { file_id: "x" }))[0]).toEqual({
      label: "XML",
      kind: "file",
      fileId: "x",
    });
    expect(artifactDownloads(make("note", "n", { file_id: "x" }))).toEqual([]);
  });
});

describe("card text", () => {
  it("shows type, version and status tone", () => {
    expect(outputMeta(make("crosstab", "t"))).toBe("Crosstab · v2");
    expect(outputStatus(make("crosstab", "t", {}, "passed_with_warnings"))).toEqual({
      label: "Passed with warnings",
      tone: "warn",
    });
    expect(outputStatus(make("codeframe", "c", {}, "needs_review"))).toEqual({ label: "Needs review", tone: "warn" });
    expect(outputStatus({ id: "x", type: "note", name: "n", latest: null })).toBeNull();
  });

  it("filters by name or type label", () => {
    const item = make("sample_purchase", "Prolific quote");
    expect(matchesQuery(item, "sample")).toBe(true);
    expect(matchesQuery(item, "PROLIFIC")).toBe(true);
    expect(matchesQuery(item, "crosstab")).toBe(false);
    expect(matchesQuery(item, "  ")).toBe(true);
  });
});

describe("nudgeWidth", () => {
  it("moves by arrow keys within bounds", () => {
    expect(nudgeWidth(480, "ArrowLeft", 320, 900)).toBe(512);
    expect(nudgeWidth(330, "ArrowRight", 320, 900)).toBe(320);
    expect(nudgeWidth(480, "Home", 320, 900)).toBe(900);
    expect(nudgeWidth(480, "x", 320, 900)).toBe(480);
  });
});

describe("theme", () => {
  it("resolves system preference and cycles", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("light", true)).toBe("light");
    expect(nextPreference("system")).toBe("light");
    expect(nextPreference("dark")).toBe("system");
  });
});
