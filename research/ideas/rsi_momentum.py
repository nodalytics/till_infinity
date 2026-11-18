"""RSI and moving averages crossed with momentum, ranked on a short window and
scored on the one before.

The operator asked, 2026-11-18: *"give me rsi + momentum combinations from
1m-15m that has worked in the last 7 days"*, and then the same for moving
averages. Both families are in here because they are one question with two
triggers, and because running them separately would hide the multiplicity they
share.

**The ranking is the easy half and it is not the answer.** A grid of 288 cells
over seven days gives each cell a few dozen trades, and the best of 288 such
cells is large whatever the market did - "picking the best of 43 instruments
gives a winner every time" is this desk's own phrasing of it. So every cell
ranked on the recent window is also scored on:

* the **window immediately before it**, which is the cheapest possible
  discovery/confirmation split and the one thing that separates "led" from
  "worked";
* a **day-block shuffled** copy of the same bars through the same grid, whose
  best-of-288 cell is the number a leader has to beat to mean anything;
* **its own cost**, charged from the median spread measured per feed in
  `mt5_catalogue.py` - 2 points on EURUSD, 15 on gold - because
  `a-shorter-clock-multiplies-cost-in-r` measures the same spread as **19x
  dearer at 15m than at 1d**, and a 1m or 5m clock is dearer again.

Four readings of the pair, each with its short mirror, because "RSI plus
momentum" is at least four different rules and they disagree by construction:

    oversold_falling   RSI below the threshold while momentum is still negative
    oversold_turning   RSI below it while momentum has turned up - a divergence
    trend_confirmed    RSI above 50 and momentum positive
    trend_pullback     RSI below 50 and momentum positive - a dip in an uptrend

Exit is a barrier race: a stop at `--stop` ATR and a target at `--reward` times
it, resolved bar by bar, with the near barrier charged when one bar touches
both. Signals that fire while a race is open are skipped, so no two outcome
windows overlap - `overlapping-outcome-windows-leak` measured a direction AUC
of 0.79 collapsing to 0.51 once they stopped sharing outcomes.

Run as:

    uv run python research/ideas/rsi_momentum.py --frames 5m,15m --days 7
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reactive_zones import CATALOGUE, Candles, atr, fold, load, shuffled  # noqa: E402

SYMBOLS = ("EURUSD", "GBPUSD", "GOLD", "USDJPY", "AUDUSD")

#: Median recorded spread in **points**, with the increment that turns it into
#: price. Measured per feed, never pooled; `spread-column-is-in-points` is the
#: error this avoids - EURUSD read a 476% round trip when the column was taken
#: as price, and the mistake reorders instruments by cost.
SPREADS: dict[str, tuple[float, float]] = {
    "EURUSD": (2.0, 1e-05),
    "GBPUSD": (3.0, 1e-05),
    "GOLD": (15.0, 0.01),
    "USDJPY": (3.0, 0.001),
    "AUDUSD": (2.0, 1e-05),
}

#: The RSI readings. Four, because "RSI plus momentum" is at least four rules
#: and they disagree with each other by construction.
RSI_READINGS = ("oversold_falling", "oversold_turning", "trend_confirmed", "trend_pullback")

#: The moving-average readings, deliberately parallel to them: a trend arm, a
#: pullback arm, a fresh-cross arm and a stretched arm.
MA_READINGS = ("ma_trend", "ma_pullback", "ma_cross", "ma_stretch")


def rsi(close: np.ndarray, period: int) -> np.ndarray:
    """Wilder's RSI, seeded on the first `period` changes.

    Wilder's smoothing and not a simple mean: the two differ by several points
    at a 14-period setting, and every published threshold is quoted against
    Wilder's.
    """
    out = np.full(close.size, np.nan)
    if close.size <= period:
        return out
    change = np.diff(close)
    up = np.where(change > 0, change, 0.0)
    down = np.where(change < 0, -change, 0.0)
    gain, loss = up[:period].mean(), down[:period].mean()
    for i in range(period, close.size):
        if i > period:
            gain = (gain * (period - 1) + up[i - 1]) / period
            loss = (loss * (period - 1) + down[i - 1]) / period
        out[i] = 100.0 if loss <= 0 else 100.0 - 100.0 / (1.0 + gain / loss)
    return out


def momentum(close: np.ndarray, band: np.ndarray, reach: int) -> np.ndarray:
    """The `reach`-bar change in ATR of the current bar.

    In ATR because one grid spans gold at 1,300 and EURUSD at 1.08:
    `reactive-zones.md` measures ATR at twice the mean close-to-close move in
    every instrument-frame cell tried.
    """
    out = np.full(close.size, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        out[reach:] = (close[reach:] - close[:-reach]) / band[reach:]
    return out


def moving(close: np.ndarray, length: int) -> np.ndarray:
    """A simple moving average, NaN until it is full."""
    out = np.full(close.size, np.nan)
    if close.size < length:
        return out
    stack = np.lib.stride_tricks.sliding_window_view(close, length)
    out[length - 1 :] = stack.mean(axis=1)
    return out


def ma_signals(
    bars: Candles,
    band: np.ndarray,
    push: np.ndarray,
    reading: str,
    length: int,
    stretch: float,
    fresh: int = 3,
) -> np.ndarray:
    """+1 long, -1 short, 0 nothing - one moving-average reading, both sides.

    `ma_cross` wants the cross to be **fresh**: a fast line that has been above
    a slow one for two hundred bars is a trend reading, not a cross, and
    scoring it as one is how a cross rule inherits a trend rule's record. The
    fast line is a quarter of the slow one, which is the common 10/40 and 50/200
    shape.
    """
    slow = moving(bars.close, length)
    fast = moving(bars.close, max(length // 4, 2))
    close = bars.close
    side = np.zeros(close.size, dtype=np.int8)
    alive = np.isfinite(slow) & np.isfinite(push) & np.isfinite(band) & (band > 0)
    if reading == "ma_trend":
        side[alive & (close > slow) & (push > 0)] = 1
        side[alive & (close < slow) & (push < 0)] = -1
    elif reading == "ma_pullback":
        side[alive & (close > slow) & (push < 0)] = 1
        side[alive & (close < slow) & (push > 0)] = -1
    elif reading == "ma_cross":
        alive &= np.isfinite(fast)
        over = fast > slow
        turned_up = np.zeros(close.size, dtype=bool)
        turned_down = np.zeros(close.size, dtype=bool)
        flips = np.flatnonzero(np.diff(over.astype(np.int8)) != 0) + 1
        for at in flips:
            until = min(close.size, at + fresh)
            if over[at]:
                turned_up[at:until] = True
            else:
                turned_down[at:until] = True
        side[alive & turned_up & (push > 0)] = 1
        side[alive & turned_down & (push < 0)] = -1
    else:
        with np.errstate(invalid="ignore", divide="ignore"):
            away = (close - slow) / band
        # Stretched below and turning up, which is the mean-reversion reading;
        # the mirror is stretched above and turning down.
        side[alive & (away < -stretch) & (push > 0)] = 1
        side[alive & (away > stretch) & (push < 0)] = -1
    return side


def signals(strength: np.ndarray, push: np.ndarray, reading: str, low: float) -> np.ndarray:
    """+1 long, -1 short, 0 nothing - one RSI reading of the pair, both sides."""
    high = 100.0 - low
    side = np.zeros(strength.size, dtype=np.int8)
    alive = np.isfinite(strength) & np.isfinite(push)
    if reading == "oversold_falling":
        side[alive & (strength < low) & (push < 0)] = 1
        side[alive & (strength > high) & (push > 0)] = -1
    elif reading == "oversold_turning":
        side[alive & (strength < low) & (push > 0)] = 1
        side[alive & (strength > high) & (push < 0)] = -1
    elif reading == "trend_confirmed":
        side[alive & (strength > 50.0) & (strength < high) & (push > 0)] = 1
        side[alive & (strength < 50.0) & (strength > low) & (push < 0)] = -1
    else:
        side[alive & (strength < 50.0) & (strength > low) & (push > 0)] = 1
        side[alive & (strength > 50.0) & (strength < high) & (push < 0)] = -1
    return side


@dataclass(slots=True)
class Result:
    trades: int
    gross: float
    net: float
    hit: float
    spread_r: float
    values: np.ndarray
    #: Entry bar of each trade, so a caller can bucket the same race by week
    #: instead of re-running it per window. `rsi_walkforward.py` needs one
    #: continuous chain of non-overlapping trades, not a chain restarted at
    #: every window edge - restarting it lets a week begin with a free entry
    #: that the previous week's open position would have blocked.
    at: np.ndarray


def race(
    bars: Candles,
    band: np.ndarray,
    side: np.ndarray,
    stop: float,
    reward: float,
    patience: int,
    cost: float,
) -> Result:
    """Non-overlapping barrier races, gross and net of one spread each way.

    One position at a time: a signal that fires while a race is open is
    skipped rather than stacked, so no two outcomes share bars. The cost is
    **one spread** on the round trip, charged in R as `cost / stop distance` -
    which is why a shorter clock is dearer: the same spread over a smaller ATR.
    """
    n = len(bars)
    high, low, close = bars.high, bars.low, bars.close
    outcomes: list[float] = []
    charges: list[float] = []
    entries: list[int] = []
    # **Jump between signals rather than walking every bar.** Stepping one bar
    # at a time made this O(bars) per cell, and at 414 cells x 2 windows x 2
    # arms that is 18 million Python iterations for one instrument - about a
    # hundred seconds where the races themselves are a few hundred.
    firing = np.flatnonzero(side != 0)
    at = 0
    while at < firing.size:
        i = int(firing[at])
        if i >= n - 1 or not np.isfinite(band[i]) or band[i] <= 0:
            at += 1
            continue
        up = side[i] == 1
        entry = float(close[i])
        risk = stop * float(band[i])
        guard = entry - risk if up else entry + risk
        target = entry + reward * risk if up else entry - reward * risk
        done = None
        last = min(n, i + 1 + patience)
        for j in range(i + 1, last):
            stopped = (low[j] <= guard) if up else (high[j] >= guard)
            made = (high[j] >= target) if up else (low[j] <= target)
            if stopped:
                done = -1.0
                break
            if made:
                done = reward
                break
        if done is None:
            j = last - 1
            done = (float(close[j]) - entry) * (1.0 if up else -1.0) / risk
        outcomes.append(done)
        charges.append(cost / risk)
        entries.append(i)
        # The next signal strictly after this race closed: one position at a
        # time, so no two outcome windows share a bar.
        at = int(np.searchsorted(firing, j + 1))
    empty = np.asarray([], dtype=float)
    if not outcomes:
        return Result(0, float("nan"), float("nan"), float("nan"), float("nan"), empty, empty)
    got = np.asarray(outcomes)
    paid = np.asarray(charges)
    return Result(
        trades=got.size,
        gross=float(got.mean()),
        net=float((got - paid).mean()),
        hit=float((got > 0).mean()),
        spread_r=float(paid.mean()),
        values=got - paid,
        at=np.asarray(entries, dtype=np.int64),
    )




@dataclass(slots=True)
class Cell:
    """One combination, named so a row of output is reproducible from it."""

    family: str
    reading: str
    trigger: int
    reach: int
    level: float
    reward: float

    def label(self) -> str:
        knob = f"rsi{self.trigger}" if self.family == "rsi" else f"ma{self.trigger}"
        if self.family == "rsi":
            gate = f"{self.level:g}"
        else:
            gate = f"{self.level:g}atr" if self.reading == "ma_stretch" else "-"
        return f"{self.reading:<17} {knob:<7} mom{self.reach:<3} {gate:<6} R{self.reward:g}"


def cells(args: argparse.Namespace) -> list[Cell]:
    out: list[Cell] = []
    families = [f.strip() for f in args.families.split(",") if f.strip()]
    rewards = [float(v) for v in args.reward.split(",")]
    reaches = [int(v) for v in args.reach.split(",")]
    if "rsi" in families:
        for length in (int(v) for v in args.rsi.split(",")):
            for reach in reaches:
                for low in (float(v) for v in args.thresholds.split(",")):
                    for reading in RSI_READINGS:
                        for reward in rewards:
                            out.append(Cell("rsi", reading, length, reach, low, reward))
    if "ma" in families:
        stretches = [float(v) for v in args.stretch.split(",")]
        for length in (int(v) for v in args.ma.split(",")):
            for reach in reaches:
                for reading in MA_READINGS:
                    # **Only `ma_stretch` reads the stretch.** Sweeping it for
                    # the other three produced four bit-identical copies of
                    # every cell, which quadrupled the grid, filled the
                    # leaderboard with the same row four times, and made the
                    # multiplicity count meaningless in both directions.
                    levels = stretches if reading == "ma_stretch" else [0.0]
                    for level in levels:
                        for reward in rewards:
                            out.append(Cell("ma", reading, length, reach, level, reward))
    return out


@dataclass(slots=True)
class Readings:
    """Every indicator the grid needs, computed once per series.

    **Not once per cell.** Wilder's RSI is a Python loop, and recomputing it
    for each of 288 cells over 600,000 bars is 173 million iterations - the
    first version of this file did exactly that and did not finish. The cache
    is keyed on the only thing a cell varies: the period.
    """

    strength: dict[int, np.ndarray]
    push: dict[int, np.ndarray]

    @classmethod
    def of(cls, bars: Candles, band: np.ndarray, every: list[Cell]) -> Readings:
        lengths = {c.trigger for c in every if c.family == "rsi"}
        reaches = {c.reach for c in every}
        return cls(
            strength={n: rsi(bars.close, n) for n in lengths},
            push={k: momentum(bars.close, band, k) for k in reaches},
        )


def sided(
    bars: Candles,
    band: np.ndarray,
    cell: Cell,
    args: argparse.Namespace,
    cache: Readings,
) -> np.ndarray:
    push = cache.push[cell.reach]
    if cell.family == "rsi":
        return signals(cache.strength[cell.trigger], push, cell.reading, cell.level)
    return ma_signals(bars, band, push, cell.reading, cell.trigger, cell.level, args.fresh)


def trimmed(bars: Candles, days: float, back: float, warmup: int) -> Candles:
    """The two windows plus `warmup` bars before them, and nothing else.

    Every indicator is then computed on a series that starts well before the
    prior window, so a 100-bar average inside it is the real one - but on
    eleven thousand bars instead of six hundred thousand.
    """
    day = 86_400_000_000_000
    start = int(bars.ts[-1]) - int((days + back) * day)
    keep = np.flatnonzero(bars.ts >= start)
    if keep.size == 0:
        return bars
    first = max(int(keep[0]) - warmup, 0)
    return Candles(
        symbol=bars.symbol,
        frame=bars.frame,
        ts=bars.ts[first:],
        open=bars.open[first:],
        high=bars.high[first:],
        low=bars.low[first:],
        close=bars.close[first:],
    )


def benjamini(values: list[float], alpha: float = 0.10) -> int:
    """How many cells survive Benjamini-Hochberg at `alpha`, two-sided.

    Counted rather than listed: the point of the number is the multiplicity,
    and `0 of 288` is the whole finding when it is the finding. This desk once
    had 18 of 43 instruments nominally profitable where chance gives 22, and
    **not one** survived BH as profitable.
    """
    if not values:
        return 0
    from math import erfc, sqrt

    ranked = sorted(erfc(abs(t) / sqrt(2.0)) for t in values)
    best = 0
    for i, p in enumerate(ranked, start=1):
        if p <= alpha * i / len(ranked):
            best = i
    return best


def score(
    bars: Candles,
    band: np.ndarray,
    side: np.ndarray,
    inside: np.ndarray,
    cell: Cell,
    args: argparse.Namespace,
    cost: float,
) -> Result:
    """One cell's race, with entries confined to `inside`.

    A race entered on the last bar of the window is allowed to resolve past
    it. Truncating instead would charge every unresolved trade to the window it
    started in as a mark-out, and scoring an unresolved race wrongly is the
    fault that moved a headline by 0.37R in `persistence.md`.
    """
    confined = np.where(inside, side, 0).astype(np.int8)
    return race(bars, band, confined, args.stop, cell.reward, args.patience, cost)


def spans(bars: Candles, days: float, back: float) -> tuple[np.ndarray, np.ndarray, str]:
    """The ranking window and the one immediately before it, as masks.

    Masks rather than sliced series: every indicator is computed on the whole
    history first, so a 100-bar moving average inside a seven-day window is
    the real one and not a hundred bars of warm-up eating the window.
    """
    day = 86_400_000_000_000
    end = int(bars.ts[-1])
    recent_from = end - int(days * day)
    prior_from = recent_from - int(back * day)
    recent = bars.ts >= recent_from
    prior = (bars.ts >= prior_from) & (bars.ts < recent_from)
    from datetime import UTC, datetime

    first = datetime.fromtimestamp(recent_from / 1e9, UTC).date()
    last = datetime.fromtimestamp(end / 1e9, UTC).date()
    return recent, prior, f"{first} to {last}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", default=str(CATALOGUE))
    parser.add_argument("--symbols", default=",".join(SYMBOLS))
    parser.add_argument("--frames", default="5m,15m")
    parser.add_argument("--unit", default="5m")
    parser.add_argument("--days", type=float, default=7.0, help="the ranking window")
    parser.add_argument("--back", type=float, default=30.0, help="the window before it")
    parser.add_argument("--families", default="rsi,ma")
    parser.add_argument("--rsi", default="7,14,21")
    parser.add_argument("--ma", default="20,50,100")
    parser.add_argument("--reach", default="5,10,20")
    parser.add_argument("--thresholds", default="20,25,30,35")
    parser.add_argument("--stretch", default="1.0,1.5,2.0,2.5")
    parser.add_argument("--reward", default="1,2")
    parser.add_argument("--stop", type=float, default=1.0)
    parser.add_argument("--patience", type=int, default=48)
    parser.add_argument("--fresh", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=600, help="bars kept before the prior window")
    parser.add_argument("--least", type=int, default=12, help="trades a cell needs to be ranked")
    parser.add_argument("--show", type=int, default=12)
    args = parser.parse_args()

    every = cells(args)
    print(
        f"{len(every)} cells  families {args.families}  stop {args.stop} ATR  patience {args.patience}  "
        f"ranking window {args.days:g}d  prior window {args.back:g}d  minimum {args.least} trades"
    )

    for frame in (f.strip() for f in args.frames.split(",") if f.strip()):
        print(f"\n{'=' * 100}\n### {frame}\n{'=' * 100}")
        pooled: dict[int, list[np.ndarray]] = {}
        pooled_prior: dict[int, list[np.ndarray]] = {}
        best_shuffled = []
        for symbol in (s for s in args.symbols.split(",") if s):
            base = load(Path(args.catalogue), symbol)
            points, tick = SPREADS[symbol]
            cost = points * tick
            for arm in ("real", "shuffled"):
                series = shuffled(base, seed=23) if arm == "shuffled" else base
                # `RATIOS` has no identity entry, so the base frame is a
                # passthrough rather than a one-step fold.
                folded = series if frame == args.unit else fold(series, frame, unit=args.unit)
                bars = trimmed(folded, args.days, args.back, args.warmup)
                band = atr(bars)
                cache = Readings.of(bars, band, every)
                recent, prior, when = spans(bars, args.days, args.back)
                rows = []
                for index, cell in enumerate(every):
                    side = sided(bars, band, cell, args, cache)
                    here = score(bars, band, side, recent, cell, args, cost)
                    if here.trades < args.least:
                        continue
                    before = score(bars, band, side, prior, cell, args, cost)
                    rows.append((index, cell, here, before))
                    if arm == "real":
                        pooled.setdefault(index, []).append(here.values)
                        pooled_prior.setdefault(index, []).append(before.values)
                if not rows:
                    print(f"\n  {symbol} {arm}: no cell reached {args.least} trades")
                    continue
                rows.sort(key=lambda row: -row[2].net)
                if arm == "shuffled":
                    best_shuffled.append(rows[0][2].net)
                    print(
                        f"  {symbol} shuffled: best of {len(rows)} cells reads {rows[0][2].net:+.4f}R net "
                        f"on {rows[0][2].trades} trades - {rows[0][1].label()}"
                    )
                    continue
                print(f"\n  {symbol} {frame}, {when}, spread {points:g} points, {len(rows)} cells ranked")
                print(
                    "    combination                                      n   gross     net    hit  "
                    "spread |  prior n     net"
                )
                for _, cell, here, before in rows[: args.show]:
                    prior_net = f"{before.net:+.4f}" if before.trades >= args.least else "    thin"
                    print(
                        f"    {cell.label()} {here.trades:>5}  {here.gross:+.3f}  {here.net:+.4f}  "
                        f"{here.hit:.3f}  {here.spread_r:.3f} | {before.trades:>7}  {prior_net}"
                    )
        if not pooled:
            continue
        summary = []
        for index, parts in pooled.items():
            values = np.concatenate(parts)
            if values.size < args.least * 2:
                continue
            spread = values.std(ddof=1) / np.sqrt(values.size) if values.size > 1 else np.nan
            prior = np.concatenate(pooled_prior.get(index, [np.asarray([])]))
            summary.append(
                (
                    float(values.mean()),
                    index,
                    values.size,
                    float(values.mean() / spread) if spread and np.isfinite(spread) else 0.0,
                    float(prior.mean()) if prior.size >= args.least else float("nan"),
                    int(prior.size),
                )
            )
        summary.sort(key=lambda row: -row[0])
        names = [s for s in args.symbols.split(",") if s]
        print(f"\n  pooled over {len(names)} market(s), {len(summary)} cells")
        print(
            "    combination                                      n     net       t |  prior n     net"
        )
        for net, index, count, t, prior_net, prior_count in summary[: args.show]:
            shown = f"{prior_net:+.4f}" if np.isfinite(prior_net) else "    thin"
            print(
                f"    {every[index].label()} {count:>5}  {net:+.4f}  {t:+6.2f} | {prior_count:>7}  {shown}"
            )
        # BH over these cells is **anti-conservative and labelled as such**:
        # they share the same bars and many are near-duplicates, so the
        # p-values are far from independent. The number that does the work is
        # the shuffled arm's best-of-grid on the line below it.
        survivors = benjamini([row[3] for row in summary])
        kept = [row for row in summary if np.isfinite(row[4]) and row[0] > 0]
        held = [row for row in kept[: args.show] if row[4] > 0]
        print(
            f"\n    Benjamini-Hochberg at 0.10 over {len(summary)} pooled cells: {survivors} survive "
            f"- anti-conservative, the cells share bars and are not independent"
        )
        if best_shuffled:
            print(
                f"    best single-market cell on day-shuffled bars: "
                f"{max(best_shuffled):+.4f}R net (mean of the five {np.mean(best_shuffled):+.4f})"
            )
        print(
            f"    of the top {min(args.show, len(summary))} pooled cells, {len(held)} were also positive "
            f"in the prior {args.back:g} days"
        )


if __name__ == "__main__":
    main()
