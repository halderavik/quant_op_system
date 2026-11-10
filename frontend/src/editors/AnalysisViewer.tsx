import { downloadUrl } from "../api";
import { ProvenancePanel } from "./ProvenancePanel";

type Report = {
  rendered?: string;
  caveats?: string[];
  claims?: { path?: string; stated_value?: string | number; sentence?: string }[];
  sections?: { id?: string; narrative?: string }[];
};

type Step = {
  step_id?: string;
  kind?: string;
  reason?: string;
  variables?: string[];
  method?: string;
  strategy?: string;
  k?: number;
  box?: number;
};

type Workflow = {
  objective?: string;
  steps?: Step[];
  assumptions?: string[];
  random_seed?: number;
};

function stepSettings(step: Step): string {
  const parts: string[] = [];
  if (step.variables?.length) parts.push(step.variables.join(", "));
  if (step.method) parts.push(step.method);
  if (step.strategy) parts.push(step.strategy);
  if (step.k) parts.push(`k=${step.k}`);
  if ((step.kind === "top_box" || step.kind === "bottom_box") && step.box) {
    parts.push(`box=${step.box}`);
  }
  return parts.join(" · ");
}

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
  const workflow = (content.workflow ?? {}) as Workflow;
  const sections = report.sections ?? [];
  const steps = workflow.steps ?? [];
  const downloads = [
    ["Analysis plan", content.plan_file_id],
    ["Script", content.script_file_id],
    ["Workbook", content.workbook_file_id],
  ] as const;
  return (
    <div className="space-y-4 text-sm">
      {workflow.objective && <h2 className="text-base font-semibold">{workflow.objective}</h2>}
      {steps.length > 0 && (
        <section>
          <h3 className="font-semibold">Analysis plan</h3>
          <ol className="mt-1 list-decimal space-y-2 pl-5">
            {steps.map((step, index) => (
              <li key={step.step_id ?? index}>
                <span className="font-medium">{(step.kind ?? "step").replaceAll("_", " ")}</span>
                {step.reason ? ` — ${step.reason}` : ""}
                {stepSettings(step) && <div className="text-stone-600">{stepSettings(step)}</div>}
              </li>
            ))}
          </ol>
        </section>
      )}
      <div className="flex flex-wrap gap-4">
        {downloads.map(([label, fileId]) =>
          typeof fileId === "string" && fileId ? (
            <a key={label} className="inline-block underline" href={downloadUrl(fileId)}>
              Download {label}
            </a>
          ) : null,
        )}
      </div>
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
      {typeof content.chart_file_id === "string" && content.chart_file_id && (
        <img alt={String(content.title ?? "Chart")} className="max-w-full" src={downloadUrl(content.chart_file_id)} />
      )}
      {!sections.length && <p className="whitespace-pre-wrap">{report.rendered}</p>}
      <ProvenancePanel content={content} version={version} />
    </div>
  );
}
