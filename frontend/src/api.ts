/** API helpers. The browser never sends or stores an OpenAI key. */

import type { PreviewPayload, PreviewScreen } from "./editors/surveyPreview";

export type Project = {
  id: string;
  name: string;
  active_dataset_id?: string | null;
  conversation_id?: string;
  study_context?: Record<string, unknown>;
};

export type ChatMessage = {
  id: string;
  role: string;
  content: string;
  task_id?: string | null;
  sequence: number;
  intent?: string;
};

export type Artifact = {
  id: string;
  type: string;
  name: string;
  latest: {
    version: number;
    content: Record<string, unknown>;
    stale: boolean;
    validation_status: string;
    content_schema: string;
    validation?: {
      issues?: { severity: string; code: string; message: string; question_id?: string | null }[];
    } | null;
  } | null;
};

async function parse<T>(response: Response): Promise<T> {
  const body = (await response.json().catch(() => ({}))) as { error?: { message?: string } };
  if (!response.ok) {
    throw new Error(body.error?.message || "The request failed.");
  }
  return body as T;
}

export async function listProjects(): Promise<Project[]> {
  return parse(await fetch("/api/projects"));
}

export async function createProject(name: string): Promise<Project> {
  return parse(await fetch("/api/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  }));
}

export async function listMessages(conversationId: string): Promise<ChatMessage[]> {
  return parse(await fetch(`/api/conversations/${conversationId}/messages`));
}

export async function sendMessage(conversationId: string, content: string): Promise<{ task_id: string }> {
  return parse(await fetch(`/api/conversations/${conversationId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  }));
}

export type TaskStage = {
  sequence: number;
  event_type: string;
  message: string;
};

export async function taskStatus(taskId: string): Promise<{
  status: string;
  error?: string | null;
  events?: TaskStage[];
}> {
  return parse(await fetch(`/api/tasks/${taskId}`));
}

export async function cancelTask(taskId: string): Promise<void> {
  await parse(await fetch(`/api/tasks/${taskId}/cancel`, { method: "POST" }));
}

export async function listArtifacts(projectId: string): Promise<Artifact[]> {
  return parse(await fetch(`/api/projects/${projectId}/artifacts`));
}

export type SavedRevision = {
  version: number;
  validation_status?: string;
  validation?: {
    issues?: { severity: string; code: string; message: string; question_id?: string | null }[];
  } | null;
  content?: Record<string, unknown>;
};

export async function saveRevision(
  artifactId: string,
  content: Record<string, unknown>,
  expectedVersion: number,
): Promise<SavedRevision> {
  const response = await fetch(`/api/artifacts/${artifactId}/revisions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content, expected_version: expectedVersion }),
  });
  const body = await response.json().catch(() => ({}));
  if (response.status === 409) {
    throw new Error("conflict");
  }
  if (!response.ok) {
    throw new Error(body?.error?.message || "Save failed.");
  }
  return body as SavedRevision;
}

export async function uploadFile(projectId: string, file: File) {
  const data = new FormData();
  data.append("file", file);
  return parse<{ file_id: string; dataset_id?: string | null; live_quality?: { status: string; message: string } | null }>(
    await fetch(`/api/projects/${projectId}/files`, { method: "POST", body: data }),
  );
}

export async function getDataset(datasetId: string) {
  return parse<{ variables: { name: string; label: string }[]; row_count: number; weight_candidates: string[] }>(
    await fetch(`/api/datasets/${datasetId}`),
  );
}

export function downloadUrl(fileId: string): string {
  return `/api/files/${fileId}/download`;
}

export async function crosstabTable(artifactId: string, tableId: string): Promise<Record<string, unknown>> {
  return parse(await fetch(`/api/artifacts/${artifactId}/tables/${encodeURIComponent(tableId)}`));
}

export async function exportQuestionnaire(
  projectId: string,
  kind: "docx" | "pdf",
): Promise<{ file_id: string }> {
  return parse(await fetch(`/api/projects/${projectId}/questionnaires/export/${kind}`, { method: "POST" }));
}

