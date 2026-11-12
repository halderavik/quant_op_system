import { useEffect, useMemo, useRef, useState } from "react";
import { previewStep } from "../api";
import { ScreenBody } from "./SurveyFields";
import {
  answerHint,
  answerReady,
  emptyAnswer,
  shuffleRows,
  toPayload,
  type PreviewAnswer,
  type PreviewScreen,
} from "./surveyPreview";

type Frame = { screen: PreviewScreen; answer: PreviewAnswer };

export function SurveyPreview({
  projectId,
  xml,
  title,
  stale,
  issues,
  onClose,
}: {
  projectId: string;
  xml: string;
  title: string;
  stale: boolean;
  issues: string[];
  onClose: () => void;
}) {
  const [screen, setScreen] = useState<PreviewScreen | null>(null);
  const [answer, setAnswer] = useState<PreviewAnswer>(emptyAnswer());
  const [stack, setStack] = useState<Frame[]>([]);
  const [busy, setBusy] = useState(false);
  const [fault, setFault] = useState("");
  const [session, setSession] = useState(0);
  const order = useRef(new Map<string, PreviewScreen["rows"]>());
  const dialog = useRef<HTMLDivElement>(null);

  useEffect(() => {
    dialog.current?.focus();
  }, []);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    if (issues.length > 0) return;
    let cancelled = false;
    setBusy(true);
    previewStep(projectId, xml, {}, null)
      .then((next) => {
        if (cancelled) return;
        setScreen(next);
        setAnswer(emptyAnswer());
        setStack([]);
        setFault("");
      })
      .catch((reason: Error) => {
        if (!cancelled) setFault(reason.message);
      })
      .finally(() => {
        if (!cancelled) setBusy(false);
      });
    return () => {
      cancelled = true;
    };
  }, [issues.length, projectId, session, xml]);

  const rows = useMemo(() => {
    if (!screen?.shuffle || !screen.label) return screen?.rows ?? [];
    const cached = order.current.get(screen.label);
    if (cached) return cached;
    const shuffled = shuffleRows(screen.rows, Math.random);
    order.current.set(screen.label, shuffled);
    return shuffled;
  }, [screen]);

  async function next() {
    if (!screen?.label || !answerReady(screen, answer)) return;
    const prior = Object.fromEntries(
      stack.flatMap((frame) => (frame.screen.label ? [[frame.screen.label, toPayload(frame.answer)]] : [])),
    );
    setBusy(true);
    setFault("");
    try {
      const following = await previewStep(
        projectId,
        xml,
        { ...prior, [screen.label]: toPayload(answer) },
        screen.label,
      );
      setStack((current) => [...current, { screen, answer }]);
      setScreen(following);
      setAnswer(emptyAnswer());
    } catch (reason) {
      setFault(reason instanceof Error ? reason.message : "The preview could not continue.");
    } finally {
      setBusy(false);
    }
  }

  function back() {
    const previous = stack[stack.length - 1];
    if (!previous) return;
    setStack((current) => current.slice(0, -1));
    setScreen(previous.screen);
    setAnswer(previous.answer);
    setFault("");
  }

  function restart() {
    setStack([]);
    setAnswer(emptyAnswer());
    setScreen(null);
    setFault("");
    setSession((current) => current + 1);
  }

  const hint = screen ? answerHint(screen, answer) : "";
  const canNext = screen?.status === "question" && answerReady(screen, answer) && !busy;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="survey-preview-title"
        tabIndex={-1}
        className="max-h-[90vh] w-full max-w-xl overflow-auto rounded-lg bg-surface p-6 shadow-lg outline-none"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <p id="survey-preview-title" className="text-xs font-medium uppercase tracking-wide text-muted">
              Survey preview
            </p>
            {title && <h2 className="text-lg font-semibold text-ink">{title}</h2>}
          </div>
          <button className="text-sm underline" onClick={onClose} type="button">
            Close
          </button>
        </div>
        {stale && (
          <p className="mt-3 rounded border border-warn-line bg-warn-soft px-3 py-2 text-sm text-warn">
            This preview is the programmed file. The questionnaire has changed since.
          </p>
        )}
        {issues.length > 0 ? (
          <ul className="mt-4 list-disc space-y-1 pl-5 text-sm text-warn">
            {issues.map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
        ) : (
          <div className="mt-4">
            {screen?.status === "question" && (
              <p className="text-xs uppercase text-muted">Question {stack.length + 1}</p>
            )}
            {!screen && !fault && <p className="text-sm text-ink-2">Opening the survey…</p>}
            {screen && <ScreenBody answer={answer} rows={rows} screen={screen} setAnswer={setAnswer} />}
            {hint && <p className="mt-3 text-sm text-ink-2">{hint}</p>}
            {fault && <p className="mt-3 text-sm text-danger">{fault}</p>}
            <div className="mt-6 flex flex-wrap gap-2">
              <button
                className="rounded border border-line-strong bg-surface px-3 py-1.5 text-sm disabled:opacity-50"
                disabled={stack.length === 0 || busy}
                onClick={back}
                type="button"
              >
                Back
              </button>
              <button
                className="rounded border border-line-strong bg-surface px-3 py-1.5 text-sm disabled:opacity-50"
                disabled={busy || issues.length > 0}
                onClick={restart}
                type="button"
              >
                Restart
              </button>
              {screen?.status === "question" && (
                <button
                  className="rounded bg-accent px-3 py-1.5 text-sm text-on-accent disabled:opacity-50"
                  disabled={!canNext}
                  onClick={() => void next()}
                  type="button"
                >
                  {screen.element === "html" || screen.element === "loop" ? "Continue" : "Next"}
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
