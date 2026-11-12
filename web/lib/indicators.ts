/**
 * Indicators, computed from the candles already on screen.
 *
 * Three, because three correct ones beat a menu of approximations. Each
 * returns points only where it is defined - a 50-bar mean has no value on bar
 * 12, and seeding it with the bars so far would draw a line that is a
 * different statistic at the left edge than at the right.
 *
 * All of them are bar-count measures, so they say nothing about calendar time:
 * an ATR of 14 bars is 70 minutes at 5m and three days at 4h, and the same
 * number means different things on the two charts.
 */

import type { Bar } from "./types";

export interface Point {
  time: number;
  value: number;
}

export interface Band {
  time: number;
  upper: number;
  lower: number;
}

/** Simple mean of the close, over `span` bars. */
export function mean(bars: Bar[], span: number): Point[] {
  if (span < 1 || bars.length < span) return [];
  const out: Point[] = [];
  let running = 0;
  for (let index = 0; index < bars.length; index += 1) {
    running += bars[index]!.close;
    if (index >= span) running -= bars[index - span]!.close;
    if (index >= span - 1) out.push({ time: bars[index]!.time, value: running / span });
  }
  return out;
}

/**
 * Wilder's true range, averaged over `span` bars.
 *
 * True range and not the bar's own range: a gap between the previous close and
 * this bar's extreme is movement the market made, and a high-minus-low misses
 * all of it. On a 5m feed with session breaks that is most of the overnight.
 */
export function atr(bars: Bar[], span = 14): Point[] {
  if (bars.length < span + 1) return [];
  const ranges: number[] = [];
  for (let index = 1; index < bars.length; index += 1) {
    const bar = bars[index]!;
    const before = bars[index - 1]!;
    ranges.push(
      Math.max(
        bar.high - bar.low,
        Math.abs(bar.high - before.close),
        Math.abs(bar.low - before.close),
      ),
    );
  }
  const out: Point[] = [];
  let running = 0;
  for (let index = 0; index < ranges.length; index += 1) {
    running += ranges[index]!;
    if (index >= span) running -= ranges[index - span]!;
    if (index >= span - 1) out.push({ time: bars[index + 1]!.time, value: running / span });
  }
  return out;
}

/** A mean with an ATR cushion either side. Drawn as two lines, not a fill. */
export function bands(bars: Bar[], span = 20, width = 2, atrSpan = 14): Band[] {
  const centre = new Map(mean(bars, span).map((point) => [point.time, point.value]));
  return atr(bars, atrSpan)
    .filter((point) => centre.has(point.time))
    .map((point) => ({
      time: point.time,
      upper: centre.get(point.time)! + width * point.value,
      lower: centre.get(point.time)! - width * point.value,
    }));
}

/**
 * Realised volatility, in basis points of the close, per bar.
 *
 * The standard deviation of log returns over `span` bars, stated in bps rather
 * than annualised: annualising needs a bars-per-year figure, and this feed has
 * session gaps and weekends, so any constant would be wrong by a factor
 * nobody could see. Bps per bar is what the desk's own `vol_bps` is.
 */
export function volatility(bars: Bar[], span = 20): Point[] {
  if (bars.length < span + 1) return [];
  const returns: number[] = [];
  for (let index = 1; index < bars.length; index += 1) {
    const before = bars[index - 1]!.close;
    const now = bars[index]!.close;
    returns.push(before > 0 && now > 0 ? Math.log(now / before) : 0);
  }
  const out: Point[] = [];
  for (let index = span - 1; index < returns.length; index += 1) {
    const window = returns.slice(index - span + 1, index + 1);
    const average = window.reduce((sum, value) => sum + value, 0) / span;
    const variance =
      window.reduce((sum, value) => sum + (value - average) ** 2, 0) / Math.max(1, span - 1);
    out.push({ time: bars[index + 1]!.time, value: Math.sqrt(variance) * 10_000 });
  }
  return out;
}
