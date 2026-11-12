import { clsx } from "clsx";
import {
  ArrowUp,
  Database,
  Layers,
  Maximize2,
  MessageSquare,
  Minimize2,
  Monitor,
  Moon,
  PanelLeft,
  Paperclip,
  Plus,
  Square,
  Sun,
  X,
} from "lucide-react";
import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent } from "react";
import {
  type Artifact,
  type ChatMessage,
  type Project,
  type TaskStage,
  createProject,
  getDataset,
  listArtifacts,
  listMessages,
  listProjects,
  cancelTask,
  sendMessage,
  taskStatus,
  uploadFile,
} from "./api";
import { ArtifactEditor } from "./Editors";
import { ArtifactIcon, OutputsPanel } from "./OutputsPanel";
import { TaskActivity } from "./TaskActivity";
import { TASK_POLL_MS, activitySteps, artifactToShow, formatElapsed, isTerminalStatus, stillWaiting } from "./chatState";
import { artifactTypeLabel } from "./labels";
import { nudgeWidth } from "./outputs";
import { nextPreference, useTheme, type ThemePreference } from "./theme";
import { Button, IconButton } from "./ui";

type WorkspaceTab = "outputs" | "viewer";
type DatasetInfo = { rows: number; variables: string[] };

const PANEL_MIN = 360;
const PANEL_MAX = 1100;

const THEME_ICON: Record<ThemePreference, typeof Sun> = { system: Monitor, light: Sun, dark: Moon };

