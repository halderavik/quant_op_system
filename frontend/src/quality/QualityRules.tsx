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
    <section aria-labelledby="quality-rules-title" className="@container rounded-xl border border-line bg-surface p-4 shadow-xs">
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
          <RulesGuide state={state} />

          <Group title="Bot detection">
            <NumberField
              defaultValue={state.defaults.bot_threshold} help="Behaviour score (0 looks human, 1 almost certainly a bot) at which a respondent is flagged. Lower is stricter and flags more real people; higher only catches clear cases."
              label="Bot score threshold" max={0.99} min={0.3} onChange={(value) => setDraft({ ...draft, bot_threshold: value })} step={0.05} value={draft.bot_threshold}
            />
            <Checklist
              help="Any of these marks a respondent as a bot, whatever the score."
              details={SIGNAL_DETAIL} label="Signals that always mean bot" labels={state.bot_signals} onChange={(value) => setDraft({ ...draft, bot_signals: value })} value={draft.bot_signals}
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
              details={REASON_DETAIL} label="Low-quality reasons" labels={state.text_reasons} onChange={(value) => setDraft({ ...draft, text_reasons: value })} value={draft.text_reasons}
            />
            <Toggle checked={draft.flag_pasted} label="Flag mostly pasted answers, or text that appeared without typing" onChange={(value) => setDraft({ ...draft, flag_pasted: value })} />
          </Group>

          <Group title="Fraud">
            <NumberField
              defaultValue={state.defaults.fraud_threshold} help="Fraud score (0 to 1, from repeat devices and networks, matching answers, and disguised locations) at which a respondent is flagged as high risk."
              label="High fraud risk threshold" max={0.99} min={0.3} onChange={(value) => setDraft({ ...draft, fraud_threshold: value })} step={0.05} value={draft.fraud_threshold}
            />
            <Toggle checked={draft.flag_duplicates} label="Flag duplicate respondents (the same person or device taking the survey again)" onChange={(value) => setDraft({ ...draft, flag_duplicates: value })} />
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
                  details={SIGNAL_DETAIL} label="Signals that end the survey" labels={state.bot_signals} onChange={(value) => setDraft({ ...draft, terminate_signals: value })} value={draft.terminate_signals}
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

/** What each decisive bot signal means, in plain words. Keys match the backend's BOT_SIGNALS. */
const SIGNAL_DETAIL: Record<string, string> = {
  automation: "The browser reports that software is driving it (for example Selenium or a headless browser).",
  scripted_input: "Clicks and key presses were produced by code, not by a real mouse, touch screen or keyboard.",
  no_input: "Pages were answered with no mouse, touch or keyboard activity at all.",
  honeypot: "A field hidden from people was filled in. A person can't see it; a form-filling bot does.",
  untyped_answers: "Text appeared in an open end without any typing, as when a script fills the box.",
};

/** What each open-end reason means. Keys match the backend's TEXT_REASONS. */
const REASON_DETAIL: Record<string, string> = {
  gibberish: "Random letters or keyboard mashing, such as “asdfgh”.",
  generic: "An answer that fits any question, such as “good”, “nothing” or “n/a”.",
  irrelevant: "Doesn't answer the question that was asked.",
  copy_paste: "The same text repeated across questions or respondents.",
  low_quality: "Too short or careless to be useful.",
};

