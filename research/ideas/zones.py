"""Origin zones: where a violent move began, traded on the first return, with 4h as the mother cycle.

The idea (the desk's, 2026-10-02): a level that launched an aggressive move - the move broke
structure and left an imbalance on the way - is where the market will defend again. When price
first comes back there it may bounce at once, stall, or grind; a reaction there is traded toward
the nearest opposite zone of the same kind. 1h to 1d, everything aligned with the 4h.

  origin   a swing low (left/right 3) whose up-leg, within 10 bars, closes above the last swing
           high known before it (the break of structure, BOS) without trading below it, travels
           at least 3 ATR, and leaves a fair-value gap (a bar whose low clears the high two bars
           earlier by 0.2 ATR). The zone is that bar from its low to its body top (at least 0.2,
           at most 1.5 ATR tall). Live once the pivot, the BOS and the gap are all known.
           Short zones are the same on the flipped chart
           The break must be strong: the next 3 bars close beyond the level and price reaches 1
           ATR past it within 5 bars (the zone is live only once that is known). Stricter after the
           first plots: the leg is 3 ATR within 10 bars and the gap at least 0.2 ATR
  return   the first bar after that whose low reaches the zone. From there a 12-bar window: the
           zone fails on a close 0.1 ATR beyond it; a trigger needs the bar's low (high) still
           within 0.25 ATR of the zone
  triggers touch    a resting limit at the zone's near edge - no confirmation
           pin      a pin bar: wick at least 60% of the range toward the zone, body at most a
                    third, closes in the far half, range at least half an ATR
           engulf   a bullish (bearish) engulfing bar
           star     a morning (evening) star: a bar against, a small body, then a bar closing
                    past the first's midpoint
           inside   an inside bar broken in the trade's direction
           cisd     change in state of delivery: within 3 bars of the down candles that brought
                    price in, a close above the open of the first of them
           reclaim  the stall or grind resolved: a close above every high since the return
           second batch (asked for after the first): sweep (a wick under the zone closing back
           in), double (a second low at the first, then a close over the high between), ifvg (a
           bearish gap left on the way in, closed through), choch (a close over the last 2-bar
           swing high since the approach), rsi_div (a lower low with a higher RSI), displace (a
           1-ATR body leaving the zone), tweezer, outside (an outside bar closing over the last
           high), climax (tick volume twice its 20-bar median, closing in the top half)
           cisd@T / choch@T (asked for after the CHoCH gallery showed late entries): the return
           confirmed on a lower timeframe T - 1h, 30m or 15m under a 4h or 1d zone, 30m or 15m
           under a 1h one - a CISD or CHoCH after T's first bar in the zone, entered at T's next
           open on T's book, stop under the reaction's low since the touch; cisd_z@T the same
           with the stop past the zone. The broker's 15m starts 2024-07; 30m is built from it
           Each enters at the next open; the stop is 0.1 ATR beyond the zone or the lowest low
           since the return, whichever is further
  exits    opp   the near edge of the nearest live opposite zone (the swing extreme the leg made
                 when there is none) - the idea's own target
           t4, t10, trail (2 ATR)
  candles  strong  (asked for later) the leg's candles are strong, not sloppy: bodies on average
                   60% of their range, 70% of bars in the move's direction, one body of 1 ATR+.
                   Run as a filter on top of the 4h bias
  dax      (asked for later) dax: the origin was a PROTECTED low (it swept the last swing low of
           the 40 bars before and closed back above it) with STRUCTURAL LIQUIDITY in the leg (a
           swing low above the origin before the break - no inducement); dax_major: and the high
           it broke was a lower high. On top of the 4h bias. The other half of the combination is
           in `dax_smc.py` (its POI on a live zone of ours)
  bjorgum  (asked for later) bjorg: the zone overlaps a Bjorgum key-level zone shown at the trigger
           bar (`bjorgum_live`: 20/15 pivots, half-width min(0.5 ATR30, 2.5%), merged, 4 newest a
           side); bjorg_strong with the strong-candle leg; bjorg_dax with the DAX tests. On top of
           the 4h bias. ZONES=bjorgum trades Bjorgum's zones alone
  zma      (asked for later) production's Z-Momentum Attention replayed bar by bar (`zma_series`):
           zma - at the trigger bar it `agrees` with the zone (oversold and rising for a long);
           zma_stretch - it is merely stretched the zone's way; zma_bjorg - stretched and on a
           Bjorgum zone; zma_strong - stretched with the strong-candle leg. On top of the 4h bias
  gap      (asked for later) nogap / hasgap: whether production's `gap` pass would have been one of
           this zone's drawers - an open fair-value gap whose midpoint sits in the zone's band at
           the trigger bar. `gap-levels.md` measures those levels holding 7.4 points worse on
           110,299 production outcomes, so this is a filter with a negative sign. Both arms, on
           top of the 4h bias
  smc      (asked for later) smc_pd: longs in the discount half of the 4h dealing range (shorts
           in the premium); smc_idm: inducement - an inner swing low formed after the break and
           swept on the way back; smc_kz (1h): the trigger closes in the London or New York
           killzone; smc_all: all of them. fast_old: the desk's NAS100 example - a zone at least 50
           bars old, reached by a 3-ATR fall in 5 bars. Each on top of the 4h bias
  4h       bias   the last 4h break of structure points the trade's way (the mother cycle)
           nest   (1h only) the entry also sits inside a live 4h zone of the same side
           none   no filter, for comparison

  hold     5 days at most (the desk's 3-5), whatever the timeframe
  direction  (asked for later) accuracy with the stop aside: the move in ATR 6 hours, 1, 3 and 5
             days on, and whether price reaches 1/2/4 ATR in the zone's favour before as much
             against within the 5 days,
             each against the same side at three random bars of the same market

  vol        (asked for later) does a volatility forecast pick better zones? A walk-forward HAR
             forecast of the next 5 days' true range over ATR; setups by its causal tercile, on
             trade R and the direction measures, each against random bars of the same tercile

  ZONES=prod  every mode on production's own origins (`structures/drawing/origins.py`) instead:
             replayed every 4 bars over the last 1,000 at production's volatility unit, live from
             the first replay that finds them; the zone is production's band. Asked for once the
             desk learned the research zones were not production's

  ZONES=fvg   every mode on fair-value gaps as the zones instead (asked for later): a 0.2+ ATR
             three-bar gap, far edge to near edge, live when it forms; strong = a 1-ATR
             displacement body left it

  OUT=... MT5BT_DB=... [ZONES=prod|fvg] MODE=plot|run|gallery|direction|vol python research/ideas/zones.py
"""
from __future__ import annotations

import os
import sys
import zlib
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

import prims as P  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/zones"))
LR, MAXLEG, MINLEG, FVG_MIN, WINDOW, NEAR, EXPIRE = 3, 10, 3.0, 0.2, 12, 0.25, 300
# **The reaction need not be immediate.** Asked for 2026-10-07: "the play might not happen
# immediately, it might happen later, even days ahead". `WINDOW` is the bars allowed for a
# reaction after the return and was fixed at 12 - two days at 4h - which decides the answer
# for a setup that takes longer. `EXPIRE` (300 bars, 50 days at 4h) already allows a late
# return; this is the other half of the same point.
WINDOW = int(os.environ.get("WINDOW", WINDOW))
EXPIRE = int(os.environ.get("EXPIRE", EXPIRE))  # bars a zone stays live waiting for its return
MAXLEG = int(os.environ.get("MAXLEG", MAXLEG))  # bars the break of structure is allowed to take
BUF = float(os.environ.get("BUF", 0.1))  # the stop past the zone, in ATR (0.3 / 0.5 / 1 tried after a wick stopped one)
HOLD_BARS, FOLLOW = 3, 1.0  # a strong break: no close back through it for 3 bars, 1 ATR beyond it within 5
OB_MINLEG = float(os.environ.get("OB_MINLEG", 1.5))  # `ob_zones`' leg floor, in ATR
#: Bars the break of structure looks back over. A close above the highest high
#: of this window is the break, with no swing high and so no pivot definition
#: anywhere in `ob_zones`. Twenty is a working month at 4h and a trading month at
#: 1d; it is not measured, and it is the one number here that replaced a rule
#: rather than a threshold.
OB_LOOKBACK = int(os.environ.get("OB_LOOKBACK", 20))
#: Whether the zone spans the zone candle's body or its whole range, wick to
#: wick.
#:
#: **"range" by default from 2026-10-07**: "for a demand we mark the full candle
#: range from high to low". "body" keeps `long_zones`' convention and the first
#: build's, and is kept so the two can be compared - the choice moves the entry,
#: the stop and therefore every R in the study, so it is a real variant and not
#: a drawing preference.
OB_BAND = os.environ.get("OB_BAND", "range")

#: The zone's width, clipped to this many ATR either side, so a single enormous
#: candle is not a zone the width of the screen. A large value turns it off;
#: `ORIGIN_MAX` now limits the candle's size directly, which is the better
#: handle on the same problem.
OB_CLIP = float(os.environ.get("OB_CLIP", 1.5))
#: How far back from the impulse the origin may sit. Asked for 2026-10-07:
#: "look for impulsive candles, then candle before this impulsive candle".
#:
#: The first build scanned the other way - every bar was tested as an origin and
#: the push had to begin on the very next bar - which is the same rule only when
#: the candle immediately before the impulse happens to be the last one against
#: the move. It often is not: a small candle the move's own colour sits between
#: them and the setup is dropped, though a reader would mark the red candle
#: behind it.
#:
#: With `OB_BACK` at `d`, the push may begin up to `d` bars after the origin, and
#: every bar in between must be the move's own colour - if one of them is
#: against the move then *it* is the last candle against the move, and the scan
#: finds it as its own origin at a smaller gap. 0 is the original behaviour.
OB_BACK = int(os.environ.get("OB_BACK", 0))

#: How many bars before the zone candle must be clear of it for the zone to
#: count as **fresh**. Asked for 2026-10-07: "the zone should be fresh".
#:
#: Two of the three usual readings are already in the rule and cost nothing to
#: state: the zone is traded on its **first** return (`Zone.ret`), so it is
#: untested at entry by construction, and it is traded once.
#:
#: What is left is freshness at **creation** - whether the band sits where price
#: has recently been doing business. Measured on **closes**, not ranges: the bar
#: immediately before the zone candle almost always overlaps its range in a
#: continuous market, so a range test rejects nearly everything and says only
#: that bars touch. A close inside the band means price actually settled there.
#:
#: 0 is off, which is the first build's behaviour.
FRESH = int(os.environ.get("FRESH", 0))
#: How much of a confirming candle's range must be the wick *under* its body
#: (over it, on a supply zone) before the return counts as a rejection. Asked
#: for 2026-10-07: "after it returns to the zone let's wait for a candlestick
#: pattern as confirmation, looking at pinbars/hammers or candle with medium to
#: long lower wick if it was a demand zone or support level".
#:
#: `pin` is the strict reading already in `TRIGGERS` - 60% of the range below
#: the body, a body of a third or less. `wick` is the "medium to long" one: a
#: lower wick of `WICK_MIN`+ of the range and longer than the body, closing in
#: the upper half. `pin` is a subset of `wick`, so the pair measures how much
#: the strictness is worth rather than whether a wick is worth anything.
WICK_MIN = float(os.environ.get("WICK_MIN", 0.40))
TRIGGERS = ("touch", "touch_mid", "touch_far", "touch_deep", "pin", "wick", "engulf", "star", "inside", "reclaim", "cisd",
            "sweep", "double", "ifvg", "choch", "rsi_div", "displace", "tweezer", "outside", "climax")
SEC = {"1h": 3600, "4h": 14400, "1d": 86400}


@dataclass
class Zone:
    side: int
    p: int  # the origin bar
    lo: float  # far edge (long: the low)
    hi: float  # near edge (long: the body top)
    bos: int
    bos_level: float
    fvg: int
    live: int  # first bar it is known
    leg_extreme: float
    clean: bool = False  # the leg's candles were strong (see `strong_leg`)
    push: bool = False  # two consecutive candles left it, the second closing past the first's close
    push_hi: bool = False  # ... past the first's high: the stronger form (`sequential_push`)
    ob: bool = False  # the origin was the last candle against the move, with a body (`strong_origin`)
    line: float = float("nan")  # the level inside the zone: the origin's close = the push bar's open
    ret: int = -1  # first return
    dead: int = -1  # the bar it failed (closed through), or expired
    parts: tuple = ()  # for a level: the (bar, low, high) of each gap that made it
    target: float = float("nan")  # a zone that carries its own target (the rejection trade: the BOS level)
    # the DAX mentorship's tests asked of an origin zone (research zones only; see `long_zones`)
    protected: bool = False
    major: bool = False
    has_sl: bool = False


def flip(df: pd.DataFrame) -> pd.DataFrame:
    """The chart upside down: a short on it is a long here."""
    return df.assign(open=-df["open"], close=-df["close"], high=-df["low"], low=-df["high"])


def long_zones(df: pd.DataFrame, a: np.ndarray, side: int = 1) -> list[Zone]:
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    n = len(df)
    ph, pl = P.pivots(h, l, LR, LR)
    ph_known = np.array([x[0] for x in ph])
    out = []
    for known, p, low in pl:
        if not a[p] > 0:
            continue
        j = np.searchsorted(ph_known, p, side="right") - 1  # last swing high known by the origin
        if j < 0:
            continue
        level = ph[j][2]
        if level <= low:
            continue
        b = -1
        for k in range(p + 1, min(n, p + MAXLEG + 1)):
            if l[k] < low:
                break
            if c[k] > level:
                b = k
                break
        if b < 0 or b + HOLD_BARS >= n:
            continue
        # a strong break: the next bars hold beyond the level and extend at least an ATR past it -
        # not a poke that falls back or stalls at the line
        if c[b + 1:b + 1 + HOLD_BARS].min() <= level or h[b:b + 6].max() < level + FOLLOW * a[p]:
            continue
        strong = b + max(HOLD_BARS, int(np.argmax(h[b:b + 6] >= level + FOLLOW * a[p])))
        ext = h[p:b + 1].max()
        if ext - low < MINLEG * a[p]:
            continue
        gaps = [k for k in range(p + 2, b + 1) if l[k] > h[k - 2] + FVG_MIN * a[p]]
        if not gaps:
            continue
        top = max(o[p], c[p])
        top = min(max(top, low + 0.2 * a[p]), low + 1.5 * a[p])
        z = Zone(side, p, low, top, b, level, gaps[0], max(known, strong, gaps[0]), ext,
                 strong_leg(o, h, l, c, a[p], p, b),
                 sequential_push(o, h, l, c, p, side, strong=False),
                 sequential_push(o, h, l, c, p, 1, strong=True),
                 strong_origin(o, h, l, c, p, side),
                 # **The level inside the zone**, asked for 2026-10-07: where the
                 # last candle against the move closed, which in a continuous
                 # market is where the first displacement candle opened. On a
                 # demand zone that is the bearish origin's close - below its
                 # body top, so an entry there is deeper than the zone's near
                 # edge and carries a different stop.
                 float(c[p]))
        # The DAX mentorship's tests, asked of this origin (`dax_smc.py` has the method in full):
        # PROTECTED - the origin swept the last swing low of the 40 bars before it (one nothing had
        # broken) and closed back above it within two bars; MAJOR - the high it broke was a lower
        # high; STRUCTURAL LIQUIDITY - a swing low inside the leg, above the origin (without one
        # the course calls the origin inducement and stands down)
        prior = [x for x in pl if p - 40 <= x[1] < p and x[0] <= p]
        if prior:
            _, q, q_px = prior[-1]
            z.protected = bool(low < q_px and l[q + 1:p].min(initial=np.inf) >= q_px and c[p:p + 2].max() > q_px)
        z.major = bool(j >= 1 and level < ph[j - 1][2])
        z.has_sl = any(p < x[1] < b and x[2] > low for x in pl)
        # its first return, or the bar it is broken / expires before one
        for k in range(z.live + 1, min(n, z.live + EXPIRE)):
            if l[k] <= z.hi:
                z.ret = k
                break
        out.append(z)
    return out


