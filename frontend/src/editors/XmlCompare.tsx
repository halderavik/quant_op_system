import { useMemo, useState } from "react";
import { compareXml, type XmlCompareRow, type XmlComparison } from "../api";
import { Badge, Button, cn } from "../ui";
import { lineDiff } from "./lineDiff";

type Filter = "differs" | "all" | "missing" | "extra";

const STATUS: Record<XmlCompareRow["status"], { label: string; tone: "success" | "warn" | "danger" | "neutral" }> = {
  match: { label: "Same", tone: "success" },
  differs: { label: "Differs", tone: "warn" },
  missing: { label: "Only in reference", tone: "danger" },
  extra: { label: "Only generated", tone: "neutral" },
};

/** Compare the generated XML with an edited or reference XML, question by question. */
export function XmlCompare({ projectId }: { projectId: string }) {
  const [reference, setReference] = useState("");
  const [fileName, setFileName] = useState("");
  const [result, setResult] = useState<XmlComparison | null>(null);
  const [filter, setFilter] = useState<Filter>("differs");
  const [openKey, setOpenKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function run() {
    setBusy(true);
    setError("");
    try {
      const next = await compareXml(projectId, reference);
      setResult(next);
      const first = next.questions.find((row) => row.status !== "match");
      setOpenKey(first?.key ?? "");
      setFilter(first ? "differs" : "all");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The comparison failed.");
    } finally {
      setBusy(false);
    }
  }

  const rows = useMemo(
    () =>
      (result?.questions ?? []).filter((row) =>
        filter === "all" ? true : filter === "differs" ? row.status !== "match" : row.status === filter,
      ),
    [result, filter],
  );
  const counts = useMemo(() => {
    const out = { match: 0, differs: 0, missing: 0, extra: 0 };
    for (const row of result?.questions ?? []) out[row.status] += 1;
    return out;
  }, [result]);

  return (
    <section aria-label="Compare XML" className="space-y-3 text-sm">
      <p className="text-ink-2">
        Paste or choose a hand-edited or reference Decipher XML. Each question is lined up with the generated XML
        using the same checks the benchmark scores with. The reference is used for this comparison only and is not saved.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <label className="inline-flex h-7 cursor-pointer items-center rounded-md border border-line-strong bg-surface px-2.5 text-xs font-medium hover:bg-sunken">
          Choose file
          <input
            accept=".xml,.txt,text/xml,text/plain"
            className="sr-only"
            onChange={async (event) => {
              const file = event.target.files?.[0];
              if (!file) return;
              setReference(await file.text());
              setFileName(file.name);
              setResult(null);
            }}
            type="file"
          />
        </label>
        {fileName && <span className="truncate text-xs text-muted">{fileName}</span>}
        <Button disabled={busy || !reference.trim()} onClick={() => void run()} size="sm" variant="primary">
          {busy ? "Comparing…" : "Compare"}
        </Button>
        {reference && (
          <Button
            disabled={busy}
            onClick={() => {
              setReference("");
              setFileName("");
              setResult(null);
            }}
            size="sm"
            variant="ghost"
          >
            Clear
          </Button>
        )}
      </div>
      <textarea
        aria-label="Reference XML"
        className="h-24 w-full rounded-md border border-line-strong bg-surface p-2 font-mono text-xs"
        onChange={(event) => {
          setReference(event.target.value);
          setFileName("");
        }}
        placeholder='<survey ...> or paste one question, for example <radio label="S1">…</radio>'
        spellCheck={false}
        value={reference}
      />
      {error && <p className="text-danger" role="alert">{error}</p>}
      {result && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-base font-semibold text-ink">{result.match ?? "–"}% match</span>
            {Object.entries(result.areas).map(([area, score]) => (
              <Badge key={area} tone={score.passed === score.total ? "success" : "neutral"}>
                {area} {score.passed}/{score.total}
              </Badge>
            ))}
          </div>
          <div aria-label="Which questions" className="flex flex-wrap gap-1" role="tablist">
            {(
              [
                ["differs", `Differences (${counts.differs + counts.missing + counts.extra})`],
                ["missing", `Only in reference (${counts.missing})`],
                ["extra", `Only generated (${counts.extra})`],
                ["all", `All (${result.questions.length})`],
              ] as [Filter, string][]
            ).map(([value, label]) => (
              <button
                aria-selected={filter === value}
                className={cn(
                  "rounded-md px-2.5 py-1 text-xs font-medium",
                  filter === value ? "bg-sunken text-ink" : "text-muted hover:text-ink",
                )}
                key={value}
                onClick={() => setFilter(value)}
                role="tab"
                type="button"
              >
                {label}
              </button>
            ))}
          </div>
          {rows.length === 0 ? (
            <p className="rounded-md border border-line bg-surface px-3 py-6 text-center text-muted">
              {filter === "differs" ? "Every question matches the reference." : "No questions here."}
            </p>
          ) : (
            <ul className="space-y-2">
              {rows.map((row) => (
                <CompareRow
                  key={row.key}
                  onToggle={() => setOpenKey(openKey === row.key ? "" : row.key)}
                  open={openKey === row.key}
                  row={row}
                />
              ))}
            </ul>
          )}
          {result.other_checks.some((check) => !check.passed) && (
            <details className="rounded-md border border-line bg-surface px-3 py-2">
              <summary className="cursor-pointer text-xs font-medium text-ink">Terminates and other checks</summary>
              <ul className="mt-2 space-y-1 text-xs">
                {result.other_checks.filter((check) => !check.passed).map((check, index) => (
                  <li key={`${check.item}-${index}`}>
                    <span className="font-mono">{check.item}</span>: {check.check}
                    {check.detail ? ` (${check.detail})` : ""}
                  </li>
                ))}
              </ul>
            </details>
          )}
          {Object.keys(result.not_scored).length > 0 && (
            <details className="rounded-md border border-line bg-surface px-3 py-2">
              <summary className="cursor-pointer text-xs font-medium text-ink">Not scored</summary>
              {Object.entries(result.not_scored).map(([heading, items]) => (
                <p className="mt-2 text-xs" key={heading}>
                  <span className="font-medium">{heading}:</span> {items.join(", ")}
                </p>
              ))}
            </details>
          )}
        </>
      )}
    </section>
  );
}

