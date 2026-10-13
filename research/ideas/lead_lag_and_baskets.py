"""Two relationships no cointegration screen can see: a lead, and a basket.

`relationship_screen.py` and `episodic_relationships.py` both test a
**contemporaneous spread between two legs**. Two whole classes of relationship
are invisible to that by construction, and neither is exotic:

## A lead is not a spread

If one instrument moves and another follows an hour later, the two are strongly
related and their *same-bar* spread is noise. Cointegration tests the level
difference now; a lead lives in `corr(d x_t, d y_{t+k})` for `k != 0`, which no
amount of windowing the spread will surface.

This is also the only one of the two that would be **directly tradeable**
rather than requiring a spread position - and this desk has found direction
closed everywhere else it looked, so a lead is the one remaining shape in which
direction could still be predictable.

## A basket is not a pair

A currency triangle is the standard example: `EURUSD`, `GBPUSD` and `EURGBP`
are related by an identity, and no *pair* among them need be cointegrated. More
generally a stationary combination can need three legs, and a pairwise screen
over 190 pairs will find none of it however carefully it is nulled.

190 pairs is 1,140 triples on the same universe, so the multiplicity is worse
and the null matters more, not less.

## Both get the same two disciplines as the pair work

**The same detector for the null**, which here is the two-real-leg block
shuffle: one leg kept, the others replaced by another instrument's returns in
day-long blocks, scrambled. Tails preserved exactly, relationship destroyed.

**A planted arm, so a null is only reported if the detector is shown to find
the thing.** A lead is planted by construction - `follow` is `lead` shifted by
`k` bars plus noise - and a basket by making the third leg a fixed combination
of the first two plus bounded noise. If the detector misses those, its null
says nothing, which is the lesson the episodic work paid for.

## What is reported

For the lead: the cross-correlation of returns at each lag, its peak, and
whether the peak at a **non-zero** lag beats the null's peak over the same lag
range. Scanning lags is itself a multiplicity problem, so the null scans the
identical range.

For the basket: the Dickey-Fuller `t` of the residual from regressing one leg
on the other two, with the weights fitted on the first half and held - the same
split discipline that collapsed the pair screen's live arm from -29 to -3.5.

## What the numbers said

Both detectors pass their planted arms - a lead is recovered at exactly the
planted lag with peak `0.957` where the same-bar correlation reads `0.004`, and
a planted basket reads `-63.5` where **the best pair among the same three legs
reads `-1.22`.** The pairwise blindness is total, not marginal.

**Leads are a null.** Traded pairs peak at a median `0.0194` away from zero
against the null's `0.0166`, max `0.0418` against `0.0307`. Six of 190 exceed
the null's maximum and none of them matters: `0.0418` is about 0.2% of return
variance against a round trip near 3.5%. Four of the six are EUR crosses
sharing a leg with their peak at lag `+/-1`, which is what non-synchronous bar
closes produce, and `XAUUSD/XAGUSD` peaks at lag 8 with a same-bar correlation
of `0.7718`. Nothing here leads anything by an hour.

**Baskets found seven relationships, and all seven are identities.** Traded
best `-77.83` against a null best of `-4.49`, with **7 of 400** beating it and
the eighth falling to `-3.72`, below the null. The seven are every currency
triangle in the universe, with weights fitted at **exactly +/-1.000** and
residual standard deviations of **0.8 to 3.2 basis points** - the spread and
rounding. `log(EURCHF) = log(EURUSD) + log(USDCHF)` is arithmetic. The first
non-triangle triple has fitted weights of `-0.675` and `+0.161` and a residual
of 119 bp, a hundred times larger.

So the objection was right - there were relationships the pair screens could
not see - and the answer is still no: they are definitional and clear 2% to 9%
of their trading cost.

**The triangles are worth keeping as a standing positive control.** Any
relationship screen on an FX universe that does not return them at `t` past
`-50` with weights at `+/-1` is broken, which is a better test than a planted
arm because it runs on the data the screen is actually used on.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import random
import statistics
from itertools import combinations

import relationship_screen as screen

#: Lags in bars to scan, each way. At 1h, 12 covers half a day.
LAGS = int(os.environ.get("LAGS", "12"))
#: Repetitions of the shuffled null.
REPS = int(os.environ.get("REPS", "3"))
#: Cap on triples scored, so the runtime stays sane; the null gets the same cap.
TRIPLES = int(os.environ.get("TRIPLES", "400"))
SEED = 20261013


def returns(series):
    import numpy as np

    return np.diff(series[1])


def cross_correlation(left, right, lags: int = LAGS):
    """`corr(d left_t, d right_{t+k})` for k in -lags..lags, on common bars."""
    import numpy as np

    got = screen.align(left, right)
    if got is None:
        return None
    _, a, b, _, _ = got
    da, db = np.diff(a), np.diff(b)
    if len(da) < 4 * lags + 50:
        return None
    da = (da - da.mean()) / (da.std() or 1.0)
    db = (db - db.mean()) / (db.std() or 1.0)
    out = {}
    for k in range(-lags, lags + 1):
        if k < 0:
            x, y = da[-k:], db[: len(db) + k]
        elif k > 0:
            x, y = da[: len(da) - k], db[k:]
        else:
            x, y = da, db
        out[k] = float((x * y).mean()) if len(x) else float("nan")
    return out


def lead_statistics(curve) -> dict[str, float] | None:
    """The peak absolute correlation away from lag zero, and where it sits."""
    if not curve:
        return None
    away = {k: v for k, v in curve.items() if k != 0 and math.isfinite(v)}
    if not away:
        return None
    best = max(away, key=lambda k: abs(away[k]))
    return {
        "same_bar": curve.get(0, float("nan")),
        "peak": abs(away[best]),
        "at": float(best),
        "signed": away[best],
    }


def basket(first, second, third):
    """DF `t` of `third - w1*first - w2*second`, weights fitted on the first half."""
    import numpy as np

    got = screen.align(first, second)
    if got is None:
        return None
    common, a, b, _, _ = got
    third_times, third_values = third[0], third[1]
    shared, li, ri = np.intersect1d(common, third_times, return_indices=True)
    if len(shared) < screen.LEAST:
        return None
    a, b, c = a[li], b[li], third_values[ri]
    half = len(a) // 2
    if half < screen.LEAST // 2:
        return None
    design = np.column_stack([a[:half], b[:half], np.ones(half)])
    try:
        weights, *_ = np.linalg.lstsq(design, c[:half], rcond=None)
    except np.linalg.LinAlgError:
        return None
    residual = c[half:] - (weights[0] * a[half:] + weights[1] * b[half:] + weights[2])
    t = screen.dickey_fuller(residual)[1]
    return None if not math.isfinite(t) else {"t": t}


def planted_arm() -> None:
    """A planted lead and a planted basket, so a null would mean something."""
    import numpy as np

    print("\n" + "=" * 104)
    print("ARM 0  planted, so that a null is a result rather than a blind spot")
    print("=" * 104)
    n = 8000
    when = np.arange(n, dtype=float)
    zeros = np.zeros(n)
    print(f"{'planted':<34}{'same bar':>11}{'peak away':>11}{'at lag':>9}")
    for shift in (0, 1, 3, 6):
        rng = np.random.default_rng(7)
        steps = rng.standard_normal(n)
        lead = np.cumsum(steps)
        follow_steps = np.concatenate([np.zeros(shift), steps[: n - shift]])
        follow = np.cumsum(follow_steps + rng.standard_normal(n) * 0.3)
        got = lead_statistics(
            cross_correlation((when, lead, zeros), (when, follow, zeros))
        )
        print(
            f"{f'a lead of {shift} bars':<34}{got['same_bar']:>+11.4f}"
            f"{got['peak']:>11.4f}{got['at']:>9.0f}"
        )

    rng = np.random.default_rng(11)
    one = np.cumsum(rng.standard_normal(n))
    two = np.cumsum(rng.standard_normal(n))
    print(f"\n{'planted':<34}{'basket t':>11}{'best pair t':>13}")
    for noise in (0.5, 2.0):
        three = 0.7 * one - 1.3 * two + rng.standard_normal(n) * noise
        legs = [(when, v, zeros) for v in (one, two, three)]
        got = basket(*legs)
        pair = min(
            (screen.screen(x, y) or {"split_t": float("nan")})["split_t"]
            for x, y in combinations(legs, 2)
        )
        print(
            f"{f'a basket, noise {noise}':<34}{got['t']:>+11.2f}{pair:>+13.2f}"
        )
    print(
        "\nThe basket rows are the point: a stationary three-leg combination\n"
        "whose best *pair* is nowhere near significant. A pairwise screen over\n"
        "this universe would report nothing and be wrong."
    )


def main() -> None:
    print(f"lags scanned +/-{LAGS} bars, {REPS} null repetitions\n")
    planted_arm()

    live = [name for name in screen.TRADED if screen.load(name) is not None]
    series = {name: screen.load(name) for name in live}
    rng = random.Random(SEED)

    print("\n" + "=" * 104)
    print("ARM 1  does any pair lead any other")
    print("=" * 104)
    real, null = [], []
    for a, b in combinations(live, 2):
        got = lead_statistics(cross_correlation(series[a], series[b]))
        if got is not None:
            got["pair"] = f"{a}/{b}"  # type: ignore[assignment]
            real.append(got)
    for _ in range(REPS):
        for a, b in combinations(live, 2):
            got = lead_statistics(
                cross_correlation(series[a], screen.block_shuffled(series[b], rng))
            )
            if got is not None:
                null.append(got)
    for label, rows in (("traded", real), ("block-shuffled null", null)):
        peaks = sorted(r["peak"] for r in rows)
        print(
            f"{label:<24}{len(rows):>7,} pairs   median peak away from zero "
            f"{statistics.median(peaks):>7.4f}   max {peaks[-1]:>7.4f}"
        )
    bar = sorted(r["peak"] for r in null)[-1]
    beat = [r for r in real if r["peak"] > bar]
    print(f"\n{len(beat)} of {len(real)} exceed the null's maximum peak ({bar:.4f})")
    print(
        f"\n{'pair':<18}{'same bar':>11}{'peak away':>11}{'at lag':>9}{'beats':>8}"
    )
    for got in sorted(real, key=lambda r: -r["peak"])[:12]:
        print(
            f"{got['pair']:<18}{got['same_bar']:>+11.4f}{got['peak']:>11.4f}"
            f"{got['at']:>9.0f}{'yes' if got['peak'] > bar else '':>8}"
        )

    print("\n" + "=" * 104)
    print("ARM 2  is any three-leg combination stationary")
    print("=" * 104)
    triples = list(combinations(live, 3))[:TRIPLES]
    real_t, null_t = [], []
    for a, b, c in triples:
        got = basket(series[a], series[b], series[c])
        if got is not None:
            got["legs"] = f"{a}/{b}/{c}"  # type: ignore[assignment]
            real_t.append(got)
    for _ in range(REPS):
        for a, b, c in triples:
            got = basket(
                series[a],
                screen.block_shuffled(series[b], rng),
                screen.block_shuffled(series[c], rng),
            )
            if got is not None:
                null_t.append(got)
    for label, rows in (("traded", real_t), ("block-shuffled null", null_t)):
        ts = sorted(r["t"] for r in rows)
        print(
            f"{label:<24}{len(rows):>7,} triples   best {ts[0]:>+8.2f}   "
            f"1st pct {ts[max(len(ts) // 100, 0)]:>+8.2f}   median {statistics.median(ts):>+8.2f}"
        )
    if null_t:
        bar_t = sorted(r["t"] for r in null_t)[0]
        beat_t = sum(1 for r in real_t if r["t"] < bar_t)
        print(f"\n{beat_t} of {len(real_t)} beat the null's best triple ({bar_t:+.2f})")
        print(f"\n{'legs':<30}{'DF t':>9}{'beats':>8}")
        for got in sorted(real_t, key=lambda r: r["t"])[:12]:
            print(
                f"{got['legs']:<30}{got['t']:>+9.2f}"
                f"{'yes' if got['t'] < bar_t else '':>8}"
            )


if __name__ == "__main__":
    main()