#: The least of its own range a candle's body must be before it counts as a push
#: rather than a stall. "Fairly okay or big", as the desk put it; a doji that
#: happens to close higher is not two candles leaving a zone.
#:
#: **0.45, set by the desk on 2026-10-07 after a first run at 0.50.** That is two
#: values tried, and the second was chosen with the first one's result already
#: visible - so any figure from it carries one degree of freedom that the first
#: did not. Recorded here rather than left in a commit message, because a
#: threshold's history is the difference between a frozen rule and a swept one.
PUSH_BODY = float(os.environ.get("PUSH_BODY", 0.70))

#: The origin's own body floor, separate from the impulsive candles'. The desk
#: set the push to 70% on 2026-10-07 while the order block keeps 45%: they are
#: different claims - a momentum candle should be nearly all body, while the
#: last candle against the move only has to be a real candle rather than a doji.
ORIGIN_BODY = float(os.environ.get("ORIGIN_BODY", 0.45))

#: Whether the origin must be a candle **against** the move - red before a
#: rally, green before a sell-off.
#:
#: The desk gave it both ways on 2026-10-07. First "the origin bar is the last
#: candle before the opposite move", which reads as the order block; then, after
#: seeing the marked charts, **"for the zone the colour of the candle does not
#: matter"** - the zone is simply the candle the impulse left from, whatever
#: colour it closed. Off by default, because that is the later word; `1`
#: restores the order-block reading and the sweep runs both.
ORIGIN_COLOUR = os.environ.get("ORIGIN_COLOUR", "0") not in ("0", "", "no", "false")

#: The origin's range, as a multiple of the **first impulse candle's** range.
#: "It is normally a small candle", 2026-10-07 - small next to what left it, not
#: small in absolute terms, so this is a ratio and not an ATR figure. 1.0 means
#: "no bigger than the candle that left it"; a large value turns the test off.
ORIGIN_MAX = float(os.environ.get("ORIGIN_MAX", 1.0))


#: How many consecutive candles must leave the zone. Two was the desk's first
#: shape; `PUSH_N` generalises it on request, 2026-10-07. Each extra candle is
#: another value tried, and the count belongs beside the result.
PUSH_N = int(os.environ.get("PUSH_N", 2))

#: Which form of `sequential_push` **admits** a zone at all, as opposed to
#: tagging one that already exists. Asked for 2026-10-07: "for the displacement
#: candles, let's use the strong one instead of the weak ones".
#:
#: Weak is `close[k+1] > close[k]`, strong is `close[k+1] > high[k]` - the second
#: candle closing past the first's whole range rather than merely past its
#: close. Strong implies weak, so this only ever removes zones.
#:
#: It is **not** the same change as the `push_hi` filter, which selects among
#: zones the weak gate already let in. The gate decides which zones *exist*, and
#: zones are read by `opposite_target`, so a zone dropped here also stops being
#: a target for every other zone. The first run reported the strong form as
#: worse than the weak one - but that was measured as a filter, on the
#: 84%-long population, before the `setups` bug was found. Both claims are
#: therefore open, and `PUSH_STRONG=0` restores the old gate for the comparison.
PUSH_STRONG = os.environ.get("PUSH_STRONG", "1") not in ("0", "", "no", "false")


def sequential_push(o, h, l, c, p, side: int, strong: bool, n: int | None = None,
                    offset: int = 0) -> bool:
    """`n` **consecutive** candles leaving the zone, each making progress on the last.

    Asked for 2026-10-07, and it is not `strong_leg`. That one is an aggregate
    over the whole leg - bodies averaging 60% of their range, 70% of bars the
    right way - which a leg can pass while its second bar closes back inside the
    first's range. This is pairwise and ordered:

    * both bars the zone's colour, each body at least `PUSH_BODY` of its range
    * **weak**: `close[2] > close[1]` - the second made progress on the first
    * **strong**: `close[2] > high[1]` - it closed above the first's whole range,
      which is a commitment the desk expects to carry a higher probability

    Mirrored for a supply zone. The bars are those **after** the origin bar,
    matching `strong_leg`'s `slice(p + 1, b + 1)`: the origin bar is the zone,
    and the leg is what leaves it.

    With `n` above two the condition is applied to every adjacent pair, so each
    candle must clear the one before it - not merely the first. A run that
    stalls in the middle is not a longer push, it is a push and then a pause.
    """
    n = PUSH_N if n is None else n
    if n < 2:
        raise ValueError("a push needs at least two candles")
    #: `offset` moves the push away from the origin. The desk's search order,
    #: 2026-10-07, is "look for impulsive candles, then candle before this
    #: impulsive candle" - and the candle immediately before an impulse is not
    #: always the last one against the move; it can be a small candle the
    #: move's own colour. With `offset` 0 this is the original behaviour.
    k = list(range(p + 1 + offset, p + 1 + offset + n))
    if k[-1] >= len(c):
        return False
    bodies = [c[i] - o[i] for i in k]
    ranges = [max(h[i] - l[i], 1e-12) for i in k]
    if any(abs(b) / r < PUSH_BODY for b, r in zip(bodies, ranges)):
        return False
    if side > 0:
        if not all(b > 0 for b in bodies):
            return False
        return all(c[k[m + 1]] > (h[k[m]] if strong else c[k[m]]) for m in range(n - 1))
    if not all(b < 0 for b in bodies):
        return False
    return all(c[k[m + 1]] < (l[k[m]] if strong else c[k[m]]) for m in range(n - 1))


def strong_origin(o, h, l, c, p, side: int) -> bool:
    """The origin bar is the **last candle against the move**, with a real body.

    The desk's definition, 2026-10-07: "the origin bar is the last candle before
    the opposite move, often good body ratio for it too means it's strong". That
    is the order block - for a demand zone, the last *down* candle before the
    rally leaves.

    It is not what `long_zones` selects. That takes a 3/3 **pivot low**, which is
    a shape of the bars either side of it and says nothing about the bar's own
    colour: a hammer that swept the low and closed green is a pivot low and is
    not an order block. So this is kept apart from `sequential_push` rather than
    folded into it - the two conditions are different claims and the run should
    say which of them, if either, carries anything.
    """
    body = c[p] - o[p]
    rng = max(h[p] - l[p], 1e-12)
    if abs(body) / rng < ORIGIN_BODY:
        return False
    if not ORIGIN_COLOUR:  # "for the zone the colour of the candle does not matter"
        return True
    return bool(body < 0) if side > 0 else bool(body > 0)


def strong_leg(o, h, l, c, A, p, b) -> bool:
    """The leg out of the zone made of strong candles, not sloppy ones: bodies at least 60% of
    their ranges on average, at least 70% of the bars in the move's direction, and one body of an
    ATR or more."""
    k = slice(p + 1, b + 1)
    body = c[k] - o[k]
    rng = np.maximum(h[k] - l[k], 1e-12)
    return bool((np.abs(body) / rng).mean() >= 0.6 and (body > 0).mean() >= 0.7 and body.max() >= A)


def ob_zones(df: pd.DataFrame, a: np.ndarray, side: int = 1) -> list[Zone]:
    """Zones built **on the order block**, not on a pivot low.

    The desk's definition, 2026-10-07: "the origin bar is the last candle before
    the opposite move". `long_zones` takes a 3/3 pivot low instead - a shape made
    by the bars either side of it, which says nothing about the origin's own
    colour. On the first run that mattered: of 274 zones with a two-candle push,
    only **59 (22%)** had an order-block origin, so the filter was mostly
    measuring pivot lows that happened to be followed by two good candles.

    So the zone is found from the push backwards:

    1. two consecutive candles leaving, each with a body of `PUSH_BODY`+ of its
       range and the second closing past the first (`sequential_push`)
    2. the bar before them is the origin, and must be the **last candle against
       the move** with a real body (`strong_origin`)
    3. the band is that candle's low to its body top, and the **line** inside it
       is where it closed - which in a continuous market is where the first push
       candle opened
    4. from there, the same structure break, live bar and return as `long_zones`,
       so the two are comparable where it counts

    Everything else is deliberately unchanged. If this reads better than
    `long_zones` it is the origin that did it, and nothing else moved.
    """
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    n = len(df)
    out = []
    for p in range(OB_LOOKBACK, n - PUSH_N - OB_BACK - 1):
        if not a[p] > 0:
            continue
        # **Always the long logic, whatever `side` says.** `zones_ob` passes an
        # already-mirrored frame for the short side, exactly as `zones` does, so
        # `side` is a tag and not a direction here - `strong_leg` takes no side
        # argument at all for the same reason.
        #
        # Threading `side` in was a bug that cost the short side entirely:
        # on the flipped frame it hunted a bearish origin and a bearish push on
        # an already-negated chart, so the zones came out **100% long on daily**
        # and 96% long at 4h. That made every "flip" result a standing short
        # rather than a reversed zone, which is a bet on the instrument set and
        # the period, not a finding.
        if not strong_origin(o, h, l, c, p, 1):
            continue
        # The impulse, allowed to start up to `OB_BACK` bars later (see the
        # constant). The first gap that works is taken: a nearer impulse is the
        # one a reader would draw the zone from.
        d = next((d for d in range(OB_BACK + 1)
                  if (not ORIGIN_COLOUR or all(c[i] >= o[i] for i in range(p + 1, p + 1 + d)))
                  and sequential_push(o, h, l, c, p, 1, strong=PUSH_STRONG, offset=d)), None)
        if d is None:
            continue
        # "It is normally a small candle" - small beside the candle that left it.
        if h[p] - l[p] > ORIGIN_MAX * (h[p + 1 + d] - l[p + 1 + d]):
            continue
        low = l[p]
        # **The break of structure, without a swing high.** Asked for
        # 2026-10-07. `long_zones` breaks a 3/3 pivot high, which makes the zone
        # depend on a shape three bars either side of some earlier bar - and
        # pivots are sparse, so most displacements have no recent one to break.
        # The highest high of the last `OB_LOOKBACK` bars is the same claim
        # without that dependency: price closed above everything it has traded
        # through in that window.
        level = float(h[p - OB_LOOKBACK:p].max())
        if level <= low:
            continue
        b = -1
        for k in range(p + 1, min(n, p + MAXLEG + 1)):
            if l[k] < low:
                break
            if c[k] > level:
                b = k
                break
        if b < 0 or b + HOLD_BARS >= n:
            continue
        if c[b + 1:b + 1 + HOLD_BARS].min() <= level or h[b:b + 6].max() < level + FOLLOW * a[p]:
            continue
        strong = b + max(HOLD_BARS, int(np.argmax(h[b:b + 6] >= level + FOLLOW * a[p])))
        ext = h[p:b + 1].max()
        # **`OB_MINLEG`, not `MINLEG`.** The desk's definition is an order block,
        # two candles leaving it and a break of structure - it says nothing about
        # the leg covering three ATR. Carrying `long_zones`' 3.0 over left 16
        # zones on 13,216 EURUSD bars, because that figure was chosen for legs
        # out of pivot lows and a two-candle push rarely travels that far by the
        # break. Stated as its own constant so the difference is visible rather
        # than inherited.
        if ext - low < OB_MINLEG * a[p]:
            continue
        # **The imbalance is required**, asked for 2026-10-07. It is the natural
        # partner of a two-candle push rather than an extra condition bolted on:
        # the first gap this can find is at `k = p + 2`, where `l[p+2] > h[p]` -
        # the hole between the order block's own high and the second push
        # candle's low, which is the displacement leaving a gap behind it.
        # **Over the push as well as the leg.** `long_zones` searches `[p+2, b]`,
        # which works there because its leg out of a pivot low takes a while to
        # break. Here the break often lands on the *first* push bar, making that
        # window empty - so the imbalance could never be found and every
        # fast-breaking setup was dropped in silence, whatever it did. The gap the
        # displacement leaves is at `p + 2` (`low[p+2] > high[p]`), the hole over
        # the order block itself, so the window has to reach at least that far.
        end_gap = max(b, p + d + PUSH_N)
        gaps = [k for k in range(p + d + 2, end_gap + 1)
                if k < len(l) and l[k] > h[k - 2] + FVG_MIN * a[p]]
        if not gaps:
            continue
        # The band is the order block's own body, clipped like `long_zones` clips
        # its own so one enormous candle is not a zone the width of the screen.
        # **The band: the body, or the whole candle.** Asked for 2026-10-07.
        # `long_zones` uses the body top and that was inherited; a reader who
        # draws the order block wick to wick gets a wider band, a deeper entry
        # and a different stop, so it is a real variant and not a presentation
        # choice. Both are run rather than one being picked.
        top = h[p] if OB_BAND == "range" else max(o[p], c[p])
        top = min(max(top, low + 0.2 * a[p]), low + OB_CLIP * a[p])
        # Fresh: nothing closed inside the band in the bars before it formed.
        if FRESH and np.any((c[max(0, p - FRESH):p] >= low) & (c[max(0, p - FRESH):p] <= top)):
            continue
        known = p + d + PUSH_N  # the push is complete here; nothing earlier could know it
        z = Zone(
            side, p, low, top, b, level, gaps[0],
            max(known, strong, gaps[0]), ext,
            strong_leg(o, h, l, c, a[p], p, b),
            True,  # push (weak), by construction: strong implies weak
            PUSH_STRONG or sequential_push(o, h, l, c, p, 1, strong=True, offset=d),
            True,  # ob, by construction
            # **The line inside the zone: the body's near edge.** 2026-10-07:
            # "the support is the open price if the candle was a green candle,
            # and the close if the candle was a red candle" - which is
            # `min(open, close)` for a demand zone, the bottom of the body,
            # mirrored for supply by the flipped frame.
            #
            # It is the same price as the first draft on a red zone candle, and
            # the first draft only ever had red ones: that version read the line
            # as "where the last opposite candle closed". Once the colour stopped
            # mattering the two readings parted, and this is the one the desk
            # gave second.
            float(min(o[p], c[p])),
        )
        # Its first return, exactly as `long_zones` finds one. Left out of the
        # first draft, which is why that build produced sixteen zones and not
        # one of them had a return: `ret` defaults to -1 and nothing else fills
        # it, so every downstream pass skipped them silently.
        for k in range(z.live + 1, min(n, z.live + EXPIRE)):
            if l[k] <= z.hi:
                z.ret = k
                break
        out.append(z)
    return out


