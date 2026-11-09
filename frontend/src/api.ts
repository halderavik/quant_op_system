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
  return parse<{ file_id: string; dataset_id?: string | null }>(
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