export function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [open, setOpen] = useState<Artifact | null>(null);
  const [tab, setTab] = useState<WorkspaceTab>("outputs");
  const [draft, setDraft] = useState("");
  const [name, setName] = useState("Brand Trust Wave 1");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [dataset, setDataset] = useState<DatasetInfo | null>(null);
  const [datasetLoading, setDatasetLoading] = useState(false);
  const projectRef = useRef<string | null>(null);
  const [variableQuery, setVariableQuery] = useState("");
  const [taskId, setTaskId] = useState<string | null>(null);
  const [stages, setStages] = useState<TaskStage[]>([]);
  const [runStatus, setRunStatus] = useState("queued");
  const [stageStarted, setStageStarted] = useState(Date.now());
  const [now, setNow] = useState(Date.now());
  const [panelWidth, setPanelWidth] = useState(560);
  const [railOpen, setRailOpen] = useState(false);
  const [mobileView, setMobileView] = useState<"chat" | "outputs">("chat");
  const [expanded, setExpanded] = useState(false);
  const [theme, setTheme] = useTheme();
  const transcriptEnd = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const steps = activitySteps(stages, runStatus);
  const activeStep = steps.find((step) => step.active)?.message ?? "";
  const ThemeIcon = THEME_ICON[theme];

  async function refreshProjects() {
    setProjects(await listProjects());
  }

  async function refreshProject(current: Project): Promise<Artifact[]> {
    if (!current.conversation_id) return [];
    const [nextMessages, nextArtifacts, full] = await Promise.all([
      listMessages(current.conversation_id),
      listArtifacts(current.id),
      fetch(`/api/projects/${current.id}`).then((response) => response.json()),
    ]);
    setMessages(nextMessages);
    setArtifacts(nextArtifacts);
    // The dataset summary can be slow for large files; load it without
    // holding back the transcript and outputs.
    if (full.active_dataset_id) {
      setDatasetLoading(true);
      getDataset(full.active_dataset_id)
        .then((loaded) => {
          if (projectRef.current !== current.id) return;
          setDataset({ rows: loaded.row_count, variables: loaded.variables.map((item) => item.name) });
        })
        .catch((reason: Error) => setError(reason.message))
        .finally(() => setDatasetLoading(false));
    } else {
      setDataset(null);
    }
    setOpen((currentOpen) => nextArtifacts.find((item) => item.id === currentOpen?.id) ?? currentOpen);
    return nextArtifacts;
  }

  function show(artifact: Artifact | null) {
    setOpen(artifact);
    setTab(artifact ? "viewer" : "outputs");
    if (artifact) setMobileView("outputs");
  }

  useEffect(() => {
    refreshProjects().catch((reason: Error) => setError(reason.message));
  }, []);

  useEffect(() => {
    setStageStarted(Date.now());
  }, [activeStep]);

  useEffect(() => {
    if (!busy) return;
    const handle = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(handle);
  }, [busy]);

  useEffect(() => {
    transcriptEnd.current?.scrollIntoView({ block: "end" });
  }, [messages, busy, activeStep]);

  function selectProject(item: Project) {
    projectRef.current = item.id;
    setProject(item);
    setArtifacts([]);
    setMessages([]);
    setDataset(null);
    setError("");
    setNotice("");
    setRailOpen(false);
    show(null);
    // Open on the Outputs overview so every result is one click away.
    refreshProject(item).catch((reason: Error) => setError(reason.message));
  }

  async function onCreate() {
    setError("");
    const created = await createProject(name);
    projectRef.current = created.id;
    setProjects((current) => [created, ...current]);
    setProject(created);
    setMessages([]);
    setArtifacts([]);
    setDataset(null);
    setRailOpen(false);
    show(null);
  }

  async function onSend() {
    if (!project?.conversation_id || !draft.trim() || busy) return;
    const text = draft.trim();
    setBusy(true);
    setError("");
    setNotice("");
    setStages([]);
    setRunStatus("queued");
    setMessages((current) => [
      ...current,
      { id: `pending-${Date.now()}`, role: "user", content: text, sequence: Number.MAX_SAFE_INTEGER },
    ]);
    setDraft("");
    const previous = artifacts;
    try {
      const sent = await sendMessage(project.conversation_id, text);
      setTaskId(sent.task_id);
      let status = "queued";
      let failure = "";
      const started = Date.now();
      while (stillWaiting(started, Date.now(), status)) {
        const task = await taskStatus(sent.task_id);
        status = task.status;
        setRunStatus(status);
        setStages(task.events ?? []);
        failure = task.error || "";
        if (!isTerminalStatus(status)) {
          await new Promise((resolve) => setTimeout(resolve, TASK_POLL_MS));
        }
      }
      const next = await refreshProject(project);
      const opened = artifactToShow(previous, next);
      if (opened) {
        const match = next.find((item) => item.id === opened.id);
        if (match) show(match);
      }
      if (status === "failed") {
        setError(failure || "The draft failed.");
      } else if (!isTerminalStatus(status)) {
        setError("The draft is still running. Reopen the project in a minute to load it.");
      }
    } catch (reason) {
      setMessages((current) => current.filter((item) => !item.id.startsWith("pending-")));
      setDraft(text);
      setError(reason instanceof Error ? reason.message : "Send failed.");
    } finally {
      setBusy(false);
      setStages([]);
    }
  }

  function onTabKey(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const next: WorkspaceTab = tab === "outputs" && open ? "viewer" : "outputs";
    setTab(next);
    document.getElementById(`tab-${next}`)?.focus();
  }

  const variables = dataset?.variables ?? [];
  const shownVariables = variables.filter((variable) => variable.toLowerCase().includes(variableQuery.toLowerCase()));

  return (
    <div className="flex h-dvh overflow-hidden bg-canvas text-ink">
      <a
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-surface focus:px-3 focus:py-2 focus:shadow-lg"
        href="#chat"
      >
        Skip to message box
      </a>

      {/* Projects rail: static on wide screens, a drawer below xl. */}
      {railOpen && <div aria-hidden className="fixed inset-0 z-30 bg-black/40 xl:hidden" onClick={() => setRailOpen(false)} />}
      <nav
        aria-label="Projects"
        className={clsx(
          "w-64 shrink-0 flex-col border-r border-line bg-surface",
          railOpen ? "fixed inset-y-0 left-0 z-40 flex shadow-xl" : "hidden",
          "xl:static xl:flex xl:shadow-none",
        )}
      >
        <div className="flex h-14 shrink-0 items-center gap-2.5 border-b border-line px-4">
          <span aria-hidden className="flex h-7 w-7 items-center justify-center rounded-md bg-accent text-xs font-bold text-on-accent">S</span>
          <div className="min-w-0 flex-1">
            <h1 className="text-sm font-semibold leading-tight">SRAS</h1>
            <p className="truncate text-[11px] leading-tight text-muted">Survey Research Agent Studio</p>
          </div>
          <IconButton className="xl:hidden" label="Close projects" onClick={() => setRailOpen(false)}>
            <X className="h-4 w-4" />
          </IconButton>
        </div>
        <form
          className="shrink-0 border-b border-line p-3"
          onSubmit={(event) => {
            event.preventDefault();
            onCreate().catch((reason: Error) => setError(reason.message));
          }}
        >
          <label className="mb-1 block text-xs font-medium text-ink-2" htmlFor="project-name">New project</label>
          <div className="flex gap-1.5">
            <input
              id="project-name"
              className="h-8 min-w-0 flex-1 rounded-md border border-line-strong bg-surface px-2 text-sm"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
            <Button aria-label="Create project" className="h-8 w-8 px-0" disabled={!name.trim()} type="submit" variant="primary">
              <Plus aria-hidden className="h-4 w-4" />
            </Button>
          </div>
        </form>
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          <p className="px-2 pb-1 pt-1 text-[11px] font-semibold uppercase tracking-wider text-muted">Projects</p>
          <ul className="space-y-0.5">
            {projects.map((item) => {
              const active = project?.id === item.id;
              return (
                <li key={item.id}>
                  <button
                    aria-current={active ? "page" : undefined}
                    className={clsx(
                      "w-full truncate rounded-md px-2 py-1.5 text-left text-sm transition-colors",
                      active ? "bg-accent-soft font-medium text-accent" : "text-ink-2 hover:bg-sunken hover:text-ink",
                    )}
                    onClick={() => selectProject(item)}
                    title={item.name}
                    type="button"
                  >
                    {item.name}
                  </button>
                </li>
              );
            })}
            {projects.length === 0 && <li className="px-2 text-sm text-muted">No projects yet.</li>}
          </ul>
          {variables.length > 0 && (
            <div className="mt-4 border-t border-line pt-3">
              <p className="px-2 pb-1 text-[11px] font-semibold uppercase tracking-wider text-muted">Variables · {variables.length}</p>
              <input
                aria-label="Filter variables"
                className="mx-2 mb-1 h-8 w-[calc(100%-1rem)] rounded-md border border-line-strong bg-surface px-2 text-sm placeholder:text-muted"
                placeholder="Filter variables"
                value={variableQuery}
                onChange={(event) => setVariableQuery(event.target.value)}
              />
              <ul className="max-h-64 overflow-y-auto">
                {shownVariables.map((variable) => (
                  <li key={variable}>
                    <button
                      className="w-full truncate rounded px-2 py-0.5 text-left font-mono text-xs text-ink-2 hover:bg-sunken hover:text-ink"
                      onClick={() => {
                        setDraft((current) => `${current} ${variable}`.trim());
                        composer.current?.focus();
                      }}
                      title={`Insert ${variable} into the message`}
                      type="button"
                    >
                      {variable}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
        <div className="shrink-0 border-t border-line p-2">
          <Button className="w-full justify-start" onClick={() => setTheme(nextPreference(theme))} size="sm" variant="ghost">
            <ThemeIcon aria-hidden className="h-4 w-4" />
            Theme: {theme === "system" ? "System" : theme === "light" ? "Light" : "Dark"}
          </Button>
        </div>
      </nav>

      {/* Conversation */}
      <main
        className={clsx(
          "min-w-0 flex-1 flex-col",
          mobileView === "outputs" && project ? "hidden md:flex" : "flex",
          expanded && project && "md:hidden",
        )}
      >
        <header className="flex h-14 shrink-0 items-center gap-2 border-b border-line bg-surface px-3 sm:px-4">
          <IconButton className="xl:hidden" label="Open projects" onClick={() => setRailOpen(true)}>
            <PanelLeft className="h-4 w-4" />
          </IconButton>
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-sm font-semibold">{project?.name ?? "No project selected"}</h2>
            <p className="flex items-center gap-1 truncate text-xs text-muted">
              {project && dataset ? (
                <>
                  <Database aria-hidden className="h-3 w-3" />
                  {dataset.rows.toLocaleString()} rows · {dataset.variables.length} variables
                </>
              ) : project && datasetLoading ? (
                "Loading dataset…"
              ) : project ? (
                "No dataset yet — attach a file to add one"
              ) : (
                "Choose or create a project"
              )}
            </p>
          </div>
          {project && (
            <Button className="md:hidden" onClick={() => setMobileView("outputs")} size="sm">
              <Layers aria-hidden className="h-3.5 w-3.5" />
              Outputs · {artifacts.length}
            </Button>
          )}
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl space-y-4 px-4 py-6">
            {!project && (
              <div className="rounded-xl border border-dashed border-line-strong bg-surface p-8 text-center">
                <p className="text-base font-semibold">Welcome to SRAS</p>
                <p className="mt-1 text-sm text-muted">
                  Pick a project on the left, or create one. Then ask for a questionnaire, a tab spec, a crosstab, a cleaning check or a Prolific sample quote.
                </p>
                <Button className="mt-4 xl:hidden" onClick={() => setRailOpen(true)} variant="primary">
                  Open projects
                </Button>
              </div>
            )}
            {project && messages.length === 0 && !busy && (
              <p className="text-center text-sm text-muted">Ask for a table, a questionnaire edit, or a note.</p>
            )}
            {messages.map((message) => {
              const mine = message.role === "user";
              return (
                <article key={message.id} className={clsx("flex", mine ? "justify-end" : "justify-start")}>
                  <div className={clsx("max-w-[85%]", mine ? "items-end" : "items-start")}>
                    <p className={clsx("mb-1 text-[11px] font-medium uppercase tracking-wide text-muted", mine && "text-right")}>
                      {mine ? "You" : message.role === "assistant" ? "Agent" : message.role}
                    </p>
                    <p
                      className={clsx(
                        "whitespace-pre-wrap break-words rounded-2xl px-4 py-2.5 text-sm leading-relaxed",
                        mine
                          ? "rounded-br-md bg-accent text-on-accent"
                          : "rounded-bl-md border border-line bg-surface text-ink shadow-xs",
                      )}
                    >
                      {message.content}
                    </p>
                  </div>
                </article>
              );
            })}
            {busy && <TaskActivity elapsedLabel={formatElapsed(now - stageStarted)} steps={steps} />}
            <div ref={transcriptEnd} />
          </div>
        </div>

        <div className="shrink-0 border-t border-line bg-surface px-3 pb-3 pt-2 sm:px-4">
          <div className="mx-auto max-w-3xl">
            {error && (
              <p className="mb-2 flex items-start justify-between gap-2 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger" role="alert">
                <span>{error}</span>
                <button aria-label="Dismiss error" className="shrink-0" onClick={() => setError("")} type="button">
                  <X aria-hidden className="h-4 w-4" />
                </button>
              </p>
            )}
            {notice && <p aria-live="polite" className="mb-2 text-xs text-muted">{notice}</p>}
            <form
              className="rounded-xl border border-line-strong bg-surface shadow-xs focus-within:border-accent focus-within:ring-1 focus-within:ring-accent"
              onSubmit={(event) => {
                event.preventDefault();
                onSend();
              }}
            >
              <label className="sr-only" htmlFor="chat">Message</label>
              <textarea
                id="chat"
                ref={composer}
                className="block max-h-48 min-h-[4.5rem] w-full resize-y rounded-t-xl bg-transparent px-3.5 py-3 text-sm placeholder:text-muted focus-visible:outline-none"
                disabled={!project}
                value={draft}
                placeholder={project ? "Ask for trust by gender, a tab spec, or save a note" : "Create or choose a project first"}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    onSend();
                  }
                }}
              />
              <div className="flex items-center justify-between gap-2 px-2 pb-2">
                <input
                  ref={fileInput}
                  aria-label="Upload a file"
                  className="sr-only"
                  type="file"
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    event.target.value = "";
                    if (file && project) {
                      setNotice(`Uploading ${file.name}…`);
                      uploadFile(project.id, file)
                        .then(() => refreshProject(project))
                        .then(() => setNotice(`Uploaded ${file.name}.`))
                        .catch((reason: Error) => {
                          setNotice("");
                          setError(reason.message);
                        });
                    }
                  }}
                />
                <Button disabled={!project} onClick={() => fileInput.current?.click()} size="sm" variant="ghost">
                  <Paperclip aria-hidden className="h-3.5 w-3.5" />
                  Attach file
                </Button>
                <div className="flex items-center gap-2">
                  <span className="hidden text-[11px] text-muted sm:inline">Enter to send · Shift+Enter for a new line</span>
                  {busy && taskId && (
                    <Button
                      onClick={() => {
                        cancelTask(taskId).catch((reason: Error) => setError(reason.message));
                      }}
                      size="sm"
                    >
                      <Square aria-hidden className="h-3 w-3" />
                      Stop
                    </Button>
                  )}
                  <Button disabled={busy || !project || !draft.trim()} size="sm" type="submit" variant="primary">
                    {busy ? "Working…" : "Send"}
                    {!busy && <ArrowUp aria-hidden className="h-3.5 w-3.5" />}
                  </Button>
                </div>
              </div>
            </form>
          </div>
        </div>
      </main>

      {/* Workspace: outputs list and the open artifact. */}
      {project && (
        <>
          <div
            aria-label="Resize workspace"
            aria-orientation="vertical"
            aria-valuemax={PANEL_MAX}
            aria-valuemin={PANEL_MIN}
            aria-valuenow={panelWidth}
            className={clsx(
              "relative hidden w-1 shrink-0 cursor-col-resize bg-line transition-colors hover:bg-accent focus-visible:bg-accent",
              !expanded && "md:block",
            )}
            onKeyDown={(event) => {
              const next = nudgeWidth(panelWidth, event.key, PANEL_MIN, PANEL_MAX);
              if (next !== panelWidth) {
                event.preventDefault();
                setPanelWidth(next);
              }
            }}
            onMouseDown={(event) => {
              event.preventDefault();
              const startX = event.clientX;
              const start = panelWidth;
              const move = (next: MouseEvent) =>
                setPanelWidth(Math.min(PANEL_MAX, Math.max(PANEL_MIN, start + (startX - next.clientX))));
              const up = () => {
                window.removeEventListener("mousemove", move);
                window.removeEventListener("mouseup", up);
              };
              window.addEventListener("mousemove", move);
              window.addEventListener("mouseup", up);
            }}
            role="separator"
            tabIndex={0}
          />
          <aside
            aria-label="Workspace"
            className={clsx(
              "min-w-0 flex-col bg-surface",
              mobileView === "outputs" ? "flex flex-1" : "hidden",
              "md:flex",
              expanded ? "md:flex-1" : "md:w-[var(--panel-w)] md:max-w-[65%] md:flex-none",
            )}
            style={{ "--panel-w": `${panelWidth}px` } as CSSProperties}
          >
            <div className="flex h-14 shrink-0 items-center gap-1 border-b border-line px-2">
              <IconButton className="md:hidden" label="Back to chat" onClick={() => setMobileView("chat")}>
                <MessageSquare className="h-4 w-4" />
              </IconButton>
              <div aria-label="Workspace views" className="flex min-w-0 flex-1 items-center gap-1" role="tablist">
                <button
                  aria-controls="panel-outputs"
                  aria-selected={tab === "outputs"}
                  className={clsx(
                    "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md px-2.5 text-sm font-medium transition-colors",
                    tab === "outputs" ? "bg-sunken text-ink" : "text-muted hover:text-ink",
                  )}
                  id="tab-outputs"
                  onClick={() => setTab("outputs")}
                  onKeyDown={onTabKey}
                  role="tab"
                  tabIndex={tab === "outputs" ? 0 : -1}
                  type="button"
                >
                  <Layers aria-hidden className="h-4 w-4" />
                  Outputs
                  <span className="rounded-full bg-accent-soft px-1.5 text-[11px] font-semibold text-accent">{artifacts.length}</span>
                </button>
                <button
                  aria-controls="panel-viewer"
                  aria-selected={tab === "viewer"}
                  className={clsx(
                    "inline-flex h-8 min-w-0 items-center gap-1.5 rounded-md px-2.5 text-sm font-medium transition-colors disabled:opacity-40",
                    tab === "viewer" ? "bg-sunken text-ink" : "text-muted hover:text-ink",
                  )}
                  disabled={!open}
                  id="tab-viewer"
                  onClick={() => setTab("viewer")}
                  onKeyDown={onTabKey}
                  role="tab"
                  tabIndex={tab === "viewer" ? 0 : -1}
                  title={open ? `${artifactTypeLabel(open.type)}: ${open.name}` : "Open an output to view it"}
                  type="button"
                >
                  {open ? <ArtifactIcon className="h-4 w-4 shrink-0" type={open.type} /> : null}
                  <span className="truncate">{open ? open.name : "Viewer"}</span>
                </button>
              </div>
              {open && (
                <IconButton label="Close viewer" onClick={() => show(null)}>
                  <X className="h-4 w-4" />
                </IconButton>
              )}
              <IconButton className="hidden md:inline-flex" label={expanded ? "Show chat" : "Expand workspace"} onClick={() => setExpanded(!expanded)}>
                {expanded ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
              </IconButton>
            </div>
            <div
              aria-labelledby="tab-outputs"
              className={clsx("min-h-0 flex-1 overflow-y-auto bg-canvas", tab !== "outputs" && "hidden")}
              id="panel-outputs"
              role="tabpanel"
            >
              <OutputsPanel
                artifacts={artifacts}
                onError={setError}
                onOpen={(artifact) => show(artifact)}
                openId={open?.id ?? null}
                projectId={project.id}
              />
            </div>
            {open && (
              <div
                aria-labelledby="tab-viewer"
                className={clsx("min-h-0 flex-1", tab !== "viewer" && "hidden")}
                id="panel-viewer"
                role="tabpanel"
              >
                <ArtifactEditor
                  artifact={open}
                  projectId={project.id}
                  currentStage={busy ? activeStep : ""}
                  onSaved={async () => {
                    if (project) await refreshProject(project);
                  }}
                  onProgrammed={async (artifactId) => {
                    if (!project) return;
                    const next = await refreshProject(project);
                    const match = next.find((item) => item.id === artifactId);
                    if (match) show(match);
                  }}
                />
              </div>
            )}
          </aside>
        </>
      )}
    </div>
  );
}
