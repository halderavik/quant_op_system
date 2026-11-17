/** Quality rules editor: what counts as a bot, a speeder, a bad answer, or fraud for one project. */

import { RotateCcw, SlidersHorizontal } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { type QualityRules, type QualityRulesState, getQualityRules, resetQualityRules, saveQualityRules } from "../api";
import { Badge, Button } from "../ui";

/** Rules card for the Live quality tab. ``programmed`` is whether the Decipher survey already carries tracking. */
export function QualityRulesCard({ projectId, programmed, onError }: {
  projectId: string;
  programmed: boolean;
  onError: (message: string) => void;
}) {
  const [state, setState] = useState<QualityRulesState | null>(null);
  const [draft, setDraft] = useState<QualityRules | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setState(null);
    setDraft(null);
    getQualityRules(projectId).then(setState).catch((reason: Error) => onError(reason.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  if (!state) return null;
  const rules = state.rules;
  const editing = draft !== null;

  async function run(action: () => Promise<QualityRulesState>) {
    setBusy(true);
    try {
      setState(await action());
      setDraft(null);
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "The rules were not saved.");
    } finally {
      setBusy(false);
    }
  }

  const surveyChanged = draft !== null && state.survey_fields.some((key) => JSON.stringify(draft[key]) !== JSON.stringify(rules[key]));

  return (
    <section aria-labelledby="quality-rules-title" className="rounded-xl border border-line bg-surface p-4 shadow-xs">
      <div className="flex flex-wrap items-start gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent">
          <SlidersHorizontal aria-hidden className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="flex flex-wrap items-center gap-2 text-sm font-semibold" id="quality-rules-title">
            Quality rules
            {state.changed.length === 0 ? <Badge>Defaults</Badge> : <Badge tone="accent">{state.changed.length} changed</Badge>}
          </h3>
          <p className="mt-0.5 text-sm text-ink-2">
            Decide what counts as a bot, a speeder, a poor answer, or fraud before the survey goes live. Flags on the
            dashboard follow these rules as soon as you save.
          </p>
        </div>
        {!editing && (
          <Button onClick={() => setDraft({ ...rules })} size="sm">
            Edit rules
          </Button>
        )}
      </div>

      {!editing && <RulesSummary rules={rules} state={state} />}

      {editing && draft && (
        <form
          className="mt-4 space-y-5"
          onSubmit={(event) => {
            event.preventDefault();
            void run(() => saveQualityRules(projectId, draft));
          }}
        >
          <Group title="Bot detection">
            <NumberField
              defaultValue={state.defaults.bot_threshold} help="Behaviour score (0 human, 1 bot) at which a respondent counts as a bot."
              label="Bot score threshold" max={0.99} min={0.3} onChange={(value) => setDraft({ ...draft, bot_threshold: value })} step={0.05} value={draft.bot_threshold}
            />
            <Checklist
              help="Any of these marks a respondent as a bot, whatever the score."
              label="Signals that always mean bot" labels={state.bot_signals} onChange={(value) => setDraft({ ...draft, bot_signals: value })} value={draft.bot_signals}
            />
          </Group>

          <Group title="Speed and attention">
            <NumberField
              defaultValue={state.defaults.speeder_page_seconds} help="Average seconds per page below which a respondent is a speeder."
              label="Speeder: seconds per page" max={60} min={0.5} onChange={(value) => setDraft({ ...draft, speeder_page_seconds: value })} step={0.5} value={draft.speeder_page_seconds}
            />
            <NumberField
              defaultValue={state.defaults.speeder_median_share} help="Also a speeder when total time is under this share of the median (0 turns it off; needs 5 completes)."
              label="Speeder: share of median time" max={0.9} min={0} onChange={(value) => setDraft({ ...draft, speeder_median_share: value })} step={0.05} value={draft.speeder_median_share}
            />
            <NumberField
              defaultValue={state.defaults.straightline_min_rows} help="Same answer on every row of a grid with at least this many rows."
              label="Straight-lining: minimum grid rows" max={30} min={2} onChange={(value) => setDraft({ ...draft, straightline_min_rows: value })} step={1} value={draft.straightline_min_rows}
            />
          </Group>

          <Group title="Open-ended answers">
            <Checklist
              help="Answers the text check flags for these reasons count as low quality."
              label="Low-quality reasons" labels={state.text_reasons} onChange={(value) => setDraft({ ...draft, text_reasons: value })} value={draft.text_reasons}
            />
            <Toggle checked={draft.flag_pasted} label="Flag mostly pasted answers" onChange={(value) => setDraft({ ...draft, flag_pasted: value })} />
          </Group>

          <Group title="Fraud">
            <NumberField
              defaultValue={state.defaults.fraud_threshold} help="Fraud score (repeat devices, networks, duplicate answers) at which a respondent is high risk."
              label="High fraud risk threshold" max={0.99} min={0.3} onChange={(value) => setDraft({ ...draft, fraud_threshold: value })} step={0.05} value={draft.fraud_threshold}
            />
            <Toggle checked={draft.flag_duplicates} label="Flag duplicate respondents" onChange={(value) => setDraft({ ...draft, flag_duplicates: value })} />
            <Toggle checked={draft.flag_datacenter} label="Flag connections from cloud data centres (bot farms, many VPNs)" onChange={(value) => setDraft({ ...draft, flag_datacenter: value })} />
          </Group>

          <Group note="Written into the survey when you next program it in Decipher." title="During the survey">
            <Toggle
              checked={draft.terminate_in_survey}
              label="End the survey for respondents with a clear bot signal"
              onChange={(value) => setDraft({ ...draft, terminate_in_survey: value })}
            />
            {draft.terminate_in_survey && (
              <>
                <NumberField
                  defaultValue={state.defaults.terminate_after_page} help="The check runs when this page is submitted; bots end there."
                  label="Check after page" max={10} min={1} onChange={(value) => setDraft({ ...draft, terminate_after_page: value })} step={1} value={draft.terminate_after_page}
                />
                <Checklist
                  help="Only these signals end the survey. Respondents are never ended on score alone."
                  label="Signals that end the survey" labels={state.bot_signals} onChange={(value) => setDraft({ ...draft, terminate_signals: value })} value={draft.terminate_signals}
                />
              </>
            )}
            <Toggle checked={draft.privacy_notice} label="Show a privacy notice on the first page" onChange={(value) => setDraft({ ...draft, privacy_notice: value })} />
            {draft.privacy_notice && (
              <label className="block text-sm">
                <span className="font-medium">Notice text</span>
                <textarea
                  className="mt-1 w-full rounded-md border border-line-strong bg-surface px-2 py-1.5 text-sm"
                  maxLength={400}
                  onChange={(event) => setDraft({ ...draft, privacy_text: event.target.value })}
                  rows={2}
                  value={draft.privacy_text}
                />
              </label>
            )}
          </Group>

          {surveyChanged && programmed && (
            <p className="rounded-md border border-warn-line bg-warn-soft px-3 py-2 text-sm text-warn" role="status">
              The live survey keeps its current in-survey settings until you program it in Decipher again.
            </p>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <Button disabled={busy} type="submit" variant="primary">{busy ? "Saving…" : "Save rules"}</Button>
            <Button disabled={busy} onClick={() => setDraft(null)} variant="ghost">Cancel</Button>
            <span className="flex-1" />
            <Button disabled={busy} onClick={() => setDraft({ ...state.defaults })} size="sm" variant="ghost">
              <RotateCcw aria-hidden className="h-3.5 w-3.5" />
              Fill in defaults
            </Button>
            {state.changed.length > 0 && (
              <Button disabled={busy} onClick={() => void run(() => resetQualityRules(projectId))} size="sm" variant="ghost">
                Reset to defaults
              </Button>
            )}
          </div>
        </form>
      )}
    </section>
  );
}

function RulesSummary({ rules, state }: { rules: QualityRules; state: QualityRulesState }) {
  const items: [string, string][] = [
    ["Bot", `score ≥ ${rules.bot_threshold} or ${rules.bot_signals.length} of ${Object.keys(state.bot_signals).length} decisive signals`],
    ["Speeder", `under ${rules.speeder_page_seconds} s a page${rules.speeder_median_share ? ` or ${Math.round(rules.speeder_median_share * 100)}% of median time` : ""}`],
    ["Straight-lining", `grids of ${rules.straightline_min_rows}+ rows`],
    ["Open ends", `${rules.text_reasons.length} low-quality reasons${rules.flag_pasted ? ", pasted answers flagged" : ""}`],
    ["Fraud", `score ≥ ${rules.fraud_threshold}${rules.flag_datacenter ? ", data-centre IPs flagged" : ""}`],
    ["In survey", rules.terminate_in_survey && rules.terminate_signals.length ? `clear bots ended after page ${rules.terminate_after_page}` : "nobody is ended early"],
  ];
  return (
    <dl className="mt-3 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
      {items.map(([term, detail]) => (
        <div className="flex gap-2" key={term}>
          <dt className="w-28 shrink-0 text-muted">{term}</dt>
          <dd className="min-w-0 text-ink-2">{detail}</dd>
        </div>
      ))}
    </dl>
  );
}

function Group({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <fieldset className="space-y-3 rounded-lg border border-line p-3">
      <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-muted">{title}</legend>
      {note && <p className="text-xs text-muted">{note}</p>}
      {children}
    </fieldset>
  );
}

function NumberField({ label, help, value, defaultValue, min, max, step, onChange }: {
  label: string; help: string; value: number; defaultValue: number; min: number; max: number; step: number; onChange: (value: number) => void;
}) {
  return (
    <label className="block text-sm">
      <span className="font-medium">{label}</span>
      {value !== defaultValue && <span className="ml-2 text-xs text-muted">default {defaultValue}</span>}
      <span className="mt-0.5 block text-xs text-muted">{help}</span>
      <input
        className="mt-1 h-8 w-28 rounded-md border border-line-strong bg-surface px-2 text-sm"
        max={max}
        min={min}
        onChange={(event) => {
          const next = Number(event.target.value);
          if (!Number.isNaN(next)) onChange(next);
        }}
        step={step}
        type="number"
        value={value}
      />
    </label>
  );
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <label className="flex items-center gap-2 text-sm">
      <input checked={checked} className="h-4 w-4 accent-[var(--color-accent)]" onChange={(event) => onChange(event.target.checked)} type="checkbox" />
      {label}
    </label>
  );
}

function Checklist({ label, help, labels, value, onChange }: {
  label: string; help: string; labels: Record<string, string>; value: string[]; onChange: (value: string[]) => void;
}) {
  return (
    <fieldset className="text-sm">
      <legend className="font-medium">{label}</legend>
      <p className="text-xs text-muted">{help}</p>
      <div className="mt-1 grid gap-1 sm:grid-cols-2">
        {Object.entries(labels).map(([code, text]) => (
          <label className="flex items-center gap-2" key={code}>
            <input
              checked={value.includes(code)}
              className="h-4 w-4 accent-[var(--color-accent)]"
              onChange={(event) => onChange(event.target.checked ? [...value, code] : value.filter((item) => item !== code))}
              type="checkbox"
            />
            {text}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

