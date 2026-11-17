/** The Quant OS quality dashboard: every tracked survey, live bot and fraud results, and exports. */

import { clsx } from "clsx";
import { Download, Pause, Play, RefreshCw, Search, ShieldCheck, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { type LiveRespondent, type LiveSurvey, getSurveyResults, listLiveSurveys, surveyExportUrl } from "../api";
import { Badge, Button, IconButton } from "../ui";
import { FlagsChart, KpiGrid, LiveDot, QualityChart, RespondentTable, StartsChart, ago, useLiveResults, useNow } from "./QualityParts";

type Filter = "all" | "flagged" | "clean" | "in_progress" | string;

const STATUS_FILTERS: { id: Filter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "flagged", label: "Flagged" },
  { id: "clean", label: "Looks human" },
  { id: "in_progress", label: "In survey" },
];

function matches(row: LiveRespondent, filter: Filter, query: string): boolean {
  if (query && !(row.respondent_id ?? "").toLowerCase().includes(query) && !row.session_id.toLowerCase().includes(query)) {
    return false;
  }
  if (filter === "all") return true;
  if (filter === "flagged") return row.flags.length > 0;
  if (filter === "clean") return row.status === "checked" && row.flags.length === 0;
  if (filter === "in_progress") return row.status === "in_progress";
  return row.flags.includes(filter);
}

