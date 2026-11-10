"""Does a confirmation delay of k bars add selection, or only buy hit rate?

    ./.secrets/lab.sh run research/harness/entry_timing.py MODE=leak  ET_WORKERS=12
    ./.secrets/lab.sh run research/harness/entry_timing.py MODE=calib ET_WORKERS=10
    ./.secrets/lab.sh run research/harness/entry_timing.py MODE=main  ET_WORKERS=14 ET_SURROGATES=1
    ./.secrets/lab.sh run research/harness/entry_timing.py MODE=power ET_WORKERS=12

Always with `OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1`: this
runs a process pool and sklearn once drove the lab's load to 658 on 64 cores
without them.

`leak` runs the surrogate arms only and is the one to run first. `calib`
measures the harness's own settlement bias and reports the number every level
in the study has to be read against. `main` is the study. `power` plants the
effect and sweeps its strength. Every number in
`research/docs/entry-timing.md` comes from one of the four at the parameters
named there; cells land in `out/entry_timing/cells-<mode>.csv`.

Environment, all optional: `ET_STORE` (the 1d price store), `ET_SEQLAB` (the
15m/1h npz cache), `ET_OUT`, `ET_INTERVALS`, `ET_POPULATIONS`, `ET_DRAWS`
(day-block draws), `ET_PLACEBO` (placebo anchors per real signal), `ET_SEED`,
`ET_SURROGATES` (surrogate series per real one), `ET_REACH`, `ET_SQUEEZE` (1
keeps vol-impulse's slow leg on), `ET_GREEDY`, `ET_REFUSAL` (`close` or
`touch`), `ET_GAPFILL`, `ET_FLOOR` (`spread` or `atr`), `ET_SUBSTEPS`,
`ET_SUBGRID`, `ET_DEMEAN`, `ET_STOPMULT`, `ET_PLANT` (the power grid),
`ET_CHUNK`, `ET_WORKERS`.

**`lab.sh run` rsyncs the repository with `--delete`, so a second agent syncing
its own worktree removes this file from `repo/` and a later launch cannot find
it.** It happened twice while this study ran. Staging the file outside `repo/`
and putting `repo` on `PYTHONPATH` avoids it; either way,
`failed-sync-still-launches-the-run` applies and the remote file is worth a
`grep` before a result is trusted.

## The null is arithmetic, which is why this harness is small

Under the null price is a martingale and every arm's exit is a bounded stopping
time, so moving an entry k bars later has **expected P&L exactly zero** in
units of the k=0 risk, counting a refused signal as zero - whatever the delay
does to the hit rate, to the reward:risk, or to the refusal rate. So
`mean R0 = 0` *is* the fair-rate null, no simulation required, and the hit-rate
column beside it is the exchange `CLAUDE.md` already measured on fade-to-value
(31% to 48% hit, 1.88 to 0.94 reward). The surrogate arms are not there to
supply the null; they are there to catch a leak in this file.

## Three defects this file is shaped around

**The race starts on the bar after the fill.** `smc-conjunctions.md` read
+0.432R on a driftless walk before that was fixed, and the price-action study
read +0.2234R from the same shape in a different place. A delay study is the
most exposed version of it: moving the entry forward in time is exactly the
operation that can accidentally settle off the bar it enters on. `_settle`
starts at `fill + 1` and a tie inside one bar goes to the **stop**.

**A refusal is not free selection.** An `anchored` arm refuses a signal whose
close has already passed the stop, and those signals are k=0 losers by
construction - so a refusal rate cannot be read as evidence on its own. The
per-signal mean in R0 with a refusal scored **zero** is the statistic that nets
that off, and `shifted` is the arm with no refusals at all.

**A delayed entry is not stopped by an excursion it was not in.** A parked
signal genuinely has no stop order, so the default refusal test is on the
**close** of the fill bar. `ET_REFUSAL=touch` refuses when the stop price was
reached intrabar before the fill instead; the gap between the two is how much
of a delay's apparent gain is that free pass.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import math
import os
import random
import sqlite3
import statistics as st
from dataclasses import dataclass, field
from multiprocessing import Pool
from pathlib import Path

import numpy as np

from research.ideas.level_shield import Series, bar_shuffle, garch_bars, units, walk_geometry
from till_infinity.indicators import candles as C
from till_infinity.strategies import volimpulse as VI
from till_infinity.strategies.structure import REACH, SPREADS
from till_infinity.strategies.structure import Fold as BosFold

STORE = os.environ.get("ET_STORE") or str(Path.home() / "till_infinity/.data/prices/prices.db")
SEQLAB = Path(os.environ.get("ET_SEQLAB") or Path.home() / "till_infinity/data/seqlab")
OUT = Path(os.environ.get("ET_OUT") or Path.home() / "till_infinity/out/entry_timing")

#: The lags swept. Zero is the deployed `EdgeEntry` and is the baseline every
#: other arm is read against.
LAGS = (0, 1, 2, 3, 4, 5)

#: Targets as multiples of the **k=0** risk. Under `anchored` that is one fixed
#: price every arm races to; a walk pays exactly zero at each of them, which is
#: what makes a departure from zero the finding rather than the arithmetic.
TARGETS = (1.0, 2.0, 3.0)

#: `vol-impulse` has **no protective stop**: `decide` sets `stop` as a sizing
#: distance, `protective_stop` is False so no order defends it, and `_clock`
#: closes the position after 16 bars. `mark` is that exit - no stop, no target,
#: marked at the hold - and it is the cleanest arm in the study, because with
#: no barrier there is no hit-rate-for-reward exchange for a delay to collect
#: and the only thing left for it to do is select.
MARK = "mark"

#: Bars held, per rule, as the rule's own clock. `structure.HOLD_MINUTES // 15`
#: is **96** and `volimpulse.HOLD_BARS` is **16** - not 16 for both, which a
#: brief for this study had them as. The difference decides how much of a hold
#: a delay eats: 5 bars is 5.2% of smc-bos-causal's and 31.3% of vol-impulse's.
HOLD = {"bos": 96, "impulse": 16}

#: The volatility unit's EWMA span per interval, from `level_shield.SETTINGS`
#: so the two studies' units are the same object.
UNIT_SPAN = {"15m": 48, "1h": 48, "4h": 30, "1d": 20}

#: Wilder's period, as `smc_bos_c_L50|M15|N20|time` states it.
ATR_N = 14

#: What `ArrivalEntry.candle_tolerance_vol` is **documented** as (volatility
#: units) and what `ArrivalEntry._candle_at` **implements** (`abs(level) * tol
#: / 100`, a fraction of price). Both are run - arms `v*` and `w*` - because
#: the two differ by a factor that depends only on the instrument's price
#: level, which is one field in two units.
CANDLE_TOL_VOL = 0.1
CANDLE_TOL_PRICE = 0.1 / 100.0

DRAWS = int(os.environ.get("ET_DRAWS") or 2000)
PLACEBO = int(os.environ.get("ET_PLACEBO") or 5)
SEED = int(os.environ.get("ET_SEED") or 7)
SURROGATES = int(os.environ.get("ET_SURROGATES") or 2)
REACH_BARS = int(os.environ.get("ET_REACH") or REACH)
#: `vol-impulse` as deployed keeps its slow leg, and the cache turned out to
#: carry 294k 15-minute bars rather than the 5k the recorded catalogue has -
#: so the 750-bin squeeze window warms with eleven years to spare and there
#: is no reason to run the rule without the gate it ships with. Firing rate
#: measured on EURUSD: 2,332 with the leg on, 10,844 with it off, of 294,499.
SQUEEZE = bool(int(os.environ.get("ET_SQUEEZE") or 1))

#: Keep one position at a time, which is **what the desk does** - `_clock`
#: runs before the fold's own event precisely so a one-position rule is
#: greedy - and which de-overlaps the outcome windows at the same time. The
#: spacing is `hold + max(LAGS)` and is read off **bar indices only**, so it
#: cannot select on an outcome; a short skip rule against a long forward
#: window once gave direction AUC 0.79 that collapsed to 0.51.
GREEDY = bool(int(os.environ.get("ET_GREEDY") or 1))
REFUSAL = (os.environ.get("ET_REFUSAL") or "close").strip().lower()

#: Fill a stop at the worse of the stop and the bar's open. Off by default:
#: see `_settle` - the surrogates fabricate a 0.65-bar-range gap on every
#: bar and it cost the control -0.6378R.
GAPFILL = bool(int(os.environ.get("ET_GAPFILL") or 0))

#: `spread` puts the rule's `N20` leg on the stop at the venue's own live
#: round trip, which is the rule as specified and which binds on tight FX:
#: 20 x 0.9 pips against a 15-minute ATR of 5-8. `atr` drops the floor, so
#: the ATR leg binds everywhere and every instrument carries one bar's range
#: of stop - the geometry sensitivity, not the rule.
FLOOR = (os.environ.get("ET_FLOOR") or "spread").strip().lower()
WORKERS = int(os.environ.get("ET_WORKERS") or 24)

#: The Deriv indices in the cache. **A control for one named property**: a
#: Volatility index is published with constant sigma and independent
#: increments, so there is no information in the bars after a signal and a
#: delay can add nothing. Jump and Step are *not* that control - they have
#: jumps and steps - and are carried under their own labels.
SYNTHETIC = {
    "Volatility 25 Index": "iid-sigma",
    "Volatility 75 Index": "iid-sigma",
    "Jump 75 Index": "jumps",
    "Step Index": "steps",
}

#: The surrogate arms, by name. **`walk-path` is the one that must read zero**
#: - see `walk_path` - and the other three are the repo's existing arms, kept
#: because the gap between them and `walk-path` is itself the measurement.
SURROGATE_ARMS = ("walk-path", "walk-geometry", "bar-shuffle", "garch-bars")

#: The key a cell is filed under.
COLUMNS = ("population", "interval", "source", "kind", "symbol", "arm", "geometry", "outcome")

#: What `summarise` reports, in order.
STATS = [
    "n", "fill", "delay", "mean_r0", "med_r0", "mean_rk", "lo", "hi", "p",
    "diff", "dlo", "dhi", "dp",
    "net_r0", "net_lo", "net_hi", "hit", "fair", "decided", "cost_r", "touch", "sd",
]


# ───────────────────────────────── the data ─────────────────────────────────


def seqlab_series(interval: str) -> list[Series]:
    """Every cached symbol at this interval, longest first."""
    out: list[Series] = []
    for path in sorted(SEQLAB.glob(f"*.{interval}.npz")):
        symbol = path.name[: -len(f".{interval}.npz")]
        with np.load(path) as data:
            arr = {k: data[k].astype(float) for k in ("time", "open", "high", "low", "close")}
        if len(arr["close"]) < 1_000:
            continue
        out.append(
            Series(
                feed=symbol,
                venue="cache",
                interval=interval,
                ts=arr["time"],
                open=arr["open"],
                high=arr["high"],
                low=arr["low"],
                close=arr["close"],
            )
        )
    return sorted(out, key=lambda s: -len(s.close))


def db_series(interval: str) -> list[Series]:
    """The price store, one venue per feed by bar count, de-duplicated by `ts`.

    De-duplication is not tidiness. `spx500` and `us100` hold **two rows per
    timestamp** at 1d - 6,005 and 6,008 rows over 3,006 stamps, 503 bars a year
    on a daily series - so a fold reading them in arrival order confirms every
    bar twice, a 96-bar hold is 48 real days, and an ATR spans half what it
    says. Dropped rows are printed rather than silently absorbed.
    """
    con = sqlite3.connect(f"file:{STORE}?mode=ro", uri=True)
    out: list[Series] = []
    feeds = [r[0] for r in con.execute("select distinct feed from bars order by feed")]
    for feed in feeds:
        row = con.execute(
            "select venue, count(*) n from bars where feed=? and interval=? and closed=1 "
            "group by venue order by n desc, venue asc limit 1",
            (feed, interval),
        ).fetchone()
        if row is None:
            continue
        rows = con.execute(
            "select ts, open, high, low, close from bars where feed=? and venue=? "
            "and interval=? and closed=1 order by ts",
            (feed, row[0], interval),
        ).fetchall()
        if len(rows) < 1_000:
            continue
        arr = np.asarray(rows, dtype=float)
        _stamps, first = np.unique(arr[:, 0], return_index=True)
        if len(first) != len(arr):
            print(f"  {feed}.{interval}: dropped {len(arr) - len(first)} duplicate timestamps")
        arr = arr[np.sort(first)]
        out.append(
            Series(
                feed=feed,
                venue=row[0],
                interval=interval,
                ts=arr[:, 0],
                open=arr[:, 1],
                high=arr[:, 2],
                low=arr[:, 3],
                close=arr[:, 4],
            )
        )
    con.close()
    return out


def db_spread_px(feed: str, venue: str) -> float:
    """The median recorded round trip for this feed **on this venue**, in price.

    Zero where there are no quotes, which is how a feed ends up geometry-only
    rather than priced off another venue's spread: the same instrument runs
    0.17 to 3.30 bps across venues and `pooled-medians-invert-subgroups` is
    the recorded reason never to pool them.
    """
    con = sqlite3.connect(f"file:{STORE}?mode=ro", uri=True)
    rows = con.execute(
        "select bid, ask from quotes where feed=? and venue=? and bid>0 and ask>bid",
        (feed, venue),
    ).fetchall()
    con.close()
    return 0.0 if not rows else float(st.median(ask - bid for bid, ask in rows))


#: The price store names a feed, the terminal names a symbol, and for three of
#: them those differ. Anything not here is asked for by its uppercase feed name
#: and comes back `nan` if the terminal does not carry it - which is the right
#: answer: an unpriced cell is geometry, never a free round trip.
BRIDGE_NAME = {"gold": "XAUUSD", "btc": "BTCUSD", "eth": "ETHUSD"}


def cache_spread_px(symbol: str) -> float:
    """The terminal's own quoted round trip, or `nan`.

    Through `research.harness.venue.quoted`, the one place that asks: the
    per-bar `spread` column is in **points, not price**, is zero on 7-35% of
    bars, and reading a cost off it is how a pair once screened at a 476% round
    trip. `nan` means the cell is unpriced, never free.
    """
    try:
        from research.harness.venue import quoted
    except ImportError:  # pragma: no cover - the bridge module is lab-side
        return float("nan")
    # The cache names a symbol the way the terminal does, spaces and all, so
    # only a store feed - which is lower case - is translated. Upper-casing
    # everything turned "Volatility 75 Index" into a name no venue carries.
    named = BRIDGE_NAME.get(symbol) or (symbol.upper() if symbol.islower() else symbol)
    return float(quoted(named, timeout=8.0))


def atr(series: Series, n: int = ATR_N) -> np.ndarray:
    """Wilder's ATR, causal, as the rule's stop leg needs it."""
    high, low, close = series.high, series.low, series.close
    prev = np.concatenate(([close[0]], close[:-1]))
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    out = np.empty(len(tr))
    cur = float(tr[0])
    for i, x in enumerate(tr):
        cur = x if i == 0 else (cur * (n - 1) + x) / n
        out[i] = cur
    return out


# ──────────────────────────────── the signals ────────────────────────────────


@dataclass(frozen=True, slots=True)
class Signal:
    """One thing a deployed rule wanted, with the geometry it named.

    `risk` is the k=0 risk in price and is the denominator of every R here:
    `risk-vol-is-not-the-stop-distance` is why it is the rule's own stop
    distance and not a volatility feature.
    """

    i: int
    side: int
    risk: float
    level: float


def _usable(signals: list[Signal], n: int, hold: int) -> list[Signal]:
    """Signals every arm can fill, settle, and hold alone.

    Two filters, both on bar indices alone so neither can select on an
    outcome. The first drops signals too near the end for the latest arm to
    settle - without it the late arms quietly lose those signals and a
    difference of means is partly a difference of populations. The second
    keeps one position at a time at `hold + max(LAGS)` spacing, which is both
    what a one-position desk does and what de-overlaps the outcome windows.
    """
    last = n - (max(LAGS) + hold + 2)
    kept = [s for s in signals if s.i <= last]
    if not GREEDY:
        return kept
    spacing = hold + max(LAGS)
    out: list[Signal] = []
    free = -1
    for sig in kept:
        if sig.i > free:
            out.append(sig)
            free = sig.i + spacing
    return out


def bos_signals(series: Series, spread_px: float, *, reach: int = REACH_BARS) -> list[Signal]:
    """`smc_bos_c_L50|M15|N20|time`'s breaks, through the production fold.

    The fold and not a copy, so the arm and the rule are the same detector.
    CHoCH events are dropped because the rule does not trade them, and the stop
    is the wider of one ATR(14) at the signal close and 20 spreads. Where no
    spread is recorded the floor is zero and the ATR leg binds - which is what
    happens on gold, spx500 and us100 anyway (`smc-bos-reconcile.md`).
    """
    fold = BosFold(reach=reach)
    unit = atr(series)
    out: list[Signal] = []
    for i in range(len(series.close)):
        for event in fold.update(
            float(series.high[i]), float(series.low[i]), float(series.close[i])
        ):
            if event.kind != "bos":
                continue
            risk = max(float(unit[i]), SPREADS * max(spread_px, 0.0))
            if risk > 0.0:
                out.append(
                    Signal(i=i, side=event.side.sign, risk=risk, level=float(series.close[i]))
                )
    return out


def impulse_signals(series: Series, *, squeeze: bool = SQUEEZE) -> list[Signal]:
    """`vol-impulse`'s impulses, through the production fold.

    The frozen HAR is per feed and there are five of them, so a symbol without
    one cannot fire - absent is not zero. `window` is shortened to
    `SQUEEZE_BINS` when the slow leg is off: with `require_squeeze=False` the
    rank is computed and unused, so the window decides only how long the fold
    stays cold, and the full 750 four-hour bins is 125 days of a 208-day cache.

    The HAR forecasts a **15-minute** mean absolute return, so this rule runs
    at 15m and nowhere else: at 1h the forecast is about half the move it would
    be compared against and `impulse` would fire on ordinary bars.
    """
    har = VI.HAR.get(series.feed.lower())
    if har is None:
        return []
    fold = VI.Fold(
        har=har,
        require_squeeze=squeeze,
        window=VI.SQUEEZE_WINDOW if squeeze else VI.SQUEEZE_BINS,
    )
    out: list[Signal] = []
    for i in range(len(series.close)):
        event = fold.update(
            int(series.ts[i]), float(series.high[i]), float(series.low[i]), float(series.close[i])
        )
        if event is None:
            continue
        risk = VI.IMPULSE_MULT * event.sigma * float(series.close[i])
        if risk > 0.0:
            out.append(Signal(i=i, side=event.side.sign, risk=risk, level=float(series.close[i])))
    return out


def signals_for(population: str, series: Series, spread_px: float) -> list[Signal]:
    """The population's signals, usable and at the stop width this run asks for.

    `STOPMULT` is 1.0 for the rule. It exists because it is the handle that
    identified the settlement bias: a bar-level stop filled *at* the stop price
    credits the trade with however far the path travelled past it inside the
    crossing bar, and that credit grows as the stop gets closer in units of a
    bar's own step. Widening it is therefore the one lever that varies the
    nuisance while holding the signal fixed, which is what
    `a-correction-derived-from-the-thing-it-corrects` says a correction needs.
    """
    found = bos_signals(series, spread_px) if population == "bos" else impulse_signals(series)
    if STOPMULT != 1.0:
        found = [
            Signal(i=x.i, side=x.side, risk=x.risk * STOPMULT, level=x.level) for x in found
        ]
    return _usable(found, len(series.close), HOLD[population])


def placebo_signals(
    series: Series, real: list[Signal], unit: np.ndarray, hold: int, rng: random.Random
) -> list[Signal]:
    """The same mechanics at random anchors, `PLACEBO` draws per real signal.

    `patterns.md` is why this is not optional: a double bottom's 58% hit rate
    was matched by a placebo at **57.6%** on the same stop and target distances
    taken at an arbitrary bar. The risk travels in **volatility units** so the
    geometry is matched rather than the price distance, and the side is the real
    signal's so this arm is not secretly a direction test.
    """
    n = len(series.close)
    lo, hi = max(REACH_BARS, ATR_N) + 1, n - (hold + max(LAGS) + 2)
    if hi <= lo or not real:
        return []
    out: list[Signal] = []
    for sig in real:
        scale = sig.risk / max(float(unit[sig.i]), 1e-12)
        for _ in range(PLACEBO):
            j = rng.randrange(lo, hi)
            risk = scale * float(unit[j])
            if risk > 0.0:
                out.append(Signal(i=j, side=sig.side, risk=risk, level=float(series.close[j])))
    return out


# ───────────────────────────────── the arms ─────────────────────────────────


def arm_names() -> tuple[str, ...]:
    """`k` a pure wait, `c` a close in the trade's direction, `w`/`v`
    production's candle witness at the implemented and the documented
    tolerance, `r` the random-delay twin of `c`."""
    return tuple(f"k{k}" for k in LAGS) + tuple(
        f"{kind}{k}" for kind in "cwvr" for k in LAGS[1:]
    )


def _closes_with(series: Series, j: int, side: int) -> bool:
    return (float(series.close[j]) - float(series.close[j - 1])) * side > 0.0


def _candle_confirms(series: Series, j: int, sig: Signal, tolerance: float) -> bool:
    """Production's own witness: `indicators.candles.confirms` at the signal price.

    The same function `ArrivalEntry._candle_at` calls, on the last two closed
    bars, so this measures the mechanism the desk already has rather than a
    fourth one.
    """
    if j < 1:
        return False
    bars = [
        C.Bar(
            open=float(series.open[t]),
            high=float(series.high[t]),
            low=float(series.low[t]),
            close=float(series.close[t]),
        )
        for t in (j - 1, j)
    ]
    return bool(C.confirms(bars, sig.level, want_up=sig.side > 0, tolerance=tolerance))


def fill_bar(
    series: Series, sig: Signal, arm: str, unit: np.ndarray, rng: random.Random, pool: list[int]
) -> int | None:
    """The bar this arm fills on, or None for "this arm refuses the signal"."""
    kind, k = arm[0], int(arm[1:])
    n = len(series.close)
    if kind == "k":
        j = sig.i + k
        return j if j < n else None
    if kind == "r":
        if not pool:
            return None
        drawn = rng.choice(pool)
        j = sig.i + drawn
        return None if drawn <= 0 or j >= n else j
    for j in range(sig.i + 1, min(sig.i + 1 + k, n)):
        if kind == "c" and _closes_with(series, j, sig.side):
            return j
        if kind == "w" and _candle_confirms(series, j, sig, abs(sig.level) * CANDLE_TOL_PRICE):
            return j
        if kind == "v" and _candle_confirms(series, j, sig, CANDLE_TOL_VOL * float(unit[j])):
            return j
    return None


def delay_pool(series: Series, signals: list[Signal], k: int, unit: np.ndarray) -> list[int]:
    """`c{k}`'s realised delays on this series, with its refusals as zeros.

    The random twin inherits the refusal rate as well as the mean delay, or
    "waiting helped" and "trading less helped" become one column - the duty
    cycle control, which every pause rule on this desk has beaten its baseline
    and failed.
    """
    still = random.Random(0)
    out = []
    for sig in signals:
        j = fill_bar(series, sig, f"c{k}", unit, still, [])
        out.append(0 if j is None else j - sig.i)
    return out


# ─────────────────────────────── the settlement ───────────────────────────────

#: An empty index, so `_settle` has one shape for "no target" and "not reached".
_NONE: np.ndarray = np.array([], dtype=int)

#: The outcomes every arm is settled on. `clock` is the rule's own exit - stop,
#: else the mark at the hold - and the rest add a target at a multiple of the
#: k=0 risk. All four are bounded, so a walk pays exactly zero on each.
_OUTCOMES: tuple[tuple[str, float | None], ...] = (
    ("clock", None),
    (MARK, None),
    *((f"tgt{int(t)}", t) for t in TARGETS),
)

#: What the placebo and surrogate arms are read at. The rule's own exit and the
#: 2R race, because those are the two the write-up reports and eight outcomes
#: on five placebo draws over eleven years of 15-minute bars is four gigabytes
#: of rows nobody reads.
_HEADLINE: tuple[tuple[str, float | None], ...] = (
    ("clock", None),
    (MARK, None),
    ("tgt2", 2.0),
)


@dataclass(frozen=True, slots=True)
class Filled:
    j: int
    entry: float
    stop: float
    risk_k: float
    touched: bool


def place(series: Series, sig: Signal, j: int | None, geometry: str, refusal: str) -> Filled | None:
    """The fill, or None when this arm refuses the signal.

    `anchored` keeps the stop at the price the signal named, so a delay walks
    the entry toward the target and raises the risk; a close already past the
    stop is refused. `shifted` re-anchors the distance to the new entry, so
    reward:risk is constant and nothing is ever refused - the arm that isolates
    the selection question from the exchange.
    """
    if j is None:
        return None
    entry = float(series.close[j])
    anchor = sig.level - sig.side * sig.risk
    stop = anchor if geometry == "anchored" else entry - sig.side * sig.risk
    risk_k = abs(entry - stop)
    if risk_k <= 0.0:
        return None
    hit = False
    if j > sig.i:
        hi, lo = series.high[sig.i + 1 : j + 1], series.low[sig.i + 1 : j + 1]
        hit = bool(np.any(lo <= anchor) if sig.side > 0 else np.any(hi >= anchor))
    if geometry == "anchored":
        if (entry - anchor) * sig.side <= 0.0:
            return None
        if refusal == "touch" and hit:
            return None
    return Filled(j=j, entry=entry, stop=stop, risk_k=risk_k, touched=hit)


def _settle(
    series: Series,
    got: Filled,
    side: int,
    target: float | None,
    hold: int,
    *,
    use_stop: bool = True,
) -> tuple[float, str]:
    """P&L in price, **from the bar after the fill**, marked at the clock.

    The one line this desk has paid for twice. A tie inside one bar goes to the
    **stop**, because bar-level first passage cannot say which barrier a bar
    reached first and the conservative rule is the only honest one.

    ## The stop fills at the stop, and the gap reading is a leak in the control

    Filling it at the worse of the stop and the bar's open is the honest
    reading of a gap on a real series and is **unusable with these
    surrogates**. `node/surrogates.walk_with_bar_geometry` and
    `level_shield.bar_shuffle` both draw each bar's open *inside that bar's own
    range*, independently of the previous close, so a synthetic bar's open is a
    fabricated gap. Measured on EURUSD 15m, `|open - previous close|` as a
    share of the bar range: **0.0000 on the real series, 0.6481 on its
    walk-geometry twin and 0.6721 on its bar shuffle**, at the median. A
    gap-aware fill therefore charges the null arm about two thirds of a bar
    range on every stop-out and the real arm nothing, and the first run of this
    harness duly read **-0.6378R at k=0 on walk-geometry** where a martingale
    must read zero.

    So the headline fills at the stop price, which is symmetric across arms and
    leak-free, and `ET_GAPFILL=1` restores the gap reading for a real-bars-only
    sensitivity. Underfilling is also the safer direction here: the recorded
    catalogue's stop fills were measured **pessimistic** by 0.08 to 0.36R
    (`smc-bos-reconcile.md`), not optimistic.
    """
    n = len(series.close)
    start, end = got.j + 1, min(got.j + 1 + hold, n)
    hi, lo = series.high[start:end], series.low[start:end]
    if not use_stop:
        stopped = _NONE
        reached = (
            _NONE
            if target is None
            else np.flatnonzero(hi >= target if side > 0 else lo <= target)
        )
    elif side > 0:
        stopped = np.flatnonzero(lo <= got.stop)
        reached = np.flatnonzero(hi >= target) if target is not None else _NONE
    else:
        stopped = np.flatnonzero(hi >= got.stop)
        reached = np.flatnonzero(lo <= target) if target is not None else _NONE
    first_s = int(stopped[0]) if len(stopped) else 10**9
    first_t = int(reached[0]) if len(reached) else 10**9
    if first_s <= first_t and first_s < 10**9:
        fill = got.stop
        if GAPFILL:
            at = start + first_s
            opened = float(series.open[at])
            fill = min(got.stop, opened) if side > 0 else max(got.stop, opened)
        return (fill - got.entry) * side, "stop"
    if first_t < 10**9 and target is not None:
        return (target - got.entry) * side, "target"
    return (float(series.close[end - 1]) - got.entry) * side, "clock"


# ─────────────────────────────── the aggregation ───────────────────────────────

#: The per-signal columns, derived from the dataclass rather than written out:
#: `dedupe()` on this desk once merged 7 of 15 fields of a type that had grown
#: four, and the ones it dropped were the numerator of a rate whose denominator
#: it kept.
def _fields() -> tuple[str, ...]:
    return tuple(f.name for f in dataclasses.fields(Cell))


@dataclass
class Cell:
    """One (population, interval, source, kind, symbol, arm, geometry, outcome).

    Flat arrays rather than rows of objects, so a day block is a mask and a
    pooled cell over eleven years of 15-minute bars still fits in memory. `r0`
    carries a **zero for a refusal**: that is what nets the refusal of a
    certain loser off against the worse reward:risk the survivors carry.
    Reading the refusal rate on its own instead is the mistake the whole design
    is arranged to avoid.
    """

    r0: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    rk: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    day: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int32))
    filled: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=bool))
    won: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=bool))
    decided: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=bool))
    fair: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float32))
    cost: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float32))
    touched: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=bool))
    delay: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int8))

    def __len__(self) -> int:
        return len(self.r0)

    @classmethod
    def blank(cls, n: int) -> Cell:
        """`n` refused rows, which every row then overwrites or leaves as one.

        A refusal is the identity here - zero P&L, unfilled, undecided, no
        fair rate - so starting from it means a path that forgets to write a
        row scores a decline rather than an invented trade.
        """
        return cls(
            r0=np.zeros(n, dtype=np.float64),
            rk=np.zeros(n, dtype=np.float64),
            day=np.zeros(n, dtype=np.int32),
            filled=np.zeros(n, dtype=bool),
            won=np.zeros(n, dtype=bool),
            decided=np.zeros(n, dtype=bool),
            fair=np.full(n, np.nan, dtype=np.float32),
            cost=np.zeros(n, dtype=np.float32),
            touched=np.zeros(n, dtype=bool),
            delay=np.zeros(n, dtype=np.int8),
        )


def run_series(
    series: Series,
    signals: list[Signal],
    *,
    hold: int,
    trip: float,
    rng: random.Random,
    refusal: str = REFUSAL,
    outcomes: tuple[tuple[str, float | None], ...] = _OUTCOMES,
) -> dict[tuple[str, str, str], Cell]:
    """Every arm x geometry x outcome on one series. The inner loop.

    `outcomes` is narrowed for the placebo and surrogate sources: those arms
    are read at the headline outcome only, because eight outcomes x 26 arms x
    five placebo draws over 294,000 bars is four gigabytes of rows nobody
    reads.
    """
    unit = units(series, UNIT_SPAN.get(series.interval, 48))
    day = (series.ts // 86_400).astype(np.int32)
    pools = {k: delay_pool(series, signals, k, unit) for k in LAGS[1:]}
    total = len(signals)
    cells = {
        (arm, geometry, name): Cell.blank(total)
        for arm in arm_names()
        for geometry in ("anchored", "shifted")
        for name, _mult in outcomes
    }
    costed = math.isfinite(trip) and trip > 0.0
    for arm in arm_names():
        pool = pools.get(int(arm[1:]), []) if arm[0] == "r" else []
        for geometry in ("anchored", "shifted"):
            for row, sig in enumerate(signals):
                stamp = day[sig.i]
                for name, _mult in outcomes:
                    cells[(arm, geometry, name)].day[row] = stamp
                j = fill_bar(series, sig, arm, unit, rng, pool)
                got = place(series, sig, j, geometry, refusal)
                if got is None:
                    continue
                waited = got.j - sig.i
                for name, mult in outcomes:
                    cell = cells[(arm, geometry, name)]
                    cell.touched[row] = got.touched
                    cell.delay[row] = waited
                    base = sig.level if geometry == "anchored" else got.entry
                    target = None if mult is None else base + sig.side * mult * sig.risk
                    if target is not None and (target - got.entry) * sig.side <= 0.0:
                        # The target is already behind the delayed entry, so
                        # there is no race left. Refused, not won: crediting it
                        # would hand the arm a free target.
                        continue
                    pnl, how = _settle(
                        series, got, sig.side, target, hold, use_stop=name != MARK
                    )
                    cell.r0[row] = pnl / sig.risk
                    cell.rk[row] = pnl / got.risk_k
                    cell.filled[row] = True
                    cell.won[row] = how == "target"
                    cell.decided[row] = how in ("target", "stop")
                    if target is not None:
                        reward = abs(target - got.entry)
                        cell.fair[row] = got.risk_k / (got.risk_k + reward)
                    cell.cost[row] = trip / sig.risk if costed else np.nan
    return cells


def merge(into: dict[tuple, Cell], got: dict[tuple, Cell], key: tuple) -> None:
    """Fold one dict of cells into another under a longer key.

    Every field, taken from `dataclasses.fields`, so a column added later is
    carried on the day it is added rather than dropped silently.
    """
    for inner, cell in got.items():
        full = key + tuple(inner)
        held = into.get(full)
        if held is None:
            # **Copied, not aliased.** The caller keeps some of these cells for
            # a per-instrument table, and inserting the object itself meant the
            # first symbol's row grew every later symbol into it - a per-symbol
            # number that silently became a running pool.
            into[full] = Cell(**{name: getattr(cell, name).copy() for name in _fields()})
            continue
        for name in _fields():
            setattr(held, name, np.concatenate((getattr(held, name), getattr(cell, name))))


#: Sub-steps a bar's path is built from in `walk_path`, and the rows built at a
#: time. 120 sub-steps of a 15-minute bar is about seven seconds.
#:
#: **This is a calibration parameter, not a detail.** A bar-level stop that
#: fills *at* the stop credits the trade with however far the path overshot it,
#: and on a discretely sampled path that overshoot is about half a sub-step. At
#: 15 sub-steps the arm that must read zero read **+0.1329R**; the sweep in the
#: write-up is `ET_SUBSTEPS` against that number, and it is the reason the
#: study's statistic is the **paired** difference from k=0, where a bias common
#: to both arms cancels, rather than the level.
SUBSTEPS = int(os.environ.get("ET_SUBSTEPS") or 120)
CHUNK = int(os.environ.get("ET_CHUNK") or 20_000)

#: Take the mean out of the resampled steps, so "driftless" is true. Off is
#: kept only to reproduce the number that found it - see `walk_path`.
DEMEAN = bool(int(os.environ.get("ET_DEMEAN") or 1))

#: A multiple on the rule's own stop distance. 1.0 is the rule; the grid is
#: the handle on the settlement bias. See `signals_for`.
STOPMULT = float(os.environ.get("ET_STOPMULT") or 1.0)


def walk_path(series: Series, rng: random.Random, sub: int = SUBSTEPS) -> Series:
    """A driftless walk whose high and low are the path's **own** extremes.

    **The only one of these arms that is a valid null for a barrier test**, and
    it exists because the other three are not. `walk_with_bar_geometry`,
    `bar_shuffle` and `garch_bars` all build a bar by drawing a close from a
    walk and then a *shape* resampled independently of that walk, so the bar's
    high and low are a fabricated envelope rather than the running extremes of
    the path the closes trace. A stop read off such a low fires without the
    price path ever having gone there, while the mark at the clock is read off
    the close path as if nothing had happened - so the race is not a martingale
    even though the closes are. Measured at k=0 on the clock outcome, where
    optional stopping requires exactly zero, with **random anchors so the
    detector cannot be the cause**: `-0.1985R` on walk-geometry bars against
    **`+0.0003R` on real bars**.

    So this arm simulates each bar as a Brownian bridge of `sub` sub-steps
    pinned to a close-to-close step drawn from the real series' own steps. The
    one-bar step distribution is the real one exactly, the open is the previous
    close exactly, the high and low are the path's extremes, and the race is a
    martingale race up to the discreteness of the path - which is what `sub`
    controls and what the write-up sweeps.

    What this arm does **not** carry is this market's wickiness: a bridge's
    range is the range Brownian motion gives, and markets are wickier
    (`how-markets-differ-from-every-simple-process`). That is why
    `walk-geometry` is kept for the questions that need wickiness and this one
    for the question of whether a race pays.
    """
    steps = np.diff(series.close)
    if len(steps) < 2 or sub < 2:
        return series
    if DEMEAN:
        # **Resampling real steps keeps the real drift**, and a surrogate that
        # is called driftless and is not makes a barrier race pay. Measured
        # with random anchors on eight 11-year 15-minute series, where optional
        # stopping requires zero: `+0.1219R` at 240 sub-steps a bar with the
        # mean left in, and it did not shrink as the path was refined - 0.1864,
        # 0.1686, 0.1077, 0.1164, 0.1219 at 15, 30, 60, 120 and 240 - so it was
        # never the stop's overshoot. Gold's own step mean over this span is
        # about +0.01 price units a bar against a 15-minute ATR of a few, which
        # is a fifth of an R of drift inside one 96-bar hold.
        #
        # `node/surrogates.walk_with_bar_geometry`, `level_shield.bar_shuffle`
        # and `level_shield.garch_bars` all resample or permute real steps and
        # none of them removes the mean, so the same applies to every arm in
        # this file that is not this one.
        steps = steps - steps.mean()
    sigma = float(np.std(steps)) or 1e-12
    n = len(series.close)
    draws = np.asarray(rng.choices(steps.tolist(), k=n), dtype=float)
    base = series.close[0] + np.concatenate(([0.0], np.cumsum(draws)[:-1]))
    weights = np.arange(1, sub + 1, dtype=float) / sub
    gen = np.random.default_rng(rng.randrange(1 << 30))
    low = np.empty(n)
    high = np.empty(n)
    # In row blocks: a full `n x sub` path at 120 sub-steps of 294,000 bars is
    # 280MB an array and this runs twelve to a box.
    for start in range(0, n, CHUNK):
        stop = min(start + CHUNK, n)
        walk = np.cumsum(gen.normal(0.0, sigma / math.sqrt(sub), size=(stop - start, sub)), axis=1)
        step = draws[start:stop]
        bridge = walk - np.outer(walk[:, -1], weights) + np.outer(step, weights)
        path = base[start:stop, None] + bridge
        low[start:stop] = np.minimum(base[start:stop], path.min(axis=1))
        high[start:stop] = np.maximum(base[start:stop], path.max(axis=1))
    return Series(
        feed=series.feed,
        venue=series.venue,
        interval=series.interval,
        ts=series.ts,
        open=base,
        high=high,
        low=low,
        close=base + draws,
    )


def surrogate_of(series: Series, name: str, rng: random.Random) -> Series:
    if name == "walk-path":
        return walk_path(series, rng)
    if name == "walk-geometry":
        return walk_geometry(series, rng)
    if name == "bar-shuffle":
        return bar_shuffle(series, rng)
    if name == "garch-bars":
        return garch_bars(series, rng)
    raise ValueError(f"{name!r} is not a surrogate arm")


def one_series(job: tuple[str, str, Series, float, float, tuple[str, ...]]) -> dict[tuple, Cell]:
    """One series' real, placebo and surrogate cells. The unit of work."""
    population, interval, series, spread_px, trip, surrogates = job
    kind = SYNTHETIC.get(series.feed, "real")
    out: dict[tuple, Cell] = {}
    signals = signals_for(population, series, spread_px)
    if not signals:
        return out
    hold = HOLD[population]
    rng = random.Random(f"{series.name}|{population}")
    merge(
        out,
        run_series(series, signals, hold=hold, trip=trip, rng=rng),
        (population, interval, "real", kind, series.feed),
    )
    unit = units(series, UNIT_SPAN.get(interval, 48))
    fakes = placebo_signals(series, signals, unit, hold, rng)
    if fakes:
        merge(
            out,
            run_series(series, fakes, hold=hold, trip=trip, rng=rng, outcomes=_HEADLINE),
            (population, interval, "placebo", kind, series.feed),
        )
    for name in surrogates:
        for draw in range(SURROGATES):
            twin = surrogate_of(series, name, random.Random(f"{series.name}|{name}|{draw}"))
            twins = signals_for(population, twin, spread_px)
            if not twins:
                continue
            merge(
                out,
                run_series(twin, twins, hold=hold, trip=trip, rng=rng, outcomes=_HEADLINE),
                (population, interval, name, kind, series.feed),
            )
            # **The placebo on the synthetic bars too.** Real bars with random
            # anchors read +0.0003 where the same rule on walk-geometry bars
            # read -0.1793, and that pair is what said the bias was in the bars
            # rather than in the detector. Keeping both arms means the next
            # reader does not have to re-derive it.
            twin_unit = units(twin, UNIT_SPAN.get(interval, 48))
            twin_fakes = placebo_signals(twin, twins, twin_unit, hold, rng)
            if twin_fakes:
                merge(
                    out,
                    run_series(
                        twin, twin_fakes, hold=hold, trip=trip, rng=rng, outcomes=_HEADLINE
                    ),
                    (population, interval, f"{name}-placebo", kind, series.feed),
                )
    print(
        f"  {series.feed:<22}{series.interval:>4}{len(series.close):>9,} bars "
        f"{_date(series.ts[0])} -> {_date(series.ts[-1])}  {len(signals):>6,} signals, "
        f"{len(fakes):>7,} placebo, trip {trip:.6g}",
        flush=True,
    )
    return out


