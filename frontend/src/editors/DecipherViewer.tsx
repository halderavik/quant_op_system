import { downloadUrl } from "../api";

type CoverageItem = {
  question_id?: string;
  element?: string;
  status?: string;
};

export function DecipherViewer({
  content,
  onPreview,
}: {
  content: Record<string, unknown>;
  onPreview: () => void;
}) {
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
      {launch === "uploaded" && surveyUrl ? (
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
          className="rounded border border-stone-300 bg-white px-3 py-1.5 disabled:opacity-50"
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
        <ul className="list-disc pl-5 text-amber-900">
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
