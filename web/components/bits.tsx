"use client";

import { useEffect, useRef, useState } from "react";
import { percent, signedR, tone } from "@/lib/format";
import type { Group } from "@/lib/types";

/** One figure with its label under it. */
export function Stat({
  value,
  label,
  colour,
}: {
  value: React.ReactNode;
  label: string;
  colour?: string;
}) {
  return (
    <div className="stat">
      <b className={colour}>{value}</b>
      <span>{label}</span>
    </div>
  );
}

/** How long a figure takes to travel to its new value. */
const TRAVEL = 420;

function still(): boolean {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

/**
 * A figure that travels to its new value instead of jumping to it.
 *
 * **The width is reserved for the destination before the first frame.** The
 * intermediate values of a count are shorter than the end of it - 0, 7, 84,
 * 1,486 - and a figure that widens as it counts drags the five figures beside
 * it along the row. `min-width` in `ch` is the width of a digit under
 * `font-variant-numeric: tabular-nums`, which the body already sets, so the
 * box is the size of the final string throughout and nothing moves but the
 * glyphs.
 *
 * The travel is deliberately short and eased out: this is a dashboard whose
 * numbers change every fifteen seconds, and a second-long count would still
 * be running when the next read lands.
 */
export function Ticker({
  value,
  format,
  from = 0,
}: {
  value: number;
  format: (value: number) => string;
  /** Where the first render starts. `value` itself means "no entrance". */
  from?: number;
}) {
  const [shown, setShown] = useState(from);
  const held = useRef(from);
  const shape = useRef(format);
  shape.current = format;

  useEffect(() => {
    const start = held.current;
    if (start === value || !Number.isFinite(value)) {
      held.current = value;
      setShown(value);
      return;
    }
    if (still()) {
      held.current = value;
      setShown(value);
      return;
    }
    let frame = 0;
    const began = performance.now();
    const step = (now: number) => {
      const t = Math.min(1, (now - began) / TRAVEL);
      const eased = 1 - (1 - t) ** 3;
      setShown(start + (value - start) * eased);
      if (t < 1) frame = requestAnimationFrame(step);
      else held.current = value;
    };
    frame = requestAnimationFrame(step);
    return () => {
      cancelAnimationFrame(frame);
      // Whatever the tween reached is where the next one starts, so an
      // interrupted count does not snap back before travelling again.
      held.current = value;
    };
  }, [value]);

  const target = format(value);
  return (
    <span className="tick" style={{ display: "inline-block", minWidth: `${target.length}ch` }}>
      {format(shown)}
    </span>
  );
}

/**
 * Marks a figure that has just changed, without moving it.
 *
 * For the figures a `Ticker` would be wrong for: a count inside a table row,
 * where reserving a destination width in `ch` would unalign a right-hand
 * column, and a string that is not a number at all. The mark is a background
 * wash that fades out, so the cell's geometry never changes.
 */
export function Flash({ on, children }: { on: string | number; children: React.ReactNode }) {
  const [marked, setMarked] = useState(false);
  const first = useRef(true);

  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    setMarked(false);
    // Two frames: one to take the class off so the animation can be
    // retriggered, one to put it back. Setting it in the same frame is a
    // no-op, and the second change of a figure would not mark at all.
    const frame = requestAnimationFrame(() => setMarked(true));
    return () => cancelAnimationFrame(frame);
  }, [on]);

  return (
    <span
      className={marked ? "tick tick-changed" : "tick"}
      onAnimationEnd={() => setMarked(false)}
    >
      {children}
    </span>
  );
}

/**
 * A panel with nothing in it, said as a designed state rather than a sentence.
 *
 * It keeps the distinction this dashboard is built on: a window with no trades
 * is not the same as a source that is missing, and both are different from a
 * read that has not finished. The caller says which.
 */
export function Empty({ children }: { children: React.ReactNode }) {
  return (
    <p className="note empty">
      <span className="empty-rule" aria-hidden="true" />
      {children}
    </p>
  );
}

/**
 * `Group.verdict`, straight from `strategies/report.py`.
 *
 * Under thirty closed trades it is a refusal to characterise a rate, and the
 * dashboard shows the refusal rather than a confident percentage over nine
 * trades. The amber is for that case and nothing else.
 */
export function Verdict({ group, extra }: { group: Group; extra?: string }) {
  return (
    <p className={group.enough ? "verdict" : "verdict verdict-thin"}>
      {group.verdict}
      {extra ? ` ${extra}` : ""}
    </p>
  );
}

/**
 * Count, win rate, mean R with its standard error, and total R.
 *
 * The standard error is printed beside the mean because a mean without one is
 * a number nobody can judge, and a dagger marks a row too thin to characterise
 * rather than quietly rounding it into a percentage.
 */
export function Groups({
  rows,
  label,
  pooled,
  enough,
  onPick,
  picked,
}: {
  rows: Group[];
  label: string;
  pooled: number;
  enough: number;
  onPick?: (name: string) => void;
  picked?: string;
}) {
  const ranked = [...rows].sort((a, b) => b.count - a.count);
  const widest = ranked.reduce((most, row) => Math.max(most, row.count), 1);
  const thin = ranked.some((row) => !row.enough);

  if (ranked.length === 0) return <Empty>Nothing closed in this window.</Empty>;

  return (
    <>
      <table className="grid">
        <thead>
          <tr>
            <th>{label}</th>
            <th aria-label="share of trades" />
            <th className="r">n</th>
            <th className="r">won</th>
            <th className="r">mean R</th>
            <th className="r">± se</th>
            <th className="r">total R</th>
          </tr>
        </thead>
        <tbody>
          {ranked.map((row) => (
            <tr
              key={row.name || "unrecorded"}
              title={row.verdict}
              onClick={onPick ? () => onPick(row.name) : undefined}
              style={onPick ? { cursor: "pointer" } : undefined}
              aria-selected={picked === row.name ? true : undefined}
            >
              <td className={picked === row.name ? "" : undefined}>{row.name || "unrecorded"}</td>
              <td style={{ width: 70 }}>
                <span className="rail-bar">
                  <span style={{ width: `${(row.count / widest) * 100}%` }} />
                </span>
              </td>
              <td className="r num">
                {row.count}
                {!row.enough && <span className="warn">&#8224;</span>}
              </td>
              <td className={`r num ${row.win_rate >= pooled ? "up" : "down"}`}>
                {percent(row.win_rate)}
              </td>
              <td className={`r num ${tone(row.mean_r)}`}>{signedR(row.mean_r)}</td>
              <td className="r num dim">{row.se_r == null ? "—" : row.se_r.toFixed(2)}</td>
              <td className={`r num ${tone(row.total_r)}`}>{signedR(row.total_r, 1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {thin && (
        <p className="note">
          <span className="warn">&#8224;</span> fewer than {enough} closed trades, so the rate is
          the sample and not an estimate of one. Win rates are coloured against the pooled{" "}
          {percent(pooled)}.
        </p>
      )}
    </>
  );
}