def _date(stamp: float) -> str:
    """A UTC date, so `n` can be read as a claim about the world.

    `slope_fade.py` reported momentum surviving costs on seven cells at `t` up
    to +4.1, and the tell was that `n = 3159` at a five-bar stride needs 15,800
    daily bars - which the file supplied by starting in 1971, twenty-eight
    years before the instrument existed.
    """
    return dt.datetime.fromtimestamp(float(stamp), tz=dt.UTC).date().isoformat()


def jobs_for(population: str, interval: str, surrogates: tuple[str, ...]) -> list[tuple]:
    loader = db_series if interval == "1d" else seqlab_series
    out = []
    for series in loader(interval):
        if population == "impulse" and (interval != "15m" or series.feed.lower() not in VI.HAR):
            continue
        recorded = db_spread_px(series.feed, series.venue) if interval == "1d" else 0.0
        trip = recorded if recorded > 0.0 else cache_spread_px(series.feed)
        # The `N20` leg needs a spread in price. The store's own median where
        # there is one, else the terminal's live quote, else zero - and zero
        # means the ATR leg binds, which `smc-bos-reconcile.md` measured as
        # what already happens on gold, spx500 and us100.
        floor = 0.0 if FLOOR == "atr" else (trip if math.isfinite(trip) else 0.0)
        out.append((population, interval, series, floor, trip, surrogates))
    return out


