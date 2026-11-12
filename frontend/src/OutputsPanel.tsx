import { clsx } from "clsx";
import {
  BarChart3,
  ClipboardList,
  Code2,
  Database,
  Download as DownloadIcon,
  FileText,
  Layers,
  MessageSquareText,
  Search,
  Sheet,
  ShieldCheck,
  StickyNote,
  Table2,
  Tags,
  TrendingUp,
  Users,
  type LucideIcon,
} from "lucide-react";
import { useState } from "react";
import { exportQuestionnaire, exportTabspec, saveDownload, type Artifact } from "./api";
import { artifactDownloads, groupOutputs, matchesQuery, outputMeta, outputStatus, runNumbers, type Download } from "./outputs";
import { Badge } from "./ui";

const ICONS: Record<string, LucideIcon> = {
  questionnaire: ClipboardList,
  decipher_survey: Code2,
  sample_purchase: Users,
  cleaning: ShieldCheck,
  synthetic_data: Database,
  tabspec: Sheet,
  crosstab: Table2,
  analysis: TrendingUp,
  chart: BarChart3,
  codeframe: Tags,
  coding: MessageSquareText,
  note: StickyNote,
};

export function ArtifactIcon({ type, className }: { type: string; className?: string }) {
  const Icon = ICONS[type] ?? FileText;
  return <Icon aria-hidden className={className} />;
}

/** Run one download: a stored file, or an export built from the latest content. */
export async function runDownload(download: Download, projectId: string, artifact: Artifact): Promise<void> {
  if (download.kind === "file") {
    saveDownload(download.fileId);
    return;
  }
  if (download.exporter === "tabspec") {
    const exported = await exportTabspec(projectId, artifact.latest?.content ?? {});
    saveDownload(exported.file_id);
    return;
  }
  const exported = await exportQuestionnaire(projectId, download.exporter);
  saveDownload(exported.file_id);
}

export function OutputsPanel({
  artifacts,
  projectId,
  openId,
  onOpen,
  onError,
}: {
  artifacts: Artifact[];
  projectId: string;
  openId: string | null;
  onOpen: (artifact: Artifact) => void;
  onError: (message: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const groups = groupOutputs(artifacts.filter((item) => matchesQuery(item, query)));
  const runs = runNumbers(artifacts);

  async function download(item: Artifact, entry: Download) {
    const key = `${item.id}:${entry.label}`;
    setPending(key);
    try {
      await runDownload(entry, projectId, item);
    } catch (error) {
      onError(error instanceof Error ? error.message : "The download failed.");
    } finally {
      setPending(null);
    }
  }

  if (artifacts.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
        <span className="flex h-12 w-12 items-center justify-center rounded-full bg-accent-soft text-accent">
          <Layers aria-hidden className="h-6 w-6" />
        </span>
        <p className="text-sm font-medium text-ink">No outputs yet</p>
        <p className="max-w-xs text-sm text-muted">
          Ask an agent for a questionnaire, a tab spec, a crosstab, a cleaning check or a sample quote. Each result appears here.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-5 p-4">
      {artifacts.length > 4 && (
        <div className="relative">
          <Search aria-hidden className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
          <input
            aria-label="Filter outputs"
            className="h-9 w-full rounded-md border border-line-strong bg-surface pl-8 pr-3 text-sm placeholder:text-muted"
            placeholder="Filter outputs"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
      )}
      {groups.length === 0 && <p className="text-sm text-muted">No outputs match “{query}”.</p>}
      {groups.map((group) => (
        <section key={group.id} aria-labelledby={`stage-${group.id}`}>
          <h3 id={`stage-${group.id}`} className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-muted">
            {group.label}
            <span className="font-normal normal-case tracking-normal">· {group.items.length}</span>
          </h3>
          <ul className="space-y-1.5">
            {group.items.map((item) => {
              const status = outputStatus(item);
              const downloads = artifactDownloads(item);
              const selected = item.id === openId;
              const run = runs.get(item.id);
              return (
                <li
                  key={item.id}
                  className={clsx(
                    "relative flex items-center gap-3 rounded-lg border bg-surface px-3 py-2.5 shadow-xs transition-colors",
                    selected ? "border-accent ring-1 ring-accent" : "border-line hover:border-line-strong hover:bg-sunken/50",
                  )}
                >
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-accent-soft text-accent">
                    <ArtifactIcon type={item.type} className="h-4 w-4" />
                  </span>
                  <div className="min-w-0 flex-1">
                    {/* The title button stretches over the whole card; downloads sit above it. */}
                    <button
                      aria-current={selected ? "true" : undefined}
                      className="block w-full truncate text-left text-sm font-medium text-ink after:absolute after:inset-0 after:rounded-lg after:content-['']"
                      onClick={() => onOpen(item)}
                      title={item.name}
                      type="button"
                    >
                      {item.name || outputMeta(item)}
                    </button>
                    <p className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-muted">
                      <span>
                        {outputMeta(item)}
                        {run ? ` · run ${run.run} of ${run.of}` : ""}
                      </span>
                      {run?.latest && <Badge tone="accent">Latest</Badge>}
                      {status && <Badge tone={status.tone}>{status.label}</Badge>}
                      {item.latest?.stale && <Badge tone="warn">Stale</Badge>}
                    </p>
                  </div>
                  {downloads.length > 0 && (
                    <div className="relative z-10 flex shrink-0 flex-wrap justify-end gap-1">
                      {downloads.map((entry) => {
                        const key = `${item.id}:${entry.label}`;
                        return (
                          <button
                            key={key}
                            aria-label={`Download ${entry.label} for ${item.name}`}
                            className="inline-flex h-7 items-center gap-1 rounded-md border border-line px-2 text-xs font-medium text-ink-2 hover:border-accent hover:text-accent disabled:opacity-50"
                            disabled={pending === key}
                            onClick={() => void download(item, entry)}
                            title={`Download ${entry.label}`}
                            type="button"
                          >
                            <DownloadIcon aria-hidden className="h-3 w-3" />
                            {pending === key ? "…" : entry.label}
                          </button>
                        );
                      })}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}
