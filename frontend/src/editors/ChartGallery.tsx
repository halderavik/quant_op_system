import { downloadUrl } from "../api";

type Chart = { title?: string; kind?: string; file_id?: string };

/** Every chart stored on an artifact, each with its own PNG download. */
export function ChartGallery({ content }: { content: Record<string, unknown> }) {
  const listed = Array.isArray(content.charts) ? (content.charts as Chart[]) : [];
  const single = typeof content.chart_file_id === "string" && content.chart_file_id ? content.chart_file_id : "";
  const charts: Chart[] = listed.length ? listed : single ? [{ title: "Chart", file_id: single }] : [];
  if (!charts.length) return null;
  const zip = typeof content.charts_zip_file_id === "string" ? content.charts_zip_file_id : "";
  return (
    <section>
      <div className="flex flex-wrap items-baseline gap-3">
        <h3 className="font-semibold">Charts ({charts.length})</h3>
        {zip && (
          <a className="text-xs underline" href={downloadUrl(zip)}>
            Download all charts (.zip)
          </a>
        )}
      </div>
      <div className="mt-2 grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(280px,1fr))]">
        {charts.map((chart, index) =>
          chart.file_id ? (
            <figure key={chart.file_id} className="rounded-md border border-line bg-white p-2">
              <a href={downloadUrl(chart.file_id)} target="_blank" rel="noreferrer">
                <img alt={chart.title ?? `Chart ${index + 1}`} className="w-full" loading="lazy" src={downloadUrl(chart.file_id)} />
              </a>
              <figcaption className="mt-1 flex items-center justify-between gap-2 text-xs text-ink-2">
                <span className="truncate" title={chart.title}>{chart.title}</span>
                <a className="shrink-0 underline" href={downloadUrl(chart.file_id)} download>
                  PNG
                </a>
              </figcaption>
            </figure>
          ) : null,
        )}
      </div>
    </section>
  );
}