# ────────────────────────────────── statistics ──────────────────────────────────


def block_ci(values: np.ndarray, days: np.ndarray, draws: int = DRAWS, seed: int = SEED):
    """A day-block bootstrap of the mean, and a two-sided p against zero.

    Whole days, because trades cluster in days and an ordinary standard error
    is far too narrow: a 96-bar hold at 15m overlaps by construction and
    `block bootstrap when the rows are not independent` is the standing rule.
    """
    if not len(values):
        return float("nan"), float("nan"), float("nan"), float("nan")
    order = np.argsort(days, kind="stable")
    values, days = values[order], days[order]
    edges = np.searchsorted(days, np.unique(days))
    blocks = np.split(values, edges[1:])
    sums = np.array([b.sum() for b in blocks])
    sizes = np.array([len(b) for b in blocks])
    rng = np.random.default_rng(seed)
    picks = rng.integers(0, len(blocks), size=(draws, len(blocks)))
    totals = sums[picks].sum(axis=1)
    counts = sizes[picks].sum(axis=1)
    means = np.where(counts > 0, totals / np.maximum(counts, 1), np.nan)
    mean = float(values.mean())
    if not np.isfinite(means).any():
        return mean, float("nan"), float("nan"), float("nan")
    lo, hi = (float(x) for x in np.nanpercentile(means, [2.5, 97.5]))
    centred = means - np.nanmean(means)
    return mean, lo, hi, float(np.mean(np.abs(centred) >= abs(mean)))


