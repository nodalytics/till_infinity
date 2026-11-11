"""Dual Thrust: is the edge in the side, or in the distance, or in the range?

    ./.secrets/lab.sh run research/ideas/dualthrust.py MODE=cost
    ./.secrets/lab.sh run research/ideas/dualthrust.py MODE=leak  DT_WORKERS=16
    ./.secrets/lab.sh run research/ideas/dualthrust.py MODE=main  DT_WORKERS=16
    ./.secrets/lab.sh run research/ideas/dualthrust.py MODE=sweep DT_WORKERS=16
    ./.secrets/lab.sh run research/ideas/dualthrust.py MODE=power DT_WORKERS=16 \
        DT_NULLS=reflect DT_SURROGATES=4

Always with `OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1`: this
runs a process pool and `one-thread-per-pool-worker` is the recorded reason.

`cost` runs first and is allowed to end the study: it prices the round trip in
the only unit this rule has, and it ended two thirds of the 15m half.
`leak` runs the null arms alone with no real arm at all, and it is the mode
that found this study's central measurement problem - the arms do **not** read
zero, and which ones do not is the result. `main` is the study. `sweep` is the
multiplicity surface, with its own null, because without one it reported a
`z +12.3` artefact. `power` plants a continuation and says where the test goes
blind. Cells land in `out/dualthrust/cells-<mode>.csv`.

**`lab.sh run` rsyncs the repository with `--delete`**, so a second agent
syncing its own worktree removes this file from `repo/` and a later launch
cannot find it. It happened to the harness this one borrows `walk_path` from,
twice. Stage it outside `repo/` and put `repo` on `PYTHONPATH`:

    rsync -az -e "$HOME/.cache/till-lab-ssh" research/ideas/dualthrust.py \
      "$HOST:till_infinity/stage/"
    ./.secrets/lab.sh exec 'cd $HOME/till_infinity && OMP_NUM_THREADS=1 \
      MODE=main DT_WORKERS=16 PYTHONPATH=$HOME/till_infinity/repo \
      nohup .venv/bin/python -u stage/dualthrust.py > logs/dt-main.log 2>&1 &'

and then `md5sum` the remote copy against the local one, because
`failed-sync-still-launches-the-run` applies. **Not** `cat file | lab.sh exec
'cat > ...'`: `lab.sh` probes the direct route with `ssh ... true` before it
runs anything, that probe consumes standard input, and the file arrives empty
with `md5` `d41d8c...` and no error. It happened here.

## The rule, as published, and the one thing the source never did

Over the last `N` daily bars take `HH`, `LL`, `HC`, `LC` and

    range = max(HH - LC, HC - LL)
    cap   = today's open + K1 * range
    floor = today's open - K2 * range

It is a reversal system: at or above the cap it is 100% long, at or below the
floor 100% short, liquidating the other side first. There is **no separate
exit** - a trade ends when the opposite trigger fires - and the published
defaults `N = 4`, `K1 = K2 = 0.5` are called "for demonstration" and are
**never swept**. So `N = 4, K = 0.5` is the pre-registered headline here and
the sweep is reported as a multiplicity count, not as the result.

## Why this is worth measuring when the source reports Sharpe -0.17

The source reports SPY Sharpe **-0.17** at a **41.1%** maximum drawdown while
its abstract says it "beat the market", models no costs and runs no control, so
there is no result to reproduce. What is worth measuring is the **shape**: the
trigger distance is scaled by a *measured range*, and the range is the
strongest volatility reading on this desk (`drive-q-from-the-range`: the
range-vs-close estimator ratio is 0.648 within strata on FX and 0.667 on 371 of
392 equities, and grows as the window shortens).

So the primary result is a decomposition into three columns:

* **`real`** - the rule.
* **`coin`** - the identical trigger distances firing at the identical times
  with the long/short choice randomised. If `real` matches `coin` the rule
  carries no directional information. `direction-is-closed-not-just-null` says
  it will, so a side result is to be disbelieved before it is believed.
* **`const`** - the same geometry with `range` replaced by a constant fixed on
  a training block. This is the arm that says whether the *range* is doing the
  work or whether any distance of that size would do.

## The unit, which has to be stated because the rule has no stop

There is no stop, so R is undefined. The unit is the **trigger distance**
`K * range` at the bar that opened the trade, which is also what a round trip
divides into. `risk-vol-is-not-the-stop-distance` is why it is the rule's own
distance and not a volatility feature. Two columns carry it:

* `mean_u` - per trade, in the arm's **own** trigger distance. This is the
  risk the rule takes, and the denominator the cost ceiling of 0.16 applies to.
* `mean_c` - per trade in a **common** unit, the instrument's median single-bar
  range, fixed per (instrument, clock) and identical across arms. `real` and
  `const` have different trigger distances by construction, so without a common
  unit their `mean_u` are not comparable and a difference between them is
  partly a difference of denominators.

## The null, and why the Brownian bridge is not it for this rule

`walk_with_bar_geometry` is out, and its own docstring says why: it places each
bar's open inside the bar's own range, so it gaps 0.60-0.64 of a range at every
bar against this market's median `|gap|` of 0.0000 on 71-79% of bars, and a
rule triggered at `open +- K * range` would fire on nearly every bar of it and
fill at the planted gap.

`entry_timing.walk_path` - a Brownian bridge of sub-steps pinned to a real
close-to-close step - was the arm this study was briefed to use, and
`breaker-blocks.md` records it reproducing a 2R race's arithmetic rate at
0.3285 against 0.3333 where the broken arm read 0.3022. **Measured here it is
not a null for this rule**, and the reason is specific to this rule rather than
a criticism of that one:

* On a clean **Gaussian** walk the bridge is exactly a Brownian motion, and the
  rule reads `+0.1936, +0.0983, +0.0300, -0.0035` units a trade at 30, 120, 480
  and 1920 sub-steps. So the machinery is right - at a resolved path the
  arithmetic null is zero, as optional stopping requires - and the residual at
  a coarse path is the overshoot past a trigger between two visited points.
* Pinned to **real** steps it is not a Brownian motion, because the free
  excursion inside each bar carries the full step **standard deviation** while
  the pin is drawn from a heavy-tailed empirical distribution. So a quiet bar
  comes out as wicky as a violent one. Median range over median `|step|` is
  **2.37** on EURUSD against the bridge's **3.23**, 2.45 against **5.43** on
  gold and 2.35 against **7.53** on silver - and the rule reads `-0.10`,
  `-0.59` and `-0.91` units a trade there, worse at 480 sub-steps than at 120,
  so it is the geometry and not the discreteness.

A rule whose trigger distance **is** a function of the bar range cannot be
nulled by an arm that gets the bar range wrong, however well calibrated that
arm is for a fixed barrier. So the headline null is `reflect`: every real bar
kept exactly as it is, its direction coined, the gaps carried, the path laid
back out continuous. It reproduces the range, the `|step|` distribution, the
clustering, the kurtosis and the gap-zero share to three figures, and it
destroys the direction and only the direction. `shuffle` adds a permutation of
the bar order, which removes the clustering too, so the pair say whether an
offset is the clustering.

**And the nulls are not centred on zero, which is the reason they are run.**
A bar is four numbers and the rule fills at a trigger inside `[low, high]`, so
it is assumed reachable with no intra-bar path to check it against. That is
worth about `+0.03` to `+0.06` units a trade, it is identical on the real arm
and on an arm with no direction in it at all, and it means **`real - reflect`
is the statistic and `real` against zero is not**. The trade-level coin arm is
in the same position: on EURUSD the direction-free `reflect` series beats its
own coin at `z +4.37`.

## The trap specific to this rule

Because it is always in the market the trades **tile** the series back to back,
so there is no outcome overlap to de-overlap. There is also **no flat state**:
the duty cycle is 1.0 by construction and the comparison against any null is a
comparison of two always-invested series. Nothing here needs a duty-cycle twin
and nothing here can have one. `strategy-rotation-is-not-timeable` is why any
*variant* that sits out would have to be compared at its own duty cycle
instead, and no variant here does.

## Three things in the fill model that a sign error would hide

**A trigger fills at the trigger price, not the close.** The cap and the floor
are limit prices the bar reached; filling at the bar's close would credit the
rule with the rest of the bar's move and is the shape that read +0.432R on a
driftless walk in `smc-conjunctions.md`.

**Both triggers can be reached in one bar, and the published rule has no
tiebreak.** The order the path touched them in is unobservable, and the choice
is not cosmetic: the first version of this file fired the nearer trigger first
and then the other, which with `K1 == K2` made the position end on the *second*
trigger in a fixed order - a systematic short bias on every whipsaw bar, and on
a hand-built momentum fixture it ended short on every up-expansion. So the
default is `once`: a reversal system liquidates and goes 100% the other way,
once, so a bar that reaches both triggers reverses the position and stops. That
is symmetric in the side by construction. `DT_INTRABAR=close` fires both and
ends on the side the bar closed, `adverse` fires both and ends on the other
side; the two bracket the convention and the write-up reports the spread.
`same_bar` counts the bars where any of it matters.

**The range window is strictly prior.** `HH`, `LL`, `HC`, `LC` are taken over
bars `i-N .. i-1`, never including bar `i`, whose own high is what triggers the
entry. Including it would be a one-bar look-ahead that makes the cap a function
of the excursion that is supposed to reach it.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import random
import sqlite3
import statistics as st
from dataclasses import dataclass
from multiprocessing import Pool
from pathlib import Path

import numpy as np

from research.harness.entry_timing import walk_path
from research.ideas.level_shield import Series, units

HOME = Path.home()
SEQLAB = Path(os.environ.get("DT_SEQLAB") or HOME / "till_infinity/data/seqlab")
SYN = Path(os.environ.get("DT_SYN") or HOME / "till_infinity/data/syn")
WIDE = Path(os.environ.get("DT_WIDE") or HOME / "till_infinity/data/btc")
STORE = os.environ.get("DT_STORE") or str(HOME / "till_infinity/.data/prices/prices.db")
OUT = Path(os.environ.get("DT_OUT") or HOME / "till_infinity/out/dualthrust")

MODE = os.environ.get("MODE", "main")
WORKERS = int(os.environ.get("DT_WORKERS") or 12)
SEED = int(os.environ.get("DT_SEED") or 20261110)

#: The published cell, and the headline. Reported before any sweep.
N0 = int(os.environ.get("DT_N") or 4)
K0 = float(os.environ.get("DT_K") or 0.5)

#: Swept **separately** from the published cell, not as a grid: the source
#: fixes both parameters, so the honest count of tests is the two lines through
#: the published point rather than their product.
N_GRID = tuple(int(x) for x in (os.environ.get("DT_N_GRID") or "2,4,6,10,20").split(","))
K_GRID = tuple(float(x) for x in (os.environ.get("DT_K_GRID") or "0.2,0.3,0.5,0.7,1.0").split(","))

#: Side-shuffle draws per cell. The coin's expectation is exactly zero, so
#: these are for the **spread** of the null mean rather than its centre.
DRAWS = int(os.environ.get("DT_DRAWS") or 400)

#: Block-bootstrap draws, over contiguous runs of trades. The trades tile, so
#: consecutive outcomes share a volatility regime and an ordinary standard
#: error is too narrow.
BOOT = int(os.environ.get("DT_BOOT") or 2000)

#: Surrogate series per real one, per null arm.
SURROGATES = int(os.environ.get("DT_SURROGATES") or 6)

#: And in the sweep, where there are nine times as many cells.
SWEEP_DRAWS = int(os.environ.get("DT_SWEEP_DRAWS") or 3)

#: Which null arms run, the first being the headline. `reflect` is the matched
#: one - the real bars, the real clustering, a coined direction; `shuffle`
#: removes the clustering as well; `walk-path` is kept beside them because it
#: disagrees with both, and the disagreement is a result.
NULLS = tuple((os.environ.get("DT_NULLS") or "reflect,shuffle,walk-path").split(","))

#: The fraction of the series used to fix the `const` arm's distance. Causal:
#: the constant is the median measured range over the first `TRAIN` of bars and
#: is then frozen, so no trade is sized by a range measured after it.
TRAIN = float(os.environ.get("DT_TRAIN") or 0.2)

#: How a bar that reaches both triggers is resolved. `once` reverses the
#: position and stops, which is what a reversal system does and is symmetric in
#: the side; `close` and `adverse` fire both and end on, or opposite, the side
#: the bar closed, and bracket it.
INTRABAR = os.environ.get("DT_INTRABAR") or "once"

#: The intrabar conventions reported side by side in `main`, the first being
#: the headline. A convention is a sensitivity, not a search: all three are
#: reported and none is chosen on its result.
INTRABARS = tuple((os.environ.get("DT_INTRABARS") or "once,close,adverse").split(","))

#: The cost ceiling, in trigger units. Quoted by the operator for this study.
CEILING = float(os.environ.get("DT_CEILING") or 0.16)

#: The volatility unit's EWMA span per clock, from `level_shield.SETTINGS` so
#: this study and that one measure volatility with the same object.
UNIT_SPAN = {"15m": 48, "1d": 20}

#: The power plant: a continuation of `strength` trigger units spread over
#: `PLANT_HOLD` bars after a close that is a `PLANT_N`-bar extreme. Defined on
#: the series rather than on the rule's own trigger, so the detector has to find
#: it rather than being handed it.
PLANT_GRID = tuple(
    float(x) for x in (os.environ.get("DT_PLANT") or "0,0.01,0.02,0.05,0.1,0.2,0.4").split(",")
)
PLANT_N = int(os.environ.get("DT_PLANT_N") or 4)
PLANT_HOLD = int(os.environ.get("DT_PLANT_HOLD") or 4)

#: Minimum trades a cell needs before a mean is reported. Pooled first, never
#: per feed: `pool-events-before-a-per-feed-guard` records a min-events guard
#: dropping 141 of 146 feeds and turning 0.9 sigma into 4.8.
MIN_TRADES = int(os.environ.get("DT_MIN_TRADES") or 30)


# ─────────────────────────────── the instruments ───────────────────────────────

#: FX and metals at 15m come from the sequence cache, which carries 276k-294k
#: bars from 2015 on these names. The shorter cache names (20k bars from
#: 2026-01) are left out rather than pooled: `pooled-medians-invert-subgroups`.
CACHE_FX = ("EURUSD", "GBPUSD", "USDJPY", "USDCAD", "AUDUSD")
CACHE_METAL = ("XAUUSD", "XAGUSD")

#: Indices are not in the sequence cache at any interval, so they come from the
#: wide cache - 50k 15m bars from 2024-08, a fifth of the FX history. The
#: length asymmetry deflates their t by about 2.4 and is reported, not hidden.
WIDE_INDEX = ("US SP 500", "US Tech 100", "Wall Street 30", "Germany 40", "UK 100", "Japan 225")

#: The independent placebo pair, which caught two leaks in one run
#: (`carry-an-independent-placebo-pair`). Length-matched to FX at 275k bars.
PLACEBO = ("Volatility 25 Index", "Volatility 75 Index")

#: The positive control. `Range_Break` has a range by construction, so a
#: range-breakout rule that cannot see it is broken and that is the first thing
#: to read. Only in the synthetic cache and only at 50k bars.
POSITIVE = ("Range Break 100 Index", "Range Break 200 Index")

#: 1d comes from the price store, which is the only 1d source here and carries
#: 19 years. Crypto is out of scope.
DB_FX = ("eurusd", "gbpusd", "usdjpy", "usdcad", "usdchf", "nzdusd", "usdcnh")
DB_METAL = ("gold",)
DB_INDEX = ("spx500", "us100")

#: The price store names a feed, the terminal names a symbol, and for one of
#: them those differ.
BRIDGE_NAME = {"gold": "XAUUSD", "spx500": "US SP 500", "us100": "US Tech 100"}

CLASS = {}
for _s in CACHE_FX + DB_FX:
    CLASS[_s] = "fx"
for _s in CACHE_METAL + DB_METAL:
    CLASS[_s] = "metal"
for _s in WIDE_INDEX + DB_INDEX:
    CLASS[_s] = "index"
for _s in PLACEBO:
    CLASS[_s] = "placebo"
for _s in POSITIVE:
    CLASS[_s] = "positive"


def malformed(arr: np.ndarray) -> np.ndarray:
    """Bars whose high and low do not contain their own open and close.

    Not pedantry, and this check exists because it caught one. `gold` on the
    venue with the most 1d bars has **177 of 5,009 (3.53%)** bars whose extremes
    do not contain their ends, one with `high < low`, and **355 (7.09%)** with
    zero range - while four other venues of the same instrument carry 5,008
    bars with none. That series produced the single largest positive cell in
    this study's whole parameter sweep, `+1.16` units a trade at `z +10.4`.

    It was found by `reflect`'s own assertion rather than by looking: reflecting
    a bar with `high < low` inverts it, the assertion fired, and the cell came
    back as an `ERROR` row instead of as a number. An arm that cannot represent
    a bad bar is worth more than one that quietly trades it.
    """
    high, low = arr[:, 2], arr[:, 3]
    ends_hi = np.maximum(arr[:, 1], arr[:, 4])
    ends_lo = np.minimum(arr[:, 1], arr[:, 4])
    return (high < ends_hi) | (low > ends_lo) | (high < low) | ~np.isfinite(arr).all(axis=1)


def _npz(path: Path, interval: str) -> Series | None:
    """One cached series, with the same malformed-bar check the 1d store gets.

    The check is applied here too rather than only where it caught something:
    a defect found in one source is a reason to look in the others, and a
    count printed on every load is how a new one gets noticed.
    """
    symbol = path.name[: -len(f".{interval}.npz")]
    with np.load(path) as data:
        arr = {k: data[k].astype(float) for k in ("time", "open", "high", "low", "close")}
    if len(arr["close"]) < 2_000:
        return None
    stacked = np.column_stack(
        [arr["time"], arr["open"], arr["high"], arr["low"], arr["close"]]
    )
    bad = malformed(stacked)
    if bad.any():
        print(f"  {symbol}.{interval}: widened {int(bad.sum())} of {len(bad)} malformed bars")
        arr["high"] = np.maximum(arr["high"], np.maximum(arr["open"], arr["close"]))
        arr["low"] = np.minimum(arr["low"], np.minimum(arr["open"], arr["close"]))
    return Series(
        feed=symbol,
        venue="cache",
        interval=interval,
        ts=arr["time"],
        open=arr["open"],
        high=arr["high"],
        low=arr["low"],
        close=arr["close"],
    )


def cache_series() -> list[Series]:
    """The 15m population: FX and metals, indices, the placebo pair, the control."""
    out: list[Series] = []
    for name in CACHE_FX + CACHE_METAL + PLACEBO:
        series = _npz(SEQLAB / f"{name}.15m.npz", "15m")
        if series is not None:
            out.append(series)
    for name in WIDE_INDEX:
        series = _npz(WIDE / f"{name}.15m.npz", "15m")
        if series is not None:
            out.append(series)
    for name in POSITIVE:
        series = _npz(SYN / f"{name}.15m.npz", "15m")
        if series is not None:
            out.append(series)
    return out


def db_series() -> list[Series]:
    """The 1d population, one venue per feed, de-duplicated by `ts`.

    **The venue is chosen by data quality first and bar count second**, which
    is a change from this repository's usual "most bars" rule and the reason is
    in `malformed`. Ties break on the venue name so the choice is deterministic
    and not a function of row order.

    De-duplication is not tidiness either. `spx500` and `us100` hold **two rows
    per timestamp** at 1d on the venue with the most rows - 6,005 rows over
    3,006 stamps - so a rolling window reading them in arrival order spans half
    the days it says and a 4-bar range is a 2-day range. Dropped rows are
    printed, and so is every candidate venue's malformed share.
    """
    con = sqlite3.connect(f"file:{STORE}?mode=ro", uri=True)
    out: list[Series] = []
    for feed in DB_FX + DB_METAL + DB_INDEX:
        best: tuple[float, int, str, np.ndarray] | None = None
        venues = [
            r[0]
            for r in con.execute(
                "select venue, count(*) n from bars where feed=? and interval='1d' "
                "and closed=1 group by venue order by n desc",
                (feed,),
            )
        ]
        for venue in venues:
            rows = con.execute(
                "select ts, open, high, low, close from bars where feed=? and venue=? "
                "and interval='1d' and closed=1 order by ts",
                (feed, venue),
            ).fetchall()
            if len(rows) < 500:
                continue
            arr = np.asarray(rows, dtype=float)
            _stamps, first = np.unique(arr[:, 0], return_index=True)
            dupes = len(arr) - len(first)
            arr = arr[np.sort(first)]
            share = float(malformed(arr).mean())
            print(
                f"  {feed}.1d {venue:12s} {len(arr):6d} bars, {dupes:5d} duplicate stamps, "
                f"{share:7.3%} malformed"
            )
            key = (round(share, 6), -len(arr), venue)
            if best is None or key < best[:3]:
                best = (*key, arr)
        if best is None:
            continue
        arr = best[3]
        bad = malformed(arr)
        if bad.any():
            # Widened rather than dropped: dropping a bar breaks the day
            # sequence the range window counts in, and the widening is the
            # smallest change that makes the bar a bar.
            print(f"  {feed}.1d: widened {int(bad.sum())} bars to contain their own ends")
            arr[:, 2] = np.maximum(arr[:, 2], np.maximum(arr[:, 1], arr[:, 4]))
            arr[:, 3] = np.minimum(arr[:, 3], np.minimum(arr[:, 1], arr[:, 4]))
        print(f"  {feed}.1d: chose {best[2]}")
        out.append(
            Series(
                feed=feed,
                venue=best[2],
                interval="1d",
                ts=arr[:, 0],
                open=arr[:, 1],
                high=arr[:, 2],
                low=arr[:, 3],
                close=arr[:, 4],
            )
        )
    con.close()
    return out


def daily(series: Series) -> Series:
    """15m bars folded into UTC days: open first, close last, high and low the block's.

    The only 1d source for the synthetic controls, which exist at 15m alone -
    and the same-venue 1d arm for the traded names, so the clock comparison is
    not confounded with the data vendor. A UTC midnight boundary is a stated
    choice, not the broker's session open; the rule reads "today's open" and
    this is which day that is here.
    """
    day = np.floor(series.ts / 86_400.0).astype(np.int64)
    edge = np.flatnonzero(np.diff(day)) + 1
    starts = np.concatenate(([0], edge))
    stops = np.concatenate((edge, [len(day)]))
    keep = (stops - starts) >= 2
    starts, stops = starts[keep], stops[keep]
    high = np.array([series.high[a:b].max() for a, b in zip(starts, stops, strict=True)])
    low = np.array([series.low[a:b].min() for a, b in zip(starts, stops, strict=True)])
    return Series(
        feed=series.feed,
        venue="cache1d",
        interval="1d",
        ts=series.ts[starts],
        open=series.open[starts],
        high=high,
        low=low,
        close=series.close[stops - 1],
    )


def quote_px(symbol: str) -> float:
    """The terminal's own round trip in price, or `nan`.

    Through `research.harness.venue.quoted`, the one place that asks. The
    per-bar `spread` column is in **points, not price** - it once read a 476%
    round trip on EURUSD - so it is not a fallback here. `nan` means the cell
    is unpriced, never free.
    """
    try:
        from research.harness.venue import quoted
    except ImportError:  # pragma: no cover - the bridge module is lab-side
        return float("nan")
    named = BRIDGE_NAME.get(symbol) or (symbol.upper() if symbol.islower() else symbol)
    return float(quoted(named, timeout=8.0))


# ───────────────────────────────── the rule ─────────────────────────────────


@dataclass(frozen=True, slots=True)
class Trade:
    """One always-invested segment: a flip in, the next flip out.

    `unit` is the trigger distance that opened it - the only risk unit this
    rule defines - and `vol` is the causal volatility reading at that bar, for
    the strata. Both are fixed at entry, so no column here is a function of the
    outcome.
    """

    enter: int
    leave: int
    side: int
    entry_px: float
    exit_px: float
    unit: float
    vol: float

    @property
    def gross(self) -> float:
        return self.side * (self.exit_px - self.entry_px)


def thrust_range(series: Series, n: int) -> np.ndarray:
    """`max(HH - LC, HC - LL)` over the `n` bars **before** each bar.

    `nan` until there are `n` prior bars, which keeps the warm-up out of the
    sample rather than filling it with a shorter window - a shorter window is a
    different rule, and averaging the two is the error
    `definitions-cannot-be-states` names.
    """
    size = len(series.close)
    out = np.full(size, np.nan)
    if size <= n:
        return out
    view = np.lib.stride_tricks.sliding_window_view
    hh = view(series.high, n)[:-1].max(axis=1)
    ll = view(series.low, n)[:-1].min(axis=1)
    hc = view(series.close, n)[:-1].max(axis=1)
    lc = view(series.close, n)[:-1].min(axis=1)
    out[n:] = np.maximum(hh - lc, hc - ll)
    return out


def run_rule(
    series: Series,
    rng_series: np.ndarray,
    vol: np.ndarray,
    k1: float,
    k2: float,
    *,
    intrabar: str = INTRABAR,
) -> tuple[list[Trade], int]:
    """The reversal system, filled at the trigger price.

    Returns the closed trades and the count of bars that reached **both**
    triggers and moved the position - the whipsaw count the write-up reports,
    because the rule fires far more often than its description suggests: four
    identical bars give a 4-bar range equal to one bar's own range, so the cap
    sits half a bar above the open and the bar's own high reaches it.

    The first trigger opens the first position and closes nothing, and the last
    position is never closed, so there are `flips - 1` trades for `flips`
    triggers. Neither end is counted as a trade: one has no entry to measure
    against and the other has no exit.
    """
    high, low, open_ = series.high, series.low, series.open
    trades: list[Trade] = []
    pos = 0
    entry_px = 0.0
    entry_i = 0
    entry_u = 0.0
    entry_v = 0.0
    same_bar = 0
    for i in range(len(high)):
        width = rng_series[i]
        if not math.isfinite(width) or width <= 0.0:
            continue
        cap = open_[i] + k1 * width
        floor = open_[i] - k2 * width
        up = high[i] >= cap
        down = low[i] <= floor
        both = up and down
        if both:
            # Which trigger the path reached first is unobservable, so this is
            # a stated convention and not a measurement. `once` is symmetric in
            # the side; the other two use the bar's close as a proxy for which
            # was touched last and bracket it from either direction.
            toward = 1 if series.close[i] >= open_[i] else -1
            if intrabar == "once":
                order = (-pos,) if pos else (toward,)
            elif intrabar == "adverse":
                order = (toward, -toward)
            else:
                order = (-toward, toward)
        elif up:
            order = (1,)
        elif down:
            order = (-1,)
        else:
            continue
        flips = 0
        for side in order:
            if pos == side:
                continue
            flips += 1
            price = cap if side > 0 else floor
            if pos != 0:
                trades.append(
                    Trade(
                        enter=entry_i,
                        leave=i,
                        side=pos,
                        entry_px=entry_px,
                        exit_px=price,
                        unit=entry_u,
                        vol=entry_v,
                    )
                )
            pos = side
            entry_px = price
            entry_i = i
            entry_u = (k1 if side > 0 else k2) * width
            entry_v = float(vol[i])
        if both and flips:
            # Bars where **both** triggers were reached and the position moved.
            # Counted on the condition rather than on the number of flips,
            # because `once` flips at most once and a count of double flips
            # would read zero under the headline convention and say nothing.
            same_bar += 1
    return trades, same_bar


def const_range(rng_series: np.ndarray, train: float = TRAIN) -> np.ndarray:
    """The `const` arm's distance: the median measured range over a training block.

    A constant and not a lookahead constant - the median is taken over the
    first `train` of the bars and frozen - because a control allowed to see the
    whole sample is a control given an advantage the rule did not have, and
    `never-test-cointegration-on-a-live-ratio` is the recorded version of that
    mistake.
    """
    finite = np.flatnonzero(np.isfinite(rng_series))
    if len(finite) == 0:
        return rng_series
    cut = finite[0] + max(1, int(train * (len(rng_series) - finite[0])))
    block = rng_series[finite[0] : cut]
    block = block[np.isfinite(block)]
    if len(block) == 0:
        return rng_series
    out = np.full(len(rng_series), float(np.median(block)))
    out[: finite[0]] = np.nan
    return out


# ──────────────────────────────── the statistics ────────────────────────────────


def block_ci(values: np.ndarray, rng: random.Random, draws: int = BOOT) -> tuple[float, float]:
    """A block bootstrap over contiguous runs of trades.

    The trades tile the series, so consecutive outcomes share a volatility
    regime and an ordinary standard error is far too narrow. The block is a
    hundredth of the sample with a floor of five trades.
    """
    size = len(values)
    if size < MIN_TRADES:
        return float("nan"), float("nan")
    block = max(5, size // 100)
    blocks = max(1, size // block)
    gen = np.random.default_rng(rng.randrange(1 << 30))
    starts = gen.integers(0, size - block + 1, size=(draws, blocks))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(draws, -1)
    means = values[idx].mean(axis=1)
    return float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def coin_means(
    gross: np.ndarray, unit: np.ndarray, rng: random.Random, draws: int = DRAWS
) -> tuple[np.ndarray, np.ndarray]:
    """The side-shuffled arm: the same times, the same distances, a random side.

    `gross` is the **signed** outcome, so `|gross|` is the move the trade's own
    distances produced and the coin re-signs it. That makes the null exact
    rather than simulated: its expectation is zero by construction and its
    spread is the spread of the real sample's magnitudes.
    """
    mag = np.abs(gross) / unit
    gen = np.random.default_rng(rng.randrange(1 << 30))
    signs = gen.choice((-1.0, 1.0), size=(draws, len(mag)))
    return (signs * mag).mean(axis=1), mag


def bh(pvalues: list[float], alpha: float = 0.05) -> tuple[int, float]:
    """Benjamini-Hochberg: how many survive, and the largest p that does."""
    clean = sorted(p for p in pvalues if math.isfinite(p))
    if not clean:
        return 0, float("nan")
    size = len(clean)
    best = 0
    cut = float("nan")
    for rank, p in enumerate(clean, start=1):
        if p <= alpha * rank / size:
            best, cut = rank, p
    return best, cut


def describe(
    trades: list[Trade],
    bars: int,
    common: float,
    cost_px: float,
    rng: random.Random,
) -> dict:
    """One cell: the rate and the sample first, then the mean and its null."""
    row = {"n": len(trades), "bars": bars}
    if len(trades) < MIN_TRADES:
        return row
    gross = np.array([t.gross for t in trades])
    unit = np.array([t.unit for t in trades])
    pnl_u = gross / unit
    priced = math.isfinite(cost_px)
    cost_u = cost_px / unit if priced else np.full(len(unit), np.nan)
    means, mag = coin_means(gross, unit, rng)
    lo, hi = block_ci(pnl_u, rng)
    row.update(
        rate=1_000.0 * len(trades) / max(1, bars),
        held=float(np.mean([t.leave - t.enter for t in trades])),
        mean_u=float(pnl_u.mean()),
        med_u=float(np.median(pnl_u)),
        sd_u=float(pnl_u.std(ddof=1)),
        top1=float(np.abs(pnl_u).max() / np.abs(pnl_u).sum()),
        lo=lo,
        hi=hi,
        mean_c=float((gross / common).mean()),
        unit_c=float(np.median(unit) / common),
        coin_u=float(means.mean()),
        coin_sd=float(means.std(ddof=1)),
        z=float(pnl_u.mean() / means.std(ddof=1)) if means.std(ddof=1) > 0 else float("nan"),
        p=float((np.abs(means) >= abs(pnl_u.mean())).mean()),
        cost_u=float(np.median(cost_u)) if priced else float("nan"),
        net_u=float(pnl_u.mean() - cost_u.mean()) if priced else float("nan"),
        hit=float((pnl_u > 0).mean()),
        p1=float((pnl_u >= 1.0).mean()),
        p2=float((pnl_u >= 2.0).mean()),
        coin_p1=float(0.5 * (mag >= 1.0).mean()),
        coin_p2=float(0.5 * (mag >= 2.0).mean()),
    )
    return row


STATS = (
    "n", "bars", "rate", "held", "mean_u", "med_u", "sd_u", "top1", "lo", "hi", "mean_c", "unit_c",
    "coin_u", "coin_sd", "z", "p", "cost_u", "net_u", "hit", "p1", "p2",
    "coin_p1", "coin_p2", "same_bar", "planted", "strength", "spread_px", "wick", "drift_u",
)  # fmt: skip


# ───────────────────────────────── the plant ─────────────────────────────────


def plant(series: Series, strength: float, scale: float) -> Series:
    """Plant a breakout continuation of `strength` trigger units and nothing else.

    After a close that is the highest (lowest) of the last `PLANT_N` closes,
    drift `strength * scale` in that direction over the next `PLANT_HOLD` bars.
    The signal is defined on the **series**, not on the rule's trigger, so the
    detector has to find it; the drift is added as a cumulative offset to the
    whole bar, which keeps the bar's own geometry and its wickiness.

    `open` carries the offset accumulated **before** the bar and `high`, `low`
    and `close` the offset including it, so the drift accrues inside the bar
    rather than teleporting at its boundary. The two clamps are what keep
    `low <= open <= high` when the planted step is large.
    """
    close = series.close
    size = len(close)
    if size <= PLANT_N or strength == 0.0:
        return series
    view = np.lib.stride_tricks.sliding_window_view
    prior_hi = np.full(size, np.inf)
    prior_lo = np.full(size, -np.inf)
    prior_hi[PLANT_N:] = view(close, PLANT_N)[:-1].max(axis=1)
    prior_lo[PLANT_N:] = view(close, PLANT_N)[:-1].min(axis=1)
    side = np.where(close > prior_hi, 1.0, np.where(close < prior_lo, -1.0, 0.0))
    step = np.zeros(size)
    per = strength * scale / PLANT_HOLD
    for lag in range(1, PLANT_HOLD + 1):
        step[lag:] += per * side[:-lag]
    offset = np.cumsum(step)
    before = np.concatenate(([0.0], offset[:-1]))
    open_ = series.open + before
    high = np.maximum(series.high + offset, open_)
    low = np.minimum(series.low + offset, open_)
    assert np.all(high >= low), "the plant inverted a bar"
    return Series(
        feed=series.feed,
        venue=series.venue,
        interval=series.interval,
        ts=series.ts,
        open=open_,
        high=high,
        low=low,
        close=series.close + offset,
    )


# ─────────────────────────────── the matched null ───────────────────────────────


def reflect(series: Series, rng: random.Random) -> Series:
    """Every bar's shape and gap kept, its **direction** coined, the path rebuilt.

    The null this rule needs, and the reason it exists is measured in
    `dual-thrust.md`: the trigger distance is a function of the last `N` bars'
    ranges, so a surrogate that gets the ranges wrong gets the triggers wrong,
    and `walk_path`'s bars are not this market's bars. A Brownian bridge pinned
    to a resampled **heavy-tailed** step has a free excursion of the full step
    sd inside every bar, so a quiet bar comes out as wicky as a violent one;
    measured on the traded 15m series its range-to-step ratio is far from the
    market's, and the rule read -0.25 units a trade on it where arithmetic
    wants zero.

    This arm instead keeps each bar exactly as it is and flips it about its own
    open with probability a half, the gap included so the gap's size and its
    correlation with the body survive. What is preserved: every bar's shape,
    the whole range sequence, the volatility clustering, and `open` equal to
    the previous close plus a real gap. What is destroyed: the direction, and
    only the direction.

    It is a martingale in the only sense that matters here - conditional on
    everything before bar `i`, the signed step is a fair coin times a fixed
    magnitude - and it shares the real arm's one piece of fill optimism, that a
    trigger inside `[low, high]` is assumed reachable. A null that did not
    share it would be measuring the fill model instead of the rule.
    """
    gap = np.concatenate(([0.0], series.open[1:] - series.close[:-1]))
    return _rebuild(series, gap, np.random.default_rng(rng.randrange(1 << 30)))


def shuffle(series: Series, rng: random.Random) -> Series:
    """`reflect`, and the bar **order** permuted as well: the clustering removed.

    The A/B that says what is in the harness's own offset. `reflect` keeps the
    real magnitude sequence and so keeps the volatility clustering; this arm
    draws the same bars in a random order, so it keeps the marginal and
    destroys the clustering. Neither has a direction, so a difference between
    them is about the clustering and nothing else - which matters because the
    trigger distance is a **lagged** measurement of the range, and a lagged
    measurement of a clustered quantity is systematically wrong in a way a
    constant one cannot be.
    """
    gen = np.random.default_rng(rng.randrange(1 << 30))
    order = gen.permutation(len(series.close))
    drawn = Series(
        feed=series.feed,
        venue=series.venue,
        interval=series.interval,
        ts=series.ts,
        open=series.open[order],
        high=series.high[order],
        low=series.low[order],
        close=series.close[order],
    )
    # A permuted `open[i] - close[i-1]` is the difference of two unrelated
    # prices, so each bar's gap is taken before the permutation and carried
    # with it. Without this the arm's gaps would be the size of the whole
    # series' excursion and it would trigger on every bar.
    gap = np.concatenate(([0.0], series.open[1:] - series.close[:-1]))[order]
    return _rebuild(drawn, gap, gen)


def _rebuild(series: Series, gap: np.ndarray, gen: np.random.Generator) -> Series:
    """Coin each bar's direction and lay the bars out as one continuous path.

    One coin per bar for the gap and the body **together**, so a bar that
    gapped up and then closed down keeps that relationship under reflection.
    The two clamps at the end are belt and braces: a reflected bar's extremes
    are its own, so they already contain its open and its close, and an
    equality failing in a float's last bit would otherwise leave a bar the rule
    can trigger on and cannot fill.
    """
    body = series.close - series.open
    up_high = series.high - series.open
    up_low = series.low - series.open
    flip = gen.choice((1.0, -1.0), size=len(series.close))
    step = flip * (gap + body)
    close = series.close[0] - (gap[0] + body[0]) + np.cumsum(step)
    open_ = close - flip * body
    high = open_ + np.where(flip > 0, up_high, -up_low)
    low = open_ + np.where(flip > 0, up_low, -up_high)
    assert np.all(high >= low - 1e-9), "reflection inverted a bar"
    return Series(
        feed=series.feed,
        venue=series.venue,
        interval=series.interval,
        ts=series.ts,
        open=open_,
        high=np.maximum(high, np.maximum(open_, close)),
        low=np.minimum(low, np.minimum(open_, close)),
        close=close,
    )


def drift_units(series: Series, trades: list[Trade]) -> float:
    """The instrument's own drift over one hold, in trigger units.

    The column that stops a trend being read as an edge. Every null here is
    direction-free - `reflect` coins each bar's sign, `walk_path` demeans its
    steps - so an always-invested rule on a market that **went somewhere** beats
    them by its exposure and not by its selection. Gold's 1d cell at `K = 0.2`
    read `+1.16` units a trade in this study's sweep, and gold went from about
    600 to about 4,000 over the sample. This number is what that is worth:
    the mean close-to-close step, times the mean bars held, over the median
    trigger distance. A difference against a null that is the size of this
    column is exposure.
    """
    if not trades:
        return float("nan")
    step = float(np.mean(np.diff(series.close)))
    held = float(np.mean([t.leave - t.enter for t in trades]))
    unit = float(np.median([t.unit for t in trades]))
    return step * held / unit if unit > 0 else float("nan")


def wickiness(series: Series) -> float:
    """The median bar range over the median absolute close-to-close step.

    The one number that says whether a surrogate's bars are this market's
    bars. A rule whose trigger is `K * range` is priced in this ratio, so an
    arm that gets it wrong is not a null for this rule however well calibrated
    it is for a fixed barrier.
    """
    rng_ = series.high - series.low
    step = np.abs(np.diff(series.close))
    good = np.median(step[step > 0]) if np.any(step > 0) else float("nan")
    return float(np.median(rng_[rng_ > 0]) / good) if good else float("nan")


# ────────────────────────────────── the cells ──────────────────────────────────


def strata(trades: list[Trade], parts: int = 3) -> list[tuple[str, list[Trade]]]:
    """Volatility terciles of the entry bar, by the trade population's own cuts.

    Labelling only - the cuts come from the trades' entry volatility, which is
    causal at each entry - and reported beside the pooled row because
    `auc-is-free-on-volatility-targets` reads 0.805 on a constant-volatility
    process pooled and 0.525 within strata, and `pooled-medians-invert-subgroups`
    is the recorded case of a pooled answer agreeing with a claim every subgroup
    refuted.
    """
    vol = np.array([t.vol for t in trades])
    if len(trades) < parts * MIN_TRADES or not np.all(np.isfinite(vol)):
        return []
    cuts = np.quantile(vol, [(j + 1) / parts for j in range(parts - 1)])
    which = np.searchsorted(cuts, vol, side="right")
    return [
        (f"vol{j}", [t for t, w in zip(trades, which, strict=True) if w == j])
        for j in range(parts)
    ]


def cell_rows(
    series: Series,
    n: int,
    k: float,
    cost_px: float,
    *,
    k2: float | None = None,
    arms: tuple[str, ...],
    nulls: tuple[str, ...] = (),
    surrogates: int = 0,
    plant_grid: tuple[float, ...] = (0.0,),
) -> list[dict]:
    """Every row for one (instrument, clock, N, K): the arms, the strata, the nulls.

    `k2` is the **short** trigger's multiple and defaults to `k`, so every
    symmetric caller is unchanged. An asymmetric pair makes the both-triggers
    bar's convention load-bearing rather than incidental: this study's first
    convention - nearest-trigger-first - left the position short on every
    whipsaw bar with `k1 == k2`, and with `k1 != k2` that tilt becomes
    systematic. `INTRABAR=once` is symmetric by construction and `close` and
    `adverse` bracket it, which is why all three run.
    """
    vol = units(series, UNIT_SPAN.get(series.interval, 48))
    k_short = k if k2 is None else float(k2)
    bar_range = series.high - series.low
    common = float(np.median(bar_range[bar_range > 0])) or 1.0
    base = {
        "symbol": series.feed,
        "klass": CLASS.get(series.feed, "other"),
        "interval": series.interval,
        "venue": series.venue,
        "source": series.venue,
        "n_window": n,
        "k": k,
        "k2": k_short,
        "days": round(series.days, 1),
    }
    rows: list[dict] = []
    measured = thrust_range(series, n)
    plans: list[tuple[str, np.ndarray, str]] = []
    if "real" in arms:
        # The headline convention first, then the two that bracket it. A
        # convention is a sensitivity and not a search, so all three are
        # reported and the headline is fixed before any of them is read.
        plans.append(("real", measured, INTRABARS[0]))
        plans.extend(
            (f"real-{name}", measured, name) for name in INTRABARS[1:]
        )
    if "const" in arms:
        plans.append(("const", const_range(measured), INTRABARS[0]))
    for arm, widths, convention in plans:
        rng = random.Random(f"{series.name}|{n}|{k}|{arm}|{SEED}")
        trades, same_bar = run_rule(series, widths, vol, k, k_short, intrabar=convention)
        row = describe(trades, len(series.close), common, cost_px, rng)
        rows.append(
            {
                **base,
                "arm": arm,
                "stratum": "all",
                "same_bar": same_bar,
                "wick": wickiness(series),
                "drift_u": drift_units(series, trades),
                **row,
            }
        )
        for label, part in strata(trades):
            part_row = describe(part, len(series.close), common, cost_px, rng)
            rows.append({**base, "arm": arm, "stratum": label, **part_row})
    makers = [(name, SURROGATE[name]) for name in nulls]
    for draw in range(surrogates):
        for name, maker in makers:
            rng = random.Random(f"{series.name}|{n}|{k}|{name}|{draw}|{SEED}")
            surrogate = maker(series, rng)
            s_vol = units(surrogate, UNIT_SPAN.get(series.interval, 48))
            s_range = surrogate.high - surrogate.low
            s_common = float(np.median(s_range[s_range > 0])) or 1.0
            widths = thrust_range(surrogate, n)
            scale = k * float(np.nanmedian(widths))
            wick = wickiness(surrogate)
            for strength in plant_grid:
                planted = plant(surrogate, strength, scale) if strength else surrogate
                p_widths = thrust_range(planted, n) if strength else widths
                # Both distance arms on the null too. Without the second one
                # the `const` column has no baseline of its own and "the range
                # does no work" would be read against the measured arm's offset.
                legs = [(name, p_widths)]
                if "const" in arms and not strength:
                    legs.append((f"{name}-const", const_range(p_widths)))
                for leg, leg_widths in legs:
                    trades, same_bar = run_rule(planted, leg_widths, s_vol, k, k_short)
                    row = describe(trades, len(planted.close), s_common, cost_px, rng)
                    tag = {
                        **base,
                        "arm": leg,
                        "draw": draw,
                        "planted": strength * scale,
                        "strength": strength,
                        "wick": wick,
                    }
                    rows.append(
                        {
                            **tag,
                            "stratum": "all",
                            "same_bar": same_bar,
                            "drift_u": drift_units(planted, trades),
                            **row,
                        }
                    )
                    # The strata need the null's own cuts, or the within-strata
                    # table is a real arm against nothing.
                    if strength:
                        continue
                    for label, part in strata(trades):
                        rows.append(
                            {
                                **tag,
                                "stratum": label,
                                **describe(part, len(planted.close), s_common, cost_px, rng),
                            }
                        )
    return rows


#: The null arms by name. `walk_path` comes from `entry_timing` rather than
#: from a copy, so this study and that one share one object.
SURROGATE = {"reflect": reflect, "shuffle": shuffle, "walk-path": walk_path}


def _job(task: tuple) -> list[dict]:
    # Eight fields is the symmetric task every mode but `asym` builds; a ninth
    # is the short trigger's own multiple.
    series, n, k, cost_px, arms, nulls, surrogates, plant_grid = task[:8]
    k2 = task[8] if len(task) > 8 else None
    try:
        return cell_rows(
            series,
            n,
            k,
            cost_px,
            k2=k2,
            arms=arms,
            nulls=nulls,
            surrogates=surrogates,
            plant_grid=plant_grid,
        )
    except Exception as exc:  # noqa: BLE001 - one bad cell must not lose the run
        print(f"  ERROR {series.name} N={n} K={k}/{k2}: {exc!r}")
        return [{"symbol": series.feed, "interval": series.interval, "arm": "error", "n": 0}]


# ─────────────────────────────────── reporting ───────────────────────────────────


def write(rows: list[dict], mode: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    keys = ("symbol", "klass", "interval", "venue", "source", "arm", "stratum", "draw",
            "n_window", "k", "days")  # fmt: skip
    path = OUT / f"cells-{mode}.csv"
    header = [*keys, *STATS]
    with path.open("w") as handle:
        handle.write(",".join(header) + "\n")
        for row in rows:
            handle.write(",".join(_fmt(row.get(key)) for key in header) + "\n")
    print(f"\n{len(rows)} rows -> {path}")
    return path


def _fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return "" if not math.isfinite(value) else f"{value:.6g}"
    return str(value).replace(",", ";")


def table(rows: list[dict], columns: tuple[str, ...]) -> None:
    head = ("symbol", "interval", "arm", "stratum")
    print("  " + "".join(f"{c:>12s}" for c in (*head, *columns)))
    for row in rows:
        cells = [str(row.get(c, ""))[:12] for c in head]
        cells += [_fmt(row.get(c)) for c in columns]
        print("  " + "".join(f"{c:>12s}" for c in cells))


# ───────────────────────────────────── modes ─────────────────────────────────────


def population() -> list[Series]:
    """Every (instrument, clock) in the study, each with its own source named.

    Three sources, because no one store answers the question. `cache` is the
    15m broker feed; `cache1d` is that same feed folded into UTC days, which is
    the only 1d arm the synthetic controls can have and the only one that
    compares the two clocks on **one venue**; `db` is the price store, the only
    source with real daily bars and 19 years of them. A result that holds on
    `cache1d` and not on `db` is a statement about the day boundary or the
    sample, and keeping them apart is what lets it be read as one.
    """
    fifteen = cache_series()
    return [*fifteen, *(daily(s) for s in fifteen), *db_series()]


def quotes(series_list: list[Series]) -> dict[str, float]:
    """One quote per symbol, asked once. The bridge is the only source."""
    out: dict[str, float] = {}
    for series in series_list:
        if series.feed in out:
            continue
        out[series.feed] = quote_px(series.feed)
    return out


def mode_cost(pop: list[Series], px: dict[str, float]) -> list[dict]:
    """Price the round trip in trigger units, per instrument and per clock.

    This runs first and is allowed to end the study. `A shorter clock
    multiplies cost in R` is the reason both clocks are priced: the same spread
    is 19x dearer at 15m than at 1d on this book, and a rule whose unit is a
    4-bar range inherits the whole of that.
    """
    rows: list[dict] = []
    for series in pop:
        width = thrust_range(series, N0)
        finite = width[np.isfinite(width) & (width > 0)]
        if len(finite) == 0:
            continue
        unit = K0 * float(np.median(finite))
        bar_range = series.high - series.low
        common = float(np.median(bar_range[bar_range > 0])) or 1.0
        spread = px.get(series.feed, float("nan"))
        rows.append(
            {
                "symbol": series.feed,
                "klass": CLASS.get(series.feed, "other"),
                "interval": series.interval,
                "venue": series.venue,
                "source": series.venue,
                "arm": "cost",
                "stratum": "all",
                "n_window": N0,
                "k": K0,
                "days": round(series.days, 1),
                "n": len(series.close),
                "bars": len(series.close),
                "mean_u": unit,
                "mean_c": unit / common,
                "cost_u": spread / unit if math.isfinite(spread) else float("nan"),
                "spread_px": spread,
                "unit_c": common,
            }
        )
    rows.sort(key=lambda r: (r["interval"], r["klass"], r["symbol"]))
    print("\nthe round trip in trigger units, N=4 K=0.5 (ceiling 0.16)\n")
    print(
        f"  {'symbol':22s} {'clock':6s} {'venue':8s} {'spread_px':>10s} "
        f"{'unit_px':>10s} {'bar_rng':>9s} {'cost_u':>8s}  verdict"
    )
    for row in rows:
        cost = row["cost_u"]
        # A ratio of two measured prices lands on 0.16000000000000003 and a
        # bare `<=` then prints FAIL against a ceiling of 0.16. The tolerance
        # is a rounding allowance, not a relaxed ceiling.
        verdict = (
            "unpriced"
            if not math.isfinite(cost)
            else ("pass" if cost <= CEILING * (1.0 + 1e-9) else "FAIL")
        )
        print(
            f"  {row['symbol']:22s} {row['interval']:6s} {row['venue']:8s} "
            f"{_fmt(row['spread_px']):>10s} {_fmt(row['mean_u']):>10s} "
            f"{_fmt(row['unit_c']):>9s} {_fmt(cost):>8s}  {verdict}"
        )
    # Keyed by symbol and **not** by venue: the two clocks are the same broker
    # feed under two names, `cache` and `cache1d`, so keying on the venue gave
    # an empty table and no error.
    print("\nthe clock multiplier, 15m against 1d on the same broker feed\n")
    by_key: dict[str, dict[str, float]] = {}
    for row in rows:
        if row["venue"] in {"cache", "cache1d"}:
            by_key.setdefault(row["symbol"], {})[row["interval"]] = row["cost_u"]
    print(f"  {'symbol':22s} {'15m':>9s} {'1d':>9s} {'ratio':>7s} {'unit/bar_rng':>13s}")
    unit_share = {
        (r["symbol"], r["interval"]): r["mean_u"] / r["unit_c"] for r in rows if r["unit_c"]
    }
    for symbol, got in sorted(by_key.items()):
        if "15m" in got and "1d" in got and math.isfinite(got["15m"] * got["1d"]):
            share = unit_share.get((symbol, "15m"), float("nan"))
            print(
                f"  {symbol:22s} {got['15m']:9.4f} {got['1d']:9.4f} "
                f"{got['15m'] / got['1d']:6.1f}x {share:13.2f}"
            )
    return rows


def run_cells(tasks: list[tuple]) -> list[dict]:
    if WORKERS <= 1:
        return [row for task in tasks for row in _job(task)]
    with Pool(WORKERS) as pool:
        return [row for part in pool.imap_unordered(_job, tasks, chunksize=1) for row in part]


def main() -> int:
    print(f"dualthrust MODE={MODE} workers={WORKERS} intrabar={INTRABAR} seed={SEED}")
    print(f"started {dt.datetime.now(tz=dt.UTC):%Y-%m-%d %H:%M}Z")
    pop = population()
    for series in pop:
        print(f"  {series.feed:22s} {series.interval:4s} {series.venue:8s} "
              f"{len(series.close):7d} bars {series.days:8.0f} days")  # fmt: skip
    px = quotes(pop)
    print("\nquotes: " + ", ".join(f"{k}={_fmt(v)}" for k, v in sorted(px.items())))

    if MODE == "cost":
        return 0 if write(mode_cost(pop, px), "cost") else 1

    mode_cost(pop, px)
    if MODE == "leak":
        tasks = [
            (s, N0, K0, px.get(s.feed, float("nan")), (), NULLS, SURROGATES, (0.0,))
            for s in pop
        ]
        rows = run_cells(tasks)
        for name in NULLS:
            print(f"\nthe {name} null at the published cell: must read zero\n")
            table(
                [r for r in rows if r.get("arm") == name],
                ("n", "rate", "wick", "mean_u", "med_u", "lo", "hi", "z", "p", "hit", "p1"),
            )
            _pooled(rows, name)
        write(rows, "leak")
        return 0

    if MODE == "main":
        tasks = [
            (s, N0, K0, px.get(s.feed, float("nan")), ("real", "const"), NULLS, SURROGATES, (0.0,))
            for s in pop
        ]
        rows = run_cells(tasks)
        write(rows, "main")
        _report_main(rows)
        return 0

    if MODE == "sweep":
        cells = {(N0, K0), *((n, K0) for n in N_GRID), *((N0, k) for k in K_GRID)}
        # With a null, and this is not optional. The fill offset is a fixed
        # price per trade and the unit is `K * range`, so the offset **in
        # units** grows as `K` shrinks: the first run of this sweep without a
        # null read `+0.1034` at `z +12.3` for EURUSD at `K = 0.2` against
        # `-0.008` at `K = 0.5`, monotone in `K`, which is the shape of the
        # artefact and not of an edge.
        tasks = [
            (s, n, k, px.get(s.feed, float("nan")), ("real",), NULLS[:1], SWEEP_DRAWS, (0.0,))
            for s in pop
            for n, k in sorted(cells)
        ]
        rows = run_cells(tasks)
        write(rows, "sweep")
        _report_sweep(rows)
        return 0

    if MODE == "asym":
        # **The full `k_up x k_down x N` surface, every cell against its own
        # direction-free twin.** Dual Thrust is traditionally tuned per
        # instrument, and the published sweep crossed only a symmetric `K`.
        #
        # **The objective is `real - reflect` and not Sharpe, deliberately.**
        # The trigger fill is worth a roughly fixed price per trade and the
        # unit is `K * range`, so the offset *in units* grows as `K` shrinks
        # while the trade count grows too - and Sharpe, which scales as
        # `mean / sd * sqrt(n)`, rewards both. A Sharpe-maximising search over
        # this grid therefore points straight at the artefact: the first
        # symmetric sweep run without a null read EURUSD `K = 0.2` at
        # `+0.1034, z +12.3`, and that cell's own null read `+0.1264`.
        #
        # Cost is priced first by `MODE=cost` and is not optional here either:
        # the realised round trip is 1.21-1.35x the screened one because a
        # nearer trigger selects small-range bars, so the region this grid
        # scores best is the region cost refuses.
        ups = tuple(float(x) for x in (os.environ.get("DT_K1_GRID") or "0.2,0.3,0.5,0.7,0.9").split(","))
        downs = tuple(
            float(x) for x in (os.environ.get("DT_K2_GRID") or "0.2,0.3,0.5,0.7,0.9").split(",")
        )
        backs = tuple(int(x) for x in (os.environ.get("DT_N_ASYM") or "2,4,6,8,10").split(","))
        tasks = [
            (s, n, k1, px.get(s.feed, float("nan")), ("real",), NULLS[:1], SWEEP_DRAWS, (0.0,), k2)
            for s in pop
            for n in backs
            for k1 in ups
            for k2 in downs
        ]
        print(
            f"{len(tasks)} cells: {len(pop)} series x {len(backs)} lookbacks x "
            f"{len(ups)}x{len(downs)} triggers, each with its own null"
        )
        rows = run_cells(tasks)
        write(rows, "asym")
        _report_sweep(rows)
        return 0

    if MODE == "power":
        tasks = [
            (s, N0, K0, px.get(s.feed, float("nan")), (), NULLS, SURROGATES, PLANT_GRID)
            for s in pop
        ]
        rows = run_cells(tasks)
        write(rows, "power")
        _report_power(rows)
        return 0

    print(f"unknown MODE={MODE}")
    return 2


def _pooled(rows: list[dict], arm: str) -> None:
    """The pooled mean over the arm's cells, trade-weighted, with its own spread."""
    cells = [r for r in rows if r.get("arm") == arm and r.get("stratum") == "all" and r.get("n")]
    good = [r for r in cells if math.isfinite(r.get("mean_u", float("nan")))]
    if not good:
        print(f"  pooled {arm}: nothing measurable")
        return
    weight = sum(r["n"] for r in good)
    pooled = sum(r["mean_u"] * r["n"] for r in good) / weight
    spread = st.pstdev([r["mean_u"] for r in good]) if len(good) > 1 else float("nan")
    print(
        f"  pooled {arm}: {len(good)} cells, {weight} trades, "
        f"mean_u {pooled:+.4f}, between-cell sd {_fmt(spread)}"
    )


