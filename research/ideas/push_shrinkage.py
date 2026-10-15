"""One shrinkage weight, estimated from a direction rate, applied to a continuous mean.

`reactions.infer` shrinks a level's own record toward its neighbours' with one
weight:

    weight = own.touches / (own.touches + prior_weight)
    probability = weight * own.probability_up(...) + (1 - weight) * prior_up
    push        = weight * own.mean_push          + (1 - weight) * prior_push

`prior_weight` is `PRIOR_WEIGHT = 4.0` until the pool can measure it, and then
it is `engine._prior_weight`, which calls `shrinkage.prior_weight` on samples of
`(stats.touches, stats.ups)` - the **direction rate**. The closed form it uses
is right for that rate: `K = p(1-p) / tau_squared`, a touch's own binomial noise
over the real spread between levels.

**The same `K` is then applied to `mean_push`, which is not a rate.** A
continuous mean's sampling variance is `s_squared / n`, not `p(1-p) / n`, and its
between-level spread is a different number in different units. Nothing says the
two ratios agree, so `expected_push` is being pooled by a weight borrowed from
another quantity's dispersion.

Two further reasons to look: `prod-probability-up-needs-halving` measured the
direction rate as carrying no signal, and a `tau` of zero sends `prior_weight`
straight to `MAX_WEIGHT = 50.0` by design - "no measurable spread between
levels: pool hard". And `SideStats.decay` multiplies `touches` by a factor, so
`n` is a decayed pseudo-count: the binomial variance `p(1-p)/n` is **overstated**,
more of the observed spread is charged to noise, and `tau` is biased down. Both
push `K` toward the clamp, where a level needs fifty touches to be heard half.

So, in order:

1. what `K` production's own estimator returns on reconstructed levels;
2. whether levels differ in **mean push** and **mean sweep depth** at all, by
   the continuous counterpart of the same decomposition, which the library does
   not have;
3. what `K` those quantities imply, against the one production uses;
4. whether any of it predicts out of sample, against the pooled mean.

Every arm carries a distance-matched placebo price and the generated feeds, and
the null for a continuous `tau` is a label shuffle at fixed counts rather than a
threshold - the lesson `dispersion.differ` already records.
"""

from __future__ import annotations

import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from till_infinity.structures.shrinkage import prior_weight as prod_weight  # noqa: E402
from till_infinity.structures.shrinkage import tau_squared  # noqa: E402

CACHE = Path.home() / "till_infinity/data/seqlab"
FRAMES = ("1h", "4h")
LIMIT = 40000
LOOKBACK = 100
PER_FEED = 60
PATIENCE = 24
#: Resolved interactions a level needs to enter the study.
LEAST = 12
#: Interactions used as history before an outcome is scored.
WARM = 5
#: Levels a pool needs before a `tau` is reported, matching `shrinkage`.
UNITS = 12
JITTER = 0.15
DRAWS = 400
SEED = 20261015
TRADED = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "AUDUSD", "USDCAD")
GENERATED = ("Volatility_75_Index", "Volatility_100_Index", "Step_Index", "Step_Index_200")
#: The positive control. `Range_Break_*` has a range **by construction**, so
#: levels really do exist on it and really do differ - a test that reads null
#: here is a test without power, not a market without levels. Carried because
#: every null in this study is otherwise unfalsifiable.
CONTROL = ("Range_Break_100_Index", "Range_Break_200_Index")
GROUPS = (("traded", TRADED), ("generated", GENERATED), ("range-break", CONTROL))
#: Planted between-level spreads, as a per-level **additive** offset whose sd
#: is this share of the pooled mean. The power curve: `tau` should come back
#: near `pooled * share`. See `planted` for why a multiplier does not work.
PLANTS = (0.0, 0.05, 0.10, 0.20)
#: Shrinkage weights scored in arm 4. 50 is `shrinkage.MAX_WEIGHT`, where a
#: `tau` of zero sends production; 4 is `reactions.PRIOR_WEIGHT`.
KAYS = (0.0, 4.0, 50.0)


