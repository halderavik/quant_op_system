/** Learned rules: programming lessons taken from corrections people made before programming. */

import { GraduationCap, Search, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  getQualityTrend,
  listProgrammingLessons,
  setProgrammingLessonStatus,
  type ProgrammingLesson,
  type QualityPoint,
} from "./api";
import { formatRate, trendSummaries } from "./learningTrend";
import { Badge, Button, IconButton } from "./ui";

type Filter = "active" | "disabled" | "all";
type Stage = "all" | "extraction" | "programming";

export const STAGE_LABEL: Record<string, string> = {
  extraction: "Reading the file",
  programming: "Programming logic",
};

/** A short readable form of a stored logic value. */
export function shortValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "not set";
  if (typeof value === "string") return value;
  if (typeof value === "boolean") return value ? "yes" : "no";
  const text = JSON.stringify(value);
  return text.length > 160 ? `${text.slice(0, 157)}...` : text;
}

/** Lessons that match the filters and every word of the search. */
export function visibleLessons(
  lessons: ProgrammingLesson[],
  filter: Filter,
  search: string,
  stage: Stage = "all",
): ProgrammingLesson[] {
  const words = search.toLowerCase().split(/\s+/).filter(Boolean);
  return lessons.filter((lesson) => {
    if (filter !== "all" && lesson.status !== filter) return false;
    if (stage !== "all" && (lesson.stage ?? "programming") !== stage) return false;
    const haystack = `${lesson.rule} ${lesson.example_instruction} ${lesson.field} ${lesson.question_type}`.toLowerCase();
    return words.every((word) => haystack.includes(word));
  });
}

