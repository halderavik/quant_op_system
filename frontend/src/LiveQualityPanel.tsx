/** Live quality tab: tracking setup for a project's Decipher survey and its live results. */

import { AlertTriangle, Check, Copy, ExternalLink, LayoutDashboard, Pause, Play, RefreshCw, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { type LiveQualityState, getLiveQuality, getLiveResults, programDecipher, setLiveQuality } from "./api";
import { KpiGrid, LiveDot, RespondentTable, useLiveResults, useNow } from "./quality/QualityParts";
import { QualityRulesCard } from "./quality/QualityRules";
import { Button } from "./ui";

/** The Live quality panel for one project. */
export function LiveQualityPanel({ projectId, onProgrammed, onError, onOpenDashboard }: {
  projectId: string;
  onProgrammed: () => Promise<void>;
  onError: (message: string) => void;
  onOpenDashboard: (surveyId: string) => void;
}) {
  const [state, setState] = useState<LiveQualityState | null>(null);
  const [paused, setPaused] = useState(false);
  const [busy, setBusy] = useState("");
  const [copied, setCopied] = useState(false);
  const now = useNow();
  const tracked = Boolean(state?.decipher.tracking_in_xml);
  const { results, error, refresh } = useLiveResults(
    () => getLiveResults(projectId),
    tracked ? `${projectId}:${state?.survey_id}` : "",
    paused,
  );

  useEffect(() => {
    setState(null);
    getLiveQuality(projectId).then(setState).catch((reason: Error) => onError(reason.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  async function save(enabled: boolean, useProjectName = false) {
    setBusy("toggle");
    try {
      setState(await setLiveQuality(projectId, enabled, useProjectName));
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "The setting was not saved.");
    } finally {
      setBusy("");
    }
  }

  async function program() {
    setBusy("program");
    try {
      await programDecipher(projectId);
      setState(await getLiveQuality(projectId));
      await onProgrammed();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "Programming failed.");
    } finally {
      setBusy("");
    }
  }

  if (!state) return <p className="p-4 text-sm text-muted">Loading live quality…</p>;
  const decipher = state.decipher;
  const link = decipher.survey_url || "";

  return (
    <div className="space-y-4 p-4">
      <section className="rounded-xl border border-line bg-surface p-4 shadow-xs">
        <div className="flex items-start gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent">
            <ShieldCheck aria-hidden className="h-5 w-5" />
          </span>
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold">Live bot and fraud detection</h3>
            <p className="mt-0.5 text-sm text-ink-2">
              Tracks behaviour, open-end quality, grid straight-lining, speed, and fraud signals (IP, device, duplicates)
              while people take the Decipher survey. Results appear here within seconds.
            </p>
            <label className="mt-3 flex items-center gap-2 text-sm font-medium">
              <input
                checked={state.enabled}
                className="h-4 w-4 accent-[var(--color-accent)]"
                disabled={busy === "toggle"}
                onChange={(event) => void save(event.target.checked)}
                type="checkbox"
              />
              Add tracking when this survey is programmed in Decipher
            </label>
            {state.enabled && (
              <p className="mt-1 text-xs text-muted">
                Survey id in the detection service: <code>{state.survey_id}</code>
                {!state.fielded && " (the project name)"}
              </p>
            )}
            {state.enabled && state.fielded && state.survey_id !== state.name_id && (
              <p className="mt-1 text-xs text-ink-2">
                The project was renamed after the survey went live, so the id stays <code>{state.survey_id}</code> to keep
                earlier responses together.{" "}
                <button className="font-medium text-accent hover:underline" onClick={() => void save(true, true)} type="button">
                  Use “{state.name_id}” from the next programming
                </button>
              </p>
            )}
          </div>
        </div>

        {state.enabled && !decipher.has_questionnaire && (
          <p className="mt-3 rounded-md bg-sunken px-3 py-2 text-sm text-ink-2">Create a questionnaire first, then program it in Decipher.</p>
        )}
        {state.enabled && decipher.has_questionnaire && !decipher.tracking_in_xml && (
          <div className="mt-3 flex flex-wrap items-center gap-2 rounded-md border border-warn-line bg-warn-soft px-3 py-2 text-sm text-warn">
            <AlertTriangle aria-hidden className="h-4 w-4 shrink-0" />
            <span className="min-w-0 flex-1">
              The Decipher survey doesn't carry this tracking id yet. Programming it uploads a new version to Decipher.
            </span>
            <Button disabled={busy === "program"} onClick={() => void program()} size="sm" variant="primary">
              {busy === "program" ? "Programming…" : "Program in Decipher"}
            </Button>
          </div>
        )}
        {decipher.tracking_in_xml && (
          <div className="mt-3 rounded-md border border-line bg-sunken/60 px-3 py-2">
            <p className="text-xs font-medium text-ink-2">
              {decipher.uploaded && link ? "Share this survey link" : "Tracking is in the survey XML"}
            </p>
            {decipher.uploaded && link ? (
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <code className="min-w-0 flex-1 break-all text-sm">{link}</code>
                <Button
                  onClick={() => {
                    void navigator.clipboard?.writeText(link).then(() => {
                      setCopied(true);
                      window.setTimeout(() => setCopied(false), 1500);
                    });
                  }}
                  size="sm"
                >
                  {copied ? <Check aria-hidden className="h-3.5 w-3.5" /> : <Copy aria-hidden className="h-3.5 w-3.5" />}
                  {copied ? "Copied" : "Copy link"}
                </Button>
                <a className="inline-flex h-7 items-center gap-1 rounded-md px-2 text-xs font-medium text-accent hover:bg-sunken" href={link} rel="noreferrer" target="_blank">
                  Open <ExternalLink aria-hidden className="h-3 w-3" />
                </a>
              </div>
            ) : (
              <p className="mt-1 text-xs text-muted">Download the XML from the Decipher output and import it, or connect the Decipher key to upload it.</p>
            )}
          </div>
        )}
      </section>

      {state.enabled && <QualityRulesCard onError={onError} programmed={tracked} projectId={projectId} />}

      {tracked && (
        <section aria-live="polite" className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <LiveDot now={now} paused={paused} updated={results?.updated_at} />
            <span className="flex-1" />
            <Button onClick={() => setPaused(!paused)} size="sm" variant="ghost">
              {paused ? <Play aria-hidden className="h-3.5 w-3.5" /> : <Pause aria-hidden className="h-3.5 w-3.5" />}
              {paused ? "Resume" : "Pause"}
            </Button>
            <Button onClick={() => void refresh()} size="sm" variant="ghost">
              <RefreshCw aria-hidden className="h-3.5 w-3.5" />
              Refresh
            </Button>
            <Button onClick={() => onOpenDashboard(state.survey_id)} size="sm">
              <LayoutDashboard aria-hidden className="h-3.5 w-3.5" />
              Open dashboard
            </Button>
          </div>
          {error && <p className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger" role="alert">{error}</p>}
          {results && <KpiGrid results={results} />}
          {results && results.respondents.length === 0 && (
            <p className="rounded-lg border border-dashed border-line-strong bg-surface p-6 text-center text-sm text-muted">
              No one has started the survey yet. Share the link; respondents appear here as soon as they open it.
            </p>
          )}
          {results && results.respondents.length > 0 && <RespondentTable limit={25} now={now} rows={results.respondents} />}
        </section>
      )}
    </div>
  );
}