def zones_ob(df, a):
    """Both sides of `ob_zones`, in this chart's prices."""
    zl = ob_zones(df, a, 1)
    zs = ob_zones(flip(df), a, -1)
    for z in zs:
        z.lo, z.hi, z.bos_level, z.leg_extreme = -z.lo, -z.hi, -z.bos_level, -z.leg_extreme
        z.line = -z.line
    return zl + zs


def zones(df, a):
    """Both sides, in this chart's prices (short zones' lo/hi are the high and the body bottom)."""
    zl = long_zones(df, a, 1)
    zs = long_zones(flip(df), a, -1)
    for z in zs:
        z.lo, z.hi, z.bos_level, z.leg_extreme = -z.lo, -z.hi, -z.bos_level, -z.leg_extreme
    return zl + zs


def prod_unit(df: pd.DataFrame) -> np.ndarray:
    """Production's volatility unit on each bar, in price: an exponentially weighted mean absolute
    close-to-close move (half-life 60 bars, floor 0.25 bps) times the close
    (`structures/vol/volatility.py`)."""
    c = df["close"].to_numpy()
    move = np.r_[0.0, np.abs(np.diff(c)) / np.maximum(np.abs(c[:-1]), 1e-12) * 10_000]
    alpha = 1.0 - np.exp(np.log(0.5) / 60.0)
    bps = pd.Series(move).ewm(alpha=alpha, adjust=False).mean().to_numpy()
    return c * np.maximum(bps, 0.25) / 10_000.0


def zones_prod(df: pd.DataFrame, a: np.ndarray, stride: int = 4) -> list[Zone]:
    """Production's origins (`structures/drawing/origins.py`), replayed as production finds them:
    every `stride` bars, `Origins.observe` over the last 1,000 bars at that bar's volatility unit.
    An origin is live from the first replay that sees it (never before its structure break). The
    zone is production's band - the turn bar's range, or its body when the bar is 2+ units wide."""
    from types import SimpleNamespace

    from till_infinity.structures.drawing.origins import Origins
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    ts = df["ts"].to_numpy()
    unit = prod_unit(df)
    bars = [SimpleNamespace(open=o[k], high=h[k], low=l[k], close=c[k]) for k in range(len(df))]
    seen: dict = {}
    for T in range(200, len(df), stride):
        lo_ = max(0, T - 999)
        got = Origins().observe([float(x) for x in ts[lo_:T + 1]], [float(x) for x in c[lo_:T + 1]], float(unit[T]),
                                bars_at=bars[lo_:T + 1])
        for g in got:
            key = (g.when, g.launched)
            if key not in seen:
                seen[key] = (g, T)
    out = []
    for (when, launched), (g, T) in seen.items():
        p = int(np.searchsorted(ts, when))
        bos = int(np.searchsorted(ts, g.settled))
        if not (0 <= p < len(df)) or not a[p] > 0:
            continue
        side = 1 if launched == "up" else -1
        live = max(T, bos)
        ext = h[p:bos + 1].max() if side > 0 else l[p:bos + 1].min()
        lo_e, hi_e = (g.low, g.high) if side > 0 else (g.high, g.low)  # far edge, near edge
        if side > 0:
            clean = strong_leg(o, h, l, c, a[p], p, bos)
        else:
            clean = strong_leg(-o, -l, -h, -c, a[p], p, bos)
        z = Zone(side, p, lo_e, hi_e, bos, c[bos], p, live, ext, clean)
        for k in range(live + 1, min(len(df), live + EXPIRE)):
            if (l[k] <= hi_e) if side > 0 else (h[k] >= hi_e):
                z.ret = k
                break
        out.append(z)
    return sorted(out, key=lambda z: z.live)


def gap_open_spans(df: pd.DataFrame, a: np.ndarray, min_vol: float = FVG_MIN) -> list[tuple]:
    """Every qualifying fair-value gap as `(formed, dies, low, high)`, the bars it is open between.

    This is what production's `gap` pass draws from (`structures/drawing/gaps.py`): a three-bar
    band only the middle bar traded through, at least `min_vol` of the volatility unit wide, and
    **dropped once later bars have filled it past half** - `gaps.OPEN_SHARE`. The fill is eaten
    from the side price arrives from, which is the top of an up-gap and the bottom of a down-gap.

    Reimplemented on ATR rather than called, because every threshold in this file is in ATR and
    mixing two volatility conventions is how `forecasting.md` lost two headline results. If an
    exact match to production is wanted, `prod_unit` is the other convention and is already here.

    The fill scan is bounded at `EXPIRE` bars: production only ever sees its own window (500 or
    1,500 bars), so a gap that has survived that long has left the question rather than answered
    it.
    """
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    n = len(df)
    out = []
    for k in range(2, n):
        A = a[k - 1]
        if not A > 0:
            continue
        up = l[k] - h[k - 2] > min_vol * A
        down = l[k - 2] - h[k] > min_vol * A
        if not (up or down):
            continue
        lo, hi = (h[k - 2], l[k]) if up else (h[k], l[k - 2])
        span = hi - lo
        rl, rh, dies = lo, hi, min(n, k + EXPIRE)
        for j in range(k + 1, dies):
            if up:
                rh = max(rl, min(rh, l[j]))
            else:
                rl = min(rh, max(rl, h[j]))
            if rh - rl < 0.5 * span:
                dies = j
                break
        out.append((k, dies, lo, hi))
    return out


def gap_marked(df: pd.DataFrame, a: np.ndarray, st: pd.DataFrame) -> np.ndarray:
    """True where production's `gap` pass would have been one of this zone's drawers.

    `gap-levels.md`: on 110,299 resolved production outcomes a level the `gap` pass helped draw
    held **56.6% against 68.4%**, and **-7.4 +- 1.4 points** after demeaning on instrument,
    interval and level age - five sigma, and the only pass identity that separated from the other
    six. That is a filter with a *negative* sign, which is the opposite of what `drawn_by_n` was
    expected to provide, and the opposite sign is why it is worth running here: if the journal's
    held-rate gap is real it should show up in R.

    The test mirrors how production acquires the attribution rather than guessing at it. `gaps`
    emits **the midpoint** of each open gap as a turning point, so `gap` becomes one of a level's
    drawers when an open gap's midpoint falls inside the level's band. So: at the trigger bar, is
    there a gap still open whose midpoint sits within this zone's band.

    Judged at the trigger bar and not at the zone's birth, deliberately - that is when the filter
    would be applied, and a gap that opens after the zone forms still marks it in production.
    """
    lo = np.minimum(st["zone_lo"].to_numpy(), st["zone_hi"].to_numpy())
    hi = np.maximum(st["zone_lo"].to_numpy(), st["zone_hi"].to_numpy())
    at = st["i"].to_numpy()
    spans = gap_open_spans(df, a)
    out = np.zeros(len(st), dtype=bool)
    if not spans:
        return out
    formed = np.array([s[0] for s in spans])
    dies = np.array([s[1] for s in spans])
    mid = np.array([(s[2] + s[3]) / 2.0 for s in spans])
    for r in range(len(st)):
        live = (formed <= at[r]) & (dies > at[r])
        if not live.any():
            continue
        m = mid[live]
        out[r] = bool(((m >= lo[r]) & (m <= hi[r])).any())
    return out


def bias_4h(d4: pd.DataFrame) -> np.ndarray:
    """+1 after the 4h closes above its last known swing high, -1 after it closes below its last
    swing low: the direction of the mother cycle's last break of structure."""
    h, l, c = (d4[k].to_numpy() for k in ("high", "low", "close"))
    ph, pl = P.pivots(h, l, LR, LR)
    hi, lo = P.last_known(ph, len(d4)), P.last_known(pl, len(d4))
    out, cur = np.zeros(len(d4), int), 0
    for i in range(len(d4)):
        if hi[i] and c[i] > hi[i][-1][1]:
            cur = 1
        elif lo[i] and c[i] < lo[i][-1][1]:
            cur = -1
        out[i] = cur
    return out


def extras(df: pd.DataFrame) -> dict:
    """What the second batch of confirmations reads: RSI, the volume's median, minor swing highs."""
    c = df["close"].to_numpy()
    d = np.r_[0.0, np.diff(c)]
    up = pd.Series(np.maximum(d, 0)).ewm(alpha=1 / 14, adjust=False).mean()
    dn = pd.Series(np.maximum(-d, 0)).ewm(alpha=1 / 14, adjust=False).mean()
    v = df["volume"].to_numpy(float) if "volume" in df else np.zeros(len(df))
    ph, pl = P.pivots(df["high"].to_numpy(), df["low"].to_numpy(), 2, 2)
    return dict(pl_at=np.array([x[1] for x in pl]), pl_px=np.array([x[2] for x in pl]),rsi=(100 - 100 / (1 + up / dn.replace(0, np.nan))).to_numpy(),
                vmed=pd.Series(v).shift(1).rolling(20).median().to_numpy(), vol=v,
                ph_known=np.array([x[0] for x in ph]), ph_at=np.array([x[1] for x in ph]),
                ph_px=np.array([x[2] for x in ph]))


def triggers(df: pd.DataFrame, a: np.ndarray, z: Zone, ex: dict | None = None) -> list[dict]:
    """Every trigger type's first firing in the zone's return window, in a long's terms (the
    caller flips a short's chart)."""
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    n, r, A = len(df), z.ret, a[z.p]
    ex = ex if ex is not None else extras(df)
    rsi, vol, vmed = ex["rsi"], ex["vol"], ex["vmed"]
    if r < 0:
        return []
    found, low_since = {}, l[r]
    found["touch"] = dict(i=r - 1, entry=z.hi, stop_px=z.lo - BUF * A, limit=1)
    # deeper resting entries (asked for with the levels): a buy below the near edge - at the zone's
    # middle, its far edge, and half an ATR past the middle - each resting through the window,
    # the stop always 0.6 ATR under the entry so R is the same size for every depth
    mid = (z.hi + z.lo) / 2
    for name, px in (("touch_mid", mid), ("touch_far", z.lo), ("touch_deep", mid - 0.5 * A)):
        found[name] = dict(i=r - 1, entry=px, stop_px=px - 0.6 * A, limit=1, expires=WINDOW)
    for j in range(r, min(n - 1, r + WINDOW)):
        low_since = min(low_since, l[j])
        if c[j] < z.lo - BUF * A:
            z.dead = j
            break
        if l[j] > z.hi + NEAR * A:  # left the zone: the window's reaction already happened
            break
        rng = max(h[j] - l[j], 1e-12)
        bd = abs(c[j] - o[j])
        stop_px = min(z.lo, low_since) - BUF * A
        pats = {
            "pin": (min(o[j], c[j]) - l[j] >= 0.6 * rng and bd <= rng / 3 and c[j] >= l[j] + 0.5 * rng
                    and rng >= 0.5 * a[j]),
            # the looser reading of the same confirmation: a medium-to-long lower wick, longer
            # than the body, closing in the upper half. Not required to be a green candle - a
            # hammer that closes red is still a rejection of the low - but it must close high
            # in its own range, which is the rejection claim itself.
            "wick": (min(o[j], c[j]) - l[j] >= WICK_MIN * rng and min(o[j], c[j]) - l[j] >= bd
                     and c[j] >= l[j] + 0.5 * rng and rng >= 0.5 * a[j]),
            "engulf": (j >= 1 and c[j] > o[j] and c[j - 1] < o[j - 1] and c[j] >= o[j - 1] and o[j] <= c[j - 1]
                       and bd >= abs(c[j - 1] - o[j - 1])),
            "star": (j >= 2 and c[j - 2] < o[j - 2] and abs(c[j - 1] - o[j - 1]) <= 0.3 * abs(c[j - 2] - o[j - 2])
                     and c[j] > o[j] and c[j] > (o[j - 2] + c[j - 2]) / 2),
            "inside": (j >= 2 and h[j - 1] <= h[j - 2] and l[j - 1] >= l[j - 2] and c[j] > h[j - 2]),
            "reclaim": j > r and c[j] > h[r:j].max(),
            # change in state of delivery: a close above the open of the run of down candles that
            # delivered price into the zone
            "cisd": c[j] > o[j] and _cisd(o, c, j),
            # the second batch
            "sweep": l[j] < z.lo and c[j] > z.lo and c[j] > o[j],
            "double": _double(l, h, c, r, j, A),
            "ifvg": _ifvg(l, h, c, r, j),
            "choch": _choch(ex, c, r, j),
            "rsi_div": _rsi_div(l, c, o, rsi, r, j),
            "displace": c[j] - o[j] >= a[j] and c[j] > z.hi,
            "tweezer": j >= 1 and c[j - 1] < o[j - 1] and c[j] > o[j] and abs(l[j] - l[j - 1]) <= 0.05 * a[j],
            "outside": j >= 1 and h[j] > h[j - 1] and l[j] < l[j - 1] and c[j] > h[j - 1],
            "climax": vmed[j] > 0 and vol[j] >= 2 * vmed[j] and c[j] >= l[j] + 0.5 * rng and c[j] > o[j],
        }
        for k, hit in pats.items():
            if hit and k not in found:
                found[k] = dict(i=j, entry=np.nan, stop_px=stop_px, limit=0)
    return [dict(trigger=k, **{"expires": 1, **v}) for k, v in found.items()]


def _double(l, h, c, r, j, A):
    """A second low at the first (within 0.15 ATR, none lower), then a close over the high between."""
    if j - r < 3:
        return False
    m = r + int(np.argmin(l[r:j]))
    return j - m >= 3 and l[m + 1:j + 1].min() >= l[m] - 0.15 * A and \
        l[m + 2:j + 1].min() <= l[m] + 0.15 * A and c[j] > h[m + 1:j].max()


def _ifvg(l, h, c, r, j):
    """A bearish gap left on the way in (bar k's high under bar k-2's low) closed through upward."""
    for k in range(max(2, r - 10), j):
        if h[k] < l[k - 2] and c[j] > l[k - 2] and c[j - 1] <= l[k - 2]:
            return True
    return False


def _choch(ex, c, r, j):
    """A close over the last minor (2-bar) swing high known by the bar, formed since the approach."""
    k = np.searchsorted(ex["ph_known"], j, side="right") - 1  # (known at p + 2, so known by j - 1)
    if k < 0 or ex["ph_at"][k] < r - 10 or ex["ph_known"][k] >= j:
        return False
    return c[j] > ex["ph_px"][k] and c[j - 1] <= ex["ph_px"][k]


def _rsi_div(l, c, o, rsi, r, j):
    """A lower low than the approach's lowest, with a higher RSI, on an up bar."""
    lo = max(0, r - 10)
    if j - lo < 3:
        return False
    m = lo + int(np.argmin(l[lo:j - 1]))
    return l[j] < l[m] and rsi[j] > rsi[m] + 3 and c[j] > o[j]


def _cisd(o, c, j):
    m = j - 1
    while m >= 0 and not c[m] < o[m]:
        m -= 1
    if m < 0 or j - m > 3:  # the down run must have just ended
        return False
    k = m
    while k - 1 >= 0 and c[k - 1] < o[k - 1]:
        k -= 1
    return c[j] > o[k]