export async function exportTabspec(
  projectId: string,
  content: Record<string, unknown>,
): Promise<{ file_id: string }> {
  return parse(
    await fetch(`/api/projects/${projectId}/tabspecs/export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(content),
    }),
  );
}

export async function programDecipher(projectId: string): Promise<{
  file_id: string;
  artifact_id: string;
  summary: string;
}> {
  return parse(await fetch(`/api/projects/${projectId}/questionnaires/decipher`, { method: "POST" }));
}

export async function repriceSample(
  projectId: string,
  body: Record<string, unknown>,
): Promise<{ artifact_id: string; summary: string }> {
  return parse(
    await fetch(`/api/projects/${projectId}/sample/quote`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

export async function launchSample(
  projectId: string,
  totalCostCents: number,
): Promise<{ artifact_id: string; summary: string }> {
  return parse(
    await fetch(`/api/projects/${projectId}/sample/launch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: true, total_cost_cents: totalCostCents }),
    }),
  );
}

export async function transitionSample(
  projectId: string,
  action: "PAUSE" | "START" | "STOP",
): Promise<{ artifact_id: string; summary: string }> {
  return parse(
    await fetch(`/api/projects/${projectId}/sample/transition`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    }),
  );
}

export async function refreshSample(
  projectId: string,
): Promise<{ artifact_id: string; summary: string }> {
  return parse(await fetch(`/api/projects/${projectId}/sample/refresh`, { method: "POST" }));
}

export type PreviewSource = {
  xml: string;
  title: string;
  warnings: string[];
  validation_status: string;
  issues: string[];
};

export async function previewSource(
  projectId: string,
  document: Record<string, unknown>,
): Promise<PreviewSource> {
  return parse(
    await fetch(`/api/projects/${projectId}/questionnaires/decipher/preview-source`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(document),
    }),
  );
}

export async function previewStep(
  projectId: string,
  xml: string,
  answers: Record<string, PreviewPayload>,
  currentLabel: string | null,
): Promise<PreviewScreen> {
  return parse(
    await fetch(`/api/projects/${projectId}/questionnaires/decipher/preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ xml, answers, current_label: currentLabel }),
    }),
  );
}

export function saveDownload(fileId: string): void {
  const link = document.createElement("a");
  link.href = downloadUrl(fileId);
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

export async function sendFeedback(artifactId: string, rating: "up" | "down", note = ""): Promise<void> {
  const response = await fetch(`/api/artifacts/${artifactId}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rating, note }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body?.error?.message || "Feedback was not saved.");
  }
}

export type ConnectorTool = { name: string; description: string; read_only: boolean };

export type Connector = {
  id: string;
  catalog_id: string;
  name: string;
  category: string;
  description: string;
  auth: "oauth" | "token";
  server_url: string;
  status: "disconnected" | "connected" | "error";
  error?: string | null;
  configured: boolean;
  client_env: string[];
  has_token: boolean;
  status_note: string;
  setup: string[];
  examples: string[];
  docs_url: string;
  redirect_uri: string;
  scopes: string[];
  tools: ConnectorTool[];
  custom: boolean;
};

export type ConnectorAction = {
  id: string;
  connector: string;
  tool: string;
  summary: string;
  arguments: Record<string, unknown>;
  display?: Record<string, string>;
  status: "pending" | "done" | "failed" | "cancelled";
  result?: string | null;
  created_at: string;
};

export async function listConnectors(): Promise<Connector[]> {
  return parse(await fetch("/api/connectors"));
}

export async function connectConnector(id: string): Promise<{ authorize_url?: string; connector?: Connector }> {
  return parse(await fetch(`/api/connectors/${id}/connect`, { method: "POST" }));
}

export async function testConnector(id: string): Promise<Connector> {
  return parse(await fetch(`/api/connectors/${id}/test`, { method: "POST" }));
}

export async function disconnectConnector(id: string): Promise<void> {
  await parse(await fetch(`/api/connectors/${id}/disconnect`, { method: "POST" }));
}

export async function addCustomConnector(body: { name: string; server_url: string; token: string }): Promise<Connector> {
  return parse(await fetch("/api/connectors/custom", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }));
}

