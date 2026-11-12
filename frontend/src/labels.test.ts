import { describe, expect, it } from "vitest";
import { artifactTitle, artifactTypeLabel, saveLabel, validationLabel } from "./labels";

describe("saveLabel", () => {
  it("names the saved state", () => {
    expect(saveLabel("saved")).toBe("Saved");
  });

  it("names an empty-looking conflict", () => {
    expect(saveLabel("conflict")).toContain("Conflict");
  });

  it("does not call a conflict saved", () => {
    expect(saveLabel("conflict")).not.toBe("Saved");
  });
});

describe("artifactTitle", () => {
  it("uses the artifact name", () => {
    expect(artifactTitle("note", "Note")).toBe("Note");
  });
});

describe("artifactTypeLabel", () => {
  it("names the questionnaire and Decipher panels", () => {
    expect(artifactTypeLabel("questionnaire")).toBe("Questionnaire");
    expect(artifactTypeLabel("decipher_survey")).toBe("Decipher survey");
    expect(artifactTypeLabel("sample_purchase")).toBe("Sample purchase");
    expect(artifactTypeLabel("cleaning")).toBe("Data cleaning");
  });

  it("keeps an unknown type readable", () => {
    expect(artifactTypeLabel("custom")).toBe("custom");
  });
});

describe("validationLabel", () => {
  it("turns a warning status into a pill label", () => {
    expect(validationLabel("passed_with_warnings")).toBe("Passed with warnings");
  });
});
