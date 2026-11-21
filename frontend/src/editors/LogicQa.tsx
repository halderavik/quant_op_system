import { useState } from "react";
import { type LogicQaResult, runLogicQa } from "../studyApi";
import { Badge, Button } from "../ui";

const KIND: Record<string, string> = {
  xml_hides: "XML skips it",
  xml_shows: "XML shows it",
  xml_continues: "Missing terminate",
  xml_terminates: "Extra terminate",
};

/** Simulate respondents through the survey XML and check every base and terminate. */
export function LogicQa({ projectId }: { projectId: string }) {
  const [result, setResult] = useState<LogicQaResult | null>(null);
  const [respondents, setRespondents] = useState(400);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function run() {
    setBusy(true);
    setError("");
    try {
      setResult(await runLogicQa(projectId, respondents));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The logic test failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-label="Logic test" className="space-y-3 text-sm">
      <p className="text-ink-2">
        Runs simulated respondents through this survey's XML the way Decipher would, then checks each one against the
        questionnaire's own bases, terminates, and derived groups. Each disagreement shows the answers that caused it.
        Nothing is sent to Decipher.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1.5 text-xs text-ink-2">
          Respondents
          <select
            className="h-7 rounded-md border border-line-strong bg-surface px-1.5 text-xs"
            onChange={(event) => setRespondents(Number(event.target.value))}
            value={respondents}
          >
            {[200, 400, 1000, 2000].map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </label>
        <Button disabled={busy} onClick={() => void run()} size="sm" variant="primary">
          {busy ? "Testing…" : result ? "Run again" : "Run logic test"}
        </Button>
      </div>
      {error && <p className="text-danger" role="alert">{error}</p>}
      {result && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-base font-semibold text-ink">{result.agreement ?? "–"}% of respondents match</span>
            <Badge tone={result.issues.length ? "warn" : "success"}>
              {result.issues.length ? `${result.issues.length} problem${result.issues.length === 1 ? "" : "s"}` : "No problems"}
            </Badge>
            <span className="text-xs text-muted">
              Screened out: {result.terminated.xml} in the XML, {result.terminated.expected} expected · XML v{result.survey_version},
              questionnaire v{result.questionnaire_version}
            </span>
          </div>
          {result.issues.length > 0 && (
            <ul className="space-y-2">
              {result.issues.map((issue) => (
                <li className="rounded-lg border border-warn-line bg-surface px-3 py-2" key={`${issue.question_id}-${issue.kind}`}>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs font-semibold text-ink">{issue.question_id}</span>
                    <Badge tone="warn">{KIND[issue.kind] ?? issue.kind}</Badge>
                  </div>
                  <p className="mt-1 text-ink">{issue.message}</p>
                  {issue.examples.length > 0 && (
                    <p className="mt-1 text-xs text-muted">
                      For example:{" "}
                      {Object.entries(issue.examples[0])
                        .map(([key, value]) => `${key} = ${value}`)
                        .join("; ") || "no earlier answers involved"}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}
          {result.written_base_without_logic.length > 0 && (
            <p className="rounded-md border border-warn-line bg-warn-soft px-3 py-2 text-warn">
              Written base with no programmed logic: {result.written_base_without_logic.join(", ")}. These are shown to
              everyone; check the To-dos tab.
            </p>
          )}
          {result.never_shown.length > 0 && (
            <p className="text-xs text-ink-2">
              Never reached by any simulated respondent: {result.never_shown.join(", ")}. A rare path may need more
              respondents, or the base can never be met.
            </p>
          )}
          {result.warnings.length > 0 && (
            <details className="rounded-md border border-line bg-surface px-3 py-2">
              <summary className="cursor-pointer text-xs font-medium text-ink">Not fully tested ({result.warnings.length})</summary>
              <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs text-ink-2">
                {result.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </details>
          )}
          <details className="rounded-md border border-line bg-surface px-3 py-2">
            <summary className="cursor-pointer text-xs font-medium text-ink">How many saw each question</summary>
            <table className="mt-2 w-full text-xs">
              <thead>
                <tr className="text-left text-muted">
                  <th className="py-1 font-medium">Question</th>
                  <th className="py-1 text-right font-medium">Expected</th>
                  <th className="py-1 text-right font-medium">XML</th>
                </tr>
              </thead>
              <tbody>
                {result.questions.map((row) => (
                  <tr className={row.expected !== row.xml ? "text-warn" : ""} key={row.question_id}>
                    <td className="py-0.5 font-mono">{row.question_id}</td>
                    <td className="py-0.5 text-right tabular-nums">{row.expected}</td>
                    <td className="py-0.5 text-right tabular-nums">{row.xml}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </div>
      )}
    </section>
  );
}