def opposite_target(zs: list[Zone], z: Zone, i: int, ref: float) -> float:
    """The near edge of the nearest opposite zone live at bar i and not yet returned to, beyond
    the entry; else the swing extreme the leg made."""
    best = np.nan
    for y in zs:
        if y.side == z.side or y.live > i or (0 <= y.ret <= i):
            continue
        edge = y.hi
        if z.side * (edge - ref) > 0 and (np.isnan(best) or z.side * (edge - best) < 0):
            best = edge
    if np.isnan(best) and z.side * (z.leg_extreme - ref) > 0:
        best = z.leg_extreme
    return best


def setups(df: pd.DataFrame, a: np.ndarray, zs: list[Zone]) -> pd.DataFrame:
    rows = []
    c = df["close"].to_numpy()
    fl = flip(df)
    ex_l, ex_s = extras(df), extras(fl)
    for z in zs:
        if z.ret < 0:
            continue
        frame = df if z.side > 0 else fl
        # **By keyword, not by position.** This was positional, and adding
        # `push`, `push_hi`, `ob` and `line` to `Zone` between `clean` and `ret`
        # silently moved `z.ret` into `push`: every short zone arrived here with
        # `ret` at its default -1, the trigger search found nothing, and the
        # trade population came out **84% long** while the zones themselves were
        # 50/50. Keywords cannot drift when a field is added.
        zz = z if z.side > 0 else Zone(
            side=1, p=z.p, lo=-z.lo, hi=-z.hi, bos=z.bos, bos_level=-z.bos_level,
            fvg=z.fvg, live=z.live, leg_extreme=-z.leg_extreme, clean=z.clean,
            push=z.push, push_hi=z.push_hi, ob=z.ob, line=-z.line, ret=z.ret,
        )
        ex = ex_l if z.side > 0 else ex_s
        fc, fl_ = frame["close"].to_numpy(), frame["low"].to_numpy()
        r = z.ret
        # what the desk's example (NAS100 1h, 2026-06-22) showed: an old zone, a fast approach,
        # and the inner lows that formed after the break swept on the way in (inducement)
        age = r - z.live
        approach = (fc[max(r - 5, 0)] - fl_[r]) / a[r] if a[r] > 0 else np.nan
        inner = (ex["pl_at"] > z.bos) & (ex["pl_at"] < r) & (ex["pl_px"] > zz.hi)
        for t in triggers(frame, a, zz, ex):
            stop_px = t["stop_px"] * z.side
            entry = t["entry"] * z.side if np.isfinite(t["entry"]) else np.nan
            ref = entry if np.isfinite(entry) else c[t["i"]]
            rows.append(dict(i=t["i"], side=z.side, trigger=t["trigger"], entry=entry, limit=t["limit"],
                             expires=t["expires"],
                             stop_px=stop_px, target_px=(z.target if np.isfinite(z.target) and z.side * (z.target - ref) > 0
                                                         else opposite_target(zs, z, t["i"], ref)), zone_p=z.p,
                             zone_lo=z.lo, zone_hi=z.hi, zone_live=z.live, zone_ret=z.ret, clean=z.clean, push=z.push, push_hi=z.push_hi, ob=z.ob, age=age, approach=approach,
                             protected=z.protected, dax_major=z.major, has_sl=z.has_sl,
                             inducement=bool(inner.any()), n_gaps=len(z.parts)))
    return pd.DataFrame(rows)


def zones_fvg(df: pd.DataFrame, a: np.ndarray) -> list[Zone]:
    """Fair-value gaps as zones: a bullish gap (bar k's low above bar k-2's high by 0.2+ ATR) is a
    zone from that high (far edge) to that low (near edge), live once bar k closes; a bearish gap
    the mirror. `clean` when the bar that left it was a displacement: a 1-ATR body the gap's way."""
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    out = []
    for k in range(2, len(df)):
        A = a[k - 1]
        if not A > 0:
            continue
        for side in (1, -1):
            gap = (l[k] - h[k - 2]) if side > 0 else (l[k - 2] - h[k])
            if gap < FVG_MIN * A:
                continue
            far, near = (h[k - 2], l[k]) if side > 0 else (l[k - 2], h[k])
            body = side * (c[k - 1] - o[k - 1])
            z = Zone(side, k - 1, far, near, k, c[k], k, k, h[k] if side > 0 else l[k], bool(body >= A))
            for j in range(k + 1, min(len(df), k + EXPIRE)):
                if (l[j] <= near) if side > 0 else (h[j] >= near):
                    z.ret = j
                    break
            out.append(z)
    return out


LEVEL_HALF, LEVEL_AWAY, LEVEL_GAP_BARS, LEVEL_EXPIRE, LEVEL_BACK = 0.25, 1.0, 10, 500, 300


def _gaps(df: pd.DataFrame, a: np.ndarray) -> list[tuple[int, float, float]]:
    """Every fair-value gap of 0.2+ ATR, either direction: (bar it completed on, low, high)."""
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    out = []
    for k in range(2, len(df)):
        A = a[k - 1]
        if not A > 0:
            continue
        if l[k] - h[k - 2] >= FVG_MIN * A:
            out.append((k, h[k - 2], l[k]))
        elif l[k - 2] - h[k] >= FVG_MIN * A:
            out.append((k, h[k], l[k - 2]))
    return out


def _level_zone(df, a, k, level, parts, n_parts, start=None):
    """A horizontal level known at bar k as a zone: once price has gone 1 ATR away from it, the side
    it went decides whether the level is support (a long) or resistance (a short); the band is the
    level +-0.25 ATR; the first return to it is the one traded."""
    h, l, c = (df[x].to_numpy() for x in ("high", "low", "close"))
    A = a[k]
    if not A > 0:
        return None
    live = -1
    k0 = k if start is None else max(k, start)
    for j in range(k0 + 1, min(len(df), k0 + LEVEL_EXPIRE)):
        if abs(c[j] - level) >= LEVEL_AWAY * A:
            live = j
            break
    if live < 0:
        return None
    side = 1 if c[live] > level else -1
    near, far = level + side * LEVEL_HALF * A, level - side * LEVEL_HALF * A
    z = Zone(side, k, far, near, k, level, k, live, np.nan, n_parts >= 3, parts=tuple(parts))
    ext = c[live]
    for j in range(live + 1, min(len(df), live + LEVEL_EXPIRE)):
        if (l[j] <= near) if side > 0 else (h[j] >= near):
            z.ret = j
            break
        ext = max(ext, h[j]) if side > 0 else min(ext, l[j])
    z.leg_extreme = ext
    return z


def _proof(df, a, k, level, first):
    """The bar a level proved itself: from the first gap that made it on, the first touch after
    which price went LEVEL_BOUNCE ATR back the way it came before closing through the band (within
    48 bars). -1 if it never did within LEVEL_EXPIRE bars of being known."""
    h, l, c = (df[x].to_numpy() for x in ("high", "low", "close"))
    A, X = a[k], float(os.environ.get("LEVEL_BOUNCE", 1.0))
    lo, hi = level - LEVEL_HALF * A, level + LEVEL_HALF * A
    inside = False
    for j in range(max(first, 1), min(len(df), k + LEVEL_EXPIRE)):
        touch = l[j] <= hi and h[j] >= lo
        if touch and not inside:
            side = 1 if c[j - 1] > level else -1
            for m in range(j, min(len(df), j + 48)):
                if side * (c[m] - level) < -(LEVEL_HALF + BUF) * A:
                    break  # closed through: no bounce
                if side * ((h[m] if side > 0 else l[m]) - level) >= X * A:
                    return m
        inside = touch
    return -1


def zones_fvglevel(df: pd.DataFrame, a: np.ndarray, mode: str | None = None) -> list[Zone]:
    """Levels where fair-value gaps from different moves line up (the desk's idea, 2026-10-02).

    aligned   a new gap whose band overlaps (within 0.1 ATR) the band of an earlier gap 10 to 300
              bars older makes a level at the mean of their centres; later gaps there add to it
              (`clean` once three or more). Filled or not does not matter - a move made each one
    single    the null for alignment: a gap with no earlier gap at its height, as a level alone
    random    the null for the gaps: for each aligned level, a level as far from the close as it
              is, on a random side, known on the same bar
    proven    an aligned level that has already bounced: a touch after which price went
              LEVEL_BOUNCE (0.5 / 1 / 2) ATR back the way it came before closing through, any time
              from its first gap on; the trade is the next return after that bounce completed
    proven_random  the same proof asked of the random levels
    One level per price: a new one within 0.25 ATR of a level not yet returned to is merged into it.
    """
    mode = mode or os.environ.get("LEVELS", "aligned")
    gaps = _gaps(df, a)
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    rng = np.random.default_rng(len(df))
    made, out = [], []  # made: [level, known bar, parts]
    for n_, (k, lo, hi) in enumerate(gaps):
        A = a[k]
        partners = [g for g in gaps[:n_] if k - LEVEL_BACK <= g[0] <= k - LEVEL_GAP_BARS
                    and g[1] <= hi + 0.1 * A and g[2] >= lo - 0.1 * A]
        if mode in ("single",):
            if partners:
                continue
            level, parts = (lo + hi) / 2, [(k, lo, hi)]
        else:
            if not partners:
                continue
            parts = partners + [(k, lo, hi)]
            level = float(np.mean([(g[1] + g[2]) / 2 for g in parts]))
            if mode in ("random", "proven_random"):  # as far from price as the aligned level, random side
                ck = df["close"].iat[k]
                level, parts = ck + rng.choice((-1, 1)) * abs(level - ck), [(k, lo, hi)]
        if any(abs(level - m[0]) <= LEVEL_HALF * A and m[1] <= k for m in made if m[2] > k):
            continue  # already a live level here
        start = None
        if mode.startswith("proven"):
            start = _proof(df, a, k, level, min(p_[0] for p_ in parts) if mode == "proven" else k - LEVEL_BACK)
            if start < 0:
                continue
        z = _level_zone(df, a, k, level, parts, len(parts) if mode in ("aligned", "proven") else 0, start)
        if z is None:
            continue
        made.append((level, k, z.ret if z.ret >= 0 else z.live + LEVEL_EXPIRE))
        out.append(z)
    return out


# ------------------------------------------------------------------------------------- bjorgum

BJ_LEFT, BJ_RIGHT, BJ_KEEP, BJ_WIDTH, BJ_PCT = 20, 15, 4, 0.5, 0.025


def bjorgum_pivots(df: pd.DataFrame) -> list[tuple]:
    """Bjorgum key-level zones as the sage peer builds them, kept causal: pivots with 20 bars left
    and 15 right (known 15 bars later), each a zone of half-width min(0.5 x ATR30, 2.5% of price)
    about the pivot's high (resistance) or low (support). Plain candles, not Heikin-Ashi. Returns
    (known bar, pivot bar, bottom, top, resistance), in the order they became known."""
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    a30 = P.atr(df, 30)
    ph, pl = P.pivots(h, l, BJ_LEFT, BJ_RIGHT)
    out = []
    for piv, res in ((ph, True), (pl, False)):
        for known, p_, px in piv:
            if not a30[p_] > 0:
                continue
            half = min(BJ_WIDTH * a30[p_], BJ_PCT * abs(px))
            out.append((known, p_, px - half, px + half, res))
    return sorted(out)


def bjorgum_live(piv: list[tuple], i: int) -> list[tuple]:
    """The zones the indicator shows at bar i: pivots known by then, overlapping same-side zones
    merged newest first, the 4 newest per side kept. (bottom, top, resistance)."""
    known = [x for x in piv if x[0] <= i][-60:]
    kept: list[list] = []
    for _, _, lo, hi, res in sorted(known, key=lambda x: x[1], reverse=True):
        hit = next((k for k in kept if k[2] == res and lo <= k[1] and hi >= k[0]), None)
        if hit is not None:
            hit[0], hit[1] = min(hit[0], lo), max(hit[1], hi)
            continue
        kept.append([lo, hi, res])
    return [tuple(k) for k in [k for k in kept if k[2]][:BJ_KEEP] + [k for k in kept if not k[2]][:BJ_KEEP]]


def bjorgum_overlap(piv, i: int, lo: float, hi: float, pad: float = 0.0) -> bool:
    """Whether any Bjorgum zone shown at bar i overlaps [lo, hi] (either role: a level is a level)."""
    return any(b_hi >= lo - pad and b_lo <= hi + pad for b_lo, b_hi, _ in bjorgum_live(piv, i))


def zones_bjorgum(df: pd.DataFrame, a: np.ndarray) -> list[Zone]:
    """Bjorgum's zones traded alone: each, once known and once price has gone 1 ATR away, is
    support or resistance by the side price went; its own band; the first return is traded. A zone
    overlapping one not yet returned to is skipped (the indicator merges them)."""
    out, made = [], []
    h, l, c = (df[x].to_numpy() for x in ("high", "low", "close"))
    for known, p_, lo, hi, res in bjorgum_pivots(df):
        if any(m_lo <= hi and m_hi >= lo and m_known <= known < m_end for m_lo, m_hi, m_known, m_end in made):
            continue
        A = a[known] if known < len(df) else np.nan
        if not A > 0:
            continue
        level = (lo + hi) / 2
        live = next((j for j in range(known + 1, min(len(df), known + LEVEL_EXPIRE))
                     if abs(c[j] - level) >= LEVEL_AWAY * A), -1)
        if live < 0:
            continue
        side = 1 if c[live] > level else -1
        near, far = (hi, lo) if side > 0 else (lo, hi)
        z = Zone(side, p_, far, near, known, level, p_, live, np.nan, False, parts=((p_, lo, hi),))
        ext = c[live]
        for j in range(live + 1, min(len(df), live + LEVEL_EXPIRE)):
            if (l[j] <= near) if side > 0 else (h[j] >= near):
                z.ret = j
                break
            ext = max(ext, h[j]) if side > 0 else min(ext, l[j])
        z.leg_extreme = ext
        made.append((lo, hi, known, z.ret if z.ret >= 0 else live + LEVEL_EXPIRE))
        out.append(z)
    return out


def zma_series(df: pd.DataFrame) -> pd.DataFrame:
    """Production's Z-Momentum Attention (`structures/zma.py`) replayed over the closes, bar by bar:
    each bar's z-score, its strong threshold, `agrees` (+1 oversold and rising, -1 overbought and
    falling) and `stretched` (+1 oversold, -1 overbought)."""
    from till_infinity.structures.zma import Zma
    z = Zma()
    rows = []
    for px in df["close"].to_numpy():
        z.observe(float(px))
        rows.append((z.z_score, z.strong, z.agrees, z.stretched))
    return pd.DataFrame(rows, columns=["z", "strong", "agrees", "stretched"])


REV_ATR = 1.0  # how far price must fall back from the post-break high for it to count as a reversal


