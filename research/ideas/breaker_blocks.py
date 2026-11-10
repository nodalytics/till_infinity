"""The breaker block - an order block's polarity flip - measured as a trade.

    ./.secrets/lab.sh run research/ideas/breaker_blocks.py MODE=run
    ./.secrets/lab.sh run research/ideas/breaker_blocks.py MODE=power
    ./.secrets/lab.sh run research/ideas/breaker_blocks.py MODE=cost
    ./.secrets/lab.sh run research/ideas/breaker_blocks.py MODE=run ZONES=desk
    ./.secrets/lab.sh run research/ideas/breaker_blocks.py MODE=overlap
    ./.secrets/lab.sh run research/ideas/breaker_blocks.py MODE=gap
    MODE=smoke uv run python research/ideas/breaker_blocks.py     # seconds, generated bars

`MODE=run` writes `$OUT/trades.csv.gz` (one row per real trade per target),
`$OUT/cells.csv` (one summary row per cell, arm, target and series, the walk
arms included) and `$OUT/zones.csv` (firing rates). `breaker_report.py` turns
those into the tables in [`breaker-blocks.md`](../docs/breaker-blocks.md).
`MODE=power` writes `power.csv`, `MODE=cost` writes `cost.csv`.

**Why this runs at all.** [`order-block-zones.md`](../docs/order-block-zones.md)
refuted the fade *to* an order block (-0.259R at 1d) and
[`origin-zones.md`](../docs/origin-zones.md) found 0 of 3,697 cells with a
positive lower bound. Its one unsettled positive was the **flip** - +0.337R at
1d, +0.506R at 4h - which it could not settle because it had no mechanical
definition of "flipped". Two published scripts supply one, and this file
implements theirs rather than inventing a third:

* *Order Blocks & Breaker Blocks* (LuxAlgo): swing lookback 10; on a close
  through the last swing high the order block is the **lowest-low bar** between
  the swing and its break. The zone becomes a **breaker** when
  `min(close, open)` closes through its far edge, and is **deleted** when
  `close` clears its near edge.
* *Market Structure Break & Order Block* (EmreKb): the flip is **confirmed**
  when a fresh swing lands inside the broken zone's range.

Every rule below is one of those two, the desk's own stop pad, or a constant
this file states. `SWING`, `PAD`, `EXPIRE` and `HOLD` were fixed before the
first run; `SWEEP=1` runs the grid around them and the write-up reports all of
it rather than its best cell.

## The arms, and what each one is for

| arm | the trade | the property it carries |
|---|---|---|
| `flip` | **against** the zone's original direction, on a retest of the breaker | the claim |
| `flip_confirmed` | the same, delayed until a fresh swing lands in the band | EmreKb's confirmation, charged its `SWING` bars of delay |
| `fade` | **with** the original direction, on a retest before it flips | the refuted claim, kept in the run. If both beat the null the finding belongs to the old claim and this harness is wrong |
| `placebo` | the identical breaker trade at a **prior swing with no order block behind it**, distance-matched, one per real trade | geometry without an order block |

and five null series under every arm, each driven through the identical
detector on the identical clock: `iid` (Student-t(3) sub-steps, no clustering),
`garch` (GARCH(1,1)-t(5)), `shipped`
(`node/surrogates.walk_with_bar_geometry` as the package writes it),
`contopen` (the same walk with every bar opening at the previous close) and
`contdrift` (that, with the realised drift left in).

**Two geometry arms, and `shipped` is the one of record.** A geometry claim
needs this market's own wickiness rather than a generated process -
`how-markets-differ-from-every-simple-process`. But a **resting-limit** arm is
sensitive to how a surrogate assembles the inside of a bar, and the two
assemblies differ on this trade by **0.171R**. `contopen` exists to measure that
sensitivity and is **not** a proposed fix to the package: the market carries the
same open-gap sawtooth the shipped arm does, which
`walk_with_bar_geometry`'s docstring records and a test pins. So both are
reported and the verdict rests on the statistics that need no surrogate at all:
the arithmetic rate, the placebo arm (which runs on the **real** bars through
the identical construction, so the harness's intrabar assumption cancels), the
per-cell counts and the sweep. See the write-up's section on why.

## The settlement, which is where this kind of study leaks

Entries are resting **limit** orders, and the fill bar is settled exactly as
`research/mt5bt/engine.walk` settles one:

* the stop counts on the fill bar - the bar cannot say whether its adverse
  extreme printed before the touch, so it is assumed to have;
* the target counts on the fill bar **only if the bar closes beyond it**, since
  a limit is filled from the far side;
* when both legs are reachable in one bar the **stop wins**, there being no
  ticks to break the tie.

All three are conservative, so a surrogate whose closes are a martingale
should read at or slightly **below** zero and slightly below `1/(1+N)`.
`MODE=power` prints that check first. One arm does not: the `shipped` geometry
surrogate pays the long-entry arm **+0.1241R**, and `MODE=gap` is where that is
run down. It is **not** a bug in that function - the market carries the same
sawtooth, negative on 28 of 28 of the broker's 1h FX stores at a mean of -0.0126
of a bar range, and the identity `close[i] - close[i-1] = (open[i] -
close[i-1]) + (close[i] - open[i])` forces it. It is a statement about what
bar data can settle: OHLC does not order the high and the low, so filling at a
limit inside a bar and marking the race from that bar is the harness choosing an
intrabar path, and an arm built that way moves with the choice. See
`a-martingale-cannot-pay` for the convention this still gets right, and the
price-action study for +0.2234R paid on a walk by the opposite convention.

**Every arm holds the same number of bars.** The prior study's `flip`,
`straight` and `coin` arms ran at `MAXHOLD = 300` while its `real` arm ran at
`HOLD_DAYS = 5` - five bars at 1d - so its headline compared the side, the
entry style *and* a sixty-fold holding period at once. One `HOLD` here, for
every arm.
"""

from __future__ import annotations

import csv
import gzip
import os
import sys
import zlib
from pathlib import Path

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

OUT = Path(os.environ.get("OUT", ".data/breaker"))
MODE = os.environ.get("MODE", "run")

#: Which order-block population the lifecycle is applied to.
#:
#: `lux` is LuxAlgo's construction, implemented in `order_blocks` below, and is
#: the pre-registered one: the published script is the thing the survey
#: shortlisted. `desk` calls `zones.ob_zones` unchanged - the detector
#: [`order-block-zones.md`](../docs/order-block-zones.md) built its +0.337R on -
#: and applies the **published flip lifecycle** to it, which is the mechanical
#: definition that study lacked and the reason this one exists.
#:
#: **They are not two versions of one object.** `MODE=overlap` measures their
#: agreement at a Jaccard of **0.0027** over 219,000 bars on eight instruments:
#: LuxAlgo cuts 20,133 blocks where the desk's rule cuts 1,316, and finds 4.4%
#: of them. `two-detectors-with-the-same-name-are-usually-two-detectors`, so
#: both populations are run and reported separately, and a null on one is not a
#: null on the other.
ZONES = os.environ.get("ZONES", "lux")

#: **Every parameter here is in bars, and that is the mapping between clocks.**
#: `SWING`, `EXPIRE`, `HOLD` and `ATR_N` are bar counts, so the same rule is ten
#: hours at 1h and ten days at 1d. That is deliberate - a Pine script's
#: `pivothigh(10, 10)` is a bar count and the published rule is what is being
#: measured - but it means the three clocks run **three different detectors over
#: three different horizons**, not one detector sampled three ways.
#: `a-bar-count-inside-a-time-portable-measurement` is the defect this note
#: exists to avoid: `volatility_ceiling.py` compared `har(5/22/110)` across 15m
#: and 1d and reported a result that vanished on conversion. Nothing here is
#: compared across clocks except by naming the horizon, and the per-clock tables
#: are reported separately for that reason.
#:
#: LuxAlgo's swing lookback. A pivot is known `SWING` bars after it prints.
SWING = int(os.environ.get("SWING", "10"))

#: The band: the order-block bar's whole range (LuxAlgo draws the box that way)
#: or its body. `zones.py` carries the same switch for the same reason - a
#: reader who draws wick to wick gets a different entry and a different stop.
BAND = os.environ.get("BAND", "range")

#: The stop pad beyond the zone's far edge, in ATR(14). 0.1 is what
#: `origin-zones.md` and `zones.py` use; 0.25 and 0.5 are in the sweep.
PAD = float(os.environ.get("PAD", "0.1"))

#: Bars a live zone waits for its retest. `zones.py`'s `EXPIRE`.
EXPIRE = int(os.environ.get("EXPIRE", "300"))

#: Bars a filled trade is held, **the same for every arm** - the asymmetry in
#: the prior study is the first thing this fixes. Sixty is this desk's own
#: barrier window (`CLAUDE.md`: "that is measured with no stop and 300 bars, and
#: the trade has a stop and sixty"); 30, 120 and 300 are in the sweep.
#:
#: A finite hold makes `1/(1+N)` an **upper bound** rather than the rate: a
#: trade that times out reached neither barrier. So `reach` is reported beside
#: `reach | resolved`, and it is the second that a walk must put on `1/(1+N)`.
HOLD = int(os.environ.get("HOLD", "60"))

