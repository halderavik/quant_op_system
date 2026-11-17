import { ArrowDown, ArrowUp, Plus, RotateCcw, Trash2 } from "lucide-react";
import { useState } from "react";
import { Badge, Button } from "../ui";
import type { Tone } from "../outputs";

type Source = {
  question_ids?: string[];
  variables?: string[];
  banner?: string;
  statistic?: string;
  filter?: string;
  analysis_request?: string;
  method?: string;
};
type Slide = {
  id: string;
  kind: string;
  title: string;
  purpose?: string;
  objective_ids?: string[];
  source?: Source;
  chart?: string;
  notes?: string;
  status?: string;
  status_reason?: string;
  base_n?: number | null;
  origin?: string;
  edited?: boolean;
};
type Section = { id: string; title: string; purpose?: string; slides: Slide[]; origin?: string; edited?: boolean };
type Plan = {
  title?: string;
  stage?: string;
  objectives?: { id: string; text: string }[];
  sections?: Section[];
  removed_slide_ids?: string[];
  coverage?: { question_id: string; text?: string; slide_ids?: string[]; reason?: string }[];
  data?: {
    raw_n?: number | null;
    removed_by_cleaning?: number | null;
    final_n?: number | null;
    cleaning_summary?: string;
    weight_variable?: string;
    synthetic?: boolean;
  };
  cleaning?: "auto" | "skip" | "run";
  notes?: string[];
};

const KINDS = [
  ["distribution", "Question: % of answers"],
  ["grid_summary", "Grid: % yes or top-2 box"],
  ["mean_summary", "Grid: mean scores"],
  ["nps", "Net Promoter Score"],
  ["rank_summary", "Ranking"],
  ["funnel", "Brand funnel"],
  ["profile", "Sample profile"],
  ["analysis", "Advanced analysis"],
  ["coding", "Open-end coding"],
  ["text", "Text slide"],
] as const;

const STAGE_LABEL: Record<string, string> = {
  draft: "Draft from questionnaire",
  questionnaire_final: "Questionnaire final",
  data_ready: "Fitted to cleaned data",
  reported: "Report generated",
};

const STATUS: Record<string, [string, Tone]> = {
  planned: ["Planned", "neutral"],
  needs_data: ["Needs data", "warn"],
  low_base: ["Low base", "warn"],
  dropped: ["Removed", "neutral"],
  done: ["Done", "success"],
  failed: ["Failed", "danger"],
};

const field = "w-full rounded border border-line-strong bg-surface px-2 py-1 text-sm";