def zones_rejection(df: pd.DataFrame, a: np.ndarray) -> list[Zone]:
    """The desk's rejection trade (2026-10-03): price breaks structure up, makes a high, and reverses;
    the high that rejected it is a zone to sell on the pullback, back down to the broken level.

    For a bullish break (a bearish one is the mirror): a swing low p, the first close above the last
    swing high L known at p within 20 bars, before any trade under p (the break, at b); then the
    first 3/3 swing high R after b and above L; the reversal - a close 1 ATR under R's high. The zone
    is R's bar from its body bottom (the near edge, where a resting sell sits) to its high (the far
    edge); its target is L. Live once R is confirmed and the reversal has happened; first return only.
    """
    out = []
    for side, frame in ((1, df), (-1, flip(df))):
        o, h, l, c = (frame[k].to_numpy() for k in ("open", "high", "low", "close"))
        n = len(frame)
        ph, pl = P.pivots(h, l, LR, LR)
        ph_known = np.array([x[0] for x in ph])
        for known, p, low in pl:
            if not a[p] > 0:
                continue
            j = np.searchsorted(ph_known, p, side="right") - 1
            if j < 0 or ph[j][2] <= low:
                continue
            level = ph[j][2]
            b = -1
            for k in range(p + 1, min(n, p + 21)):
                if l[k] < low:
                    break
                if c[k] > level:
                    b = k
                    break
            if b < 0:
                continue
            nxt = [x for x in ph if x[1] > b and x[2] > level]
            if not nxt:
                continue
            r_known, r, r_hi = nxt[0]
            A = a[r]
            if not A > 0:
                continue
            rev = next((k for k in range(r + 1, min(n, r + 60)) if c[k] <= r_hi - REV_ATR * A), -1)
            if rev < 0:
                continue
            near = min(o[r], c[r])
            near = max(min(near, r_hi - 0.2 * A), r_hi - 1.5 * A)
            if not near > level:
                continue
            live = max(r_known, rev)
            # in this (long-terms) chart the trade is a sell: far edge the high, near edge the body bottom
            far_px, near_px, tgt = (r_hi, near, level) if side > 0 else (-r_hi, -near, -level)
            z = Zone(-side, r, far_px, near_px, b, tgt, r, live, tgt, False, target=tgt)
            for k in range(live + 1, min(n, live + EXPIRE)):
                if h[k] >= near:
                    z.ret = k
                    break
            out.append(z)
    return out


if os.environ.get("ZONES") == "prod":  # every mode below on production's origins instead
    zones = zones_prod  # noqa: F811
elif os.environ.get("ZONES") == "fvg":  # or on fair-value gaps
    zones = zones_fvg  # noqa: F811
elif os.environ.get("ZONES") == "bjorgum":  # or on Bjorgum's key-level zones alone
    zones = zones_bjorgum  # noqa: F811
elif os.environ.get("ZONES") == "rejection":  # or on the post-break rejection high, traded back to the break
    zones = zones_rejection  # noqa: F811
elif os.environ.get("ZONES") == "fvglevel":  # or on levels where gaps line up (LEVELS=aligned|single|random)
    zones = zones_fvglevel  # noqa: F811
elif os.environ.get("ZONES") == "ob":  # or on the order block: the last candle against the move
    zones = zones_ob  # noqa: F811


# ------------------------------------------------------------------------------------------ plot

def plot():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    import run as R
    R.DB = os.environ.get("MT5BT_DB")
    picks = [("EURUSD", "1h"), ("XAUUSD", "4h"), ("US SP 500", "1d"), ("GBPJPY", "1h"), ("BTCUSD", "4h"),
             ("US Tech 100", "1h")]
    OUT.mkdir(parents=True, exist_ok=True)
    for sym, iv in picks:
        df = R.load(sym, iv)
        if df is None:
            continue
        df = df.reset_index(drop=True)
        a = P.atr(df, 14)
        zs = zones(df, a)
        st = setups(df, a, zs)
        st = st[st["trigger"].isin(["pin", "engulf", "reclaim", "cisd"])]
        if st.empty:
            continue
        rng = np.random.default_rng(zlib.crc32(sym.encode()))
        pick = st.iloc[np.sort(rng.choice(len(st), min(4, len(st)), replace=False))]
        fig, axes = plt.subplots(2, 2, figsize=(18, 11))
        for ax, (_, s) in zip(axes.flat, pick.iterrows(), strict=False):
            z = next(z for z in zs if z.p == s.zone_p and z.side == s.side)
            i0, i1 = max(0, z.p - 40), min(len(df) - 1, int(s.i) + 40)
            w = df.iloc[i0:i1 + 1]
            x = np.arange(i0, i1 + 1)
            up = w["close"] >= w["open"]
            ax.vlines(x, w["low"], w["high"], color="#555", lw=0.6)
            ax.bar(x[up], (w["close"] - w["open"])[up], bottom=w["open"][up], color="#2a9d8f", width=0.7)
            ax.bar(x[~up], (w["close"] - w["open"])[~up], bottom=w["open"][~up], color="#e76f51", width=0.7)
            lo, hi = min(z.lo, z.hi), max(z.lo, z.hi)
            ax.add_patch(Rectangle((z.p - 0.4, lo), int(s.i) - z.p + 0.8, hi - lo, color="#457b9d", alpha=0.25))
            h_, l_ = df["high"].to_numpy(), df["low"].to_numpy()
            g = z.fvg  # the gap: between bar g-2's high and bar g's low (a short's mirrored)
            if g != z.p:  # zones without a gap (the rejection trade) carry fvg = p
                g_lo, g_hi = (h_[g - 2], l_[g]) if z.side > 0 else (h_[g], l_[g - 2])
                ax.add_patch(Rectangle((g - 2, g_lo), 2, g_hi - g_lo, color="#f4a261", alpha=0.5))
            ax.hlines(z.bos_level, z.bos - 15, z.bos, colors="k", linestyles="--", lw=1)
            ax.annotate("BOS", (z.bos, z.bos_level), fontsize=8)
            ax.axvline(z.ret, color="#999", lw=0.6, ls=":")
            ent = s.entry if np.isfinite(s.entry) else df["open"].iat[int(s.i) + 1]
            ax.scatter([s.i + (0 if s.limit else 1)], [ent], marker="^" if s.side > 0 else "v", s=120,
                       color="green" if s.side > 0 else "red", zorder=5)
            ax.hlines(s.stop_px, s.i, i1, colors="red", lw=1)
            if np.isfinite(s.target_px):
                ax.hlines(s.target_px, s.i, i1, colors="green", lw=1)
            ax.set_title(f"{sym} {iv}  {'long' if s.side > 0 else 'short'}  trigger={s.trigger}  "
                         f"{pd.Timestamp(df['ts'].iat[int(s.i)], unit='s'):%Y-%m-%d %H:%M}", fontsize=10)
        fig.suptitle("blue: origin zone (to the trigger)   orange: fair-value gap   dashed: structure broken   "
                     "dotted: first return   red/green: stop / opposite-zone target", fontsize=11)
        fig.tight_layout()
        fig.savefig(OUT / f"zones_{sym.replace(' ', '_')}_{iv}.png", dpi=80)
        plt.close(fig)
        print(f"  {sym} {iv}: {len(zs)} zones, {sum(z.ret >= 0 for z in zs)} returned, {len(st)} setups", flush=True)


# ------------------------------------------------------------------------------------------- run

EXITS = ("opp", "t4", "t10", "trail")
HOLD_DAYS = float(os.environ.get("HOLD_DAYS", 5))  # the desk holds 3-5 days at most


def nested(df, d4, a4, zs4, st):
    """For each setup, whether its entry sits in a live 4h zone of the same side: live by the 1h
    bar's close and not closed through before it."""
    if st.empty:
        return np.zeros(0, bool)
    ts = df["ts"].to_numpy()
    c4 = d4["close"].to_numpy()
    k4 = P.htf_index(ts, SEC["1h"], d4["ts"].to_numpy(), SEC["4h"])
    lo_px, hi_px = df["low"].to_numpy(), df["high"].to_numpy()
    out = np.zeros(len(st), bool)
    for n_, s in enumerate(st.itertuples()):
        k = k4[s.i]
        if k < 0:
            continue
        px = lo_px[s.i] if s.side > 0 else hi_px[s.i]
        for z in zs4:
            if z.side != s.side or z.live > k:
                continue
            lo, hi = min(z.lo, z.hi), max(z.lo, z.hi)
            pad = NEAR * a4[z.p]
            if not (lo - pad <= px <= hi + pad):
                continue
            broken = c4[z.live:k + 1] < lo - BUF * a4[z.p] if z.side > 0 else c4[z.live:k + 1] > hi + BUF * a4[z.p]
            if not broken.any():
                out[n_] = True
                break
    return out


LTF_KINDS = ("cisd", "choch", "cisd_z")
LTFS = {"1h": ("30m", "15m"), "4h": ("1h", "30m", "15m"), "1d": ("1h", "30m", "15m")}
SEC.update({"15m": 900, "30m": 1800})
LTF_TRIGGERS = tuple(f"{k}@{t}" for t in ("1h", "30m", "15m") for k in LTF_KINDS)


def ltf_book(sym, ltf):
    """The confirmation timeframe's book: the broker's 1h or 15m bars, or 30m built from the 15m."""
    from mt5bt import Book
    from survivors import book_for
    if ltf != "30m":
        return book_for(sym, ltf)
    got = book_for(sym, "15m")
    if got is None:
        return None
    b, costs, ms = got
    d = b.bars.copy()
    d["k"] = d["ts"] // 1800 * 1800
    d30 = d.groupby("k").agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                             close=("close", "last"), volume=("volume", "sum"), spread=("spread", "min"))
    d30 = d30.reset_index().rename(columns={"k": "ts"})
    return Book(sym, d30, b.spec, "30m", feed=sym.lower()), costs, ms


def ltf_setups(dh: pd.DataFrame, ah: np.ndarray, zs: list[Zone], d1: pd.DataFrame, a1: np.ndarray,
               sec: int, ltf: str = "1h") -> pd.DataFrame:
    """A 4h or 1d zone's return confirmed on the 1h: from the first 1h bar that reaches the zone,
    within the zone's return window, a 1h CISD or CHoCH. The early entry the higher bar's close
    makes late. Stop: under the reaction's low since the touch (tight), or past the zone (`_z`)."""
    t1 = d1["ts"].to_numpy()
    th = dh["ts"].to_numpy()
    rows = []
    fl1 = flip(d1)
    ex1 = (extras(d1), extras(fl1))
    for z in zs:
        if z.ret < 0:
            continue
        frame, ex = (d1, ex1[0]) if z.side > 0 else (fl1, ex1[1])
        o, h, l, c = (frame[k].to_numpy() for k in ("open", "high", "low", "close"))
        lo, hi = (z.lo, z.hi) if z.side > 0 else (-z.lo, -z.hi)
        A = ah[z.p]
        j0 = int(np.searchsorted(t1, th[z.ret], side="left"))
        j1 = int(np.searchsorted(t1, th[min(z.ret + WINDOW, len(th) - 1)] + sec, side="left"))
        touch, low_since, found = -1, np.inf, {}
        for j in range(j0, min(j1, len(d1) - 1)):
            if touch < 0:
                if l[j] <= hi:
                    touch = j
                else:
                    continue
            low_since = min(low_since, l[j])
            if c[j] < lo - BUF * A:
                break
            if l[j] > hi + NEAR * A and j > touch + 2:
                break
            tight = low_since - BUF * a1[j]
            if "cisd" not in found and c[j] > o[j] and _cisd(o, c, j):
                found["cisd"] = tight
                found["cisd_z"] = min(lo, low_since) - BUF * A
                rows += [dict(i=j, side=z.side, trigger=f"{k}@{ltf}", entry=np.nan, limit=0, stop_px=found[k] * z.side,
                              zone_p=z.p, clean=z.clean, push=z.push, push_hi=z.push_hi, ob=z.ob) for k in ("cisd", "cisd_z")]
            if "choch" not in found and j > touch and _choch(ex, c, touch, j):
                found["choch"] = tight
                rows.append(dict(i=j, side=z.side, trigger=f"choch@{ltf}", entry=np.nan, limit=0,
                                 stop_px=tight * z.side, zone_p=z.p, clean=z.clean, push=z.push, push_hi=z.push_hi, ob=z.ob))
            if len(found) == 3:
                break
    st = pd.DataFrame(rows)
    if st.empty:
        return st
    c1 = d1["close"].to_numpy()
    k = np.searchsorted(th + sec, t1[st["i"].to_numpy()] + SEC[ltf], side="right") - 1  # the HTF bar closed by then
    st["target_px"] = [opposite_target(zs, next(z for z in zs if z.p == p_ and z.side == sd), max(kk, 0), c1[i])
                       for p_, sd, kk, i in zip(st["zone_p"], st["side"], k, st["i"], strict=True)]
    return st


def _trade_all(sym, iv, book, costs, min_stop, df, a, st, filters, trigs, sec):
    import run as R
    from survivors import random_time
    out = []
    for trig in trigs:
        for flt in filters:
            raw = st[st["trigger"] == trig]
            if flt != "none":
                raw = raw[raw[flt]]
            if raw.empty:
                continue
            raw = raw.assign(expires=raw["expires"] if "expires" in raw else 1, tag="",
                             hold=max(1, int(HOLD_DAYS * 86400 / sec)))
            sid_of = raw.drop_duplicates("i").set_index("i")["sid"]
            for exit_ in EXITS:
                sig = R.to_mt5(raw, df, a, "src" if exit_ == "opp" else ("trail" if exit_ == "trail" else exit_), min_stop)
                if sig.empty:
                    continue
                t = R.trade(book, sig, costs)
                if t.empty:
                    continue
                ts = df["ts"].to_numpy()
                mult = int(exit_[1:]) if exit_[1:].isdigit() else 0
                trail = R.TRAIL_ATR * a[np.clip(np.searchsorted(ts, t["entry_ts"].to_numpy(), side="right") - 2, 0, None)] \
                    if exit_ == "trail" else 0.0
                tgt = t["stop_d"] * mult if mult else (t["target_d"] if "target_d" in t and exit_ == "opp" else 0.0)
                seed = zlib.crc32(f"{sym}{iv}{trig}{flt}{exit_}".encode())
                ct = R.trade(book, R.coin(book, t.assign(target_d=tgt, trail_d=trail), a, seed), costs)
                rt = R.trade(book, random_time(sig, df, a, np.random.default_rng(seed + 1)), costs)
                mk = t.assign(target_d=tgt, trail_d=trail)
                ft = R.trade(book, at_market(book, mk, a, flip=True), costs)
                st_ = R.trade(book, at_market(book, mk, a, flip=False), costs)
                for kind, x in (("real", t), ("coin", ct), ("random_time", rt),
                                ("flip", ft), ("straight", st_)):
                    if x.empty:
                        continue
                    out.append(pd.DataFrame({"kind": kind, "sym": sym, "family": R.FAMILY.get(sym, "?"), "iv": iv,
                                             "trigger": trig, "filter": flt, "exit": exit_, "R": x["R"].to_numpy(),
                                             "side": x["side"].to_numpy(), "entry_ts": x["entry_ts"].to_numpy(),
                                             "sid": sid_of.reindex(x["signal_bar"]).to_numpy() if kind == "real" else ""}))
    return out