def load(name: str, frame: str):
    import numpy as np

    path = CACHE / f"{name}.{frame}.npz"
    if not path.exists():
        return None
    with np.load(path) as bundle:
        need = {"time", "high", "low", "close"}
        if not need <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        got = {k: np.asarray(bundle[k], dtype=float)[order] for k in need}
    keep = (got["high"] >= got["low"]) & (got["low"] > 0)
    got = {k: v[keep] for k, v in got.items()}
    if len(got["close"]) < 8000:
        return None
    if len(got["close"]) > LIMIT:
        got = {k: v[-LIMIT:] for k, v in got.items()}
    return got


def interactions(bars, level: float, start: int, move: float) -> list[tuple[bool, ...]]:
    """Every resolved interaction with `level` after `start`, oldest first.

    `(held, wick, depth, push)` per interaction, every distance in `move`
    units so they are comparable across feeds:

    * `held` - price travelled one `move` back the way it came before one
      `move` through, the same race `conditional_holds` settles.
    * `wick` - how far past the level the **touching bar** reached, which is
      what `SideStats.observe_wick` is given and `wick_deep_vol` turns into a
      stop distance. Uncensored.
    * `depth` - how far past the level price reached over the whole race. The
      same quantity measured longer, and on a hold the race caps it at one
      `move` by construction, so it lives in [0, 1) and the two disagree on
      purpose.
    * `push` - how far price reached on the resolving side within `PATIENCE`,
      the magnitude `mean_push` averages and `expected_push` publishes.
    """
    highs, lows, closes = bars["high"], bars["low"], bars["close"]
    out: list[tuple[bool, ...]] = []
    i, end = start, len(highs)
    while i < end:
        if not (lows[i] <= level <= highs[i]):
            i += 1
            continue
        before = closes[i - 1] if i > 0 else closes[i]
        from_below = before < level
        back = level - move if from_below else level + move
        through = level + move if from_below else level - move
        settled: bool | None = None
        j = i + 1
        while j < min(i + 1 + PATIENCE, end):
            if (highs[j] >= through) if from_below else (lows[j] <= through):
                settled = False
                break
            if (lows[j] <= back) if from_below else (highs[j] >= back):
                settled = True
                break
            j += 1
        if settled is not None:
            span = slice(i, min(j + 1, end))
            above = float(highs[span].max()) - level
            below = level - float(lows[span].min())
            # Beyond the level is up when price arrived from below. The
            # resolving side is back the way it came on a hold, through on a
            # break - the other one of the same pair.
            beyond = above if from_below else below
            went = (from_below and not settled) or (not from_below and settled)
            reach = above if went else below
            wick = float(highs[i]) - level if from_below else level - float(lows[i])
            out.append(
                (
                    settled,
                    max(0.0, wick) / move,
                    max(0.0, beyond) / move,
                    max(0.0, reach) / move,
                )
            )
        i = j + 1
    return out


def spread_of_means(groups: list[list[float]]) -> tuple[float, float, int, list[int]]:
    """`(tau, pooled, units, counts)` for a per-unit **mean**.

    DerSimonian and Laird on a continuous quantity, which `shrinkage` and
    `dispersion` only have for a rate. The one change is the within-unit
    variance: `s_squared / n` from the unit's own observations, where a rate
    uses `p(1-p) / n` from the pool. Everything after that is identical -
    inverse-variance weights, the weighted spread about the pooled mean, and
    subtract the degrees of freedom sampling alone would have produced.
    """
    usable: list[tuple[float, float, int]] = []
    for values in groups:
        n = len(values)
        if n < LEAST:
            continue
        mean = sum(values) / n
        var = sum((v - mean) ** 2 for v in values) / (n - 1)
        if var <= 0.0:
            continue
        usable.append((mean, var / n, n))
    if len(usable) < UNITS:
        return float("nan"), float("nan"), len(usable), []
    weights = sum(1.0 / v for _, v, _ in usable)
    pooled = sum(m / v for m, v, _ in usable) / weights
    q = sum((m - pooled) ** 2 / v for m, v, _ in usable)
    squared = sum((1.0 / v) ** 2 for _, v, _ in usable)
    divisor = weights - squared / weights
    tau2 = max(0.0, (q - (len(usable) - 1)) / divisor) if divisor > 0.0 else 0.0
    return math.sqrt(tau2), pooled, len(usable), [n for _, _, n in usable]


