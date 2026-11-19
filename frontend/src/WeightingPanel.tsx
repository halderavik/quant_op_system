/** Weighting tab: census targets with references, user edits, building the weight, and using it. */

import { AlertTriangle, BadgeCheck, ExternalLink, Plus, Scale, Search, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  type TargetCategory,
  type WeightingCandidate,
  type WeightingDimension,
  type WeightingPlan,
  type WeightingState,
  buildWeighting,
  getWeighting,
  proposeWeighting,
  saveWeighting,
  setWeightingUse,
} from "./api";
import { Button, cn } from "./ui";

const EMPTY_SETTINGS = { min_weight: 0.3, max_weight: 3, max_iterations: 200, tolerance: 1e-6 };

/** Sum of a dimension's targets, ignoring blanks. */
export function targetSum(dimension: WeightingDimension): number {
  return dimension.categories.reduce((total, category) => total + (category.target_share ?? 0), 0);
}

/** A plan the user can fill in by hand from the chosen variables. */
function blankPlan(population: string, candidates: WeightingCandidate[]): WeightingPlan {
  return {
    population,
    dimensions: candidates.map(({ score: _score, concept: _concept, suggested: _suggested, ...dimension }) => ({
      ...dimension,
      categories: dimension.categories.map((category) => ({ ...category, target_share: null, origin: "user" })),
    })),
    sources: [],
    settings: EMPTY_SETTINGS,
    research_note: "",
    status: "proposed",
    result: null,
  };
}

/** A variable label without the variable name it starts with, such as "Q17: Gender". */
function stripName(label: string, name: string): string {
  return label.startsWith(`${name}:`) ? label.slice(name.length + 1).trim() : label;
}

function percent(value: number | null | undefined, digits = 1): string {
  return value === null || value === undefined ? "—" : `${value.toFixed(digits)}%`;
}