function CompareRow({ row, open, onToggle }: { row: XmlCompareRow; open: boolean; onToggle: () => void }) {
  const status = STATUS[row.status];
  const failed = row.checks.filter((check) => !check.passed);
  return (
    <li className="rounded-lg border border-line bg-surface">
      <button
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
        onClick={onToggle}
        type="button"
      >
        <span className="font-mono text-xs font-semibold text-ink">{row.label}</span>
        <Badge tone={status.tone}>{status.label}</Badge>
        {row.total > 0 && <span className="text-xs text-muted">{row.passed}/{row.total} checks</span>}
        <span className="ml-auto truncate text-xs text-muted">
          {failed.slice(0, 3).map((check) => check.check).join(", ")}
        </span>
      </button>
      {open && (
        <div className="space-y-2 border-t border-line px-3 py-2">
          {failed.length > 0 && (
            <ul className="space-y-0.5 text-xs text-warn">
              {failed.map((check, index) => (
                <li key={`${check.check}-${index}`}>
                  <span className="font-medium">{check.area} · {check.check}</span>
                  {check.detail ? `: ${check.detail}` : ""}
                </li>
              ))}
            </ul>
          )}
          <SideBySide left={row.generated_xml} right={row.reference_xml} />
        </div>
      )}
    </li>
  );
}

const CELL: Record<string, string> = {
  same: "",
  changed: "bg-warn-soft",
  left: "bg-danger-soft",
  right: "bg-success-soft",
};

function SideBySide({ left, right }: { left: string; right: string }) {
  const rows = useMemo(() => lineDiff(left, right), [left, right]);
  return (
    <div className="overflow-x-auto rounded-md border border-line">
      <table className="w-full min-w-[360px] table-fixed border-collapse font-mono text-[11px] leading-4">
        <thead>
          <tr className="bg-sunken text-left font-sans text-xs text-ink-2">
            <th className="w-1/2 border-r border-line px-2 py-1 font-medium">Generated</th>
            <th className="w-1/2 px-2 py-1 font-medium">Reference</th>
          </tr>
        </thead>
        <tbody>
          {!left && !right ? (
            <tr>
              <td className="px-2 py-2 font-sans text-muted" colSpan={2}>No XML to show for this question.</td>
            </tr>
          ) : (
            rows.map((row, index) => (
              <tr key={index}>
                <td
                  className={cn(
                    "whitespace-pre-wrap break-all border-r border-line px-2 align-top",
                    row.left !== null && (row.kind === "left" ? CELL.left : CELL[row.kind]),
                  )}
                >
                  {row.left ?? ""}
                </td>
                <td
                  className={cn(
                    "whitespace-pre-wrap break-all px-2 align-top",
                    row.right !== null && (row.kind === "right" ? CELL.right : CELL[row.kind]),
                  )}
                >
                  {row.right ?? ""}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
