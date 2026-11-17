/** Shared pieces of the live quality views: polling, tiles, charts, and the respondent table. */

import { clsx } from "clsx";
import { AlertTriangle, Check, ChevronDown, ChevronRight } from "lucide-react";
import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import type { LiveRespondent, LiveResults } from "../api";
import { Badge } from "../ui";

export const POLL_MS = 8000;

/** Poll a results loader every POLL_MS while the tab is visible and not paused. */
export function useLiveResults(load: (() => Promise<LiveResults>) | null, key: string, paused: boolean) {
  const [results, setResults] = useState<LiveResults | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const inFlight = useRef(false);
  const loader = useRef(load);
  loader.current = load;

  async function refresh() {
    if (!loader.current || inFlight.current) return;
    inFlight.current = true;
    setLoading(true);
    try {
      setResults(await loader.current());
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The live results could not be loaded.");
    } finally {
      inFlight.current = false;
      setLoading(false);
    }
  }

  useEffect(() => {
    setResults(null);
    setError("");
    if (!key) return;
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  useEffect(() => {
    if (!key || paused) return;
    const handle = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, POLL_MS);
    return () => window.clearInterval(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, paused]);

  return { results, error, loading, refresh };
}

/** A clock that ticks every second, for "updated 5s ago" labels. */
export function useNow(): number {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const handle = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(handle);
  }, []);
  return now;
}

export function ago(iso: string | null | undefined, now: number): string {
  if (!iso) return "";
  const seconds = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}

export function quality(value: number | null | undefined): string {
  return value === null || value === undefined ? "–" : `${Math.round(value)}`;
}

export function LiveDot({ paused, updated, now }: { paused: boolean; updated?: string; now: number }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium text-ink-2">
      <span className={clsx("h-2 w-2 rounded-full", paused ? "bg-line-strong" : "animate-pulse bg-success")} />
      {paused ? "Paused" : "Live"}
      {updated && <span className="font-normal text-muted">· updated {ago(updated, now)}</span>}
    </span>
  );
}

function Tile({ label, value, note, tone }: { label: string; value: number | string; note?: string; tone?: "danger" | "warn" }) {
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2.5">
      <p className="text-[11px] font-medium uppercase tracking-wide text-muted">{label}</p>
      <p className="mt-0.5 flex items-center gap-1.5 text-2xl font-semibold tabular-nums text-ink">
        {value}
        {tone && Number(value) > 0 && (
          <AlertTriangle aria-label="Needs review" className={clsx("h-4 w-4", tone === "danger" ? "text-danger" : "text-warn")} />
        )}
      </p>
      {note && <p className="text-xs text-muted">{note}</p>}
    </div>
  );
}

export function KpiGrid({ results }: { results: LiveResults }) {
  const totals = results.totals;
  const avg = results.text.avg_quality;
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      <Tile label="Started" note={`${totals.in_progress} in survey now`} value={totals.sessions} />
      <Tile label="Checked" note={`${totals.dropped} did not finish`} value={totals.checked} />
      <Tile label="Flagged" note={totals.sessions ? `${Math.round((100 * totals.flagged) / totals.sessions)}% of starts` : "At least one check"} tone="warn" value={totals.flagged} />
      <Tile label="Bot-like" note="Behaviour verdict" tone="danger" value={totals.bots} />
      <Tile label="Low-quality text" note={avg != null ? `Avg quality ${Math.round(avg)}/100` : "Open ends"} tone="warn" value={totals.low_quality_text} />
      <Tile label="Straight-liners" note="Same answer across a grid" tone="warn" value={totals.straight_liners} />
      <Tile label="Speeders" note="Under 3.5 s a page" tone="warn" value={totals.speeders} />
      <Tile label="Duplicates" note={`${results.fraud.high_risk} high fraud risk`} tone="danger" value={totals.duplicates} />
    </div>
  );
}

export function statusBadge(row: LiveRespondent) {
  if (row.status === "in_progress") return <Badge tone="accent">In survey</Badge>;
  if (row.status === "dropped") return <Badge>Not finished</Badge>;
  if (row.verdict === "bot") return <Badge tone="danger">Bot-like</Badge>;
  if (row.flags.length > 0) return <Badge tone="warn">Review</Badge>;
  return <Badge tone="success"><Check aria-hidden className="h-3 w-3" />Looks human</Badge>;
}