def _against_null(rows: list[dict], arm: str, null: str) -> list[dict]:
    """`arm - null`, per instrument and clock. The study's primary statistic.

    The nulls here are **not** centred on zero - a bar is four numbers and a
    trigger inside `[low, high]` is assumed fillable at the trigger, which is
    worth a few hundredths of a unit on an arm with no direction in it - so a
    level read against zero is reading the fill model. The difference is read
    against the two arms' own spreads: the real arm's from its block bootstrap,
    which is what carries the serial dependence between tiling trades, and the
    null's from the spread of its own draws, floored at the real arm's own
    standard error over the number of draws so a lucky agreement between six
    draws cannot shrink it to nothing.
    """
    out: list[dict] = []
    real = {
        (r["interval"], r["symbol"]): r
        for r in rows
        if r.get("arm") == arm and r.get("stratum") == "all"
    }
    draws: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        if row.get("arm") == null and row.get("stratum") == "all" and not row.get("strength"):
            draws.setdefault((row["interval"], row["symbol"]), []).append(row)
    for key, row in sorted(real.items()):
        group = [d for d in draws.get(key, []) if math.isfinite(d.get("mean_u", float("nan")))]
        if not group or not math.isfinite(row.get("mean_u", float("nan"))):
            continue
        weight = sum(d["n"] for d in group)
        level = sum(d["mean_u"] * d["n"] for d in group) / weight
        se_real = (row["hi"] - row["lo"]) / 3.92 if math.isfinite(row.get("hi", np.nan)) else np.nan
        across = st.stdev([d["mean_u"] for d in group]) if len(group) > 1 else 0.0
        se_null = max(across / math.sqrt(len(group)), se_real / math.sqrt(len(group)))
        se = math.sqrt(se_real**2 + se_null**2)
        diff = row["mean_u"] - level
        out.append(
            {
                "symbol": row["symbol"],
                "klass": row.get("klass", ""),
                "interval": row["interval"],
                "venue": row.get("venue", ""),
                "arm": f"{arm}-vs-{null}",
                "stratum": "all",
                "n": row["n"],
                "mean_u": row["mean_u"],
                "coin_u": level,
                "sd_u": se,
                "lo": diff - 1.96 * se,
                "hi": diff + 1.96 * se,
                "med_u": diff,
                "z": diff / se if se > 0 else float("nan"),
                "p": 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(diff / se) / math.sqrt(2.0))))
                if se > 0
                else float("nan"),
                "cost_u": row.get("cost_u"),
                "net_u": diff - (row.get("cost_u") or float("nan")),
                "draw": len(group),
            }
        )
    return out