export async function updateConnector(
  id: string,
  body: { server_url?: string; scopes?: string[]; tenant_id?: string; token?: string },
): Promise<Connector> {
  return parse(await fetch(`/api/connectors/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }));
}

export async function listConnectorActions(projectId: string): Promise<ConnectorAction[]> {
  return parse(await fetch(`/api/projects/${projectId}/connector-actions`));
}

export async function decideConnectorAction(id: string, decision: "approve" | "cancel"): Promise<ConnectorAction> {
  return parse(await fetch(`/api/connector-actions/${id}/${decision}`, { method: "POST" }));
}

export type LiveQualityState = {
  enabled: boolean;
  survey_id: string;
  name_id: string;
  fielded: boolean;
  decipher: {
    programmed: boolean;
    survey_url?: string | null;
    survey_path?: string | null;
    uploaded: boolean;
    tracking_in_xml: boolean;
    has_questionnaire: boolean;
    /** Name of the uploaded XML the survey came from, when it was not programmed here. */
    source_file?: string | null;
    file_id?: string | null;
    awaiting_upload?: boolean;
  };
  /** Whether the active dataset carries QOS ids, already has LQ_ variables, and the last merge. */
  data?: { tracked: boolean; merged: boolean; last?: QualityMergeReport | null };
};

/** What joining Live quality results to the survey data added. */
export type QualityMergeReport = {
  status: string;
  message: string;
  records?: number;
  tracked?: number;
  matched?: number;
  unmatched?: number;
  flagged?: number;
  bots?: number;
  merged_at?: string;
  variables?: string[];
};

/** Add or refresh the Live quality flags in the active dataset (saved as a new version). */
export async function mergeLiveQuality(projectId: string): Promise<{ report: QualityMergeReport; state: LiveQualityState }> {
  return parse(await fetch(`/api/projects/${projectId}/live-quality/merge`, { method: "POST" }));
}

export type LiveTextDetail = { question?: string | null; answer?: string | null; quality?: number | null; flagged: boolean; reasons: string[] };

export type LiveRespondent = {
  session_id: string;
  respondent_id?: string | null;
  started?: string | null;
  last_activity?: string | null;
  events: number;
  status: "checked" | "in_progress" | "dropped";
  verdict: "bot" | "human" | "pending";
  confidence?: number | null;
  risk: string;
  text_responses: number;
  text_quality?: number | null;
  text_flagged: number;
  fraud_score?: number | null;
  duplicate: boolean;
  fraud_risk?: string | null;
  straight_lining: boolean;
  speeder: boolean;
  flatliner: boolean;
  pages: number;
  seconds?: number | null;
  flags: string[];
  explanation?: string | null;
  text_details: LiveTextDetail[];
  fraud_reasons?: Record<string, unknown> | null;
  grid_explanation?: string | null;
  timing_explanation?: string | null;
};

export type LiveResults = {
  survey_id: string;
  updated_at: string;
  totals: {
    sessions: number;
    in_progress: number;
    checked: number;
    dropped: number;
    bots: number;
    flagged: number;
    duplicates: number;
    speeders: number;
    straight_liners: number;
    low_quality_text: number;
  };
  text: { responses: number; avg_quality?: number | null; flagged: number; flagged_pct: number };
  fraud: { analyzed: number; avg_score?: number | null; high_risk: number; duplicates: number };
  flag_counts: { flag: string; count: number }[];
  quality_distribution: Record<string, number>;
  trend: { unit: "hour" | "day"; buckets: { start: string; started: number; flagged: number }[] };
  respondents: LiveRespondent[];
};

export type LiveSurvey = {
  survey_id: string;
  respondents: number;
  sessions: number;
  bots: number;
  last_session?: string | null;
  project_id?: string | null;
  project_name?: string | null;
};

export async function listLiveSurveys(): Promise<LiveSurvey[]> {
  return parse(await fetch("/api/live-quality/surveys"));
}

export async function getSurveyResults(surveyId: string): Promise<LiveResults> {
  return parse(await fetch(`/api/live-quality/results?survey_id=${encodeURIComponent(surveyId)}`));
}

export function surveyExportUrl(surveyId: string): string {
  return `/api/live-quality/export?survey_id=${encodeURIComponent(surveyId)}`;
}

export async function getLiveQuality(projectId: string): Promise<LiveQualityState> {
  return parse(await fetch(`/api/projects/${projectId}/live-quality`));
}

/** Add bot and fraud tracking to a Decipher survey XML already uploaded to the project. */
export async function addTrackingToXml(projectId: string, fileId: string): Promise<{
  summary: string;
  file_id: string;
  tracking_survey_id: string;
  state: LiveQualityState;
}> {
  return parse(await fetch(`/api/projects/${projectId}/live-quality/xml`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ file_id: fileId }),
  }));
}

export async function setLiveQuality(
  projectId: string,
  enabled: boolean,
  useProjectName = false,
): Promise<LiveQualityState> {
  return parse(await fetch(`/api/projects/${projectId}/live-quality`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled, use_project_name: useProjectName }),
  }));
}

/** One project's quality rules (see backend app/services/quality_rules.py). */
export type QualityRules = {
  bot_threshold: number;
  bot_signals: string[];
  speeder_page_seconds: number;
  speeder_median_share: number;
  straightline_min_rows: number;
  text_reasons: string[];
  flag_pasted: boolean;
  fraud_threshold: number;
  flag_duplicates: boolean;
  flag_datacenter: boolean;
  terminate_in_survey: boolean;
  terminate_after_page: number;
  terminate_signals: string[];
  privacy_notice: boolean;
  privacy_text: string;
};

export type QualityRulesState = {
  rules: QualityRules;
  defaults: QualityRules;
  changed: (keyof QualityRules)[];
  bot_signals: Record<string, string>;
  text_reasons: Record<string, string>;
  survey_fields: (keyof QualityRules)[];
};

export async function getQualityRules(projectId: string): Promise<QualityRulesState> {
  return parse(await fetch(`/api/projects/${projectId}/live-quality/rules`));
}

export async function saveQualityRules(projectId: string, rules: QualityRules): Promise<QualityRulesState> {
  return parse(await fetch(`/api/projects/${projectId}/live-quality/rules`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(rules),
  }));
}

export async function resetQualityRules(projectId: string): Promise<QualityRulesState> {
  return parse(await fetch(`/api/projects/${projectId}/live-quality/rules`, { method: "DELETE" }));
}

export async function getLiveResults(projectId: string): Promise<LiveResults> {
  return parse(await fetch(`/api/projects/${projectId}/live-quality/results`));
}

export type ProgrammingLesson = {
  id: string;
  status: "active" | "disabled";
  stage: "extraction" | "programming";
  rule: string;
  field: string;
  question_type: string;
  example_instruction: string;
  example_before: { value?: unknown };
  example_after: { value?: unknown };
  support: number;
  updated_at: string;
};

export async function listProgrammingLessons(): Promise<ProgrammingLesson[]> {
  return parse(await fetch("/api/learning/programming-lessons?limit=1000"));
}

export async function setProgrammingLessonStatus(
  id: string,
  status: "active" | "disabled",
): Promise<{ id: string; status: string }> {
  return parse(await fetch(`/api/learning/programming-lessons/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  }));
}

