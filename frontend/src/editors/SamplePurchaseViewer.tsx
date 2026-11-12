import { useState } from "react";
import { launchSample, refreshSample, repriceSample, transitionSample } from "../api";
import { formatMoney, quotaCellLabel, type QuotaCell } from "./sampleQuote";

type FilterRow = {
  filter_id?: string;
  label?: string;
  kind?: string;
  selected_values?: string[];
  choice_labels?: Record<string, string>;
  lower?: number | null;
  upper?: number | null;
  weightings?: Record<string, number>;
  age_bands?: { lower: number; upper: number; weighting: number }[];
};

export function SamplePurchaseViewer({
  projectId,
  content,
  onChanged,
}: {
  projectId: string;
  content: Record<string, unknown>;
  onChanged: (artifactId: string) => Promise<void>;
}) {
  const purchase = readPurchase(content);
  const stamp = `${purchase.sampleSize}|${purchase.minutes}|${purchase.rewardCents}|${JSON.stringify(content.filters ?? [])}`;
  const [sampleSize, setSampleSize] = useState(String(purchase.sampleSize));
  const [minutes, setMinutes] = useState(String(purchase.minutes));
  const [reward, setReward] = useState((purchase.rewardCents / 100).toFixed(2));
  const [filters, setFilters] = useState(purchase.filters);
  const [stampSeen, setStampSeen] = useState(stamp);
  const [confirming, setConfirming] = useState(false);
  const [message, setMessage] = useState("");
  const [working, setWorking] = useState(false);
  if (stamp !== stampSeen) {
    setStampSeen(stamp);
    setSampleSize(String(purchase.sampleSize));
    setMinutes(String(purchase.minutes));
    setReward((purchase.rewardCents / 100).toFixed(2));
    setFilters(purchase.filters);
  }
  const total = formatMoney(purchase.totalCents, purchase.currency);
  const canLaunch = purchase.status === "quoted" || purchase.status === "draft";
  const blocked = purchase.blockers.length > 0 || !canLaunch;

  async function run(action: () => Promise<{ artifact_id: string; summary?: string }>) {
    setWorking(true);
    setMessage("");
    try {
      const result = await action();
      setMessage(result.summary ?? "");
      setConfirming(false);
      await onChanged(result.artifact_id);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "The sample request failed.");
    } finally {
      setWorking(false);
    }
  }

  function editBody() {
    return {
      sample_size: Number(sampleSize),
      estimated_minutes: Number(minutes),
      reward_cents: Math.round(Number(reward) * 100),
      filters,
      study_type: purchase.studyType,
      devices: purchase.devices,
    };
  }

  return (
    <div className="space-y-4 text-sm">
      <p>
        {purchase.provider === "prolific" ? "Prolific" : purchase.provider} · {purchase.status}
        {purchase.studyId ? ` · ${purchase.studyId}` : ""}
      </p>
      <p className="text-2xl font-semibold text-ink">{total}</p>
      <p>
        {formatMoney(purchase.participantPay, purchase.currency)} participant pay for {purchase.sampleSize}{" "}
        completions. Fees and VAT are included in the total.
      </p>
      {purchase.fees !== null && (
        <p>
          Rewards {formatMoney(purchase.rewards ?? 0, purchase.currency)}, fees{" "}
          {formatMoney(purchase.fees, purchase.currency)}, tax {formatMoney(purchase.tax ?? 0, purchase.currency)}.
        </p>
      )}
      <p>
        {formatMoney(purchase.rewardCents, purchase.currency)} each · {purchase.minutes} minutes
        {purchase.minutesEstimated ? " (estimated from the question count)" : ""} ·{" "}
        {formatMoney(purchase.hourly, purchase.currency)} per hour. Minimum{" "}
        {formatMoney(purchase.minimumHourly, purchase.currency)} per hour.
      </p>
      <p>
        Eligible participants: {purchase.eligible === 0 ? "fewer than 5" : purchase.eligible.toLocaleString()}
        {purchase.eligibleNote ? `. ${purchase.eligibleNote}` : ""}
      </p>
      {purchase.balance !== null && (
        <p>
          {purchase.shortfall
            ? `Available balance ${formatMoney(purchase.balance, purchase.currency)}. Shortfall ${formatMoney(purchase.shortfall, purchase.currency)}.`
            : `Available balance ${formatMoney(purchase.balance, purchase.currency)}.`}
        </p>
      )}
      <section>
        <h3 className="font-medium">Audience</h3>
        {purchase.studyType && <p>Representative sample: {purchase.studyType}</p>}
        <ul className="list-disc pl-5">
          {purchase.filters.map((filter) => (
            <li key={filter.filter_id}>
              {filter.label}: {filterSummary(filter)}
            </li>
          ))}
        </ul>
        {purchase.studyTypeNote && <p>{purchase.studyTypeNote}</p>}
      </section>
      <section>
        <h3 className="font-medium">Quotas</h3>
        <ul className="list-disc pl-5">
          {purchase.cells.map((cell) => (
            <li key={quotaCellLabel(cell)}>{quotaCellLabel(cell)}</li>
          ))}
        </ul>
        {filters.map((filter) => (
          <QuotaWeights key={filter.filter_id} filter={filter} onChange={setFilters} />
        ))}
        <p>{purchase.screenoutNote}</p>
      </section>
      {purchase.counts.length > 0 && (
        <p>Submissions: {purchase.counts.map(([name, count]) => `${name} ${count}`).join(", ")}</p>
      )}
      {purchase.blockers.map((blocker) => (
        <p key={blocker}>{blocker}</p>
      ))}
      {purchase.warnings.map((warning) => (
        <p key={warning}>{warning}</p>
      ))}
      <div className="flex flex-wrap gap-2">
        <label>
          Sample size
          <input
            className="ml-2 w-24 rounded border border-line-strong px-2 py-1"
            value={sampleSize}
            onChange={(event) => setSampleSize(event.target.value)}
          />
        </label>
        <label>
          Minutes
          <input
            className="ml-2 w-20 rounded border border-line-strong px-2 py-1"
            value={minutes}
            onChange={(event) => setMinutes(event.target.value)}
          />
        </label>
        <label>
          Reward
          <input
            className="ml-2 w-24 rounded border border-line-strong px-2 py-1"
            value={reward}
            onChange={(event) => setReward(event.target.value)}
          />
        </label>
        <button
          className="rounded border border-line-strong bg-surface px-3 py-1.5"
          disabled={working}
          onClick={() => void run(() => repriceSample(projectId, editBody()))}
          type="button"
        >
          Recalculate
        </button>
        <button
          className="rounded border border-line-strong bg-surface px-3 py-1.5"
          disabled={working || !purchase.studyId}
          onClick={() => void run(() => refreshSample(projectId))}
          type="button"
        >
          Refresh
        </button>
        {purchase.status === "active" && (
          <button
            className="rounded border border-line-strong bg-surface px-3 py-1.5"
            disabled={working}
            onClick={() => void run(() => transitionSample(projectId, "PAUSE"))}
            type="button"
          >
            Pause
          </button>
        )}
        {purchase.status === "paused" && (
          <button
            className="rounded border border-line-strong bg-surface px-3 py-1.5"
            disabled={working}
            onClick={() => void run(() => transitionSample(projectId, "START"))}
            type="button"
          >
            Resume
          </button>
        )}
        {purchase.studyId && purchase.status !== "completed" && (
          <button
            className="rounded border border-line-strong bg-surface px-3 py-1.5"
            disabled={working}
            onClick={() => void run(() => transitionSample(projectId, "STOP"))}
            type="button"
          >
            Stop
          </button>
        )}
      </div>
      {!confirming ? (
        <button
          className="rounded bg-accent px-3 py-1.5 text-on-accent disabled:opacity-50"
          disabled={working || blocked}
          onClick={() => setConfirming(true)}
          type="button"
        >
          Launch sample
        </button>
      ) : (
        <div className="space-y-2 rounded border border-line-strong bg-surface p-3">
          <p>Publish this study and lock {total} on Prolific?</p>
          <div className="flex gap-2">
            <button
              className="rounded bg-accent px-3 py-1.5 text-on-accent disabled:opacity-50"
              disabled={working}
              onClick={() =>
                void run(() => launchSample(projectId, purchase.totalCents))
              }
              type="button"
            >
              Publish {total}
            </button>
            <button
              className="rounded border border-line-strong bg-surface px-3 py-1.5"
              disabled={working}
              onClick={() => setConfirming(false)}
              type="button"
            >
              Back
            </button>
          </div>
        </div>
      )}
      {message && <p>{message}</p>}
    </div>
  );
}

