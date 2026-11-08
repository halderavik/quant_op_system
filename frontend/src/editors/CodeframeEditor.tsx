import {
  addCode,
  codesOf,
  deleteCode,
  netsOf,
  reparentCode,
  updateCode,
} from "./model";

export function CodeframeEditor({
  content,
  onChange,
}: {
  content: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
}) {
  const codes = codesOf(content);
  const nets = netsOf(content);
  return (
    <div className="space-y-4 text-sm">
      <button className="rounded border border-stone-400 px-3 py-1" onClick={() => onChange(addCode(content))} type="button">
        Add code
      </button>
      {codes.map((code, index) => (
        <fieldset key={code.id} className="rounded border border-stone-200 p-3">
          <legend className="px-1">{code.id}</legend>
          <label className="mt-2 block">
            Label
            <input
              aria-label={`${code.id} label`}
              className="mt-1 w-full rounded border border-stone-300 px-2 py-1"
              value={code.label}
              onChange={(event) => onChange(updateCode(content, index, { label: event.target.value }))}
            />
          </label>
          <label className="mt-2 block">
            Definition
            <textarea
              aria-label={`${code.id} definition`}
              className="mt-1 h-16 w-full rounded border border-stone-300 p-2"
              value={code.definition ?? ""}
              onChange={(event) => onChange(updateCode(content, index, { definition: event.target.value }))}
            />
          </label>
          <label className="mt-2 block">
            Include examples
            <input
              aria-label={`${code.id} include examples`}
              className="mt-1 w-full rounded border border-stone-300 px-2 py-1"
              value={(code.include_examples ?? []).join(" | ")}
              onChange={(event) => onChange(updateCode(content, index, { include_examples: splitExamples(event.target.value) }))}
            />
          </label>
          <label className="mt-2 block">
            Exclude examples
            <input
              aria-label={`${code.id} exclude examples`}
              className="mt-1 w-full rounded border border-stone-300 px-2 py-1"
              value={(code.exclude_examples ?? []).join(" | ")}
              onChange={(event) => onChange(updateCode(content, index, { exclude_examples: splitExamples(event.target.value) }))}
            />
          </label>
          <label className="mt-2 block">
            Parent net
            <select
              aria-label={`${code.id} parent`}
              className="ml-2 rounded border border-stone-300 px-2 py-1"
              value={code.parent_id ?? ""}
              onChange={(event) => onChange(reparentCode(content, index, event.target.value))}
            >
              <option value="">None</option>
              {nets.map((net) => (
                <option key={net.id} value={net.id}>{net.label}</option>
              ))}
            </select>
          </label>
          <button className="mt-2 underline" onClick={() => onChange(deleteCode(content, index))} type="button">
            Delete code
          </button>
        </fieldset>
      ))}
      {nets.length > 0 && (
        <section>
          <h3 className="font-semibold">Nets</h3>
          <ul className="mt-1 list-disc pl-5">
            {nets.map((net) => (
              <li key={net.id}>{net.id} {net.label}: {net.child_ids.join(", ")}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function splitExamples(value: string): string[] {
  return value.split("|").map((part) => part.trim()).filter(Boolean);
}