#: Reward multiples. The headline is N = 2, which is the desk's own brief and
#: the multiple `(1 + cost) / 3` break-even arithmetic assumes.
TARGETS = tuple(float(x) for x in os.environ.get("TARGETS", "1,2,3,4").split(","))

#: A stop may not sit inside the spread (`run.to_mt5`'s rule, two round trips)
#: and may not be a whole regime wide.
MIN_STOP_TRIPS, MAX_STOP_ATR = 2.0, 15.0

#: Fewer bars than this and the cell is not reported. 1,200 is the floor
#: `lab-seqlab-is-much-bigger-than-seven` arrived at; below it a 20-bar swing
#: and a 300-bar expiry do not both fit.
MIN_BARS = int(os.environ.get("MIN_BARS", "1200"))

ATR_N = 14
SEC = {"1h": 3600, "4h": 14400, "1d": 86400}
INTERVALS = tuple(os.environ.get("INTERVALS", "1h,4h,1d").split(","))
WALKS = int(os.environ.get("WALKS", "3"))
HOME = Path(os.environ.get("BARS_HOME", Path.home() / "till_infinity" / "data"))

#: Instruments, by store, deepest first. `data/seqlab`'s 15m stores reach 2015
#: (294,000 bars) and `data/btc`'s reach 2024 (50,000), so the deep names carry
#: the daily clock and the wide ones widen the universe at 1h and 4h. Widening
#: 16 instruments to 29 killed the only positive cell of a sixty-cell sweep
#: once, which is why both sets run rather than the deep eight alone.
DEEP = ("EURUSD", "GBPUSD", "AUDUSD", "USDCAD", "USDJPY", "XAUUSD", "XAGUSD", "BTCUSD")
WIDE = ("US SP 500", "US Tech 100", "Wall Street 30", "Germany 40", "UK 100", "Japan 225",
        "Australia 200", "Europe 50", "France 40", "Hong Kong 50", "US Oil", "UK Brent Oil",
        "XPTUSD", "XCUUSD", "ETHUSD", "BNBUSD", "AUDCAD", "AUDNZD", "EURAUD", "EURCAD",
        "NZDUSD", "USDCHF")

#: Deriv's synthetics, which are **real markets with a published generator** -
#: `deriv-synthetics-are-real-markets`. The property they control for is named
#: and is narrow: no participant in them leaves unfilled interest, so there is
#: no order block to flip, while they do have levels (`Range Break` is the
#: level positive control) and a switching drift (`Drift Switch`). They are not
#: a tail control and they are never pooled with the traded book.
SYNTH = ("Boom 500 Index", "Boom 1000 Index", "Crash 500 Index", "Crash 1000 Index",
         "Drift Switch Index 10", "Drift Switch Index 20", "Drift Switch Index 30",
         "Range Break 100 Index", "Range Break 200 Index", "Step Index",
         "Volatility 25 Index", "Volatility 75 Index", "Jump 75 Index")

FAMILY = {
    **{s: "fx" for s in ("EURUSD", "GBPUSD", "AUDUSD", "USDCAD", "USDJPY", "AUDCAD", "AUDNZD",
                         "EURAUD", "EURCAD", "NZDUSD", "USDCHF")},
    **{s: "metal" for s in ("XAUUSD", "XAGUSD", "XPTUSD", "XCUUSD")},
    **{s: "crypto" for s in ("BTCUSD", "ETHUSD", "BNBUSD")},
    **{s: "index" for s in ("US SP 500", "US Tech 100", "Wall Street 30", "Germany 40", "UK 100",
                            "Japan 225", "Australia 200", "Europe 50", "France 40",
                            "Hong Kong 50")},
    **{s: "energy" for s in ("US Oil", "UK Brent Oil")},
    **{s: "deriv" for s in SYNTH},
}

ARM_NAMES = ("flip", "flip_confirmed", "fade", "placebo")


# ───────────────────────────────── bars ─────────────────────────────────


def sources() -> dict[str, Path]:
    """One 15m store per name, deepest first, so a name is never read at 50,000
    bars when 294,000 exist."""
    found: dict[str, Path] = {}
    for folder in (HOME / "seqlab", HOME / "btc", HOME / "syn"):
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.15m.npz")):
            found.setdefault(path.name[: -len(".15m.npz")], path)
    return found


def read(path: Path) -> tuple[dict[str, np.ndarray], int]:
    """One store's 15m bars, oldest first, de-duplicated by timestamp.

    **The de-duplication is unconditional and the drop is reported.** `spx500`
    and `us100` daily in the prices store were found duplicated on 2026-11-10 -
    6,005 rows over 3,006 timestamps, 503 bars a year on a daily series. These
    are different stores and were checked clean, but a duplicate bar doubles a
    detector's firing rate in silence, so the guard stays and `zones.csv`
    carries the count.
    """
    with np.load(path) as z:
        got = {k: z[k].astype(float) for k in ("open", "high", "low", "close")}
        got["ts"] = z["time"].astype(np.int64)
        got["spread"] = z["spread"].astype(float) if "spread" in z.files else np.zeros(len(z["time"]))
    order = np.argsort(got["ts"], kind="stable")
    got = {k: v[order] for k, v in got.items()}
    keep = np.r_[True, np.diff(got["ts"]) > 0]
    return {k: v[keep] for k, v in got.items()}, int((~keep).sum())


def fold(bars: dict[str, np.ndarray], sec: int) -> dict[str, np.ndarray]:
    """15m bars into `sec`-second bars by **timestamp bucket**, not by index.

    Index folding (`arange(n) // k`) walks across the weekend and puts Friday's
    close in the same bar as Monday's open; a timestamp bucket just yields fewer
    bars. The daily bar is therefore a **UTC day**, not the broker's 21:00 or
    22:00 session - a legitimate daily clock and not the same one, which is
    stated because the prior study's 1d bars were the broker's.
    """
    key = bars["ts"] // sec
    start = np.r_[0, np.flatnonzero(np.diff(key)) + 1]
    end = np.r_[start[1:], len(key)]
    return {
        "ts": key[start] * sec,
        "open": bars["open"][start],
        "high": np.maximum.reduceat(bars["high"], start),
        "low": np.minimum.reduceat(bars["low"], start),
        "close": bars["close"][end - 1],
        "spread": np.maximum.reduceat(bars["spread"], start),
    }


def atr(high, low, close, n: int = ATR_N) -> np.ndarray:
    """Wilder's ATR, as `prims.atr` computes it, `nan` before the warmup.

    True range is invariant under the mirror, so this is computed once per
    series and shared by both sides.
    """
    prev = np.r_[close[0], close[:-1]]
    tr = np.maximum(high, prev) - np.minimum(low, prev)
    out = np.full(len(tr), np.nan)
    if len(tr) <= n:
        return out
    acc = float(tr[1 : n + 1].mean())
    out[n] = acc
    for i in range(n + 1, len(tr)):
        acc += (tr[i] - acc) / n
        out[i] = acc
    return out


# ─────────────────────────────── the detector ───────────────────────────────


def pivot_flags(high, low, left: int, right: int) -> tuple[np.ndarray, np.ndarray]:
    """`prims.pivots`' definition, vectorised: strictly above the `left` bars
    before and at or above the `right` after, so a flat top reports once."""
    n = len(high)
    ph, pl = np.zeros(n, bool), np.zeros(n, bool)
    if n < left + right + 1:
        return ph, pl
    wh = sliding_window_view(high, left + right + 1)
    wl = sliding_window_view(low, left + right + 1)
    mid = slice(left, n - right)
    ph[mid] = (high[mid] > wh[:, :left].max(axis=1)) & (high[mid] >= wh[:, left + 1 :].max(axis=1))
    pl[mid] = (low[mid] < wl[:, :left].min(axis=1)) & (low[mid] <= wl[:, left + 1 :].min(axis=1))
    return ph, pl


def order_blocks(o, h, l, c, ph: np.ndarray, swing: int = SWING,
                 band: str = BAND) -> list[tuple[int, float, float, int]]:
    """LuxAlgo's bullish order blocks: `(ob_bar, btm, top, break_bar)`.

    Its state machine, unchanged. `top` is the last pivot high **known** at the
    bar (its bar plus `swing`); the block is cut on `ta.crossover(close, top)`
    and only once per swing (its `top_crossed` flag); the block itself is the
    lowest-low bar between the swing and the crossing bar.

    Long-side only on purpose: the short side is this function on a mirrored
    frame, which is the idiom `zones.py` uses and whose absence once cost that
    study its entire supply side.
    """
    bars = np.flatnonzero(ph)
    n, out, ptr = len(c), [], 0
    start, level, used = -1, np.nan, True
    for i in range(n):
        while ptr < len(bars) and bars[ptr] + swing <= i:
            start, level, used = int(bars[ptr]), float(h[bars[ptr]]), False
            ptr += 1
        if used or start < 0:
            continue
        if c[i] > level and (i == 0 or c[i - 1] <= level):
            p = start + int(np.argmin(l[start : i + 1]))
            btm = float(l[p])
            top = float(h[p]) if band == "range" else float(max(o[p], c[p]))
            if top > btm:
                out.append((p, btm, top, i))
            used = True
    return out