def bh(pvalues: dict[str, float], alpha: float = 0.05) -> dict[str, bool]:
    """Benjamini-Hochberg. Picking the best of many cells gives a winner every
    time: on this desk 18 of 43 nominally profitable instruments survived as
    none, while five survived as losers."""
    live = {k: v for k, v in pvalues.items() if math.isfinite(v)}
    if not live:
        return {}
    ordered = sorted(live.items(), key=lambda kv: kv[1])
    m = len(ordered)
    cut = 0
    for rank, (_key, p) in enumerate(ordered, start=1):
        if p <= alpha * rank / m:
            cut = rank
    return {key: rank <= cut for rank, (key, _p) in enumerate(ordered, start=1)}


def summarise(cell: Cell, base: Cell | None = None) -> dict[str, float]:
    """One cell's statistics, and its **paired** difference from the baseline.

    The paired difference is the statistic that answers the question. Every
    arm is run over the same signals in the same order, so `r0 - base.r0` is a
    per-signal difference and its day-block interval is far tighter than the
    difference of two independent means - which matters, because the delay's
    effect is a few hundredths of an R against a per-trade sd above 1.

    `base` is the k=0 arm of the same source, geometry and outcome. A length
    mismatch returns `nan` rather than pairing two different populations: one
    series with no placebo anchors would otherwise shift every later block by
    its own length and the difference would silently be between two different
    sets of trades.
    """
    r0 = cell.r0
    days = cell.day
    filled = cell.filled
    decided = cell.decided
    won = cell.won
    fair = cell.fair.astype(float)
    cost = cell.cost.astype(float)
    delay = cell.delay.astype(float)
    touched = cell.touched
    mean, lo, hi, p = block_ci(r0, days)
    priced = filled.any() and bool(np.all(np.isfinite(cost[filled])))
    if priced:
        net_mean, net_lo, net_hi, _ = block_ci(r0 - np.where(filled, cost, 0.0), days)
    else:
        # **Not zero.** An unpriced cell charged nothing would read as a free
        # round trip, and a free round trip passes every cost gate there is.
        net_mean = net_lo = net_hi = float("nan")
    live = decided & filled
    return {
        "n": float(len(r0)),
        "fill": float(filled.mean()) if len(filled) else float("nan"),
        "mean_r0": mean,
        # **A median beside every mean.** On this desk a mean R of +3.35 sat
        # beside a median of -0.27, carried by one row at 2390.
        "med_r0": float(np.median(r0)) if len(r0) else float("nan"),
        # In units of the trade's **own** risk rather than the k=0 risk, which
        # is the denominator the cost gate and the sizer use.
        "mean_rk": float(cell.rk[filled].mean()) if filled.any() else float("nan"),
        "lo": lo,
        "hi": hi,
        "p": p,
        "net_r0": net_mean,
        "net_lo": net_lo,
        "net_hi": net_hi,
        "hit": float(won[live].mean()) if live.any() else float("nan"),
        "fair": float(np.nanmean(fair[live])) if live.any() else float("nan"),
        "decided": float(decided[filled].mean()) if filled.any() else float("nan"),
        "cost_r": _nanmean(cost[filled]),
        "touch": float(touched[filled].mean()) if filled.any() else float("nan"),
        "delay": float(delay[filled].mean()) if filled.any() else float("nan"),
        "sd": float(r0.std(ddof=1)) if len(r0) > 1 else float("nan"),
        **_paired(cell, base),
    }