export async function uploadDecipher(projectId: string): Promise<{
  artifact_id: string;
  summary: string;
  launch: string;
}> {
  return parse(await fetch(`/api/projects/${projectId}/decipher/upload`, { method: "POST" }));
}

export type QualityPoint = {
  kind: "import_quality" | "approval_corrections";
  project: string;
  created_at: string;
  title?: string;
  questions?: number;
  sections?: number;
  reread_parts?: number;
  first_read_problems?: number;
  lessons_used?: number;
  extraction?: number;
  programming?: number;
};

export async function getQualityTrend(): Promise<QualityPoint[]> {
  return parse(await fetch("/api/learning/quality-trend?limit=500"));
}

export async function redoTask(taskId: string, action: string): Promise<{ task_id: string }> {
  return parse(await fetch(`/api/tasks/${taskId}/redo`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  }));
}

export type TargetCategory = {
  label: string;
  codes: number[];
  sample_share?: number | null;
  target_share?: number | null;
  origin: "census" | "user" | "sample";
  source_ids: string[];
  note: string;
};

export type WeightingDimension = {
  variable: string;
  label: string;
  categories: TargetCategory[];
  note: string;
};

export type TargetSource = {
  id: string;
  title: string;
  url: string;
  publisher: string;
  year: string;
  note: string;
  verified: boolean;
};

