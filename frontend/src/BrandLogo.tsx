/**
 * Quant OS logo by b3, drawn as SVG so it follows the light and dark theme.
 * Colors come from the --logo-* tokens in index.css; nothing here is a fixed color.
 */

const NODES: [number, number, number][] = [
  [239, 84, 83],
  [97, 166, 46],
  [381, 166, 46],
  [239, 249, 46],
  [97, 331, 46],
  [381, 331, 46],
  [239, 412, 46],
];

/** The b3 network mark: four squares with the node graph laid over them. */
function MarkShapes() {
  const halo = { stroke: "var(--logo-halo)", strokeWidth: 12, paintOrder: "stroke" as const };
  return (
    <g>
      <rect x="2" y="3" width="201" height="201" fill="var(--logo-ink)" />
      <rect x="263" y="3" width="200" height="201" fill="var(--logo-ink)" />
      <rect x="2" y="274" width="201" height="201" fill="var(--logo-ink)" />
      <rect x="263" y="274" width="200" height="201" fill="var(--logo-grey)" />
      <path
        d="M97 166 V331 M97 166 L239 249 L381 331 M381 166 V331"
        fill="none"
        stroke="var(--logo-halo)"
        strokeWidth="34"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {NODES.map(([cx, cy, r]) => (
        <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r={r} fill="var(--logo-node)" style={halo} />
      ))}
      <path
        d="M97 166 V331 M97 166 L239 249 L381 331 M381 166 V331"
        fill="none"
        stroke="var(--logo-node)"
        strokeWidth="18"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {NODES.map(([cx, cy, r]) => (
        <circle key={`f-${cx}-${cy}`} cx={cx} cy={cy} r={r} fill="var(--logo-node)" />
      ))}
    </g>
  );
}

/** The mark alone, for small places such as the header and the favicon. */
export function BrandMark({ className, title = "Quant OS" }: { className?: string; title?: string }) {
  return (
    <svg className={className} viewBox="-12 -8 489 496" {...(title ? { role: "img", "aria-label": title } : { "aria-hidden": true })}>
      <MarkShapes />
    </svg>
  );
}

/** Mark with the b³ letters, then "Quant OS" underneath: the full logo. */
export function BrandLogo({ className }: { className?: string }) {
  return (
    <div className={className} role="img" aria-label="b3 Quant OS">
      <svg className="mx-auto block w-full" viewBox="-12 -110 1080 600" aria-hidden>
        <MarkShapes />
        <g fill="none" stroke="var(--logo-b3)" strokeLinecap="butt">
          <path d="M589 60 V450" strokeWidth="43" />
          <ellipse cx="690" cy="311" rx="102" ry="120" strokeWidth="43" />
          <path d="M899.6 -7 A64 64 0 1 1 950 83 A77 77 0 1 1 890 198.5" strokeWidth="33" />
        </g>
      </svg>
      <p
        className="mt-[6%] text-center font-bold"
        style={{
          color: "var(--logo-word)",
          fontFamily: '"Poppins", "Space Grotesk", var(--font-sans)',
          fontSize: "clamp(18px, 9cqw, 64px)",
          letterSpacing: "0.32em",
          paddingLeft: "0.32em",
        }}
      >
        Quant OS
      </p>
    </div>
  );
}