/** Edit the report plan: storyline sections, every slide's computation, and what is left out. */
export function ReportPlanEditor({
  content,
  onChange,
  onAsk,
  dirty,
}: {
  content: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
  onAsk?: (text: string) => void;
  dirty: boolean;
}) {
  const plan = content as Plan;
  const sections = plan.sections ?? [];
  const removed = new Set(plan.removed_slide_ids ?? []);
  const [open, setOpen] = useState<string>("");
  const slides = sections.flatMap((section) => section.slides);
  const live = slides.filter((slide) => slide.status !== "dropped");
  const flagged = live.filter((slide) => slide.status === "needs_data" || slide.status === "low_base").length;
  const uncovered = (plan.coverage ?? []).filter((row) => !(row.slide_ids ?? []).length);
  const skipCleaning = plan.cleaning === "skip" || ((plan.cleaning ?? "auto") === "auto" && Boolean(plan.data?.synthetic));

  function commit(next: Section[], removedIds = removed) {
    onChange({ ...content, sections: next, removed_slide_ids: [...removedIds] });
  }
  function editSection(index: number, patch: Partial<Section>) {
    commit(sections.map((s, i) => (i === index ? { ...s, ...patch, edited: true } : s)));
  }
  function editSlide(si: number, li: number, patch: Partial<Slide>) {
    commit(
      sections.map((s, i) =>
        i === si ? { ...s, slides: s.slides.map((sl, j) => (j === li ? { ...sl, ...patch, edited: true } : sl)) } : s,
      ),
    );
  }
  function editSource(si: number, li: number, patch: Partial<Source>) {
    const slide = sections[si].slides[li];
    editSlide(si, li, { source: { ...(slide.source ?? {}), ...patch } });
  }
  function move(si: number, li: number, by: number) {
    const list = [...sections[si].slides];
    const target = li + by;
    if (target < 0 || target >= list.length) return;
    [list[li], list[target]] = [list[target], list[li]];
    commit(sections.map((s, i) => (i === si ? { ...s, slides: list } : s)));
  }
  function toggleRemove(si: number, li: number) {
    const slide = sections[si].slides[li];
    const ids = new Set(removed);
    const dropping = slide.status !== "dropped";
    if (dropping) ids.add(slide.id);
    else ids.delete(slide.id);
    const next = sections.map((s, i) =>
      i === si
        ? {
            ...s,
            slides: s.slides.map((sl, j) =>
              j === li ? { ...sl, status: dropping ? "dropped" : "planned", status_reason: "", edited: true } : sl,
            ),
          }
        : s,
    );
    commit(next, ids);
  }
  function addSlide(si: number) {
    const id = `user-${Date.now().toString(36)}`;
    const slide: Slide = {
      id,
      kind: "distribution",
      title: "New slide",
      purpose: "",
      source: { question_ids: [], variables: [] },
      chart: "bar",
      status: "planned",
      origin: "user",
      edited: true,
    };
    commit(sections.map((s, i) => (i === si ? { ...s, slides: [...s.slides, slide] } : s)));
    setOpen(id);
  }
  function addSection() {
    const section: Section = { id: `user-sec-${Date.now().toString(36)}`, title: "New section", purpose: "", slides: [], origin: "user", edited: true };
    const at = Math.max(sections.findIndex((s) => s.id === "sec-close"), 0) || sections.length;
    commit([...sections.slice(0, at), section, ...sections.slice(at)]);
  }

  return (
    <div className="space-y-4 text-sm">
      <section className="rounded-lg border border-line bg-surface p-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="accent">
            {plan.stage === "data_ready" && skipCleaning ? "Fitted to data" : (STAGE_LABEL[plan.stage ?? "draft"] ?? plan.stage)}
          </Badge>
          <span className="text-ink-2">
            {sections.length} sections · {live.length} slides
            {flagged ? ` · ${flagged} flagged` : ""}
          </span>
        </div>
        {plan.data?.final_n != null && (
          <p className="mt-2 text-ink-2">
            Data{plan.data.synthetic ? " (synthetic)" : ""}: {plan.data.raw_n} completes,{" "}
            {skipCleaning ? "cleaning skipped" : `${plan.data.removed_by_cleaning ?? 0} removed in cleaning`}, {plan.data.final_n} in the
            final sample
            {plan.data.weight_variable ? `, weighted by ${plan.data.weight_variable}` : ", unweighted"}.
          </p>
        )}
        <label className="mt-2 flex items-start gap-2 text-ink-2">
          <input
            checked={skipCleaning}
            className="mt-0.5"
            onChange={(event) => onChange({ ...content, cleaning: event.target.checked ? "skip" : "run" })}
            type="checkbox"
          />
          <span>
            Skip data cleaning
            <span className="block text-xs text-muted">
              {plan.data?.synthetic
                ? "Synthetic data skips cleaning by default. Untick to check it for fraud anyway."
                : "Use when the data was cleaned before upload. Save, then update with data."}
            </span>
          </span>
        </label>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button disabled={!onAsk || dirty} onClick={() => onAsk?.("Update the report plan with the data")} size="sm">
            Update with data
          </Button>
          <Button disabled={!onAsk || dirty} onClick={() => onAsk?.("Generate the report")} size="sm" variant="primary">
            Generate report
          </Button>
          {dirty && <span className="self-center text-xs text-warn">Save your edits first.</span>}
        </div>
      </section>

      {(plan.objectives ?? []).length > 0 && (
        <section>
          <h3 className="font-semibold">Objectives the deck must answer</h3>
          <ol className="mt-1 list-decimal space-y-1 pl-5 text-ink-2">
            {(plan.objectives ?? []).map((o) => (
              <li key={o.id}>
                <span className="font-medium text-ink">{o.id}</span> {o.text}
              </li>
            ))}
          </ol>
        </section>
      )}

      {sections.map((section, si) => (
        <section key={section.id} className="rounded-lg border border-line bg-surface">
          <div className="space-y-1 border-b border-line p-3">
            <input aria-label={`Section ${si + 1} title`} className={`${field} font-semibold`} value={section.title} onChange={(e) => editSection(si, { title: e.target.value })} />
            <input aria-label={`Section ${si + 1} purpose`} className={`${field} text-ink-2`} value={section.purpose ?? ""} placeholder="What this section answers" onChange={(e) => editSection(si, { purpose: e.target.value })} />
          </div>
          <ol className="divide-y divide-line">
            {section.slides.map((slide, li) => {
              const [label, tone] = STATUS[slide.status ?? "planned"] ?? ["Planned", "neutral"];
              const expanded = open === slide.id;
              const src = slide.source ?? {};
              return (
                <li key={slide.id} className={slide.status === "dropped" ? "p-3 opacity-60" : "p-3"}>
                  <div className="flex items-start gap-2">
                    <button type="button" className="min-w-0 flex-1 text-left" onClick={() => setOpen(expanded ? "" : slide.id)} aria-expanded={expanded}>
                      <span className="font-medium">{slide.title}</span>
                      <span className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-muted">
                        <Badge tone={tone}>{label}</Badge>
                        <span>{KINDS.find(([k]) => k === slide.kind)?.[1] ?? slide.kind}</span>
                        {(src.question_ids ?? []).length > 0 && <span>· {(src.question_ids ?? []).join(", ")}</span>}
                        {src.banner && <span>· by {src.banner}</span>}
                        {slide.base_n != null && <span>· n={slide.base_n}</span>}
                        {slide.origin === "user" && <span>· added by you</span>}
                      </span>
                      {slide.status_reason && <span className="mt-0.5 block text-xs text-warn">{slide.status_reason}</span>}
                    </button>
                    <div className="flex shrink-0 gap-1">
                      <Button aria-label="Move up" size="sm" onClick={() => move(si, li, -1)}><ArrowUp className="h-3.5 w-3.5" /></Button>
                      <Button aria-label="Move down" size="sm" onClick={() => move(si, li, 1)}><ArrowDown className="h-3.5 w-3.5" /></Button>
                      <Button aria-label={slide.status === "dropped" ? "Restore slide" : "Remove slide"} size="sm" onClick={() => toggleRemove(si, li)}>
                        {slide.status === "dropped" ? <RotateCcw className="h-3.5 w-3.5" /> : <Trash2 className="h-3.5 w-3.5" />}
                      </Button>
                    </div>
                  </div>
                  {expanded && (
                    <div className="mt-3 grid gap-2 sm:grid-cols-2">
                      <label className="sm:col-span-2">Title
                        <input className={field} value={slide.title} onChange={(e) => editSlide(si, li, { title: e.target.value })} />
                      </label>
                      <label className="sm:col-span-2">Question it answers
                        <input className={field} value={slide.purpose ?? ""} onChange={(e) => editSlide(si, li, { purpose: e.target.value })} />
                      </label>
                      <label>How it is computed
                        <select className={field} value={slide.kind} onChange={(e) => editSlide(si, li, { kind: e.target.value })}>
                          {KINDS.map(([k, text]) => <option key={k} value={k}>{text}</option>)}
                        </select>
                      </label>
                      <label>Chart
                        <select className={field} value={slide.chart ?? "bar"} onChange={(e) => editSlide(si, li, { chart: e.target.value })}>
                          {["bar", "column", "stacked", "line", "table", "none"].map((c) => <option key={c} value={c}>{c}</option>)}
                        </select>
                      </label>
                      <label>Questions
                        <input className={field} value={(src.question_ids ?? []).join(", ")} onChange={(e) => editSource(si, li, { question_ids: split(e.target.value) })} />
                      </label>
                      <label>Variables
                        <input className={field} value={(src.variables ?? []).join(", ")} onChange={(e) => editSource(si, li, { variables: split(e.target.value) })} />
                      </label>
                      <label>Split by (banner)
                        <input className={field} value={src.banner ?? ""} placeholder="e.g. S7" onChange={(e) => editSource(si, li, { banner: e.target.value.trim() })} />
                      </label>
                      <label>Filter
                        <input className={field} value={src.filter ?? ""} placeholder="e.g. Q5r1 == 1" onChange={(e) => editSource(si, li, { filter: e.target.value })} />
                      </label>
                      {(slide.kind === "grid_summary" || slide.kind === "mean_summary") && (
                        <label>Statistic
                          <select className={field} value={src.statistic ?? "top2"} onChange={(e) => editSource(si, li, { statistic: e.target.value })}>
                            <option value="top2">Top-2 box</option>
                            <option value="pct_yes">% yes</option>
                            <option value="mean">Mean</option>
                          </select>
                        </label>
                      )}
                      {slide.kind === "analysis" && (
                        <label className="sm:col-span-2">Analysis request (sent to the analysis agent)
                          <textarea className={`${field} h-20`} value={src.analysis_request ?? ""} onChange={(e) => editSource(si, li, { analysis_request: e.target.value })} />
                        </label>
                      )}
                      <label className="sm:col-span-2">Notes
                        <input className={field} value={slide.notes ?? ""} onChange={(e) => editSlide(si, li, { notes: e.target.value })} />
                      </label>
                    </div>
                  )}
                </li>
              );
            })}
          </ol>
          <div className="p-2">
            <Button size="sm" onClick={() => addSlide(si)}><Plus className="h-3.5 w-3.5" /> Add slide</Button>
          </div>
        </section>
      ))}
      <Button size="sm" onClick={addSection}><Plus className="h-3.5 w-3.5" /> Add section</Button>

      {uncovered.length > 0 && (
        <section>
          <h3 className="font-semibold">Questions not reported ({uncovered.length})</h3>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-ink-2">
            {uncovered.map((row) => (
              <li key={row.question_id}><span className="font-medium text-ink">{row.question_id}</span>: {row.reason}</li>
            ))}
          </ul>
        </section>
      )}
      {(plan.notes ?? []).length > 0 && <p className="text-xs text-muted">{(plan.notes ?? []).join(" ")}</p>}
    </div>
  );
}