export type WeightResult = {
  weight_variable: string;
  dataset_id: string;
  respondents: number;
  converged: boolean;
  iterations: number;
  efficiency: number;
  effective_base: number;
  design_effect: number;
  min_weight: number;
  max_weight: number;
  capped: number;
  achieved: { variable: string; label: string; sample_share: number; target_share: number; weighted_share: number }[];
  warnings: string[];
};

export type WeightingPlan = {
  population: string;
  dataset_id?: string | null;
  dimensions: WeightingDimension[];
  sources: TargetSource[];
  settings: { min_weight: number; max_weight: number; max_iterations: number; tolerance: number };
  research_note: string;
  status: "proposed" | "built";
  result?: WeightResult | null;
};

export type WeightingCandidate = WeightingDimension & { score: number; concept: string; suggested: boolean };

export type WeightingState = {
  artifact_id: string | null;
  version: number | null;
  plan: WeightingPlan | null;
  project_weight: string | null;
  default_population: string;
  dataset_id: string | null;
  candidates: WeightingCandidate[];
  stale: boolean;
};

export async function getWeighting(projectId: string): Promise<WeightingState> {
  return parse(await fetch(`/api/projects/${projectId}/weighting`));
}

/** Search official statistics for targets on the chosen variables. Takes a minute or two. */
export async function proposeWeighting(
  projectId: string,
  population: string,
  variables: string[],
): Promise<{ summary: string; plan: WeightingPlan; version: number }> {
  return parse(await fetch(`/api/projects/${projectId}/weighting/propose`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ population, variables }),
  }));
}

export async function saveWeighting(
  projectId: string,
  plan: WeightingPlan,
  expectedVersion: number | null,
): Promise<{ plan: WeightingPlan; version: number; problems: string[] }> {
  return parse(await fetch(`/api/projects/${projectId}/weighting`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plan, expected_version: expectedVersion }),
  }));
}

export async function buildWeighting(projectId: string): Promise<{ summary: string; plan: WeightingPlan; version: number }> {
  return parse(await fetch(`/api/projects/${projectId}/weighting/build`, { method: "POST" }));
}

export async function setWeightingUse(projectId: string, enabled: boolean): Promise<{ project_weight: string | null }> {
  return parse(await fetch(`/api/projects/${projectId}/weighting/use`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  }));
}

export type ProgrammerTodo = {
  id: string;
  owner: string;
  owner_kind: "question" | "derived";
  title: string;
  text: string;
  source: "review" | "planner";
  done: boolean;
  fixable: boolean;
};

export type TodoList = {
  todos: ProgrammerTodo[];
  open: number;
  done: number;
  questionnaire_version: number | null;
  xml_stale: boolean;
  summary?: string;
  artifact_id?: string | null;
  fixed?: number;
  remaining?: number;
};

export async function listTodos(projectId: string): Promise<TodoList> {
  return parse(await fetch(`/api/projects/${projectId}/decipher/todos`));
}

export async function markTodos(projectId: string, ids: string[], done: boolean): Promise<TodoList> {
  return parse(
    await fetch(`/api/projects/${projectId}/decipher/todos/mark`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids, done }),
    }),
  );
}

export async function fixTodos(projectId: string, ids: string[]): Promise<TodoList> {
  return parse(
    await fetch(`/api/projects/${projectId}/decipher/todos/fix`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids }),
    }),
  );
}

export type XmlCheck = { area: string; check: string; passed: boolean; detail: string; item: string };

export type XmlCompareRow = {
  key: string;
  label: string;
  status: "match" | "differs" | "missing" | "extra";
  passed: number;
  total: number;
  generated_xml: string;
  reference_xml: string;
  checks: XmlCheck[];
};

export type XmlComparison = {
  match: number | null;
  areas: Record<string, { passed: number; total: number }>;
  questions: XmlCompareRow[];
  other_checks: XmlCheck[];
  not_scored: Record<string, string[]>;
  generated_version: number | null;
};

export async function compareXml(projectId: string, xml: string): Promise<XmlComparison> {
  return parse(
    await fetch(`/api/projects/${projectId}/decipher/compare`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ xml }),
    }),
  );
}
