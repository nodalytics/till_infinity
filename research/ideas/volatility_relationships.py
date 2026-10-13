"""Relationships in volatility, in tails, and in factors - none of which is a spread.

Every screen so far lives in **price space**: a linear combination of log levels
with a constant or drifting weight, at widths two to five, contemporaneous or
lagged. All of it is a null apart from currency identities.

**That is the wrong space to be looking in, by this desk's own evidence.** The
standing result across the volatility work, the ladder, the clock and the
forecast work is that *volatility is forecastable and direction is not*. If a
relationship exists here, the prior says it is between **volatilities**.

And a price screen cannot see one. Two instruments can share a single
volatility process with independent signs: no cointegration, no correlation at
any lag, no basket - and a strong, exploitable relationship. `ARM 0` plants
exactly that case and shows the price screen reading nothing on it.

## Four shapes, none of them a spread

* **shared volatility** - do log-volatilities move together, and is their
  relationship stationary where the price relationship is not;
* **volatility spillover** - does one instrument's volatility *lead* another's.
  This is the shape with a direct use: it sizes positions rather than needing a
  spread trade, so it escapes the cost gate that killed everything else;
* **tail co-dependence** - two series near-uncorrelated in the middle can be
  jointly extreme at the edges. A correlation and a Dickey-Fuller `t` are both
  blind to it, and it is the quantity that decides whether diversification
  survives the day it is needed;
* **factor structure** - 20 instruments is not 190 independent questions. A
  factor model asks how many common drivers there are and whether anything
  relates *after* they are removed, which is the question 190 pairwise tests
  were a bad parametrisation of.

## The null has to be a rotation, not a shuffle

The block shuffle used for the price work preserves each leg's marginal tails
exactly, which was the right property there. **It is the wrong null here**,
because scrambling day-long blocks destroys volatility clustering across them -
it would damage the very process under test and make any vol relationship look
significant against a vol-free null.

A **circular rotation** is the correct null: the identical series at a random
offset. Every autocorrelation, every clustering property and all long memory
survive untouched, because it *is* the same series; only the cross-relationship
is destroyed. The offset is drawn away from multiples of the daily period, so
shared time-of-day seasonality does not survive the rotation and get scored as
a relationship.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import random
import statistics
from itertools import combinations

import relationship_screen as screen

#: Bars per volatility observation. 24 at 1h is one day.
SPAN = int(os.environ.get("SPAN", "24"))
#: Lags in volatility observations to scan for spillover, each way.
LAGS = int(os.environ.get("LAGS", "10"))
#: Quantiles at which tail co-dependence is measured.
EDGES = (0.95, 0.99)
#: Null repetitions.
REPS = int(os.environ.get("REPS", "3"))
#: Factors removed before the residual screen.
FACTORS = int(os.environ.get("FACTORS", "3"))
SEED = 20261013
DAY = 24


def rotated(series, rng):
    """The same series at a random offset, which is the null for a process.

    Preserves every marginal property exactly - it is the identical data - and
    destroys any relationship to another series. The offset avoids multiples of
    a day so that shared time-of-day structure does not survive it.
    """
    import numpy as np

    times, values, spread = series
    count = len(values)
    while True:
        shift = rng.randrange(DAY * 5, max(count - DAY * 5, DAY * 6))
        if shift % DAY:
            break
    rolled = np.roll(values, shift)
    # Re-anchor so the wrap point is not a false jump in the level.
    steps = np.diff(rolled)
    rebuilt = np.empty_like(rolled)
    rebuilt[0] = values[0]
    rebuilt[1:] = values[0] + np.cumsum(steps)
    return times, rebuilt, spread


def log_volatility(series, span: int = SPAN):
    """`(times, log sd of returns)` over non-overlapping spans."""
    import numpy as np

    times, values, _ = series
    steps = np.diff(values)
    count = len(steps) // span
    if count < 50:
        return None
    blocks = steps[: count * span].reshape(count, span)
    sd = blocks.std(axis=1)
    keep = sd > 0
    if keep.sum() < 50:
        return None
    stamps = times[1 : count * span + 1 : span][keep]
    return stamps, np.log(sd[keep]), np.zeros(int(keep.sum()))


def correlation(left, right) -> float:
    import numpy as np

    a = np.asarray(left, dtype=float)
    b = np.asarray(right, dtype=float)
    if len(a) < 3 or a.std() == 0 or b.std() == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def spearman(left, right) -> float:
    """Rank correlation, which sees a monotone relationship a linear fit misses."""
    import numpy as np

    a = np.argsort(np.argsort(np.asarray(left, dtype=float)))
    b = np.argsort(np.argsort(np.asarray(right, dtype=float)))
    return correlation(a, b)


def vol_pair(left, right):
    """Level correlation, rank correlation and spread stationarity of log-vols."""
    import numpy as np

    lv, rv = log_volatility(left), log_volatility(right)
    if lv is None or rv is None:
        return None
    got = screen.align(lv, rv)
    if got is None:
        common, li, ri = np.intersect1d(lv[0], rv[0], return_indices=True)
        if len(common) < 50:
            return None
        a, b = lv[1][li], rv[1][ri]
    else:
        _, a, b, _, _ = got
    if len(a) < 50:
        return None
    half = len(a) // 2
    weight = float(np.polyfit(a[:half], b[:half], 1)[0])
    residual = b[half:] - weight * a[half:]
    t = screen.dickey_fuller(residual)[1]
    return {
        "corr": correlation(a, b),
        "rank": spearman(a, b),
        "t": t if math.isfinite(t) else float("nan"),
        "weight": weight,
    }


def spillover(left, right, lags: int = LAGS):
    """Peak cross-correlation of log-volatility *changes*, away from lag zero."""
    import numpy as np

    lv, rv = log_volatility(left), log_volatility(right)
    if lv is None or rv is None:
        return None
    common, li, ri = np.intersect1d(lv[0], rv[0], return_indices=True)
    if len(common) < 4 * lags + 50:
        return None
    da, db = np.diff(lv[1][li]), np.diff(rv[1][ri])
    if da.std() == 0 or db.std() == 0:
        return None
    da = (da - da.mean()) / da.std()
    db = (db - db.mean()) / db.std()
    best, at, same = 0.0, 0, float("nan")
    for k in range(-lags, lags + 1):
        if k < 0:
            x, y = da[-k:], db[: len(db) + k]
        elif k > 0:
            x, y = da[: len(da) - k], db[k:]
        else:
            x, y = da, db
        if not len(x):
            continue
        value = float((x * y).mean())
        if k == 0:
            same = value
        elif abs(value) > abs(best):
            best, at = value, k
    return {"same_span": same, "peak": abs(best), "at": float(at), "signed": best}


def tail_dependence(left, right):
    """`P(|y| past its edge | |x| past its edge)`, less the unconditional rate."""
    import numpy as np

    got = screen.align(left, right)
    if got is None:
        return None
    _, a, b, _, _ = got
    da, db = np.abs(np.diff(a)), np.abs(np.diff(b))
    if len(da) < 500:
        return None
    out = {}
    for edge in EDGES:
        x = da > np.quantile(da, edge)
        y = db > np.quantile(db, edge)
        if x.sum() < 10:
            out[edge] = float("nan")
            continue
        # Lift over the unconditional rate, so 1-edge is the no-dependence point.
        out[edge] = float(y[x].mean() - y.mean())
    return out


def summarise(label: str, values, width: int = 30) -> None:
    values = sorted(v for v in values if math.isfinite(v))
    if not values:
        print(f"{label:<{width}}{'-':>9}")
        return
    print(
        f"{label:<{width}}{len(values):>8,}{values[-1]:>+11.4f}"
        f"{values[max(len(values) - len(values) // 100 - 1, 0)]:>+11.4f}"
        f"{statistics.median(values):>+11.4f}"
    )


def planted_arm() -> None:
    """A shared volatility process with independent signs, which no spread sees."""
    import numpy as np

    print("=" * 104)
    print("ARM 0  a shared volatility process, which the price screens cannot see")
    print("=" * 104)
    rng = np.random.default_rng(5)
    n = 24_000
    when = np.arange(n, dtype=float)
    zeros = np.zeros(n)
    # One AR(1) log-volatility process, two independent sign streams.
    shocks = rng.standard_normal(n)
    logvol = np.zeros(n)
    for i in range(1, n):
        logvol[i] = 0.995 * logvol[i - 1] + 0.1 * shocks[i]
    vol = np.exp(logvol) * 0.001
    one = (when, np.cumsum(vol * rng.standard_normal(n)), zeros)
    two = (when, np.cumsum(vol * rng.standard_normal(n)), zeros)
    apart = (when, np.cumsum(0.001 * rng.standard_normal(n)), zeros)

    print(f"{'':<34}{'price DF t':>12}{'ret corr':>10}{'vol corr':>10}{'vol DF t':>10}")
    for label, left, right in (
        ("shared volatility, free signs", one, two),
        ("unrelated", one, apart),
    ):
        price = screen.screen(left, right)
        vols = vol_pair(left, right)
        rets = correlation(np.diff(left[1]), np.diff(right[1]))
        print(
            f"{label:<34}{price['split_t'] if price else float('nan'):>+12.2f}"
            f"{rets:>+10.4f}{vols['corr']:>+10.4f}{vols['t']:>+10.2f}"
        )
    print(
        "\n**The first row is the whole argument.** A strong relationship with\n"
        "no price cointegration and no return correlation - invisible to every\n"
        "screen built so far, and obvious in volatility space."
    )

    # And a spillover, planted as a lag in the volatility process itself.
    print(f"\n{'':<34}{'same span':>12}{'vol peak':>10}{'at lag':>8}")
    for shift in (0, 2, 5):
        lagged = np.concatenate([np.zeros(shift), vol[: n - shift]]) if shift else vol
        follow = (when, np.cumsum(lagged * rng.standard_normal(n)), zeros)
        got = spillover(one, follow)
        print(
            f"{f'volatility lagged {shift} spans':<34}{got['same_span']:>+12.4f}"
            f"{got['peak']:>10.4f}{got['at']:>8.0f}"
        )


def main() -> None:
    print(
        f"volatility over {SPAN}-bar spans, spillover lags +/-{LAGS} spans, "
        f"tails at {EDGES}, {FACTORS} factors removed\n"
    )
    planted_arm()

    live = [name for name in screen.TRADED if screen.load(name) is not None]
    series = {name: screen.load(name) for name in live}
    rng = random.Random(SEED)
    print(f"\n{len(live)} instruments -> {len(live) * (len(live) - 1) // 2} pairs")

    def both(builder):
        """`(real, null)` for a per-pair statistic, the null by rotation."""
        real, null = [], []
        for a, b in combinations(live, 2):
            got = builder(series[a], series[b])
            if got is not None:
                got["pair"] = f"{a}/{b}"
                real.append(got)
        for _ in range(REPS):
            for a, b in combinations(live, 2):
                got = builder(series[a], rotated(series[b], rng))
                if got is not None:
                    null.append(got)
        return real, null

    print("\n" + "=" * 104)
    print("ARM 1  do volatilities move together more than a rotation of themselves")
    print("=" * 104)
    vols, vols_null = both(vol_pair)
    print(f"{'':<30}{'pairs':>8}{'max':>11}{'99th pct':>11}{'median':>11}")
    for key in ("corr", "rank"):
        summarise(f"traded, vol {key}", [r[key] for r in vols])
        summarise(f"  rotation null, vol {key}", [r[key] for r in vols_null])
    bar = max(r["corr"] for r in vols_null if math.isfinite(r["corr"]))
    beat = [r for r in vols if math.isfinite(r["corr"]) and r["corr"] > bar]
    print(f"\n{len(beat)} of {len(vols)} exceed the null's maximum vol correlation ({bar:+.4f})")
    print(f"\n{'pair':<18}{'vol corr':>10}{'rank':>9}{'vol DF t':>10}{'weight':>9}")
    for got in sorted(vols, key=lambda r: -(r["corr"] if math.isfinite(r["corr"]) else -9))[:12]:
        print(
            f"{got['pair']:<18}{got['corr']:>+10.4f}{got['rank']:>+9.4f}"
            f"{got['t']:>+10.2f}{got['weight']:>+9.3f}"
        )

    print("\n" + "=" * 104)
    print("ARM 2  does one instrument's volatility lead another's")
    print("=" * 104)
    spills, spills_null = both(spillover)
    print(f"{'':<30}{'pairs':>8}{'max':>11}{'99th pct':>11}{'median':>11}")
    summarise("traded, peak away from zero", [r["peak"] for r in spills])
    summarise("  rotation null, peak", [r["peak"] for r in spills_null])
    bar_s = max(r["peak"] for r in spills_null)
    beat_s = [r for r in spills if r["peak"] > bar_s]
    print(f"\n{len(beat_s)} of {len(spills)} exceed the null's maximum peak ({bar_s:.4f})")
    print(f"\n{'pair':<18}{'same span':>11}{'peak away':>11}{'at lag':>8}{'beats':>8}")
    for got in sorted(spills, key=lambda r: -r["peak"])[:12]:
        print(
            f"{got['pair']:<18}{got['same_span']:>+11.4f}{got['peak']:>11.4f}"
            f"{got['at']:>8.0f}{'yes' if got['peak'] > bar_s else '':>8}"
        )

    print("\n" + "=" * 104)
    print("ARM 3  are the tails jointly extreme beyond the middle's correlation")
    print("=" * 104)
    tails, tails_null = [], []
    for a, b in combinations(live, 2):
        got = tail_dependence(series[a], series[b])
        if got is not None:
            got["pair"] = f"{a}/{b}"  # type: ignore[index]
            tails.append(got)
    for _ in range(REPS):
        for a, b in combinations(live, 2):
            got = tail_dependence(series[a], rotated(series[b], rng))
            if got is not None:
                tails_null.append(got)
    print(f"{'':<30}{'pairs':>8}{'max':>11}{'99th pct':>11}{'median':>11}")
    for edge in EDGES:
        summarise(f"traded, lift at {edge:.2f}", [r[edge] for r in tails])
        summarise(f"  rotation null at {edge:.2f}", [r[edge] for r in tails_null])
    bar_t = max(r[0.99] for r in tails_null if math.isfinite(r[0.99]))
    beat_t = [r for r in tails if math.isfinite(r[0.99]) and r[0.99] > bar_t]
    print(f"\n{len(beat_t)} of {len(tails)} exceed the null's maximum 99th lift ({bar_t:+.4f})")
    print(f"\n{'pair':<18}{'lift 0.95':>11}{'lift 0.99':>11}{'beats':>8}")
    for got in sorted(tails, key=lambda r: -(r[0.99] if math.isfinite(r[0.99]) else -9))[:12]:
        print(
            f"{got['pair']:<18}{got[0.95]:>+11.4f}{got[0.99]:>+11.4f}"
            f"{'yes' if math.isfinite(got[0.99]) and got[0.99] > bar_t else '':>8}"
        )

    print("\n" + "=" * 104)
    print("ARM 4  how many common drivers, and is anything left after them")
    print("=" * 104)
    import numpy as np

    times = series[live[0]][0]
    for name in live[1:]:
        times = np.intersect1d(times, series[name][0])
    if len(times) < 2000:
        print("  not enough common bars across every instrument")
        return
    columns = []
    for name in live:
        _, index, _ = np.intersect1d(series[name][0], times, return_indices=True)
        step = np.diff(series[name][1][index])
        columns.append((step - step.mean()) / (step.std() or 1.0))
    matrix = np.column_stack(columns)
    _, singular, right = np.linalg.svd(matrix, full_matrices=False)
    variance = singular**2 / (singular**2).sum()
    print(f"{len(times):,} common bars, {len(live)} instruments")
    print("share of return variance by component:")
    print("  " + "  ".join(f"{v:.3f}" for v in variance[:8]))
    print(f"  first {FACTORS} together: {variance[:FACTORS].sum():.3f}")

    kept = right[:FACTORS]
    residual = matrix - (matrix @ kept.T) @ kept
    print(f"\nafter removing {FACTORS} factors, the strongest residual correlations:")
    pairs = []
    for i, j in combinations(range(len(live)), 2):
        pairs.append((abs(correlation(residual[:, i], residual[:, j])), live[i], live[j]))
    pairs.sort(reverse=True)
    rotation = []
    for _ in range(REPS):
        shuffled = np.column_stack(
            [np.roll(residual[:, k], rng.randrange(100, len(times) - 100)) for k in range(len(live))]
        )
        for i, j in combinations(range(len(live)), 2):
            rotation.append(abs(correlation(shuffled[:, i], shuffled[:, j])))
    bar_f = max(rotation)
    print(f"{'pair':<22}{'|residual corr|':>18}{'beats':>8}")
    for value, a, b in pairs[:10]:
        print(f"{a + '/' + b:<22}{value:>18.4f}{'yes' if value > bar_f else '':>8}")
    print(f"\nrotation null's maximum residual correlation: {bar_f:.4f}")
    print(f"{sum(1 for v, _, _ in pairs if v > bar_f)} of {len(pairs)} exceed it")


if __name__ == "__main__":
    main()