def _nanmean(values: np.ndarray) -> float:
    """A mean that treats "nothing to average" as `nan` rather than a warning.

    An unpriced cell is the normal case on the crosses the terminal does not
    carry, and `np.nanmean` of an empty slice is a `RuntimeWarning` plus a
    `nan` - the right answer with a hundred lines of noise around it.
    """
    live = values[np.isfinite(values)]
    return float(live.mean()) if live.size else float("nan")


def _paired(cell: Cell, base: Cell | None) -> dict[str, float]:
    """`mean(arm - k0)` per signal, with a day-block interval."""
    if base is None or len(base) != len(cell) or not len(cell):
        return {"diff": float("nan"), "dlo": float("nan"), "dhi": float("nan"), "dp": float("nan")}
    mean, lo, hi, p = block_ci(cell.r0 - base.r0, cell.day)
    return {"diff": mean, "dlo": lo, "dhi": hi, "dp": p}


def pooled(cells: dict[tuple, Cell], *, kinds: tuple[str, ...] = ("real",)) -> dict[tuple, Cell]:
    """Pool over symbols, keeping everything else."""
    out: dict[tuple, Cell] = {}
    for key, cell in cells.items():
        population, interval, source, kind, _symbol, arm, geometry, outcome = key
        if kind not in kinds:
            continue
        merge(out, {(arm, geometry, outcome): cell}, (population, interval, source, kind))
    return out