def _report_main(rows: list[dict]) -> None:
    columns = ("n", "rate", "held", "mean_u", "med_u", "top1", "lo", "hi", "z", "p",
               "cost_u", "net_u", "hit")  # fmt: skip
    arms = ("real", *(f"real-{name}" for name in INTRABARS[1:]), "const", *NULLS)
    for interval in ("1d", "15m"):
        for arm in arms:
            picked = [
                r
                for r in rows
                if r.get("interval") == interval
                and r.get("arm") == arm
                and r.get("stratum") == "all"
            ]
            if not picked:
                continue
            print(f"\n{interval} {arm}, pooled over strata\n")
            table(sorted(picked, key=lambda r: (r.get("klass", ""), r["symbol"])), columns)
            _pooled(picked, arm)
    print("\nthe side decomposition: real against its own coin\n")
    table(
        sorted(
            (r for r in rows if r.get("arm") == "real" and r.get("stratum") == "all"),
            key=lambda r: (r.get("interval", ""), r.get("klass", ""), r["symbol"]),
        ),
        ("n", "mean_u", "coin_u", "coin_sd", "z", "p", "p1", "coin_p1", "p2", "coin_p2"),
    )
    print("\nthe distance decomposition: real against const, in the common unit\n")
    table(
        sorted(
            (
                r
                for r in rows
                if r.get("arm") in {"real", "const"} and r.get("stratum") == "all"
            ),
            key=lambda r: (r.get("interval", ""), r["symbol"], r.get("arm", "")),
        ),
        ("n", "rate", "unit_c", "mean_c", "mean_u", "z", "p", "net_u"),
    )
    print("\nwithin volatility strata\n")
    table(
        sorted(
            (r for r in rows if r.get("stratum", "all") != "all"),
            key=lambda r: (r.get("interval", ""), r["symbol"], r.get("arm", ""), r["stratum"]),
        ),
        ("n", "rate", "mean_u", "lo", "hi", "z", "p", "net_u"),
    )
    for null in NULLS:
        for arm in ("real", "const"):
            diffs = _against_null(rows, arm, null if arm == "real" else f"{null}-const")
            if not diffs:
                continue
            print(f"\n{arm} minus {null}: the study's primary statistic\n")
            table(
                sorted(diffs, key=lambda r: (r["interval"], r.get("klass", ""), r["symbol"])),
                ("n", "draw", "mean_u", "coin_u", "med_u", "lo", "hi", "z", "p", "net_u"),
            )
            traded = [
                d
                for d in diffs
                if d["klass"] in {"fx", "metal", "index"} and math.isfinite(d["p"])
            ]
            survive, cut = bh([d["p"] for d in traded])
            beat = sum(1 for d in traded if d["med_u"] > 0)
            print(
                f"  {len(traded)} traded cells, {beat} above the null, "
                f"BH survivors {survive} at p <= {_fmt(cut)}"
            )
    traded = [
        r
        for r in rows
        if r.get("arm") == "real"
        and r.get("stratum") == "all"
        and r.get("klass") in {"fx", "metal", "index"}
        and math.isfinite(r.get("p", float("nan")))
    ]
    survive, cut = bh([r["p"] for r in traded])
    print(f"\nthe trade-level coin against zero, which is the statistic this study "
          f"says not to use: {len(traded)} cells, BH survivors {survive} "
          f"at p <= {_fmt(cut)}")  # fmt: skip


