import { toggleRow, type PreviewAnswer, type PreviewScreen } from "./surveyPreview";

export function ScreenBody({
  screen,
  rows,
  answer,
  setAnswer,
}: {
  screen: PreviewScreen;
  rows: PreviewScreen["rows"];
  answer: PreviewAnswer;
  setAnswer: (next: PreviewAnswer) => void;
}) {
  if (screen.status === "terminated" || screen.status === "complete") {
    return (
      <div className="mt-3 space-y-2">
        <h3 className="text-xl font-medium text-ink">{screen.title || "End of survey"}</h3>
        {screen.message && <p className="text-ink-2">{screen.message}</p>}
      </div>
    );
  }
  if (screen.status === "error") {
    return <p className="mt-3 text-sm text-danger">{screen.message}</p>;
  }
  return (
    <div className="mt-2">
      <h3 className="text-xl font-medium text-ink">{screen.title}</h3>
      {screen.comment && <p className="mt-2 text-sm text-ink-2">{screen.comment}</p>}
      {screen.check === "date" && <p className="mt-2 text-sm text-muted">YYYY-MM-DD</p>}
      {screen.check === "total100" && (
        <p className="mt-2 text-sm text-muted">These numbers need to total 100.</p>
      )}
      {screen.warning && (
        <p className="mt-3 rounded border border-warn-line bg-warn-soft px-3 py-2 text-sm text-warn">
          {screen.warning}
        </p>
      )}
      <div className="mt-4">
        <Fields answer={answer} rows={rows} screen={screen} setAnswer={setAnswer} />
      </div>
    </div>
  );
}

function Fields({
  screen,
  rows,
  answer,
  setAnswer,
}: {
  screen: PreviewScreen;
  rows: PreviewScreen["rows"];
  answer: PreviewAnswer;
  setAnswer: (next: PreviewAnswer) => void;
}) {
  if (screen.element === "html") return null;
  if (screen.element === "loop") {
    return (
      <ul className="list-disc space-y-1 pl-5 text-sm">
        {rows.map((row) => (
          <li key={row.label}>{row.text}</li>
        ))}
      </ul>
    );
  }
  if (screen.element === "checkbox") return <Checks answer={answer} rows={rows} setAnswer={setAnswer} />;
  if (screen.element === "radio" && screen.cols.length > 0) {
    return <Grid answer={answer} rows={rows} screen={screen} setAnswer={setAnswer} />;
  }
  if (screen.element === "radio") return <Radios answer={answer} rows={rows} screen={screen} setAnswer={setAnswer} />;
  if (screen.element === "select") return <Ranks answer={answer} rows={rows} screen={screen} setAnswer={setAnswer} />;
  if (screen.element === "number" && rows.length > 0) {
    return <Numbers answer={answer} rows={rows} setAnswer={setAnswer} />;
  }
  if (screen.element === "textarea") {
    return (
      <textarea
        aria-label={screen.title}
        className="min-h-28 w-full rounded border border-line-strong p-3 text-sm"
        value={answer.value}
        onChange={(event) => setAnswer({ ...answer, value: event.target.value })}
      />
    );
  }
  return (
    <input
      aria-label={screen.title}
      className="w-full rounded border border-line-strong px-3 py-2 text-sm"
      inputMode={screen.element === "number" ? "decimal" : undefined}
      value={answer.value}
      onChange={(event) => setAnswer({ ...answer, value: event.target.value })}
    />
  );
}

function Radios({
  screen,
  rows,
  answer,
  setAnswer,
}: {
  screen: PreviewScreen;
  rows: PreviewScreen["rows"];
  answer: PreviewAnswer;
  setAnswer: (next: PreviewAnswer) => void;
}) {
  return (
    <div className="space-y-2">
      {rows.map((row) => {
        const selected = answer.rows.includes(row.label);
        return (
          <label key={row.label} className="flex items-start gap-2 text-sm">
            <input
              className="mt-1"
              type="radio"
              name={screen.label ?? "choice"}
              checked={selected}
              onChange={() => setAnswer({ ...answer, rows: [row.label] })}
            />
            <span className="min-w-0 flex-1">
              {row.text}
              {row.open && selected && (
                <input
                  aria-label={`${row.text} text`}
                  className="mt-1 w-full rounded border border-line-strong px-2 py-1"
                  value={answer.open_text[row.label] ?? ""}
                  onChange={(event) =>
                    setAnswer({ ...answer, open_text: { ...answer.open_text, [row.label]: event.target.value } })
                  }
                />
              )}
            </span>
          </label>
        );
      })}
    </div>
  );
}