def show(title: str, rows: list[tuple[str, dict[str, float]]]) -> None:
    order = {name: i for i, name in enumerate(arm_names())}
    rows = sorted(rows, key=lambda kv: order.get(kv[0], 99))
    print(f"\n### {title}")
    head = (
        f"  {'arm':<5}{'n':>7}{'fill':>6}{'wait':>6}{'mean R0':>9}{'med':>8}{'95% lo':>9}"
        f"{'95% hi':>9}{'vs k0':>9}{'d lo':>9}{'d hi':>9}{'d p':>6}{'net R0':>9}"
        f"{'hit':>6}{'fair':>6}{'dec':>5}{'cost':>6}{'touch':>6}"
    )
    print(head)
    print("  " + "-" * (len(head) - 2))
    for label, s in rows:
        print(
            f"  {label:<5}{s['n']:>7.0f}{s['fill']:>6.3f}{s['delay']:>6.2f}"
            f"{s['mean_r0']:>9.4f}{s['med_r0']:>8.3f}{s['lo']:>9.4f}{s['hi']:>9.4f}"
            f"{s['diff']:>9.4f}{s['dlo']:>9.4f}{s['dhi']:>9.4f}{s['dp']:>6.3f}"
            f"{s['net_r0']:>9.4f}{s['hit']:>6.3f}{s['fair']:>6.3f}"
            f"{s['decided']:>5.2f}{s['cost_r']:>6.3f}{s['touch']:>6.3f}"
        )