function RespondentDetail({ row }: { row: LiveRespondent }) {
  return (
    <div className="space-y-2 text-xs text-ink-2">
      <p>
        <span className="font-medium text-ink">Behaviour:</span>{" "}
        {row.verdict === "pending" ? "not scored yet (still in the survey or did not finish)" : `${row.verdict}, risk ${row.risk.toLowerCase()}`}
        {row.explanation ? ` · ${row.explanation}` : ""} · {row.events} events
      </p>
      {row.fraud_score != null && (
        <p>
          <span className="font-medium text-ink">Fraud:</span> score {row.fraud_score.toFixed(2)}
          {row.fraud_risk ? `, ${row.fraud_risk.toLowerCase()} risk` : ""}
          {row.duplicate ? ", duplicate of another response" : ""}
          {row.fraud_reasons && Object.keys(row.fraud_reasons).length > 0 ? ` · signals: ${Object.keys(row.fraud_reasons).join(", ").replace(/_/g, " ")}` : ""}
        </p>
      )}
      {row.grid_explanation && <p><span className="font-medium text-ink">Grid:</span> {row.grid_explanation}</p>}
      {row.timing_explanation && <p><span className="font-medium text-ink">Timing:</span> {row.timing_explanation}</p>}
      {row.seconds ? <p><span className="font-medium text-ink">Time:</span> {Math.round(row.seconds)} seconds over {row.pages} pages</p> : null}
      {row.text_details.length > 0 && (
        <ul className="space-y-1">
          {row.text_details.map((detail, index) => (
            <li className="rounded-md border border-line bg-surface px-2.5 py-1.5" key={index}>
              <p className="text-muted">{detail.question}</p>
              <p className="text-ink">“{detail.answer}”</p>
              <p>
                Quality {quality(detail.quality)}/100
                {detail.flagged && detail.reasons.length > 0 && (
                  <span className="text-warn"> · {detail.reasons.join(", ").replace(/_/g, " ")}</span>
                )}
              </p>
            </li>
          ))}
        </ul>
      )}
      <p className="font-mono text-[11px] text-muted">Session {row.session_id}</p>
    </div>
  );
}