function RulesSummary({ rules, state }: { rules: QualityRules; state: QualityRulesState }) {
  const median = rules.speeder_median_share ? Math.round(rules.speeder_median_share * 100) : 0;
  const items: { term: string; setting: string; meaning: string }[] = [
    {
      term: "Bot",
      setting: `score ≥ ${rules.bot_threshold}, or any of ${rules.bot_signals.length} decisive signals${rules.bot_signals.length < Object.keys(state.bot_signals).length ? ` (of ${Object.keys(state.bot_signals).length})` : ""}`,
      meaning: "Flagged when how they type, click and move looks automated, or a signal only a bot gives fires.",
    },
    {
      term: "Speeder",
      setting: `under ${rules.speeder_page_seconds} s a page${median ? `, or under ${median}% of the median time` : ""}`,
      meaning: median
        ? `Too fast to have read the questions. With a median of 10 minutes, anyone under ${(10 * median) / 100} minutes is flagged.`
        : "Too fast to have read the questions.",
    },
    {
      term: "Straight-lining",
      setting: `same answer on every row of a grid with ${rules.straightline_min_rows}+ rows`,
      meaning: "Picking one column all the way down usually means they stopped reading.",
    },
    {
      term: "Open ends",
      setting: `${rules.text_reasons.length} of ${Object.keys(state.text_reasons).length} low-quality reasons count${rules.flag_pasted ? "; pasted answers flagged" : ""}`,
      meaning: "Each typed answer is checked for gibberish, generic or off-topic text.",
    },
    {
      term: "Fraud",
      setting: `score ≥ ${rules.fraud_threshold}${rules.flag_duplicates ? "; duplicates flagged" : ""}${rules.flag_datacenter ? "; data-centre IPs flagged" : ""}`,
      meaning: "Catches the same person or device taking the survey more than once, or hiding where they connect from.",
    },
    {
      term: "In survey",
      setting: rules.terminate_in_survey && rules.terminate_signals.length ? `clear bots ended after page ${rules.terminate_after_page}` : "nobody is ended early",
      meaning: rules.terminate_in_survey && rules.terminate_signals.length
        ? "Only a decisive signal ends the survey, never the score alone."
        : "Everyone finishes; flags only show on the dashboard.",
    },
  ];
  return (
    <>
      <dl className="mt-3 grid gap-x-6 gap-y-2.5 text-sm @3xl:grid-cols-2">
        {items.map(({ term, setting, meaning }) => (
          <div className="flex gap-2" key={term}>
            <dt className="w-28 shrink-0 text-muted">{term}</dt>
            <dd className="min-w-0">
              <span className="text-ink">{setting}</span>
              <span className="mt-0.5 block text-xs text-muted">{meaning}</span>
            </dd>
          </div>
        ))}
      </dl>
      <RulesGuide state={state} />
    </>
  );
}