/** The Weighting panel for one project. */
export function WeightingPanel({ projectId, onChanged, onError }: {
  projectId: string;
  onChanged: () => Promise<void>;
  onError: (message: string) => void;
}) {
  const [state, setState] = useState<WeightingState | null>(null);
  const [draft, setDraft] = useState<WeightingPlan | null>(null);
  const [version, setVersion] = useState<number | null>(null);
  const [dirty, setDirty] = useState(false);
  const [population, setPopulation] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [problems, setProblems] = useState<string[]>([]);
  const [adding, setAdding] = useState("");

  async function load() {
    const next = await getWeighting(projectId);
    setState(next);
    setDraft(next.plan);
    setVersion(next.version);
    setDirty(false);
    setPopulation(next.plan?.population || next.default_population || "");
    setChosen(
      next.plan?.dimensions.map((item) => item.variable)
        ?? next.candidates.filter((item) => item.suggested).map((item) => item.variable),
    );
  }

  useEffect(() => {
    setState(null);
    setNotice("");
    setProblems([]);
    load().catch((reason: Error) => onError(reason.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const candidates = useMemo(() => new Map((state?.candidates ?? []).map((item) => [item.variable, item])), [state]);

  async function run(label: string, work: () => Promise<void>) {
    setBusy(label);
    setNotice("");
    try {
      await work();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "The request failed.");
    } finally {
      setBusy("");
    }
  }

  function edit(change: (plan: WeightingPlan) => WeightingPlan) {
    setDraft((current) => (current ? change(current) : current));
    setDirty(true);
  }

  function setTarget(dimensionIndex: number, categoryIndex: number, raw: string) {
    const value = raw.trim() === "" ? null : Number(raw);
    edit((plan) => ({
      ...plan,
      dimensions: plan.dimensions.map((dimension, d) => d !== dimensionIndex ? dimension : {
        ...dimension,
        categories: dimension.categories.map((category, c): TargetCategory => c !== categoryIndex ? category : {
          ...category,
          target_share: value === null || Number.isNaN(value) ? null : value,
          origin: "user",
        }),
      }),
    }));
  }

  async function save(): Promise<boolean> {
    if (!draft) return false;
    const saved = await saveWeighting(projectId, { ...draft, population }, version);
    setDraft(saved.plan);
    setVersion(saved.version);
    setDirty(false);
    setProblems(saved.problems);
    return saved.problems.length === 0;
  }

  if (!state) return <p className="p-4 text-sm text-muted">Loading weighting…</p>;
  if (!state.dataset_id) {
    return (
      <p className="m-4 rounded-md bg-sunken px-3 py-2 text-sm text-ink-2">
        Upload the survey data (an SPSS file) before building a weight.
      </p>
    );
  }
  const result = draft?.result ?? null;
  const used = Boolean(result && state.project_weight === result.weight_variable);
  const sources = new Map((draft?.sources ?? []).map((source) => [source.id, source]));
  const notIncluded = (state.candidates ?? []).filter((item) => !draft?.dimensions.some((d) => d.variable === item.variable));

  return (
    <div className="space-y-4 p-4">
      <section className="rounded-xl border border-line bg-surface p-4 shadow-xs">
        <div className="flex items-start gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent">
            <Scale aria-hidden className="h-5 w-5" />
          </span>
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold">Weight the sample to the population</h3>
            <p className="mt-0.5 text-sm text-ink-2">
              The research agent looks up official census figures for the variables you pick and proposes a target for each answer,
              with its source. Accept them, change any number, or type your own, then build a rim weight.
            </p>
          </div>
        </div>
        <label className="mt-3 block text-xs font-medium text-ink-2" htmlFor="weighting-population">Who the survey represents</label>
        <textarea
          className="mt-1 w-full rounded-md border border-line-strong bg-surface px-2.5 py-1.5 text-sm"
          id="weighting-population"
          onChange={(event) => setPopulation(event.target.value)}
          placeholder="For example: US adults aged 18 to 65 who drink coffee at home"
          rows={2}
          value={population}
        />
        <fieldset className="mt-3">
          <legend className="text-xs font-medium text-ink-2">Variables to weight on</legend>
          <div className="mt-1 flex max-h-40 flex-wrap gap-1.5 overflow-y-auto">
            {[...state.candidates].sort((a, b) => Number(b.suggested) - Number(a.suggested)).map((item) => {
              const on = chosen.includes(item.variable);
              return (
                <label
                  className={cn(
                    "inline-flex min-w-0 max-w-[15rem] cursor-pointer items-center gap-1.5 rounded-md border px-2 py-1 text-xs",
                    on ? "border-accent bg-accent-soft text-ink" : "border-line text-ink-2 hover:bg-sunken",
                  )}
                  key={item.variable}
                  title={item.label}
                >
                  <input
                    checked={on}
                    className="h-3.5 w-3.5 accent-[var(--color-accent)]"
                    onChange={() => setChosen((list) => on ? list.filter((name) => name !== item.variable) : [...list, item.variable])}
                    type="checkbox"
                  />
                  <span className="font-medium">{item.variable}</span>
                  <span className="min-w-0 truncate text-muted">{stripName(item.label, item.variable)}</span>
                </label>
              );
            })}
          </div>
        </fieldset>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button
            disabled={Boolean(busy) || !chosen.length || !population.trim()}
            onClick={() => void run("research", async () => {
              const outcome = await proposeWeighting(projectId, population, chosen);
              setNotice(outcome.summary);
              await load();
              await onChanged();
            })}
            size="sm"
            variant="primary"
          >
            <Search aria-hidden className="h-3.5 w-3.5" />
            {busy === "research" ? "Searching official statistics…" : "Research census targets"}
          </Button>
          <Button
            disabled={Boolean(busy) || !chosen.length}
            onClick={() => {
              setDraft(blankPlan(population, chosen.map((name) => candidates.get(name)).filter((item): item is WeightingCandidate => Boolean(item))));
              setDirty(true);
              setProblems([]);
            }}
            size="sm"
          >
            Enter targets myself
          </Button>
          {busy === "research" && <span className="text-xs text-muted">This usually takes one to two minutes.</span>}
        </div>
        {notice && <p className="mt-3 rounded-md bg-accent-soft px-3 py-2 text-sm text-ink" role="status">{notice}</p>}
      </section>

      {draft && (
        <section className="rounded-xl border border-line bg-surface p-4 shadow-xs">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="min-w-0 flex-1 text-sm font-semibold">Targets</h3>
            {dirty && <span className="text-xs text-muted">Unsaved changes</span>}
            <Button disabled={Boolean(busy) || !dirty} onClick={() => void run("save", async () => { await save(); })} size="sm">
              {busy === "save" ? "Saving…" : "Save targets"}
            </Button>
            <Button
              disabled={Boolean(busy) || !draft.dimensions.length}
              onClick={() => void run("build", async () => {
                if (dirty && !(await save())) return;
                const outcome = await buildWeighting(projectId);
                setNotice(outcome.summary);
                await load();
                await onChanged();
              })}
              size="sm"
              variant="primary"
            >
              {busy === "build" ? "Building…" : draft.status === "built" && !dirty ? "Rebuild weight" : "Build weight"}
            </Button>
          </div>
          {draft.research_note && <p className="mt-2 text-xs text-ink-2">{draft.research_note}</p>}
          {problems.length > 0 && (
            <ul className="mt-3 space-y-1 rounded-md border border-warn-line bg-warn-soft px-3 py-2 text-sm text-warn" role="alert">
              {problems.map((problem) => <li key={problem}>{problem}</li>)}
            </ul>
          )}

          {draft.dimensions.map((dimension, d) => {
            const sum = targetSum(dimension);
            const off = Math.abs(sum - 100) > 0.5;
            return (
              <div className="mt-4" key={dimension.variable}>
                <div className="flex items-center gap-2">
                  <p className="min-w-0 flex-1 truncate text-sm font-medium" title={dimension.label}>
                    {dimension.variable}
                    <span className="font-normal text-muted"> · {stripName(dimension.label, dimension.variable)}</span>
                  </p>
                  <button
                    aria-label={`Remove ${dimension.variable}`}
                    className="rounded p-1 text-muted hover:bg-sunken hover:text-ink"
                    onClick={() => edit((plan) => ({ ...plan, dimensions: plan.dimensions.filter((_, index) => index !== d) }))}
                    title={`Remove ${dimension.variable}`}
                    type="button"
                  >
                    <Trash2 aria-hidden className="h-3.5 w-3.5" />
                  </button>
                </div>
                <div className="mt-1 overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-line text-left text-xs text-muted">
                        <th className="py-1 pr-2 font-medium">Category</th>
                        <th className="w-20 py-1 pr-2 text-right font-medium">Sample</th>
                        <th className="w-24 py-1 pr-2 text-right font-medium">Target %</th>
                        <th className="py-1 font-medium">Source</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dimension.categories.map((category, c) => (
                        <tr className="border-b border-line/60 align-top" key={`${category.label}-${c}`}>
                          <td className="py-1.5 pr-2">
                            {category.label}
                            {category.codes.length > 1 && <span className="text-xs text-muted"> (codes {category.codes.join(", ")})</span>}
                            {category.note && <p className="text-xs text-muted">{category.note}</p>}
                          </td>
                          <td className="py-1.5 pr-2 text-right tabular-nums text-ink-2">{percent(category.sample_share)}</td>
                          <td className="py-1 pr-2 text-right">
                            <input
                              aria-label={`Target for ${dimension.variable} ${category.label}`}
                              className="w-20 rounded-md border border-line-strong bg-surface px-2 py-1 text-right tabular-nums"
                              inputMode="decimal"
                              onChange={(event) => setTarget(d, c, event.target.value)}
                              step="0.1"
                              type="number"
                              value={category.target_share ?? ""}
                            />
                          </td>
                          <td className="py-1.5 text-xs">
                            {category.origin === "user" ? (
                              <span className="text-muted">Your target</span>
                            ) : category.source_ids.length ? (
                              category.source_ids.map((id) => {
                                const source = sources.get(id);
                                return source ? (
                                  <a className="mr-1 inline-flex items-center gap-0.5 text-accent hover:underline" href={source.url} key={id} rel="noreferrer" target="_blank" title={source.title}>
                                    [{id}] <ExternalLink aria-hidden className="h-3 w-3" />
                                  </a>
                                ) : <span className="mr-1 text-muted" key={id}>[{id}]</span>;
                              })
                            ) : (
                              <span className="text-muted">No source</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot>
                      <tr>
                        <td className="py-1 pr-2 text-xs text-muted">Total</td>
                        <td />
                        <td className={cn("py-1 pr-2 text-right text-xs font-semibold tabular-nums", off ? "text-danger" : "text-success")}>
                          {sum.toFixed(1)}%
                        </td>
                        <td className="py-1 text-xs text-muted">{off ? "Targets must add up to 100%." : ""}</td>
                      </tr>
                    </tfoot>
                  </table>
                </div>
              </div>
            );
          })}

          {notIncluded.length > 0 && (
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <label className="text-xs font-medium text-ink-2" htmlFor="weighting-add">Add a variable</label>
              <select
                className="h-8 min-w-0 max-w-xs rounded-md border border-line-strong bg-surface px-2 text-sm"
                id="weighting-add"
                onChange={(event) => setAdding(event.target.value)}
                value={adding}
              >
                <option value="">Choose…</option>
                {notIncluded.map((item) => <option key={item.variable} value={item.variable}>{item.variable} · {item.label}</option>)}
              </select>
              <Button
                disabled={!adding}
                onClick={() => {
                  const item = candidates.get(adding);
                  if (!item) return;
                  const { score: _score, concept: _concept, suggested: _suggested, ...dimension } = item;
                  edit((plan) => ({
                    ...plan,
                    dimensions: [...plan.dimensions, { ...dimension, categories: dimension.categories.map((category) => ({ ...category, target_share: null, origin: "user" })) }],
                  }));
                  setAdding("");
                }}
                size="sm"
              >
                <Plus aria-hidden className="h-3.5 w-3.5" />
                Add
              </Button>
            </div>
          )}

          <div className="mt-4 flex flex-wrap items-center gap-3 text-xs text-ink-2">
            <span className="font-medium">Weight caps</span>
            {(["min_weight", "max_weight"] as const).map((key) => (
              <label className="inline-flex items-center gap-1" key={key}>
                {key === "min_weight" ? "lowest" : "highest"}
                <input
                  className="w-16 rounded-md border border-line-strong bg-surface px-2 py-1 text-right tabular-nums"
                  min={key === "min_weight" ? 0.01 : 1}
                  onChange={(event) => {
                    const value = Number(event.target.value);
                    if (!Number.isNaN(value)) edit((plan) => ({ ...plan, settings: { ...plan.settings, [key]: value } }));
                  }}
                  step="0.1"
                  type="number"
                  value={draft.settings[key]}
                />
              </label>
            ))}
            <span className="text-muted">Relative to an average weight of 1.</span>
          </div>

          {draft.sources.length > 0 && (
            <div className="mt-4">
              <p className="text-xs font-medium text-ink-2">References</p>
              <ul className="mt-1 space-y-1.5">
                {draft.sources.map((source) => (
                  <li className="text-sm" key={source.id}>
                    <span className="font-medium">[{source.id}]</span>{" "}
                    <a className="text-accent hover:underline" href={source.url} rel="noreferrer" target="_blank">{source.title || source.url}</a>
                    {(source.publisher || source.year) && <span className="text-muted"> · {[source.publisher, source.year].filter(Boolean).join(", ")}</span>}
                    {source.verified ? (
                      <span className="ml-2 inline-flex items-center gap-0.5 text-xs text-success"><BadgeCheck aria-hidden className="h-3 w-3" />Found by the search</span>
                    ) : (
                      <span className="ml-2 inline-flex items-center gap-0.5 text-xs text-warn"><AlertTriangle aria-hidden className="h-3 w-3" />Not confirmed, check it</span>
                    )}
                    {source.note && <p className="text-xs text-muted">{source.note}</p>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}

      {result && (
        <section className="rounded-xl border border-line bg-surface p-4 shadow-xs">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="min-w-0 flex-1 text-sm font-semibold">Weight {result.weight_variable}</h3>
            {draft?.status !== "built" && <span className="text-xs text-warn">Targets changed since this was built</span>}
          </div>
          {state.stale && (
            <p className="mt-2 flex items-center gap-2 rounded-md border border-warn-line bg-warn-soft px-3 py-2 text-sm text-warn">
              <AlertTriangle aria-hidden className="h-4 w-4 shrink-0" />
              The dataset changed after this weight was built (for example, respondents were removed). Rebuild it.
            </p>
          )}
          <dl className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {[
              ["Efficiency", `${result.efficiency.toFixed(1)}%`],
              ["Effective base", `${Math.round(result.effective_base).toLocaleString()} of ${result.respondents.toLocaleString()}`],
              ["Design effect", result.design_effect.toFixed(2)],
              ["Weight range", `${result.min_weight.toFixed(2)} – ${result.max_weight.toFixed(2)}`],
            ].map(([label, value]) => (
              <div className="rounded-md bg-sunken px-3 py-2" key={label}>
                <dt className="text-xs text-muted">{label}</dt>
                <dd className="text-sm font-semibold tabular-nums">{value}</dd>
              </div>
            ))}
          </dl>
          {result.warnings.map((warning) => <p className="mt-2 text-xs text-warn" key={warning}>{warning}</p>)}
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line text-left text-xs text-muted">
                  <th className="py-1 pr-2 font-medium">Variable</th>
                  <th className="py-1 pr-2 font-medium">Category</th>
                  <th className="py-1 pr-2 text-right font-medium">Sample</th>
                  <th className="py-1 pr-2 text-right font-medium">Target</th>
                  <th className="py-1 text-right font-medium">Weighted</th>
                </tr>
              </thead>
              <tbody>
                {result.achieved.map((row) => (
                  <tr className="border-b border-line/60" key={`${row.variable}-${row.label}`}>
                    <td className="py-1 pr-2 text-ink-2">{row.variable}</td>
                    <td className="py-1 pr-2">{row.label}</td>
                    <td className="py-1 pr-2 text-right tabular-nums text-ink-2">{percent(row.sample_share)}</td>
                    <td className="py-1 pr-2 text-right tabular-nums">{percent(row.target_share)}</td>
                    <td className={cn("py-1 text-right tabular-nums", Math.abs(row.weighted_share - row.target_share) > 0.5 && "text-warn")}>
                      {percent(row.weighted_share)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <label className="mt-3 flex items-center gap-2 text-sm font-medium">
            <input
              checked={used}
              className="h-4 w-4 accent-[var(--color-accent)]"
              disabled={busy === "use"}
              onChange={(event) => void run("use", async () => {
                const next = await setWeightingUse(projectId, event.target.checked);
                setState((current) => current && { ...current, project_weight: next.project_weight });
              })}
              type="checkbox"
            />
            Use {result.weight_variable} in crosstabs, tab books, and reports
          </label>
          <p className="mt-1 text-xs text-muted">
            Weighted tables show weighted percentages and means, with significance tested on the effective base.
            Ask for "unweighted" in chat to get an unweighted table.
          </p>
        </section>
      )}
    </div>
  );
}