def _sweep_diffs(rows: list[dict]) -> list[dict]:
    """Every swept cell as `real - reflect`, keyed by the cell's own `N` and `K`."""
    null: dict[tuple, list[dict]] = {}
    for row in rows:
        if row.get("arm") == NULLS[0] and row.get("stratum") == "all":
            null.setdefault(
                (row["interval"], row["symbol"], row["venue"], row["n_window"], row["k"]), []
            ).append(row)
    out: list[dict] = []
    for row in rows:
        if row.get("arm") != "real" or row.get("stratum") != "all":
            continue
        key = (row["interval"], row["symbol"], row["venue"], row["n_window"], row["k"])
        group = [d for d in null.get(key, []) if math.isfinite(d.get("mean_u", float("nan")))]
        if not group or not math.isfinite(row.get("mean_u", float("nan"))):
            continue
        weight = sum(d["n"] for d in group)
        level = sum(d["mean_u"] * d["n"] for d in group) / weight
        se_real = (row["hi"] - row["lo"]) / 3.92 if math.isfinite(row.get("hi", np.nan)) else np.nan
        across = st.stdev([d["mean_u"] for d in group]) if len(group) > 1 else 0.0
        se = math.sqrt(se_real**2 + max(across, se_real) ** 2 / len(group))
        diff = row["mean_u"] - level
        out.append(
            {
                **{k: row.get(k) for k in ("symbol", "klass", "interval", "venue", "n_window",
                                           "k", "n", "rate", "mean_u", "cost_u", "drift_u")},  # fmt: skip
                "arm": "real-vs-null",
                "stratum": "all",
                "coin_u": level,
                "med_u": diff,
                "sd_u": se,
                "z": diff / se if se > 0 else float("nan"),
                "p": 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(diff / se) / math.sqrt(2.0))))
                if se > 0
                else float("nan"),
                "net_u": diff - (row.get("cost_u") or float("nan")),
                "draw": len(group),
            }
        )
    return out