function split(text: string): string[] {
  return text.split(",").map((part) => part.trim()).filter(Boolean);
}

/** The generated deck: download and an outline of every slide. */
export function ReportViewer({ content }: { content: Record<string, unknown> }) {
  const slides = (content.slides ?? []) as { type?: string; title?: string; subtitle?: string; bullets?: string[] }[];
  const skipped = (content.skipped ?? []) as string[][];
  return (
    <div className="space-y-3 text-sm">
      <p className="text-ink-2">{slides.length} slides. Charts are native PowerPoint charts, so you can edit them in PowerPoint. Use the PowerPoint download above.</p>
      <ol className="space-y-2">
        {slides.map((slide, index) => (
          <li key={index} className={slide.type === "section" ? "rounded-md bg-accent-soft p-2 font-semibold" : "rounded-md border border-line bg-surface p-2"}>
            <span className="mr-2 text-xs text-muted">{index + 1}</span>
            {slide.title}
            {slide.type !== "section" && slide.subtitle && <span className="block text-xs text-muted">{slide.subtitle}</span>}
            {(slide.bullets ?? []).length > 0 && (
              <ul className="mt-1 list-disc pl-5 text-ink-2">
                {(slide.bullets ?? []).map((b, i) => <li key={i}>{b}</li>)}
              </ul>
            )}
          </li>
        ))}
      </ol>
      {skipped.length > 0 && (
        <section>
          <h3 className="font-semibold">Planned slides not included</h3>
          <ul className="mt-1 list-disc pl-5 text-ink-2">
            {skipped.map(([title, reason], i) => <li key={i}>{title}: {reason}</li>)}
          </ul>
        </section>
      )}
    </div>
  );
}
