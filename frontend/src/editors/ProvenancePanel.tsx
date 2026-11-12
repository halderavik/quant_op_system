import { provenanceRows } from "./model";

export function ProvenancePanel({
  content,
  version,
}: {
  content: Record<string, unknown>;
  version?: number;
}) {
  const rows = provenanceRows(content, version);
  return (
    <section className="mt-4 rounded border border-line p-3 text-sm">
      <h3 className="font-semibold">Provenance</h3>
      <dl className="mt-2 grid grid-cols-[8rem_1fr] gap-y-1">
        {rows.map((row) => (
          <div key={row.label} className="contents">
            <dt className="text-muted">{row.label}</dt>
            <dd>{row.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
