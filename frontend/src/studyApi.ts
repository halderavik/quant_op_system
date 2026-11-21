/** API calls for the logic test, tracking, translation, and segmentation. */

async function parse<T>(response: Response): Promise<T> {
  const body = (await response.json().catch(() => ({}))) as { error?: { message?: string } };
  if (!response.ok) {
    throw new Error(body.error?.message || "The request failed.");
  }
  return body as T;
}

function send(url: string, body: unknown, method = "POST"): Promise<Response> {
  return fetch(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

// ---------------------------------------------------------------- logic test

export type LogicIssue = {
  question_id: string;
  kind: "xml_hides" | "xml_shows" | "xml_continues" | "xml_terminates";
  count: number;
  message: string;
  examples: Record<string, string>[];
};

export type LogicQaResult = {
  respondents: number;
  agreement: number | null;
  terminated: { expected: number; xml: number };
  issues: LogicIssue[];
  questions: { question_id: string; label: string; expected: number; xml: number }[];
  never_shown: string[];
  written_base_without_logic: string[];
  warnings: string[];
  survey_version: number | null;
  questionnaire_version: number;
};

export async function runLogicQa(projectId: string, respondents = 400): Promise<LogicQaResult> {
  return parse(await send(`/api/projects/${projectId}/decipher/qa`, { respondents }));
}

// ---------------------------------------------------------------- tracking

export type Wave = { project_id: string; name: string; wave: number; label: string; has_data: boolean; current: boolean };
export type TrackingState = {
  tracking: { series?: string; wave?: number; label?: string; previous_project_id?: string };
  waves: Wave[];
};
export type WaveChange = {
  question_id: string;
  status: "added" | "removed" | "changed";
  notes: string[];
  breaks_trend: boolean;
};
export type WaveChanges = {
  changes: WaveChange[];
  added: number;
  removed: number;
  changed: number;
  breaks_trend: number;
  unchanged: number;
};
export type TrendCell = {
  wave: string;
  value: number | null;
  base: number;
  change: number | null;
  significant: boolean;
  direction: "up" | "down" | null;
};
export type TrendTable = {
  variable: string;
  label: string;
  kind?: "categorical" | "numeric";
  bases?: { wave: string; base: number }[];
  rows: { code: string; label: string; kind?: string; cells: TrendCell[] }[];
  missing_in: string[];
};
export type TrendResult = {
  waves: { project_id: string; wave: number; label: string; current: boolean }[];
  tables: TrendTable[];
  note: string;
};
export type NamedVariable = { name: string; label: string };

export async function getTracking(projectId: string): Promise<TrackingState> {
  return parse(await fetch(`/api/projects/${projectId}/tracking`));
}

export async function startNextWave(
  projectId: string,
  name: string,
  label: string,
): Promise<{ project_id: string; name: string; wave: number; label: string; copied: string[]; summary: string }> {
  return parse(await send(`/api/projects/${projectId}/tracking/next-wave`, { name, label }));
}

export async function getWaveChanges(projectId: string): Promise<WaveChanges> {
  return parse(await fetch(`/api/projects/${projectId}/tracking/changes`));
}

export async function getTrendVariables(projectId: string): Promise<NamedVariable[]> {
  return parse(await fetch(`/api/projects/${projectId}/tracking/variables`));
}

export async function runTrend(projectId: string, variables: string[]): Promise<TrendResult> {
  return parse(await send(`/api/projects/${projectId}/tracking/trend`, { variables }));
}

// ---------------------------------------------------------------- translation

export type LanguageSummary = {
  artifact_id: string;
  version: number;
  language: string;
  status: "draft" | "approved" | "needs_review";
  approved_by: string;
  approved_at: string;
  total: number;
  missing: number;
  source_changed: number;
  edited: number;
};
export type LanguageSegment = {
  key: string;
  source: string;
  text: string;
  origin: string;
  state: "ok" | "missing" | "source_changed";
};
export type LanguageDetail = LanguageSummary & { segments: LanguageSegment[] };

export async function listLanguages(
  projectId: string,
): Promise<{ source_version: number; segments: number; languages: LanguageSummary[] }> {
  return parse(await fetch(`/api/projects/${projectId}/translations`));
}

export async function getLanguage(projectId: string, artifactId: string): Promise<LanguageDetail> {
  return parse(await fetch(`/api/projects/${projectId}/translations/${artifactId}`));
}

export async function addLanguage(
  projectId: string,
  language: string,
  notes: string,
): Promise<LanguageSummary & { summary: string }> {
  return parse(await send(`/api/projects/${projectId}/translations`, { language, notes }));
}

export async function translateMissing(
  projectId: string,
  artifactId: string,
): Promise<LanguageSummary & { summary: string }> {
  return parse(await send(`/api/projects/${projectId}/translations/${artifactId}/translate`, {}));
}

export async function editSegment(projectId: string, artifactId: string, key: string, text: string): Promise<LanguageDetail> {
  return parse(await send(`/api/projects/${projectId}/translations/${artifactId}/segments`, { key, text }, "PUT"));
}

export async function approveLanguage(projectId: string, artifactId: string, reviewer: string): Promise<LanguageDetail> {
  return parse(await send(`/api/projects/${projectId}/translations/${artifactId}/approve`, { reviewer }));
}

export async function exportLanguage(
  projectId: string,
  artifactId: string,
  kind: "docx" | "pdf" | "xml",
): Promise<{ file_id: string; filename: string; warning: string }> {
  return parse(await fetch(`/api/projects/${projectId}/translations/${artifactId}/export/${kind}`, { method: "POST" }));
}

// ---------------------------------------------------------------- segmentation

export type SegmentProfile = {
  segment: number;
  name: string;
  n: number;
  share: number;
  means: Record<string, number>;
  index: Record<string, number | null>;
  top: { variable: string; label: string; z: number; direction: "higher" | "lower" }[];
};
export type SegmentSolution = {
  k: number;
  silhouette: number;
  calinski: number;
  stability: number;
  smallest: number;
  profiles: SegmentProfile[];
  typing: { variables: string[]; accuracy: number; full_accuracy: number };
};
export type Segmentation = {
  artifact_id: string;
  version: number;
  variables: NamedVariable[];
  base: number;
  dropped: number;
  totals: Record<string, number>;
  solutions: SegmentSolution[];
  recommended: number;
  chosen: number;
};

export async function getSegmentationVariables(projectId: string): Promise<NamedVariable[]> {
  return parse(await fetch(`/api/projects/${projectId}/segmentation/variables`));
}

export async function getSegmentation(projectId: string): Promise<{ segmentation: Segmentation | null }> {
  return parse(await fetch(`/api/projects/${projectId}/segmentation`));
}

export async function runSegmentation(
  projectId: string,
  variables: string[],
  kMin: number,
  kMax: number,
): Promise<Segmentation> {
  return parse(await send(`/api/projects/${projectId}/segmentation`, { variables, k_min: kMin, k_max: kMax }));
}

export async function updateSegmentation(
  projectId: string,
  artifactId: string,
  k: number | null,
  names: Record<string, string>,
): Promise<Segmentation> {
  return parse(await send(`/api/projects/${projectId}/segmentation/${artifactId}`, { k, names }, "PATCH"));
}

export async function typingTool(projectId: string, artifactId: string): Promise<{ file_id: string }> {
  return parse(await fetch(`/api/projects/${projectId}/segmentation/${artifactId}/typing-tool`, { method: "POST" }));
}

export async function saveSegmentsToData(
  projectId: string,
  artifactId: string,
): Promise<{ dataset_id: string; version: number; variable: string; summary: string }> {
  return parse(await fetch(`/api/projects/${projectId}/segmentation/${artifactId}/save-to-data`, { method: "POST" }));
}
