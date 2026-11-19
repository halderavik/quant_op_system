import type { Catalog, QuestionLite } from "./logic";
import {
  earlierIds,
  highlight,
  setHidden,
  setNumber,
  setOptionFlag,
  setRandomize,
  setRequired,
  setRowFilter,
  setShowIf,
  setSorted,
  setTerminateTiming,
  toDraft,
  type ConditionDraft,
  type ShowIfDraft,
} from "./logicEdit";

const OPERATORS: [string, string][] = [
  ["eq", "is"],
  ["ne", "is not"],
  ["in", "is one of"],
  ["not_in", "is not one of"],
  ["gt", ">"],
  ["gte", "≥"],
  ["lt", "<"],
  ["lte", "≤"],
  ["answered", "is answered"],
  ["not_answered", "is not answered"],
];

const box = "rounded border border-line-strong bg-surface px-2 py-1 text-sm";

function ConditionRow({
  condition,
  refs,
  catalog,
  onChange,
  onRemove,
}: {
  condition: ConditionDraft;
  refs: string[];
  catalog: Catalog;
  onChange: (next: ConditionDraft) => void;
  onRemove: () => void;
}) {
  const options = catalog[condition.ref]?.options ?? [];
  const noValue = condition.op === "answered" || condition.op === "not_answered";
  const toggle = (code: string) =>
    onChange({ ...condition, values: condition.values.includes(code) ? condition.values.filter((v) => v !== code) : [...condition.values, code] });
  return (
    <div className="flex flex-wrap items-start gap-2">
      <select aria-label="Condition question" className={box} value={condition.ref} onChange={(e) => onChange({ ...condition, ref: e.target.value, values: [] })}>
        <option value="">Question…</option>
        {refs.map((id) => <option key={id} value={id}>{id}</option>)}
      </select>
      <select aria-label="Condition operator" className={box} value={condition.op} onChange={(e) => onChange({ ...condition, op: e.target.value })}>
        {OPERATORS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select>
      {!noValue && (options.length > 0 ? (
        <span className="flex max-w-md flex-wrap gap-x-3 gap-y-1 text-sm">
          {options.map((option) => (
            <label key={String(option.code)} className="flex items-center gap-1">
              <input type="checkbox" checked={condition.values.includes(String(option.code))} onChange={() => toggle(String(option.code))} />
              {option.code} {option.label}
            </label>
          ))}
        </span>
      ) : (
        <input aria-label="Condition value" className={`${box} w-28`} placeholder="value" value={condition.values.join(", ")}
          onChange={(e) => onChange({ ...condition, values: e.target.value.split(",").map((v) => v.trim()) })} />
      ))}
      <button type="button" className="text-xs underline text-ink-2" onClick={onRemove}>Remove</button>
    </div>
  );
}

/** Pickers for the logic a reviewer most often corrects. Anything else is changed in chat. */
export function LogicEditor({
  question,
  ids,
  catalog,
  onChange,
}: {
  question: QuestionLite;
  ids: string[];
  catalog: Catalog;
  onChange: (next: QuestionLite) => void;
}) {
  const spec = (question.programming ?? {}) as Record<string, any>;
  const refs = [...earlierIds(ids, question.id), ...Object.keys(catalog).filter((id) => catalog[id].type === "derived")];
  const draft = toDraft(question.display_if);
  const update = (next: ShowIfDraft) => onChange(setShowIf(question, next));
  const numeric = question.type === "numeric" || question.type === "allocation";
  const hasRows = (question.matrix_items ?? []).length > 0 || question.type === "multi_select" || question.type === "allocation";
  const row = (spec.row_condition ?? {}) as { source?: string; mode?: string };
  return (
    <div className="mt-2 space-y-3 text-sm">
      <fieldset>
        <legend className="text-xs font-medium text-ink-2">Who sees it</legend>
        <label className="mt-1 flex items-center gap-2">
          <input type="checkbox" checked={Boolean(spec.hidden)} onChange={(e) => onChange(setHidden(question, e.target.checked))} />
          Hidden question (never shown)
        </label>
        {draft ? (
          <div className="mt-1 space-y-2">
            {draft.conditions.length > 1 && (
              <select aria-label="Join conditions" className={box} value={draft.join} onChange={(e) => update({ ...draft, join: e.target.value as "and" | "or" })}>
                <option value="and">All of these</option>
                <option value="or">Any of these</option>
              </select>
            )}
            {draft.conditions.length === 0 && <p className="text-ink-2">Everyone who reaches it.</p>}
            {draft.conditions.map((condition, index) => (
              <ConditionRow key={index} condition={condition} refs={refs} catalog={catalog}
                onChange={(next) => update({ ...draft, conditions: draft.conditions.map((c, i) => (i === index ? next : c)) })}
                onRemove={() => update({ ...draft, conditions: draft.conditions.filter((_, i) => i !== index) })} />
            ))}
            <button type="button" className="text-xs underline" onClick={() => update({ ...draft, conditions: [...draft.conditions, { ref: "", op: "eq", values: [] }] })}>
              Add condition
            </button>
          </div>
        ) : (
          <p className="mt-1 text-ink-2">
            This condition uses grid rows, counts, or nested logic. Change it in chat, or{" "}
            <button type="button" className="underline" onClick={() => update({ join: "and", conditions: [] })}>start it again here</button>.
          </p>
        )}
      </fieldset>

      {(question.options ?? []).length > 0 && (
        <fieldset>
          <legend className="text-xs font-medium text-ink-2">Answers</legend>
          <table className="mt-1 text-sm">
            <thead><tr className="text-xs text-ink-2"><th className="pr-3 text-left font-normal">Answer</th><th className="px-2 font-normal">Terminate</th><th className="px-2 font-normal">Anchor</th>{question.type === "multi_select" && <th className="px-2 font-normal">Exclusive</th>}</tr></thead>
            <tbody>
              {(question.options ?? []).map((option, index) => (
                <tr key={`${option.code}-${index}`}>
                  <td className="pr-3">{option.code} {option.label}</td>
                  <td className="px-2 text-center"><input aria-label={`Terminate ${option.code}`} type="checkbox" checked={Boolean(option.terminate)} onChange={(e) => onChange(setOptionFlag(question, index, "terminate", e.target.checked))} /></td>
                  <td className="px-2 text-center"><input aria-label={`Anchor ${option.code}`} type="checkbox" checked={Boolean(option.anchor)} onChange={(e) => onChange(setOptionFlag(question, index, "anchor", e.target.checked))} /></td>
                  {question.type === "multi_select" && <td className="px-2 text-center"><input aria-label={`Exclusive ${option.code}`} type="checkbox" checked={Boolean(option.exclusive)} onChange={(e) => onChange(setOptionFlag(question, index, "exclusive", e.target.checked))} /></td>}
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-2 flex flex-wrap gap-4">
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={Boolean(question.randomize_options)} onChange={(e) => onChange(setRandomize(question, e.target.checked))} />
              Randomize answers
            </label>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={Boolean(spec.sort_alphabetically)} onChange={(e) => onChange(setSorted(question, e.target.checked))} />
              Sort A-Z
            </label>
            <label className="flex items-center gap-2">
              Terminate
              <select aria-label="Terminate timing" className={box} value={spec.terminate_immediately ? "now" : "flag"} onChange={(e) => onChange(setTerminateTiming(question, e.target.value === "now"))}>
                <option value="now">immediately</option>
                <option value="flag">as a flag at the end of the screener</option>
              </select>
            </label>
          </div>
        </fieldset>
      )}

      <fieldset className="flex flex-wrap items-end gap-3">
        <legend className="text-xs font-medium text-ink-2">Entry checks</legend>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={question.required !== false} onChange={(e) => onChange(setRequired(question, e.target.checked))} />
          Answer required
        </label>
        {numeric && (["min_value", "max_value", "total"] as const).map((key) => (
          <label key={key} className="text-xs text-ink-2">
            {key === "min_value" ? "Lowest" : key === "max_value" ? "Highest" : "Must add up to"}
            <input aria-label={key} className={`${box} ml-1 w-20`} defaultValue={spec[key] ?? ""} onBlur={(e) => onChange(setNumber(question, key, e.target.value))} />
          </label>
        ))}
        {question.type === "open_text" && (
          <label className="text-xs text-ink-2">
            Minimum characters
            <input aria-label="min_chars" className={`${box} ml-1 w-20`} defaultValue={spec.min_chars ?? ""} onBlur={(e) => onChange(setNumber(question, "min_chars", e.target.value))} />
          </label>
        )}
      </fieldset>

      {hasRows && (
        <fieldset className="flex flex-wrap items-center gap-2">
          <legend className="text-xs font-medium text-ink-2">Which rows show</legend>
          <select aria-label="Row filter source" className={box} value={row.source ?? ""} onChange={(e) => onChange(setRowFilter(question, e.target.value, row.mode ?? "selected"))}>
            <option value="">All rows</option>
            {earlierIds(ids, question.id).map((id) => <option key={id} value={id}>Only rows from {id}</option>)}
          </select>
          {row.source && (
            <select aria-label="Row filter mode" className={box} value={row.mode ?? "selected"} onChange={(e) => onChange(setRowFilter(question, row.source ?? "", e.target.value))}>
              <option value="selected">that were chosen</option>
              <option value="not_selected">that were not chosen</option>
              <option value="positive">given a number above 0</option>
            </select>
          )}
        </fieldset>
      )}
    </div>
  );
}

/** The part of the uploaded file the question was read from, with its wording marked. */
export function SourceExcerpt({ excerpt, wording }: { excerpt: string; wording: string }) {
  return (
    <pre className="mt-1 max-h-80 overflow-auto whitespace-pre-wrap rounded border border-line bg-surface px-3 py-2 font-sans text-sm text-ink">
      {highlight(excerpt, wording).map((part, index) =>
        part.match ? <mark key={index} className="rounded bg-accent-soft px-0.5 text-ink">{part.text}</mark> : <span key={index}>{part.text}</span>,
      )}
    </pre>
  );
}