/** Collapsible explanation of every check and how to pick a setting. */
function RulesGuide({ state, open = false }: { state: QualityRulesState; open?: boolean }) {
  const d = state.defaults;
  return (
    <details className="mt-3 rounded-lg border border-line bg-sunken px-3 py-2 text-sm" open={open}>
      <summary className="cursor-pointer font-medium text-ink">How the checks work, and how to choose</summary>
      <div className="mt-2 space-y-3 text-ink-2">
        <p>
          While people take the survey, a tracker records how they answer: typing, mouse and touch movement, scrolling,
          time on each page, grid answers and open-end text. Each respondent gets the checks below. A flag marks them on
          the dashboard and in the export; it doesn&apos;t remove anyone from your data.
        </p>

        <GuideSection title="Scores run from 0 to 1">
          <p>
            0 means the respondent looks entirely human or genuine, 1 means almost certainly a bot or fraud. A respondent is
            flagged when their score reaches the threshold. Under 0.5 counts as low risk, 0.5 to 0.7 medium, 0.7 and over high.
          </p>
          <p>
            <strong className="font-medium text-ink">Lower threshold</strong> (for example 0.5): stricter, catches more bots,
            but flags more real people. <strong className="font-medium text-ink">Higher threshold</strong> (for example 0.85):
            only the clearest cases, so fewer false alarms but more bots get through. The default, {d.bot_threshold}, suits
            most studies. Go lower for a panel known to have bot problems or a high incentive; go higher for a small or
            hard-to-reach sample where losing a real respondent is costly.
          </p>
        </GuideSection>

        <GuideSection title="Bot behaviour">
          <p>
            The bot score comes from how the respondent behaves: whether typing rhythm, mouse paths and timings look like a
            person&apos;s. Some signals are decisive: any one you tick flags the respondent as a bot, whatever their score.
          </p>
          <ul className="list-disc space-y-0.5 pl-5">
            {Object.entries(state.bot_signals).map(([code, label]) => (
              <li key={code}><span className="text-ink">{label}.</span> {SIGNAL_DETAIL[code] ?? ""}</li>
            ))}
          </ul>
        </GuideSection>

        <GuideSection title="Speeders and straight-lining">
          <p>
            <strong className="font-medium text-ink">Speeder</strong>: average time per page is under the limit (default{" "}
            {d.speeder_page_seconds} s), or total time is under a share of the median respondent&apos;s time (default{" "}
            {Math.round(d.speeder_median_share * 100)}%). The median check starts once 5 respondents have finished. Raise the
            seconds for long or text-heavy pages; set the share to 0 to turn the median check off.
          </p>
          <p>
            <strong className="font-medium text-ink">Straight-lining</strong>: the same answer on every row of a grid with at
            least the set number of rows (default {d.straightline_min_rows}). Raise it if short grids where everyone could
            honestly agree are being flagged.
          </p>
          <p>
            <strong className="font-medium text-ink">Flatliner</strong> (always shown): the time between answers is
            unnaturally even, as when a script answers at a fixed pace.
          </p>
        </GuideSection>

        <GuideSection title="Open-ended answers">
          <p>Each typed answer is checked, and flagged for any reason you tick:</p>
          <ul className="list-disc space-y-0.5 pl-5">
            {Object.entries(state.text_reasons).map(([code, label]) => (
              <li key={code}><span className="text-ink">{label}.</span> {REASON_DETAIL[code] ?? ""}</li>
            ))}
          </ul>
          <p>
            <strong className="font-medium text-ink">Pasted answers</strong>: most of the answer was pasted in or appeared
            without typing. Untick it if respondents are asked to paste something, such as a link.
          </p>
        </GuideSection>

        <GuideSection title="Fraud">
          <p>
            The fraud score (0 to 1, default threshold {d.fraud_threshold}) looks at the device and connection: the same
            device or network seen many times, matching answers from different sessions, and disguised locations.
          </p>
          <ul className="list-disc space-y-0.5 pl-5">
            <li><span className="text-ink">Duplicate respondents.</span> The same person or device has already taken this survey.</li>
            <li>
              <span className="text-ink">Data-centre connections.</span> The connection comes from a cloud server rather than
              a home or mobile network. Bot farms use them, and so do many VPNs, so some real people are caught too.
            </li>
          </ul>
        </GuideSection>

        <GuideSection title="During the survey">
          <p>
            These settings are written into the survey when you next program it in Decipher. With &ldquo;End the survey&rdquo;
            on, the check runs when the chosen page is submitted (default page {d.terminate_after_page}), and only the decisive
            signals you tick end the survey, so you don&apos;t pay for a completed bot. Nobody is ended on the score alone. The
            privacy notice tells respondents, on the first page, that how they answer is checked.
          </p>
        </GuideSection>
      </div>
    </details>
  );
}

function GuideSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-1.5">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">{title}</h4>
      {children}
    </section>
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

function Checklist({ label, help, labels, details, value, onChange }: {
  label: string; help: string; labels: Record<string, string>; details?: Record<string, string>; value: string[]; onChange: (value: string[]) => void;
}) {
  return (
    <fieldset className="text-sm">
      <legend className="font-medium">{label}</legend>
      <p className="text-xs text-muted">{help}</p>
      <div className="mt-1 grid gap-1 sm:grid-cols-2">
        {Object.entries(labels).map(([code, text]) => (
          <label className="flex items-start gap-2" key={code}>
            <input
              checked={value.includes(code)}
              className="mt-0.5 h-4 w-4 shrink-0 accent-[var(--color-accent)]"
              onChange={(event) => onChange(event.target.checked ? [...value, code] : value.filter((item) => item !== code))}
              type="checkbox"
            />
            <span>
              {text}
              {details?.[code] && <span className="block text-xs text-muted">{details[code]}</span>}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

