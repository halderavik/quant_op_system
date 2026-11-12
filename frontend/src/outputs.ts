/** Pure helpers for the Outputs panel: grouping, downloads and status tones. */

import { artifactTypeLabel, validationLabel } from "./labels";

export type OutputArtifact = {
  id: string;
  type: string;
  name: string;
  latest: {
    version: number;
    content: Record<string, unknown>;
    stale: boolean;
    validation_status: string;
  } | null;
};

export type StageId = "design" | "fieldwork" | "analysis" | "notes";

export const STAGES: { id: StageId; label: string; types: string[] }[] = [
  { id: "design", label: "Survey design", types: ["questionnaire", "decipher_survey"] },
  { id: "fieldwork", label: "Fieldwork and data", types: ["sample_purchase", "synthetic_data", "cleaning"] },
  {
    id: "analysis",
    label: "Analysis and reporting",
    types: ["tabspec", "crosstab", "analysis", "chart", "codeframe", "coding"],
  },
  { id: "notes", label: "Notes and other", types: ["note"] },
];

const TYPE_ORDER = STAGES.flatMap((stage) => stage.types);

export function stageOf(type: string): StageId {
  return STAGES.find((stage) => stage.types.includes(type))?.id ?? "notes";
}

export type OutputGroup<T extends OutputArtifact> = {
  id: StageId;
  label: string;
  items: T[];
};

/**
 * Group artifacts by workflow stage, in pipeline order, dropping empty stages.
 * The API lists artifacts in creation order, so within one type and name the
 * newest run comes first.
 */
export function groupOutputs<T extends OutputArtifact>(artifacts: T[]): OutputGroup<T>[] {
  const rank = (type: string) => {
    const index = TYPE_ORDER.indexOf(type);
    return index === -1 ? TYPE_ORDER.length : index;
  };
  const position = new Map(artifacts.map((item, index) => [item.id, index]));
  return STAGES.map((stage) => ({
    id: stage.id,
    label: stage.label,
    items: artifacts
      .filter((item) => stageOf(item.type) === stage.id)
      .sort(
        (left, right) =>
          rank(left.type) - rank(right.type) ||
          left.name.localeCompare(right.name) ||
          (position.get(right.id) ?? 0) - (position.get(left.id) ?? 0),
      ),
  })).filter((group) => group.items.length > 0);
}

export type RunInfo = { run: number; of: number; latest: boolean };

/**
 * Number repeated runs that share a type and name (in creation order) so the
 * cards can say "run 3 of 5" and mark the newest one. Unique items are omitted.
 */
export function runNumbers(artifacts: OutputArtifact[]): Map<string, RunInfo> {
  const buckets = new Map<string, string[]>();
  for (const item of artifacts) {
    const key = `${item.type}|${item.name}`;
    buckets.set(key, [...(buckets.get(key) ?? []), item.id]);
  }
  const result = new Map<string, RunInfo>();
  for (const ids of buckets.values()) {
    if (ids.length < 2) continue;
    ids.forEach((id, index) => result.set(id, { run: index + 1, of: ids.length, latest: index === ids.length - 1 }));
  }
  return result;
}

export type Exporter = "tabspec" | "docx" | "pdf";

export type Download =
  | { label: string; kind: "file"; fileId: string }
  | { label: string; kind: "export"; exporter: Exporter };

const FILE_KEYS: [key: string, label: string][] = [
  ["export_file_id", "Excel"],
  ["workbook_file_id", "Workbook"],
  ["plan_file_id", "Plan"],
  ["script_file_id", "Script"],
  ["chart_file_id", "Chart image"],
];

/**
 * Every file a user can download for an artifact. Questionnaires and tab specs
 * export from the latest saved content on demand, so their stored file ids are
 * ignored in favour of an export action.
 */
export function artifactDownloads(artifact: OutputArtifact): Download[] {
  if (artifact.type === "questionnaire") {
    return [
      { label: "DOCX", kind: "export", exporter: "docx" },
      { label: "PDF", kind: "export", exporter: "pdf" },
    ];
  }
  if (artifact.type === "tabspec") {
    return [{ label: "Excel", kind: "export", exporter: "tabspec" }];
  }
  const content = artifact.latest?.content ?? {};
  if (artifact.type === "synthetic_data") {
    const fileId = content.export_file_id;
    return typeof fileId === "string" && fileId ? [{ label: "SPSS .sav", kind: "file", fileId }] : [];
  }
  const downloads: Download[] = [];
  if (artifact.type === "decipher_survey" && typeof content.file_id === "string" && content.file_id) {
    downloads.push({ label: "XML", kind: "file", fileId: content.file_id });
  }
  for (const [key, label] of FILE_KEYS) {
    const value = content[key];
    if (typeof value === "string" && value) {
      downloads.push({ label, kind: "file", fileId: value });
    }
  }
  return downloads;
}

export type Tone = "neutral" | "success" | "warn" | "danger" | "accent";

export function validationTone(status: string): Tone {
  if (status === "passed") return "success";
  if (status === "passed_with_warnings" || status === "needs_review") return "warn";
  if (status === "failed") return "danger";
  return "neutral";
}

/** One line under the card title: "Crosstab · v3". */
export function outputMeta(artifact: OutputArtifact): string {
  const version = artifact.latest ? ` · v${artifact.latest.version}` : " · no revision";
  return `${artifactTypeLabel(artifact.type)}${version}`;
}

export function outputStatus(artifact: OutputArtifact): { label: string; tone: Tone } | null {
  if (!artifact.latest) return null;
  return {
    label: validationLabel(artifact.latest.validation_status),
    tone: validationTone(artifact.latest.validation_status),
  };
}

/** Case-insensitive match on name and type label for the outputs filter box. */
export function matchesQuery(artifact: OutputArtifact, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return `${artifact.name} ${artifactTypeLabel(artifact.type)}`.toLowerCase().includes(needle);
}

/** Keyboard resize for the workspace splitter: arrows move 32px, clamped. */
export function nudgeWidth(width: number, key: string, min: number, max: number): number {
  const step = 32;
  let next = width;
  if (key === "ArrowLeft") next = width + step;
  else if (key === "ArrowRight") next = width - step;
  else if (key === "Home") next = max;
  else if (key === "End") next = min;
  return Math.min(max, Math.max(min, next));
}