def desk_blocks(bars, o, h, l, c, unit) -> list[tuple[int, float, float, int]]:
    """`zones.ob_zones` called unchanged, in this file's `(p, btm, top, known)` shape.

    That detector's own defaults are this repo's corrected ones -
    `PUSH_BODY = 0.70`, `ORIGIN_BODY = 0.45`, `OB_BAND = range`, the imbalance
    required and the break strong - which are the values
    `order-block-zones.md`'s correction section reports. `known` is its `live`
    bar: the latest of the push completing, the strong break confirming and the
    gap forming, so nothing is used before it could be.
    """
    import pandas as pd

    import zones as Z  # noqa: N812 - that study's module name

    df = pd.DataFrame({"ts": bars["ts"], "open": o, "high": h, "low": l, "close": c,
                       "volume": 0.0})
    return [(z.p, float(z.lo), float(z.hi), int(z.live)) for z in Z.ob_zones(df, unit)
            if z.hi > z.lo and 0 <= z.live < len(c)]


def _first(mask: np.ndarray, offset: int) -> int:
    hit = np.flatnonzero(mask)
    return int(hit[0] + offset) if len(hit) else -1


def lifecycle(c, mn, piv_bars, piv_px, btm: float, top: float, known: int,
              swing: int = SWING) -> tuple[int, int, int]:
    """`(flip, dead, confirmed)` bar indices, -1 where it never happens.

    * **flip** - the first bar after `known` whose `min(close, open)` closes
      through the far edge (LuxAlgo's breaker condition).
    * **dead** - the first bar after the flip whose `close` clears the near
      edge, which for a flipped demand zone is its top.
    * **confirmed** - the first pivot after the flip whose price lands inside
      the broken band, returned at the bar it is *known*, so EmreKb's
      confirmation is charged its `swing` bars of delay rather than given them.
    """
    n = len(c)
    f = _first(mn[known + 1 :] < btm, known + 1)
    if f < 0:
        return -1, -1, -1
    d = _first(c[f + 1 :] > top, f + 1)
    end = d if d >= 0 else n - 1
    lo, hi = np.searchsorted(piv_bars, [f + 1, end + 1])
    conf = -1
    for k in range(int(lo), int(hi)):
        px = piv_px[k]
        if btm <= px <= top and piv_bars[k] + swing <= end:
            conf = int(piv_bars[k] + swing)
            break
    return f, d, conf


# ─────────────────────────────── the trades ───────────────────────────────


def fill_bar(h, l, side: int, level: float, lo: int, hi: int) -> int:
    """The first bar in `[lo, hi]` that touches a resting limit at `level`.

    A long limit sits below price and is touched by a low, a short one above it
    and by a high. `hi` **includes the bar that kills the zone**: cancelling on
    that bar's close would be using the close to withdraw an order the bar had
    already touched.
    """
    if hi < lo or lo < 0 or lo >= len(h):
        return -1
    seg = l[lo : hi + 1] <= level if side > 0 else h[lo : hi + 1] >= level
    return _first(seg, lo)


def settle(o, h, l, c, j: int, side: int, entry: float, stop_px: float, nn: float,
           hold: int, plant: float = 0.0) -> tuple[float, str, int]:
    """`(R, reason, bars_held)` for one trade from its fill bar `j` at an `nn`R target.

    The fill-bar conventions are `mt5bt.engine.walk`'s and the module docstring
    says why each is conservative. A gap through either barrier exits at the
    open, which is the only way a trade prints beyond its own target.

    `plant` adds a drift of `plant` R, spread over the holding window, to the
    forward path from the fill bar on. Nothing before the fill moves, so the
    detector and the fill are untouched and `plant` is exactly "the edge this
    trade would have to carry" - which is the currency the power curve is in.
    """
    n = len(c)
    last = min(n - 1, j + hold - 1)
    m = last + 1 - j
    stop_d = side * (entry - stop_px)
    target_px = entry + side * nn * stop_d
    lift = side * plant * stop_d * np.arange(m) / hold if plant else 0.0
    oo = o[j : last + 1] + lift
    hh = h[j : last + 1] + lift
    ll = l[j : last + 1] + lift
    cc = c[j : last + 1] + lift
    adverse, favour = (ll, hh) if side > 0 else (hh, ll)
    hit_s = side * (adverse - stop_px) <= 0
    hit_t = side * (favour - target_px) >= 0
    hit_t[0] = side * (cc[0] - target_px) >= 0  # a limit is filled from the far side
    gap_s = np.zeros(m, bool)
    gap_t = np.zeros(m, bool)
    if m > 1:
        gap_s[1:] = side * (oo[1:] - stop_px) <= 0
        gap_t[1:] = side * (oo[1:] - target_px) >= 0
    where = np.flatnonzero(hit_s | hit_t | gap_s | gap_t)
    if not len(where):
        return float(side * (cc[-1] - entry) / stop_d), "time", m - 1
    k = int(where[0])
    if gap_s[k]:
        px, why = oo[k], "stop_gap"
    elif gap_t[k]:
        px, why = oo[k], "target_gap"
    elif hit_s[k]:
        px, why = stop_px, "stop"
    else:
        px, why = target_px, "target"
    return float(side * (px - entry) / stop_d), why, k


def zones_and_trades(bars: dict[str, np.ndarray], unit: np.ndarray, mirror: bool, trip: float,
                     pad: float = PAD, band: str = BAND, expire: int = EXPIRE, hold: int = HOLD,
                     swing: int = SWING, targets=TARGETS,
                     rng: np.random.Generator | None = None,
                     plant: float = 0.0) -> tuple[list[dict], dict]:
    """Every arm's trades on one frame. `mirror` runs the short side.

    A mirrored frame is prices negated with high and low swapped, so every
    predicate stays long-logic and the two sides cannot drift apart. R is
    scale-free and the cost is symmetric, so nothing has to be un-negated
    except the side that is reported.
    """
    if mirror:
        o, h, l, c = -bars["open"], -bars["low"], -bars["high"], -bars["close"]
    else:
        o, h, l, c = bars["open"], bars["high"], bars["low"], bars["close"]
    n = len(c)
    rng = rng or np.random.default_rng(0)
    ph, pl = pivot_flags(h, l, swing, swing)
    mn = np.minimum(c, o)
    piv_bars = np.flatnonzero(ph | pl)
    piv_px = np.where(ph[piv_bars], h[piv_bars], l[piv_bars])

    zs = (order_blocks(o, h, l, c, ph, swing=swing, band=band) if ZONES == "lux"
          else desk_blocks(bars, o, h, l, c, unit))
    ob_bars = {p for p, _b, _t, _k in zs}
    rows: list[dict] = []
    tally = dict.fromkeys(("zones", "flipped", "deleted", "confirmed", "placebo_pool",
                           "wrong_side"), 0)
    tally["zones"] = len(zs)
    side_out = -1 if mirror else 1
    dropped = [0]

    def emit(arm: str, side: int, lo: int, hi: int, entry: float, far: float, anchor: int,
             ref: int, height_u: float, wait: int) -> None:
        u = unit[ref] if 0 <= ref < n else np.nan
        if not np.isfinite(u) or u <= 0:
            return
        # **A resting limit sits on the far side of the market.** At the bar
        # the order is placed the entry level must be beyond the close -
        # otherwise price is already there, the "retest" has happened, and the
        # fill-bar convention that a limit is filled from the far side is
        # false. LuxAlgo's breaker condition is `min(close, open) < btm`, which
        # an up-closing bar can satisfy through its open alone, so this drops
        # trades rather than being vacuous; the count is in `zones.csv`.
        # Correctly placed means `side * (close - entry) > 0`: a long limit
        # below the market, a short limit above it.
        if lo - 1 >= 0 and side * (c[lo - 1] - entry) <= 0:
            dropped[0] += 1
            return
        j = fill_bar(h, l, side, entry, lo, hi)
        if j < 0 or j >= n - 1:
            return
        stop_px = far - side * pad * u
        stop_d = side * (entry - stop_px)
        if not (stop_d > 0) or stop_d > MAX_STOP_ATR * u or stop_d < MIN_STOP_TRIPS * trip:
            return
        for nn in targets:
            r, why, held = settle(o, h, l, c, j, side, entry, stop_px, nn, hold, plant)
            rows.append({
                "arm": arm, "side": side * side_out, "target": nn, "R_gross": r,
                "reach": int(why in ("target", "target_gap")), "reason": why, "bars": held,
                "resolved": int(why != "time"), "stop_d": stop_d, "unit": float(u),
                "cost_r": (trip / stop_d) if trip else 0.0, "height_u": height_u, "wait": wait,
                "anchor": anchor, "fill": j, "exit": j + held, "ts": int(bars["ts"][j]),
            })

    for p, btm, top, brk in zs:
        f, d, conf = lifecycle(c, mn, piv_bars, piv_px, btm, top, brk, swing)
        u = unit[brk]
        height_u = float((top - btm) / u) if np.isfinite(u) and u > 0 else float("nan")
        end = f if f >= 0 else n - 1
        # the refuted arm: the zone traded with its original polarity, alive
        # from the break until the flip that ends it
        emit("fade", +1, brk + 1, min(end, brk + expire, n - 1), top, btm, p, brk, height_u, 0)
        if f < 0:
            continue
        tally["flipped"] += 1
        tally["deleted"] += int(d >= 0)
        dead = d if d >= 0 else n - 1
        emit("flip", -1, f + 1, min(dead, f + expire, n - 1), btm, top, p, f, height_u, f - brk)
        if conf >= 0:
            tally["confirmed"] += 1
            emit("flip_confirmed", -1, conf + 1, min(dead, f + expire, n - 1), btm, top, p, f,
                 height_u, f - brk)

    # ── the placebo: the same breaker trade where no order block was cut ──
    pool = []
    for q in np.flatnonzero(pl):
        q = int(q)
        if q in ob_bars or q + swing >= n - 2:
            continue
        lo_, hi_ = float(l[q]), float(h[q])
        if hi_ <= lo_:
            continue
        f, d, _conf = lifecycle(c, mn, piv_bars, piv_px, lo_, hi_, q + swing, swing)
        if f < 0 or not np.isfinite(unit[f]) or unit[f] <= 0:
            continue
        pool.append((q, lo_, hi_, f, d, (hi_ - lo_) / unit[f], f - (q + swing)))
    tally["placebo_pool"] = len(pool)
    real = [r for r in rows if r["arm"] == "flip" and r["target"] == targets[0]]
    for q, lo_, hi_, f, d, height_u, wait in match(real, pool, rng):
        dead = d if d >= 0 else n - 1
        emit("placebo", -1, f + 1, min(dead, f + expire, n - 1), lo_, hi_, q, f, height_u, wait)
    tally["wrong_side"] = dropped[0]
    return rows, tally