def table(cells: dict[tuple, Cell], *, geometry: str, outcome: str) -> list[tuple[str, dict]]:
    """One (geometry, outcome) across every arm, each paired against its k0."""
    want = [k for k in cells if k[5] == geometry and k[6] == outcome and len(cells[k])]
    bases = {k[:4]: cells[k] for k in want if k[4] == "k0"}
    return [(k[4], summarise(cells[k], bases.get(k[:4]))) for k in want]


def write_csv(path: Path, cells: dict[tuple, Cell]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    bases = {(*k[:5], *k[6:]): v for k, v in cells.items() if k[5] == "k0"}
    with path.open("w") as handle:
        handle.write(",".join(COLUMNS + tuple(STATS)) + "\n")
        for key, cell in sorted(cells.items(), key=lambda kv: str(kv[0])):
            s = summarise(cell, bases.get((*key[:5], *key[6:])))
            handle.write(
                ",".join(str(x) for x in key) + "," + ",".join(f"{s[k]:.6g}" for k in STATS) + "\n"
            )
    print(f"\nwrote {path}")


# ───────────────────────────────── the power arm ─────────────────────────────────


def plant(series: Series, signals: list[Signal], strength: float, confirm_at: int) -> Series:
    """Plant the hypothesis: continuation **after** a confirmation, nowhere else.

    For each signal, the `hold` bars after `i + confirm_at` carry an extra
    drift of `strength` volatility units over the whole hold - **with the
    trade where the first `confirm_at` bars moved with it and against the trade
    where they did not**. So the market gains nothing on average and a
    confirmation carries real information about which signals continue, which
    is the one shape a delay could exploit and therefore the only honest thing
    to plant. `show-power-before-reporting-a-null` is why it is planted and
    swept rather than assumed.

    **Signed, and that is the correction that makes the sweep mean anything.**
    The first version planted continuation only on the confirmers, which the
    k=0 arm collects in full - it is in the trade for all 96 bars too - so
    every arm's reading rose together and the confirmation arm's paired
    difference stayed at +0.003 to +0.010 even at two whole volatility units of
    planted drift. A planted effect that the baseline captures is not a planted
    *selection* effect.

    **Stated as a total and not as a rate**, because the version before that
    took `strength` per bar over a 96-bar hold: 0.2 "units a bar" was 19 units
    of drift inside one trade, the stop became unreachable - 4% of trades
    decided anything - and the grid measured nothing but its own magnitude.

    Planted on a surrogate rather than on a real series, so the only structure
    present is the one being planted, and never before `i + confirm_at + 1`, so
    every signal's own side stays a function of untouched bars.
    """
    unit = units(series, UNIT_SPAN.get(series.interval, 48))
    shift = np.zeros(len(series.close))
    reach = max(HOLD.values())
    for sig in signals:
        j = sig.i + confirm_at
        if j + 1 >= len(series.close):
            continue
        confirmed = (float(series.close[j]) - float(series.close[sig.i])) * sig.side > 0.0
        step = (1.0 if confirmed else -1.0) * strength * float(unit[j]) * sig.side / reach
        end = min(j + 1 + reach, len(series.close))
        shift[j + 1 : end] += step * np.arange(1, end - j)
        shift[end:] += step * (end - j - 1)
    return Series(
        feed=series.feed,
        venue=series.venue,
        interval=series.interval,
        ts=series.ts,
        open=series.open + shift,
        high=series.high + shift,
        low=series.low + shift,
        close=series.close + shift,
    )


def replanted(series: Series, signals: list[Signal], floor: float) -> list[Signal]:
    """The same signal bars and sides, with the geometry re-read off `series`.

    **Needed because the plant moves the level the base signals named.** A
    planted window shifts every later bar permanently, so a signal's `level`
    taken from the unplanted twin sits an arbitrary distance from the planted
    close and `place` refuses it - measured as a **0.530 fill rate at k=0**,
    where the baseline arm cannot refuse anything. The bar index and the side
    stay the base ones, because the planted effect is keyed to them; the entry
    price and the stop distance are re-read at the same bar of the series being
    traded, which is causal because no earlier plant reaches a signal's own bar
    - the greedy spacing is wider than the planted reach.
    """
    atr_now = atr(series)
    out = []
    for sig in signals:
        risk = max(float(atr_now[sig.i]), SPREADS * max(floor, 0.0))
        if risk > 0.0:
            out.append(
                Signal(i=sig.i, side=sig.side, risk=risk, level=float(series.close[sig.i]))
            )
    return out


def one_planted(job: tuple[str, str, Series, float, int]) -> dict[tuple, Cell]:
    """One series' planted cell, on the arm that is a valid barrier null.

    `walk_path` and not `walk_geometry`: the point of the sweep is where the
    *test* goes blind, and an arm whose own random-anchor baseline sits at
    -0.2055R is measuring its own fabricated wicks as well.
    """
    population, interval, series, strength, confirm_at = job
    twin = walk_path(series, random.Random(f"{series.name}|power"))
    base = signals_for(population, twin, 0.0)
    if not base:
        return {}
    planted = plant(twin, base, strength, confirm_at) if strength else twin
    signals = replanted(planted, base, 0.0)
    if not signals:
        return {}
    out: dict[tuple, Cell] = {}
    merge(
        out,
        run_series(
            planted,
            signals,
            hold=HOLD[population],
            trip=float("nan"),
            rng=random.Random(f"{series.name}|power"),
        ),
        (population, interval, f"plant{strength:g}", "real", series.feed),
    )
    return out


def power(interval: str, population: str) -> dict[tuple, Cell]:
    grid = tuple(
        float(x)
        for x in (os.environ.get("ET_PLANT") or "0,0.05,0.1,0.25,0.5,1.0,2.0").split(",")
    )
    confirm_at = 2
    loader = db_series if interval == "1d" else seqlab_series
    series = [
        s
        for s in loader(interval)
        if SYNTHETIC.get(s.feed, "real") == "real"
        and (population == "bos" or s.feed.lower() in VI.HAR)
    ]
    print(
        f"\n## power: continuation worth `strength` volatility units over the whole "
        f"hold, planted after bar +{confirm_at}, **with** the trade where the first "
        f"{confirm_at} bars moved with it and against it where they did not, so the "
        f"market gains nothing on average. Brownian-bridge walks of "
        f"{len(series)} {interval} series, {population}\n"
    )
    everything: dict[tuple, Cell] = {}
    for strength in grid:
        jobs = [(population, interval, s, strength, confirm_at) for s in series]
        with Pool(min(WORKERS, max(1, len(jobs)))) as pool:
            for got in pool.imap_unordered(one_planted, jobs):
                for key, cell in got.items():
                    merge(everything, {key[5:]: cell}, key[:5])
        merged = pooled({k: v for k, v in everything.items() if k[2] == f"plant{strength:g}"})
        watch = ("k0", "k2", "c2", "r2", "c5")
        rows = [
            row
            for row in table(merged, geometry="anchored", outcome="clock")
            if row[0] in watch
        ]
        show(f"plant {strength:g} units/bar", rows)
    return everything


def one_calibration(job: tuple[str, str, Series, int]) -> dict[tuple, Cell]:
    population, interval, series, sub = job
    twin = walk_path(series, random.Random(f"{series.name}|calib|{sub}"), sub)
    signals = signals_for(population, twin, 0.0)
    if not signals:
        return {}
    unit = units(twin, UNIT_SPAN.get(interval, 48))
    rng = random.Random(f"{series.name}|calib|{sub}")
    fakes = placebo_signals(twin, signals, unit, HOLD[population], rng)
    if not fakes:
        return {}
    out: dict[tuple, Cell] = {}
    merge(
        out,
        run_series(
            twin, fakes, hold=HOLD[population], trip=float("nan"), rng=rng, outcomes=_HEADLINE
        ),
        (population, interval, f"sub{sub}", "real", series.feed),
    )
    return out


def calibrate(interval: str, population: str) -> dict[tuple, Cell]:
    """How much of `mean R0` is the stop's overshoot, as a function of the path.

    Random anchors on a Brownian-bridge walk, where optional stopping requires
    **exactly zero**. The only thing swept is how finely the bridge is sampled,
    so what the sweep traces is the bar-level settlement bias and nothing else.
    `show-power-before-reporting-a-null` applied to the harness rather than to
    the claim: a null is worth reporting with the size of its own measurement
    error attached.
    """
    grid = tuple(int(x) for x in (os.environ.get("ET_SUBGRID") or "15,30,60,120,240").split(","))
    loader = db_series if interval == "1d" else seqlab_series
    series = [
        s
        for s in loader(interval)
        if SYNTHETIC.get(s.feed, "real") == "real" and len(s.close) > 100_000
    ]
    print(
        f"\n## calibration: random anchors on a Brownian-bridge walk, {len(series)} "
        f"{interval} series, {population}. Every row must read zero.\n"
    )
    everything: dict[tuple, Cell] = {}
    for sub in grid:
        jobs = [(population, interval, s, sub) for s in series]
        with Pool(min(WORKERS, max(1, len(jobs)))) as pool:
            for got in pool.imap_unordered(one_calibration, jobs):
                for key, cell in got.items():
                    merge(everything, {key[5:]: cell}, (*key[:4], "POOLED"))
        merged = pooled({k: v for k, v in everything.items() if k[2] == f"sub{sub}"})
        rows = [
            row
            for row in table(merged, geometry="anchored", outcome="clock")
            if row[0] in ("k0", "k1", "k3", "k5", "c3")
        ]
        show(f"{sub} sub-steps a bar", rows)
    return everything


# ──────────────────────────────────── main ────────────────────────────────────


def main() -> int:
    mode = (os.environ.get("MODE") or "main").strip().lower()
    intervals = tuple(
        x.strip() for x in (os.environ.get("ET_INTERVALS") or "15m,1h,1d").split(",") if x.strip()
    )
    populations = tuple(
        x.strip()
        for x in (os.environ.get("ET_POPULATIONS") or "bos,impulse").split(",")
        if x.strip()
    )
    if mode == "power":
        write_csv(OUT / "cells-power.csv", power(intervals[0], populations[0]))
        return 0
    if mode == "calib":
        write_csv(OUT / "cells-calib.csv", calibrate(intervals[0], populations[0]))
        return 0
    surrogates = ("walk-path", "walk-geometry") if mode == "leak" else SURROGATE_ARMS
    print(
        f"entry timing: lags {LAGS}, targets {TARGETS}, holds {HOLD}, reach {REACH_BARS}, "
        f"squeeze {SQUEEZE}, refusal {REFUSAL}, placebo x{PLACEBO}, surrogates "
        f"{surrogates} x{SURROGATES}, {DRAWS} day-block draws, {WORKERS} workers"
    )
    everything: dict[tuple, Cell] = {}
    for population in populations:
        for interval in intervals:
            if population == "impulse" and interval != "15m":
                continue
            jobs = jobs_for(population, interval, surrogates)
            print(f"\n## {population} at {interval}: {len(jobs)} series")
            if not jobs:
                continue
            cells: dict[tuple, Cell] = {}
            with Pool(min(WORKERS, len(jobs))) as pool:
                for got in pool.imap_unordered(one_series, jobs):
                    for key, cell in got.items():
                        # Pooled as it arrives, because holding every
                        # per-symbol cell for every outcome is gigabytes.
                        merge(cells, {key[5:]: cell}, (*key[:4], "POOLED"))
                        headline = key[6:] == ("anchored", "clock")
                        if key[2:4] == ("real", "real") and headline:
                            everything[key] = cell
            everything |= cells
            shown = ("real", "placebo", *surrogates, *(f"{a}-placebo" for a in surrogates))
            for source in shown:
                merged = pooled({k: v for k, v in cells.items() if k[2] == source})
                rows = table(merged, geometry="anchored", outcome="clock")
                if rows:
                    show(f"{population} {interval} {source}, anchored, clock", rows)
            # **Net is only readable where every instrument in the pool has a
            # price.** A pooled cell containing one unpriced symbol reports a
            # `nan` net, which is the right answer and an unreadable table, so
            # the priced subset is pooled on its own from the per-symbol cells.
            priced: dict[tuple, Cell] = {}
            for key, cell in everything.items():
                if key[:2] != (population, interval) or key[4] == "POOLED":
                    continue
                if cell.filled.any() and np.all(np.isfinite(cell.cost[cell.filled])):
                    merge(priced, {key[5:]: cell}, (*key[:4], "PRICED"))
            rows = table(pooled(priced), geometry="anchored", outcome="clock")
            if rows:
                show(f"{population} {interval} real and priced, anchored, clock", rows)

            merged = pooled({k: v for k, v in cells.items() if k[2] == "real"})
            for geometry, outcome in (
                ("anchored", MARK),
                ("shifted", "clock"),
                ("anchored", "tgt1"),
                ("anchored", "tgt2"),
                ("anchored", "tgt3"),
            ):
                rows = table(merged, geometry=geometry, outcome=outcome)
                if rows:
                    show(f"{population} {interval} real, {geometry}, {outcome}", rows)
            for kind in ("iid-sigma", "jumps", "steps"):
                merged = pooled(
                    {k: v for k, v in cells.items() if k[2] == "real"}, kinds=(kind,)
                )
                rows = table(merged, geometry="anchored", outcome="clock")
                if rows:
                    show(f"{population} {interval} {kind} control, anchored, clock", rows)
    if everything:
        write_csv(OUT / f"cells-{mode}.csv", everything)
        reals = {
            k: v
            for k, v in everything.items()
            if k[2] == "real"
            and k[3] == "real"
            and k[4] != "POOLED"
            and k[6] == "anchored"
            and k[7] == "clock"
        }
        bases = {(*k[:5], *k[6:]): v for k, v in reals.items() if k[5] == "k0"}
        pvalues = {
            str(k): summarise(v, bases.get((*k[:5], *k[6:])))["dp"]
            for k, v in reals.items()
            if len(v) >= 30 and k[5] != "k0"
        }
        survivors = [k for k, ok in bh(pvalues).items() if ok]
        print(
            f"\nBH over {len(pvalues)} real per-instrument delay cells at the headline "
            f"outcome, on the **paired** difference from k0: "
            f"{len(survivors)} survive q<0.05"
        )
        for key in sorted(survivors):
            print(f"  {key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