def _report_sweep(rows: list[dict]) -> None:
    diffs = [d for d in _sweep_diffs(rows) if math.isfinite(d["p"])]
    traded = [d for d in diffs if d["klass"] in {"fx", "metal", "index"}]
    columns = ("n_window", "k", "n", "rate", "mean_u", "coin_u", "med_u", "z", "p",
               "drift_u", "net_u")  # fmt: skip
    print(f"\nthe sweep: {len(diffs)} cells, {len(traded)} on traded instruments\n")
    table(
        sorted(traded, key=lambda r: (r["interval"], r["symbol"], r["n_window"], r["k"])),
        columns,
    )
    survive, cut = bh([d["p"] for d in traded])
    beat = sum(1 for d in traded if d["med_u"] > 0)
    print(
        f"\nBH over {len(traded)} swept cells against the null: {survive} survive "
        f"at p <= {_fmt(cut)}, {beat} of them above the null"
    )
    print("\nthe K line and the N line, pooled over traded instruments per clock\n")
    print(f"  {'clock':6s} {'line':6s} {'value':>6s} {'cells':>6s} {'trades':>9s} "
          f"{'real':>9s} {'null':>9s} {'diff':>9s} {'cost':>8s} {'net':>9s}")  # fmt: skip
    for interval in ("1d", "15m"):
        for line, grid in (("K", K_GRID), ("N", N_GRID)):
            for value in grid:
                group = [
                    d
                    for d in traded
                    if d["interval"] == interval
                    and (d["k"] == value if line == "K" else d["n_window"] == value)
                    and (d["n_window"] == N0 if line == "K" else d["k"] == K0)
                ]
                if not group:
                    continue
                weight = sum(d["n"] for d in group)
                real = sum(d["mean_u"] * d["n"] for d in group) / weight
                null = sum(d["coin_u"] * d["n"] for d in group) / weight
                cost = st.fmean(
                    [d["cost_u"] for d in group if math.isfinite(d.get("cost_u", np.nan))]
                )
                print(
                    f"  {interval:6s} {line:6s} {value:6g} {len(group):6d} {weight:9d} "
                    f"{real:+9.4f} {null:+9.4f} {real - null:+9.4f} {cost:8.4f} "
                    f"{real - null - cost:+9.4f}"
                )
    print("\nthe best cell per instrument, which is what a sweep reported as a result selects\n")
    best: dict[tuple[str, str], dict] = {}
    for row in traded:
        key = (row["interval"], row["symbol"])
        if key not in best or row["med_u"] > best[key]["med_u"]:
            best[key] = row
    table(sorted(best.values(), key=lambda r: (r["interval"], r["symbol"])), columns)
    print("\nthe published cell, which is the headline\n")
    table(
        sorted(
            (r for r in traded if r["n_window"] == N0 and r["k"] == K0),
            key=lambda r: (r["interval"], r["symbol"]),
        ),
        columns,
    )


