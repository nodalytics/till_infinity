"""Over-stretched extremes on higher timeframes, and whether the reversal can be caught.

Run from the repository root:  python research/harness/stretch.py

The operator's hypothesis, in their words: markets that have **stretched too long** and are
**currently stalling or trying to reject**, and the stretch belongs on higher timeframes, not
lower ones.

That is two claims joined, and they are different in kind - which is the whole design of this
harness, because one of them already has evidence against it.

## What is already known, and why the test is still worth running

`breakout-runs.md` measured the hazard of reversal against how long a run had lasted:

| bars into the run | hazard per bar |
|---|---|
| 1-2 | 0.243 |
| 3-5 | 0.362 |
| 6-10 | 0.365 |
| 11-20 | 0.323 |

It **steps up after two bars and is then flat**. A flat hazard is memorylessness, and it says
runs do not exhaust with age. "Stretched too long" is an age claim, so it is the one this
already speaks against - though that was measured on hourly breakouts, and whether it holds
for a daily extreme is a separate question this answers directly.

**Stalling and rejecting are not age claims.** They are conditions on the present bar, and
nothing here has tested them. That is the part of the hypothesis genuinely open, and it is
why the ablation below scores stretch alone, trigger alone, and the conjunction.

## Stretch, six ways, and scored by decile rather than threshold

"Over-stretched" needs a cutoff, and picking one is how a study finds whatever it looks for.
So no cutoff is picked. Each measure is turned into a **causal percentile** - where the
current value ranks among the last `LOOKBACK` of its own history, never the whole series -
and the hit rate is reported per decile.

**If extension matters, the top decile differs from the rest and the pattern is monotone.** A
single good decile in the middle is noise, and that cannot be seen from a threshold test at
all.

| measure | what it is |
|---|---|
| `from_ma` | distance from the moving average, in true ranges |
| `run` | consecutive bars closing in the trend direction |
| `from_swing` | travel since the last confirmed swing, in true ranges |
| `since_turn` | bars since the series last made an extreme the other way |
| `z_cum` | cumulative return over the window, in its own standard deviations |
| `from_fit` | distance from a least-squares line, in residual sigmas |

`since_turn` is the direct test of "too long"; `from_ma` and `from_fit` are the direct tests
of "too far". Separating them matters, because time and distance are not the same claim and
the operator's phrasing contains both.

## Stalling and rejecting, five ways

| trigger | what it is |
|---|---|
| `stall` | this bar's range under `STALL` of the recent average - momentum gone |
| `reject` | a wick of at least `WICK` TR beyond the extreme, closing back inside |
| `no_new` | `QUIET` bars without extending the extreme |
| `engulf` | close back through the previous bar's open, against the trend |
| `any` | any of the four |

## Higher timeframes, folded on the clock

Hourly bars are folded into 4h, 8h, 1d and 2d buckets on **clock boundaries**, so a 4h bar
here is the 4h bar on a chart rather than an arbitrary four-bar group. Lower timeframes are
included only as the control the operator's claim implies: if the stretch belongs on higher
timeframes, then 1h should be visibly worse, and that is a prediction to check rather than an
assumption to encode.

## What makes a result

The trade is counter-trend from the close, with **stop and target both one true range**, so
fair odds is 50% for every row and no geometry can explain an outcome - the confound that
decided `premium_discount.py` across 314,794 rows.

Costs are charged at the measured figures, not assumed: **0.063 TR of stop slippage**, from
305 live stop-outs in the journal, and the spread from `spread_cost.py`.

Two comparisons, and the second is the one that matters:

* against **fair odds**, which says whether the cell beats a coin;
* against the **unconditional counter-trend trade on the same instrument and timeframe**,
  which says whether the stretch condition added anything. A counter-trend trade on a drifting
  instrument inherits the drift, and without this column that drift reads as skill.

Both barriers inside one bar counts as a stop, as everywhere here.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "training"))

import candles  # noqa: E402
import imbalance  # noqa: E402

#: Timeframes, as (label, seconds). 1h is the control the hypothesis predicts is worse.
LADDER = (("1h", 3600), ("4h", 4 * 3600), ("8h", 8 * 3600), ("1d", 86400), ("2d", 2 * 86400))

#: Window for the moving average, the regression fit and the cumulative return.
SPAN = 20

#: History a percentile is taken against. Causal - only the past.
LOOKBACK = 250

#: Bars either side of a confirmed swing.
SWING = 3

#: Trigger parameters.
STALL = 0.6
WICK = 0.5
QUIET = 3

#: Bars allowed to resolve, in bars of the timeframe being tested.
HORIZON = 24

#: Measured costs, in true ranges. Slippage is the live figure from 305 stop-outs in the
#: journal - see `costs.md`; it is charged only on the losers, where it is paid.
SLIPPAGE = 0.063
SPREAD = {"boom": 0.004, "crash": 0.004, "volatility": 0.004, "default": 0.020}


def rolling_rank(values: np.ndarray, window: int = LOOKBACK) -> np.ndarray:
    """Where each value sits among the previous `window`, as 0..1. Causal.

    `nan` until there is a history to rank against, which keeps the warm-up out of the
    deciles rather than piling it into the bottom one.
    """
    n = len(values)
    out = np.full(n, np.nan)
    for i in range(window, n):
        past = values[i - window : i]
        good = past[np.isfinite(past)]
        if len(good) < window // 2 or not np.isfinite(values[i]):
            continue
        out[i] = float((good < values[i]).mean())
    return out


def swings(bars: np.ndarray, k: int = SWING):
    """Running last confirmed swing high and low, delayed by `k`."""
    high, low = bars[:, 2], bars[:, 3]
    n = len(bars)
    hi = np.full(n, np.nan)
    lo = np.full(n, np.nan)
    hi_now = lo_now = np.nan
    for i in range(k, n - k):
        j = i - k
        if j >= k:
            if high[j] >= high[j - k : j + k + 1].max():
                hi_now = float(high[j])
            if low[j] <= low[j - k : j + k + 1].min():
                lo_now = float(low[j])
        hi[i], lo[i] = hi_now, lo_now
    return hi, lo


def measures(bars: np.ndarray, tr: np.ndarray) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """The trend direction at each bar, and each stretch measure as a magnitude in it."""
    high, low, close = bars[:, 2], bars[:, 3], bars[:, 4]
    n = len(bars)
    unit = tr * np.maximum(close, 1e-12)
    unit[unit <= 0] = np.nan

    ma = np.full(n, np.nan)
    for i in range(SPAN, n):
        ma[i] = close[i - SPAN : i].mean()
    trend = np.sign(close - ma)

    from_ma = (close - ma) / unit * trend

    # Consecutive closes in the trend direction.
    step = np.sign(np.diff(close, prepend=close[0]))
    run = np.zeros(n)
    for i in range(1, n):
        run[i] = run[i - 1] + 1 if step[i] == trend[i] and step[i] != 0 else 0.0

    hi, lo = swings(bars)
    from_swing = np.where(trend > 0, close - lo, hi - close) / unit

    # Bars since the series last made an extreme the other way - the "too long" measure.
    since_turn = np.zeros(n)
    for i in range(1, n):
        made = (
            (low[i] <= np.nanmin(low[max(i - SPAN, 0) : i + 1]))
            if trend[i] > 0
            else (high[i] >= np.nanmax(high[max(i - SPAN, 0) : i + 1]))
        )
        since_turn[i] = 0.0 if made else since_turn[i - 1] + 1.0

    cum = np.full(n, np.nan)
    z_cum = np.full(n, np.nan)
    from_fit = np.full(n, np.nan)
    x = np.arange(SPAN, dtype=float)
    x = x - x.mean()
    denom = float(x @ x)
    for i in range(SPAN + SPAN, n):
        window = close[i - SPAN + 1 : i + 1]
        rets = np.diff(np.log(np.maximum(window, 1e-12)))
        sd = float(rets.std(ddof=1)) if len(rets) > 2 else 0.0
        cum[i] = float(np.log(max(close[i], 1e-12) / max(close[i - SPAN], 1e-12)))
        if sd > 0:
            z_cum[i] = cum[i] / (sd * np.sqrt(SPAN)) * trend[i]
        y = window - window.mean()
        slope = float(x @ y) / denom if denom > 0 else 0.0
        resid = y - slope * x
        rs = float(resid.std(ddof=2)) if len(resid) > 2 else 0.0
        if rs > 0:
            from_fit[i] = float(resid[-1]) / rs * trend[i]

    return trend, {
        "from_ma": from_ma,
        "run": run,
        "from_swing": from_swing,
        "since_turn": since_turn,
        "z_cum": z_cum,
        "from_fit": from_fit,
    }


def triggers(bars: np.ndarray, tr: np.ndarray, trend: np.ndarray) -> dict[str, np.ndarray]:
    """Is this bar stalling, or trying to reject?"""
    opens, high, low, close = bars[:, 1], bars[:, 2], bars[:, 3], bars[:, 4]
    n = len(bars)
    unit = tr * np.maximum(close, 1e-12)
    rng = high - low
    mean_rng = np.full(n, np.nan)
    for i in range(SPAN, n):
        mean_rng[i] = rng[i - SPAN : i].mean()

    stall = rng < STALL * mean_rng
    # The wick that took the extreme while the body did not hold it.
    wick = np.where(trend > 0, high - np.maximum(opens, close), np.minimum(opens, close) - low)
    reject = wick >= WICK * unit
    engulf = np.where(trend > 0, close < opens, close > opens) & (
        np.where(trend > 0, close < np.roll(opens, 1), close > np.roll(opens, 1))
    )
    no_new = np.zeros(n, dtype=bool)
    for i in range(QUIET + 1, n):
        if trend[i] > 0:
            no_new[i] = high[i - QUIET : i + 1].max() <= high[i - QUIET - 1]
        else:
            no_new[i] = low[i - QUIET : i + 1].min() >= low[i - QUIET - 1]

    out = {"stall": stall, "reject": reject, "no_new": no_new, "engulf": engulf}
    out["any"] = stall | reject | no_new | engulf
    out["none"] = ~out["any"]
    return out


def resolve(bars: np.ndarray, tr: np.ndarray, at: int, side: int, horizon: int) -> int:
    """+1 target first, -1 stop first, 0 neither. Both in one bar is a stop."""
    close, high, low = bars[:, 4], bars[:, 2], bars[:, 3]
    here = close[at]
    unit = tr[at] * max(here, 1e-12)
    if unit <= 0:
        return 0
    target, stop = here + side * unit, here - side * unit
    for step in range(1, horizon + 1):
        i = at + step
        if i >= len(bars):
            return 0
        if side > 0:
            hit_t, hit_s = high[i] >= target, low[i] <= stop
        else:
            hit_t, hit_s = low[i] <= target, high[i] >= stop
        if hit_t and hit_s:
            return -1
        if hit_t:
            return 1
        if hit_s:
            return -1
    return 0


def study(bars: np.ndarray, tally: dict, base: dict, label: str, horizon: int) -> int:
    tr = candles.true_range(bars)
    trend, stretch = measures(bars, tr)
    fires = triggers(bars, tr, trend)
    ranks = {name: rolling_rank(values) for name, values in stretch.items()}
    counted = 0
    start = max(LOOKBACK + SPAN * 2, SWING * 2 + 2)

    for at in range(start, len(bars) - horizon):
        side = -int(trend[at])  # counter-trend: fade the stretch
        if side == 0:
            continue
        got = resolve(bars, tr, at, side, horizon)
        if got == 0:
            continue
        counted += 1
        base[label].append(got > 0)
        for name, rank in ranks.items():
            r = rank[at]
            if not np.isfinite(r):
                continue
            decile = min(int(r * 10), 9)
            tally[(label, name, decile, "all")].append(got > 0)
            for trig, fired in fires.items():
                if fired[at]:
                    tally[(label, name, decile, trig)].append(got > 0)
    return counted


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    # `SYMBOLS` because `lab.sh run` forwards environment and not arguments; commas,
    # never spaces, since that forwarding goes through an unquoted `$*`.
    ap.add_argument(
        "symbols",
        nargs="*",
        default=[s.strip() for s in os.environ.get("SYMBOLS", "").split(",") if s.strip()]
        or ["xauusd", "eurusd", "gbpusd", "usdjpy", "boom_1000_index", "crash_1000_index"],
    )
    ap.add_argument("--where", default=os.environ.get("WHERE", ".secrets/broker-deep"))
    ap.add_argument("--horizon", type=int, default=HORIZON)
    args = ap.parse_args()

    print(
        "counter-trend from the close, stop and target both one true range, so fair odds\n"
        f"is 50.0% for every row. Slippage charged at the live {SLIPPAGE:.3f} TR on losers.\n"
    )
    tally: dict[tuple, list] = defaultdict(list)
    base: dict[str, list] = defaultdict(list)

    for symbol in args.symbols:
        found = sorted(Path(args.where).expanduser().glob(f"{symbol}_1h_broker.csv.gz"))
        if not found:
            print(f"{symbol:<22} no 1h file")
            continue
        hourly, _repaired = candles.read(found[0])
        if len(hourly) < 5000:
            continue
        for name, seconds in LADDER:
            folded = hourly if seconds == 3600 else imbalance.fold(hourly, seconds)
            if len(folded) < LOOKBACK + SPAN * 3 + args.horizon + 200:
                continue
            n = study(folded, tally, base, name, args.horizon)
            print(f"  {symbol:<22}{name:>5}{len(folded):>8,} bars{n:>9,} trades")

    cost = SPREAD["default"]
    print(
        "\n  net is after spread and slippage; excess is against the unconditional\n"
        "  counter-trend trade on the same timeframe - the column that separates the\n"
        "  condition from the instrument's own drift.\n"
        f"\n  {'tf':<4}{'measure':<12}{'dec':>4}{'trigger':<9}{'n':>8}"
        f"{'hit':>7}{'net R':>8}{'vs plain':>10}{'+/-':>7}"
    )
    plain = {k: float(np.mean(v)) for k, v in base.items() if len(v) >= 500}
    rows = []
    for (label, name, decile, trig), got in tally.items():
        if len(got) < 400 or label not in plain:
            continue
        won = np.array(got, dtype=float)
        hit = float(won.mean())
        net = hit * 1.0 - (1 - hit) * (1.0 + SLIPPAGE) - cost
        band = 2.0 * float(np.sqrt(hit * (1 - hit) / len(won)))
        rows.append((hit - plain[label], label, name, decile, trig, len(won), hit, net, band))

    for excess, label, name, decile, trig, n, hit, net, band in sorted(rows, reverse=True)[:18]:
        mark = "  <-" if abs(excess) > band else ""
        print(
            f"  {label:<4}{name:<12}{decile:>4}{trig:<9}{n:>8,}"
            f"{hit:>7.1%}{net:>+8.3f}{excess:>+10.2%}{band:>7.2%}{mark}"
        )

    print("\n  is more stretch better? mean excess by decile, over every measure and trigger:")
    by_decile: dict[tuple[str, int], list[float]] = defaultdict(list)
    for excess, label, _name, decile, _trig, *_rest in rows:
        by_decile[(label, decile)].append(excess)
    for label, _s in LADDER:
        line = f"  {label:<4}"
        for decile in range(10):
            got = by_decile.get((label, decile), [])
            line += f"{np.mean(got):>+8.2%}" if got else f"{'-':>8}"
        print(line)
    print(f"  {'':<4}" + "".join(f"{f'd{d}':>8}" for d in range(10)))

    print(
        f"\n  {len(rows)} cells scored, so about {0.05 * len(rows):.0f} clear a two-sigma bar\n"
        "  by chance. The decile table is the real reading: extension only means\n"
        "  something if the top deciles beat the bottom ones and do it monotonically.\n"
        "  A single good cell in the middle is noise however large it looks.\n"
        "\n  The prediction to check: the operator says the stretch belongs on higher\n"
        "  timeframes, so 1h should be visibly worse than 1d. If every row is flat, the\n"
        "  flat hazard in breakout-runs.md holds for daily extremes too."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
