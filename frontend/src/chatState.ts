/** Chat wait and panel selection. Components and tests share these functions. */

export const TASK_WAIT_MS = 5 * 60 * 1000;
export const TASK_POLL_MS = 1000;

const TERMINAL = new Set([
  "completed",
  "completed_with_warnings",
  "failed",
  "cancelled",
  "clarification_needed",
]);

export type PanelArtifact = {
  id: string;
  type: string;
  latest: { version: number } | null;
};

export function isTerminalStatus(status: string): boolean {
  return TERMINAL.has(status);
}

export function stillWaiting(startedAt: number, now: number, status: string): boolean {
  return !isTerminalStatus(status) && now - startedAt < TASK_WAIT_MS;
}

export type TaskStage = {
  sequence: number;
  event_type: string;
  message: string;
};

export type ActivityStep = {
  message: string;
  active: boolean;
};

export function activitySteps(events: TaskStage[], status: string): ActivityStep[] {
  const ordered = [...events].sort((left, right) => left.sequence - right.sequence);
  const messages: string[] = [];
  for (const event of ordered) {
    const message = event.message.trim();
    if (!message || messages.includes(message)) continue;
    messages.push(message);
  }
  if (messages.length === 0) {
    return [{ message: "Reading the request", active: !isTerminalStatus(status) }];
  }
  const finished = isTerminalStatus(status);
  return messages.map((message, index) => ({
    message,
    active: !finished && index === messages.length - 1,
  }));
}

export function formatElapsed(milliseconds: number): string {
  const total = Math.max(0, Math.floor(milliseconds / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

export function artifactToShow<T extends PanelArtifact>(previous: T[], next: T[]): T | null {
  const changed = next.filter((item) => {
    const before = previous.find((candidate) => candidate.id === item.id);
    return !before || before.latest?.version !== item.latest?.version;
  });
  return (
    changed.find((item) => item.type === "decipher_survey") ??
    changed.find((item) => item.type === "questionnaire") ??
    changed[0] ??
    null
  );
}
