import { ArrowDown, ArrowUp } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  getTracking,
  getTrendVariables,
  getWaveChanges,
  type NamedVariable,
  runTrend,
  startNextWave,
  type TrackingState,
  type TrendResult,
  type WaveChanges,
} from "../studyApi";
import { Badge, Button, cn } from "../ui";

/** Tracking study: waves in the series, next wave, what changed, and trend tables. */
export function TrackingPanel({
  projectId,
  projectName,
  onOpenProject,
}: {
  projectId: string;
  projectName: string;
  onOpenProject: (projectId: string) => Promise<void> | void;
}) {
  const [state, setState] = useState<TrackingState | null>(null);
  const [changes, setChanges] = useState<WaveChanges | null>(null);
  const [variables, setVariables] = useState<NamedVariable[]>([]);
  const [picked, setPicked] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [trend, setTrend] = useState<TrendResult | null>(null);
  const [label, setLabel] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    setState(null);
    setChanges(null);
    setTrend(null);
    setPicked([]);
    setMessage("");
    setError("");
    (async () => {
      try {
        const next = await getTracking(projectId);
        if (!live) return;
        setState(next);
        if (next.tracking.previous_project_id) {
          getWaveChanges(projectId).then((c) => live && setChanges(c)).catch(() => undefined);
        }
        if (next.waves.filter((wave) => wave.has_data).length >= 2) {
          getTrendVariables(projectId).then((v) => live && setVariables(v)).catch(() => undefined);
        }
      } catch (reason) {
        if (live) setError(reason instanceof Error ? reason.message : "Tracking could not be loaded.");
      }
    })();
    return () => {
      live = false;
    };
  }, [projectId]);

  const nextNumber = (state?.waves.reduce((top, wave) => Math.max(top, wave.wave), 0) || 1) + 1;
  // Reason: "Study – Wave 2" continues as "Study – Wave 3", not "Study – Wave 2 – Wave 3".
  const baseName = projectName.replace(/\s*[–-]\s*wave\s*\d+\s*$/i, "");
  const shown = useMemo(() => {
    const words = query.trim().toLowerCase();
    return variables.filter((v) => !words || `${v.name} ${v.label}`.toLowerCase().includes(words)).slice(0, 200);
  }, [variables, query]);

  async function next() {
    setBusy("wave");
    setError("");
    try {
      const created = await startNextWave(projectId, name || `${baseName} – Wave ${nextNumber}`, label || `Wave ${nextNumber}`);
      setMessage(created.summary);
      await onOpenProject(created.project_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The next wave could not be started.");
    } finally {
      setBusy("");
    }
  }

  async function runTable() {
    setBusy("trend");
    setError("");
    try {
      setTrend(await runTrend(projectId, picked));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The trend could not be built.");
    } finally {
      setBusy("");
    }
  }

  if (!state) return error ? <p className="text-sm text-danger" role="alert">{error}</p> : <p className="text-sm text-muted">Loading…</p>;
  const tracking = state.waves.length > 0;

  return (
    <section aria-label="Tracking" className="space-y-4 text-sm">
      <div className="rounded-lg border border-line bg-surface p-3">
        <h3 className="font-semibold text-ink">{tracking ? "Waves in this study" : "Make this a tracking study"}</h3>
        {tracking ? (
          <ol className="mt-2 flex flex-wrap gap-1.5">
            {state.waves.map((wave) => (
              <li key={wave.project_id}>
                <button
                  className={cn(
                    "rounded-md border px-2 py-1 text-xs",
                    wave.current ? "border-accent bg-accent-soft text-accent" : "border-line text-ink-2 hover:bg-sunken",
                  )}
                  disabled={wave.current}
                  onClick={() => void onOpenProject(wave.project_id)}
                  title={wave.name}
                  type="button"
                >
                  {wave.label}
                  {!wave.has_data && <span className="ml-1 text-muted">(no data)</span>}
                </button>
              </li>
            ))}
          </ol>
        ) : (
          <p className="mt-1 text-ink-2">
            Starting the next wave copies this project's questionnaire (with its programming logic), tab spec, weighting
            and report plan into a new project. Data and survey XML are not copied.
          </p>
        )}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input
            aria-label="Next wave label"
            className="h-7 w-32 rounded-md border border-line-strong bg-surface px-2 text-xs"
            onChange={(event) => setLabel(event.target.value)}
            placeholder={`Wave ${nextNumber}`}
            value={label}
          />
          <input
            aria-label="Next wave project name"
            className="h-7 min-w-0 flex-1 rounded-md border border-line-strong bg-surface px-2 text-xs sm:max-w-72"
            onChange={(event) => setName(event.target.value)}
            placeholder={`${baseName} – Wave ${nextNumber}`}
            value={name}
          />
          <Button disabled={!!busy} onClick={() => void next()} size="sm" variant="primary">
            {busy === "wave" ? "Starting…" : `Start wave ${nextNumber}`}
          </Button>
        </div>
      </div>
      {message && <p className="text-accent" role="status">{message}</p>}
      {error && <p className="text-danger" role="alert">{error}</p>}

      {changes && (
        <div className="rounded-lg border border-line bg-surface p-3">
          <h3 className="font-semibold text-ink">Changes since the previous wave</h3>
          <p className="mt-1 text-xs text-ink-2">
            {changes.unchanged} unchanged · {changes.changed} changed · {changes.added} added · {changes.removed} removed
            {changes.breaks_trend ? ` · ${changes.breaks_trend} break the trend` : ""}
          </p>
          {changes.changes.length > 0 && (
            <ul className="mt-2 divide-y divide-line">
              {changes.changes.map((change) => (
                <li className="flex items-start gap-2 py-1.5" key={`${change.question_id}-${change.status}`}>
                  <span className="w-20 shrink-0 font-mono text-xs font-semibold">{change.question_id}</span>
                  <Badge tone={change.breaks_trend ? "warn" : "neutral"}>
                    {change.status === "changed" ? (change.breaks_trend ? "Breaks trend" : "Changed") : change.status === "added" ? "New" : "Dropped"}
                  </Badge>
                  <span className="text-xs text-ink-2">{change.notes.join(" ")}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {tracking && (
        <div className="rounded-lg border border-line bg-surface p-3">
          <h3 className="font-semibold text-ink">Trend tables</h3>
          {variables.length === 0 ? (
            <p className="mt-1 text-ink-2">Trend tables need at least two waves with data uploaded.</p>
          ) : (
            <>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <input
                  aria-label="Search variables"
                  className="h-7 min-w-0 flex-1 rounded-md border border-line-strong bg-surface px-2 text-xs sm:max-w-56"
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Search variables"
                  value={query}
                />
                <Button disabled={!!busy || !picked.length} onClick={() => void runTable()} size="sm" variant="primary">
                  {busy === "trend" ? "Building…" : `Trend ${picked.length || ""}`}
                </Button>
              </div>
              <ul className="mt-2 max-h-40 overflow-y-auto rounded-md border border-line">
                {shown.map((variable) => (
                  <li key={variable.name}>
                    <label className="flex items-center gap-2 px-2 py-1 text-xs hover:bg-sunken">
                      <input
                        checked={picked.includes(variable.name)}
                        onChange={(event) =>
                          setPicked((current) =>
                            event.target.checked ? [...current, variable.name].slice(0, 60) : current.filter((n) => n !== variable.name),
                          )
                        }
                        type="checkbox"
                      />
                      <span className="font-mono">{variable.name}</span>
                      <span className="truncate text-muted">{variable.label}</span>
                    </label>
                  </li>
                ))}
              </ul>
            </>
          )}
          {trend && (
            <div className="mt-3 space-y-3">
              <p className="text-xs text-muted">{trend.note} Arrows mark a significant change from the previous wave.</p>
              {trend.tables.map((table) => (
                <div className="overflow-x-auto" key={table.variable}>
                  <p className="font-medium text-ink">
                    {table.label} <span className="font-mono text-xs text-muted">{table.variable}</span>
                  </p>
                  {table.missing_in.length > 0 && <p className="text-xs text-warn">Not in: {table.missing_in.join(", ")}</p>}
                  <table className="mt-1 w-full text-xs">
                    <thead>
                      <tr className="text-left text-muted">
                        <th className="py-1 font-medium" />
                        {trend.waves.map((wave) => (
                          <th className="py-1 text-right font-medium" key={wave.project_id}>{wave.label}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {table.rows.map((row) => (
                        <tr className="border-t border-line" key={row.code}>
                          <td className="py-1 pr-2">{row.label}</td>
                          {row.cells.map((cell) => (
                            <td className="py-1 text-right tabular-nums" key={cell.wave}>
                              {cell.value === null ? "–" : row.kind === "mean" ? cell.value.toFixed(2) : `${cell.value.toFixed(1)}%`}
                              {cell.direction === "up" && <ArrowUp aria-label="significantly up" className="ml-0.5 inline h-3 w-3 text-success" />}
                              {cell.direction === "down" && <ArrowDown aria-label="significantly down" className="ml-0.5 inline h-3 w-3 text-danger" />}
                            </td>
                          ))}
                        </tr>
                      ))}
                      {table.bases && (
                        <tr className="border-t border-line text-muted">
                          <td className="py-1 pr-2">Base</td>
                          {table.bases.map((base) => (
                            <td className="py-1 text-right tabular-nums" key={base.wave}>{base.base}</td>
                          ))}
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