def at_market(book, t, a, flip: bool):
    """The same fills, stop and exit, entered **at market** - `flip` reverses the side.

    Both arms exist because `R.coin` enters at market while a real zone trade
    enters on a limit at the zone, so "real against flip" would mix two changes:
    the side and the entry. `straight` is the same side at market, and is the
    only honest comparison for `flip`.
    """
    import run as R

    ts = book.bars["ts"].to_numpy()
    j = np.searchsorted(ts, t["entry_ts"].to_numpy(), side="right") - 1
    side = t["side"].to_numpy()
    return pd.DataFrame({
        "i": np.maximum(j - 1, 0), "side": -side if flip else side,
        "stop": t["stop_d"].to_numpy(), "target": t.get("target_d", 0.0),
        "hold": R.MAXHOLD, "trail": t.get("trail_d", 0.0), "entry": np.nan,
        "limit": 0, "expires": 1, "tag": t["tag"].to_numpy(),
    })


def flipped(book, t, a):
    """The same fills, the same stop and exit, the **opposite side**.

    `R.coin` is this with a random side; the flip is deterministic. It is the
    test `walks-and-edge.md` names for a result that sits *below* its walk:

        Real below walk: the market punishes the chart reader's view ... The
        opposite trade then becomes its own frozen test.

    `origin-zones.md` flipped its zones and found -0.24 to -0.80 everywhere, but
    those were pivot-low origins - of which only 22% are order blocks - so this
    is a different population and the question is open again.
    """
    import run as R

    ts = book.bars["ts"].to_numpy()
    j = np.searchsorted(ts, t["entry_ts"].to_numpy(), side="right") - 1
    return pd.DataFrame({
        "i": np.maximum(j - 1, 0), "side": -t["side"].to_numpy(),
        "stop": t["stop_d"].to_numpy(), "target": t.get("target_d", 0.0),
        "hold": R.MAXHOLD, "trail": t.get("trail_d", 0.0), "entry": np.nan,
        "limit": 0, "expires": 1, "tag": t["tag"].to_numpy(),
    })


def run_one(job):
    import run as R
    import survivors
    from survivors import book_for
    sym, iv = job
    R.DB = survivors.DB = os.environ.get("MT5BT_DB")
    got = book_for(sym, iv)
    d4 = R.load(sym, "4h")
    if got is None or d4 is None:
        return []
    book, costs, min_stop = got
    df = book.bars.reset_index(drop=True)
    d4 = d4.reset_index(drop=True)
    a = P.atr(df, 14)
    zs = zones(df, a)
    st = setups(df, a, zs)
    if st.empty:
        return []
    k4 = P.htf_index(df["ts"].to_numpy(), SEC[iv], d4["ts"].to_numpy(), SEC["4h"])
    b4 = bias_4h(d4)
    st["bias"] = np.where(k4[st["i"].to_numpy()] >= 0, b4[np.maximum(k4[st["i"].to_numpy()], 0)], 0) == st["side"]
    if iv == "1h":
        a4 = P.atr(d4, 14)
        st["nest"] = st["bias"] & nested(df, d4, a4, zones(d4, a4), st)
    st["strong"] = st["bias"] & st["clean"]
    # Asked for 2026-10-07, frozen before the run: two consecutive candles
    # leaving the zone, each making progress on the last. `push` is close past
    # the previous close, `push_hi` close past its whole range - the desk
    # expects the second to be the better one, which is itself a prediction.
    # `push_ob` adds the origin being the last candle against the move with a
    # real body. Kept apart so the run says which part, if any, carries it.
    st["push"] = st["bias"] & st["push"]
    st["push_hi"] = st["bias"] & st["push_hi"]
    st["push_ob"] = st["push_hi"] & st["ob"]
    # SMC: the 4h dealing range (last known 4h swing high and low) - longs from its discount half,
    # shorts from its premium; London (02-05 New York) and New York (07-10) killzones
    h4, l4 = d4["high"].to_numpy(), d4["low"].to_numpy()
    ph4, pl4 = P.pivots(h4, l4, LR, LR)
    hi4, lo4 = P.last_known(ph4, len(d4)), P.last_known(pl4, len(d4))
    kk = np.maximum(k4[st["i"].to_numpy()], 0)
    mid = np.array([(hi4[k][-1][1] + lo4[k][-1][1]) / 2 if hi4[k] and lo4[k] else np.nan for k in kk])
    ref = np.where(np.isfinite(st["entry"]), st["entry"], df["close"].to_numpy()[st["i"].to_numpy()])
    st["discount"] = np.where(st["side"] > 0, ref < mid, ref > mid)
    hr = P.ny_hour(df["ts"].to_numpy()[st["i"].to_numpy()] + SEC[iv])  # the trigger bar's close
    st["killzone"] = ((hr >= 2) & (hr < 5)) | ((hr >= 7) & (hr < 10))
    st["smc_pd"] = st["bias"] & st["discount"]
    st["smc_idm"] = st["bias"] & st["inducement"]
    st["smc_all"] = st["bias"] & st["discount"] & st["inducement"] & (st["killzone"] if iv == "1h" else True)
    st["fast_old"] = st["bias"] & (st["approach"] >= 3) & (st["age"] >= 50)
    # `gap-levels.md`: production levels the `gap` pass helped draw held 7.4 points worse, five
    # sigma. Both arms are run, because a filter whose two halves are not reported is a filter
    # nobody can check - and under ZONES=fvg the zone *is* a gap, so `hasgap` is close to
    # everything and `nogap` close to nothing, which is the expected degenerate case and not a
    # fault.
    st["marked"] = gap_marked(df, a, st)
    st["nogap"] = st["bias"] & ~st["marked"]
    st["hasgap"] = st["bias"] & st["marked"]
    # the DAX tests on the origin (research zones): protected and not inducement; and the major break
    st["dax"] = st["bias"] & st["protected"] & st["has_sl"]
    st["dax_major"] = st["dax"] & st["dax_major"]
    # Bjorgum alignment: the zone overlaps a Bjorgum zone shown at the trigger bar
    piv = bjorgum_pivots(df)
    st["bj"] = [bjorgum_overlap(piv, int(r.i), min(r.zone_lo, r.zone_hi), max(r.zone_lo, r.zone_hi))
                for r in st.itertuples()]
    st["bjorg"] = st["bias"] & st["bj"]
    st["bjorg_strong"] = st["strong"] & st["bj"]
    st["bjorg_dax"] = st["dax"] & st["bj"]
    # ZMA at the trigger bar: displacement and momentum agreeing with the zone, or displacement alone
    zm = zma_series(df)
    ii = st["i"].to_numpy()
    st["zma_ag"] = zm["agrees"].to_numpy()[ii] == st["side"].to_numpy()
    st["zma_st"] = zm["stretched"].to_numpy()[ii] == st["side"].to_numpy()
    st["zma"] = st["bias"] & st["zma_ag"]
    st["zma_stretch"] = st["bias"] & st["zma_st"]
    st["zma_bjorg"] = st["zma_stretch"] & st["bj"]
    st["zma_strong"] = st["strong"] & st["zma_st"]
    filters = ["none", "bias", "strong", "push", "push_hi", "push_ob",
               "smc_pd", "smc_idm", "smc_all", "fast_old",
               "nogap", "hasgap", "dax", "dax_major", "bjorg", "bjorg_strong", "bjorg_dax",
               "zma", "zma_stretch", "zma_bjorg", "zma_strong"] + \
        (["nest", "smc_kz"] if iv == "1h" else [])
    if iv == "1h":
        st["smc_kz"] = st["bias"] & st["killzone"]
    st["sid"] = [f"{sym}|{iv}|{k}" for k in range(len(st))]
    feats = st.assign(sym=sym, iv=iv, ts=df["ts"].to_numpy()[st["i"].to_numpy()])
    trigs = [t for t in os.environ.get("TRIGGERS", ",".join(TRIGGERS + LTF_TRIGGERS)).split(",") if t in TRIGGERS]
    out = _trade_all(sym, iv, book, costs, min_stop, df, a, st, filters, trigs, SEC[iv])
    wanted = [t for t in os.environ.get("TRIGGERS", ",".join(LTF_TRIGGERS)).split(",") if t in LTF_TRIGGERS]
    for lt_iv in LTFS[iv]:
        trig_here = [t for t in wanted if t.endswith("@" + lt_iv)]
        got1 = ltf_book(sym, lt_iv) if trig_here else None
        if got1 is None:
            continue
        b1, c1, ms1 = got1
        d1 = b1.bars.reset_index(drop=True)
        a1 = P.atr(d1, 14)
        lt = ltf_setups(df, a, zs, d1, a1, SEC[iv], lt_iv)
        if lt.empty:
            continue
        k4l = P.htf_index(d1["ts"].to_numpy(), SEC[lt_iv], d4["ts"].to_numpy(), SEC["4h"])
        lt["bias"] = b4[np.maximum(k4l[lt["i"].to_numpy()], 0)] == lt["side"]
        lt["strong"] = lt["bias"] & lt["clean"]
        lt["push"] = lt["bias"] & lt["push"]
        lt["push_hi"] = lt["bias"] & lt["push_hi"]
        lt["push_ob"] = lt["push_hi"] & lt["ob"]
        lt["sid"] = [f"{sym}|{iv}>{lt_iv}|{k}" for k in range(len(lt))]
        out += _trade_all(sym, iv, b1, c1, ms1, d1, a1, lt, ["none", "bias", "strong", "push", "push_hi", "push_ob"], trig_here,
                          SEC[lt_iv])
    print(f"  {sym} {iv}: {len(zs)} zones, {len(st)} setups", flush=True)
    return out + [feats.assign(kind="setup")]


