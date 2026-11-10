import { crosstabTable, downloadUrl } from "../api";
import { ProvenancePanel } from "./ProvenancePanel";
import { bookTables, exceptionLines, filterTables, type CrosstabTable } from "./model";
import { useEffect, useState } from "react";

export function CrosstabViewer({
  artifactId,
  content,
  version,
}: {
  artifactId?: string;
  content: Record<string, unknown>;
  version?: number;
}) {
  const tables = bookTables(content);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(tables[0]?.table_id ?? tables[0]?.title ?? "");
  const [loaded, setLoaded] = useState<CrosstabTable | null>(null);
  const [loadError, setLoadError] = useState("");
  const visible = filterTables(tables, query);
  const listed = visible.slice(0, 40);
  const current = visible.find((table) => (table.table_id ?? table.title) === selected) ?? visible[0];
  const fileId = content.export_file_id as string | undefined;
  const exceptions = exceptionLines(content);
  const oversized = content.oversized === true;
  const tableId = current?.table_id;
  const hasRows = Boolean(current?.rows);
  useEffect(() => {
    setLoaded(null);
    if (hasRows || !artifactId || !tableId || oversized) return;
    let cancel = false;
    setLoadError("");
    crosstabTable(artifactId, tableId)
      .then((table) => {
        if (!cancel) setLoaded(table as CrosstabTable);
      })
      .catch((reason: Error) => {
        if (!cancel) setLoadError(reason.message);
      });
    return () => {
      cancel = true;
    };
  }, [artifactId, hasRows, oversized, tableId]);
  const shown = current?.rows ? current : loaded;
  return (
    <div className="space-y-3">
      <label className="block text-sm" htmlFor="table-search">Search tables</label>
      <input
        id="table-search"
        className="w-full rounded border border-stone-300 px-2 py-1"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      <ul className="flex flex-wrap gap-2">
        {listed.map((table) => {
          const id = table.table_id ?? table.title ?? "table";
          return (
            <li key={id}>
              <button
                className={`rounded border px-2 py-1 text-sm ${current && (current.table_id ?? current.title) === id ? "bg-stone-900 text-white" : ""}`}
                onClick={() => setSelected(id)}
                type="button"
              >
                {table.table_id} {table.title}
              </button>
            </li>
          );
        })}
      </ul>
      {visible.length > listed.length && (
        <p className="text-sm text-stone-500">Showing {listed.length} of {visible.length}. Search to narrow the list.</p>
      )}
      {oversized && (
        <p className="text-sm text-amber-900">This saved book is too large to open. Generate the cross-tabs again to build the workbook.</p>
      )}
      {visible.length === 0 && !oversized && <p className="text-sm text-stone-500">No table matches that search.</p>}
      {loadError && <p className="text-sm text-red-700">{loadError}</p>}
      {shown && <TableGrid table={shown} />}
      {exceptions.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold">Exceptions</h3>
          <ul className="list-disc pl-5 text-sm text-amber-900">
            {exceptions.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      )}
      {fileId && (
        <a className="inline-block text-sm underline" href={downloadUrl(fileId)}>Download Excel</a>
      )}
      <ProvenancePanel content={content} version={version} />
    </div>
  );
}

function TableGrid({ table }: { table: CrosstabTable }) {
  return (
    <div>
      <h3 className="mb-2 font-semibold">{table.title}</h3>
      <div className="overflow-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-white">
            <tr>
              <th className="py-2 text-left">Row</th>
              {(table.columns ?? []).map((column) => (
                <th key={column.id} className="px-2 text-right">
                  {column.label}
                  {column.letter ? ` [${column.letter}]` : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(table.rows ?? []).slice(0, 80).map((row) => (
              <tr key={row.label} className="border-t border-stone-200">
                <td className="py-1">{row.label}</td>
                {(table.columns ?? []).map((column) => {
                  const cell = row.cells?.[column.id];
                  const tip = cell
                    ? `Unweighted base ${cell.unweighted_base ?? "—"}, weighted base ${cell.weighted_base ?? "—"}`
                    : "";
                  const letters = cell?.significance_letters;
                  return (
                    <td key={column.id} className="px-2 text-right" title={tip}>
                      <div>{cell?.display_value ?? "—"}</div>
                      <div className="text-stone-500">{cell?.unweighted_numerator ?? ""}</div>
                      {letters ? <div className="text-xs tracking-wide">{letters}</div> : null}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="mt-3 list-disc pl-5 text-sm text-stone-600">
        {(table.footnotes ?? []).map((note) => (
          <li key={note}>{note}</li>
        ))}
      </ul>
    </div>
  );
}
