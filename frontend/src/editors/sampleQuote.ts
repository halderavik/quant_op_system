/** Labels for a planned Prolific quota cell. */

export type QuotaCell = {
  labels?: string[];
  places?: number;
};

export function quotaCellLabel(cell: QuotaCell): string {
  const labels = Array.isArray(cell.labels) ? cell.labels.filter((item) => item) : [];
  const name = labels.length > 0 ? labels.join(" · ") : "All eligible";
  const places = typeof cell.places === "number" ? cell.places : 0;
  return `${name}: ${places} planned`;
}

export function formatMoney(cents: number, currency: string): string {
  const code = currency === "GBP" || currency === "USD" ? currency : "USD";
  return new Intl.NumberFormat(code === "GBP" ? "en-GB" : "en-US", {
    style: "currency",
    currency: code,
  }).format(cents / 100);
}
