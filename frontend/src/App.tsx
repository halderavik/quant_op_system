import { useEffect, useRef, useState } from "react";
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
import { TaskActivity } from "./TaskActivity";
import { TASK_POLL_MS, activitySteps, artifactToShow, formatElapsed, isTerminalStatus, stillWaiting } from "./chatState";

export function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [open, setOpen] = useState<Artifact | null>(null);
  const [draft, setDraft] = useState("");
  const [name, setName] = useState("Brand Trust Wave 1");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [variables, setVariables] = useState<string[]>([]);
  const [variableQuery, setVariableQuery] = useState("");
  const [taskId, setTaskId] = useState<string | null>(null);
  const [stages, setStages] = useState<TaskStage[]>([]);
  const [runStatus, setRunStatus] = useState("queued");
  const [stageStarted, setStageStarted] = useState(Date.now());
  const [now, setNow] = useState(Date.now());
  const [panelWidth, setPanelWidth] = useState(480);
  const transcriptEnd = useRef<HTMLDivElement>(null);
  const steps = activitySteps(stages, runStatus);
  const activeStep = steps.find((step) => step.active)?.message ?? "";

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
    if (full.active_dataset_id) {
      const dataset = await getDataset(full.active_dataset_id);
      setVariables(dataset.variables.map((item) => item.name));
    } else {
      setVariables([]);
    }
    setOpen((currentOpen) => nextArtifacts.find((item) => item.id === currentOpen?.id) ?? currentOpen);
    return nextArtifacts;
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

  async function onCreate() {
    setError("");
    const created = await createProject(name);
    setProjects((current) => [created, ...current]);
    setProject(created);
    setMessages([]);
    setArtifacts([]);
    setOpen(null);
  }

  async function onSend() {
    if (!project?.conversation_id || !draft.trim()) return;
    const text = draft.trim();
    setBusy(true);
    setError("");
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
        if (match) setOpen(match);
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

  return (
    <div className="grid min-h-screen" style={{ gridTemplateColumns: open ? `220px minmax(0,1fr) 8px ${panelWidth}px` : "220px minmax(0,1fr)" }}>
      <aside className="border-r border-stone-200 bg-white p-4">
        <h1 className="text-base font-semibold leading-snug">SRAS (Survey Research Agent Studio)</h1>
        <label className="mt-4 block text-sm text-stone-600" htmlFor="project-name">New project</label>
        <input id="project-name" className="mt-1 w-full rounded border border-stone-300 px-2 py-1" value={name} onChange={(event) => setName(event.target.value)} />
        <button className="mt-2 w-full rounded bg-teal-900 px-3 py-2 text-white" onClick={() => onCreate().catch((reason: Error) => setError(reason.message))} type="button">
          Create project
        </button>
        <ul className="mt-6 space-y-1">
          {projects.map((item) => (
            <li key={item.id}>
              <button
                className={`w-full rounded px-2 py-1 text-left ${project?.id === item.id ? "bg-stone-200" : ""}`}
                onClick={() => {
                  setProject(item);
                  setArtifacts([]);
                  setOpen(null);
                  refreshProject(item)
                    .then((next) => {
                      const opened = artifactToShow([], next);
                      if (opened) setOpen(opened);
                    })
                    .catch((reason: Error) => setError(reason.message));
                }}
                type="button"
              >
                {item.name}
              </button>
            </li>
          ))}
        </ul>
        {variables.length > 0 && (
          <div className="mt-6">
            <p className="text-xs uppercase text-stone-500">Variables</p>
            <input
              aria-label="Filter variables"
              className="mt-2 w-full rounded border border-stone-300 px-2 py-1 text-sm"
              value={variableQuery}
              onChange={(event) => setVariableQuery(event.target.value)}
            />
            <ul className="mt-2 max-h-48 overflow-auto text-sm">
              {variables
                .filter((variable) => variable.toLowerCase().includes(variableQuery.toLowerCase()))
                .map((variable) => (
                <li key={variable}>
                  <button className="text-left underline" onClick={() => setDraft((current) => `${current} ${variable}`.trim())} type="button">
                    {variable}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </aside>
      <main className="flex min-w-0 flex-col">
        <div className="flex-1 space-y-3 overflow-auto px-6 py-6">
          {messages.map((message) => (
            <article key={message.id} className={message.role === "user" ? "ml-8" : "mr-8"}>
              <p className="text-xs uppercase text-stone-500">{message.role}</p>
              <p className="whitespace-pre-wrap rounded bg-white p-3 shadow-sm">{message.content}</p>
            </article>
          ))}
          {messages.length === 0 && !busy && <p className="text-stone-500">Create a project, then ask for a table, a questionnaire edit, or a note.</p>}
          {busy && <TaskActivity elapsedLabel={formatElapsed(now - stageStarted)} steps={steps} />}
          <div ref={transcriptEnd} />
        </div>
        {error && <p className="px-6 text-sm text-red-700">{error}</p>}
        <form
          className="border-t border-stone-200 bg-white p-4"
          onSubmit={(event) => {
            event.preventDefault();
            onSend();
          }}
        >
          <label className="sr-only" htmlFor="chat">Message</label>
          <textarea
            id="chat"
            className="h-24 w-full rounded border border-stone-300 p-3"
            value={draft}
            placeholder="Ask for trust by gender, a tab spec, or save a note"
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                onSend();
              }
            }}
          />
          <div className="mt-2 flex items-center justify-between">
            <input
              aria-label="Upload a file"
              type="file"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file && project) {
                  uploadFile(project.id, file)
                    .then(() => refreshProject(project))
                    .catch((reason: Error) => setError(reason.message));
                }
              }}
            />
            <div className="flex gap-2">
              {busy && taskId && (
                <button
                  className="rounded border border-stone-400 px-4 py-2"
                  onClick={() => {
                    cancelTask(taskId).catch((reason: Error) => setError(reason.message));
                  }}
                  type="button"
                >
                  Stop
                </button>
              )}
              <button className="rounded bg-teal-900 px-4 py-2 text-white disabled:opacity-50" disabled={busy || !project} type="submit">
                {busy ? "Working" : "Send"}
              </button>
            </div>
          </div>
        </form>
        <div className="flex gap-2 overflow-auto border-t border-stone-200 px-4 py-2">
          {artifacts.map((artifact) => (
            <button key={artifact.id} className="rounded border border-stone-300 bg-white px-2 py-1 text-sm" onClick={() => setOpen(artifact)} type="button">
              {artifact.name}
              {artifact.latest?.stale ? " · stale" : ""}
            </button>
          ))}
        </div>
      </main>
      {open && project && (
        <>
          <div
            aria-hidden
            className="cursor-col-resize bg-stone-200"
            onMouseDown={(event) => {
              const startX = event.clientX;
              const start = panelWidth;
              const move = (next: MouseEvent) => setPanelWidth(Math.max(320, start + (startX - next.clientX)));
              const up = () => {
                window.removeEventListener("mousemove", move);
                window.removeEventListener("mouseup", up);
              };
              window.addEventListener("mousemove", move);
              window.addEventListener("mouseup", up);
            }}
          />
          <section className="min-w-0 bg-white">
            <div className="flex justify-end border-b border-stone-200 px-3 py-2">
              <button className="text-sm underline" onClick={() => setOpen(null)} type="button">Close</button>
            </div>
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
                if (match) setOpen(match);
              }}
            />
          </section>
        </>
      )}
    </div>
  );
}
