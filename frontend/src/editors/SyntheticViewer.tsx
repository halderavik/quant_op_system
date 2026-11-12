import { Badge } from "../ui";

type PersonaRow = { name?: string; description?: string; target_share?: number; completes?: number };
type QuotaRow = { question?: string; label?: string; target?: number; achieved?: number };
type CheckRow = { id?: string; status?: string; details?: string };
type TraitRow = { name?: string; description?: string; questions?: string[] };

/** Read-only summary of a synthetic dataset: counts, personas, quotas, and checks. */
export function SyntheticViewer({ content }: { content: Record<string, unknown> }) {
  const personas = (content.personas ?? []) as PersonaRow[];
  const quotas = (content.quotas ?? []) as QuotaRow[];
  const checks = (content.checks ?? []) as CheckRow[];
  const traits = (content.traits ?? []) as TraitRow[];
  const warnings = (content.warnings ?? []) as string[];
  const completes = Number(content.completes ?? 0);
  const attempts = Number(content.attempts ?? 0);
  const incidence = attempts ? Math.round((completes / attempts) * 100) : 100;
  const fromModel = content.answer_source === "model";
  return (
    <div className="space-y-6 text-sm text-ink">
      <p className="rounded-lg border border-warn-line bg-warn-soft px-3 py-2 text-warn" role="note">
        Synthetic data, not real fieldwork. Use it to test routing, tables, and analysis before the survey goes live.
      </p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Completes" value={completes} />
        <Stat label="Screened out" value={Number(content.terminated ?? 0)} />
        <Stat label="Incidence" value={`${incidence}%`} />
        <Stat label="Variables" value={Number(content.variable_count ?? 0)} />
      </div>
      <div className="space-y-1 rounded-lg border border-line bg-surface p-3">
        <p>
          From Decipher survey v{String(content.decipher_version ?? "")}.{" "}
          {fromModel
            ? `Answer patterns came from the model for ${String(content.profiled_questions ?? 0)} of ${String(content.question_count ?? 0)} questions; Python drew every respondent.`
            : "No model was used, so answers are drawn uniformly."}
        </p>
        <p className="text-ink-2">
          {content.dataset_active
            ? "This is the active dataset, so analysis and tables use it."
            : "Real data stays the active dataset. Switch datasets to analyse this file."}{" "}
          Seed {String(content.seed ?? "")}.
        </p>
      </div>
      {personas.length > 0 && (
        <section>
          <h3 className="mb-2 text-sm font-semibold">Personas</h3>
          <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
            {personas.map((persona) => (
              <li className="px-3 py-2" key={persona.name}>
                <p className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{persona.name}</span>
                  <Badge>{persona.completes ?? 0} completes</Badge>
                  <span className="text-xs text-muted">target {Math.round((persona.target_share ?? 0) * 100)}%</span>
                </p>
                {persona.description && <p className="text-ink-2">{persona.description}</p>}
              </li>
            ))}
          </ul>
        </section>
      )}
      {traits.length > 0 && (
        <section>
          <h3 className="mb-2 text-sm font-semibold">Traits that link answers</h3>
          <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
            {traits.map((trait) => (
              <li className="px-3 py-2" key={trait.name}>
                <p className="font-medium">{trait.name}</p>
                {trait.description && <p className="text-ink-2">{trait.description}</p>}
                <p className="text-xs text-muted">
                  {(trait.questions ?? []).length > 0
                    ? `Moves ${(trait.questions ?? []).join(", ")}`
                    : "No question loads on this trait."}
                </p>
              </li>
            ))}
          </ul>
        </section>
      )}
      <section>
        <h3 className="mb-2 text-sm font-semibold">Quotas</h3>
        {quotas.length === 0 ? (
          <p className="text-ink-2">No quotas were applied.</p>
        ) : (
          <div className="overflow-auto rounded-lg border border-line bg-surface">
            <table className="w-full border-collapse text-left">
              <thead className="bg-sunken">
                <tr className="border-b border-line-strong">
                  <th className="px-3 py-1.5 font-medium" scope="col">Question</th>
                  <th className="px-3 py-1.5 font-medium" scope="col">Cell</th>
                  <th className="px-3 py-1.5 text-right font-medium" scope="col">Target</th>
                  <th className="px-3 py-1.5 text-right font-medium" scope="col">Achieved</th>
                </tr>
              </thead>
              <tbody>
                {quotas.map((row) => (
                  <tr className="border-b border-line last:border-0" key={`${row.question}-${row.label}`}>
                    <td className="px-3 py-1.5 font-mono text-xs">{row.question}</td>
                    <td className="px-3 py-1.5">{row.label}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{row.target}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{row.achieved}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <section>
        <h3 className="mb-2 text-sm font-semibold">Checks</h3>
        <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
          {checks.map((check) => (
            <li className="flex items-start gap-2 px-3 py-2" key={check.id}>
              <Badge tone={check.status === "passed" ? "success" : "danger"}>
                {check.status === "passed" ? "Passed" : "Failed"}
              </Badge>
              <span>{check.details}</span>
            </li>
          ))}
        </ul>
      </section>
      {warnings.length > 0 && (
        <section>
          <h3 className="mb-2 text-sm font-semibold">Notes</h3>
          <ul className="list-disc space-y-1 pl-5 text-warn">
            {warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2.5 shadow-xs">
      <p className="text-[11px] font-medium uppercase tracking-wider text-muted">{label}</p>
      <p className="text-2xl font-semibold tabular-nums">{String(value)}</p>
    </div>
  );
}
