import { useEffect, useState } from "react";
import type { Artifact } from "./api";
import { downloadUrl, exportQuestionnaire, exportTabspec, previewSource, programDecipher, saveDownload, saveRevision, type SavedRevision } from "./api";
import { AnalysisViewer } from "./editors/AnalysisViewer";
import { CodeframeEditor } from "./editors/CodeframeEditor";
import { CrosstabViewer } from "./editors/CrosstabViewer";
import { DecipherViewer } from "./editors/DecipherViewer";
import { ProvenancePanel } from "./editors/ProvenancePanel";
import { QuestionnaireEditor } from "./editors/QuestionnaireEditor";
import { ReviewQueue } from "./editors/ReviewQueue";
import { TabSpecGrid, tabSpecBlocked } from "./editors/TabSpecGrid";
import { SurveyPreview } from "./editors/SurveyWindow";
import { artifactTypeLabel, saveLabel, validationLabel } from "./labels";
import type { FlowIssue } from "./editors/model";

type SaveState = "saved" | "unsaved" | "conflict" | "saving";

type SurveyWindow = {
  xml: string;
  title: string;
  stale: boolean;
  issues: string[];
};

export function ArtifactEditor({
  artifact,
  projectId,
  currentStage = "",
  onSaved,
  onProgrammed,
}: {
  artifact: Artifact;
  projectId: string;
  currentStage?: string;
  onSaved: () => Promise<void>;
  onProgrammed: (artifactId: string) => Promise<void>;
}) {
  const latest = artifact.latest;
  const [draft, setDraft] = useState<Record<string, unknown>>(latest?.content ?? {});
  const [state, setState] = useState<SaveState>("saved");
  const [message, setMessage] = useState("");
  const [issues, setIssues] = useState<FlowIssue[]>([]);
  const [working, setWorking] = useState(false);
  const [preview, setPreview] = useState<SurveyWindow | null>(null);

  useEffect(() => {
    setDraft(latest?.content ?? {});
    setState("saved");
    setMessage("");
    setIssues(latest?.validation?.issues ?? []);
  }, [artifact.id, latest?.version]);

  useEffect(() => {
    if (artifact.type !== "questionnaire" || state !== "unsaved" || !latest) return;
    const handle = window.setTimeout(() => {
      save(draft);
    }, 400);
    return () => window.clearTimeout(handle);
  }, [artifact.type, draft, latest, state]);

  if (!latest) {
    return <p className="p-6 text-stone-500">This artifact has no revision yet.</p>;
  }

  async function save(next: Record<string, unknown>) {
    if (!latest) return;
    if (artifact.type === "tabspec" && tabSpecBlocked(next)) {
      setState("unsaved");
      setMessage("Fix the table id and banner errors before saving.");
      return;
    }
    setState("saving");
    try {
      const saved: SavedRevision = await saveRevision(artifact.id, next, latest.version);
      setState("saved");
      setMessage(saved.validation_status === "failed" ? "Saved with validation errors." : "");
      setIssues(saved.validation?.issues ?? []);
      await onSaved();
    } catch (error) {
      if (error instanceof Error && error.message === "conflict") {
        setState("conflict");
        setMessage("Someone saved a newer version. Reload the artifact before editing.");
        return;
      }
      setState("unsaved");
      setMessage(error instanceof Error ? error.message : "Save failed.");
    }
  }

  async function downloadTabspec() {
    setWorking(true);
    setMessage("");
    try {
      const exported = await exportTabspec(projectId, draft);
      saveDownload(exported.file_id);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Excel export failed.");
    } finally {
      setWorking(false);
    }
  }

  async function downloadKind(kind: "docx" | "pdf") {
    setWorking(true);
    setMessage("");
    try {
      const exported = await exportQuestionnaire(projectId, kind);
      saveDownload(exported.file_id);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Export failed.");
    } finally {
      setWorking(false);
    }
  }

  async function openDraftPreview() {
    setWorking(true);
    setMessage("");
    try {
      const source = await previewSource(projectId, draft);
      const failed = source.validation_status === "failed";
      setPreview({
        xml: source.xml,
        title: source.title,
        stale: false,
        issues: failed
          ? source.issues.length > 0
            ? source.issues
            : ["The Decipher survey could not be programmed."]
          : [],
      });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "The survey preview could not be opened.");
    } finally {
      setWorking(false);
    }
  }

  function openStoredPreview() {
    const xml = typeof draft.xml === "string" ? draft.xml : "";
    const storedTitle = typeof draft.title === "string" ? draft.title : artifact.name;
    setPreview({
      xml,
      title: storedTitle,
      stale: latest?.stale ?? false,
      issues: xml ? [] : ["The XML file is not ready."],
    });
  }

  async function program() {
    setWorking(true);
    setMessage("");
    try {
      const result = await programDecipher(projectId);
      setMessage(result.summary);
      await onProgrammed(result.artifact_id);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Decipher programming failed.");
    } finally {
      setWorking(false);
    }
  }

  const readOnly = artifact.type === "crosstab" || artifact.type === "chart" || artifact.type === "decipher_survey";
  const blocked = artifact.type === "tabspec" && tabSpecBlocked(draft);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="border-b border-stone-200 bg-white px-4 py-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-stone-500">{artifactTypeLabel(artifact.type)}</p>
            <h2 className="text-lg font-semibold text-stone-900">{artifact.name}</h2>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2">
            {latest.stale && <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-950">Stale</span>}
            <span className="rounded-full bg-stone-100 px-2 py-0.5 text-xs text-stone-700">{validationLabel(latest.validation_status)}</span>
          </div>
        </div>
        {currentStage && <p aria-live="polite" className="mt-2 text-sm text-teal-900">Working · {currentStage}</p>}
        <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
          {artifact.type === "tabspec" && (
            <button className="rounded border border-stone-300 bg-white px-3 py-1.5" disabled={working} onClick={() => void downloadTabspec()} type="button">
              Download Excel
            </button>
          )}
          {artifact.type === "questionnaire" && (
            <>
              <button className="rounded border border-stone-300 bg-white px-3 py-1.5" disabled={working} onClick={() => downloadKind("docx")} type="button">
                Download DOCX
              </button>
              <button className="rounded border border-stone-300 bg-white px-3 py-1.5" disabled={working} onClick={() => downloadKind("pdf")} type="button">
                Download PDF
              </button>
              <button className="rounded border border-stone-300 bg-white px-3 py-1.5" disabled={working} onClick={() => program()} type="button">
                Program in Decipher
              </button>
              <button className="rounded border border-stone-300 bg-white px-3 py-1.5" disabled={working} onClick={() => void openDraftPreview()} type="button">
                Preview survey
              </button>
            </>
          )}
          <span aria-live="polite" className="text-stone-500">{saveLabel(state)}</span>
          {!readOnly && (
            <button
              className="rounded bg-teal-900 px-3 py-1.5 text-white disabled:opacity-50"
              disabled={blocked}
              onClick={() => save(draft)}
              type="button"
            >
              Save
            </button>
          )}
        </div>
      </header>
      {message && <p className="bg-amber-50 px-4 py-2 text-sm text-amber-950">{message}</p>}
      <div className="min-h-0 flex-1 overflow-auto bg-stone-50 p-4">
        {artifact.type === "note" && (
          <textarea
            aria-label="Note text"
            className="h-64 w-full rounded border border-stone-300 p-3"
            value={String(draft.text ?? "")}
            onChange={(event) => {
              setDraft({ ...draft, text: event.target.value });
              setState("unsaved");
            }}
          />
        )}
        {artifact.type === "decipher_survey" && <DecipherViewer content={draft} onPreview={openStoredPreview} />}
        {artifact.type === "questionnaire" && (
          <QuestionnaireEditor
            content={draft}
            issues={issues}
            onChange={(next) => {
              setDraft(next);
              setState("unsaved");
            }}
          />
        )}
        {artifact.type === "tabspec" && (
          <TabSpecGrid
            content={draft}
            onChange={(next) => {
              setDraft(next);
              setState("unsaved");
            }}
          />
        )}
        {artifact.type === "crosstab" && (
          <CrosstabViewer artifactId={artifact.id} content={draft} version={latest.version} />
        )}
        {artifact.type === "analysis" && (
          <AnalysisViewer
            content={draft}
            version={latest.version}
            onChange={(next) => {
              setDraft(next);
              setState("unsaved");
            }}
          />
        )}
        {artifact.type === "chart" && <ChartView content={draft} version={latest.version} />}
        {artifact.type === "codeframe" && (
          <CodeframeEditor
            content={draft}
            onChange={(next) => {
              setDraft(next);
              setState("unsaved");
            }}
          />
        )}
        {artifact.type === "coding" && (
          <ReviewQueue
            content={draft}
            version={latest.version}
            onChange={(next) => {
              setDraft(next);
              setState("unsaved");
            }}
          />
        )}
        {!["note", "questionnaire", "decipher_survey", "tabspec", "crosstab", "analysis", "chart", "codeframe", "coding"].includes(artifact.type) && (
          <pre className="whitespace-pre-wrap text-sm">{JSON.stringify(draft, null, 2)}</pre>
        )}
      </div>
      {preview && (
        <SurveyPreview
          projectId={projectId}
          xml={preview.xml}
          title={preview.title}
          stale={preview.stale}
          issues={preview.issues}
          onClose={() => setPreview(null)}
        />
      )}
    </div>
  );
}

function ChartView({ content, version }: { content: Record<string, unknown>; version: number }) {
  const fileId = content.chart_file_id as string | undefined;
  return (
    <div>
      {fileId && <img alt={String(content.title ?? "Chart")} className="max-w-full" src={downloadUrl(fileId)} />}
      <p className="mt-3 whitespace-pre-wrap text-sm">{String(content.rendered ?? "")}</p>
      {content.script != null && (
        <pre className="mt-3 overflow-auto whitespace-pre-wrap text-sm">{String(content.script)}</pre>
      )}
      <ProvenancePanel content={content} version={version} />
    </div>
  );
}
