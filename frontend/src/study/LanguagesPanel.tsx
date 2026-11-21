import { useCallback, useEffect, useMemo, useState } from "react";
import { downloadUrl } from "../api";
import {
  addLanguage,
  approveLanguage,
  editSegment,
  exportLanguage,
  getLanguage,
  type LanguageDetail,
  type LanguageSummary,
  listLanguages,
  translateMissing,
} from "../studyApi";
import { Badge, Button, cn } from "../ui";

const STATUS: Record<LanguageSummary["status"], { label: string; tone: "success" | "warn" | "neutral" }> = {
  approved: { label: "Signed off", tone: "success" },
  needs_review: { label: "Needs review", tone: "warn" },
  draft: { label: "Draft", tone: "neutral" },
};

/** Questionnaire languages: add, translate, review segment by segment, sign off, export. */
export function LanguagesPanel({ projectId }: { projectId: string }) {
  const [languages, setLanguages] = useState<LanguageSummary[] | null>(null);
  const [openId, setOpenId] = useState("");
  const [detail, setDetail] = useState<LanguageDetail | null>(null);
  const [language, setLanguage] = useState("");
  const [notes, setNotes] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [filter, setFilter] = useState<"todo" | "all">("all");
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const next = await listLanguages(projectId);
      setLanguages(next.languages);
      setError("");
    } catch (reason) {
      setLanguages([]);
      setError(reason instanceof Error ? reason.message : "Languages could not be loaded.");
    }
  }, [projectId]);

  useEffect(() => {
    setOpenId("");
    setDetail(null);
    setMessage("");
    void load();
  }, [load]);

  useEffect(() => {
    if (!openId) return;
    let live = true;
    getLanguage(projectId, openId)
      .then((next) => live && setDetail(next))
      .catch((reason: Error) => live && setError(reason.message));
    return () => {
      live = false;
    };
  }, [projectId, openId]);

  async function act(kind: string, work: () => Promise<void>) {
    setBusy(kind);
    setError("");
    setMessage("");
    try {
      await work();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "That did not work.");
    } finally {
      setBusy("");
    }
  }

  const segments = useMemo(
    () => (detail?.segments ?? []).filter((segment) => filter === "all" || segment.state !== "ok"),
    [detail, filter],
  );

  return (
    <section aria-label="Languages" className="space-y-4 text-sm">
      <p className="text-ink-2">
        Translate what respondents see (wording, answers, grid rows). Programmer notes stay in English. A reviewer checks
        each language and signs it off; if the questionnaire changes later, the changed text is translated again and the
        language needs a new sign-off.
      </p>
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-surface p-3">
        <input
          aria-label="Language and market"
          className="h-7 w-48 rounded-md border border-line-strong bg-surface px-2 text-xs"
          onChange={(event) => setLanguage(event.target.value)}
          placeholder="Language (market), e.g. German (Germany)"
          value={language}
        />
        <input
          aria-label="Translator notes"
          className="h-7 min-w-0 flex-1 rounded-md border border-line-strong bg-surface px-2 text-xs"
          onChange={(event) => setNotes(event.target.value)}
          placeholder="Notes for the translator (formal 'Sie', keep brand names…)"
          value={notes}
        />
        <Button
          disabled={!!busy || language.trim().length < 2}
          onClick={() =>
            void act("add", async () => {
              const added = await addLanguage(projectId, language, notes);
              setMessage(added.summary);
              setLanguage("");
              setNotes("");
              await load();
              setOpenId(added.artifact_id);
            })
          }
          size="sm"
          variant="primary"
        >
          {busy === "add" ? "Translating…" : "Add and translate"}
        </Button>
      </div>
      {message && <p className="text-accent" role="status">{message}</p>}
      {error && <p className="text-danger" role="alert">{error}</p>}
      {languages && languages.length === 0 && !error && <p className="text-muted">No languages yet.</p>}
      <ul className="space-y-2">
        {(languages ?? []).map((item) => (
          <li className="rounded-lg border border-line bg-surface" key={item.artifact_id}>
            <button
              aria-expanded={openId === item.artifact_id}
              className="flex w-full flex-wrap items-center gap-2 px-3 py-2 text-left"
              onClick={() => {
                setDetail(null);
                setOpenId(openId === item.artifact_id ? "" : item.artifact_id);
              }}
              type="button"
            >
              <span className="font-medium text-ink">{item.language}</span>
              <Badge tone={STATUS[item.status].tone}>{STATUS[item.status].label}</Badge>
              <span className="text-xs text-muted">
                {item.total - item.missing - item.source_changed}/{item.total} translated
                {item.source_changed ? ` · ${item.source_changed} source changed` : ""}
                {item.edited ? ` · ${item.edited} edited by a reviewer` : ""}
                {item.status === "approved" && item.approved_by ? ` · signed off by ${item.approved_by}` : ""}
              </span>
            </button>
            {openId === item.artifact_id && detail && (
              <div className="space-y-2 border-t border-line px-3 py-2">
                <div className="flex flex-wrap items-center gap-2">
                  {(detail.missing > 0 || detail.source_changed > 0) && (
                    <Button
                      disabled={!!busy}
                      onClick={() =>
                        void act("translate", async () => {
                          const done = await translateMissing(projectId, item.artifact_id);
                          setMessage(done.summary);
                          await load();
                          setDetail(await getLanguage(projectId, item.artifact_id));
                        })
                      }
                      size="sm"
                    >
                      {busy === "translate" ? "Translating…" : `Translate ${detail.missing + detail.source_changed} remaining`}
                    </Button>
                  )}
                  {(["docx", "pdf", "xml"] as const).map((kind) => (
                    <Button
                      disabled={!!busy}
                      key={kind}
                      onClick={() =>
                        void act("export", async () => {
                          const file = await exportLanguage(projectId, item.artifact_id, kind);
                          setMessage(file.warning || `${file.filename} is ready.`);
                          window.location.assign(downloadUrl(file.file_id));
                        })
                      }
                      size="sm"
                      variant="ghost"
                    >
                      {kind === "xml" ? "Survey XML" : kind.toUpperCase()}
                    </Button>
                  ))}
                  <span className="ml-auto flex items-center gap-1.5">
                    <input
                      aria-label="Reviewer name"
                      className="h-7 w-36 rounded-md border border-line-strong bg-surface px-2 text-xs"
                      onChange={(event) => setReviewer(event.target.value)}
                      placeholder="Reviewer name"
                      value={reviewer}
                    />
                    <Button
                      disabled={!!busy || !reviewer.trim() || detail.missing + detail.source_changed > 0}
                      onClick={() =>
                        void act("approve", async () => {
                          setDetail(await approveLanguage(projectId, item.artifact_id, reviewer));
                          setMessage(`${item.language} is signed off.`);
                          await load();
                        })
                      }
                      size="sm"
                      variant="primary"
                    >
                      Sign off
                    </Button>
                  </span>
                </div>
                <div aria-label="Which segments" className="flex gap-1" role="tablist">
                  {(["todo", "all"] as const).map((value) => (
                    <button
                      aria-selected={filter === value}
                      className={cn("rounded-md px-2 py-0.5 text-xs", filter === value ? "bg-sunken text-ink" : "text-muted")}
                      key={value}
                      onClick={() => setFilter(value)}
                      role="tab"
                      type="button"
                    >
                      {value === "todo" ? `Needs translation (${detail.missing + detail.source_changed})` : `All (${detail.segments.length})`}
                    </button>
                  ))}
                </div>
                <ul className="divide-y divide-line">
                  {segments.map((segment) => (
                    <SegmentRow
                      disabled={!!busy}
                      key={segment.key}
                      onSave={(text) =>
                        act("edit", async () => {
                          setDetail(await editSegment(projectId, item.artifact_id, segment.key, text));
                          await load();
                        })
                      }
                      segment={segment}
                    />
                  ))}
                  {segments.length === 0 && <li className="py-3 text-center text-xs text-muted">Every segment is translated.</li>}
                </ul>
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function SegmentRow({
  segment,
  disabled,
  onSave,
}: {
  segment: LanguageDetail["segments"][number];
  disabled: boolean;
  onSave: (text: string) => Promise<void>;
}) {
  const [text, setText] = useState(segment.text);
  useEffect(() => setText(segment.text), [segment.text]);
  const changed = text.trim() !== segment.text.trim();
  return (
    <li className="grid gap-2 py-2 sm:grid-cols-2">
      <div>
        <p className="font-mono text-[11px] text-muted">
          {segment.key}
          {segment.state === "source_changed" && <span className="ml-1 text-warn">· source changed</span>}
          {segment.state === "missing" && <span className="ml-1 text-warn">· not translated</span>}
          {segment.origin === "edited" && <span className="ml-1">· edited</span>}
        </p>
        <p className="text-ink">{segment.source}</p>
      </div>
      <div className="flex items-start gap-1">
        <textarea
          aria-label={`Translation of ${segment.key}`}
          className="min-h-[2.25rem] flex-1 rounded-md border border-line-strong bg-surface px-2 py-1 text-xs"
          onChange={(event) => setText(event.target.value)}
          rows={Math.min(4, Math.max(1, Math.ceil(text.length / 60)))}
          value={text}
        />
        {changed && (
          <Button disabled={disabled || !text.trim()} onClick={() => void onSave(text)} size="sm">
            Save
          </Button>
        )}
      </div>
    </li>
  );
}
