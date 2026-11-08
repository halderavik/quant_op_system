import {
  deleteTable,
  duplicateTable,
  insertTable,
  sortTables,
  tablesOf,
  tabspecIssues,
  updateTableTitle,
} from "./model";

export function TabSpecGrid({
  content,
  onChange,
}: {
  content: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
}) {
  const tables = tablesOf(content);
  const issues = tabspecIssues(content);
  return (
    <div className="space-y-3">
      <div className="flex gap-2 text-sm">
        <button type="button" onClick={() => onChange(sortTables(content))}>Sort by title</button>
        <button type="button" onClick={() => onChange(insertTable(content, tables.length - 1))}>Insert table</button>
      </div>
      {issues.map((issue) => (
        <p key={issue} className="text-sm text-amber-900">{issue}</p>
      ))}
      <table className="w-full text-left text-sm">
        <thead className="sticky top-0 bg-white">
          <tr>
            <th className="py-2">ID</th>
            <th>Title</th>
            <th>Type</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {tables.map((table, index) => (
            <tr key={`${table.id}-${index}`} className="border-t border-stone-200">
              <td className="py-2">{table.id}</td>
              <td>
                <input
                  aria-label={`${table.id} title`}
                  className="w-full rounded border border-stone-300 px-2 py-1"
                  value={table.title ?? ""}
                  onChange={(event) => onChange(updateTableTitle(content, index, event.target.value))}
                />
              </td>
              <td>{table.table_type}</td>
              <td className="space-x-2 whitespace-nowrap">
                <button type="button" onClick={() => onChange(duplicateTable(content, index))}>Copy</button>
                <button type="button" onClick={() => onChange(insertTable(content, index))}>Insert</button>
                <button type="button" onClick={() => onChange(deleteTable(content, index))}>Delete</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function tabSpecBlocked(content: Record<string, unknown>): boolean {
  return tabspecIssues(content).length > 0;
}
