import type { ActivityStep } from "./chatState";

export function TaskActivity({
  steps,
  elapsedLabel,
}: {
  steps: ActivityStep[];
  elapsedLabel: string;
}) {
  const active = steps.find((step) => step.active);
  return (
    <section aria-live="polite" className="max-w-[85%] rounded-2xl rounded-bl-md border border-line bg-surface p-4 shadow-xs">
      <p className="text-sm font-medium text-ink">Working</p>
      <ol className="mt-3 space-y-2">
        {steps.map((step) => (
          <li key={step.message} className="flex items-start gap-2 text-sm text-ink">
            {step.active ? (
              <span aria-hidden className="mt-1.5 h-2 w-2 shrink-0 animate-pulse rounded-full bg-accent" />
            ) : (
              <span aria-hidden className="mt-0.5 text-accent">✓</span>
            )}
            <span>
              {step.active ? <span className="sr-only">Current step. </span> : <span className="sr-only">Done. </span>}
              {step.message}
            </span>
          </li>
        ))}
      </ol>
      {active && <p className="mt-3 text-xs text-muted">This stage · {elapsedLabel}</p>}
    </section>
  );
}