def match(real: list[dict], pool: list[tuple], rng: np.random.Generator) -> list[tuple]:
    """One placebo per real breaker trade, nearest on zone height and staleness.

    Distance-matched in the sense `surrogates.distance_matched` means: the
    placebo is **this geometry with no order block**, not a random anchor. Both
    coordinates are standardised logs - the zone height in volatility units
    sets the stop and therefore the whole barrier geometry, and the wait from
    the zone being known to its flip is how stale the level is. Drawn without
    replacement, so the arm also matches the **duty cycle**: equal n per cell is
    what makes the two standard errors comparable, and on a net-negative book an
    arm that trades less shows a profit improvement for no other reason.
    """
    if not real or not pool:
        return []
    pv = np.array([[p[5], p[6]] for p in pool], float)
    ok = np.isfinite(pv).all(axis=1) & (pv[:, 0] > 0)
    idx = np.flatnonzero(ok)
    if not len(idx):
        return []
    lp = np.log(np.c_[pv[idx, 0], pv[idx, 1] + 1.0])
    rv = np.array([[max(r["height_u"], 1e-9), max(r["wait"], 0)] for r in real], float)
    lr = np.log(np.c_[rv[:, 0], rv[:, 1] + 1.0])
    good = np.isfinite(lr).all(axis=1)
    lr = lr[good]
    scale = np.where(lp.std(axis=0) > 0, lp.std(axis=0), 1.0)
    taken = np.zeros(len(idx), bool)
    out = []
    for want in rng.permutation(len(lr)):
        dist = (((lp - lr[want]) / scale) ** 2).sum(axis=1)
        dist[taken] = np.inf
        k = int(np.argmin(dist))
        if not np.isfinite(dist[k]):
            break
        taken[k] = True
        out.append(pool[int(idx[k])])
    return out


# ───────────────────────────────── the nulls ─────────────────────────────────


def _bars_from_steps(steps: np.ndarray, price: float) -> dict[str, np.ndarray]:
    """`mt5bt.nulls._bars`: OHLC built forward from sub-steps, never bridged to
    a drawn close. A bridged path drifts predictably toward its own close and
    pays +0.07R a trade of free edge on a walk."""
    path = price + np.cumsum(steps.ravel()).reshape(steps.shape)
    o = np.r_[price, path[:-1, -1]]
    c = path[:, -1]
    return {"open": o, "high": np.maximum(path.max(axis=1), o),
            "low": np.minimum(path.min(axis=1), o), "close": c}


def _t(rng, dof, shape):
    return rng.standard_t(dof, shape) / np.sqrt(dof / (dof - 2))


#: Sub-steps a bar. `mt5bt/README` measured the bar-mode optimism this removes:
#: +0.09R a trade at 16 sub-steps of t(3), +0.03 at 64, none at 256. 64 is the
#: compromise this file runs at and the residual is visible in `MODE=power`'s
#: leak table, which is where it belongs.
SUB = int(os.environ.get("SUB", "64"))


def iid_bars(real: dict[str, np.ndarray], seed: int) -> dict[str, np.ndarray]:
    """Student-t(3) sub-steps at the real series' own close-to-close sd."""
    rng = np.random.default_rng(seed)
    n = len(real["close"])
    sd = float(np.std(np.diff(real["close"])))
    got = _bars_from_steps(_t(rng, 3.0, (n, SUB)) * sd / np.sqrt(SUB), float(real["close"][0]))
    return {**got, "ts": real["ts"], "spread": real["spread"]}


def garch_bars(real: dict[str, np.ndarray], seed: int, alpha: float = 0.06,
               beta: float = 0.92) -> dict[str, np.ndarray]:
    """GARCH(1,1) with t(5) sub-steps: volatility clusters, direction does not."""
    rng = np.random.default_rng(seed)
    n = len(real["close"])
    sd = float(np.std(np.diff(real["close"])))
    omega = sd**2 * (1 - alpha - beta)
    var = sd**2
    steps = _t(rng, 5.0, (n, SUB)) / np.sqrt(SUB)
    scale = np.empty(n)
    for i in range(n):
        scale[i] = np.sqrt(var)
        var = omega + alpha * (scale[i] * steps[i].sum()) ** 2 + beta * var
    got = _bars_from_steps(steps * scale[:, None], float(real["close"][0]))
    return {**got, "ts": real["ts"], "spread": real["spread"]}


def shipped_geom_bars(real: dict[str, np.ndarray], seed: int,
                      pyrng=None) -> dict[str, np.ndarray]:
    """`node/surrogates.walk_with_bar_geometry`, vectorised faithfully.

    The package's own construction and the null of record for a geometry claim:
    closes follow a walk on this market's resampled close-to-close steps, and
    each bar's `span` and its `(open_frac, close_frac)` pair are resampled from
    the real bars **with independent draws**, as `r.choice(spans)` and
    `r.choice(shapes)` do there. A first version of this function drew both with
    one index, which preserved a link the package breaks - so it was not the
    shipped arm it claimed to be, and the independent draws are the fix.

    **It is not demeaned, because the package does not demean**, and measured
    here demeaning moves nothing that matters: the `contdrift` arm reads within
    0.002R of `contopen` on every arm of this study.

    What this construction does to a bar's **open** is the thing to know before
    reading any limit-entry number off it. The open is placed inside that bar's
    own range rather than at the previous close, so `mean(open[i] - close[i-1])`
    is a by-product of the resampled marginals rather than a matched quantity.
    The identity `close[i] - close[i-1] = (open[i] - close[i-1]) +
    (close[i] - open[i])` means a series with near-nil close-to-close drift and
    bars that close above their opens **must** carry a negative mean gap - and
    the market does: `MODE=gap` reads it as negative on **28 of 28** of the
    broker's 1h FX stores, mean **-0.0126** of a bar range. So a sawtooth is not
    an artefact, this file does not call it one, and
    `walk_with_bar_geometry`'s own docstring and
    `test_the_walk_keeps_the_market_s_own_sawtooth_rather_than_removing_it` are
    where that is recorded and pinned.

    How closely the arm matches that gap depends on the clock. At the hourly FX
    cells it is the **same sign on 5 of 5** and within a factor of 0.46 to 4.43,
    under- as often as over-stating. The spread grows to 2.4-9.0x at 1d, and on
    the Deriv synthetics - whose own gap is about zero - it reaches **+0.1280**
    on Boom 1000 and **-0.1393** on Crash 1000. So it carries the phenomenon
    without matching its size, which is enough for a statistic that does not
    read the inside of a bar and not enough for one that does. See `MODE=gap`.
    """
    o, h, l, c = real["open"], real["high"], real["low"], real["close"]
    n = len(c)
    span = h - l
    good = span > 0
    denom = np.where(good, span, 1.0)
    of = np.where(good, (o - l) / denom, 0.5)
    cf = np.where(good, (c - l) / denom, 0.5)
    steps = np.diff(c)
    if pyrng is None:
        rng = np.random.default_rng(seed)
        drawn = steps[rng.integers(0, len(steps), n)]
        sp = span[rng.integers(0, n, n)]       # the package's `r.choice(spans)`
        shape = rng.integers(0, n, n)          # ... and its separate `r.choice(shapes)`
        drawn_of, drawn_cf = of[shape], cf[shape]
    else:
        # The same three draws in the package's own per-bar order, off a
        # `random.Random`, so `check_matches_package` can assert equality
        # instead of asserting a resemblance. Public API only: `choice` returns
        # a value, which is all the arithmetic below needs.
        steps_l, spans_l = steps.tolist(), span.tolist()
        shapes_l = list(zip(of.tolist(), cf.tolist(), strict=True))
        drawn, sp = np.empty(n), np.empty(n)
        drawn_of, drawn_cf = np.empty(n), np.empty(n)
        for i in range(n):
            drawn[i] = pyrng.choice(steps_l)
            sp[i] = pyrng.choice(spans_l)
            drawn_of[i], drawn_cf[i] = pyrng.choice(shapes_l)
    price = float(c[0]) + np.cumsum(drawn)
    low = price - drawn_cf * sp
    return {"ts": real["ts"], "spread": real["spread"], "low": low, "high": low + sp,
            "open": low + drawn_of * sp, "close": price}


