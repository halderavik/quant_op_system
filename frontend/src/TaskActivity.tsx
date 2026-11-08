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
    <section aria-live="polite" className="mr-8 rounded-lg border border-stone-200 bg-white p-4 shadow-sm">
      <p className="text-sm font-medium text-stone-900">Working</p>
      <ol className="mt-3 space-y-2">
        {steps.map((step) => (
          <li key={step.message} className="flex items-start gap-2 text-sm text-stone-800">
            {step.active ? (
              <span aria-hidden className="mt-1.5 h-2 w-2 shrink-0 animate-pulse rounded-full bg-teal-800" />
            ) : (
              <span aria-hidden className="mt-0.5 text-teal-800">✓</span>
            )}
            <span>
              {step.active ? <span className="sr-only">Current step. </span> : <span className="sr-only">Done. </span>}
              {step.message}
            </span>
          </li>
        ))}
      </ol>
      {active && <p className="mt-3 text-xs text-stone-500">This stage · {elapsedLabel}</p>}
    </section>
  );
}