def dependence(groups: list[list[float]]) -> float:
    """Mean within-unit lag-1 autocorrelation, which sets the null's block size.

    The one number that decides how conservative `shuffled_tau` has to be. A
    unit's own mean is removed first, so this is dependence *inside* a level and
    not the between-level spread the study is about.
    """
    got: list[float] = []
    for values in groups:
        if len(values) < LEAST:
            continue
        mean = sum(values) / len(values)
        centred = [v - mean for v in values]
        top = sum(a * b for a, b in zip(centred, centred[1:], strict=False))
        bottom = sum(v * v for v in centred)
        if bottom > 0.0:
            got.append(top / bottom)
    return sum(got) / len(got) if got else float("nan")


def shuffled_tau(
    groups: list[list[float]], draws: int, seed: int, block: int = 0
) -> tuple[float, float]:
    """`(median null tau, p)` from reassigning observations at fixed counts.

    The null is "these units are the same unit": deal every observation back
    out in the same group sizes and recompute. No distribution is assumed and
    the counts - which is what drives the noise floor - are exactly preserved.

    **`blocks` is on, and an i.i.d. shuffle is not an acceptable null here.**
    Dealing single observations destroys serial dependence *within* a unit,
    which inflates nothing in the null and so lowers the floor. Measured on
    identical units with an AR(1) inside each: an i.i.d. shuffle rejects at
    p <= 0.05 on **100%** of trials at rho of 0.3 and 0.6, against 7% at rho of
    zero. A real level's consecutive touches are correlated, so the i.i.d.
    version would have reported that every pool of levels differs.

    The block version deals each unit a **contiguous** run from the units laid
    end to end at a random circular offset, so a drawn unit carries dependence
    at the same scale a real one does. Blocks straddle unit boundaries, which
    is what mixes the identities.

    **`block` is the length of those runs and it is a real trade-off, not a
    detail.** It has to exceed the dependence scale or the floor drops, and stay
    under the unit length or the null inherits the unit's own mean and eats the
    effect. Measured on 150 identical units of 30 observations with an AR(1)
    inside each, as (size at rho 0.3, size at rho 0.6, power at a planted 5%):

        L = 3   ->  0.75, 1.00, 1.00      floor far too low
        L = 8   ->  0.12, 0.88, 0.69
        L = 16  ->  0.00, 0.19, 0.38
        L = 30  ->  0.00, 0.06, 0.06      correct size, little power

    So with strong dependence only a whole-unit block is honest, and it costs
    almost all the power against a small effect. `block` of 0 means the unit's
    own length, which is that conservative default; anything else is a
    sensitivity arm to be read beside the measured `dependence`.
    """
    observed, _, used, counts = spread_of_means(groups)
    if not counts or math.isnan(observed):
        return float("nan"), float("nan")
    laid = [v for values in groups if len(values) >= LEAST for v in values]
    size = len(laid)
    rng = random.Random(seed)
    nulls: list[float] = []
    over = 0
    for _ in range(draws):
        drawn: list[list[float]] = []
        for n in counts:
            length = n if block <= 0 else min(block, n)
            values: list[float] = []
            while len(values) < n:
                at = rng.randrange(size)
                take = min(length, n - len(values))
                values.extend(laid[(at + step) % size] for step in range(take))
            drawn.append(values)
        got, _, _, _ = spread_of_means(drawn)
        if math.isnan(got):
            continue
        nulls.append(got)
        over += got >= observed
    if not nulls:
        return float("nan"), float("nan")
    nulls.sort()
    return nulls[len(nulls) // 2], (over + 1) / (len(nulls) + 1)


def within_feed_tau(rows: list[tuple[str, list[float]]]) -> tuple[float, int]:
    """`(median within-feed tau, feeds counted)`.

    `spread_of_means` over every level at once charges the between-**feed**
    spread to `tau`, because a level on XAUUSD and one on EURUSD are different
    units of the same pool. That inflates the observed figure - and the block
    null inherits the same mixture, so it inflates the floor too, which is why
    the pooled reading is usable. This is the clean version: `tau` inside each
    feed separately, where no instrument difference can contribute.
    """
    byfeed: dict[str, list[list[float]]] = {}
    for feed, values in rows:
        byfeed.setdefault(feed, []).append(values)
    got = []
    for groups in byfeed.values():
        tau, _pooled, used, _counts = spread_of_means(groups)
        if not math.isnan(tau) and used >= UNITS:
            got.append(tau)
    if not got:
        return float("nan"), 0
    got.sort()
    return got[len(got) // 2], len(got)


def implied_weight(groups: list[list[float]]) -> tuple[float, float]:
    """`(K, tau)` for a continuous mean: within-unit variance over `tau_squared`.

    The same ratio `shrinkage.prior_weight` forms for a rate, with the rate's
    `p(1-p)` replaced by the pooled within-unit variance. Unclamped, so the
    figure can be compared with production's clamp rather than hidden by it.
    """
    tau, _pooled, used, _counts = spread_of_means(groups)
    if math.isnan(tau) or used < UNITS:
        return float("nan"), tau
    within: list[float] = []
    for values in groups:
        if len(values) < LEAST:
            continue
        mean = sum(values) / len(values)
        within.append(sum((v - mean) ** 2 for v in values) / (len(values) - 1))
    pooled_within = sum(within) / len(within) if within else float("nan")
    if not (tau > 0.0):
        return float("inf"), tau
    return pooled_within / (tau * tau), tau


def logged(rows: list[tuple[str, list[float]]]) -> list[tuple[str, list[float]]]:
    """The same levels in log space, and this is not a cosmetic transform.

    The positive control is what forced it. `Range_Break_*` has a range **by
    construction**, so its levels really do differ, and the raw-mean version of
    arm 2 read null there - wick `tau` 0.4785 against a null of 0.4782 - while
    arm 4's MSE came back at **577** against 1.79 on traded instruments. The
    reason is the quantity, not the method: `move` is the median bar range
    inside a quiet range, a break runs hundreds of those in one bar, and a
    per-level **mean** of something that heavy-tailed is carried by its largest
    one or two observations. Within-level variance then swamps any between-level
    difference, so nothing is detectable even where the structure is real.

    `log1p` fixes three things at once. The tail becomes finite, so a mean and
    its sampling variance mean something. A per-level effect on a positive
    quantity is naturally **multiplicative** - a level that gets swept twice as
    deep, not half a bar deeper - and in logs that is the additive shift this
    test is built to find. And `log1p` rather than `log` because a depth of
    exactly zero is common and legitimate.
    """
    return [(feed, [math.log1p(v) for v in values]) for feed, values in rows]


def planted(
    groups: list[list[float]], share: float, seed: int, absolute: bool = False
) -> list[list[float]]:
    """Each unit's observations **shifted** by its own offset.

    Additive, and a multiplicative version does not work. The first run of this
    harness used a per-unit lognormal **factor**, which scales a unit's own
    spread along with its mean - so the ratio this test forms is unchanged and
    the plant is invisible. Measured: a factor with a log-sd of 0.20 moved `tau`
    by less than 0.004 on every quantity and frame, where the between-level sd
    it implies is 0.07 to 0.36. On a scale-free statistic a scale-free plant is
    not an effect.

    The additive version moves a unit's mean and leaves its within-unit variance
    alone, which is the effect a per-level estimator would be trying to find.
    `share` is the offset's sd as a fraction of the pooled mean, so the
    between-unit `tau` it should produce is `pooled * share`. With `absolute`
    it is the sd itself, which is what log space wants: an offset of 0.10 in
    logs is a 10% multiplicative spread between levels, the same number on
    every quantity and frame. Values are clipped at zero because all three
    quantities are distances, and a log-space value cannot go below `log1p(0)`.
    """
    if share <= 0.0:
        return groups
    sizes = [len(v) for v in groups if len(v) >= LEAST]
    if not sizes:
        return groups
    pooled = (
        1.0 if absolute else sum(sum(v) for v in groups if len(v) >= LEAST) / sum(sizes)
    )
    rng = random.Random(seed)
    out: list[list[float]] = []
    for values in groups:
        offset = rng.gauss(0.0, pooled * share)
        out.append([max(0.0, v + offset) for v in values])
    return out


def predict(
    rows: list[tuple[str, list[float]]], kays: tuple[float, ...]
) -> dict[str, tuple[float, float]]:
    """Out-of-sample error per shrinkage weight, as `(MSE, MAE)`.

    Walk-forward: a unit's first `i` observations predict its `i`-th, shrunk
    toward the pool. Every pool is leave-one-out, so a unit never informs its
    own baseline. `K = 0` is the unit's own mean with no pooling, large `K` is
    the pooled mean, and `reactions.infer` is `K` of 50 because that is where
    arm 1 shows production's estimate pinned.

    **The pool is the unit's own feed, and that is the whole point.** The first
    run pooled across all six traded instruments, and a level's own record beat
    that by 0.112 of MSE on push - which reads as a per-level effect and is a
    per-**feed** one: push in median-bar-range units is not the same size on
    XAUUSD as on EURUSD, so a level's own mean was being credited for knowing
    which instrument it was on. The generated arm, whose two feeds are alike,
    showed the gain **reversed** at -0.004 in the same run, which is the tell.
    Both baselines are reported so the difference is visible rather than
    assumed.
    """
    kept = [(feed, values) for feed, values in rows if len(values) >= LEAST]
    if len(kept) < UNITS:
        return {}
    means = [sum(values) / len(values) for _, values in kept]
    total = sum(means)
    #: Per-feed sums, for the baseline that already knows the instrument.
    feeds: dict[str, list[float]] = {}
    for (feed, _), mean in zip(kept, means, strict=True):
        held = feeds.setdefault(feed, [0.0, 0.0])
        held[0] += mean
        held[1] += 1.0
    scored: dict[str, list[tuple[float, float]]] = {}
    for (feed, values), mean in zip(kept, means, strict=True):
        everywhere = (total - mean) / (len(means) - 1)
        count = feeds[feed][1]
        here = (feeds[feed][0] - mean) / (count - 1) if count > 1 else everywhere
        for i in range(WARM, len(values)):
            own = sum(values[:i]) / i
            truth = values[i]
            for arm, guess in (("all levels", everywhere), ("this feed", here)):
                scored.setdefault(arm, []).append(((guess - truth) ** 2, abs(guess - truth)))
            for k in kays:
                shrunk = own if k <= 0.0 else (own * i + here * k) / (i + k)
                scored.setdefault(f"K={k:g}", []).append(
                    ((shrunk - truth) ** 2, abs(shrunk - truth))
                )
    return {
        arm: (sum(a for a, _ in rows) / len(rows), sum(b for _, b in rows) / len(rows))
        for arm, rows in scored.items()
        if rows
    }


def gather(names: tuple[str, ...], frame: str):
    """Per-level observations for real levels and for distance-matched placebos.

    Each continuous quantity is `(feed, values)` per level, because `predict`
    needs to pool within a feed and a bare list cannot say which feed a level
    came from.
    """
    import numpy as np

    rng = np.random.default_rng(SEED)
    out = {
        which: {"wick": [], "depth": [], "push": [], "rate": []} for which in ("real", "fake")
    }
    for name in names:
        bars = load(name, frame)
        if bars is None:
            continue
        closes, highs, lows = bars["close"], bars["high"], bars["low"]
        starts = np.linspace(LOOKBACK, len(closes) - 500, PER_FEED, dtype=int)
        for k, at in enumerate(starts):
            window = slice(max(at - LOOKBACK, 0), at)
            move = float(np.median(highs[window] - lows[window]))
            if not (move > 0):
                continue
            level = float(highs[window].max() if k % 2 == 0 else lows[window].min())
            here = float(closes[at])
            gap = level - here
            if abs(gap) < 0.25 * move:
                continue
            scale = 1.0 + float(rng.uniform(-JITTER, JITTER))
            for which, price in (("real", level), ("fake", here + gap * scale)):
                got = interactions(bars, price, int(at), move)
                if len(got) < LEAST:
                    continue
                out[which]["wick"].append((name, [w for _, w, _, _ in got]))
                out[which]["depth"].append((name, [d for held, _, d, _ in got if held]))
                out[which]["push"].append((name, [p for _, _, _, p in got]))
                # `(touches, ups)` exactly as `engine._prior_weight` builds it.
                out[which]["rate"].append(
                    (float(len(got)), float(sum(1 for held, *_ in got if held)))
                )
    return out


def main() -> None:
    print(
        f"{LOOKBACK}-bar extremes, {LEAST}+ resolved interactions, patience {PATIENCE} bars.\n"
        f"depth and push in median-bar-range units. null = {DRAWS} label shuffles "
        "at fixed counts.\n"
    )
    for frame in FRAMES:
        for group, names in GROUPS:
            got = gather(names, frame)
            if not got["real"]["push"]:
                continue
            print("=" * 94)
            print(f"{frame}  {group}")
            print("=" * 94)

            print("ARM 1  the weight production's own estimator returns, from the rate")
            held: dict[str, tuple[float, float]] = {}
            for which in ("real", "fake"):
                rows = got[which]["rate"]
                touches = sum(n for n, _ in rows)
                if touches <= 0 or len(rows) < UNITS:
                    continue
                hits = sum(h for _, h in rows)
                mean = hits / touches
                held[which] = (touches, hits)
                tau2, used = tau_squared(rows, mean)
                k = prod_weight(rows, 4.0)
                print(
                    f"  {which:<6} pooled {mean:.4f}  tau {math.sqrt(tau2):.4f}  over "
                    f"{used:>3} levels, {int(touches):>6,} interactions  ->  K = {k:.2f}"
                    + ("   (at the clamp)" if k >= 50.0 else "")
                )
            if {"real", "fake"} <= held.keys():
                # Do real levels hold more often than prices that are not levels?
                # A different question from `tau`, and the one `Range_Break_*` is
                # a construction-guaranteed control for: its boundaries are real,
                # so a desk that cannot see them here cannot see them anywhere.
                (n1, h1), (n2, h2) = held["real"], held["fake"]
                pooled = (h1 + h2) / (n1 + n2)
                error = math.sqrt(pooled * (1.0 - pooled) * (1.0 / n1 + 1.0 / n2))
                gap = h1 / n1 - h2 / n2
                print(
                    f"  real - placebo = {gap:+.4f}  SE {error:.4f}  "
                    f"z {gap / error if error else float('nan'):+.2f}"
                )
            print(
                "  `K` is `p(1-p)/tau_squared`, clamped to [0.5, 50]. This is the number\n"
                "  `reactions.infer` uses for `push` as well, which is the question. The\n"
                "  `z` is the **pooled** level effect, which is not what `K` depends on:\n"
                "  a population of real levels that all behave alike has a large `z` and\n"
                "  a `tau` of zero, and then pooling hard is right.\n"
            )

            print("ARM 2  do levels differ in these continuous quantities at all")
            head = f"  {'what':<6}{'space':<5}{'arm':<6}{'levels':>7}{'rho':>7}{'tau':>9}"
            print(head + f"{'null':>9}{'p':>8}{'null8':>9}{'p8':>8}{'in-feed':>9}{'K':>9}")
            for quantity in ("wick", "depth", "push"):
                for space in ("raw", "log"):
                    for which in ("real", "fake"):
                        rows = got[which][quantity]
                        rows = rows if space == "raw" else logged(rows)
                        groups = [values for _, values in rows]
                        tau, pooled, used, _counts = spread_of_means(groups)
                        if math.isnan(tau):
                            continue
                        null, p = shuffled_tau(groups, DRAWS, SEED)
                        short, short_p = shuffled_tau(groups, DRAWS, SEED, block=8)
                        k, _ = implied_weight(groups)
                        inside, _feeds = within_feed_tau(rows)
                        rho = dependence(groups)
                        print(
                            f"  {quantity:<6}{space:<5}{which:<6}{used:>7}{rho:>7.3f}"
                            f"{tau:>9.4f}{null:>9.4f}{p:>8.3f}{short:>9.4f}"
                            f"{short_p:>8.3f}{inside:>9.4f}{k:>9.1f}"
                        )
                        _ = pooled
            print(
                "  `rho` is the mean lag-1 autocorrelation **inside** a level, which is\n"
                "  what decides how long the null's blocks have to be. `null`/`p` use a\n"
                "  whole-unit block, which has correct size under any dependence and\n"
                "  little power against a small effect; `null8`/`p8` use a block of 8,\n"
                "  which has far more power and is only honest if `rho` is small. Read\n"
                "  the pair, not either alone. `in-feed` is `tau` computed inside one\n"
                "  instrument so no between-feed difference can contribute, and `K` the\n"
                "  weight this quantity implies, unclamped, against arm 1's.\n"
            )

            print("ARM 3  power, in log space: shift each level and look again")
            head = f"  {'quantity':<8}{'share':>7}{'tau':>9}{'excess':>9}"
            print(head + f"{'null':>9}{'p':>8}{'p8':>8}")
            for quantity in ("wick", "depth", "push"):
                groups = [values for _, values in logged(got["real"][quantity])]
                _base, pooled, used, _counts = spread_of_means(groups)
                if used < UNITS or math.isnan(pooled):
                    continue
                for share in PLANTS:
                    spiked = planted(groups, share, SEED + int(share * 1000), absolute=True)
                    tau, _p, _u, _c = spread_of_means(spiked)
                    null, p = shuffled_tau(spiked, DRAWS, SEED)
                    _short, short_p = shuffled_tau(spiked, DRAWS, SEED, block=8)
                    print(
                        f"  {quantity:<8}{share:>7.2f}{tau:>9.4f}"
                        f"{tau - null:>+9.4f}{null:>9.4f}{p:>8.3f}{short_p:>8.3f}"
                    )
            print(
                "  `planted` is `pooled * share`, the between-level sd the offsets add.\n"
                "  A row whose `tau` rises with it is a test with power; the `share` of\n"
                "  zero row is the data unplanted, and `excess` is `tau` over its own\n"
                "  null, which is the effect size the floor has not already eaten.\n"
            )

            print("ARM 4  does a level's own record beat knowing only its instrument")
            head = f"  {'what':<6}{'space':<5}{'arm':<11}{'MSE':>10}{'vs feed':>10}"
            print(head + f"{'MAE':>9}   {'placebo MSE':>12}{'placebo vs':>11}")
            for quantity in ("wick", "depth", "push"):
                for space in ("raw", "log"):
                    real = got["real"][quantity]
                    fakes = got["fake"][quantity]
                    if space == "log":
                        real, fakes = logged(real), logged(fakes)
                    scored = predict(real, KAYS)
                    shadow = predict(fakes, KAYS)
                    if not scored:
                        continue
                    base = scored.get("this feed", (float("nan"), float("nan")))[0]
                    shade = shadow.get("this feed", (float("nan"), float("nan")))[0]
                    for arm in ("all levels", "this feed", *[f"K={k:g}" for k in KAYS]):
                        if arm not in scored:
                            continue
                        mse, mae = scored[arm]
                        fake = shadow.get(arm, (float("nan"), float("nan")))[0]
                        print(
                            f"  {quantity:<6}{space:<5}{arm:<11}{mse:>10.4f}"
                            f"{base - mse:>+10.5f}{mae:>9.4f}   {fake:>12.4f}"
                            f"{shade - fake:>+11.5f}"
                        )
            print(
                "  `vs feed` is positive when the arm beats predicting that instrument's\n"
                "  pooled mean - the baseline that already knows everything except which\n"
                "  level this is. `all levels` is the weaker baseline the first run used.\n"
                "  The placebo columns are the same arms on distance-matched prices that\n"
                "  are not levels: a gain they share is not a gain from a level.\n"
            )


if __name__ == "__main__":
    main()