function Checks({
  rows,
  answer,
  setAnswer,
}: {
  rows: PreviewScreen["rows"];
  answer: PreviewAnswer;
  setAnswer: (next: PreviewAnswer) => void;
}) {
  return (
    <div className="space-y-2">
      {rows.map((row) => {
        const selected = answer.rows.includes(row.label);
        return (
          <label key={row.label} className="flex items-start gap-2 text-sm">
            <input
              className="mt-1"
              type="checkbox"
              checked={selected}
              onChange={() => setAnswer({ ...answer, rows: toggleRow(rows, answer.rows, row.label) })}
            />
            <span className="min-w-0 flex-1">
              {row.text}
              {row.open && selected && (
                <input
                  aria-label={`${row.text} text`}
                  className="mt-1 w-full rounded border border-line-strong px-2 py-1"
                  value={answer.open_text[row.label] ?? ""}
                  onChange={(event) =>
                    setAnswer({ ...answer, open_text: { ...answer.open_text, [row.label]: event.target.value } })
                  }
                />
              )}
            </span>
          </label>
        );
      })}
    </div>
  );
}

function Grid({
  screen,
  rows,
  answer,
  setAnswer,
}: {
  screen: PreviewScreen;
  rows: PreviewScreen["rows"];
  answer: PreviewAnswer;
  setAnswer: (next: PreviewAnswer) => void;
}) {
  return (
    <div className="overflow-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr>
            <th className="p-2 text-left font-medium" />
            {screen.cols.map((column) => (
              <th key={column.label} className="p-2 text-center font-medium">
                {column.text}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label} className="border-t border-line">
              <th className="p-2 text-left font-normal" scope="row">
                {row.text}
              </th>
              {screen.cols.map((column) => (
                <td key={column.label} className="p-2 text-center">
                  <input
                    aria-label={`${row.text} ${column.text}`}
                    type="radio"
                    name={`${screen.label ?? "grid"}-${row.label}`}
                    checked={answer.cells[row.label] === column.label}
                    onChange={() =>
                      setAnswer({ ...answer, cells: { ...answer.cells, [row.label]: column.label } })
                    }
                  />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Ranks({
  screen,
  rows,
  answer,
  setAnswer,
}: {
  screen: PreviewScreen;
  rows: PreviewScreen["rows"];
  answer: PreviewAnswer;
  setAnswer: (next: PreviewAnswer) => void;
}) {
  return (
    <div className="space-y-2">
      {rows.map((row) => (
        <label key={row.label} className="flex items-center justify-between gap-3 text-sm">
          <span>{row.text}</span>
          <select
            aria-label={`${row.text} rank`}
            className="rounded border border-line-strong bg-surface px-2 py-1"
            value={answer.row_values[row.label] ?? ""}
            onChange={(event) =>
              setAnswer({ ...answer, row_values: { ...answer.row_values, [row.label]: event.target.value } })
            }
          >
            <option value="">Select</option>
            {screen.choices.map((choice) => (
              <option key={choice.label} value={choice.label}>
                {choice.text}
              </option>
            ))}
          </select>
        </label>
      ))}
    </div>
  );
}

function Numbers({
  rows,
  answer,
  setAnswer,
}: {
  rows: PreviewScreen["rows"];
  answer: PreviewAnswer;
  setAnswer: (next: PreviewAnswer) => void;
}) {
  return (
    <div className="space-y-2">
      {rows.map((row) => (
        <label key={row.label} className="flex items-center justify-between gap-3 text-sm">
          <span>{row.text}</span>
          <input
            aria-label={row.text}
            className="w-24 rounded border border-line-strong px-2 py-1"
            inputMode="decimal"
            value={answer.row_values[row.label] ?? ""}
            onChange={(event) =>
              setAnswer({ ...answer, row_values: { ...answer.row_values, [row.label]: event.target.value } })
            }
          />
        </label>
      ))}
    </div>
  );
}