def check_matches_package(bars: dict[str, np.ndarray], seed: int = 20261110,
                          tol: float = 1e-12) -> dict[str, float]:
    """Assert `shipped_geom_bars` **is** `walk_with_bar_geometry`, to `tol`.

    **A vectorised re-implementation of a production function is a second
    implementation**, and `two-definitions-of-one-concept` is the house defect:
    the only way to know the copy is the same function is to run the original
    beside it on real-shaped input and assert **equality**, not resemblance.

    This file shipped a copy that drew `span` and the shape pair with **one**
    index where the package draws them with two independent `r.choice` calls, so
    the arm labelled as the shipped one was not it - and the difference was worth
    **0.0229R** on the long-entry arm, which is the size of the evidence the
    whole first version of the write-up rested on. Nothing flagged it, because a
    surrogate that is wrong in a plausible way looks exactly like a surrogate:
    no count went to zero and no distribution collapsed.

    Returns the worst absolute deviation per OHLC field so a caller can print it.
    """
    import random

    from till_infinity.node.surrogates import walk_with_bar_geometry

    quad = list(zip(bars["open"].tolist(), bars["high"].tolist(), bars["low"].tolist(),
                    bars["close"].tolist(), strict=True))
    theirs = np.asarray(walk_with_bar_geometry(quad, rng=random.Random(seed)), float)
    mine = shipped_geom_bars(bars, seed, pyrng=random.Random(seed))
    worst = {}
    for k, col in (("open", 0), ("high", 1), ("low", 2), ("close", 3)):
        worst[k] = float(np.max(np.abs(mine[k] - theirs[:, col])))
        if worst[k] > tol:
            raise AssertionError(f"{k} differs from the package by {worst[k]:.3e} > {tol:.0e}")
    return worst


def contopen_bars(real: dict[str, np.ndarray], seed: int,
                  demean: bool = True) -> dict[str, np.ndarray]:
    """The same walk with every bar **opening at the previous close**.

    A second geometry arm, not a correction of the first. It exists because a
    resting-limit arm is sensitive to how a surrogate assembles the inside of a
    bar, and carrying two assemblies that differ in exactly that is the only
    honest way to show how much of a limit-entry reading is the assembly:
    through this harness the two differ by **0.171R** on the long-entry arm.

    What it keeps and what it loses, against `shipped_geom_bars`:

    * the series is **continuous**, so `mean(open[i] - close[i-1])` is exactly
      zero. The market's is about -0.003 to -0.011 of a range on FX and about
      zero on the 24/7 feeds and the synthetics, so this arm is **further** from
      the market on that quantity than the shipped one is wherever the market
      carries a gap. **It is not a fix and must not be read as one** - the
      package's docstring says why opening at the previous close would be a
      different series rather than a corrected one, and a test pins it. It is
      carried here only to size how much a limit-entry reading moves with the
      assembly, which is 0.171R;
    * a bar's **body is its own close-to-close step**, so the link between a
      bar's shape and its own move - which the shipped arm breaks - is exact;
    * the two **wicks** are this market's own absolute upper and lower wick
      lengths, resampled as a pair so their dependence travels, and attached
      outside the body. **Body-to-range is therefore not preserved as a
      marginal here**, where the shipped arm does preserve it (it is a function
      of the shape pair alone, and that pair travels). A detector that grades a
      bar by body share is mis-nulled by this arm and better served by the
      shipped one; one that reads a bar's move against its own shape is the
      reverse. Neither arm is right for both, which is why both are reported.

    `demean=False` keeps the series' realised drift and is the `contdrift` arm.
    """
    rng = np.random.default_rng(seed)
    o, h, l, c = real["open"], real["high"], real["low"], real["close"]
    n = len(c)
    upper = h - np.maximum(o, c)
    lower = np.minimum(o, c) - l
    steps = np.diff(c)
    if demean:
        steps = steps - steps.mean()
    draw = steps[rng.integers(0, len(steps), n)]
    close = float(c[0]) + np.cumsum(draw)
    open_ = np.r_[float(c[0]), close[:-1]]
    pick = rng.integers(0, n, n)
    hi = np.maximum(open_, close) + upper[pick]
    lo = np.minimum(open_, close) - lower[pick]
    return {"ts": real["ts"], "spread": real["spread"], "open": open_, "high": hi,
            "low": lo, "close": close}


def contdrift_bars(real: dict[str, np.ndarray], seed: int) -> dict[str, np.ndarray]:
    """`contopen_bars` with the series' own realised drift left in.

    **Not in `ARMS`**: it read within 0.002R of `contopen` on every arm of this
    study, so it measured the claim "the market's unconditional drift reaches
    none of these arms" once and has nothing left to add to a table. It stays
    callable because `path_bars` demeans for a reason `entry_timing` measured at
    +0.1219R, and a reader who doubts that should be able to run the undemeaned
    twin.
    """
    return contopen_bars(real, seed, demean=False)


def path_bars(real: dict[str, np.ndarray], seed: int) -> dict[str, np.ndarray]:
    '''A driftless walk whose open is the previous close and whose extremes are
    the path's own. **The only arm here that is a valid null for this trade.**

    Taken from `research/harness/entry_timing.walk_path`, which built it after
    hitting the same two defects from the other side; the construction is
    theirs and the reason both defects bite this study is that a breaker trade
    is a resting limit *and* a barrier race:

    * `shipped_geom_bars` places each bar's open inside that bar's own range,
      so it **gaps at every bar** - median `|gap|` 0.60-0.64 of a range against
      the market's 0.0000 - and a resting limit collects that gap. Here it paid
      the long-entry arm **+0.1012R**.
    * `contopen_bars` fixes the open and **is not sufficient**: its highs and
      lows are resampled independently of the close path, so a stop fires where
      the path never went while the mark is read off the close path as though
      nothing happened. `entry_timing` measured that second defect with random
      anchors - no detector to blame - at **-0.1985R** against **+0.0003R** on
      real bars.

    Each bar is a Brownian bridge of `SUB` sub-steps pinned to a close-to-close
    step drawn from the real series' own steps. So the one-bar step
    distribution is the real one exactly, the open is the previous close
    exactly, the high and low are the running extremes of the path those closes
    trace, and the race is a martingale race up to the discreteness `SUB`
    controls.

    **The steps are demeaned, and that is not cosmetic.** `entry_timing`
    measured a resampled-but-not-demeaned bridge paying **+0.1219R** with random
    anchors, and it did not shrink as the path was refined (0.1864, 0.1686,
    0.1077, 0.1164, 0.1219 at 15 to 240 sub-steps), so it was never the stop's
    overshoot.

    What this arm does **not** carry is this market's wickiness: a bridge's
    range is the range Brownian motion gives, and markets are wickier
    (`how-markets-differ-from-every-simple-process`). That is the trade: it is
    the right null for whether a race pays, and the wrong one for a claim about
    bar shape. Both are reported.
    '''
    rng = np.random.default_rng(seed)
    c = real["close"]
    n = len(c)
    steps = np.diff(c)
    if n < 3:
        return dict(real)
    steps = steps - steps.mean()
    sigma = float(np.std(steps)) or 1e-12
    draws = steps[rng.integers(0, len(steps), n)]
    base = float(c[0]) + np.r_[0.0, np.cumsum(draws)[:-1]]
    weights = np.arange(1, SUB + 1, dtype=float) / SUB
    low = np.empty(n)
    high = np.empty(n)
    chunk = 4096
    for start in range(0, n, chunk):
        stop = min(start + chunk, n)
        walk = np.cumsum(rng.normal(0.0, sigma / np.sqrt(SUB), size=(stop - start, SUB)), axis=1)
        step = draws[start:stop]
        bridge = walk - np.outer(walk[:, -1], weights) + np.outer(step, weights)
        path = base[start:stop, None] + bridge
        low[start:stop] = np.minimum(base[start:stop], path.min(axis=1))
        high[start:stop] = np.maximum(base[start:stop], path.max(axis=1))
    return {"ts": real["ts"], "spread": real["spread"], "open": base, "high": high,
            "low": low, "close": base + draws}


