import { downloadUrl } from "../api";
import { ProvenancePanel } from "./ProvenancePanel";

type Report = {
  rendered?: string;
  caveats?: string[];
  claims?: { path?: string; stated_value?: string | number; sentence?: string }[];
  sections?: { id?: string; narrative?: string }[];
};

export function AnalysisViewer({
  content,
  version,
  onChange,
}: {
  content: Record<string, unknown>;
  version?: number;
  onChange: (next: Record<string, unknown>) => void;
}) {
  const report = (content.report ?? {}) as Report;
  const result = (content.result ?? {}) as { script?: string; diagnostics?: unknown };
  const sections = report.sections ?? [];
  const fileId = (content.chart_file_id as string | undefined) ?? undefined;
  return (
    <div className="space-y-4 text-sm">
      {sections.map((section, index) => (
        <label key={section.id ?? index} className="block">
          Section {section.id ?? index + 1}
          <textarea
            aria-label={`Section ${section.id ?? index + 1}`}
            className="mt-1 h-28 w-full rounded border border-stone-300 p-2"
            value={section.narrative ?? ""}
            onChange={(event) => {
              const next = sections.slice();
              next[index] = { ...section, narrative: event.target.value };
              onChange({ ...content, report: { ...report, sections: next } });
            }}
          />
        </label>
      ))}
      <label className="block">
        Caveats
        <textarea
          aria-label="Caveats"
          className="mt-1 h-24 w-full rounded border border-stone-300 p-2"
          value={(report.caveats ?? []).join("\n")}
          onChange={(event) => {
            const caveats = event.target.value.split("\n").filter((line) => line.trim());
            onChange({ ...content, report: { ...report, caveats } });
          }}
        />
      </label>
      <section>
        <h3 className="font-semibold">Claims</h3>
        <ul className="mt-1 list-disc pl-5 text-stone-700">
          {(report.claims ?? []).map((claim) => (
            <li key={claim.path}>{claim.sentence} ({String(claim.stated_value)})</li>
          ))}
        </ul>
      </section>
      {result.diagnostics != null && (
        <section>
          <h3 className="font-semibold">Diagnostics</h3>
          <pre className="overflow-auto whitespace-pre-wrap">{JSON.stringify(result.diagnostics, null, 2)}</pre>
        </section>
      )}
      <section>
        <h3 className="font-semibold">Script</h3>
        <pre className="overflow-auto whitespace-pre-wrap">{String(result.script ?? content.script ?? "")}</pre>
      </section>
      {fileId && <img alt={String(content.title ?? "Chart")} className="max-w-full" src={downloadUrl(fileId)} />}
      {!sections.length && <p className="whitespace-pre-wrap">{report.rendered}</p>}
      <ProvenancePanel content={content} version={version} />
    </div>
  );
}