export function RespondentTable({ rows, now, limit }: { rows: LiveRespondent[]; now: number; limit?: number }) {
  const [open, setOpen] = useState<string | null>(null);
  const shown = limit ? rows.slice(0, limit) : rows;
  return (
    <div className="overflow-x-auto rounded-lg border border-line bg-surface">
      <table className="w-full min-w-[680px] text-sm">
        <thead className="bg-sunken text-left text-[11px] uppercase tracking-wide text-muted">
          <tr>
            <th className="w-6 px-2 py-2" />
            <th className="px-2 py-2 font-medium">Started</th>
            <th className="px-2 py-2 font-medium">Respondent</th>
            <th className="px-2 py-2 font-medium">Status</th>
            <th className="px-2 py-2 text-right font-medium">Text quality</th>
            <th className="px-2 py-2 text-right font-medium">Time</th>
            <th className="px-2 py-2 font-medium">Flags</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {shown.map((row) => {
            const expanded = open === row.session_id;
            return (
              <Fragment key={row.session_id}>
                <tr
                  aria-expanded={expanded}
                  className="cursor-pointer hover:bg-sunken/60"
                  onClick={() => setOpen(expanded ? null : row.session_id)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      setOpen(expanded ? null : row.session_id);
                    }
                  }}
                  tabIndex={0}
                >
                  <td className="px-2 py-2 text-muted">
                    {expanded ? <ChevronDown aria-hidden className="h-4 w-4" /> : <ChevronRight aria-hidden className="h-4 w-4" />}
                  </td>
                  <td className="whitespace-nowrap px-2 py-2 text-ink-2" title={row.started ?? ""}>{ago(row.started, now)}</td>
                  <td className="px-2 py-2 font-mono text-xs">{row.respondent_id ?? "–"}</td>
                  <td className="px-2 py-2">{statusBadge(row)}</td>
                  <td className="px-2 py-2 text-right tabular-nums">
                    {quality(row.text_quality)}
                    {row.text_flagged > 0 && <span className="ml-1 text-xs text-warn">({row.text_flagged} flagged)</span>}
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums text-ink-2">{row.seconds ? `${Math.round(row.seconds)} s` : "–"}</td>
                  <td className="px-2 py-2">
                    <div className="flex flex-wrap gap-1">
                      {row.flags.map((flag) => (
                        <Badge key={flag} tone={flag === "Bot-like behaviour" || flag === "Duplicate" ? "danger" : "warn"}>{flag}</Badge>
                      ))}
                    </div>
                  </td>
                </tr>
                {expanded && (
                  <tr className="bg-canvas">
                    <td />
                    <td className="px-2 py-3" colSpan={6}>
                      <RespondentDetail row={row} />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
      {limit && rows.length > limit && (
        <p className="border-t border-line px-3 py-2 text-xs text-muted">Showing the newest {limit} of {rows.length}.</p>
      )}
    </div>
  );
}

/** Hover tooltip shared by the charts. */
function useTip() {
  const [tip, setTip] = useState<{ x: number; y: number; text: string } | null>(null);
  return { tip, setTip };
}

function Tip({ tip }: { tip: { x: number; y: number; text: string } | null }) {
  if (!tip) return null;
  return (
    <div
      className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-md border border-line bg-surface px-2 py-1 text-xs text-ink shadow-md"
      role="status"
      style={{ left: tip.x, top: tip.y - 6 }}
    >
      {tip.text}
    </div>
  );
}

function ChartCard({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-line bg-surface p-3">
      <h4 className="text-sm font-semibold">{title}</h4>
      {note && <p className="text-xs text-muted">{note}</p>}
      <div className="relative mt-2">{children}</div>
    </section>
  );
}

/** Starts over time as stacked bars: clean starts and flagged starts. */
export function StartsChart({ results }: { results: LiveResults }) {
  const { tip, setTip } = useTip();
  const buckets = results.trend.buckets;
  const width = 560;
  const height = 150;
  const pad = { left: 28, right: 6, top: 8, bottom: 20 };
  const max = Math.max(1, ...buckets.map((bucket) => bucket.started));
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const slot = buckets.length ? plotW / buckets.length : plotW;
  const barW = Math.max(2, Math.min(28, slot - 2));
  const label = (iso: string) => {
    const date = new Date(iso);
    return results.trend.unit === "hour"
      ? date.toLocaleTimeString([], { hour: "numeric" })
      : date.toLocaleDateString([], { month: "short", day: "numeric" });
  };
  const ticks = [0, Math.ceil(max / 2), max];
  const every = Math.max(1, Math.ceil(buckets.length / 6));
  return (
    <ChartCard note={`Respondents who started, per ${results.trend.unit}`} title="Starts over time">
      <div className="mb-1 flex gap-3 text-xs text-ink-2">
        <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm bg-accent" />Clean</span>
        <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm bg-warn" />Flagged</span>
      </div>
      {buckets.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted">No starts yet.</p>
      ) : (
        <svg aria-label="Starts over time" className="w-full" onMouseLeave={() => setTip(null)} role="img" viewBox={`0 0 ${width} ${height}`}>
          {ticks.map((tick) => {
            const y = pad.top + plotH - (tick / max) * plotH;
            return (
              <g key={tick}>
                <line stroke="var(--color-line)" x1={pad.left} x2={width - pad.right} y1={y} y2={y} />
                <text className="fill-muted text-[10px]" textAnchor="end" x={pad.left - 4} y={y + 3}>{tick}</text>
              </g>
            );
          })}
          {buckets.map((bucket, index) => {
            const x = pad.left + index * slot + (slot - barW) / 2;
            const clean = bucket.started - bucket.flagged;
            const cleanH = (clean / max) * plotH;
            const flaggedH = (bucket.flagged / max) * plotH;
            const base = pad.top + plotH;
            const text = `${label(bucket.start)}: ${bucket.started} started, ${bucket.flagged} flagged`;
            return (
              <g key={bucket.start}>
                <rect
                  fill="transparent"
                  height={plotH}
                  onMouseEnter={(event) => {
                    const box = (event.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
                    setTip({ x: ((x + barW / 2) / width) * box.width, y: ((base - cleanH - flaggedH) / height) * box.height, text });
                  }}
                  width={slot}
                  x={pad.left + index * slot}
                  y={pad.top}
                />
                {clean > 0 && <rect className="pointer-events-none" fill="var(--color-accent)" height={Math.max(0, cleanH - (bucket.flagged ? 1 : 0))} rx={2} width={barW} x={x} y={base - cleanH} />}
                {bucket.flagged > 0 && <rect className="pointer-events-none" fill="var(--color-warn)" height={Math.max(1, flaggedH - 1)} rx={2} width={barW} x={x} y={base - cleanH - flaggedH} />}
                {index % every === 0 && (
                  <text className="fill-muted text-[10px]" textAnchor="middle" x={x + barW / 2} y={height - 6}>{label(bucket.start)}</text>
                )}
              </g>
            );
          })}
          <line stroke="var(--color-line-strong)" x1={pad.left} x2={width - pad.right} y1={pad.top + plotH} y2={pad.top + plotH} />
        </svg>
      )}
      <Tip tip={tip} />
    </ChartCard>
  );
}

/** Respondents per flag, one horizontal bar each, labelled with the count. */
export function FlagsChart({ results, onPick }: { results: LiveResults; onPick?: (flag: string) => void }) {
  const counts = results.flag_counts;
  const max = Math.max(1, ...counts.map((item) => item.count));
  const total = Math.max(1, results.totals.sessions);
  return (
    <ChartCard note="Respondents with each flag (one person can have several)" title="Why respondents were flagged">
      <ul className="space-y-1.5">
        {counts.map((item) => (
          <li key={item.flag}>
            <button
              className="grid w-full grid-cols-[9.5rem_1fr_3.5rem] items-center gap-2 rounded px-1 py-0.5 text-left text-xs hover:bg-sunken disabled:cursor-default disabled:hover:bg-transparent"
              disabled={!onPick || item.count === 0}
              onClick={() => onPick?.(item.flag)}
              title={`${item.flag}: ${item.count} of ${results.totals.sessions} respondents`}
              type="button"
            >
              <span className="truncate text-ink-2">{item.flag}</span>
              <span className="h-3 rounded-sm bg-sunken">
                <span className="block h-3 rounded-sm bg-warn" style={{ width: `${(item.count / max) * 100}%` }} />
              </span>
              <span className="text-right tabular-nums text-ink">
                {item.count} <span className="text-muted">({Math.round((100 * item.count) / total)}%)</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </ChartCard>
  );
}

const QUALITY_BUCKETS = ["0-10", "10-20", "20-30", "30-40", "40-50", "50-60", "60-70", "70-80", "80-90", "90-100"];

/** Open-end quality scores as a histogram, low scores to the left. */
export function QualityChart({ results }: { results: LiveResults }) {
  const { tip, setTip } = useTip();
  const values = QUALITY_BUCKETS.map((bucket) => Number(results.quality_distribution[bucket] ?? 0));
  const total = values.reduce((sum, value) => sum + value, 0);
  const max = Math.max(1, ...values);
  return (
    <ChartCard note={`${results.text.responses} answers scored 0 to 100 · below 40 is usually flagged`} title="Open-end quality">
      {total === 0 ? (
        <p className="py-8 text-center text-sm text-muted">No open-end answers yet.</p>
      ) : (
        <div className="flex h-[120px] items-end gap-[2px]" onMouseLeave={() => setTip(null)}>
          {values.map((value, index) => (
            <div className="flex h-full flex-1 flex-col justify-end" key={QUALITY_BUCKETS[index]}>
              <div
                className={clsx("rounded-t-[4px]", index < 4 ? "bg-warn" : "bg-accent")}
                onMouseEnter={(event) => {
                  const box = (event.currentTarget.parentElement?.parentElement as HTMLElement).getBoundingClientRect();
                  const own = event.currentTarget.getBoundingClientRect();
                  setTip({ x: own.left - box.left + own.width / 2, y: own.top - box.top, text: `Score ${QUALITY_BUCKETS[index]}: ${value} answers` });
                }}
                style={{ height: `${Math.max(value ? 3 : 0, (value / max) * 100)}%` }}
              />
            </div>
          ))}
        </div>
      )}
      <div className="mt-1 flex justify-between text-[10px] text-muted"><span>0</span><span>50</span><span>100</span></div>
      <Tip tip={tip} />
    </ChartCard>
  );
}
