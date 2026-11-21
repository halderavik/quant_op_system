import { useCallback, useEffect, useMemo, useState } from "react";
import { Check, RotateCcw, Sparkles } from "lucide-react";
import { fixTodos, listTodos, markTodos, type ProgrammerTodo, type TodoList } from "../api";
import { Badge, Button, cn } from "../ui";

type View = "open" | "done";

/** Programmer to-dos with Fix with AI, Mark done, and Reopen. */
export function TodoPanel({
  projectId,
  version,
  onChanged,
  onCount,
}: {
  projectId: string;
  /** Survey version on screen; the list reloads when it changes. */
  version: number;
  onChanged: (artifactId: string) => Promise<void> | void;
  onCount?: (open: number) => void;
}) {
  const [list, setList] = useState<TodoList | null>(null);
  const [view, setView] = useState<View>("open");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<"" | "fix" | "mark">("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const next = await listTodos(projectId);
      setList(next);
      onCount?.(next.open);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The to-dos could not be loaded.");
    }
  }, [projectId, onCount]);

  useEffect(() => {
    void load();
  }, [load, version]);

  const shown = useMemo(() => {
    const words = query.trim().toLowerCase();
    return (list?.todos ?? []).filter(
      (todo) =>
        todo.done === (view === "done") &&
        (!words || `${todo.owner} ${todo.title} ${todo.text}`.toLowerCase().includes(words)),
    );
  }, [list, view, query]);

  const groups = useMemo(() => {
    const byOwner = new Map<string, ProgrammerTodo[]>();
    for (const todo of shown) byOwner.set(todo.owner, [...(byOwner.get(todo.owner) ?? []), todo]);
    return [...byOwner.entries()];
  }, [shown]);

  const picked = shown.filter((todo) => selected.has(todo.id));
  const fixable = picked.filter((todo) => todo.fixable);

  async function run(kind: "fix" | "mark", ids: string[], done = true) {
    if (!ids.length) return;
    setBusy(kind);
    setError("");
    setMessage(kind === "fix" ? "Fixing with AI, then checking the result. This can take a few minutes." : "");
    try {
      const next = kind === "fix" ? await fixTodos(projectId, ids) : await markTodos(projectId, ids, done);
      setList(next);
      onCount?.(next.open);
      setSelected(new Set());
      setMessage(next.summary ?? "");
      if (next.artifact_id) await onChanged(next.artifact_id);
    } catch (reason) {
      setMessage("");
      setError(reason instanceof Error ? reason.message : "That did not work.");
    } finally {
      setBusy("");
    }
  }

  function toggle(id: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  if (!list) {
    return error ? <p className="text-sm text-danger" role="alert">{error}</p> : <p className="text-sm text-muted">Loading to-dos…</p>;
  }

  return (
    <section aria-label="Programmer to-dos" className="space-y-3 text-sm">
      <p className="text-ink-2">
        What programming could not carry out on its own. <strong>Fix with AI</strong> plans the question again and
        has the reviewer check it; <strong>Mark done</strong> is for what you handled in Decipher or don't need.
        Each change rebuilds the XML. Nothing is uploaded.
      </p>
      {list.xml_stale && (
        <p className="rounded-md border border-warn-line bg-warn-soft px-3 py-2 text-warn" role="status">
          The questionnaire changed after this XML was built. Program it again to bring the XML up to date.
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <div aria-label="Which to-dos" className="flex rounded-md border border-line bg-sunken p-0.5" role="tablist">
          {(["open", "done"] as View[]).map((option) => (
            <button
              aria-selected={view === option}
              className={cn(
                "rounded px-2.5 py-1 text-xs font-medium",
                view === option ? "bg-surface text-ink shadow-xs" : "text-muted hover:text-ink",
              )}
              key={option}
              onClick={() => {
                setView(option);
                setSelected(new Set());
              }}
              role="tab"
              type="button"
            >
              {option === "open" ? `Open (${list.open})` : `Done (${list.done})`}
            </button>
          ))}
        </div>
        <input
          aria-label="Search to-dos"
          className="h-7 min-w-0 flex-1 rounded-md border border-line-strong bg-surface px-2 text-xs sm:max-w-56"
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search by question or text"
          value={query}
        />
        {view === "open" ? (
          <>
            <Button disabled={!!busy || !fixable.length} onClick={() => void run("fix", fixable.map((t) => t.id))} size="sm" variant="primary">
              <Sparkles aria-hidden className="h-3.5 w-3.5" />
              {busy === "fix" ? "Fixing…" : `Fix ${fixable.length || ""} with AI`.replace("  ", " ")}
            </Button>
            <Button disabled={!!busy || !picked.length} onClick={() => void run("mark", picked.map((t) => t.id), true)} size="sm">
              <Check aria-hidden className="h-3.5 w-3.5" />
              Mark {picked.length || ""} done
            </Button>
          </>
        ) : (
          <Button disabled={!!busy || !picked.length} onClick={() => void run("mark", picked.map((t) => t.id), false)} size="sm">
            <RotateCcw aria-hidden className="h-3.5 w-3.5" />
            Reopen {picked.length || ""}
          </Button>
        )}
      </div>
      {message && <p aria-live="polite" className="text-accent">{message}</p>}
      {error && <p className="text-danger" role="alert">{error}</p>}
      {shown.length === 0 ? (
        <p className="rounded-md border border-line bg-surface px-3 py-6 text-center text-muted">
          {view === "open" ? (list.open ? "No open to-dos match that search." : "No open to-dos. Every instruction is programmed.") : "Nothing is marked done yet."}
        </p>
      ) : (
        <>
          <label className="flex items-center gap-2 text-xs text-muted">
            <input
              checked={picked.length === shown.length}
              onChange={(event) => setSelected(event.target.checked ? new Set(shown.map((t) => t.id)) : new Set())}
              type="checkbox"
            />
            Select all {shown.length} shown
          </label>
          <ul className="space-y-2">
            {groups.map(([owner, todos]) => (
              <li className="rounded-lg border border-line bg-surface" key={owner}>
                <div className="flex items-baseline gap-2 border-b border-line px-3 py-2">
                  <span className="font-mono text-xs font-semibold text-ink">{owner}</span>
                  {todos[0].owner_kind === "derived" && <Badge>Derived variable</Badge>}
                  <span className="truncate text-xs text-muted" title={todos[0].title}>{todos[0].title}</span>
                </div>
                <ul className="divide-y divide-line">
                  {todos.map((todo) => (
                    <li className="flex items-start gap-2 px-3 py-2" key={todo.id}>
                      <input
                        aria-label={`Select to-do: ${todo.text}`}
                        checked={selected.has(todo.id)}
                        className="mt-1"
                        onChange={() => toggle(todo.id)}
                        type="checkbox"
                      />
                      <div className="min-w-0 flex-1">
                        <p className={cn("text-ink", todo.done && "text-muted line-through")}>{todo.text}</p>
                        <p className="mt-0.5 text-[11px] text-muted">
                          {todo.source === "review" ? "Found by the reviewer" : "Left by the planner"}
                        </p>
                      </div>
                      <div className="flex shrink-0 gap-1">
                        {todo.done ? (
                          <Button disabled={!!busy} onClick={() => void run("mark", [todo.id], false)} size="sm" variant="ghost">
                            Reopen
                          </Button>
                        ) : (
                          <>
                            {todo.fixable && (
                              <Button disabled={!!busy} onClick={() => void run("fix", [todo.id])} size="sm" variant="ghost">
                                <Sparkles aria-hidden className="h-3.5 w-3.5" />
                                Fix with AI
                              </Button>
                            )}
                            <Button disabled={!!busy} onClick={() => void run("mark", [todo.id], true)} size="sm" variant="ghost">
                              <Check aria-hidden className="h-3.5 w-3.5" />
                              Mark done
                            </Button>
                          </>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
