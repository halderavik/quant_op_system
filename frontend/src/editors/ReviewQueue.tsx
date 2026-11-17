import { useState } from "react";
import { downloadUrl } from "../api";
import { ChartGallery } from "./ChartGallery";
import { ProvenancePanel } from "./ProvenancePanel";
import { applyOverride, assignmentsOf, visibleAssignments } from "./model";

export function ReviewQueue({
  content,
  version,
  onChange,
}: {
  content: Record<string, unknown>;
  version?: number;
  onChange: (next: Record<string, unknown>) => void;
}) {
  const [query, setQuery] = useState("");
  const [reviewOnly, setReviewOnly] = useState(false);
  const rows = assignmentsOf(content);
  const visible = visibleAssignments(rows, query, reviewOnly);
  const report = (content.report ?? {}) as { substantive_n?: number; frequencies?: { id: string; label: string; unweighted_respondents: number }[] };
  const engine = (content.autocoder ?? null) as {
    engine?: string;
    model?: string;
    codeframe_size?: number;
    nets?: string[];
    question_text?: string;
  } | null;
  const reviewCount = rows.filter((row) => row.review_required).length;
  const files = [
    ["Coding workbook", content.export_file_id],
    ["AutoCoder workbook", content.autocoder_file_id],
  ] as const;
  return (
    <div className="space-y-3 text-sm">
      {engine && (
        <section className="rounded border border-line p-3">
          <p className="font-semibold">Coded by {engine.engine ?? "Ad Hoc AutoCoder"}</p>
          <p className="text-ink-2">
            {engine.codeframe_size ?? 0} codes under {(engine.nets ?? []).length} nets
            {engine.model ? ` · model ${engine.model}` : ""} · {reviewCount} in the review queue
          </p>
          {engine.question_text && <p className="mt-1 text-ink-2">Question: {engine.question_text}</p>}
          <div className="mt-2 flex flex-wrap gap-4">
            {files.map(([label, fileId]) =>
              typeof fileId === "string" && fileId ? (
                <a key={label} className="underline" href={downloadUrl(fileId)}>
                  Download {label}
                </a>
              ) : null,
            )}
          </div>
        </section>
      )}
      <ChartGallery content={content} />
      <div className="flex flex-wrap items-center gap-3">
        <input
          aria-label="Search responses"
          className="rounded border border-line-strong px-2 py-1"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <label>
          <input
            className="mr-1"
            type="checkbox"
            checked={reviewOnly}
            onChange={(event) => setReviewOnly(event.target.checked)}
          />
          Needs review
        </label>
      </div>
      {visible.length === 0 && <p className="text-muted">No responses match.</p>}
      {visible.map((row) => (
        <fieldset key={row.source_row_id} className="rounded border border-line p-3">
          <legend className="px-1">{row.respondent_id ?? row.source_row_id}</legend>
          <p className="whitespace-pre-wrap">{row.response_text}</p>
          <p className="mt-1 text-muted">Model codes: {(row.assigned_code_ids ?? []).join(", ") || "none"}</p>
          <label className="mt-2 block">
            Final codes
            <input
              aria-label={`Final codes ${row.source_row_id}`}
              className="mt-1 w-full rounded border border-line-strong px-2 py-1"
              value={(row.human_overrides?.code_ids ?? row.assigned_code_ids ?? []).join(", ")}
              onChange={(event) => {
                const codeIds = event.target.value.split(",").map((part) => part.trim()).filter(Boolean);
                const sentiment = row.human_overrides?.sentiment ?? row.sentiment ?? "";
                onChange(replaceRow(content, row.source_row_id, applyOverride(row, codeIds, String(sentiment ?? ""))));
              }}
            />
          </label>
          <label className="mt-2 block">
            Sentiment
            <select
              aria-label={`Sentiment ${row.source_row_id}`}
              className="ml-2 rounded border border-line-strong px-2 py-1"
              value={row.human_overrides?.sentiment ?? row.sentiment ?? ""}
              onChange={(event) => {
                const codeIds = row.human_overrides?.code_ids ?? row.assigned_code_ids ?? [];
                onChange(replaceRow(content, row.source_row_id, applyOverride(row, codeIds, event.target.value)));
              }}
            >
              <option value="">Unset</option>
              {["positive", "negative", "neutral", "mixed", "unclear"].map((label) => (
                <option key={label} value={label}>{label}</option>
              ))}
            </select>
          </label>
        </fieldset>
      ))}
      <section>
        <h3 className="font-semibold">Frequencies</h3>
        <p>Substantive responses: {report.substantive_n ?? "—"}</p>
        <ul className="list-disc pl-5">
          {(report.frequencies ?? []).map((item) => (
            <li key={item.id}>{item.label}: {item.unweighted_respondents}</li>
          ))}
        </ul>
      </section>
      <ProvenancePanel content={content} version={version} />
    </div>
  );
}

function replaceRow(content: Record<string, unknown>, sourceRowId: number, next: ReturnType<typeof applyOverride>) {
  const rows = assignmentsOf(content).map((row) => (row.source_row_id === sourceRowId ? next : row));
  return { ...content, assignments: rows };
}
