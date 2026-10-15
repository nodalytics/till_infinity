"""Two published SMC frameworks, decomposed into primitives and conjunctions.

Both arrived as named methods and both are the same shape under the names.

**EMS** - stated as *all three systems must align*:

1. Mark a key level and wait for a clear rejection; that sets the direction.
2. Find an **engulfing** candle in that direction - and draw the zone on the
   candle that got **engulfed**, not the one that did the engulfing. That is the
   one non-obvious instruction in the method.
3. Drop a few timeframes and require a clean structure inside the zone; the
   worked example annotates a liquidity sweep followed by a break of structure.

**SLK** - a top-down framework:

* **S - Structure.** The primary trend and its shifts (CHoCH) on H1 or H4.
* **L - Liquidity.** Internal and external range liquidity, order blocks, and
  sweeps of resting stops.
* **K - Key levels.** Bounce zones and order blocks, used to time an entry on
  15m or 5m.

So both are: a higher-timeframe bias, a liquidity event, and a lower-timeframe
entry at a zone. They are tested together because they share every primitive.

## What is already closed, and what is not

The primitives are mostly measured on this desk, and they are carried here as
the baseline the conjunction has to beat rather than as candidates:

* **Liquidity sweeps** - `sweeps.md`, 2026-10-04: every sweep form "identified
  exactly, and predicting nothing", occurring on the diffusive indices at
  0.94-1.02x an iid walk's rate, and real markets showing *fewer* wick sweeps
  than their own shuffled bars.
* **Break of structure** - `bos-predict.md`: the side is not predictable beyond
  geometry, and the geometry reads AUC 0.75 on iid and GARCH walks too.
* **Structure shape** - `structure.md`: nothing predicts direction beyond `side`.
* **Order blocks** - `order-block-zones.md`: an 82% return rate and a losing
  read, with a correction already recorded against its first version.
* **Direction generally** - `direction-is-closed-not-just-null`.

**What none of them tested is the conjunction.** Three filters that are each
worthless can still select a population that is not, and that is the entire
claim both frameworks make. Each primitive alone, then the pairs, then the full
stack, is the output here.

## The baseline is a walk, not zero

The trade geometry loses money on a driftless random walk, and by a lot: the
stop sits at the engulfing candle's extreme and the entry at the engulfed
candle's edge, so the risk can be a hair wide, both barriers fall inside one
bar, and the conservative reading charges the loss. Measured on a walk before
any filter was applied: **-0.598R at a 1R target, hit rate 0.201**. `MIN_RISK`
removes the worst of it and a matched walk arm prices the rest, because a
result here means beating the walk through the same detector and not beating
zero.

Every arm also carries a distance-matched placebo level, a block-shuffled twin
that preserves candle shapes, the generated feeds, and the spread - a setup
whose stop is one candle away pays the round trip on every attempt.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

CACHE = Path.home() / "till_infinity/data/seqlab"
#: `(signal frame, confirming frame)`. EMS says weekly with "a few timeframes
#: lower" and the cache tops out at 1d; SLK names H1 or H4 for bias and 15m or
#: 5m for entry, and the cache's lowest useful frame is 15m. These four cover
#: both readings.
PAIRS = (("1d", "4h"), ("4h", "1h"), ("4h", "15m"), ("1h", "15m"))
LIMIT = 40000
#: Bars of history that nominate the key level on the signal frame.
LOOKBACK = 60
#: Bars after a rejection in which an engulfing candle still counts.
PATIENCE = 3
#: Bars allowed for price to return into the zone after the engulf.
WAIT = 10
#: Bars allowed for the trade to resolve once filled.
HOLD = 30
#: How close to the level a bar has to come to count as reaching it, in units of
#: the signal frame's median bar range.
REACH = 0.25
#: Targets in multiples of the stop distance.
TARGETS = (1.0, 2.0, 3.0)
#: Readings of the entry band, swept for the headline arms.
ZONES = ("engulfed", "origin zone", "order block")
#: Setups a row needs before it is printed. Without it the table was topped by
#: 21-setup cells whose apparent edge was one lucky fill.
LEAST_SETUPS = 200
JITTER = 0.15
SEED = 20261015
MAJORS = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD")
CROSSES = ("EURGBP", "EURJPY", "GBPJPY", "AUDJPY", "EURAUD", "CADJPY")
METALS = ("XAUUSD", "XAGUSD")
GENERATED = ("Volatility_75_Index", "Volatility_100_Index", "Step_Index_200")
GROUPS = (("fx majors", MAJORS), ("fx crosses", CROSSES), ("metals", METALS),
          ("generated", GENERATED))
#: Minimum stop distance, in units of the signal frame's median bar range.
#:
#: **Without this the measurement is about stop size and nothing else.** The
#: stop sits at the engulfing candle's extreme and the entry at the engulfed
#: candle's edge, so the risk can be a hair wide - and then both barriers fall
#: inside one bar, the conservative "charge the loss" rule fires, and a
#: driftless walk reads **-0.598R at a 1R target with a hit rate of 0.201**.
#: That is the geometry, not the market.
MIN_RISK = 0.25
#: The arms. Each primitive alone, then the conjunctions the method claims.
#:
#: The primitives are mostly closed already and are here as the baseline the
#: conjunction has to beat: `sweeps.md` found every sweep form "identified
#: exactly, and predicting nothing"; `bos-predict.md` found the side of a break
#: unpredictable beyond geometry, at AUC 0.75 on walks as well as markets;
#: `structure.md` found nothing predicting direction beyond `side`. What none of
#: them tested is the **conjunction** - three filters that are each worthless can
#: still select a population that is not, and that is the whole claim here.
ARMS = (
    # Primitives, each alone.
    ("engulf", ("engulf",)),
    ("key level", ("level",)),
    ("sweep (ext)", ("sweep",)),
    ("imbalance (int)", ("internal",)),
    ("CRT", ("crt",)),
    ("structure shift", ("reversal",)),
    # Pairs.
    ("engulf + level", ("engulf", "level")),
    ("engulf + sweep", ("engulf", "sweep")),
    ("bias + level", ("reversal", "level")),
    # The user's observation, as a measurement: an engulf and a displacement
    # origin are nearly the same construction. These price the difference.
    ("displaced", ("displaced",)),
    ("origin body", ("origin body",)),
    ("engulf + displaced", ("engulf", "displaced")),
    ("engulf + origin body", ("engulf", "origin body")),
    ("full origin", ("engulf", "displaced", "origin body")),
    # The two frameworks as stated. **The liquidity event is the lower frame's**
    # - `structure` - and not the signal frame's `sweep`, because on one frame a
    # structure shift and a sweep are near-exclusive: a shift closes beyond the
    # range and a sweep closes back inside it, and the two share a Jaccard of
    # 0.016 on a walk. Encoding SLK on a single frame left it firing on 1 of 622
    # walk setups, which is not a test of anything. Top-down is not decoration
    # in these frameworks; it is what makes the conjunction satisfiable.
    ("EMS", ("engulf", "level", "structure")),
    ("SLK", ("reversal", "level", "structure")),
    ("everything", ("engulf", "level", "reversal", "structure")),
)


def load(name: str, frame: str):
    path = CACHE / f"{name}.{frame}.npz"
    if not path.exists():
        return None
    with np.load(path) as bundle:
        need = {"time", "open", "high", "low", "close"}
        if not need <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        got = {k: np.asarray(bundle[k], dtype=float)[order] for k in need}
        got["spread"] = (
            np.asarray(bundle["spread"], dtype=float)[order]
            if "spread" in bundle
            else np.zeros_like(got["close"])
        )
    keep = (got["high"] >= got["low"]) & (got["low"] > 0)
    got = {k: v[keep] for k, v in got.items()}
    if len(got["close"]) < 600:
        return None
    if len(got["close"]) > LIMIT:
        got = {k: v[-LIMIT:] for k, v in got.items()}
    return got


def point_size(closes: np.ndarray) -> float:
    """The quote grid, from the smallest non-zero close change.

    `spread` is in **points**, not price, so it needs this before it can be
    compared with anything - the error that read a 476% round trip on EURUSD.
    """
    steps = np.abs(np.diff(closes))
    steps = steps[steps > 0]
    if not len(steps):
        return 0.0
    return float(np.percentile(steps, 0.1))


def shuffled(bars, rng):
    """A block-shuffled rebuild: same bar geometry, no memory.

    Candle shapes are preserved by moving whole bars, because an engulfing
    pattern is a statement about two adjacent bars' shapes and destroying the
    shapes would test a different thing.
    """
    count = len(bars["close"])
    blocks = np.array_split(np.arange(count), max(count // 40, 2))
    rng.shuffle(blocks)
    order = np.concatenate(blocks)
    out = {k: v[order] for k, v in bars.items() if k != "time"}
    out["time"] = bars["time"]
    # Re-anchor each block so the path is continuous rather than a sawtooth.
    shift = np.concatenate(([0.0], np.cumsum(out["close"][:-1] - out["open"][1:])))
    for key in ("open", "high", "low", "close"):
        out[key] = out[key] + shift
    return out if np.all(out["low"] > 0) else None


def engulfings(bars) -> np.ndarray:
    """Index of each bar that engulfs its predecessor, with the sign of its body.

    Range engulfing - `high >= previous high` and `low <= previous low` - which
    is the stricter reading and the one the worked examples show.

    The range must also be **strictly** larger. Without that, two adjacent bars
    with identical highs and lows satisfy both inequalities and count as an
    engulf of nothing, which a smoke test caught immediately: a hand-built
    five-bar series returned two engulfings where one was built in.
    """
    highs, lows = bars["high"], bars["low"]
    opens, closes = bars["open"], bars["close"]
    bigger = (
        (highs[1:] >= highs[:-1])
        & (lows[1:] <= lows[:-1])
        & ((highs[1:] - lows[1:]) > (highs[:-1] - lows[:-1]))
    )
    moved = np.sign(closes[1:] - opens[1:])
    where = np.flatnonzero(bigger & (moved != 0))
    return where + 1


def swept(bars, at: int, up: bool, back: int = 20, patience: int = PATIENCE) -> bool:
    """A liquidity sweep on the signal frame: a poke past a prior extreme that closes back.

    `sweeps.md` measured every sweep form at 0.94 to 1.02 times an iid walk's
    rate on the diffusive indices, and predicting nothing on six real asset
    classes - so this is carried as a **filter**, not as a signal.
    """
    if at < back + patience + 1:
        return False
    # Any of the last `patience` bars may be the sweep, as `rejected` allows for
    # the rejection. Requiring it on the signal bar itself made the SLK
    # conjunction fire on 2 of 622 walk setups, which is not a test.
    for i in range(max(at - patience, back), at + 1):
        window = slice(i - back, i)
        if up:
            roof = float(bars["high"][window].max())
            if bars["high"][i] > roof and bars["close"][i] < roof:
                return True
        else:
            floor = float(bars["low"][window].min())
            if bars["low"][i] < floor and bars["close"][i] > floor:
                return True
    return False


def reversed_structure(bars, at: int, up: bool, back: int = 10) -> bool:
    """A market-structure reversal: the last opposite swing gives way.

    For a short, price made a higher high and has since closed below the swing
    low that followed it - the change of character both frameworks use as the
    higher-timeframe **bias**. `bos-predict.md` has the side of a break at AUC
    0.75 on walks as well as markets, so again: a filter, not a signal.

    **A short window on purpose.** Over 20 bars a shift in the trade direction
    occurs on **0.741** of walk setups, and over the same window `crt` fires on
    0.706 with a Jaccard overlap of 0.552 between them - two named primitives
    that are half the same event and neither of which removes much. Ten bars is
    the window where it still means something.

    **Evaluated over a window ending before `at`, not on `at` itself**, and
    that is the whole point. The first version tested the signal bar, which
    made it mutually exclusive with `swept` by construction - a sweep closes
    back inside the range and a structure shift closes beyond it, so the two
    can never be the same bar, and the overlap table read **0.000**. The SLK
    conjunction could not have fired once. Both frameworks establish the bias
    first and wait for the liquidity event afterwards, which is what this now
    encodes.
    """
    if at < back + 3:
        return False
    window = slice(at - back - 1, at)
    highs, lows, closes = bars["high"][window], bars["low"][window], bars["close"][window]
    if len(closes) < 6:
        return False
    if up:
        made = int(np.argmax(highs))
        if made >= len(lows) - 2:
            return False
        # The running extreme is whatever stood **before** this bar. Updating
        # it first makes the test unsatisfiable, since a bar's low never
        # exceeds its close - which read a fire rate of exactly 0.000.
        floor = float(lows[made])
        for i in range(made + 1, len(closes)):
            if i > made + 1 and closes[i] < floor:
                return True
            floor = min(floor, float(lows[i]))
        return False
    made = int(np.argmin(lows))
    if made >= len(highs) - 2:
        return False
    roof = float(highs[made])
    for i in range(made + 1, len(closes)):
        if i > made + 1 and closes[i] > roof:
            return True
        roof = max(roof, float(highs[i]))
    return False


#: The desk's own displacement parameters, from `drawing/displacement.py` and
#: `drawing/origins.py`, so the comparison uses its definition and not a new one.
PUSH_BODY, PUSH_N = 0.65, 2
ORIGIN_BODY = (0.10, 0.60)
MIN_LEG_VOL = 1.5
WIDE_BAR = 2.0


def displaced(bars, at: int, up: bool, unit: float) -> bool:
    """The desk's push test applied to the engulfing bar.

    `PUSH_N` consecutive bars whose bodies are at least `PUSH_BODY` of their own
    range, all the same direction, spanning at least `MIN_LEG_VOL` volatility
    units. The engulfing bar is the candidate impulse.
    """
    if unit <= 0 or at + PUSH_N > len(bars["close"]):
        return False
    side = -1.0 if up else 1.0
    for i in range(at, at + PUSH_N):
        span = float(bars["high"][i] - bars["low"][i])
        if span <= 0:
            return False
        body = side * float(bars["close"][i] - bars["open"][i])
        if body < PUSH_BODY * span:
            return False
    leg = abs(float(bars["close"][at + PUSH_N - 1] - bars["open"][at]))
    return leg >= MIN_LEG_VOL * unit


def origin_shaped(bars, at: int, unit: float) -> bool:
    """Does the engulfed candle look like an origin bar by the desk's rule?

    Body between a tenth and three fifths of its own range - "normally a small
    candle", with the upper bound stopping every bar of a trend qualifying and
    the lower one rejecting the doji. **The published method puts no constraint
    here at all**, which is the difference the variants below price.
    """
    span = float(bars["high"][at - 1] - bars["low"][at - 1])
    if span <= 0 or unit <= 0:
        return False
    share = abs(float(bars["close"][at - 1] - bars["open"][at - 1])) / span
    return ORIGIN_BODY[0] <= share <= ORIGIN_BODY[1]


def desk_zone(bars, at: int, unit: float) -> tuple[float, float]:
    """`zone_of` from `drawing/origins.py`, on the engulfed candle.

    Its range, or its **body** when the range reaches `WIDE_BAR` volatility
    units - price went there and did not stay, so the traded part is the body.
    """
    high, low = float(bars["high"][at - 1]), float(bars["low"][at - 1])
    if unit > 0 and (high - low) >= WIDE_BAR * unit:
        top, bottom = float(bars["open"][at - 1]), float(bars["close"][at - 1])
        if top != bottom:
            return min(top, bottom), max(top, bottom)
    return low, high


def imbalance(bars, at: int, up: bool) -> bool:
    """Internal-range liquidity: a three-bar fair-value gap at the signal bar.

    SLK distinguishes **internal** range liquidity - imbalances and order
    blocks inside the range - from **external**, the swing extremes that
    `swept` covers. This is the internal one: the standard three-bar gap
    centred on the displacement bar, so for a short the bar before it has a low
    above the bar after it has a high.

    Centred on `at`, not ending at it. The first version read bars `at-2` to
    `at` and fired **0.000** of the time on a walk, because `at` is the
    engulfing bar by construction - it has the widest range in the
    neighbourhood, so its high is almost never below a low two bars back. Using
    `at + 1` makes the filter causal only if the fill waits for that bar, which
    `setups` enforces.
    """
    if at < 1 or at + 1 >= len(bars["high"]):
        return False
    if up:
        return bool(bars["low"][at - 1] > bars["high"][at + 1])
    return bool(bars["high"][at - 1] < bars["low"][at + 1])


def order_block(bars, at: int, up: bool, back: int = 6):
    """The last opposite candle before the move, as `(low, high)` or `None`.

    The zone SLK calls a key level and `order-block-zones.md` already measured
    at an 82% return rate with a losing read. Returned as a range so it can be
    used as an entry zone in place of the engulfed candle's.
    """
    for i in range(at - 1, max(at - back, 0), -1):
        rising = bars["close"][i] > bars["open"][i]
        if rising == up:  # a bullish candle before a short, or the mirror
            return float(bars["low"][i]), float(bars["high"][i])
    return None


def candle_range(bars, at: int, up: bool) -> bool:
    """Candle Range Theory: the prior candle's range is swept and reclaimed.

    Named in the SLK material beside key levels. For a short, this bar takes
    out the previous bar's high and closes back inside its range, which is the
    dealing-range reading of the same sweep the method elsewhere calls
    liquidity.

    **It is nearly implied by a range engulf, and the overlap table says so.**
    A range engulf already requires `high >= previous high`, so the sweep half
    of this is satisfied by construction and only the close-back-inside half
    adds anything - it fires on 0.702 of engulfing bars on a walk. Kept because
    the frameworks name it separately, and reported in the overlap table so the
    redundancy is visible rather than inherited.
    """
    if at < 1:
        return False
    high, low = float(bars["high"][at - 1]), float(bars["low"][at - 1])
    close = float(bars["close"][at])
    if up:
        return bool(bars["high"][at] > high and low < close < high)
    return bool(bars["low"][at] < low and low < close < high)


def walk_like(bars, rng):
    """A driftless walk matched to this feed's bar volatility and range shape.

    The baseline every arm is read against, because the trade geometry loses on
    a walk by construction. `null-structure-claims-on-the-same-detector`: the
    null goes through the same detector with the same bar geometry.
    """
    closes = bars["close"]
    steps = np.diff(np.log(closes))
    spread = float(np.nanstd(steps))
    wick = float(np.nanmedian((bars["high"] - bars["low"]) / np.maximum(closes, 1e-12)))
    count = len(closes)
    path = float(closes[0]) * np.exp(np.cumsum(rng.normal(0.0, spread, count)))
    opens = np.concatenate(([path[0]], path[:-1]))
    half = np.abs(rng.normal(0.0, wick / 2.0, count)) * path
    highs = np.maximum(opens, path) + half
    lows = np.minimum(opens, path) - half
    return {
        "open": opens,
        "high": highs,
        "low": np.maximum(lows, 1e-9),
        "close": path,
        "time": bars["time"],
        "spread": bars["spread"],
    }


def rejected(bars, at: int, level: float, up: bool, move: float) -> bool:
    """Did price reach `level` and close back away from it, within `PATIENCE`?

    `up` is a level above price - a resistance - so a rejection is a bar whose
    high reaches it and whose close is back below.
    """
    start = max(at - PATIENCE, 1)
    for i in range(start, at + 1):
        if up:
            if bars["high"][i] >= level - REACH * move and bars["close"][i] < level:
                return True
        elif bars["low"][i] <= level + REACH * move and bars["close"][i] > level:
            return True
    return False


def structure(lower, begin: float, end: float, low: float, high: float, up: bool) -> bool:
    """A sweep then a break of structure, on the lower frame, inside the zone.

    `up` is a short - the zone is a resistance - so the sweep is a poke above a
    local high that closes back below it, and the break is a close under the
    lowest low since that sweep. Both must happen between `begin` and `end`,
    which is the signal bar's own span, and the sweep must occur inside the
    zone's price range.
    """
    when = lower["time"]
    inside = np.flatnonzero((when >= begin) & (when <= end))
    if len(inside) < 8:
        return False
    span = slice(int(inside[0]), int(inside[-1]) + 1)
    highs, lows, closes = lower["high"][span], lower["low"][span], lower["close"][span]
    for i in range(3, len(closes) - 2):
        if up:
            swept = highs[i] > highs[:i].max() and closes[i] < highs[:i].max()
            if not (swept and low <= highs[i] <= high):
                continue
            floor = lows[max(i - 5, 0) : i + 1].min()
            if np.any(closes[i + 1 :] < floor):
                return True
        else:
            swept = lows[i] < lows[:i].min() and closes[i] > lows[:i].min()
            if not (swept and low <= lows[i] <= high):
                continue
            roof = highs[max(i - 5, 0) : i + 1].max()
            if np.any(closes[i + 1 :] > roof):
                return True
    return False


def resolve(bars, start: int, entry: float, stop: float, up: bool, target: float):
    """First touch of the target or the stop within `HOLD` bars.

    Returns the realised multiple of the stop distance, or `None` if neither is
    reached - unresolved races are dropped rather than scored as flat, the same
    rule `conditional_holds` uses for the same reason.
    """
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    aim = entry - target * risk if up else entry + target * risk
    end = min(start + HOLD + 1, len(bars["close"]))
    for i in range(start, end):
        hit_stop = bars["high"][i] >= stop if up else bars["low"][i] <= stop
        hit_aim = bars["low"][i] <= aim if up else bars["high"][i] >= aim
        if hit_stop and hit_aim:
            # Both in one bar: charge the loss, which is the conservative read
            # and the one a live fill would most often get.
            return -1.0
        if hit_stop:
            return -1.0
        if hit_aim:
            return target
    return None


def setups(bars, lower, name: str, placebo: bool, rng):
    """Every candidate, with which filters it passed and what it would have paid."""
    highs, lows, closes = bars["high"], bars["low"], bars["close"]
    grid = point_size(closes)
    out = []
    for at in engulfings(bars):
        at = int(at)
        if at < LOOKBACK + 2 or at + WAIT + HOLD + 3 >= len(closes):
            continue
        window = slice(at - LOOKBACK, at - 1)
        move = float(np.median(highs[window] - lows[window]))
        if not (move > 0):
            continue
        up = closes[at] < bars["open"][at]  # a bearish engulf is a short
        level = float(highs[window].max()) if up else float(lows[window].min())
        if placebo:
            here = float(closes[at])
            level = here + (level - here) * (1.0 + float(rng.uniform(-JITTER, JITTER)))
        passed = {"engulf": True}
        passed["level"] = rejected(bars, at, level, up, move)
        passed["sweep"] = swept(bars, at, up)
        passed["reversal"] = reversed_structure(bars, at, up)
        passed["internal"] = imbalance(bars, at, up)
        passed["crt"] = candle_range(bars, at, up)
        # The desk's displacement-origin conditions, as separate filters, so
        # "is an engulf the same thing as a displacement origin" is a number.
        unit = move
        passed["displaced"] = displaced(bars, at, up, unit)
        passed["origin body"] = origin_shaped(bars, at, unit)
        zone_low, zone_high = float(lows[at - 1]), float(highs[at - 1])
        passed["structure"] = structure(
            lower, float(bars["time"][at]), float(bars["time"][at + 1]),
            zone_low, zone_high, up,
        ) if lower is not None else False
        # Four readings of the same zone, scored side by side.
        desk_low, desk_high = desk_zone(bars, at, move)
        block = order_block(bars, at, up)
        zones = {
            # The method as published: the engulfed candle's whole range.
            "engulfed": (zone_low, zone_high),
            # The desk's rule: body instead of range when the bar is wide.
            "origin zone": (desk_low, desk_high),
            # The last opposite candle before the move.
            "order block": block if block else (zone_low, zone_high),
        }
        # Entry on the return into each candidate zone, from `at + 2` - because
        # `imbalance` reads bar `at + 1`, and entering there would use a bar the
        # filter had already seen.
        stop = float(highs[at]) if up else float(lows[at])
        cost = float(np.median(bars["spread"][window])) * grid
        fills = {}
        for key, (low, high) in zones.items():
            entry = high if up else low
            if abs(entry - stop) < MIN_RISK * move:
                continue
            for i in range(at + 2, min(at + 2 + WAIT, len(closes))):
                if (highs[i] >= entry) if up else (lows[i] <= entry):
                    fills[key] = (entry, i)
                    break
        if not fills:
            continue
        out.append(
            {
                "feed": name,
                "passed": passed,
                "stop": stop,
                "up": up,
                "cost": cost,
                "fills": fills,
            }
        )
    return out


def score(bars, found, target: float, zone: str = "engulfed"):
    """Expectancy in R over the setups that resolved, gross and net of spread.

    `zone` picks which reading of the entry band to use, so the published
    method's "the engulfed candle's whole range" can be compared directly with
    the desk's `zone_of` rule and with an order block, on the same bars.
    """
    gross, net = [], []
    for got in found:
        if zone not in got["fills"]:
            continue
        entry, filled = got["fills"][zone]
        risk = abs(entry - got["stop"])
        result = resolve(bars, filled, entry, got["stop"], got["up"], target)
        if result is None:
            continue
        gross.append(result)
        # One round trip, charged against the stop distance.
        net.append(result - (got["cost"] / risk if risk > 0 else 0.0))
    if len(gross) < 20:
        return None
    return {
        "n": len(gross),
        "hit": sum(1 for g in gross if g > 0) / len(gross),
        "gross": float(np.mean(gross)),
        "net": float(np.mean(net)),
        "error": float(np.std(net, ddof=1) / np.sqrt(len(net))),
    }


def main() -> None:
    print(
        "A published three-filter setup, decomposed. Entry on the return into the\n"
        "**engulfed** candle's range, stop beyond the engulfing candle, targets in R.\n"
        f"Unresolved races within {HOLD} bars are dropped.\n"
    )
    rng = np.random.default_rng(SEED)
    for signal, confirm in PAIRS:
        for group, names in GROUPS:
            for which in ("real", "walk", "placebo", "twin"):
                rows: dict[str, list] = {}
                frames: dict[str, dict] = {}
                for name in names:
                    bars = load(name, signal)
                    lower = load(name, confirm)
                    if bars is None:
                        continue
                    if which == "twin":
                        bars = shuffled(bars, rng)
                        if bars is None:
                            continue
                    elif which == "walk":
                        bars = walk_like(bars, rng)
                    frames[name] = bars
                    rows[name] = setups(
                        bars,
                        lower if which in {"real", "placebo"} else None,
                        name,
                        which == "placebo",
                        rng,
                    )
                if not rows:
                    continue
                if which == "real":
                    print("=" * 96)
                    print(f"{signal} signal / {confirm} confirm   {group}")
                    print("=" * 96)
                    head = f"  {'arm':<20}{'zone':<12}{'which':<8}{'R':>6}{'n':>7}"
                    print(head + f"{'hit':>8}{'gross R':>9}{'SE':>8}{'z':>7}{'cost R':>8}")
                headline = {"engulf", "EMS", "SLK", "everything", "full origin"}
                for label, need in ARMS:
                    if which in {"twin", "walk"} and "structure" in need:
                        continue
                    zones = ZONES if label in headline else ("engulfed",)
                    for zone, target in ((z, t) for z in zones for t in TARGETS):
                        pooled = []
                        for name, found in rows.items():
                            kept = [
                                g for g in found if all(g["passed"].get(k) for k in need)
                            ]
                            if kept:
                                pooled.append((frames[name], kept))
                        every = [g for _, kept in pooled for g in kept]
                        if len(every) < 20:
                            continue
                        parts = [score(frame, kept, target, zone) for frame, kept in pooled]
                        parts = [p for p in parts if p]
                        if not parts:
                            continue
                        total = sum(p["n"] for p in parts)
                        hit = sum(p["hit"] * p["n"] for p in parts) / total
                        gross = sum(p["gross"] * p["n"] for p in parts) / total
                        net = sum(p["net"] * p["n"] for p in parts) / total
                        error = (sum((p["error"] * p["n"]) ** 2 for p in parts) ** 0.5) / total
                        if total < LEAST_SETUPS:
                            continue
                        cost = gross - net
                        print(
                            f"  {label:<20}{zone[:11]:<12}{which:<8}{target:>6.0f}{total:>7}"
                            f"{hit:>8.3f}{gross:>+9.3f}{error:>8.3f}"
                            f"{gross / error if error else float('nan'):>+7.2f}{cost:>8.3f}"
                        )
            print(
                "  **`gross R` is the column to read, and `cost R` is carried beside it**\n"
                "  rather than subtracted into one number. The spread charged against a\n"
                "  stop that is one candle away can exceed the stop itself - on the\n"
                "  generated feeds it reached 5R - so a net figure ranks instruments by\n"
                "  their spread-to-stop ratio and tells you nothing about the setup. The\n"
                "  cost decides whether a positive gross is tradeable; it is not evidence\n"
                "  about whether the filters select anything.\n"
                "  `placebo` moves the key level to a distance-matched price that is not\n"
                "  one; `twin` block-shuffles whole bars, keeping every candle shape and\n"
                "  destroying the order. `net` charges one spread round trip against the\n"
                "  stop distance. A target of 1 pays 1R and risks 1R, so break-even is a\n"
                "  hit rate of 0.5 and `net R` near zero is a coin after costs.\n"
            )


if __name__ == "__main__":
    main()
