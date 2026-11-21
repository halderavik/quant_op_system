import { useEffect, useMemo, useState } from "react";
import { downloadUrl } from "../api";
import {
  getSegmentation,
  getSegmentationVariables,
  type NamedVariable,
  runSegmentation,
  saveSegmentsToData,
  type Segmentation,
  typingTool,
  updateSegmentation,
} from "../studyApi";
import { Badge, Button, cn } from "../ui";

/** Segmentation: pick variables, compare 3–6 segment solutions, name them, type and save. */
export function SegmentsPanel({ projectId, onChanged }: { projectId: string; onChanged: () => Promise<void> | void }) {
  const [variables, setVariables] = useState<NamedVariable[]>([]);
  const [picked, setPicked] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [kMin, setKMin] = useState(3);
  const [kMax, setKMax] = useState(6);
  const [result, setResult] = useState<Segmentation | null>(null);
  const [names, setNames] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    setResult(null);
    setMessage("");
    setError("");
    getSegmentationVariables(projectId)
      .then((list) => live && setVariables(list))
      .catch((reason: Error) => live && setError(reason.message));
    getSegmentation(projectId)
      .then((saved) => {
        if (!live || !saved.segmentation) return;
        setResult(saved.segmentation);
        setPicked(saved.segmentation.variables.map((v) => v.name));
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [projectId]);

  const shown = useMemo(() => {
    const words = query.trim().toLowerCase();
    return variables.filter((v) => !words || `${v.name} ${v.label}`.toLowerCase().includes(words)).slice(0, 300);
  }, [variables, query]);
  const solution = result?.solutions.find((s) => s.k === result.chosen) ?? null;
  const labels = useMemo(() => Object.fromEntries((result?.variables ?? []).map((v) => [v.name, v.label])), [result]);

  async function act(kind: string, work: () => Promise<void>) {
    setBusy(kind);
    setError("");
    setMessage("");
    try {
      await work();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "That did not work.");
    } finally {
      setBusy("");
    }
  }

  return (
    <section aria-label="Segments" className="space-y-4 text-sm">
      <div className="rounded-lg border border-line bg-surface p-3">
        <h3 className="font-semibold text-ink">Segmentation variables</h3>
        <p className="mt-1 text-xs text-ink-2">
          Choose attitude, need or behaviour ratings from the active data. Respondents missing any of them are left out.
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <input
            aria-label="Search variables"
            className="h-7 min-w-0 flex-1 rounded-md border border-line-strong bg-surface px-2 text-xs sm:max-w-56"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search variables"
            value={query}
          />
          <label className="flex items-center gap-1 text-xs text-ink-2">
            Segments
            <select aria-label="Fewest segments" className="h-7 rounded-md border border-line-strong bg-surface text-xs" onChange={(e) => setKMin(Number(e.target.value))} value={kMin}>
              {[2, 3, 4, 5, 6].map((n) => <option key={n}>{n}</option>)}
            </select>
            to
            <select aria-label="Most segments" className="h-7 rounded-md border border-line-strong bg-surface text-xs" onChange={(e) => setKMax(Number(e.target.value))} value={kMax}>
              {[3, 4, 5, 6, 7, 8].map((n) => <option key={n}>{n}</option>)}
            </select>
          </label>
          <Button
            disabled={!!busy || picked.length < 2 || kMax < kMin}
            onClick={() =>
              void act("run", async () => {
                const next = await runSegmentation(projectId, picked, kMin, kMax);
                setResult(next);
                setNames({});
              })
            }
            size="sm"
            variant="primary"
          >
            {busy === "run" ? "Comparing…" : `Compare solutions (${picked.length} variables)`}
          </Button>
        </div>
        <ul className="mt-2 max-h-40 overflow-y-auto rounded-md border border-line">
          {shown.map((variable) => (
            <li key={variable.name}>
              <label className="flex items-center gap-2 px-2 py-1 text-xs hover:bg-sunken">
                <input
                  checked={picked.includes(variable.name)}
                  onChange={(event) =>
                    setPicked((current) =>
                      event.target.checked ? [...current, variable.name] : current.filter((n) => n !== variable.name),
                    )
                  }
                  type="checkbox"
                />
                <span className="font-mono">{variable.name}</span>
                <span className="truncate text-muted">{variable.label}</span>
              </label>
            </li>
          ))}
          {shown.length === 0 && <li className="px-2 py-2 text-xs text-muted">No numeric variables in the active data.</li>}
        </ul>
      </div>
      {message && <p className="text-accent" role="status">{message}</p>}
      {error && <p className="text-danger" role="alert">{error}</p>}

      {result && (
        <div className="space-y-3 rounded-lg border border-line bg-surface p-3">
          <h3 className="font-semibold text-ink">Solutions</h3>
          <p className="text-xs text-ink-2">
            {result.base} respondents{result.dropped ? ` (${result.dropped} left out for missing answers)` : ""}. Recommended:
            the best-separated solution whose smallest segment is at least 5% and that comes back the same on a different
            80% of the sample.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-muted">
                  <th className="py-1 font-medium">Segments</th>
                  <th className="py-1 text-right font-medium">Separation</th>
                  <th className="py-1 text-right font-medium">Stability</th>
                  <th className="py-1 text-right font-medium">Smallest</th>
                  <th className="py-1 text-right font-medium">Typing tool</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {result.solutions.map((s) => (
                  <tr className={cn("border-t border-line", s.k === result.chosen && "bg-accent-soft")} key={s.k}>
                    <td className="py-1">
                      {s.k} {s.k === result.recommended && <Badge tone="success">Recommended</Badge>}
                    </td>
                    <td className="py-1 text-right tabular-nums">{s.silhouette.toFixed(2)}</td>
                    <td className="py-1 text-right tabular-nums">{s.stability.toFixed(2)}</td>
                    <td className="py-1 text-right tabular-nums">{Math.round(100 * s.smallest)}%</td>
                    <td className="py-1 text-right tabular-nums">
                      {Math.round(100 * s.typing.accuracy)}% with {s.typing.variables.length}
                    </td>
                    <td className="py-1 text-right">
                      {s.k !== result.chosen && (
                        <Button
                          disabled={!!busy}
                          onClick={() =>
                            void act("choose", async () => {
                              setResult(await updateSegmentation(projectId, result.artifact_id, s.k, {}));
                              setNames({});
                            })
                          }
                          size="sm"
                          variant="ghost"
                        >
                          Use
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {solution && (
            <>
              <h4 className="font-medium text-ink">{solution.k} segments</h4>
              <ul className="grid gap-2 md:grid-cols-2">
                {solution.profiles.map((profile) => (
                  <li className="rounded-md border border-line p-2" key={profile.segment}>
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-muted">{profile.segment}</span>
                      <input
                        aria-label={`Name of segment ${profile.segment}`}
                        className="h-7 min-w-0 flex-1 rounded-md border border-line-strong bg-surface px-2 text-xs font-medium"
                        onChange={(event) => setNames({ ...names, [String(profile.segment)]: event.target.value })}
                        value={names[String(profile.segment)] ?? profile.name}
                      />
                      <span className="text-xs tabular-nums text-ink-2">{Math.round(100 * profile.share)}%</span>
                    </div>
                    <ul className="mt-1 space-y-0.5 text-xs text-ink-2">
                      {profile.top.map((item) => (
                        <li key={item.variable}>
                          <span className={item.direction === "higher" ? "text-success" : "text-danger"}>
                            {item.direction === "higher" ? "▲" : "▼"}
                          </span>{" "}
                          {labels[item.variable] ?? item.variable}: {profile.means[item.variable]?.toFixed(1)} vs{" "}
                          {result.totals[item.variable]?.toFixed(1)} overall
                        </li>
                      ))}
                    </ul>
                  </li>
                ))}
              </ul>
              <div className="flex flex-wrap gap-2">
                <Button
                  disabled={!!busy || Object.keys(names).length === 0}
                  onClick={() =>
                    void act("names", async () => {
                      setResult(await updateSegmentation(projectId, result.artifact_id, null, names));
                      setNames({});
                      setMessage("Segment names saved.");
                    })
                  }
                  size="sm"
                >
                  Save names
                </Button>
                <Button
                  disabled={!!busy}
                  onClick={() =>
                    void act("typing", async () => {
                      const file = await typingTool(projectId, result.artifact_id);
                      window.location.assign(downloadUrl(file.file_id));
                    })
                  }
                  size="sm"
                >
                  Typing tool (Excel)
                </Button>
                <Button
                  disabled={!!busy}
                  onClick={() =>
                    void act("save", async () => {
                      const saved = await saveSegmentsToData(projectId, result.artifact_id);
                      setMessage(saved.summary);
                      await onChanged();
                    })
                  }
                  size="sm"
                  variant="primary"
                >
                  Add segments to the data
                </Button>
              </div>
              <p className="text-xs text-muted">
                The typing tool uses {solution.typing.variables.map((v) => labels[v] ?? v).join(", ")} and classified{" "}
                {Math.round(100 * solution.typing.accuracy)}% of a held-out quarter correctly (
                {Math.round(100 * solution.typing.full_accuracy)}% with every variable).
              </p>
            </>
          )}
        </div>
      )}
    </section>
  );
}
