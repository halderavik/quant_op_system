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
  const modules = modulesOf(content);
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-stone-600">{questions.length} questions</p>
        <button className="rounded border border-stone-300 bg-white px-3 py-1.5 text-sm" onClick={() => onChange(addQuestion(content))} type="button">
          Add question
        </button>
      </div>
      {questions.map((question, index) => {
        const related = issues.filter((issue) => !issue.question_id || issue.question_id === question.id);
        return (
          <article key={question.id ?? index} className="rounded-lg border border-stone-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2">
              <span className="rounded bg-stone-100 px-2 py-0.5 text-xs font-medium text-stone-700">{question.id}</span>
              <span className="text-xs text-stone-500">{question.type}</span>
            </div>
            <label className="mt-3 block text-xs font-medium text-stone-600">
              Question
              <input
                aria-label={`${question.id} text`}
                className="mt-1 w-full rounded border border-stone-300 px-2 py-1.5 text-sm"
                value={question.text ?? ""}
                onChange={(event) => onChange(updateQuestionText(content, index, event.target.value))}
              />
            </label>
            <label className="mt-3 block text-xs font-medium text-stone-600">
              Respondent instruction
              <input
                aria-label={`${question.id} instruction`}
                className="mt-1 w-full rounded border border-stone-300 px-2 py-1.5 text-sm"
                value={question.instruction ?? ""}
                onChange={(event) =>
                  onChange(updateQuestionField(content, index, { instruction: event.target.value }))
                }
              />
            </label>
            <label className="mt-3 block text-xs font-medium text-stone-600">
              Programmer notes
              <textarea
                aria-label={`${question.id} programmer notes`}
                className="mt-1 w-full rounded border border-stone-300 px-2 py-1.5 text-sm"
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
            <div className="mt-3 flex flex-wrap gap-3 text-xs text-stone-600">
              <button className="underline" type="button" onClick={() => onChange(moveQuestion(content, index, -1))}>Move up</button>
              <button className="underline" type="button" onClick={() => onChange(moveQuestion(content, index, 1))}>Move down</button>
              <button className="underline" type="button" onClick={() => onChange(deleteQuestion(content, index))}>Delete question</button>
              <button className="underline" type="button" onClick={() => onChange(addOption(content, index))}>Add option</button>
            </div>
            {modules.length > 0 && (
              <label className="mt-3 block text-xs font-medium text-stone-600">
                Module
                <select
                  aria-label={`${question.id} module`}
                  className="ml-2 rounded border border-stone-300 bg-white px-2 py-1 text-sm"
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
            <ul className="mt-3 space-y-2">
              {(question.options ?? []).map((option, optionIndex) => (
                <li key={`${question.id}-${optionIndex}`} className="grid grid-cols-[5rem_minmax(0,1fr)_auto] items-center gap-2">
                  <input
                    aria-label={`${question.id} option ${optionIndex} code`}
                    className="w-full rounded border border-stone-300 px-2 py-1 text-sm"
                    value={String(option.code)}
                    onChange={(event) => onChange(updateOption(content, index, optionIndex, { code: event.target.value }))}
                  />
                  <input
                    aria-label={`${question.id} option ${optionIndex} label`}
                    className="w-full rounded border border-stone-300 px-2 py-1 text-sm"
                    value={option.label}
                    onChange={(event) => onChange(updateOption(content, index, optionIndex, { label: event.target.value }))}
                  />
                  <span className="flex gap-2 text-xs text-stone-600">
                    <button className="underline" type="button" onClick={() => onChange(moveOption(content, index, optionIndex, -1))}>Up</button>
                    <button className="underline" type="button" onClick={() => onChange(deleteOption(content, index, optionIndex))}>Delete</button>
                  </span>
                </li>
              ))}
            </ul>
            {related.length > 0 && (
              <ul className="mt-3 list-disc pl-5 text-sm text-amber-900">
                {related.map((issue) => (
                  <li key={`${issue.code}-${issue.message}`}>{issue.message}</li>
                ))}
              </ul>
            )}
          </article>
        );
      })}
      {issues.filter((issue) => !issue.question_id).map((issue) => (
        <p key={issue.code} className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-950">{issue.message}</p>
      ))}
    </div>
  );
}