export function LessonsDialog({ onClose }: { onClose: () => void }) {
  const [lessons, setLessons] = useState<ProgrammingLesson[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<Filter>("active");
  const [search, setSearch] = useState("");
  const [stage, setStage] = useState<Stage>("all");
  const [view, setView] = useState<"rules" | "progress">("rules");
  const [trend, setTrend] = useState<QualityPoint[] | null>(null);

  function showProgress() {
    setView("progress");
    if (trend === null) {
      getQualityTrend()
        .then(setTrend)
        .catch((reason: Error) => setError(reason.message));
    }
  }
  const [busy, setBusy] = useState("");
  const dialog = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listProgrammingLessons()
      .then(setLessons)
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
    dialog.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function toggle(lesson: ProgrammingLesson) {
    const next = lesson.status === "active" ? "disabled" : "active";
    setBusy(lesson.id);
    setError("");
    try {
      await setProgrammingLessonStatus(lesson.id, next);
      setLessons((current) => current.map((item) => (item.id === lesson.id ? { ...item, status: next } : item)));
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy("");
    }
  }

  const shown = visibleLessons(lessons, filter, search, stage);
  const active = lessons.filter((lesson) => lesson.status === "active");
  const confirmations = active.reduce((sum, lesson) => sum + lesson.support, 0);

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-3 sm:p-6" onClick={onClose}>
      <div
        aria-labelledby="lessons-title"
        aria-modal="true"
        className="flex max-h-[calc(100dvh-1.5rem)] w-full max-w-3xl flex-col overflow-hidden rounded-xl border border-line bg-surface shadow-xl outline-none sm:max-h-[calc(100dvh-3rem)]"
        onClick={(event) => event.stopPropagation()}
        ref={dialog}
        role="dialog"
        tabIndex={-1}
      >
        <header className="flex shrink-0 items-start gap-3 border-b border-line px-5 py-4">
          <GraduationCap aria-hidden className="mt-0.5 h-5 w-5 text-accent" />
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-semibold" id="lessons-title">Learned rules</h2>
            <p className="mt-0.5 text-sm text-muted">
              Rules come from two places: the importer's own fixes when a part of a file was misread and then read
              correctly, and the changes people make to the wording, answer lists, or logic before programming the survey
              in Decipher. Later questionnaires are read, planned, and reviewed with the rules that fit them. Switch off a
              rule that is wrong.
            </p>
          </div>
          <IconButton label="Close learned rules" onClick={onClose}>
            <X className="h-4 w-4" />
          </IconButton>
        </header>
        <div className="flex shrink-0 gap-1 border-b border-line px-5 pt-3" role="tablist">
          {(["rules", "progress"] as const).map((tab) => (
            <button
              aria-selected={view === tab}
              className={
                view === tab
                  ? "rounded-t-md border border-b-0 border-line bg-surface px-3 py-1.5 text-sm font-medium text-ink"
                  : "px-3 py-1.5 text-sm text-ink-2 hover:text-ink"
              }
              key={tab}
              onClick={() => (tab === "progress" ? showProgress() : setView("rules"))}
              role="tab"
              type="button"
            >
              {tab === "rules" ? "Rules" : "Progress"}
            </button>
          ))}
        </div>
        {view === "progress" && <ProgressView error={error} trend={trend} />}
        <div className={view === "progress" ? "hidden" : "flex shrink-0 flex-wrap items-center gap-2 border-b border-line px-5 py-3"}>
          <div className="flex gap-1" role="group" aria-label="Show rules">
            {(["active", "disabled", "all"] as Filter[]).map((value) => (
              <Button
                aria-pressed={filter === value}
                key={value}
                onClick={() => setFilter(value)}
                size="sm"
                variant={filter === value ? "primary" : "secondary"}
              >
                {value === "active" ? "In use" : value === "disabled" ? "Switched off" : "All"}
              </Button>
            ))}
          </div>
          <label className="flex items-center gap-1.5 text-sm text-ink-2">
            Kind
            <select
              aria-label="Kind of rule"
              className="rounded-md border border-line-strong bg-surface px-2 py-1 text-sm text-ink"
              onChange={(event) => setStage(event.target.value as Stage)}
              value={stage}
            >
              <option value="all">All</option>
              <option value="extraction">Reading the file</option>
              <option value="programming">Programming logic</option>
            </select>
          </label>
          <label className="ml-auto flex min-w-0 items-center gap-1.5 rounded-md border border-line-strong bg-surface px-2 py-1 text-sm">
            <Search aria-hidden className="h-3.5 w-3.5 text-muted" />
            <input
              aria-label="Search rules"
              className="w-48 min-w-0 bg-transparent outline-none"
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search rules"
              value={search}
            />
          </label>
        </div>
        <div className={view === "progress" ? "hidden" : "min-h-0 flex-1 overflow-y-auto bg-canvas px-5 py-4"}>
          {error && (
            <p className="mb-3 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger" role="alert">{error}</p>
          )}
          {loading && <p className="text-sm text-muted">Loading rules…</p>}
          {!loading && (
            <p className="mb-3 text-sm text-ink-2">
              {active.length} rule{active.length === 1 ? "" : "s"} in use, confirmed {confirmations} time
              {confirmations === 1 ? "" : "s"} in total.
            </p>
          )}
          {!loading && lessons.length === 0 && (
            <p className="rounded-md border border-line bg-surface px-3 py-3 text-sm text-ink-2">
              No rules yet. They appear after someone corrects a questionnaire&apos;s planned logic and programs it in Decipher.
            </p>
          )}
          {!loading && lessons.length > 0 && shown.length === 0 && (
            <p className="text-sm text-muted">No rules match.</p>
          )}
          <ul className="space-y-3">
            {shown.map((lesson) => (
              <li className="rounded-lg border border-line bg-surface p-4 shadow-xs" key={lesson.id}>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={lesson.status === "active" ? "success" : "neutral"}>
                    {lesson.status === "active" ? "In use" : "Switched off"}
                  </Badge>
                  <Badge tone="accent">Confirmed {lesson.support}×</Badge>
                  <Badge tone="neutral">{STAGE_LABEL[lesson.stage ?? "programming"]}</Badge>
                  {lesson.question_type && <span className="text-xs text-muted">{lesson.question_type.replace("_", " ")}</span>}
                  <span className="text-xs text-muted">{lesson.field}</span>
                  <Button
                    className="ml-auto"
                    disabled={busy === lesson.id}
                    onClick={() => toggle(lesson)}
                    size="sm"
                    variant="secondary"
                  >
                    {lesson.status === "active" ? "Switch off" : "Switch on"}
                  </Button>
                </div>
                <p className="mt-2 text-sm text-ink">{lesson.rule}</p>
                {lesson.example_instruction && (
                  <p className="mt-2 text-xs text-ink-2">
                    <span className="font-medium">
                      {lesson.stage === "extraction" ? "Learned from this part of a file:" : "Learned from the instruction:"}
                    </span> “{lesson.example_instruction}”
                  </p>
                )}
                <dl className="mt-1 grid grid-cols-[6rem_minmax(0,1fr)] gap-x-2 text-xs">
                  <dt className="text-muted">{lesson.stage === "extraction" ? "Read as" : "Planned"}</dt>
                  <dd className="break-words font-mono text-ink-2">{shortValue(lesson.example_before?.value)}</dd>
                  <dt className="text-muted">Corrected to</dt>
                  <dd className="break-words font-mono text-ink">{shortValue(lesson.example_after?.value)}</dd>
                </dl>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

function ProgressView({ trend, error }: { trend: QualityPoint[] | null; error: string }) {
  if (error) return <p className="m-5 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger" role="alert">{error}</p>;
  if (trend === null) return <p className="px-5 py-4 text-sm text-muted">Loading progress…</p>;
  const summaries = trendSummaries(trend);
  return (
    <div className="min-h-0 flex-1 overflow-y-auto bg-canvas px-5 py-4 text-sm">
      <p className="text-ink-2">
        Lower is better. Each import counts the parts of the file that had to be re-read; each approval counts what people
        changed before programming. Recent is the last 5 surveys; earlier is everything before them.
      </p>
      <table className="mt-3 w-full border-collapse">
        <thead>
          <tr className="text-left text-xs text-muted">
            <th className="py-1 pr-3 font-medium">Measure</th>
            <th className="py-1 pr-3 text-right font-medium">Earlier</th>
            <th className="py-1 pr-3 text-right font-medium">Recent</th>
            <th className="py-1 text-right font-medium">Surveys</th>
          </tr>
        </thead>
        <tbody>
          {summaries.map((row) => (
            <tr className="border-t border-line" key={row.label}>
              <td className="py-1.5 pr-3 text-ink">{row.label}</td>
              <td className="py-1.5 pr-3 text-right tabular-nums text-ink-2">{formatRate(row.earlier)}</td>
              <td className="py-1.5 pr-3 text-right tabular-nums text-ink">{formatRate(row.recent)}</td>
              <td className="py-1.5 text-right tabular-nums text-ink-2">{row.count}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h3 className="mb-2 mt-5 text-[11px] font-semibold uppercase tracking-wider text-muted">Surveys</h3>
      {trend.length === 0 ? (
        <p className="text-ink-2">Nothing measured yet. Imports and approvals appear here.</p>
      ) : (
        <ul className="space-y-1">
          {[...trend].reverse().map((point, index) => (
            <li className="flex flex-wrap gap-x-3 rounded border border-line bg-surface px-3 py-1.5" key={`${point.created_at}-${index}`}>
              <span className="text-muted">{point.created_at.slice(0, 10)}</span>
              <span className="font-medium text-ink">{point.title || point.project}</span>
              <span className="text-ink-2">
                {point.kind === "import_quality"
                  ? `imported: ${point.reread_parts ?? 0} part(s) re-read, ${point.lessons_used ?? 0} rule(s) available`
                  : `approved: ${point.extraction ?? 0} reading and ${point.programming ?? 0} logic correction(s)`}
              </span>
              <span className="ml-auto text-muted">{point.questions ?? 0} questions</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