ARMS = {"iid": iid_bars, "garch": garch_bars, "shipped": shipped_geom_bars,
        "contopen": contopen_bars, "path": path_bars}


# ───────────────────────────────── the run ─────────────────────────────────


def summarise(rows: list[dict], key: dict) -> list[dict]:
    """One row per (arm, target, side-group): n, mean R, its sd, and `P(>= NR)`.

    The split halves are by **trade order within the cell**, which is the
    discovery/confirmation split the prior study used, and are reported as a
    gating condition rather than a verdict - the operator's standing
    instruction, since a mechanism that only runs in one regime is still a
    mechanism.
    """
    out = []
    for arm in ARM_NAMES:
        for nn in TARGETS:
            got = [r for r in rows if r["arm"] == arm and r["target"] == nn]
            if not got:
                continue
            for group, sel in (("both", got), ("long", [r for r in got if r["side"] > 0]),
                               ("short", [r for r in got if r["side"] < 0])):
                if not sel:
                    continue
                x = np.array([r["R_gross"] for r in sel])
                reach = np.array([r["reach"] for r in sel], float)
                cost = np.array([r["cost_r"] for r in sel])
                half = len(sel) // 2
                out.append({
                    **key, "arm": arm, "target": nn, "leg": group, "n": len(sel),
                    "mean_R": float(x.mean()), "sd_R": float(x.std(ddof=1)) if len(x) > 1 else 0.0,
                    "reach": float(reach.mean()), "cost_r": float(cost.mean()),
                    "net_R": float((x - cost).mean()),
                    "resolved": float(np.mean([r["resolved"] for r in sel])),
                    "reach_given_resolved": float(
                        np.sum([r["reach"] for r in sel]) / max(1, np.sum([r["resolved"] for r in sel]))),
                    "mean_first": float(x[:half].mean()) if half else float("nan"),
                    "mean_second": float(x[half:].mean()) if half else float("nan"),
                    "arith": 1.0 / (1.0 + nn),
                })
    return out


def one(job) -> tuple[list[dict], list[dict], list[dict]]:
    sym, iv, store, path, trip = job
    try:
        raw, dupes = read(Path(path))
    except Exception as exc:  # noqa: BLE001 - a broken store is a skipped cell, named
        return [], [], [{"sym": sym, "iv": iv, "note": f"unreadable: {exc}"}]
    bars = fold(raw, SEC[iv])
    if len(bars["close"]) < MIN_BARS:
        return [], [], [{"sym": sym, "iv": iv, "store": store, "bars": len(bars["close"]),
                         "dupes": dupes, "note": "too short"}]
    trip = trip if np.isfinite(trip) else 0.0
    seed = zlib.crc32(sym.encode())
    trades, cells, info = [], [], []

    def series():
        yield "real", 0, bars
        for name, make in ARMS.items():
            for k in range(WALKS):
                yield name, k, make(bars, seed=seed + 1_000_003 * (k + 1) + len(name))

    for name, draw, frame in series():
        unit = atr(frame["high"], frame["low"], frame["close"])
        got, tally = [], {}
        for mirror in (False, True):
            part, t = zones_and_trades(frame, unit, mirror, trip,
                                       rng=np.random.default_rng(seed + 13 * draw + mirror))
            got += part
            for k, v in t.items():
                tally[k] = tally.get(k, 0) + v
        key = {"sym": sym, "family": FAMILY.get(sym, "?"), "iv": iv, "store": store,
               "series": name, "draw": draw, "zones": ZONES}
        cells += summarise(got, key)
        info.append({**key, "bars": len(frame["close"]), "dupes": dupes, "trip": trip, **tally,
                     "trades": len([r for r in got if r["target"] == TARGETS[0]])})
        if name == "real":
            for r in got:
                r.update(key)
            trades += got
    return trades, cells, info


def jobs(trips: dict[str, float]) -> list[tuple]:
    src = sources()
    only = [s for s in os.environ.get("SYMBOLS", "").split(",") if s]
    out = []
    for sym in DEEP + WIDE + SYNTH:
        if sym not in src or (only and sym not in only):
            continue
        store = "deep" if sym in DEEP else ("wide" if sym in WIDE else "synth")
        for iv in INTERVALS:
            out.append((sym, iv, store, str(src[sym]), trips.get(sym, float("nan"))))
    return out


