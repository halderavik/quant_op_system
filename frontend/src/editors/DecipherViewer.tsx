import { useState } from "react";
import { downloadUrl } from "../api";

type CoverageItem = {
  question_id?: string;
  element?: string;
  status?: string;
};

export function DecipherViewer({
  content,
  onPreview,
  onUpload,
}: {
  content: Record<string, unknown>;
  onPreview: () => void;
  onUpload?: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [kept, setKept] = useState(false);
  const [error, setError] = useState("");
  const fileId = typeof content.file_id === "string" ? content.file_id : "";
  const xml = typeof content.xml === "string" ? content.xml : "";
  const warnings = stringList(content.warnings);
  const items = Array.isArray(content.items) ? (content.items as CoverageItem[]) : [];
  const launch = typeof content.launch === "string" ? content.launch : "not_configured";
  const surveyUrl = typeof content.survey_url === "string" ? content.survey_url : "";
  const surveyPath = typeof content.survey_path === "string" ? content.survey_path : "";
  const launchMessage = typeof content.launch_message === "string" ? content.launch_message : "";
  return (
    <div className="space-y-4 text-sm">
      {launch === "awaiting_confirmation" && !kept ? (
        <div className="rounded-lg border border-accent bg-accent-soft p-3" role="region" aria-label="Upload to Decipher">
          <p className="font-medium text-ink">{launchMessage || "Ready to upload to Decipher."}</p>
          <p className="mt-1 text-ink-2">
            Nothing has been sent yet. Uploading changes your Decipher account; live surveys are never replaced.
          </p>
          {error && <p className="mt-2 text-danger" role="alert">{error}</p>}
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              className="rounded bg-accent px-3 py-1.5 font-medium text-on-accent disabled:opacity-50"
              disabled={busy || !onUpload}
              onClick={async () => {
                if (!onUpload) return;
                setBusy(true);
                setError("");
                try {
                  await onUpload();
                } catch (reason) {
                  setError(reason instanceof Error ? reason.message : "The upload failed.");
                } finally {
                  setBusy(false);
                }
              }}
              type="button"
            >
              {busy ? "Uploading…" : "Upload to Decipher"}
            </button>
            <button
              className="rounded border border-line-strong bg-surface px-3 py-1.5"
              disabled={busy}
              onClick={() => setKept(true)}
              type="button"
            >
              Keep XML only
            </button>
          </div>
        </div>
      ) : launch === "awaiting_confirmation" ? (
        <p>Kept as XML only. Download it below, or ask to upload it later.</p>
      ) : launch === "uploaded" && surveyUrl ? (
        <p>
          Uploaded to Decipher at {surveyPath}.{" "}
          <a className="underline" href={surveyUrl} rel="noreferrer">
            Open survey
          </a>
        </p>
      ) : launch === "failed" ? (
        <p>
          {launchMessage || "Decipher did not accept this survey. Download the XML and import it."}
        </p>
      ) : (
        <p>This XML is for import into Decipher. Direct launch is not connected.</p>
      )}
      <div className="flex flex-wrap gap-3">
        {fileId ? (
          <a className="inline-block underline" href={downloadUrl(fileId)}>Download XML</a>
        ) : (
          <p>The XML file is not ready.</p>
        )}
        <button
          className="rounded border border-line-strong bg-surface px-3 py-1.5 disabled:opacity-50"
          disabled={!xml}
          onClick={onPreview}
          type="button"
        >
          Preview survey
        </button>
      </div>
      <ul className="space-y-1">
        {items.map((item) => (
          <li key={item.question_id}>
            {item.question_id}: {item.element} ({item.status})
          </li>
        ))}
      </ul>
      {warnings.length > 0 && (
        <ul className="list-disc pl-5 text-warn">
          {warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}
