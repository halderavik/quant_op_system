import { downloadUrl } from "../api";
import type { Tone } from "../outputs";
import { Badge } from "../ui";

type CleaningRow = {
  source_row_id?: number;
  respondent_id?: string;
  disposition?: string;
  rule_ids?: string[];
  flags?: { detail?: string }[];
};

type CleaningRule = {
  id?: string;
  label?: string;
  ran?: boolean;
  skip_reason?: string;
  definition?: string;
};

type OpenEndRow = {
  respondent_id?: string;
  variable?: string;
  text_preview?: string;
  rule_id?: string;
  detail?: string;
};

/** Read-only fraud recommendation: counts, rules, and the respondent list. */
export function CleaningViewer({ content }: { content: Record<string, unknown> }) {
  const summary = (content.summary ?? {}) as Record<string, unknown>;
  const respondents = (content.respondents ?? []) as CleaningRow[];
  const rules = (content.rules ?? []) as CleaningRule[];
  const openEnds = (content.open_ends ?? []) as OpenEndRow[];
  const fileId = typeof content.export_file_id === "string" ? content.export_file_id : "";
  const skipped = Array.isArray(summary.skipped) ? (summary.skipped as string[]) : [];
  const shown = respondents.slice(0, 200);
  return (
    <div className="space-y-6 text-sm text-ink">
      <div className="grid grid-cols-3 gap-3">
        <Count label="Remove" tone="danger" value={summary.remove_n} />
        <Count label="Review" tone="warn" value={summary.review_n} />
        <Count label="Keep" tone="success" value={summary.keep_n} />
      </div>
      {(Boolean(summary.semantic_review) || skipped.length > 0) && (
        <div className="space-y-1 rounded-lg border border-line bg-surface p-3">
          {Boolean(summary.semantic_review) && <p>{String(summary.semantic_review)}</p>}
          {skipped.length > 0 && <p className="text-ink-2">Not run: {skipped.join("; ")}</p>}
        </div>
      )}
      <section>
        <h3 className="mb-2 text-sm font-semibold">Rules</h3>
        <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
          {rules.map((rule) => (
            <li className="px-3 py-2" key={rule.id}>
              <p className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{rule.label}</span>
                {rule.ran ? <Badge tone="success">Ran</Badge> : <Badge>Not run</Badge>}
              </p>
              {rule.skip_reason && <p className="text-xs text-muted">{rule.skip_reason}</p>}
              <p className="text-ink-2">{rule.definition}</p>
            </li>
          ))}
        </ul>
      </section>
      <section>
        <h3 className="mb-2 text-sm font-semibold">Respondents</h3>
        <div className="max-h-[28rem] overflow-auto rounded-lg border border-line bg-surface">
          <table className="w-full border-collapse text-left">
            <thead className="sticky top-0 bg-sunken">
              <tr className="border-b border-line-strong">
                <th className="px-3 py-1.5 font-medium" scope="col">Id</th>
                <th className="px-3 py-1.5 font-medium" scope="col">Disposition</th>
                <th className="px-3 py-1.5 font-medium" scope="col">Rules</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((row) => (
                <tr className="border-b border-line last:border-0" key={row.source_row_id}>
                  <td className="px-3 py-1.5 font-mono text-xs">{row.respondent_id}</td>
                  <td className="px-3 py-1.5">
                    <Badge tone={DISPOSITION_TONE[row.disposition ?? ""] ?? "neutral"}>{row.disposition}</Badge>
                  </td>
                  <td className="px-3 py-1.5 text-ink-2">{(row.rule_ids ?? []).join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {respondents.length > shown.length && (
          <p className="mt-2 text-ink-2">
            Showing {shown.length} of {respondents.length}.{" "}
            {fileId ? (
              <a className="font-medium text-accent underline" href={downloadUrl(fileId)}>
                Download the workbook
              </a>
            ) : (
              "The workbook"
            )}{" "}
            for every row.
          </p>
        )}
      </section>
      {openEnds.length > 0 && (
        <section>
          <h3 className="mb-2 text-sm font-semibold">Open ends</h3>
          <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
            {openEnds.slice(0, 80).map((row, index) => (
              <li className="px-3 py-2" key={`${row.respondent_id}-${row.variable}-${index}`}>
                <p>
                  <span className="font-mono text-xs text-muted">{row.respondent_id} · {row.variable}</span>
                </p>
                <p>{row.text_preview}</p>
                <p className="text-xs text-ink-2">{row.detail}</p>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

const DISPOSITION_TONE: Record<string, Tone> = { remove: "danger", review: "warn", keep: "success" };

const COUNT_TONE: Record<Tone, string> = {
  danger: "text-danger",
  warn: "text-warn",
  success: "text-success",
  neutral: "text-ink",
  accent: "text-accent",
};

function Count({ label, value, tone }: { label: string; value: unknown; tone: Tone }) {
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2.5 shadow-xs">
      <p className="text-[11px] font-medium uppercase tracking-wider text-muted">{label}</p>
      <p className={`text-2xl font-semibold tabular-nums ${COUNT_TONE[tone]}`}>{String(value ?? 0)}</p>
    </div>
  );
}
