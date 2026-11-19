import {
  addOption,
  addQuestion,
  deleteOption,
  deleteQuestion,
  modulesOf,
  moveOption,
  moveQuestion,
  moveQuestionToModule,
  questionsOf,
  updateOption,
  updateQuestionField,
  updateQuestionText,
  type FlowIssue,
} from "./model";
import { useState } from "react";

import { buildCatalog, derivedLines, logicLines, type LogicLine, type QuestionLite } from "./logic";
import { LogicEditor, SourceExcerpt } from "./LogicEditor";

function LogicList({ lines, onResolve }: { lines: LogicLine[]; onResolve?: (text: string) => void }) {
  return (
    <dl className="mt-1 grid grid-cols-[7.5rem_minmax(0,1fr)] gap-x-3 gap-y-1 text-sm">
      {lines.map((line, lineIndex) => (
        <div key={`${line.label}-${lineIndex}`} className="contents">
          <dt className={line.todo ? "font-medium text-warn" : "text-ink-2"}>{line.label}</dt>
          <dd className={line.todo ? "text-warn" : "text-ink"}>
            {line.text}
            {line.todo && onResolve && line.label === "To-do" && (
              <button className="ml-2 text-xs underline" type="button" onClick={() => onResolve(line.text)}>
                Mark done
              </button>
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function QuestionnaireEditor({
  content,
  issues,
  onChange,
}: {
  content: Record<string, unknown>;
  issues: FlowIssue[];
  onChange: (next: Record<string, unknown>) => void;
}) {
  const questions = questionsOf(content);
  const [editing, setEditing] = useState<string | null>(null);
  const [showing, setShowing] = useState<Set<string>>(new Set());
  const ids = questions.map((question) => question.id ?? "");
  const toggleSource = (id: string) =>
    setShowing((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const modules = modulesOf(content);
  const source = content.source as { mode?: string; filename?: string; checked_items?: number } | null | undefined;
  const rotations = (content.rotations as { groups: string[][]; note?: string }[] | undefined) ?? [];
  const derived = (content.derived_variables as { id: string; label?: string; definition: string; compute?: { kind: string; sources?: string[]; rows?: (string | number)[] } | null; values?: { code: string | number; label: string }[]; unresolved?: string[] }[] | undefined) ?? [];
  const catalog = buildCatalog(questions as QuestionLite[], derived);
  const planned = questions.some((question) => (question as QuestionLite).programming);
  const todos = questions.flatMap((question) =>
    (((question as QuestionLite).programming?.unresolved as string[] | undefined) ?? []).map((text) => ({ id: question.id, text })),
  );
  return (
    <div className="space-y-4">
      {source?.filename && (
        <p className="rounded border border-line bg-sunken px-3 py-2 text-sm text-ink-2">
          {source.mode === "exact"
            ? `Imported exactly as written from ${source.filename}. ${source.checked_items ?? 0} pieces of text, the question order, and the punch codes were checked against the file.`
            : `Drafted using ${source.filename} as a reference.`}
        </p>
      )}
      {planned && (
        <section className="rounded border border-line bg-surface px-3 py-2 text-sm">
          <p className="font-medium text-ink">Programming logic</p>
          <p className="mt-1 text-ink-2">
            Each question below shows how it will be programmed: who sees it, which rows show, checks, and terminates.
            Review it against the questionnaire, edit anything that is wrong (or ask in chat), then ask to program it in Decipher.
          </p>
          {todos.length > 0 ? (
            <details className="mt-2">
              <summary className="cursor-pointer text-warn">{todos.length} item(s) need a programmer&apos;s decision</summary>
              <ul className="mt-1 list-disc pl-5 text-ink">
                {todos.map((todo, todoIndex) => (
                  <li key={`${todo.id}-${todoIndex}`}><span className="font-medium">{todo.id}</span>: {todo.text}</li>
                ))}
              </ul>
            </details>
          ) : (
            <p className="mt-2 text-ink-2">No open items.</p>
          )}
          {rotations.map((rotation, rotationIndex) => (
            <p key={rotationIndex} className="mt-2 text-ink">
              <span className="text-ink-2">Sections in random order: </span>
              {rotation.groups.map((group) => (group.length > 1 ? `${group[0]}-${group[group.length - 1]}` : group[0])).join(" | ")}
              {rotation.note ? <span className="text-ink-2"> ({rotation.note})</span> : null}
            </p>
          ))}
        </section>
      )}
      <div className="flex items-center justify-between">
        <p className="text-sm text-ink-2">{questions.length} questions</p>
        <button className="rounded border border-line-strong bg-surface px-3 py-1.5 text-sm" onClick={() => onChange(addQuestion(content))} type="button">
          Add question
        </button>
      </div>
      {questions.map((question, index) => {
        const related = issues.filter((issue) => !issue.question_id || issue.question_id === question.id);
        return (
          <article key={question.id ?? index} className="rounded-lg border border-line bg-surface p-4 shadow-sm">
            <div className="flex items-center gap-2">
              <span className="rounded bg-sunken px-2 py-0.5 text-xs font-medium text-ink-2">{question.id}</span>
              <span className="text-xs text-muted">{question.type}</span>
              {(question as { source_excerpt?: string }).source_excerpt && (
                <button className="ml-auto text-xs underline text-ink-2" type="button" onClick={() => toggleSource(question.id ?? "")}>
                  {showing.has(question.id ?? "") ? "Hide the file's text" : "Show in the file"}
                </button>
              )}
            </div>
            {showing.has(question.id ?? "") && (
              <SourceExcerpt excerpt={(question as { source_excerpt?: string }).source_excerpt ?? ""} wording={question.text ?? ""} />
            )}
            <label className="mt-3 block text-xs font-medium text-ink-2">
              Question
              <input
                aria-label={`${question.id} text`}
                className="mt-1 w-full rounded border border-line-strong px-2 py-1.5 text-sm"
                value={question.text ?? ""}
                onChange={(event) => onChange(updateQuestionText(content, index, event.target.value))}
              />
            </label>
            <label className="mt-3 block text-xs font-medium text-ink-2">
              Respondent instruction
              <input
                aria-label={`${question.id} instruction`}
                className="mt-1 w-full rounded border border-line-strong px-2 py-1.5 text-sm"
                value={question.instruction ?? ""}
                onChange={(event) =>
                  onChange(updateQuestionField(content, index, { instruction: event.target.value }))
                }
              />
            </label>
            <label className="mt-3 block text-xs font-medium text-ink-2">
              Programmer notes
              <textarea
                aria-label={`${question.id} programmer notes`}
                className="mt-1 w-full rounded border border-line-strong px-2 py-1.5 text-sm"
                rows={3}
                value={(question.programmer_notes ?? []).join("\n")}
                onChange={(event) =>
                  onChange(
                    updateQuestionField(content, index, {
                      programmer_notes: event.target.value ? event.target.value.split("\n") : [],
                    }),
                  )
                }
              />
            </label>
            <div className="mt-3 flex flex-wrap gap-3 text-xs text-ink-2">
              <button className="underline" type="button" onClick={() => onChange(moveQuestion(content, index, -1))}>Move up</button>
              <button className="underline" type="button" onClick={() => onChange(moveQuestion(content, index, 1))}>Move down</button>
              <button className="underline" type="button" onClick={() => onChange(deleteQuestion(content, index))}>Delete question</button>
              <button className="underline" type="button" onClick={() => onChange(addOption(content, index))}>Add option</button>
            </div>
            {(question as QuestionLite).programming && (
              <div className="mt-3 rounded border border-line bg-sunken px-3 py-2">
                <div className="flex items-center justify-between">
                  <p className="text-xs font-medium text-ink-2">How it will be programmed</p>
                  <button className="text-xs underline text-ink-2" type="button" onClick={() => setEditing(editing === question.id ? null : question.id ?? null)}>
                    {editing === question.id ? "Done editing" : "Edit logic"}
                  </button>
                </div>
                {editing === question.id && (
                  <LogicEditor
                    question={question as QuestionLite}
                    ids={ids}
                    catalog={catalog}
                    onChange={(next) =>
                      onChange(
                        updateQuestionField(content, index, {
                          display_if: next.display_if ?? null,
                          options: next.options,
                          randomize_options: next.randomize_options,
                          required: next.required,
                          programming: next.programming,
                        }),
                      )
                    }
                  />
                )}
                <LogicList
                  lines={logicLines(question as QuestionLite, catalog)}
                  onResolve={(text) => {
                    const programming = { ...((question as QuestionLite).programming ?? {}) };
                    programming.unresolved = ((programming.unresolved as string[] | undefined) ?? []).filter((item) => item !== text);
                    onChange(updateQuestionField(content, index, { programming }));
                  }}
                />
              </div>
            )}
            {modules.length > 0 && (
              <label className="mt-3 block text-xs font-medium text-ink-2">
                Module
                <select
                  aria-label={`${question.id} module`}
                  className="ml-2 rounded border border-line-strong bg-surface px-2 py-1 text-sm"
                  value={modules.find((module) => (module.question_ids ?? []).includes(question.id ?? ""))?.id ?? ""}
                  onChange={(event) => onChange(moveQuestionToModule(content, question.id ?? "", event.target.value))}
                >
                  <option value="">Unassigned</option>
                  {modules.map((module) => (
                    <option key={module.id} value={module.id}>{module.title ?? module.id}</option>
                  ))}
                </select>
              </label>
            )}
            {(question.matrix_items ?? []).length > 0 && (
              <div className="mt-3 text-xs text-ink-2">
                <p className="font-medium">Grid rows</p>
                <ol className="mt-1 list-decimal space-y-0.5 pl-5 text-sm text-ink">
                  {(question.matrix_items ?? []).map((item, rowIndex) => (
                    <li key={`${question.id}-row-${rowIndex}`}>{item}</li>
                  ))}
                </ol>
              </div>
            )}
            <ul className="mt-3 space-y-2">
              {(question.options ?? []).map((option, optionIndex) => (
                <li key={`${question.id}-${optionIndex}`} className="grid grid-cols-[5rem_minmax(0,1fr)_auto] items-center gap-2">
                  <input
                    aria-label={`${question.id} option ${optionIndex} code`}
                    className="w-full rounded border border-line-strong px-2 py-1 text-sm"
                    value={String(option.code)}
                    onChange={(event) => onChange(updateOption(content, index, optionIndex, { code: event.target.value }))}
                  />
                  <input
                    aria-label={`${question.id} option ${optionIndex} label`}
                    className="w-full rounded border border-line-strong px-2 py-1 text-sm"
                    value={option.label}
                    onChange={(event) => onChange(updateOption(content, index, optionIndex, { label: event.target.value }))}
                  />
                  <span className="flex gap-2 text-xs text-ink-2">
                    <button className="underline" type="button" onClick={() => onChange(moveOption(content, index, optionIndex, -1))}>Up</button>
                    <button className="underline" type="button" onClick={() => onChange(deleteOption(content, index, optionIndex))}>Delete</button>
                  </span>
                </li>
              ))}
            </ul>
            {related.length > 0 && (
              <ul className="mt-3 list-disc pl-5 text-sm text-warn">
                {related.map((issue) => (
                  <li key={`${issue.code}-${issue.message}`}>{issue.message}</li>
                ))}
              </ul>
            )}
          </article>
        );
      })}
      {derived.length > 0 && (
        <section className="rounded-lg border border-line bg-surface p-4 shadow-sm">
          <h3 className="text-sm font-medium text-ink">Derived variables ({derived.length})</h3>
          <p className="mt-1 text-xs text-muted">Hidden and classification variables the questionnaire defines. Respondents do not see them.</p>
          <dl className="mt-3 space-y-2 text-sm">
            {derived.map((variable) => (
              <div key={variable.id}>
                <dt className="font-medium text-ink-2">{variable.id}{variable.label ? ` - ${variable.label}` : ""}</dt>
                <dd className="whitespace-pre-line text-ink">{variable.definition}</dd>
                {((variable.values ?? []).length > 0 || variable.compute) && (
                  <dd className="mt-1 rounded border border-line bg-sunken px-3 py-1">
                    <LogicList lines={derivedLines(variable, catalog)} />
                  </dd>
                )}
                {(variable.unresolved ?? []).map((item, itemIndex) => (
                  <dd key={itemIndex} className="text-warn">To-do: {item}</dd>
                ))}
              </div>
            ))}
          </dl>
        </section>
      )}
      {issues.filter((issue) => !issue.question_id).map((issue) => (
        <p key={issue.code} className="rounded border border-warn-line bg-warn-soft px-3 py-2 text-sm text-warn">{issue.message}</p>
      ))}
    </div>
  );
}
