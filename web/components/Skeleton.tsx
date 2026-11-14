/**
 * The shape of the data, while the data is being read.
 *
 * **A blank panel and a broken panel look identical.** The first read of this
 * dashboard is not instant - `data.series()` groups a 300MB bar table, and the
 * journal read behind `/api/overview` is a hundred thousand entries - so there
 * are seconds in which every panel is empty, and "empty" is also what a
 * missing source looks like. These stand in the place the table will occupy
 * and carry a caption naming what is being read, so the two states are
 * different at a glance.
 *
 * Nothing here is a spinner: a spinner says "wait" and says nothing about
 * what for.
 */

/**
 * A wandering series for the chart's placeholder, computed once at module
 * load from a fixed seed.
 *
 * **Deterministic, and that is the whole point.** `Math.random()` inside the
 * component would redraw a different series on every parent re-render, so the
 * placeholder would flicker through unrelated shapes while the real candles
 * were being read. A walk rather than a sawtooth because a comb of
 * alternating heights does not read as a price series at a glance, and the
 * thing this stands in for is a price series.
 */
const BARS = (() => {
  let seed = 20260101;
  const next = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
  let level = 50;
  return Array.from({ length: 104 }, () => {
    level = Math.max(18, Math.min(74, level + (next() - 0.5) * 9));
    const body = 3 + next() * 7;
    return { height: body, bottom: level - body / 2 };
  });
})();

/** One grey line. `width` is a CSS length. */
export function Line({ width = "100%", height = 9 }: { width?: string; height?: number }) {
  return <span className="skel skel-line" style={{ width, height, display: "block" }} />;
}

/** The six-figure header a panel opens with. */
export function SkeletonStats({ count = 6 }: { count?: number }) {
  return (
    <div className="skel-stats" aria-hidden="true">
      {Array.from({ length: count }, (_, index) => (
        <div className="skel-stat" key={index}>
          <Line width="62px" height={18} />
          <Line width="88px" height={8} />
        </div>
      ))}
    </div>
  );
}

/**
 * A table's worth of rows.
 *
 * The first cell is wide and the rest are narrow, because that is the shape of
 * every table in this app: a label, then figures. A grid of equal columns
 * would be a placeholder for a table nobody here has.
 */
export function SkeletonRows({ rows = 6, cells = 5 }: { rows?: number; cells?: number }) {
  const columns = `minmax(0, 2fr) repeat(${Math.max(0, cells - 1)}, minmax(0, 1fr))`;
  return (
    <div className="skel-rows" aria-hidden="true">
      {Array.from({ length: rows }, (_, row) => (
        <div className="skel-row" style={{ gridTemplateColumns: columns }} key={row}>
          {Array.from({ length: cells }, (_, cell) => (
            <Line key={cell} width={cell === 0 ? "70%" : "54%"} height={8} />
          ))}
        </div>
      ))}
    </div>
  );
}

/** A whole panel: figures, a table, and what is being read. */
export function SkeletonPanel({
  caption,
  stats = 6,
  rows = 6,
  cells = 5,
}: {
  caption: string;
  stats?: number;
  rows?: number;
  cells?: number;
}) {
  return (
    <div className="panel-swap">
      {stats > 0 && <SkeletonStats count={stats} />}
      <SkeletonRows rows={rows} cells={cells} />
      <p className="skel-caption">{caption}</p>
    </div>
  );
}

/** The chart pane, while its candles are in flight. */
export function SkeletonChart({ caption }: { caption: string }) {
  return (
    <>
      {/*
        Each column is full height and the bar inside it is absolutely
        positioned. A percentage `margin-bottom` would have been simpler and is
        wrong: percentage margins resolve against the containing block's
        *width*, so on a 1200px pane a "50%" offset lifts a bar 600px and the
        series climbs off the top of the chart.
      */}
      <div className="skel-chart" aria-hidden="true">
        {BARS.map((bar, index) => (
          <span key={index}>
            <i style={{ height: `${bar.height}%`, bottom: `${bar.bottom}%` }} />
          </span>
        ))}
      </div>
      <p className="skel-caption" style={{ position: "absolute", top: 12, left: 16, margin: 0 }}>
        {caption}
      </p>
    </>
  );
}