function QuotaWeights({
  filter,
  onChange,
}: {
  filter: FilterRow;
  onChange: (update: (current: FilterRow[]) => FilterRow[]) => void;
}) {
  const weights = filter.weightings ?? {};
  const bands = filter.age_bands ?? [];
  if (Object.keys(weights).length === 0 && bands.length === 0) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-2">
      {Object.entries(weights).map(([choiceId, weight]) => (
        <label key={choiceId}>
          {filter.choice_labels?.[choiceId] ?? choiceId} weight
          <input
            className="ml-2 w-16 rounded border border-line-strong px-2 py-1"
            value={weight}
            onChange={(event) => {
              const next = Number(event.target.value);
              if (!Number.isFinite(next)) return;
              onChange((current) =>
                current.map((item) =>
                  item.filter_id === filter.filter_id
                    ? { ...item, weightings: { ...item.weightings, [choiceId]: next } }
                    : item,
                ),
              );
            }}
          />
        </label>
      ))}
      {bands.map((band, index) => (
        <label key={`${band.lower}-${band.upper}`}>
          {band.lower}–{band.upper} weight
          <input
            className="ml-2 w-16 rounded border border-line-strong px-2 py-1"
            value={band.weighting}
            onChange={(event) => {
              const next = Number(event.target.value);
              if (!Number.isFinite(next)) return;
              onChange((current) =>
                current.map((item) => {
                  if (item.filter_id !== filter.filter_id) return item;
                  const ageBands = [...(item.age_bands ?? [])];
                  ageBands[index] = { ...ageBands[index], weighting: next };
                  return { ...item, age_bands: ageBands };
                }),
              );
            }}
          />
        </label>
      ))}
    </div>
  );
}

