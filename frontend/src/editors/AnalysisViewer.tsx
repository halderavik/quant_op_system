import { downloadUrl } from "../api";
import { ChartGallery } from "./ChartGallery";
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
  k_min?: number;
  k_max?: number;
  box?: number;
};

type Workflow = {
  objective?: string;
  steps?: Step[];
  assumptions?: string[];
  standards?: string[];
  random_seed?: number;
};

type QualityCheck = { area?: string; check?: string; status?: string; detail?: string };
type RankRow = { rank?: number; driver?: string; importance_pct?: number; standardized_coefficient?: number };
type Diagnostics = { quality_checks?: QualityCheck[] };

/** Collect driver rankings from a single fit or from each fit of a multi-step run. */
export function driverRankings(descriptive: Record<string, unknown> | undefined): [string, RankRow[]][] {
  if (!descriptive) return [];
  const own = descriptive.importance_ranking;
  if (Array.isArray(own) && own.length) return [["Key drivers", own as RankRow[]]];
  return Object.entries(descriptive).flatMap(([name, block]) => {
    const ranking = (block as { importance_ranking?: unknown } | null)?.importance_ranking;
    return Array.isArray(ranking) && ranking.length ? [[name, ranking as RankRow[]] as [string, RankRow[]]] : [];
  });
}

function fixed(value: number | undefined, digits: number): string {
  return typeof value === "number" ? value.toFixed(digits) : "";
}

function stepSettings(step: Step): string {
  const parts: string[] = [];
  if (step.variables?.length) parts.push(step.variables.join(", "));
  if (step.method) parts.push(step.method);
  if (step.strategy) parts.push(step.strategy);
  if (step.k) parts.push(`k=${step.k}`);
  else if (step.k_min || step.k_max) parts.push(`test k=${step.k_min ?? 2}–${step.k_max ?? step.k_min}`);
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
  const result = (content.result ?? {}) as {
    script?: string;
    diagnostics?: unknown;
    descriptive?: Record<string, unknown>;
  };
  const checks = ((result.diagnostics ?? {}) as Diagnostics).quality_checks ?? [];
  const flagged = checks.filter((item) => item.status === "flag").length;
  const rankings = driverRankings(result.descriptive);
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
                {stepSettings(step) && <div className="text-ink-2">{stepSettings(step)}</div>}
              </li>
            ))}
          </ol>
        </section>
      )}
      <ChartGallery content={content} />
      {(workflow.standards ?? []).length > 0 && (
        <section>
          <h3 className="font-semibold">Research standards applied</h3>
          <ul className="mt-1 list-disc pl-5 text-ink-2">
            {(workflow.standards ?? []).map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </section>
      )}
      {checks.length > 0 && (
        <section>
          <h3 className="font-semibold">
            Quality checks{" "}
            <span className="font-normal text-ink-2">
              ({checks.length - flagged} passed, {flagged} flagged)
            </span>
          </h3>
          <table className="mt-1 w-full border-collapse text-left text-xs">
            <thead>
              <tr className="border-b border-line">
                <th className="py-1 pr-2">Area</th>
                <th className="py-1 pr-2">Check</th>
                <th className="py-1 pr-2">Status</th>
                <th className="py-1">Detail</th>
              </tr>
            </thead>
            <tbody>
              {checks.map((item, index) => (
                <tr key={index} className="border-b border-line align-top">
                  <td className="py-1 pr-2">{item.area}</td>
                  <td className="py-1 pr-2">{item.check}</td>
                  <td className={`py-1 pr-2 font-medium ${item.status === "flag" ? "text-warn" : "text-success"}`}>
                    {item.status === "flag" ? "Flag" : "Pass"}
                  </td>
                  <td className="py-1">{item.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      {rankings.map(([name, ranking]) => (
        <section key={name}>
          <h3 className="font-semibold">Driver importance{rankings.length > 1 ? ` — ${name}` : ""}</h3>
          <table className="mt-1 w-full border-collapse text-left text-xs">
            <thead>
              <tr className="border-b border-line">
                <th className="py-1 pr-2">Rank</th>
                <th className="py-1 pr-2">Driver</th>
                <th className="py-1 pr-2">Importance</th>
                <th className="py-1">Std. coefficient</th>
              </tr>
            </thead>
            <tbody>
              {ranking.map((row) => (
                <tr key={row.driver} className="border-b border-line">
                  <td className="py-1 pr-2">{row.rank}</td>
                  <td className="py-1 pr-2">{row.driver}</td>
                  <td className="py-1 pr-2">{fixed(row.importance_pct, 1)}%</td>
                  <td className="py-1">{fixed(row.standardized_coefficient, 3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
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
            className="mt-1 h-28 w-full rounded border border-line-strong p-2"
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
          className="mt-1 h-24 w-full rounded border border-line-strong p-2"
          value={(report.caveats ?? []).join("\n")}
          onChange={(event) => {
            const caveats = event.target.value.split("\n").filter((line) => line.trim());
            onChange({ ...content, report: { ...report, caveats } });
          }}
        />
      </label>
      <section>
        <h3 className="font-semibold">Claims</h3>
        <ul className="mt-1 list-disc pl-5 text-ink-2">
          {(report.claims ?? []).map((claim) => (
            <li key={claim.path}>{claim.sentence} ({String(claim.stated_value)})</li>
          ))}
        </ul>
      </section>
      {result.diagnostics != null && (
        <section>
          <h3 className="font-semibold">Diagnostics</h3>
          <pre className="overflow-auto whitespace-pre-wrap rounded-md border border-line bg-surface p-3 font-mono text-xs">{JSON.stringify(result.diagnostics, null, 2)}</pre>
        </section>
      )}
      <section>
        <h3 className="font-semibold">Script</h3>
        <pre className="overflow-auto whitespace-pre-wrap rounded-md border border-line bg-surface p-3 font-mono text-xs">{String(result.script ?? content.script ?? "")}</pre>
      </section>
      {!sections.length && <p className="whitespace-pre-wrap">{report.rendered}</p>}
      <ProvenancePanel content={content} version={version} />
    </div>
  );
}
