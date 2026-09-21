"""Drift conditional on a level event - the class `(6)` does not rule out.

Run from the repository root:  python research/harness/level_events.py

`barrier-geometry-is-irrelevant.md` derived that a barrier trade earns `m = mu E[tau]` and
nothing else, and that was read here as killing every level-based study. **That reading was too
broad, and the correction matters.**

`(6)` says where *you* put your stop and target cannot produce expectancy. It says nothing about
whether drift is predictable **conditional on a level event having occurred**. Those are
different claims, and only the first was tested.

So `smc.py` measured liquidity sweeps with the wrong statistic: it scored them as barrier trades
against fair odds, which `(6)` now says was guaranteed to return nothing whatever the sweep meant.
The right test is whether the **mean forward return** after a sweep differs from zero, with market
exits so `E = m` holds exactly.

## The hypotheses, each from a stated source

**Sweep reversal.** Price trades through a confirmed prior extreme and closes back inside it - the
wick takes the level, the body does not hold. Predict a move against the sweep. From a
retired system that calls this "sweep prediction": predict which bound gets hit first, then take
the opposite stance once it is hit.

**New extreme, then a fall.** The operator's hypothesis: each time a new high is made, especially
one never seen before, a crash is next or looming. Tested at three strengths - a new high over 500
bars, over 2000, and a **new highest close in the entire history so far**, which is the closest
this data comes to "never seen before".

**Compression.** True range collapsing before expansion. Included as a control that should fail:
compression predicts the *size* of the next move, and `(6)` needs its *sign*. If it scores, the
scoring is wrong somewhere.

## Design, following what the last few runs taught

**Market exit, no stop**, so `(6)` applies exactly and the measured mean return is `m`. A stop
would reintroduce the overshoot terms and measure something else.

**Scored against the same instrument's unconditional drift** over the same horizon. This is not
optional here: an instrument in a decade-long uptrend makes new highs constantly and keeps rising,
so "new high then falls" would fail on gold and succeed on nothing for reasons that have nothing
to do with the hypothesis. The `vs uncond` column is the hypothesis; the raw mean is not.

**The period split runs first, not last.** That is the method note from the efficiency candidate,
which measured +0.0861 over the early half and -0.0308 over the late half and was only caught
because the split was eventually run. Any effect that lives in one half is reported as decayed
rather than as a finding.

**The detection floor is stated before the run.** Mean-return test, so the floor is
`(z + z_beta) sigma / sqrt(n)` with `n` the count of independent events - and events are rare, so
this is where most of these will die. Each row prints its own count against what it would need.
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

#: Horizons in bars, market exit.
HOLDS = (6, 24, 96)

#: Bars either side of a confirmed swing.
SWING = 5

#: Lookbacks for "a new extreme".
NEW_HIGH = (500, 2000)

#: Compression: true range below this fraction of its own recent median.
SQUEEZE = 0.6
SQUEEZE_WINDOW = 50

#: Measured costs, in true ranges.
SPREAD = {"boom": 0.004, "crash": 0.004, "volatility": 0.004, "default": 0.020}

DRAWS = 400


def events(bars: np.ndarray, tr: np.ndarray) -> dict[str, list[tuple[int, int]]]:
    """Every level event, as `name -> [(bar index, predicted direction)]`."""
    high, low, close = bars[:, 2], bars[:, 3], bars[:, 4]
    n = len(bars)
    out: dict[str, list[tuple[int, int]]] = defaultdict(list)

    # Running confirmed swings, delayed by SWING so nothing uses the future.
    last_hi = np.full(n, np.nan)
    last_lo = np.full(n, np.nan)
    hi_now = lo_now = np.nan
    for i in range(SWING, n - SWING):
        j = i - SWING
        if j >= SWING:
            if high[j] >= high[j - SWING : j + SWING + 1].max():
                hi_now = float(high[j])
            if low[j] <= low[j - SWING : j + SWING + 1].min():
                lo_now = float(low[j])
        last_hi[i], last_lo[i] = hi_now, lo_now

    running_max = np.maximum.accumulate(close)
    running_min = np.minimum.accumulate(close)
    med_tr = np.full(n, np.nan)
    for i in range(SQUEEZE_WINDOW, n):
        med_tr[i] = np.median(tr[i - SQUEEZE_WINDOW : i])

    for at in range(max(SWING * 2, SQUEEZE_WINDOW) + 1, n - max(HOLDS) - 1):
        hi, lo = last_hi[at], last_lo[at]
        # Sweep: the wick takes the level, the close does not hold it. Trade against it.
        if np.isfinite(hi) and high[at] > hi and close[at] < hi:
            out["sweep high (predict down)"].append((at, -1))
        if np.isfinite(lo) and low[at] < lo and close[at] > lo:
            out["sweep low (predict up)"].append((at, 1))

        # A new extreme over a lookback, and the operator's claim that a fall follows.
        for span in NEW_HIGH:
            if at > span and close[at] >= close[at - span : at].max():
                out[f"new {span}-bar high (predict down)"].append((at, -1))
            if at > span and close[at] <= close[at - span : at].min():
                out[f"new {span}-bar low (predict up)"].append((at, 1))

        # Never seen before in this history at all.
        if at > 200 and close[at] >= running_max[at - 1]:
            out["new all-time high (predict down)"].append((at, -1))
        if at > 200 and close[at] <= running_min[at - 1]:
            out["new all-time low (predict up)"].append((at, 1))

        # Control that should fail: compression has no direction.
        if np.isfinite(med_tr[at]) and med_tr[at] > 0 and tr[at] < SQUEEZE * med_tr[at]:
            out["compression (control, up)"].append((at, 1))
    return out


def forward(bars: np.ndarray, tr: np.ndarray, at: int, side: int, hold: int) -> float:
    """Return in true ranges at entry, market exit after `hold` bars, no stop."""
    close = bars[:, 4]
    unit = tr[at] * max(close[at], 1e-12)
    if unit <= 0 or at + hold >= len(close):
        return float("nan")
    return float(side * (close[at + hold] - close[at]) / unit)


def block_error(values: np.ndarray, hold: int, seed: int = 0) -> float:
    size = max(hold * 3, 12)
    n = len(values)
    if n < size * 3:
        return float("nan")
    rng = np.random.default_rng(seed)
    count = int(np.ceil(n / size))
    means = np.empty(DRAWS)
    for d in range(DRAWS):
        picks = rng.integers(0, n - size, size=count)
        means[d] = np.concatenate([values[i : i + size] for i in picks])[:n].mean()
    return float(means.std())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "symbols",
        nargs="*",
        default=[s.strip() for s in os.environ.get("SYMBOLS", "").split(",") if s.strip()]
        or ["xauusd", "eurusd", "boom_1000_index"],
    )
    ap.add_argument("--where", default=os.environ.get("WHERE", ".secrets/broker-deep"))
    ap.add_argument("--interval", default="1h")
    args = ap.parse_args()

    # name -> hold -> half -> list of returns; plus the unconditional baseline per half.
    tally: dict[tuple[str, int, str], list[float]] = defaultdict(list)
    base: dict[tuple[int, str, int], list[float]] = defaultdict(list)
    cost_of: list[float] = []

    for symbol in args.symbols:
        found = sorted(Path(args.where).expanduser().glob(f"{symbol}_{args.interval}_*.csv.gz"))
        if not found:
            print(f"  {symbol:<24} no {args.interval} file")
            continue
        bars, _repaired = candles.read(found[0])
        if len(bars) < 10_000:
            continue
        tr = candles.true_range(bars)
        cost_of.append(next((v for k, v in SPREAD.items() if k in symbol), SPREAD["default"]))
        mid = len(bars) // 2
        found_events = events(bars, tr)
        for name, hits in found_events.items():
            for at, side in hits:
                half = "early" if at < mid else "late"
                for hold in HOLDS:
                    got = forward(bars, tr, at, side, hold)
                    if np.isfinite(got):
                        tally[(name, hold, half)].append(got)
        # Unconditional drift in each direction and half, the comparison that matters.
        for at in range(200, len(bars) - max(HOLDS) - 1, 12):
            half = "early" if at < mid else "late"
            for hold in HOLDS:
                for side in (1, -1):
                    got = forward(bars, tr, at, side, hold)
                    if np.isfinite(got):
                        base[(side, half, hold)].append(got)
        print(f"  {symbol:<24}{sum(len(v) for v in found_events.values()):>9,} events")

    cost = float(np.mean(cost_of)) if cost_of else 0.02
    print(
        "\nmean forward return in true ranges, market exit, no stop - so this is m\n"
        f"pooled spread {cost:.3f} TR; `vs uncond` is against the same direction's drift\n"
        f"\n  {'event':<34}{'hold':>5}{'n early':>9}{'m early':>9}{'n late':>8}{'m late':>9}"
        f"{'vs uncond':>11}{'+/-':>8}"
    )

    for name in sorted({k[0] for k in tally}):
        side = 1 if "up" in name else -1
        for hold in HOLDS:
            early = np.array(tally.get((name, hold, "early"), []))
            late = np.array(tally.get((name, hold, "late"), []))
            if len(early) < 100 or len(late) < 100:
                continue
            both = np.concatenate([early, late])
            ref = np.array(base.get((side, "early", hold), []) + base.get((side, "late", hold), []))
            edge = float(both.mean() - ref.mean()) if len(ref) else float("nan")
            err = block_error(both, hold)
            mark = "  <-" if np.isfinite(err) and abs(edge) > 2 * err else ""
            print(
                f"  {name:<34}{hold:>5}{len(early):>9,}{early.mean():>+9.3f}"
                f"{len(late):>8,}{late.mean():>+9.3f}{edge:>+11.3f}"
                f"{2 * err if np.isfinite(err) else np.nan:>8.3f}{mark}"
            )

    print(
        "\n  **Read `m early` against `m late` first.** An effect in one half and not the other\n"
        "  is decayed, and a decayed edge is not an edge - that is what killed the directional\n"
        "  efficiency candidate and it was only caught because the split was eventually run.\n"
        "\n  Then read `vs uncond`, which is the hypothesis. A new-high event on an instrument\n"
        "  that rose for a decade will show a positive raw mean whatever the hypothesis says;\n"
        "  only the excess over that instrument's own drift is evidence.\n"
        "\n  `compression` is a control and should not score: it predicts the size of the next\n"
        "  move, not its sign, and (6) needs the sign."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