def write(rows: list[dict], name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if not rows:
        print(f"no rows for {name}")
        return
    keys = list({k: None for r in rows for k in r})
    opener = gzip.open if name.endswith(".gz") else open
    with opener(OUT / name, "wt", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {OUT / name}  ({len(rows):,} rows)", flush=True)


def _gap_shape(o, h, l, c) -> dict[str, float]:
    """The gap's **distribution**, as a share of each bar's own range.

    `mean(gap)` is the one statistic that cannot see this defect: the identity
    `close[i] - close[i-1] = (open[i] - close[i-1]) + (close[i] - open[i])`
    forces `mean(gap) = -mean(body)` for any series whose bars close above their
    opens with nil close-to-close drift, so a contiguous market and a
    gap-at-every-bar surrogate agree on it and get there completely
    differently. This study withdrew a correct finding on that agreement. The
    median, the share of bars with **no** gap, and the p90 are what separate
    them, and they are printed beside the mean so the mistake cannot recur.
    """
    span = np.maximum(h - l, 1e-12)
    share = np.abs(o[1:] - c[:-1]) / span[1:]
    return {"gap_median": float(np.median(share)),
            "gap_zero": float(np.mean(share < 1e-9)),
            "gap_p90": float(np.quantile(share, 0.90))}


def gap() -> None:
    """Does the market carry the sawtooth the surrogates are judged on?

    **It does, and this mode exists because this study first claimed it did
    not.** The first version of the write-up read a surrogate's negative mean
    `open[i] - close[i-1]` as a defect in
    `node/surrogates.walk_with_bar_geometry` and "fixed" it by opening each bar
    at the previous close. The identity

        close[i] - close[i-1] = (open[i] - close[i-1]) + (close[i] - open[i])

    forces the sign: a series whose bars close above their opens on average
    and whose close-to-close drift is about nil **must** have a negative mean
    gap, the market included. Measured here, the gap is negative on **28 of
    28** of the broker's own 1h FX stores at a mean of **-0.0126** of a bar
    range, with the body positive and the step near zero on every one. So the
    sawtooth is a property of the book and pinning a surrogate's gap at zero
    is a change of null, not a correction.

    What the mode also shows is how closely each arm matches it. At the hourly
    FX cells the shipped construction is the same sign on 5 of 5 and within a
    factor of 0.46 to 4.43, which is the coordinator's own reading; the spread
    grows to 2.4-9.0x at 1d and reaches -0.1393 to +0.1280 on the Deriv
    synthetics, whose own gap is about zero. `contopen_bars` pins it at exactly
    zero on all 54 cells, which is further from the market wherever the market
    has a gap. That is the limit the write-up reports in place of the withdrawn
    defect.
    """
    rows = []
    print("== the broker's own 1h stores, as stored ==")
    print(f"  {'sym':<22}{'gap/span':>10}{'body/span':>11}{'step/span':>11}{'bars':>9}"
          f"{'med|gap|':>11}{'no gap':>10}{'p90|gap|':>10}")
    for path in sorted((HOME / "seqlab").glob("*.1h.npz")):
        sym = path.name[: -len(".1h.npz")]
        with np.load(path) as z:
            o, h, l, c = (z[k].astype(float) for k in ("open", "high", "low", "close"))
        span = float(np.mean(h - l))
        if not span > 0 or len(c) < 2:
            continue
        g, b, st = (float(np.mean(o[1:] - c[:-1])) / span, float(np.mean(c - o)) / span,
                    float(np.mean(np.diff(c))) / span)
        rows.append({"sym": sym, "iv": "1h", "series": "real", "store": "as-stored",
                     "gap_span": g, "body_span": b, "step_span": st, "bars": len(c),
                     **_gap_shape(o, h, l, c)})
        r = rows[-1]
        print(f"  {sym:<22}{g:>10.4f}{b:>11.4f}{st:>11.4f}{len(c):>9,d}"
              f"{r['gap_median']:>11.4f}{r['gap_zero']:>10.4f}{r['gap_p90']:>10.4f}")
    gaps = np.array([r["gap_span"] for r in rows])
    if len(gaps):
        print(f"  negative on {int((gaps < 0).sum())} of {len(gaps)}; "
              f"mean {gaps.mean():+.4f}, median {np.median(gaps):+.4f}")

    print("\n== the folded series this study trades, and the two geometry arms ==")
    print(f"  {'sym':<22}{'iv':>3}  {'arm':<9}{'gap/span':>10}{'med|gap|':>11}"
          f"{'no gap':>10}{'p90|gap|':>10}")
    src = sources()
    for sym in [s for s in DEEP + SYNTH if s in src]:
        raw, _d = read(src[sym])
        for iv in INTERVALS:
            b = fold(raw, SEC[iv])
            if len(b["close"]) < MIN_BARS:
                continue
            for name, frame in (("real", b), ("shipped", shipped_geom_bars(b, seed=5)),
                                ("contopen", contopen_bars(b, seed=5)),
                                ("path", path_bars(b, seed=5))):
                o2, h2, l2, c2 = (frame[k] for k in ("open", "high", "low", "close"))
                span = float(np.mean(h2 - l2))
                g = (float(np.mean(o2[1:] - c2[:-1])) / span if span > 0 else float("nan"))
                shape = _gap_shape(o2, h2, l2, c2)
                rows.append({"sym": sym, "iv": iv, "series": name, "store": "folded",
                             "gap_span": g, "bars": len(c2), **shape})
                print(f"  {sym:<22}{iv:>3}  {name:<9}{g:>10.4f}{shape['gap_median']:>11.4f}"
                      f"{shape['gap_zero']:>10.4f}{shape['gap_p90']:>10.4f}")
    write(rows, "gap.csv")


def overlap() -> None:
    """Is LuxAlgo's order block the same object as this repo's own?

    **Two detectors with the same name are usually two detectors.** `displace`
    and `DISPLACE_C` fire at similar rates over 2.0M bars and agree on about a
    quarter of their union; `origins` and `displacement` agree 59-78%. So before
    any reading here is read against
    [`order-block-zones.md`](../docs/order-block-zones.md)'s, the two zone
    populations are compared bar for bar: the Jaccard of their order-block bars
    and the share of each that the other finds.

    `zones.ob_zones` is that study's detector, called unchanged - the desk's
    rule, with a two-candle push, a body floor, a required imbalance and a
    strong pivot-free break. LuxAlgo's has none of those: a swing high, a close
    through it, and the lowest low in between.
    """
    import pandas as pd

    import zones as Z  # noqa: N812 - that study's module name

    src = sources()
    syms = [s for s in DEEP if s in src]
    rows = []
    for sym in syms:
        raw, _d = read(src[sym])
        for iv in INTERVALS:
            b = fold(raw, SEC[iv])
            if len(b["close"]) < MIN_BARS:
                continue
            unit = atr(b["high"], b["low"], b["close"])
            df = pd.DataFrame({k: b[k] for k in ("ts", "open", "high", "low", "close")})
            df["volume"] = 0.0
            for mirror in (False, True):
                if mirror:
                    f = {"ts": b["ts"], "open": -b["open"], "high": -b["low"],
                         "low": -b["high"], "close": -b["close"], "spread": b["spread"]}
                    d2 = pd.DataFrame({k: f[k] for k in ("ts", "open", "high", "low", "close")})
                else:
                    f, d2 = b, df
                ph, _pl = pivot_flags(f["high"], f["low"], SWING, SWING)
                mine = {p for p, *_ in order_blocks(f["open"], f["high"], f["low"],
                                                    f["close"], ph)}
                theirs = {z.p for z in Z.ob_zones(d2, unit)}
                both = mine & theirs
                rows.append({"sym": sym, "iv": iv, "mirror": int(mirror), "bars": len(f["close"]),
                             "lux": len(mine), "desk": len(theirs), "both": len(both),
                             "jaccard": len(both) / max(1, len(mine | theirs)),
                             "lux_in_desk": len(both) / max(1, len(mine)),
                             "desk_in_lux": len(both) / max(1, len(theirs))})
                print(f"  {sym:<10}{iv:>3} mirror={int(mirror)} bars {len(f['close']):7,d} "
                      f"lux {len(mine):5d} desk {len(theirs):5d} both {len(both):4d} "
                      f"jaccard {rows[-1]['jaccard']:.4f} "
                      f"desk-in-lux {rows[-1]['desk_in_lux']:.4f}", flush=True)
    tot = {k: sum(r[k] for r in rows) for k in ("lux", "desk", "both")}
    print(f"\n  pooled: lux {tot['lux']:,} desk {tot['desk']:,} both {tot['both']:,}  "
          f"jaccard {tot['both'] / max(1, tot['lux'] + tot['desk'] - tot['both']):.4f}  "
          f"of the desk's blocks LuxAlgo finds {tot['both'] / max(1, tot['desk']):.4f}")
    write(rows, "overlap.csv")


def quotes(syms) -> dict[str, float]:
    """The terminal's own round trip per symbol, `nan` where it will not answer.

    Never the per-bar `spread` column: it is in **points, not price**, and runs
    3-8x below the terminal's quote, so a cost taken from it is the one number
    that looks like a measurement and is not. A `nan` is not a cheap row - it is
    an unpriced one, and `cost_r` is 0 there so the write-up can say which cells
    carry a cost and which are geometry.
    """
    try:
        from research.harness.venue import quoted
    except Exception:  # noqa: BLE001 - no bridge from here; geometry only
        return {}
    got = {}
    for s in syms:
        try:
            got[s] = float(quoted(s))
        except Exception:  # noqa: BLE001
            got[s] = float("nan")
    return got


def main() -> None:
    from concurrent.futures import ProcessPoolExecutor

    if MODE == "smoke":
        smoke()
        return
    if MODE == "cost":
        cost()
        return
    if MODE == "power":
        power()
        return
    if MODE == "sweep":
        sweep()
        return
    if MODE == "overlap":
        overlap()
        return
    if MODE == "gap":
        gap()
        return
    if MODE == "check":
        src = sources()
        for sym in [x for x in DEEP if x in src][:4]:
            raw, _d = read(src[sym])
            for iv in INTERVALS:
                b = fold(raw, SEC[iv])
                if len(b["close"]) < MIN_BARS:
                    continue
                small = {k: v[:4000] for k, v in b.items()}
                print(f"  {sym:<10}{iv:>3} vs the package: "
                      f"{check_matches_package(small)}", flush=True)
        return
    src = sources()
    trips = quotes([s for s in DEEP + WIDE + SYNTH if s in src])
    js = jobs(trips)
    quoted_n = int(np.isfinite(list(trips.values())).sum()) if trips else 0
    print(f"{len(js)} cells, {quoted_n} of {len(trips)} quoted, "
          f"{WALKS} draws x {len(ARMS)} walk arms", flush=True)
    trades, cells, info = [], [], []
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", "24"))) as pool:
        for t, cl, inf in pool.map(one, js):
            trades += t
            cells += cl
            info += inf
            print(f"  {len(trades):,} real trade-rows, {len(cells):,} cell rows", flush=True)
    write(trades, "trades.csv.gz")
    write(cells, "cells.csv")
    write(info, "zones.csv")


# ───────────────────────────── cost, power, smoke ─────────────────────────────


def cost() -> None:
    """The cost screen, re-derived rather than quoted.

    Two columns, because they answer different questions. `swing20` is the
    survey's own geometry - the distance from the close to the far side of a
    20-bar swing - and reproducing it is the check that this harness reads the
    same book. `breaker_stop` is **this harness's own realised stop**, the
    median over the breaker trades it actually takes, which is the number the
    result is priced at. Both carry the width
    `tradingview-survey.md` recorded: a single live snapshot, and two snapshots
    of the same book disagreed by 3.7x on gold.
    """
    src = sources()
    syms = [s for s in DEEP + WIDE + SYNTH if s in src]
    trips = quotes(syms)
    rows = []
    for sym in syms:
        raw, _dupes = read(src[sym])
        trip = trips.get(sym, float("nan"))
        for iv in INTERVALS:
            b = fold(raw, SEC[iv])
            if len(b["close"]) < MIN_BARS:
                continue
            h, l, c = b["high"], b["low"], b["close"]
            unit = atr(h, l, c)
            hi = sliding_window_view(h, 20).max(axis=1)
            lo = sliding_window_view(l, 20).min(axis=1)
            swing20 = float(np.median(np.maximum(hi - c[19:], c[19:] - lo)))
            stops = []
            for mirror in (False, True):
                part, _ = zones_and_trades(b, unit, mirror, 0.0, targets=(2.0,))
                stops += [r["stop_d"] for r in part if r["arm"] == "flip"]
            med = float(np.median(stops)) if stops else float("nan")
            a14 = float(np.nanmedian(unit))
            rows.append({"sym": sym, "family": FAMILY.get(sym, "?"), "iv": iv, "bars": len(c),
                         "atr14": a14, "trip_px": trip, "swing20_px": swing20,
                         "swing20_atr": swing20 / a14 if a14 > 0 else float("nan"),
                         "cost_swing20": trip / swing20 if swing20 > 0 else float("nan"),
                         "breaker_stop_px": med,
                         "breaker_stop_atr": med / a14 if a14 > 0 else float("nan"),
                         "cost_breaker": trip / med if med and np.isfinite(med) else float("nan"),
                         "n_flip": len(stops)})
            r = rows[-1]
            print(f"  {sym:<22}{iv:>3}  swing20 {r['cost_swing20']:.4f}  "
                  f"breaker {r['cost_breaker']:.4f}  (stop {r['breaker_stop_atr']:.2f} ATR, "
                  f"n {r['n_flip']})", flush=True)
    write(rows, "cost.csv")


def power() -> None:
    """The leak check, then the power sweep, in that order.

    The leak check is the headline: on a walk every arm must read at or just
    below zero and just below `1/(1+N)`, because all three fill-bar conventions
    are conservative. A positive number there is a defect in this file and is
    worth more than the study.

    The sweep plants a drift of `g` R over the holding window and re-measures,
    on the walks *and* on the real series, so the curve is in the same currency
    as the claim: the smallest edge, in R a trade, this test can tell from zero
    at this sample size. A null with no power curve is not a result.
    """
    src = sources()
    syms = [s for s in (DEEP + SYNTH) if s in src]
    if os.environ.get("POWER_SYMS"):
        syms = [s for s in os.environ["POWER_SYMS"].split(",") if s in src]
    grid = [float(x) for x in os.environ.get("PLANT", "0,0.05,0.1,0.2,0.4,0.8").split(",")]
    rows = []
    for sym in syms:
        raw, _dupes = read(src[sym])
        for iv in INTERVALS:
            b = fold(raw, SEC[iv])
            if len(b["close"]) < MIN_BARS:
                continue
            for name in ("real", "iid", "garch", "shipped", "contopen", "path"):
                frame = b if name == "real" else ARMS[name](b, seed=zlib.crc32(sym.encode()) + 7)
                unit = atr(frame["high"], frame["low"], frame["close"])
                for g in grid:
                    got = []
                    for mirror in (False, True):
                        part, _ = zones_and_trades(frame, unit, mirror, 0.0, targets=(2.0,),
                                                   plant=g)
                        got += part
                    for arm in ARM_NAMES:
                        x = np.array([r["R_gross"] for r in got if r["arm"] == arm])
                        if not len(x):
                            continue
                        reach = np.array([r["reach"] for r in got if r["arm"] == arm], float)
                        se = float(x.std(ddof=1) / np.sqrt(len(x))) if len(x) > 1 else float("nan")
                        rows.append({"sym": sym, "family": FAMILY.get(sym, "?"), "iv": iv,
                                     "series": name, "plant": g, "arm": arm, "n": len(x),
                                     "mean_R": float(x.mean()), "se": se,
                                     "reach2": float(reach.mean()), "arith": 1 / 3})
                        print(f"  {sym:<22}{iv:>3} {name:<6} plant {g:<5} {arm:<15} "
                              f"n {len(x):6d} meanR {x.mean():+.4f} +-{se:.4f} "
                              f"P2 {reach.mean():.4f}", flush=True)
    write(rows, "power.csv")


#: The coordinate sweep: one parameter moved at a time from the pre-registered
#: default, never the full cross. Fifteen configurations x four targets is 60
#: cells and the write-up reports all of them, because the count belongs beside
#: the result - `PUSH_BODY` at two values and `PUSH_N` at two was already "a real
#: search" in the study this one follows.
SWEEP = (
    {},
    {"pad": 0.25}, {"pad": 0.5},
    {"band": "body"},
    {"swing": 5}, {"swing": 20},
    {"expire": 50}, {"expire": 1000},
    {"hold": 5}, {"hold": 30}, {"hold": 120}, {"hold": 300},
)


def _sweep_one(job):
    sym, iv, path, cfg = job
    raw, _dupes = read(Path(path))
    b = fold(raw, SEC[iv])
    if len(b["close"]) < MIN_BARS:
        return []
    unit = atr(b["high"], b["low"], b["close"])
    got = []
    for mirror in (False, True):
        part, _ = zones_and_trades(b, unit, mirror, 0.0,
                                   rng=np.random.default_rng(zlib.crc32(sym.encode())), **cfg)
        got += part
    return [{**r, "sym": sym, "iv": iv, "family": FAMILY.get(sym, "?")} for r in got]


def sweep() -> None:
    """Every parameter moved one at a time, real series only, traded book only.

    The question this answers is not "which cell is best" - picking the best of
    many cells gives a winner every time, and 18 of 43 instruments were
    nominally profitable here where chance gives 22 and **not one** survived
    Benjamini-Hochberg. It answers whether *any* cell is positive in absolute
    terms after its own cost, and the whole grid is printed.
    """
    from concurrent.futures import ProcessPoolExecutor

    src = sources()
    syms = [s for s in DEEP + WIDE if s in src]
    rows = []
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", "24"))) as pool:
        for k, cfg in enumerate(SWEEP):
            js = [(s, iv, str(src[s]), cfg) for s in syms for iv in INTERVALS]
            got = [r for part in pool.map(_sweep_one, js) for r in part]
            label = ", ".join(f"{a}={b}" for a, b in cfg.items()) or "pre-registered default"
            print(f"\n== {k}: {label} ==", flush=True)
            for iv in INTERVALS:
                for arm in ("flip", "fade", "placebo"):
                    for nn in TARGETS:
                        sel = [r for r in got
                               if r["iv"] == iv and r["arm"] == arm and r["target"] == nn]
                        if len(sel) < 30:
                            continue
                        x = np.array([r["R_gross"] for r in sel])
                        reach = np.mean([r["reach"] for r in sel])
                        se = float(x.std(ddof=1) / np.sqrt(len(x)))
                        rows.append({"cell": k, "config": label, "iv": iv, "arm": arm,
                                     "target": nn, "n": len(x), "mean_R": float(x.mean()),
                                     "se": se, "reach": float(reach),
                                     "arith": 1 / (1 + nn)})
                        print(f"  {iv:>3} {arm:<8} {nn:.0f}R n {len(x):6,d} "
                              f"meanR {x.mean():+.4f} +-{se:.4f}  "
                              f"P {reach:.4f} vs {1 / (1 + nn):.4f}", flush=True)
    write(rows, "sweep.csv")


def smoke() -> None:
    """Seconds, on generated bars, locally: does every piece move at all.

    Not a measurement. It exists because a detector that returns nothing and a
    detector that is out of scope read identically - `a zero is a reading, and a
    reading can be of nothing` - so every stage's count is printed, and the two
    identical calls at the end are the cheapest test for a sweep whose cells
    share state.
    """
    rng = np.random.default_rng(1)
    n = 40_000
    bars = _bars_from_steps(rng.standard_t(4.0, (n, 32)) * 1e-4 / np.sqrt(32), 1.10)
    bars["ts"] = np.arange(n, dtype=np.int64) * 900 + 1_600_000_000
    bars["spread"] = np.zeros(n)
    for iv in ("1h", "4h"):
        b = fold(bars, SEC[iv])
        unit = atr(b["high"], b["low"], b["close"])
        allrows = []
        for mirror in (False, True):
            rows, tally = zones_and_trades(b, unit, mirror, 0.0, targets=(2.0,))
            allrows += rows
            by: dict[str, int] = {}
            for r in rows:
                by[r["arm"]] = by.get(r["arm"], 0) + 1
            print(f"{iv} mirror={int(mirror)} bars={len(b['close'])} {tally} trades={by}")
        for arm in ARM_NAMES:
            x = np.array([r["R_gross"] for r in allrows if r["arm"] == arm])
            p = np.array([r["reach"] for r in allrows if r["arm"] == arm], float)
            if len(x) > 2:
                print(f"   {arm:<15} n {len(x):5d} meanR {x.mean():+.4f} "
                      f"+-{x.std(ddof=1) / np.sqrt(len(x)):.4f}  P(>=2R) {p.mean():.4f} "
                      f"vs 0.3333")
    b = fold(bars, SEC["4h"])
    unit = atr(b["high"], b["low"], b["close"])
    a, _ = zones_and_trades(b, unit, False, 0.0, targets=(2.0,))
    c, _ = zones_and_trades(b, unit, False, 0.0, targets=(2.0,))
    same = len(a) == len(c) and all(x["R_gross"] == y["R_gross"] for x, y in zip(a, c))
    print(f"two identical calls agree: {same}")


if __name__ == "__main__":
    main()