/** Full-screen dashboard. ``initialSurvey`` selects a survey on open. */
export function QualityDashboard({ initialSurvey, onClose }: { initialSurvey?: string; onClose: () => void }) {
  const [surveys, setSurveys] = useState<LiveSurvey[]>([]);
  const [listError, setListError] = useState("");
  const [selected, setSelected] = useState(initialSurvey ?? "");
  const [scope, setScope] = useState<"quantos" | "all">("quantos");
  const [search, setSearch] = useState("");
  const [paused, setPaused] = useState(false);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const now = useNow();
  const { results, error, loading, refresh } = useLiveResults(
    selected ? () => getSurveyResults(selected) : null,
    selected,
    paused,
  );

  useEffect(() => {
    listLiveSurveys()
      .then((list) => {
        setSurveys(list);
        if (!selected) {
          const first = list.find((item) => item.project_id) ?? list[0];
          if (first) setSelected(first.survey_id);
        }
        if (initialSurvey && !list.some((item) => item.survey_id === initialSurvey)) setScope("all");
      })
      .catch((reason: Error) => setListError(reason.message));
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    setFilter("all");
    setQuery("");
  }, [selected]);

  const visibleSurveys = surveys.filter(
    (item) =>
      (scope === "all" || item.project_id) &&
      `${item.survey_id} ${item.project_name ?? ""}`.toLowerCase().includes(search.toLowerCase()),
  );
  const current = surveys.find((item) => item.survey_id === selected);
  const rows = useMemo(
    () => (results ? results.respondents.filter((row) => matches(row, filter, query.trim().toLowerCase())) : []),
    [results, filter, query],
  );

  return (
    <div aria-label="Quality dashboard" aria-modal="true" className="fixed inset-0 z-50 flex flex-col bg-canvas" role="dialog">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line bg-surface px-4">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-soft text-accent">
          <ShieldCheck aria-hidden className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold">Quality dashboard</h2>
          <p className="truncate text-xs text-muted">Live bot and fraud detection for Decipher surveys</p>
        </div>
        <IconButton label="Close dashboard" onClick={onClose}>
          <X className="h-4 w-4" />
        </IconButton>
      </header>

      <div className="flex min-h-0 flex-1">
        <nav aria-label="Surveys" className="hidden w-72 shrink-0 flex-col border-r border-line bg-surface md:flex">
          <div className="space-y-2 border-b border-line p-3">
            <label className="relative block">
              <span className="sr-only">Find a survey</span>
              <Search aria-hidden className="pointer-events-none absolute left-2 top-2 h-4 w-4 text-muted" />
              <input
                className="h-8 w-full rounded-md border border-line-strong bg-surface pl-8 pr-2 text-sm placeholder:text-muted"
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Find a survey"
                value={search}
              />
            </label>
            <div className="flex rounded-md border border-line p-0.5 text-xs" role="radiogroup">
              {(["quantos", "all"] as const).map((value) => (
                <button
                  aria-checked={scope === value}
                  className={clsx("flex-1 rounded px-2 py-1 font-medium", scope === value ? "bg-sunken text-ink" : "text-muted hover:text-ink")}
                  key={value}
                  onClick={() => setScope(value)}
                  role="radio"
                  type="button"
                >
                  {value === "quantos" ? "Quant OS projects" : "All surveys"}
                </button>
              ))}
            </div>
          </div>
          <ul className="min-h-0 flex-1 space-y-0.5 overflow-y-auto p-2">
            {listError && <li className="px-2 py-1 text-xs text-danger">{listError}</li>}
            {visibleSurveys.map((item) => (
              <li key={item.survey_id}>
                <button
                  aria-current={item.survey_id === selected ? "page" : undefined}
                  className={clsx(
                    "w-full rounded-md px-2 py-1.5 text-left transition-colors",
                    item.survey_id === selected ? "bg-accent-soft" : "hover:bg-sunken",
                  )}
                  onClick={() => setSelected(item.survey_id)}
                  type="button"
                >
                  <span className={clsx("block truncate text-sm", item.survey_id === selected ? "font-medium text-accent" : "text-ink")}>
                    {item.project_name ?? item.survey_id}
                  </span>
                  <span className="block truncate text-[11px] text-muted">
                    {item.respondents.toLocaleString()} respondents
                    {item.last_session ? ` · ${ago(item.last_session, now)}` : " · no responses yet"}
                  </span>
                </button>
              </li>
            ))}
            {!listError && visibleSurveys.length === 0 && (
              <li className="px-2 py-2 text-xs text-muted">
                {scope === "quantos" ? "No Quant OS project has tracking on yet. Turn it on in a project's Live quality tab." : "No surveys found."}
              </li>
            )}
          </ul>
        </nav>

        <main className="min-w-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-6xl space-y-4 p-4">
            <div className="md:hidden">
              <label className="text-xs font-medium text-ink-2" htmlFor="survey-picker">Survey</label>
              <select
                className="mt-1 h-9 w-full rounded-md border border-line-strong bg-surface px-2 text-sm"
                id="survey-picker"
                onChange={(event) => setSelected(event.target.value)}
                value={selected}
              >
                {surveys.map((item) => (
                  <option key={item.survey_id} value={item.survey_id}>{item.project_name ?? item.survey_id}</option>
                ))}
              </select>
            </div>

            {!selected && <p className="text-sm text-muted">Choose a survey.</p>}

            {selected && (
              <>
                <div className="flex flex-wrap items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <h3 className="truncate text-lg font-semibold">{current?.project_name ?? selected}</h3>
                    <p className="flex flex-wrap items-center gap-2 text-xs text-muted">
                      <span>Tracking id <code>{selected}</code></span>
                      {current?.project_id ? <Badge tone="accent">Quant OS project</Badge> : <Badge>External survey</Badge>}
                      <LiveDot now={now} paused={paused} updated={results?.updated_at} />
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Button onClick={() => setPaused(!paused)} size="sm" variant="ghost">
                      {paused ? <Play aria-hidden className="h-3.5 w-3.5" /> : <Pause aria-hidden className="h-3.5 w-3.5" />}
                      {paused ? "Resume" : "Pause"}
                    </Button>
                    <Button disabled={loading} onClick={() => void refresh()} size="sm" variant="ghost">
                      <RefreshCw aria-hidden className={clsx("h-3.5 w-3.5", loading && "animate-spin")} />
                      Refresh
                    </Button>
                    <a
                      className="inline-flex h-7 items-center gap-1.5 rounded-md border border-line-strong bg-surface px-2.5 text-xs font-medium text-ink shadow-xs hover:bg-sunken"
                      download
                      href={surveyExportUrl(selected)}
                    >
                      <Download aria-hidden className="h-3.5 w-3.5" />
                      Export CSV
                    </a>
                  </div>
                </div>

                {error && <p className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger" role="alert">{error}</p>}
                {!results && !error && <p className="text-sm text-muted">Loading results… Large surveys can take up to a minute.</p>}

                {results && (
                  <>
                    <KpiGrid results={results} />
                    <div className="grid gap-3 lg:grid-cols-3">
                      <div className="lg:col-span-2">
                        <StartsChart results={results} />
                      </div>
                      <QualityChart results={results} />
                    </div>
                    <FlagsChart onPick={(flag) => setFilter(flag)} results={results} />

                    <section className="space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <h4 className="text-sm font-semibold">Respondents</h4>
                        <div className="flex flex-wrap gap-1" role="radiogroup">
                          {[...STATUS_FILTERS, ...results.flag_counts.filter((item) => item.count > 0).map((item) => ({ id: item.flag, label: item.flag }))].map((item) => (
                            <button
                              aria-checked={filter === item.id}
                              className={clsx(
                                "rounded-full border px-2.5 py-0.5 text-xs",
                                filter === item.id ? "border-accent bg-accent-soft font-medium text-accent" : "border-line-strong text-ink-2 hover:border-accent",
                              )}
                              key={item.id}
                              onClick={() => setFilter(item.id)}
                              role="radio"
                              type="button"
                            >
                              {item.label}
                            </button>
                          ))}
                        </div>
                        <span className="flex-1" />
                        <input
                          aria-label="Find a respondent"
                          className="h-7 w-48 rounded-md border border-line-strong bg-surface px-2 text-xs placeholder:text-muted"
                          onChange={(event) => setQuery(event.target.value)}
                          placeholder="Respondent or session id"
                          value={query}
                        />
                      </div>
                      {results.respondents.length === 0 ? (
                        <p className="rounded-lg border border-dashed border-line-strong bg-surface p-6 text-center text-sm text-muted">
                          No one has started this survey yet. Respondents appear here as soon as they open the link.
                        </p>
                      ) : rows.length === 0 ? (
                        <p className="text-sm text-muted">No respondents match this filter.</p>
                      ) : (
                        <RespondentTable limit={500} now={now} rows={rows} />
                      )}
                    </section>
                  </>
                )}
              </>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
