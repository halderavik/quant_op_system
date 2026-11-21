/** Card for adding Live quality flags to the survey data as LQ_ variables. */

import { Database, RefreshCw } from "lucide-react";
import { useState } from "react";
import { type LiveQualityState, mergeLiveQuality } from "../api";
import { Badge, Button } from "../ui";

/** Shows whether the active dataset carries the Live quality flags, and adds or refreshes them. */
export function QualityDataCard({ projectId, state, onChange, onError }: {
  projectId: string;
  state: LiveQualityState;
  onChange: (state: LiveQualityState) => void;
  onError: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const data = state.data;
  const last = data?.last?.status === "merged" ? data.last : null;

  async function merge() {
    setBusy(true);
    setNote("");
    try {
      const outcome = await mergeLiveQuality(projectId);
      onChange(outcome.state);
      setNote(outcome.report.message);
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "The flags were not added to the data.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="quality-data-title" className="rounded-xl border border-line bg-surface p-4 shadow-xs">
      <div className="flex flex-wrap items-start gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent">
          <Database aria-hidden className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="flex flex-wrap items-center gap-2 text-sm font-semibold" id="quality-data-title">
            Flags in your data
            {data?.merged ? <Badge tone="success">Added</Badge> : data?.tracked ? <Badge tone="warn">Not added yet</Badge> : <Badge>No data yet</Badge>}
          </h3>
          <p className="mt-0.5 text-sm text-ink-2">
            The Decipher export carries each respondent&apos;s <code className="text-xs">QOS_SESSION</code>. Quant OS matches
            it to the Live quality results and adds the scores and flags as <code className="text-xs">LQ_</code> variables,
            so you can tab, filter and clean on them.
          </p>
        </div>
        {data?.tracked && (
          <Button disabled={busy} onClick={() => void merge()} size="sm">
            <RefreshCw aria-hidden className={busy ? "h-3.5 w-3.5 animate-spin" : "h-3.5 w-3.5"} />
            {busy ? "Adding…" : data.merged ? "Refresh flags" : "Add flags to data"}
          </Button>
        )}
      </div>

      {!data?.tracked && (
        <p className="mt-3 text-sm text-muted">
          Upload the Decipher data file (.sav) when fieldwork closes. The flags are added on upload.
        </p>
      )}

      {last && (
        <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-4">
          <Fact label="Matched" value={`${last.matched ?? 0} of ${last.tracked ?? 0}`} />
          <Fact label="Flagged" value={String(last.flagged ?? 0)} />
          <Fact label="Bots" value={String(last.bots ?? 0)} />
          <Fact label="Updated" value={last.merged_at ? new Date(last.merged_at).toLocaleString() : "–"} />
        </dl>
      )}
      {last && (last.unmatched ?? 0) > 0 && (
        <p className="mt-2 text-xs text-muted">
          {last.unmatched} tracked records weren&apos;t found in Live quality, usually sessions older than the service keeps.
          Their LQ_MATCHED is 0.
        </p>
      )}
      {note && <p className="mt-2 text-sm text-ink-2" role="status">{note}</p>}

      <details className="mt-3 text-sm">
        <summary className="cursor-pointer text-ink-2">What gets added</summary>
        <ul className="mt-2 list-disc space-y-0.5 pl-5 text-ink-2">
          <li><span className="text-ink">LQ_MATCHED, LQ_STATUS, LQ_VERDICT</span>: found in Live quality, session status, human or bot under your rules.</li>
          <li><span className="text-ink">LQ_BOT_SCORE, LQ_BOT_RISK, LQ_BOT_SIGNALS</span>: behaviour score, its risk band, and the decisive signals that fired.</li>
          <li><span className="text-ink">LQ_SECONDS, LQ_PAGES, LQ_SEC_PER_PAGE, LQ_TEXT_QUALITY</span>: timing and open-end quality.</li>
          <li><span className="text-ink">LQ_FRAUD_SCORE, LQ_FRAUD_RISK</span>: fraud score and its band.</li>
          <li><span className="text-ink">LQ_F_BOT … LQ_F_DATACENTRE</span>: one 0/1 variable per flag, plus LQ_NFLAGS and LQ_FLAGS.</li>
        </ul>
        <p className="mt-2 text-xs text-muted">
          Flags follow the quality rules at the time you add them. A refresh after changing the rules saves a new dataset version;
          earlier tables keep the data they were run on.
        </p>
      </details>
    </section>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="text-ink">{value}</dd>
    </div>
  );
}
