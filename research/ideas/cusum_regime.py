"""CUSUM as published: does its change-point carry a side, or only a location?

LuxAlgo's "Change-Point Detection (CUSUM)", from the Pine source, which is
short enough to reproduce exactly rather than approximately:

    z    = (logret - sma(logret, L)) / stdev(logret, L)
    sPos = max(0, sPos + z - k)
    sNeg = min(0, sNeg + z + k)
    fire = sPos > h (up) or sNeg < -h (down)   then both reset to 0

Defaults L=50, h=4.0, k=0.5. The indicator colours a regime line green or red
from which accumulator tripped, so **the side is a claim** and it is the claim
tested in Part A. Part B asks the question the detector is actually shaped for.

## Part A: the side, against the only null that is matched

A CUSUM fires when a standardised return accumulates past a threshold, which
puts it in the family that produced this desk's most expensive false positive:
a trailing z-score read a +0.137 effect at z 4.23 of which **the shuffled twin
took +0.111** - more than an FX cross's round trip. So three nulls, and the
first is the one that decides it.

* **`flip`** - the same fires, side inverted. Matched on count, on timing, on
  the volatility at entry and on the bar geometry, because it is the same bars.
  A side that carries information beats its own mirror.
* **`placebo`** - as many fires at random bars, side drawn at random. Catches an
  edge that is really the unconditional drift of the sample.
* **`shuffled`** - the same detector on a block-shuffled return series, so the
  marginal distribution and the volatility clustering survive and the ordering
  does not. Catches an edge that is the detector's own construction.

Thresholds are swept and reported **on the mean**, never on a z: a z grid faked
a ridge at exactly the chosen threshold once on this desk, where the mean grid
over the same cells was monotone.

## Part B: the location, against the detector we already run

`statespace/changepoint.py` is Adams-MacKay BOCPD with a Normal-Inverse-Gamma
conjugate, which keeps a posterior over the run length instead of a pair of
accumulators, infers its own measurement variance, and drives the hazard off
elapsed time. If a CUSUM adds anything it has to add it on top of that.

The question is put the way `dispersion-forecast.md` puts every question, so
the answer is comparable to what is already on the shelf: the **increment in
out-of-sample R2 over HAR** on forward log Parkinson variance, same frames,
same classes, same ridge selected on an inner split of the training half.
Topology was measured this way and its best cell was +0.0008, which is zero.
That is the bar.

Two controls carry through both parts: a **shuffled** target, which every arm
must read about zero on, and the Deriv **volatility** family, whose generator
fixes sigma so there is nothing to find.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
for q in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(q))

from dispersion_ml import LAGS, RIDGES, _apply, _design, _r2, _ridge, parkinson  # noqa: E402
from pattern_fingerprint import CACHE, classify, load  # noqa: E402

from till_infinity.statespace.changepoint import Changepoint  # noqa: E402

FRAMES = ("1h", "4h")
TRADED = ("fx_major", "fx_cross", "metal")
CONTROLS = ("volatility",)
PER_CLASS = 6
HORIZONS = (1, 5, 20)

#: The published defaults, first, then the sweep around them.
PUBLISHED = (50, 0.5, 4.0)
LOOKBACKS = (20, 50, 100)
SLACKS = (0.25, 0.5, 1.0)
THRESHOLDS = (2.0, 4.0, 6.0)

#: Bars held after a fire, for Part A. Three spans rather than one, because a
#: detector that fires on a 50-bar window has no stated horizon of its own.
HOLDS = (10, 40, 120)
#: Rewards for the barrier race. The stop is one dispersion unit, so a
#: driftless race pays 1/(1+r) and nothing else needs saying.
REWARDS = (1.0, 2.0, 3.0)
#: Bars of trailing dispersion the unit is measured over. Causal by slicing.
UNIT_BARS = 100
#: Log variance below which a bar is treated as not having traded. `parkinson`
#: floors a non-positive range at `log(1e-300)`; anything near that is a dead
#: bar, and -200 is far below any real bar's log variance (a 1e-43 range).
DEAD_BAR = -200.0
#: Live bars a window needs before it will state a unit.
UNIT_LEAST = 50
#: Block length for the shuffled arm, in bars. Long enough to keep volatility
#: clustering, short enough to destroy the ordering a CUSUM reads.
BLOCK = 24
#: Pooled trades below which a cell prints a dash instead of a number.
#:
#: A forward read over `hold` bars has a standard deviation near `sqrt(hold)`
#: dispersion units, so one instrument's 69 fires at hold 40 carry a standard
#: error of **0.76 units** - and the first run of this harness printed +0.0780
#: on a walk, which is a tenth of its own noise. Four hundred pooled trades
#: puts the standard error near 0.3. That is still large, and saying so is the
#: finding rather than a limitation.
LEAST_TRADES = 400
SEED = 20261017


def cusum(returns: np.ndarray, lookback: int, slack: float, threshold: float):
    """The Pine source, as arrays. Returns (fire index, side) and the states.

    `sPos`/`sNeg` are returned per bar as well, because Part B wants them as
    features and recomputing them is how the two parts drift apart.
    """
    n = len(returns)
    spos = np.zeros(n)
    sneg = np.zeros(n)
    runlen = np.zeros(n)
    fires: list[tuple[int, int]] = []
    pos = neg = 0.0
    since = 0
    for i in range(n):
        if i >= lookback:
            window = returns[i - lookback + 1 : i + 1]
            sd = float(window.std())
            z = (returns[i] - float(window.mean())) / (sd if sd > 0 else 1.0)
            if math.isfinite(z):
                pos = max(0.0, pos + z - slack)
                neg = min(0.0, neg + z + slack)
        up, down = pos > threshold, neg < -threshold
        if up or down:
            fires.append((i, 1 if up else -1))
            pos = neg = 0.0
            since = 0
        else:
            since += 1
        spos[i], sneg[i], runlen[i] = pos, neg, since
    return fires, spos, sneg, runlen


def _units(logvar: np.ndarray) -> np.ndarray:
    """The trailing **relative** dispersion unit: a log-return standard deviation.

    Relative, not a price. Everything downstream therefore measures moves in
    log space, and that is not a stylistic choice - the first version of this
    harness divided a *price difference* by this number and used it as a
    *price offset* for the stop. On a synthetic starting at 1.0 the two
    coincide and it looked right; on gold at 2600 it is wrong by six orders of
    magnitude, which is what the first lab run printed: mean forward reads of
    10^27 units.

    **Dead bars are dropped rather than floored.** `parkinson` floors a
    non-positive range at `log(1e-300)`, which is about -690, and one such bar
    in the window drags a mean of a hundred by -6.9 - so `exp(mean/2)` collapses
    and every move divided by it explodes. Metals and the synthetics both carry
    bars whose high equals their low. So the window averages only the bars that
    traded, and returns nothing where too few did.
    """
    out = np.full(len(logvar), np.nan)
    if len(logvar) <= UNIT_BARS:
        return out
    alive = np.isfinite(logvar) & (logvar > DEAD_BAR)
    values = np.where(alive, logvar, 0.0)
    totals = np.concatenate([[0.0], np.cumsum(values)])
    counts = np.concatenate([[0.0], np.cumsum(alive.astype(float))])
    idx = np.arange(UNIT_BARS, len(logvar))
    n = counts[idx] - counts[idx - UNIT_BARS]
    total = totals[idx] - totals[idx - UNIT_BARS]
    enough = n >= UNIT_LEAST
    means = np.where(enough, total / np.maximum(n, 1.0), np.nan)
    out[idx] = np.exp(means / 2.0)
    return np.where(np.isfinite(out) & (out > 0), out, np.nan)


def _forward(bars, fires, unit, hold: int, flip: bool = False):
    """Mean forward return per fire, in dispersion units. Entry at next open."""
    opens, closes = bars["open"], bars["close"]
    got = []
    for i, side in fires:
        entry_i = i + 1
        exit_i = entry_i + hold
        if exit_i >= len(closes) or not math.isfinite(unit[i]) or unit[i] <= 0:
            continue
        if opens[entry_i] <= 0 or closes[exit_i] <= 0:
            continue
        move = math.log(closes[exit_i] / opens[entry_i]) / unit[i]
        got.append(float((-side if flip else side) * move))
    return got


def _regime(bars, fires, unit, flip: bool = False):
    """Hold each regime to the next change-point, which is the actual claim.

    `trend := changeUp ? 1 : (changeDn ? -1 : trend)` - the published source
    carries the side forward until the next fire, so the indicator is not
    proposing a fixed-hold trade. It is proposing that the market is bullish or
    bearish *until it says otherwise*, and a fixed hold tests a claim nobody
    made. Entry is the open after the fire, exit the close of the bar the next
    fire lands on, so the two are adjacent and nothing overlaps.

    **Overlap matters here and is why the exit is the next fire rather than a
    horizon.** A short skip rule with a long forward window gave direction AUC
    0.79 on this desk that collapsed to 0.51 once the windows stopped sharing
    bars.
    """
    opens, closes = bars["open"], bars["close"]
    got = []
    for (i, side), (j, _) in zip(fires, fires[1:]):
        entry_i = i + 1
        if entry_i >= j or j >= len(closes) or not math.isfinite(unit[i]) or unit[i] <= 0:
            continue
        if opens[entry_i] <= 0 or closes[j] <= 0:
            continue
        move = math.log(closes[j] / opens[entry_i]) / unit[i]
        got.append(float((-side if flip else side) * move))
    return got


def _race(bars, fires, unit, hold: int, reward: float, flip: bool = False):
    """First-touch race, stop at one unit, target at `reward`.

    Ambiguity inside a bar is resolved **against** the trade: a bar that spans
    both levels is a loss. A race scored the other way pays on a martingale,
    which is how this desk learned to score it.
    """
    opens, highs, lows = bars["open"], bars["high"], bars["low"]
    wins = losses = 0
    for i, side in fires:
        entry_i = i + 1
        if entry_i + hold >= len(closes_of(bars)) or not math.isfinite(unit[i]) or unit[i] <= 0:
            continue
        side = -side if flip else side
        entry = opens[entry_i]
        if entry <= 0:
            continue
        # One unit of **log** distance, turned into a price level once. A
        # subtraction here is the dimensional error that produced 10^27.
        stop = entry * math.exp(-side * unit[i])
        target = entry * math.exp(side * reward * unit[i])
        for j in range(entry_i, entry_i + hold):
            hit_stop = lows[j] <= stop if side > 0 else highs[j] >= stop
            hit_target = highs[j] >= target if side > 0 else lows[j] <= target
            if hit_stop:
                losses += 1
                break
            if hit_target:
                wins += 1
                break
    return wins, losses


def closes_of(bars):
    return bars["close"]


def _blocks(n: int, rng) -> np.ndarray:
    """Block-shuffled bar **indices**: clustering kept, ordering destroyed."""
    cuts = [np.arange(i, min(i + BLOCK, n)) for i in range(0, n, BLOCK)]
    rng.shuffle(cuts)
    return np.concatenate(cuts)[:n]


def _rebuilt(bars, order: np.ndarray):
    """A bar series in a shuffled order, each bar still self-consistent.

    **Whole bars move, not returns.** The first version chained block-shuffled
    returns while leaving each bar's original high and low in place, which
    produced bars whose range no longer contained their own open and close - a
    5% close-to-close move inside a 0.1% range. That is not a control on
    ordering, it is a different and impossible market, and it showed up as a
    standard error of 5.55 units on the shuffled arm where the other three read
    0.35.

    So each bar keeps its internal geometry exactly - the log offsets of its
    high, low and close from its own open - and is re-chained onto the running
    price in the shuffled order. The marginal distribution of every bar
    statistic is therefore identical to the real series, bar by bar, and only
    the sequence differs.
    """
    opens, highs, lows, closes = bars["open"], bars["high"], bars["low"], bars["close"]
    safe = np.maximum(opens, 1e-300)
    to_close = np.log(np.maximum(closes, 1e-300) / safe)
    to_high = np.log(np.maximum(highs, 1e-300) / safe)
    to_low = np.log(np.maximum(lows, 1e-300) / safe)
    n = len(order)
    out_open = np.empty(n)
    out_close = np.empty(n)
    price = float(closes[0])
    for position, source in enumerate(order):
        out_open[position] = price
        price = price * math.exp(to_close[source])
        out_close[position] = price
    return {
        "open": out_open,
        "high": out_open * np.exp(to_high[order]),
        "low": out_open * np.exp(to_low[order]),
        "close": out_close,
    }


@dataclass(slots=True)
class Prepared:
    """Everything about one instrument that a threshold sweep does not change.

    Built once. The sweep then re-runs only `cusum` and the forward reads,
    which is the difference between minutes and hours: the first version of
    this file rebuilt the block-shuffled twin and both dispersion-unit series
    for all twenty-seven combinations of `(L, k, h)`.
    """

    bars: dict
    returns: np.ndarray
    unit: np.ndarray
    shuffled_bars: dict
    shuffled_returns: np.ndarray
    shuffled_unit: np.ndarray


def prepare(bars, rng) -> Prepared:
    closes = bars["close"]
    returns = np.diff(np.log(np.maximum(closes, 1e-300)), prepend=0.0)
    unit = _units(parkinson(bars["high"], bars["low"]))
    order = _blocks(len(closes), rng)
    shuffled_bars = _rebuilt(bars, order)
    shuffled_returns = np.diff(np.log(np.maximum(shuffled_bars["close"], 1e-300)), prepend=0.0)
    shuffled_unit = _units(parkinson(shuffled_bars["high"], shuffled_bars["low"]))
    return Prepared(
        bars=bars,
        returns=returns,
        unit=unit,
        shuffled_bars=shuffled_bars,
        shuffled_returns=shuffled_returns,
        shuffled_unit=shuffled_unit,
    )


def swept(
    ready: Prepared, lookback, slack, threshold, hold: int
) -> tuple[list[float], list[float], int]:
    """The signal and flip **trades** at one hold. The caller pools them."""
    fires, _, _, _ = cusum(ready.returns, lookback, slack, threshold)
    if not fires:
        return [], [], 0
    signal = _forward(ready.bars, fires, ready.unit, hold)
    flip = _forward(ready.bars, fires, ready.unit, hold, flip=True)
    return signal, flip, len(fires)


def part_a(ready: Prepared, lookback, slack, threshold, rng) -> dict:
    """The side, four arms, three holds and three rewards."""
    bars, returns, unit = ready.bars, ready.returns, ready.unit
    closes = bars["close"]
    fires, _, _, _ = cusum(returns, lookback, slack, threshold)
    if len(fires) < 20:
        return {}
    shuffled_bars, shuffled_unit = ready.shuffled_bars, ready.shuffled_unit
    shuffled_fires, _, _, _ = cusum(ready.shuffled_returns, lookback, slack, threshold)

    placebo = [
        (int(i), int(rng.choice([-1, 1])))
        for i in rng.choice(
            np.arange(lookback, len(closes) - max(HOLDS) - 2), size=len(fires), replace=False
        )
    ]

    out: dict = {"fires": len(fires)}
    for hold in HOLDS:
        out[f"signal.{hold}"] = _forward(bars, fires, unit, hold)
        out[f"flip.{hold}"] = _forward(bars, fires, unit, hold, flip=True)
        out[f"placebo.{hold}"] = _forward(bars, placebo, unit, hold)
        out[f"shuffled.{hold}"] = _forward(shuffled_bars, shuffled_fires, shuffled_unit, hold)
    out["signal.regime"] = _regime(bars, fires, unit)
    out["flip.regime"] = _regime(bars, fires, unit, flip=True)
    out["placebo.regime"] = _regime(bars, sorted(placebo), unit)
    out["shuffled.regime"] = _regime(shuffled_bars, shuffled_fires, shuffled_unit)
    out["spans"] = [float(j - i) for (i, _), (j, _) in zip(fires, fires[1:])]
    for reward in REWARDS:
        for arm, these, bb, uu in (
            ("signal", fires, bars, unit),
            ("flip", fires, bars, unit),
            ("placebo", placebo, bars, unit),
            ("shuffled", shuffled_fires, shuffled_bars, shuffled_unit),
        ):
            wins, losses = _race(bb, these, uu, max(HOLDS), reward, flip=(arm == "flip"))
            out[f"race.{arm}.{reward}"] = (wins, losses)
    return out


def _fit(x: np.ndarray, y: np.ndarray, cut: int, base: float) -> float:
    """HAR-style ridge, lambda chosen on an inner split of the training half."""
    best, pick = -math.inf, RIDGES[0]
    inner = max(cut // 2, 1)
    for lam in RIDGES:
        coef, _ = _ridge(x[:inner], y[:inner], lam)
        got = _r2(y[inner:cut], _apply(coef, x[inner:cut]), float(y[:inner].mean()))
        if got > best:
            best, pick = got, lam
    coef, _ = _ridge(x[:cut], y[:cut], pick)
    return _r2(y[cut:], _apply(coef, x[cut:]), base)


def _bocpd(series: np.ndarray, frame: str) -> np.ndarray:
    """Our BOCPD's three readings per bar, online and causal.

    The three are the ones the member publishes: `changepoint` (posterior mass
    on a run younger than `FRESH_HOURS`), `run_length` (expected observations
    since the change) and `sd` (the predictive standard deviation, which this
    member infers rather than being told - it is the only one that does).

    `when` advances by the frame's real duration because the hazard is **per
    hour**, not per bar. Feeding 3600 for a 4h bar would tell the model a 4h
    series changes four times as often as it does.
    """
    step = 4.0 * 3600.0 if frame == "4h" else 3600.0
    model = Changepoint()
    out = np.zeros((len(series), 3))
    when = 0.0
    for i, value in enumerate(series):
        when += step
        model.update(float(value), 1.0, when)
        out[i] = (
            float(model.changepoint),
            math.log1p(max(float(model.run_length), 0.0)),
            float(model.sd),
        )
    return out


def part_b(bars, horizon: int, lookback, slack, threshold, frame: str) -> dict:
    """The location: what each detector adds on top of HAR."""
    logvar = parkinson(bars["high"], bars["low"])
    x, y, start = _design(logvar, horizon)
    if len(y) < 600:
        return {}
    cut = len(y) // 2
    base = float(y[:cut].mean())
    rows = slice(start, start + len(y))

    closes = bars["close"]
    returns = np.diff(np.log(np.maximum(closes, 1e-300)), prepend=0.0)
    _, rpos, rneg, rrun = cusum(returns, lookback, slack, threshold)
    _, dpos, dneg, drun = cusum(logvar, lookback, slack, threshold)
    bo = _bocpd(logvar, frame)

    arms = {
        "har": x,
        "har+cusum_ret": np.hstack([x, np.c_[rpos, rneg, np.log1p(rrun)][rows]]),
        "har+cusum_disp": np.hstack([x, np.c_[dpos, dneg, np.log1p(drun)][rows]]),
        "har+bocpd": np.hstack([x, bo[rows]]),
    }
    got = {name: _fit(design, y, cut, base) for name, design in arms.items()}
    shuffled = y.copy()
    np.random.default_rng(SEED).shuffle(shuffled)
    got["har.shuffled"] = _fit(x, shuffled, cut, float(shuffled[:cut].mean()))
    return got


def main() -> None:
    print(
        "CUSUM as published (LuxAlgo), two questions.\n"
        "A: does the side it colours carry anything, against its own flip,\n"
        "   a random-time placebo and a block-shuffled twin? Means, not z.\n"
        "B: does its change-point add to HAR on forward log dispersion, and\n"
        "   does it add more than the BOCPD this desk already runs?\n"
        f"Published defaults L={PUBLISHED[0]} k={PUBLISHED[1]} h={PUBLISHED[2]}.\n"
    )
    rng = np.random.default_rng(SEED)
    groups: dict[str, list[str]] = {}
    for path in sorted(CACHE.glob("*.1h.npz")):
        name = path.name[: -len(".1h.npz")]
        groups.setdefault(classify(name), []).append(name)
    print("classes in the cache:", ", ".join(sorted(groups)), flush=True)

    wanted = {k: v[:PER_CLASS] for k, v in groups.items() if k in TRADED + CONTROLS}

    print("\n=== Part A: the side, at the published defaults")
    lookback, slack, threshold = int(PUBLISHED[0]), float(PUBLISHED[1]), float(PUBLISHED[2])
    for frame in FRAMES:
        for klass, names in sorted(wanted.items()):
            pooled: dict[str, list[float]] = {}
            races: dict[str, list[int]] = {}
            spans: list[float] = []
            fires = 0
            for name in names:
                bars = load(name, frame)
                if bars is None:
                    continue
                got = part_a(prepare(bars, rng), lookback, slack, threshold, rng)
                if not got:
                    continue
                fires += got["fires"]
                # **Trades pooled, not per-instrument means averaged.** A mean
                # of means weights a feed with thirty fires like one with three
                # hundred; and an events guard applied per feed rather than to
                # the pool once dropped 141 of 146 feeds and turned 0.9 sigma
                # into 4.8.
                for hold in (*HOLDS, "regime"):
                    for arm in ("signal", "flip", "placebo", "shuffled"):
                        pooled.setdefault(f"{arm}.{hold}", []).extend(
                            got.get(f"{arm}.{hold}") or []
                        )
                spans.extend(got.get("spans") or [])
                for reward in REWARDS:
                    for arm in ("signal", "flip", "placebo", "shuffled"):
                        wins, losses = got.get(f"race.{arm}.{reward}", (0, 0))
                        cell = races.setdefault(f"{arm}.{reward}", [0, 0])
                        cell[0] += wins
                        cell[1] += losses
            if not pooled:
                continue
            print(f"\n--- {klass}, {frame}: {fires} fires over {len(names)} instruments")
            print(
                f"{'hold':>6}  {'signal':>17} {'flip':>17} {'placebo':>17} {'shuffled':>17}"
                "   mean +/- 1se, dispersion units"
            )
            for hold in (*HOLDS, "regime"):
                cells = []
                for arm in ("signal", "flip", "placebo", "shuffled"):
                    vals = pooled.get(f"{arm}.{hold}") or []
                    if len(vals) < LEAST_TRADES:
                        cells.append(f"{'-':>17}")
                        continue
                    arr = np.asarray(vals)
                    se = float(arr.std(ddof=1)) / math.sqrt(len(arr))
                    cells.append(f"{float(arr.mean()):+9.4f}+/-{se:<6.4f}")
                print(f"{str(hold):>6}  " + " ".join(cells))
            if spans:
                print(
                    f"       regime length: median {np.median(spans):.0f} bars, "
                    f"mean {np.mean(spans):.0f}, n={len(spans)}"
                )
            print(
                f"{'reward':>6}  {'signal':>12} {'flip':>12} {'placebo':>12} "
                f"{'shuffled':>12}  needed"
            )
            for reward in REWARDS:
                cells = []
                for arm in ("signal", "flip", "placebo", "shuffled"):
                    wins, losses = races.get(f"{arm}.{reward}", (0, 0))
                    total = wins + losses
                    cells.append(
                        f"{wins / total:.4f}({total:>5})" if total >= LEAST_TRADES else f"{'-':>12}"
                    )
                print(f"{reward:>6}  " + " ".join(cells) + f"  {1.0 / (1.0 + reward):.4f}")

    print("\n=== Part A: swept, mean forward R at hold 40, signal minus flip")
    print(
        f"{'L':>5} {'k':>5} {'h':>5}  {'signal':>9} {'flip':>9} {'edge':>9} {'se':>9} {'fires':>7}"
    )
    # Prepared once, swept twenty-seven times. The block-shuffled twin and the
    # dispersion units do not depend on `(L, k, h)`.
    ready = []
    for klass, names in sorted(wanted.items()):
        if klass in CONTROLS:
            continue
        for name in names:
            bars = load(name, "1h")
            if bars is not None:
                ready.append(prepare(bars, rng))
    print(f"(prepared {len(ready)} instruments)", flush=True)
    for lb in LOOKBACKS:
        for sl in SLACKS:
            for th in THRESHOLDS:
                sig: list[float] = []
                flp: list[float] = []
                fires = 0
                for one in ready:
                    s_vals, f_vals, count = swept(one, lb, sl, th, 40)
                    fires += count
                    sig.extend(s_vals)
                    flp.extend(f_vals)
                if len(sig) < LEAST_TRADES:
                    continue
                arr = np.asarray(sig)
                s_bar, f_bar = float(arr.mean()), float(np.mean(flp))
                se = float(arr.std(ddof=1)) / math.sqrt(len(arr))
                print(
                    f"{lb:>5} {sl:>5} {th:>5}  {s_bar:+9.4f} {f_bar:+9.4f} "
                    f"{s_bar - f_bar:+9.4f} {se:9.4f} {fires:>7}",
                    flush=True,
                )

    print("\n=== Part B: increment over HAR on forward log dispersion")
    print(
        f"{'cell':>22} {'har':>8} {'+cusum_r':>9} {'+cusum_d':>9} {'+bocpd':>8} "
        f"{'shuffled':>9} {'agree':>6}"
    )
    for frame in FRAMES:
        for horizon in HORIZONS:
            for klass, names in sorted(wanted.items()):
                rows = []
                for name in names:
                    bars = load(name, frame)
                    if bars is None:
                        continue
                    got = part_b(
                        bars, horizon, int(PUBLISHED[0]), PUBLISHED[1], PUBLISHED[2], frame
                    )
                    if got:
                        rows.append(got)
                if not rows:
                    continue
                med = {
                    key: float(np.median([r[key] for r in rows]))
                    for key in (
                        "har",
                        "har+cusum_ret",
                        "har+cusum_disp",
                        "har+bocpd",
                        "har.shuffled",
                    )
                }
                better = sum(1 for r in rows if r["har+cusum_disp"] > r["har"])
                # **The baseline has to be the known one.** `dispersion-forecast.md`
                # measured HAR at 1h h=20 as +0.103 on fx_major, +0.110 on
                # fx_cross and +0.791 on metals. An increment over a HAR that
                # is not reproducing those is an increment over a broken
                # opponent, which is how an ESN once read +0.565 against a
                # ridge crippled at a fixed 1e-8.
                if klass in TRADED and horizon == 20 and med["har"] < 0.05:
                    print(
                        f"  WARN {klass} {frame} h=20: HAR reads {med['har']:+.4f}, "
                        "below the +0.10 this cell is known to give. The increments "
                        "below are against a baseline that is not reproducing."
                    )
                print(
                    f"{klass + ' ' + frame + ' h=' + str(horizon):>22} "
                    f"{med['har']:+8.4f} "
                    f"{med['har+cusum_ret'] - med['har']:+9.4f} "
                    f"{med['har+cusum_disp'] - med['har']:+9.4f} "
                    f"{med['har+bocpd'] - med['har']:+8.4f} "
                    f"{med['har.shuffled']:+9.4f} {better:>3}/{len(rows):<2}",
                    flush=True,
                )


if __name__ == "__main__":
    main()
