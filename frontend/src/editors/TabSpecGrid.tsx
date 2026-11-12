import {
  bannerPlanLabel,
  deleteTable,
  duplicateTable,
  insertTable,
  sortTables,
  tablesOf,
  tabspecIssues,
  updateTableField,
  type TableDraft,
} from "./model";

const columns: { field: keyof TableDraft; label: string }[] = [
  { field: "section", label: "Section" },
  { field: "stub_label", label: "Variable" },
  { field: "title", label: "Title" },
  { field: "plan_type", label: "Type" },
  { field: "base_text", label: "Base" },
  { field: "row_instruction", label: "Rows / nets" },
  { field: "banner_plans", label: "Banner" },
  { field: "notes", label: "Notes" },
];

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
        <p key={issue} className="text-sm text-warn">{issue}</p>
      ))}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="sticky top-0 bg-surface">
            <tr>
              <th className="py-2 pr-2">Table</th>
              {columns.map((column) => (
                <th key={column.field} className="py-2 pr-2">{column.label}</th>
              ))}
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {tables.map((table, index) => (
              <tr key={`${table.id}-${index}`} className="border-t border-line">
                <td className="py-2 pr-2">{table.id}</td>
                {columns.map((column) => (
                  <td key={column.field} className="py-2 pr-2">
                    <input
                      aria-label={`${table.id} ${column.label}`}
                      className="w-full min-w-28 rounded border border-line-strong px-2 py-1"
                      value={cellValue(table, column.field)}
                      onChange={(event) =>
                        onChange(updateTableField(content, index, column.field, event.target.value))
                      }
                    />
                  </td>
                ))}
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
    </div>
  );
}

function cellValue(table: TableDraft, field: keyof TableDraft): string {
  if (field === "banner_plans") return bannerPlanLabel(table);
  if (field === "notes") return (table.notes ?? []).join(" ");
  if (field === "plan_type") return table.plan_type || table.table_type || "";
  if (field === "stub_label") return table.stub_label || (table.row_variable_names ?? []).join(", ");
  const value = table[field];
  return typeof value === "string" ? value : "";
}

export function tabSpecBlocked(content: Record<string, unknown>): boolean {
  return tabspecIssues(content).length > 0;
}