function filterSummary(filter: FilterRow): string {
  if (filter.kind === "range") {
    const bands = filter.age_bands ?? [];
    if (bands.length > 0) {
      return bands.map((band) => `${band.lower}–${band.upper}`).join(", ");
    }
    return `${filter.lower ?? ""}–${filter.upper ?? ""}`;
  }
  const labels = filter.choice_labels ?? {};
  return (filter.selected_values ?? []).map((value) => labels[value] ?? value).join(", ");
}

function readPurchase(content: Record<string, unknown>) {
  const filters = Array.isArray(content.filters) ? (content.filters as FilterRow[]) : [];
  const cells = Array.isArray(content.quota_cells) ? (content.quota_cells as QuotaCell[]) : [];
  const counts = content.submission_counts;
  return {
    provider: text(content.provider, "prolific"),
    status: text(content.status, "quoted"),
    studyId: text(content.prolific_study_id, ""),
    studyType: typeof content.study_type === "string" ? content.study_type : null,
    studyTypeNote: text(content.study_type_note, ""),
    sampleSize: number(content.sample_size),
    minutes: number(content.estimated_minutes),
    minutesEstimated: content.minutes_estimated === true,
    rewardCents: number(content.reward_cents),
    hourly: number(content.reward_per_hour_cents),
    minimumHourly: number(content.min_reward_per_hour_cents),
    currency: text(content.currency, "USD"),
    participantPay: number(content.participant_pay_cents),
    totalCents: number(content.total_cost_cents),
    fees: optionalNumber(content.fees_cents),
    tax: optionalNumber(content.tax_cents),
    rewards: optionalNumber(content.rewards_cents),
    balance: optionalNumber(content.available_balance_cents),
    shortfall: optionalNumber(content.shortfall_cents),
    eligible: number(content.eligible_count),
    eligibleNote: text(content.eligible_note, ""),
    screenoutNote: text(content.screenout_note, ""),
    devices: Array.isArray(content.devices) ? content.devices.filter((item) => typeof item === "string") : [],
    filters,
    cells,
    blockers: stringList(content.launch_blockers),
    warnings: stringList(content.warnings),
    counts: counts && typeof counts === "object" ? Object.entries(counts as Record<string, number>) : [],
  };
}

function text(value: unknown, fallback: string): string {
  return typeof value === "string" && value ? value : fallback;
}

function number(value: unknown): number {
  return typeof value === "number" ? value : 0;
}

function optionalNumber(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}
