import { describe, expect, it } from "vitest";
import {
  answerReady,
  emptyAnswer,
  shuffleRows,
  toggleRow,
  type PreviewRow,
  type PreviewScreen,
} from "./surveyPreview";

const row = (label: string, exclusive = false, randomize = true): PreviewRow => ({
  label,
  text: label,
  exclusive,
  open: false,
  randomize,
});

function screen(partial: Partial<PreviewScreen>): PreviewScreen {
  return {
    status: "question",
    label: "Q1",
    element: "radio",
    title: "Question",
    comment: null,
    required: true,
    atleast: null,
    rows: [row("r1")],
    cols: [],
    choices: [],
    shuffle: false,
    verify: null,
    check: "none",
    warning: null,
    message: "",
    ...partial,
  };
}

describe("exclusive rows", () => {
  const rows = [row("r1"), row("r2", true)];

  it("keeps only the exclusive row when that box is checked", () => {
    expect(toggleRow(rows, ["r1"], "r2")).toEqual(["r2"]);
  });

  it("drops the exclusive row when another box is checked", () => {
    expect(toggleRow(rows, ["r2"], "r1")).toEqual(["r1"]);
  });

  it("clears a box that was already checked", () => {
    expect(toggleRow(rows, ["r1"], "r1")).toEqual([]);
  });
});

describe("required answers", () => {
  it("blocks Next until a required choice is selected", () => {
    const radio = screen({});
    expect(answerReady(radio, emptyAnswer())).toBe(false);
    expect(answerReady(radio, { ...emptyAnswer(), rows: ["r1"] })).toBe(true);
  });

  it("lets a display screen continue without an answer", () => {
    expect(answerReady(screen({ element: "html", required: false, rows: [] }), emptyAnswer())).toBe(true);
  });

  it("blocks a required checkbox that has no selection", () => {
    const boxes = screen({ element: "checkbox", atleast: 1, rows: [row("r1"), row("r2")] });
    expect(answerReady(boxes, emptyAnswer())).toBe(false);
  });
});

describe("shuffle", () => {
  it("leaves randomize=0 rows in their original index", () => {
    const rows = [row("a", false, true), row("b", false, false), row("c", false, true)];
    const shuffled = shuffleRows(rows, () => 0);
    expect(shuffled.map((item) => item.label)).toEqual(["c", "b", "a"]);
  });

  it("does not move a list where every row is anchored", () => {
    const rows = [row("a", false, false), row("b", false, false)];
    expect(shuffleRows(rows, () => 0).map((item) => item.label)).toEqual(["a", "b"]);
  });

  it("keeps the authored order when the random draw does not swap", () => {
    const rows = [row("a"), row("b", false, false), row("c")];
    expect(shuffleRows(rows, () => 0.99).map((item) => item.label)).toEqual(["a", "b", "c"]);
  });
});