def run(one=None, primary=("pin", "bias", "opp"), show="bias"):
    import run as R
    from score import JUMPY, boot_p
    syms = os.environ.get("SYMBOLS")
    syms = syms.split(",") if syms else [s for s in R.FAMILY if s not in R.FRESH]
    ivs = os.environ.get("INTERVALS", "1h,4h,1d").split(",")
    jobs = [(s, iv) for iv in ivs for s in syms]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 20))) as pool:
        parts = [p for got in pool.map(one or run_one, jobs) for p in got]
    pd.concat([p for p in parts if (p["kind"] == "setup").all()], ignore_index=True).to_pickle(OUT / "setups.pkl.gz")
    df = pd.concat([p for p in parts if not (p["kind"] == "setup").all()], ignore_index=True)
    df.loc[(df["family"] == "deriv") & df["sym"].str.startswith(JUMPY), "family"] = "deriv_jump"
    df["day"] = (df["entry_ts"] // 86400).astype(int)
    df.to_pickle(OUT / "zone_trades.pkl.gz")
    rng = np.random.default_rng(7)
    rows = []
    real_fam = ~df["family"].str.startswith("deriv")
    for scope, sub in (("real markets", df[real_fam]), *((f, g) for f, g in df.groupby("family"))):
        for (iv, trig, flt, exit_), g in sub.groupby(["iv", "trigger", "filter", "exit"]):
            r, c, n_ = (g[g["kind"] == k] for k in ("real", "coin", "random_time"))
            if len(r) < 30:
                continue
            mid = r["entry_ts"].median()
            rows.append(dict(scope=scope, iv=iv, trigger=trig, filter=flt, exit=exit_, n=len(r), R=r["R"].mean(),
                             coin_R=c["R"].mean(), random_time_R=n_["R"].mean(),
                             first=r.loc[r["entry_ts"] < mid, "R"].mean(), second=r.loc[r["entry_ts"] >= mid, "R"].mean(),
                             win=(r["R"] > 0).mean(), p4=(r["R"] >= 4).mean(), p10=(r["R"] >= 10).mean(),
                             long_share=(r["side"] > 0).mean(),
                             # 200 draws resolve p no finer than 1/201: a 0 is "below that", not
                             # zero, and read as zero it passed tiny cells through BH unearned
                             p_coin=max(boot_p(r, c, rng, 200), 1 / 201) if len(c) >= 30 else np.nan,
                             p_rt=max(boot_p(r, n_, rng, 200), 1 / 201) if len(n_) >= 30 else np.nan))
    cells = pd.DataFrame(rows)
    if cells.empty:
        # A setting strict enough to leave no cell with 30 trades is a result -
        # the rule is too rare to measure - and not a crash. The trades are
        # already on disk above, so a sweep can still read what there was.
        print("\nno cell reached 30 trades; nothing to score")
        pd.DataFrame(columns=["scope", "iv", "trigger", "filter", "exit", "n", "R"]).to_csv(
            OUT / "zones.csv", index=False)
        return
    # Benjamini-Hochberg over every cell, on the weaker of the two nulls
    pmax = cells[["p_coin", "p_rt"]].fillna(1.0).max(axis=1).to_numpy()  # a null too thin to test fails
    order = np.argsort(pmax)
    m = len(pmax)
    q = np.empty(m)
    q[order] = np.minimum.accumulate((pmax[order] * m / np.arange(1, m + 1))[::-1])[::-1]
    cells["q"] = q
    cells["passes"] = ((cells["first"] > 0) & (cells["second"] > 0) & (cells["R"] > cells["coin_R"])
                       & (cells["R"] > cells["random_time_R"]) & (cells["q"] < 0.10)
                       & ~cells["scope"].eq("deriv_jump"))
    cells.to_csv(OUT / "zones.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 400)
    rm = cells[cells["scope"] == "real markets"]
    print(f"\nreal markets, R by trigger x exit ({show} filter):")
    for iv in ivs:
        g = rm[(rm["iv"] == iv) & (rm["filter"] == show)]
        print(f"\n{iv}\n" + g.pivot_table(index="trigger", columns="exit", values="R").round(3).to_string())
    print(f"\nprimary {primary}:")
    print(cells[(cells["trigger"] == primary[0]) & (cells["filter"] == primary[1])
                & (cells["exit"] == primary[2])].round(3).to_string(index=False))
    print("\npassing cells:")
    print(cells[cells["passes"]].round(3).to_string(index=False))


def gallery():
    """Four setups of each trigger (strong leg, 4h bias) from across the real markets, each drawn
    with the 60 bars after, so the eye can judge what each confirmation looks like and does."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    import run as R
    R.DB = os.environ.get("MT5BT_DB")
    pool = []
    for sym in ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "XAGUSD", "US SP 500", "US Tech 100", "Germany 40",
                "US Oil", "BTCUSD", "ETHUSD", "GBPJPY"):
        for iv in ("1h", "4h"):
            df, d4 = R.load(sym, iv), R.load(sym, "4h")
            if df is None or d4 is None:
                continue
            df, d4 = df.reset_index(drop=True), d4.reset_index(drop=True)
            a = P.atr(df, 14)
            zs = zones(df, a)
            st = setups(df, a, zs)
            if st.empty:
                continue
            k4 = P.htf_index(df["ts"].to_numpy(), SEC[iv], d4["ts"].to_numpy(), SEC["4h"])
            b4 = bias_4h(d4)
            st = st[st["clean"] & (b4[np.maximum(k4[st["i"].to_numpy()], 0)] == st["side"])]
            pool.append((sym, iv, df, a, zs, st))
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(1)
    for trig in TRIGGERS:
        cands = [(n_, k) for n_, (_, _, _, _, _, st) in enumerate(pool) for k in np.flatnonzero(st["trigger"].to_numpy() == trig)]
        if not cands:
            continue
        fig, axes = plt.subplots(2, 2, figsize=(18, 11))
        for ax, ci in zip(axes.flat, rng.choice(len(cands), min(4, len(cands)), replace=False), strict=False):
            n_, k = cands[ci]
            sym, iv, df, a, zs, st = pool[n_]
            s = st.iloc[k]
            z = next(z for z in zs if z.p == s.zone_p and z.side == s.side)
            i0, i1 = max(0, z.p - 30), min(len(df) - 1, int(s.i) + 60)
            w = df.iloc[i0:i1 + 1]
            x = np.arange(i0, i1 + 1)
            up = (w["close"] >= w["open"]).to_numpy()
            ax.vlines(x, w["low"], w["high"], color="#555", lw=0.6)
            ax.bar(x[up], (w["close"] - w["open"])[up], bottom=w["open"][up], color="#2a9d8f", width=0.7)
            ax.bar(x[~up], (w["close"] - w["open"])[~up], bottom=w["open"][~up], color="#e76f51", width=0.7)
            lo, hi = min(z.lo, z.hi), max(z.lo, z.hi)
            ax.add_patch(Rectangle((z.p - 0.4, lo), int(s.i) - z.p + 0.8, hi - lo, color="#457b9d", alpha=0.25))
            ax.hlines(z.bos_level, z.bos - 10, z.bos, colors="k", linestyles="--", lw=1)
            ent = s.entry if np.isfinite(s.entry) else df["open"].iat[int(s.i) + 1]
            ax.scatter([s.i + (0 if s.limit else 1)], [ent], marker="^" if s.side > 0 else "v", s=120,
                       color="green" if s.side > 0 else "red", zorder=5)
            ax.hlines(s.stop_px, s.i, i1, colors="red", lw=1)
            if np.isfinite(s.target_px):
                ax.hlines(s.target_px, s.i, i1, colors="green", lw=1)
            ax.set_title(f"{sym} {iv} {'long' if s.side > 0 else 'short'}  "
                         f"{pd.Timestamp(df['ts'].iat[int(s.i)], unit='s'):%Y-%m-%d %H:%M}", fontsize=10)
        fig.suptitle(f"trigger: {trig}   (strong leg, with the 4h)   blue: zone   dashed: structure broken   "
                     f"red / green: stop / opposite-zone target", fontsize=12)
        fig.tight_layout()
        fig.savefig(OUT / f"gallery_{trig}.png", dpi=75)
        plt.close(fig)
        print(f"  {trig}: {len(cands)} setups", flush=True)


# ------------------------------------------------------------------------------------- direction

HORIZONS, LEVELS = (0.25, 1, 3, 5), (1, 2, 4)  # days; ATR


def _paths(df, a, i, side, ref, sec):
    """From the bar after i: the move in ATR at each horizon (days), and for each level which of
    +k / -k ATR is reached first within the 5-day hold (1, -1, 0 if a bar reaches both or neither)."""
    h, l, c = (df[k].to_numpy() for k in ("high", "low", "close"))
    n, A = len(df), a[i]
    bars = [max(1, int(round(H * 86400 / sec))) for H in HORIZONS]
    mv = [side * (c[i + H] - ref) / A if i + H < n else np.nan for H in bars]
    first = []
    for k in LEVELS:
        up, dn = ref + side * k * A, ref - side * k * A
        res = 0
        for j in range(i + 1, min(n, i + 1 + bars[-1])):
            fav = h[j] >= up if side > 0 else l[j] <= up
            adv = l[j] <= dn if side > 0 else h[j] >= dn
            if fav or adv:
                res = 0 if (fav and adv) else (1 if fav else -1)
                break
        first.append(res)
    return mv + first


def direction_one(job):
    import run as R
    sym, iv = job
    R.DB = os.environ.get("MT5BT_DB")
    df, d4 = R.load(sym, iv), R.load(sym, "4h")
    if df is None or d4 is None:
        return None
    df, d4 = df.reset_index(drop=True), d4.reset_index(drop=True)
    a = P.atr(df, 14)
    zs = zones(df, a)
    st = setups(df, a, zs)
    if st.empty:
        return None
    k4 = P.htf_index(df["ts"].to_numpy(), SEC[iv], d4["ts"].to_numpy(), SEC["4h"])
    st["bias"] = bias_4h(d4)[np.maximum(k4[st["i"].to_numpy()], 0)] == st["side"]
    piv = bjorgum_pivots(df)
    zm = zma_series(df)
    zm_ag, zm_st = zm["agrees"].to_numpy(), zm["stretched"].to_numpy()
    o = df["open"].to_numpy()
    rng = np.random.default_rng(zlib.crc32(f"dir{sym}{iv}".encode()))
    ok = np.flatnonzero(a > 0)
    ok = ok[(ok > 100) & (ok < len(df) - 2)]
    cols = [f"mv{H}" for H in HORIZONS] + [f"first{k}" for k in LEVELS]
    rows = []
    for s in st.itertuples():
        i = int(s.i) if not s.limit else int(s.zone_ret)
        if i + 1 >= len(df) or not a[i] > 0:
            continue
        ref = s.entry if s.limit else o[i + 1]
        dx = dict(dax=bool(s.bias and s.protected and s.has_sl), dax_major=bool(s.bias and s.protected and s.has_sl
                                                                                 and s.dax_major),
                  bj=bjorgum_overlap(piv, int(s.i), min(s.zone_lo, s.zone_hi), max(s.zone_lo, s.zone_hi)),
                  zma_ag=bool(zm_ag[int(s.i)] == s.side), zma_st=bool(zm_st[int(s.i)] == s.side))
        rows.append(dict(kind="setup", trigger=s.trigger, bias=bool(s.bias), side=s.side, n_gaps=s.n_gaps, **dx,
                         **dict(zip(cols, _paths(df, a, i, s.side, ref, SEC[iv]), strict=True))))
        for j in rng.choice(ok, 3):  # the same side at a random bar of this market
            rows.append(dict(kind="random", trigger=s.trigger, bias=bool(s.bias), side=s.side, n_gaps=s.n_gaps, **dx,
                             **dict(zip(cols, _paths(df, a, int(j), s.side, o[j + 1], SEC[iv]), strict=True))))
    out = pd.DataFrame(rows).assign(sym=sym, iv=iv, family=R.FAMILY.get(sym, "?"))
    print(f"  direction {sym} {iv}: {len(st)} setups", flush=True)
    return out


def direction():
    """Directional accuracy, the stop aside: does price go the zone's way, and does it get k ATR
    in its favour before k against - for every trigger, against the same side at random bars."""
    import run as R
    from score import JUMPY
    syms = os.environ.get("SYMBOLS")
    syms = syms.split(",") if syms else [s for s in R.FAMILY if s not in R.FRESH]
    jobs = [(s, iv) for iv in os.environ.get("INTERVALS", "1h,4h,1d").split(",") for s in syms]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 20))) as pool:
        got = [g for g in pool.map(direction_one, jobs) if g is not None]
    d = pd.concat(got, ignore_index=True)
    d.loc[(d["family"] == "deriv") & d["sym"].str.startswith(JUMPY), "family"] = "deriv_jump"
    d["scope"] = np.where(d["family"].str.startswith("deriv"), d["family"], "real markets")
    d.to_pickle(OUT / "direction.pkl.gz")
    rows = []
    for (scope, iv, trig, kind), g in d.groupby(["scope", "iv", "trigger", "kind"]):
        for flt, x in (("none", g), ("bias", g[g["bias"]])):
            if len(x) < 30:
                continue
            r = dict(scope=scope, iv=iv, trigger=trig, filter=flt, kind=kind, n=len(x))
            for H in HORIZONS:
                v = x[f"mv{H}"].dropna()
                r[f"up{H}d"] = (v > 0).mean()
            for k in LEVELS:
                f = x[f"first{k}"]
                r[f"first{k}"] = (f == 1).sum() / max((f != 0).sum(), 1)
            rows.append(r)
    t = pd.DataFrame(rows)
    t.to_csv(OUT / "direction.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 500)
    val = [f"up{H}d" for H in HORIZONS] + [f"first{k}" for k in LEVELS]
    w = t.pivot_table(index=["scope", "iv", "trigger", "filter"], columns="kind", values=val + ["n"])
    for v in val:
        w[(v, "edge")] = w[(v, "setup")] - w[(v, "random")]
    show = w[[(v, k) for v in val for k in ("setup", "edge")] + [("n", "setup")]].round(3)
    print(show.to_string())


def plot_levels():
    """Aligned-gap levels: every gap that made the level, the level, the first return and the next
    60 bars - to check by eye that the levels are what the desk means."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    import run as R
    R.DB = os.environ.get("MT5BT_DB")
    OUT.mkdir(parents=True, exist_ok=True)
    for sym, iv in (("EURUSD", "1h"), ("XAUUSD", "4h"), ("US Tech 100", "1h"), ("GBPJPY", "4h"),
                    ("BTCUSD", "4h"), ("Germany 40", "1h"), ("US SP 500", "1d"), ("Volatility 75 Index", "1h")):
        df = R.load(sym, iv)
        if df is None:
            continue
        df = df.reset_index(drop=True)
        a = P.atr(df, 14)
        zs = [z for z in zones_fvglevel(df, a, "aligned") if z.ret >= 0]
        if not zs:
            continue
        rng = np.random.default_rng(zlib.crc32(sym.encode()))
        fig, axes = plt.subplots(2, 2, figsize=(18, 11))
        for ax, zi in zip(axes.flat, np.sort(rng.choice(len(zs), min(4, len(zs)), replace=False)), strict=False):
            z = zs[zi]
            first = min(p[0] for p in z.parts)
            i0, i1 = max(0, first - 10), min(len(df) - 1, z.ret + 60)
            w = df.iloc[i0:i1 + 1]
            x = np.arange(i0, i1 + 1)
            up = (w["close"] >= w["open"]).to_numpy()
            ax.vlines(x, w["low"], w["high"], color="#555", lw=0.5)
            ax.bar(x[up], (w["close"] - w["open"])[up], bottom=w["open"][up], color="#2a9d8f", width=0.7)
            ax.bar(x[~up], (w["close"] - w["open"])[~up], bottom=w["open"][~up], color="#e76f51", width=0.7)
            for k, lo, hi in z.parts:
                ax.add_patch(Rectangle((k - 2, lo), 2, hi - lo, color="#f4a261", alpha=0.6))
            level = z.bos_level
            ax.hlines(level, first, i1, colors="#1d3557", lw=1.2)
            ax.axhspan(min(z.lo, z.hi), max(z.lo, z.hi), color="#457b9d", alpha=0.12)
            ax.axvline(z.p, color="purple", lw=0.8, ls=":")
            ax.axvline(z.live, color="#999", lw=0.8, ls=":")
            ax.scatter([z.ret], [z.hi], marker="^" if z.side > 0 else "v", s=110,
                       color="green" if z.side > 0 else "red", zorder=5)
            ax.set_title(f"{sym} {iv}  {len(z.parts)} gaps line up  level {level:.5g}  as "
                         f"{'support' if z.side > 0 else 'resistance'}  returned "
                         f"{pd.Timestamp(df['ts'].iat[z.ret], unit='s'):%Y-%m-%d %H:%M}", fontsize=10)
        fig.suptitle("orange: each fair-value gap (filled later or not)   navy line: the level they make   "
                     "purple dotted: level known   grey dotted: price 1 ATR away   triangle: first return", fontsize=11)
        fig.tight_layout()
        fig.savefig(OUT / f"levels_{sym.replace(' ', '_')}_{iv}.png", dpi=80)
        plt.close(fig)
        print(f"  {sym} {iv}: {len(zs)} levels returned to", flush=True)


def plot_combo():
    """Our origin zones where a Bjorgum zone lines up, and Bjorgum's zones alone: the origin zone
    (blue) with its break of structure and gap, every Bjorgum zone the indicator shows at the
    trigger bar (purple, support / resistance by where it came from), the entry, stop, target."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    import run as R
    R.DB = os.environ.get("MT5BT_DB")
    OUT.mkdir(parents=True, exist_ok=True)

    def candles(ax, df, i0, i1):
        w = df.iloc[i0:i1 + 1]
        x = np.arange(i0, i1 + 1)
        up = (w["close"] >= w["open"]).to_numpy()
        ax.vlines(x, w["low"], w["high"], color="#555", lw=0.6)
        ax.bar(x[up], (w["close"] - w["open"])[up], bottom=w["open"][up], color="#2a9d8f", width=0.7)
        ax.bar(x[~up], (w["close"] - w["open"])[~up], bottom=w["open"][~up], color="#e76f51", width=0.7)

    for sym, iv in (("EURUSD", "1h"), ("XAUUSD", "4h"), ("US Tech 100", "1h"), ("GBPJPY", "4h"),
                    ("BTCUSD", "4h"), ("Germany 40", "1h")):
        df, d4 = R.load(sym, iv), R.load(sym, "4h")
        if df is None or d4 is None:
            continue
        df, d4 = df.reset_index(drop=True), d4.reset_index(drop=True)
        a = P.atr(df, 14)
        piv = bjorgum_pivots(df)
        rng = np.random.default_rng(zlib.crc32(sym.encode()))
        # 1 our zones that line up with Bjorgum
        zs = zones(df, a)
        st = setups(df, a, zs)
        k4 = P.htf_index(df["ts"].to_numpy(), SEC[iv], d4["ts"].to_numpy(), SEC["4h"])
        st = st[(bias_4h(d4)[np.maximum(k4[st["i"].to_numpy()], 0)] == st["side"])
                & st["trigger"].isin(["touch", "pin", "engulf", "reclaim", "cisd"])]
        st = st[[bjorgum_overlap(piv, int(r.i), min(r.zone_lo, r.zone_hi), max(r.zone_lo, r.zone_hi))
                 for r in st.itertuples()]]
        figs = []
        if len(st):
            fig, axes = plt.subplots(2, 2, figsize=(18, 11))
            for ax, (_, s_) in zip(axes.flat, st.iloc[np.sort(rng.choice(len(st), min(4, len(st)), replace=False))].iterrows(),
                                   strict=False):
                z = next(z for z in zs if z.p == s_.zone_p and z.side == s_.side)
                i = int(s_.i)
                i0, i1 = max(0, z.p - 40), min(len(df) - 1, i + 50)
                candles(ax, df, i0, i1)
                for b_lo, b_hi, res in bjorgum_live(piv, i):
                    ax.axhspan(b_lo, b_hi, color="purple", alpha=0.10)
                    ax.annotate("bjorgum " + ("R" if res else "S"), (i0, b_hi), fontsize=7, color="purple")
                lo, hi = min(z.lo, z.hi), max(z.lo, z.hi)
                ax.add_patch(Rectangle((z.p - 0.4, lo), i - z.p + 0.8, hi - lo, color="#457b9d", alpha=0.35))
                hh, ll = df["high"].to_numpy(), df["low"].to_numpy()
                g = z.fvg
                g_lo, g_hi = (hh[g - 2], ll[g]) if z.side > 0 else (hh[g], ll[g - 2])
                ax.add_patch(Rectangle((g - 2, g_lo), 2, g_hi - g_lo, color="#f4a261", alpha=0.6))
                ax.hlines(z.bos_level, z.bos - 10, z.bos, colors="k", linestyles="--", lw=1)
                ax.annotate("BOS", (z.bos, z.bos_level), fontsize=8)
                ent = s_.entry if np.isfinite(s_.entry) else df["open"].iat[i + 1]
                ax.scatter([i + (0 if s_.limit else 1)], [ent], marker="^" if s_.side > 0 else "v", s=120,
                           color="green" if s_.side > 0 else "red", zorder=5)
                ax.hlines(s_.stop_px, i, i1, colors="red", lw=1)
                if np.isfinite(s_.target_px):
                    ax.hlines(s_.target_px, i, i1, colors="green", lw=1)
                ax.set_ylim(df["low"].iloc[i0:i1 + 1].min() * 0.998, df["high"].iloc[i0:i1 + 1].max() * 1.002)
                ax.set_title(f"{sym} {iv} {'long' if s_.side > 0 else 'short'}  trigger={s_.trigger}  "
                             f"{pd.Timestamp(df['ts'].iat[i], unit='s'):%Y-%m-%d %H:%M}", fontsize=10)
            fig.suptitle("our origin zone (blue: BOS dashed, imbalance orange) where a Bjorgum zone (purple) lines up "
                         "- 4h bias agrees | red stop, green target", fontsize=11)
            figs.append(("combo", fig))
        # 2 Bjorgum alone
        zb = [z for z in zones_bjorgum(df, a) if z.ret >= 0]
        if zb:
            fig, axes = plt.subplots(2, 2, figsize=(18, 11))
            for ax, zi in zip(axes.flat, np.sort(rng.choice(len(zb), min(4, len(zb)), replace=False)), strict=False):
                z = zb[zi]
                i0, i1 = max(0, z.p - 30), min(len(df) - 1, z.ret + 50)
                candles(ax, df, i0, i1)
                for b_lo, b_hi, res in bjorgum_live(piv, z.ret):
                    ax.axhspan(b_lo, b_hi, color="purple", alpha=0.08)
                lo, hi = min(z.lo, z.hi), max(z.lo, z.hi)
                ax.add_patch(Rectangle((z.p, lo), z.ret - z.p, hi - lo, color="#457b9d", alpha=0.35))
                ax.scatter([z.p], [z.bos_level], marker="o", s=60, facecolors="none", edgecolors="k")
                ax.axvline(z.bos, color="#999", lw=0.8, ls=":")
                ax.scatter([z.ret], [z.hi], marker="^" if z.side > 0 else "v", s=110,
                           color="green" if z.side > 0 else "red", zorder=5)
                ax.set_ylim(df["low"].iloc[i0:i1 + 1].min() * 0.998, df["high"].iloc[i0:i1 + 1].max() * 1.002)
                ax.set_title(f"{sym} {iv} Bjorgum zone as {'support' if z.side > 0 else 'resistance'}  first return "
                             f"{pd.Timestamp(df['ts'].iat[z.ret], unit='s'):%Y-%m-%d %H:%M}", fontsize=10)
            fig.suptitle("Bjorgum alone: the pivot (circle, 20 bars left / 15 right), its zone (blue) from the pivot to "
                         "the first return (triangle); dotted: pivot confirmed; purple: every zone shown then", fontsize=11)
            figs.append(("bjorgum", fig))
        for name, fig in figs:
            fig.tight_layout()
            fig.savefig(OUT / f"{name}_{sym.replace(' ', '_')}_{iv}.png", dpi=80)
            plt.close(fig)
        print(f"  {sym} {iv}: {len(st)} aligned setups, {len(zb)} Bjorgum zones returned to", flush=True)


def plot_zma():
    """Our origin zones where ZMA agrees at the trigger bar: price with the zone, gap and break above;
    ZMA's z-score below with its strong thresholds, the trigger bar marked."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    import run as R
    R.DB = os.environ.get("MT5BT_DB")
    OUT.mkdir(parents=True, exist_ok=True)
    for sym, iv in (("EURUSD", "1h"), ("XAUUSD", "4h"), ("US Tech 100", "1h"), ("GBPJPY", "4h"),
                    ("BTCUSD", "4h"), ("Germany 40", "1h")):
        df = R.load(sym, iv)
        if df is None:
            continue
        df = df.reset_index(drop=True)
        a = P.atr(df, 14)
        zs = zones(df, a)
        st = setups(df, a, zs)
        zm = zma_series(df)
        st = st[(zm["stretched"].to_numpy()[st["i"].to_numpy()] == st["side"].to_numpy())
                & st["trigger"].isin(["touch", "pin", "engulf", "reclaim", "cisd"])]
        if st.empty:
            continue
        rng = np.random.default_rng(zlib.crc32(("zma" + sym).encode()))
        pick = st.iloc[np.sort(rng.choice(len(st), min(4, len(st)), replace=False))]
        fig = plt.figure(figsize=(18, 12))
        gs = fig.add_gridspec(4, 2, height_ratios=[3, 1, 3, 1])
        for n_, (_, s_) in enumerate(pick.iterrows()):
            r_, c_ = (n_ // 2) * 2, n_ % 2
            ax, az = fig.add_subplot(gs[r_, c_]), fig.add_subplot(gs[r_ + 1, c_])
            z = next(z for z in zs if z.p == s_.zone_p and z.side == s_.side)
            i = int(s_.i)
            i0, i1 = max(0, z.p - 40), min(len(df) - 1, i + 50)
            w = df.iloc[i0:i1 + 1]
            x = np.arange(i0, i1 + 1)
            up = (w["close"] >= w["open"]).to_numpy()
            ax.vlines(x, w["low"], w["high"], color="#555", lw=0.6)
            ax.bar(x[up], (w["close"] - w["open"])[up], bottom=w["open"][up], color="#2a9d8f", width=0.7)
            ax.bar(x[~up], (w["close"] - w["open"])[~up], bottom=w["open"][~up], color="#e76f51", width=0.7)
            lo, hi = min(z.lo, z.hi), max(z.lo, z.hi)
            ax.add_patch(Rectangle((z.p - 0.4, lo), i - z.p + 0.8, hi - lo, color="#457b9d", alpha=0.35))
            hh, ll = df["high"].to_numpy(), df["low"].to_numpy()
            g = z.fvg
            g_lo, g_hi = (hh[g - 2], ll[g]) if z.side > 0 else (hh[g], ll[g - 2])
            ax.add_patch(Rectangle((g - 2, g_lo), 2, g_hi - g_lo, color="#f4a261", alpha=0.6))
            ax.hlines(z.bos_level, z.bos - 10, z.bos, colors="k", linestyles="--", lw=1)
            ent = s_.entry if np.isfinite(s_.entry) else df["open"].iat[i + 1]
            ax.scatter([i + (0 if s_.limit else 1)], [ent], marker="^" if s_.side > 0 else "v", s=120,
                       color="green" if s_.side > 0 else "red", zorder=5)
            ax.hlines(s_.stop_px, i, i1, colors="red", lw=1)
            if np.isfinite(s_.target_px):
                ax.hlines(s_.target_px, i, i1, colors="green", lw=1)
            ax.set_ylim(w["low"].min() * 0.998, w["high"].max() * 1.002)
            ax.set_xlim(i0 - 1, i1 + 1)
            ax.set_title(f"{sym} {iv} {'long' if s_.side > 0 else 'short'}  trigger={s_.trigger}  ZMA "
                         f"{'agrees' if zm['agrees'].iat[i] == s_.side else 'stretched'}  "
                         f"{pd.Timestamp(df['ts'].iat[i], unit='s'):%Y-%m-%d %H:%M}", fontsize=10)
            zz = zm.iloc[i0:i1 + 1]
            az.plot(x, zz["z"], color="#1d3557", lw=1)
            az.plot(x, zz["strong"], color="#999", lw=0.8, ls="--")
            az.plot(x, -zz["strong"], color="#999", lw=0.8, ls="--")
            az.axhline(0, color="#ccc", lw=0.6)
            az.axvline(i, color="purple", lw=1)
            az.set_xlim(i0 - 1, i1 + 1)
            az.set_ylabel("ZMA z", fontsize=8)
        fig.suptitle("origin zone (blue, BOS dashed, imbalance orange) with ZMA (below: z-score, dashed = strong "
                     "thresholds, purple = trigger bar) stretched the zone's way | red stop, green target", fontsize=11)
        fig.tight_layout()
        fig.savefig(OUT / f"zma_{sym.replace(' ', '_')}_{iv}.png", dpi=80)
        plt.close(fig)
        print(f"  {sym} {iv}: {len(st)} setups with ZMA stretched the zone's way", flush=True)


# ------------------------------------------------------------------------------------ volatility

def vol_forecast(df: pd.DataFrame, a: np.ndarray, sec: int) -> tuple[np.ndarray, np.ndarray]:
    """A HAR forecast of the next 5 days' mean true range over the current ATR, walk-forward: refit
    every 500 bars on the rows whose 5 days are already over. Returns (forecast, realised), logs."""
    h, l, c = (df[k].to_numpy() for k in ("high", "low", "close"))
    pc = np.r_[c[0], c[:-1]]
    tr = pd.Series(np.maximum(h, pc) - np.minimum(l, pc))
    H = max(1, int(5 * 86400 / sec))
    day = max(1, int(86400 / sec))
    A = pd.Series(a).replace(0, np.nan)
    X = np.column_stack([np.log(tr / A), np.log(tr.rolling(day).mean() / A), np.log(tr.rolling(5 * day).mean() / A),
                         np.log(A / tr.rolling(20 * day).mean()), np.ones(len(df))])
    y = np.log(tr[::-1].rolling(H).mean()[::-1].shift(-1) / A).to_numpy()
    X[~np.isfinite(X)] = np.nan
    pred = np.full(len(df), np.nan)
    for start in range(1000, len(df), 500):
        known = np.arange(start - H)
        ok = known[np.isfinite(X[known]).all(axis=1) & np.isfinite(y[known])]
        if len(ok) < 300:
            continue
        beta, *_ = np.linalg.lstsq(X[ok], y[ok], rcond=None)
        seg = np.arange(start, min(len(df), start + 500))
        pred[seg] = X[seg] @ beta
    return pred, y


def vol_one(job):
    import run as R
    sym, iv = job
    R.DB = os.environ.get("MT5BT_DB")
    df = R.load(sym, iv)
    if df is None:
        return None
    df = df.reset_index(drop=True)
    a = P.atr(df, 14)
    zs = zones(df, a)
    st = setups(df, a, zs)
    if st.empty:
        return None
    pred, real = vol_forecast(df, a, SEC[iv])
    # each bar's forecast as a percentile of this market's forecasts before it (causal)
    ps = pd.Series(pred)
    pct = ps.expanding(200).rank(pct=True).to_numpy()
    o = df["open"].to_numpy()
    rng = np.random.default_rng(zlib.crc32(f"vol{sym}{iv}".encode()))
    ok = np.flatnonzero((a > 0) & np.isfinite(pct))
    ok = ok[ok < len(df) - 2]
    cols = [f"mv{H}" for H in HORIZONS] + [f"first{k}" for k in LEVELS]
    rows = []
    for k, s in enumerate(st.itertuples()):
        i = int(s.i) if not s.limit else int(s.zone_ret)
        if i + 1 >= len(df) or not a[i] > 0 or not np.isfinite(pct[i]):
            continue
        ref = s.entry if s.limit else o[i + 1]
        rows.append(dict(kind="setup", sid=f"{sym}|{iv}|{k}", trigger=s.trigger, side=s.side, pct=pct[i],
                         pred=pred[i], real=real[i], **dict(zip(cols, _paths(df, a, i, s.side, ref, SEC[iv]), strict=True))))
        if len(ok):
            for j in rng.choice(ok, 3):
                rows.append(dict(kind="random", sid="", trigger=s.trigger, side=s.side, pct=pct[j], pred=pred[j],
                                 real=real[j], **dict(zip(cols, _paths(df, a, int(j), s.side, o[j + 1], SEC[iv]),
                                                          strict=True))))
    print(f"  vol {sym} {iv}", flush=True)
    return pd.DataFrame(rows).assign(sym=sym, iv=iv, family=R.FAMILY.get(sym, "?"))


def vol():
    """Does a volatility forecast pick better zones? Setups by the tercile of their market's
    forecast of the next 5 days' range: trade R (from the zone run's trades, `TRADES`), and the
    direction with the stop aside, each tercile against random bars in the same tercile."""
    import run as R
    from score import JUMPY
    syms = os.environ.get("SYMBOLS")
    syms = syms.split(",") if syms else [s for s in R.FAMILY if s not in R.FRESH]
    jobs = [(s, iv) for iv in os.environ.get("INTERVALS", "1h,4h,1d").split(",") for s in syms]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 20))) as pool:
        got = [g for g in pool.map(vol_one, jobs) if g is not None]
    d = pd.concat(got, ignore_index=True)
    d.loc[(d["family"] == "deriv") & d["sym"].str.startswith(JUMPY), "family"] = "deriv_jump"
    d["scope"] = np.where(d["family"].str.startswith("deriv"), d["family"], "real markets")
    d["tercile"] = pd.cut(d["pct"], [0, 1 / 3, 2 / 3, 1.0001], labels=["low", "mid", "high"])
    d.to_pickle(OUT / "vol.pkl.gz")
    pd.set_option("display.width", 250)
    ok = np.isfinite(d["pred"]) & np.isfinite(d["real"])
    print("forecast quality, correlation of forecast and realised (log range over ATR, next 5 days):")
    print(d[ok].groupby(["scope", "iv"]).apply(lambda g: np.corrcoef(g["pred"], g["real"])[0, 1]).round(3).to_string())

    def summ(g):
        r = {"n": len(g)}
        for H in HORIZONS:
            x = g[f"mv{H}"].dropna()
            r[f"up{H}d"] = (x > 0).mean()
            r[f"move{H}d_atr"] = x.mean()
        for k in LEVELS:
            f = g[f"first{k}"]
            r[f"{k}ATR first"] = (f == 1).sum() / max((f != 0).sum(), 1)
        return pd.Series(r)
    print("\ndirection, stop aside, by forecast tercile (setup vs random bars of the same tercile):")
    print(d.groupby(["scope", "iv", "tercile", "kind"], observed=True).apply(summ).round(3).to_string())
    tp = os.environ.get("TRADES")
    if tp:
        t = pd.read_pickle(tp)
        t = t[(t["kind"] == "real") & (t["filter"] == "none") & t["sid"].astype(bool)]
        t = t.merge(d[d["kind"] == "setup"][["sid", "tercile", "scope"]], on="sid", how="inner")
        print("\ntrade R by forecast tercile (all triggers, no filter, 5-day hold):")
        print(t.groupby(["scope", "iv", "exit", "tercile"], observed=True)["R"].agg(
            ["size", "mean", lambda x: (x >= 4).mean()]).round(3).rename(columns={"<lambda_0>": "p4"}).to_string())


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    {"plot": plot, "run": run, "gallery": gallery, "direction": direction, "vol": vol,
     "levelplot": plot_levels, "comboplot": plot_combo, "zmaplot": plot_zma}[os.environ.get("MODE", "plot")]()


if __name__ == "__main__":
    main()