def _report_power(rows: list[dict]) -> None:
    """The planted continuation, and where the test stops seeing it.

    Three filters that each cost a wrong answer when they were missing:

    * **`stratum == "all"`.** The strata rows carry an `n` too, so including
      them averaged four sub-samples into every unplanted cell and reported the
      trade rate as 99.65 against the real 196.
    * **traded classes only.** `Range Break` reads `+1.59` to `+2.54` units a
      trade, so pooling it with FX moves the baseline by more than any plant.
    * **the comparison is against the unplanted arm, not against the coin.**
      The row's own `p` is the trade-level side shuffle, and the unplanted
      arm beats that at `z +4` to `+5` from the fill offset alone - so a
      detection rate read off it is 1.00 at a planted strength of zero.
    """
    cells = [
        r
        for r in rows
        if r.get("arm") == NULLS[0]
        and r.get("stratum") == "all"
        and r.get("klass") in {"fx", "metal", "index"}
        and math.isfinite(r.get("mean_u", float("nan")))
    ]
    if not cells:
        print("\nno planted cells to report")
        return

    def _pool(group: list[dict]) -> tuple[float, float, int]:
        """The trade-weighted mean and its standard error over the draws."""
        weight = sum(r["n"] for r in group)
        mean = sum(r["mean_u"] * r["n"] for r in group) / weight
        each = [
            (r["hi"] - r["lo"]) / 3.92
            for r in group
            if math.isfinite(r.get("hi", float("nan")))
        ]
        se = (st.fmean(each) / math.sqrt(len(each))) if each else float("nan")
        return mean, se, int(weight)

    by: dict[tuple[str, str, float], list[dict]] = {}
    for row in cells:
        by.setdefault((row["interval"], row["symbol"], row.get("strength", 0.0)), []).append(row)
    strengths = sorted({k[2] for k in by if k[2]})

    print("\nplanted continuation on the %s null, by strength\n" % NULLS[0])
    print(f"  {'clock':6s} {'strength':>9s} {'cells':>6s} {'trades':>10s} "
          f"{'mean_u':>9s} {'rate':>8s}")  # fmt: skip
    for interval in sorted({k[0] for k in by}):
        for strength in (0.0, *strengths):
            group = [r for k, g in by.items() if k[0] == interval and k[2] == strength for r in g]
            if not group:
                continue
            mean, _se, weight = _pool(group)
            rate = st.fmean([r["rate"] for r in group])
            print(f"  {interval:6s} {strength:9.3f} {len(group):6d} {weight:10d} "
                  f"{mean:+9.4f} {rate:8.2f}")  # fmt: skip

    print("\nwhere the test goes blind, in realised units a trade\n")
    print("  A plant fires on every `PLANT_N`-bar close extreme and a trade holds several")
    print("  bars, so a trade collects two to three of them and the **realised** gain is")
    print("  the plant times that. The realised column is what an effect is compared to,")
    print("  and `detected` is the share of instruments whose planted mean clears its own")
    print("  unplanted mean by 1.96 combined standard errors.\n")
    print(f"  {'clock':6s} {'planted':>8s} {'realised':>9s} {'recovery':>9s} "
          f"{'z median':>9s} {'detected':>9s}")  # fmt: skip
    for interval in sorted({k[0] for k in by}):
        zero = {k[1]: _pool(g) for k, g in by.items() if k[0] == interval and not k[2]}
        base = _pool([r for k, g in by.items() if k[0] == interval and not k[2] for r in g])[0]
        for strength in strengths:
            got = {k[1]: _pool(g) for k, g in by.items() if k[0] == interval and k[2] == strength}
            if not got:
                continue
            zeds = []
            for symbol, (mean, se, _n) in got.items():
                if symbol not in zero:
                    continue
                base_mean, base_se, _ = zero[symbol]
                spread = math.sqrt(se**2 + base_se**2)
                if spread > 0:
                    zeds.append((mean - base_mean) / spread)
            if not zeds:
                continue
            mean = _pool([r for k, g in by.items() if k[0] == interval and k[2] == strength
                          for r in g])[0]  # fmt: skip
            gain = mean - base
            print(
                f"  {interval:6s} {strength:8.3f} {gain:+9.4f} {gain / strength:9.2f} "
                f"{st.median(zeds):+9.2f} "
                f"{sum(1 for z in zeds if z > 1.96) / len(zeds):9.2f}"
            )


if __name__ == "__main__":
    raise SystemExit(main())
