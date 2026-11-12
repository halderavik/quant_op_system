import { useEffect, useState } from "react";
import type { Artifact } from "./api";
import { Code2, Download as DownloadIcon, Eye } from "lucide-react";
import { downloadUrl, exportTabspec, previewSource, programDecipher, saveDownload, saveRevision, type SavedRevision } from "./api";
import { ArtifactIcon, runDownload } from "./OutputsPanel";
import { artifactDownloads, validationTone, type Download } from "./outputs";
import { Badge, Button } from "./ui";
import { AnalysisViewer } from "./editors/AnalysisViewer";
import { CleaningViewer } from "./editors/CleaningViewer";
import { SyntheticViewer } from "./editors/SyntheticViewer";
import { CodeframeEditor } from "./editors/CodeframeEditor";
import { CrosstabViewer } from "./editors/CrosstabViewer";
import { DecipherViewer } from "./editors/DecipherViewer";
import { SamplePurchaseViewer } from "./editors/SamplePurchaseViewer";
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
    return <p className="p-6 text-muted">This artifact has no revision yet.</p>;
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

  async function download(entry: Download) {
    setWorking(true);
    setMessage("");
    try {
      if (entry.kind === "export" && entry.exporter === "tabspec") {
        // Export the grid as edited, including unsaved changes.
        const exported = await exportTabspec(projectId, draft);
        saveDownload(exported.file_id);
      } else {
        await runDownload(entry, projectId, artifact);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "The download failed.");
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

  const readOnly =
    artifact.type === "crosstab" ||
    artifact.type === "chart" ||
    artifact.type === "decipher_survey" ||
    artifact.type === "sample_purchase" ||
    artifact.type === "cleaning" ||
    artifact.type === "synthetic_data";
  const blocked = artifact.type === "tabspec" && tabSpecBlocked(draft);
  const downloads = artifactDownloads(artifact);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="shrink-0 border-b border-line bg-surface px-4 py-3">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent">
            <ArtifactIcon className="h-5 w-5" type={artifact.type} />
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-base font-semibold text-ink" title={artifact.name}>{artifact.name}</h2>
            <p className="text-xs text-muted">{artifactTypeLabel(artifact.type)} · version {latest.version}</p>
          </div>
          <div className="flex shrink-0 flex-wrap items-center justify-end gap-1.5">
            {latest.stale && <Badge tone="warn">Stale</Badge>}
            <Badge tone={validationTone(latest.validation_status)}>{validationLabel(latest.validation_status)}</Badge>
          </div>
        </div>
        {currentStage && <p aria-live="polite" className="mt-2 text-sm text-accent">Working · {currentStage}</p>}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {artifact.type === "questionnaire" && (
            <>
              <Button disabled={working} onClick={() => void openDraftPreview()} size="sm">
                <Eye aria-hidden className="h-3.5 w-3.5" />
                Preview survey
              </Button>
              <Button disabled={working} onClick={() => program()} size="sm">
                <Code2 aria-hidden className="h-3.5 w-3.5" />
                Program in Decipher
              </Button>
            </>
          )}
          {downloads.map((entry) => (
            <Button key={entry.label} disabled={working} onClick={() => void download(entry)} size="sm">
              <DownloadIcon aria-hidden className="h-3.5 w-3.5" />
              {entry.label}
            </Button>
          ))}
          <span className="ml-auto flex items-center gap-2">
            {!readOnly && (
              <span aria-live="polite" className={state === "conflict" ? "text-xs text-danger" : "text-xs text-muted"}>
                {saveLabel(state)}
              </span>
            )}
            {!readOnly && (
              <Button disabled={blocked || state === "saving"} onClick={() => save(draft)} size="sm" variant="primary">
                Save
              </Button>
            )}
          </span>
        </div>
      </header>
      {message && <p className="shrink-0 border-b border-warn-line bg-warn-soft px-4 py-2 text-sm text-warn" role="status">{message}</p>}
      <div className="min-h-0 flex-1 overflow-auto bg-canvas p-4 sm:p-5">
        {artifact.type === "note" && (
          <textarea
            aria-label="Note text"
            className="h-64 w-full rounded-md border border-line-strong bg-surface p-3"
            value={String(draft.text ?? "")}
            onChange={(event) => {
              setDraft({ ...draft, text: event.target.value });
              setState("unsaved");
            }}
          />
        )}
        {artifact.type === "decipher_survey" && <DecipherViewer content={draft} onPreview={openStoredPreview} />}
        {artifact.type === "sample_purchase" && (
          <SamplePurchaseViewer content={draft} projectId={projectId} onChanged={onProgrammed} />
        )}
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
        {artifact.type === "cleaning" && <CleaningViewer content={draft} />}
        {artifact.type === "synthetic_data" && <SyntheticViewer content={draft} />}
        {!["note", "questionnaire", "decipher_survey", "sample_purchase", "tabspec", "crosstab", "analysis", "chart", "codeframe", "coding", "cleaning", "synthetic_data"].includes(artifact.type) && (
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
      {fileId && <img alt={String(content.title ?? "Chart")} className="max-w-full rounded-md border border-line bg-white p-2" src={downloadUrl(fileId)} />}
      <p className="mt-3 whitespace-pre-wrap text-sm">{String(content.rendered ?? "")}</p>
      {content.script != null && (
        <pre className="mt-3 overflow-auto whitespace-pre-wrap rounded-md border border-line bg-surface p-3 font-mono text-xs">{String(content.script)}</pre>
      )}
      <ProvenancePanel content={content} version={version} />
    </div>
  );
}
