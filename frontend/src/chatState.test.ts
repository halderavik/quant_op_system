import { describe, expect, it } from "vitest";
import { TASK_WAIT_MS, activitySteps, artifactToShow, formatElapsed, stillWaiting, type PanelArtifact } from "./chatState";

const questionnaire: PanelArtifact = {
  id: "q",
  type: "questionnaire",
  latest: { version: 1 },
};

describe("stillWaiting", () => {
  it("keeps polling while a draft is running", () => {
    expect(stillWaiting(1_000, 2_000, "running")).toBe(true);
  });

  it("stops at the wait limit", () => {
    expect(stillWaiting(0, TASK_WAIT_MS, "running")).toBe(false);
  });

  it("stops when the task has finished", () => {
    expect(stillWaiting(0, 1_000, "completed_with_warnings")).toBe(false);
  });
});

describe("artifactToShow", () => {
  it("opens a new questionnaire ahead of other new artifacts", () => {
    const note: PanelArtifact = { id: "n", type: "note", latest: { version: 1 } };
    expect(artifactToShow([], [note, questionnaire])?.id).toBe("q");
  });

  it("leaves an unchanged questionnaire closed", () => {
    expect(artifactToShow([questionnaire], [questionnaire])).toBeNull();
  });

  it("does not invent an artifact when the project has none", () => {
    expect(artifactToShow([], [])).toBeNull();
  });

  it("starts with the first real stage when no events have arrived", () => {
    expect(activitySteps([], "running")).toEqual([{ message: "Reading the request", active: true }]);
  });

  it("keeps the first copy of a repeated stage and marks the latest one active", () => {
    const steps = activitySteps(
      [
        { sequence: 1, event_type: "running", message: "Reading the request" },
        { sequence: 2, event_type: "running", message: "Drafting the instrument" },
        { sequence: 3, event_type: "running", message: "Drafting the instrument" },
      ],
      "running",
    );
    expect(steps.map((step) => step.message)).toEqual(["Reading the request", "Drafting the instrument"]);
    expect(steps[1]?.active).toBe(true);
    expect(steps[0]?.active).toBe(false);
  });

  it("does not leave a finished task on an active step", () => {
    const steps = activitySteps(
      [{ sequence: 1, event_type: "completed", message: "Saved the questionnaire." }],
      "completed",
    );
    expect(steps.every((step) => !step.active)).toBe(true);
  });

  it("formats an elapsed stage clock", () => {
    expect(formatElapsed(0)).toBe("0:00");
    expect(formatElapsed(75_000)).toBe("1:15");
  });

  it("opens a decipher survey when that artifact changed", () => {
    const survey: PanelArtifact = { id: "d", type: "decipher_survey", latest: { version: 1 } };
    expect(artifactToShow([questionnaire], [questionnaire, survey])?.id).toBe("d");
  });
});
