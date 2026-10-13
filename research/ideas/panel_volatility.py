"""Forecasting one instrument's volatility with the others', which is what a factor is for.

The relationship work found volatility co-movement that is large and
**contemporaneous**: median cross-instrument correlation of log-volatility
`0.5170` against a rotation null's `-0.0015`, with 104 of 107 pairs beating the
null's maximum, and residuals after three principal components still correlated
up to `0.9422` along currency lines.

Contemporaneous structure cannot be turned into a directional bet, and that was
reported. **It was then wrongly allowed to imply it cannot be used at all.**

## Denoising a state is not predicting a relationship

A contemporaneous relationship improves the estimate of **now**. Own realised
volatility at `t` is a noisy measurement of instrument `i`'s true volatility; a
cross-sectional factor is a *less* noisy measurement of the part `i` shares with
everything else. Volatility is persistent, so a better estimate of `t` is a
better forecast of `t+1` - **without the factor carrying any information beyond
the contemporaneous.**

That is the whole claim and it is falsifiable: the factor at `t` should predict
`i`'s log-volatility at `t+1` beyond what `i`'s own history already says.

It also matters more than a relationship would. Every measured win on this desk
runs through `Q`, the volatility state - the `Q` clock at `+1055`, the clock and
loop together at `+1567`, the log-volatility ladder at `+191` to `+547` on 7 of
7 markets. A less noisy `Q` is an improvement to all of them at once.

## The baseline has to be HAR, not an AR(1)

Beating an AR(1) on realised volatility is easy and means nothing. The standard
strong baseline is **HAR** - the own value, the own five-span mean and the own
twenty-two span mean - which captures the long memory that makes volatility
forecastable in the first place. The panel arm is that same model plus one term.

So the comparison is three parameters against four, scored out of sample, which
penalises the extra parameter rather than rewarding it.

## The factor is computed leave-one-out, or the test is circular

A cross-sectional mean that includes instrument `i` lets `i` predict itself, and
the gain would be arithmetic. Every factor here excludes the instrument being
forecast. Standardisation uses **training-half statistics only**, so nothing
about the test half reaches the inputs.

## Three controls, and the synthetics are the sharpest

* **planted** - a known common log-volatility factor plus idiosyncratic noise,
  where the gain must appear, and a no-factor version where it must not;
* **rotation null** - the other instruments rotated in time, which destroys the
  factor and preserves every marginal exactly. More regressors always fit
  better in sample, so this is what says the out-of-sample gain is the factor
  rather than the extra term;
* **the synthetics** - measured mutually uncorrelated in volatility at
  `-0.0133`, so a panel over them must gain **nothing**. A control that comes
  from the same pipeline on the same bars is worth more than a simulated one.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import random
import statistics

import relationship_screen as screen

#: Bars per volatility observation. 24 at 1h is one day.
SPAN = int(os.environ.get("SPAN", "24"))
#: HAR's medium and long windows, in spans.
WEEK = int(os.environ.get("WEEK", "5"))
MONTH = int(os.environ.get("MONTH", "22"))
#: Null repetitions.
REPS = int(os.environ.get("REPS", "8"))
SEED = 20261013


def rotated(series, rng):
    """The same series at a random offset: the factor dies, the process lives."""
    import numpy as np

    times, values, spread = series
    shift = rng.randrange(SPAN * 3, max(len(values) - SPAN * 3, SPAN * 4))
    steps = np.diff(np.roll(values, shift))
    rebuilt = np.empty_like(values)
    rebuilt[0] = values[0]
    rebuilt[1:] = values[0] + np.cumsum(steps)
    return times, rebuilt, spread


def aligned(names, series):
    """A `(instruments x spans)` matrix of log-volatility on a **common** grid.

    **Spans have to be cut from aligned bars, not from each instrument's own
    index.** Taking every 24th bar of each series separately puts the span
    boundaries on different timestamps whenever two instruments keep different
    sessions - crypto trades through the weekend and FX does not - so the
    intersection of span *ends* was almost empty and the first version reported
    "not enough common spans" on a universe with 13,000 shared bars.

    So the bars are intersected first and the spans are cut from the aligned
    matrix, which makes every instrument's span the same wall-clock window.
    """
    import numpy as np

    usable = [n for n in names if series.get(n) is not None]
    if len(usable) < 4:
        return None, None
    stamps = None
    for name in usable:
        times = series[name][0]
        stamps = times if stamps is None else np.intersect1d(stamps, times)
    if stamps is None or len(stamps) < SPAN * (MONTH + 60):
        return None, None
    levels = []
    for name in usable:
        times, values, _ = series[name]
        _, index, _ = np.intersect1d(times, stamps, return_indices=True)
        levels.append(values[index])
    # Returns on the common grid, then non-overlapping spans of the same
    # wall-clock windows for every instrument.
    steps = np.diff(np.vstack(levels), axis=1)
    count = steps.shape[1] // SPAN
    if count < MONTH + 60:
        return None, None
    blocks = steps[:, : count * SPAN].reshape(len(usable), count, SPAN)
    sd = blocks.std(axis=2)
    # Drop any span where an instrument did not move at all, for every
    # instrument at once, so the grid stays rectangular.
    keep = (sd > 0).all(axis=0)
    if keep.sum() < MONTH + 60:
        return None, None
    return usable, np.log(sd[:, keep])


def har_design(column, start: int):
    """HAR inputs for every forecastable span: own value, own week, own month."""
    import numpy as np

    rows, targets, where = [], [], []
    for t in range(max(start, MONTH), len(column) - 1):
        rows.append(
            [
                column[t],
                float(column[t - WEEK + 1 : t + 1].mean()),
                float(column[t - MONTH + 1 : t + 1].mean()),
            ]
        )
        targets.append(column[t + 1])
        where.append(t)
    return np.asarray(rows, dtype=float), np.asarray(targets, dtype=float), where


def currencies(name: str) -> frozenset[str]:
    """The codes a symbol spans, so neighbours can be found without a table."""
    return frozenset((name[:3], name[3:6])) if len(name) >= 6 else frozenset()


def neighbours(names, index: int):
    """Which instruments share a currency with this one.

    **The global factor is the wrong specification and the residuals said so
    before this harness ran:** after three principal components the traded
    universe still carried residual correlations up to `0.9422`, and every
    strong residual pair shared a currency - `EURAUD/AUDJPY`, `GBPUSD/GBPJPY`,
    `USDCHF/CHFJPY`. Twenty instruments spanning eleven currencies have roughly
    eleven drivers, not one.

    So the sharper factor is the mean over instruments sharing a currency, which
    is a different regressor per instrument rather than one shared by all.
    """
    want = currencies(names[index])
    if not want:
        return []
    return [
        other
        for other, name in enumerate(names)
        if other != index and currencies(name) & want
    ]


#: Neighbours used by the `nearest` factor.
NEAREST = int(os.environ.get("NEAREST", "5"))
#: Equities screened, capped for runtime.
EQUITIES = int(os.environ.get("EQUITIES", "40"))


def nearest_neighbours(matrix, index: int, train_end: int, count: int = NEAREST):
    """The `count` instruments whose **training-half** log-volatility correlates most.

    **A currency rule needs currencies, and the cache has 439 equities with no
    sector labels at all** - only RIC suffixes. A measured neighbourhood needs
    no metadata, works on any asset class, and tests what the currency result
    actually claimed: that a factor pays when it is *targeted*, whatever picks
    the target.

    Correlations come from the training half only, so the neighbourhood is part
    of the fit rather than a peek at the answer.
    """
    import numpy as np

    train = matrix[:, : train_end + 1]
    own = train[index]
    if own.std() == 0:
        return []
    scores = []
    for other in range(len(matrix)):
        if other == index or train[other].std() == 0:
            continue
        scores.append((abs(float(np.corrcoef(own, train[other])[0, 1])), other))
    scores.sort(reverse=True)
    return [other for _, other in scores[:count]]


def score_one(matrix, index: int, *, factor: str = "none", names=None):
    """Out-of-sample mean squared error for one instrument, with and without.

    The factor is the cross-sectional mean of standardised log-volatility
    **excluding this instrument**, and the standardisation uses training-half
    statistics only.
    """
    import numpy as np

    column = matrix[index]
    rows, targets, where = har_design(column, MONTH)
    if len(rows) < 120:
        return None
    half = len(rows) // 2

    if factor != "none":
        if factor == "currency":
            if names is None:
                return None
            picked = neighbours(names, index)
            if len(picked) < 2:
                return None
            others = matrix[picked]
        elif factor == "nearest":
            picked = nearest_neighbours(matrix, index, where[half])
            if len(picked) < 2:
                return None
            others = matrix[picked]
        else:
            others = np.delete(matrix, index, axis=0)
        # Train-half mean and spread per instrument, so nothing leaks.
        train_end = where[half]
        centre = others[:, : train_end + 1].mean(axis=1, keepdims=True)
        spread = others[:, : train_end + 1].std(axis=1, keepdims=True)
        spread[spread == 0] = 1.0
        standard = (others - centre) / spread
        rows = np.column_stack([rows, standard.mean(axis=0)[where]])

    design = np.column_stack([rows, np.ones(len(rows))])
    try:
        weights, *_ = np.linalg.lstsq(design[:half], targets[:half], rcond=None)
    except np.linalg.LinAlgError:
        return None
    residual = targets[half:] - design[half:] @ weights
    return {
        "mse": float((residual**2).mean()),
        "errors": residual**2,
        "n": len(residual),
        "weights": weights,
    }


def compare(names, matrix, *, factor: str = "global"):
    """Per-instrument HAR against HAR-plus-factor, out of sample."""
    import numpy as np

    out = []
    for index, name in enumerate(names):
        plain = score_one(matrix, index, factor="none")
        panel = score_one(matrix, index, factor=factor, names=names)
        if plain is None or panel is None:
            continue
        gap = plain["errors"] - panel["errors"]
        sd = float(gap.std())
        out.append(
            {
                "name": name,
                "plain": plain["mse"],
                "panel": panel["mse"],
                # Share of the baseline's squared error removed.
                "gain": 1.0 - panel["mse"] / plain["mse"] if plain["mse"] > 0 else 0.0,
                # Paired t on the per-span squared errors, which is the honest
                # test: the two models see the identical spans.
                "t": (
                    float(gap.mean()) / (sd / math.sqrt(len(gap))) if sd > 0 else 0.0
                ),
                "factor_weight": float(panel["weights"][3]),
                "gaps": gap,
                "n": plain["n"],
            }
        )
    return out


def pooled_t(rows) -> float:
    """One paired `t` over every instrument's spans stacked together.

    **A per-instrument `t` is the wrong unit.** The claim is that the universe
    has a volatility factor, not that one instrument does, and with a dozen
    instruments the per-instrument statistic has almost no power - the planted
    arm reads a median `t` of 1.13 at a loading of 0.8. Stacking the paired
    squared-error differences tests the claim that was made.

    The spans overlap across instruments, so this is not a clean `t` either; it
    is a pooled effect size whose null is the rotation arm rather than a table.
    """
    import numpy as np

    if not rows:
        return float("nan")
    # **Normalised per instrument before pooling.** Pooling raw squared errors
    # weights each instrument by its own error scale, so one high-variance
    # instrument where the panel loses dominates the whole statistic - the
    # first version read a pooled t of -0.54 on a planted factor whose median
    # gain was positive, and -2.29 on the control.
    gaps = np.concatenate(
        [r["gaps"] / r["plain"] for r in rows if r["plain"] > 0]
    )
    if not len(gaps):
        return float("nan")
    sd = float(gaps.std())
    if sd <= 0:
        return 0.0
    return float(gaps.mean()) / (sd / math.sqrt(len(gaps)))


def summarise(label: str, rows) -> None:
    if not rows:
        print(f"{label:<34}{'-':>9}")
        return
    gains = sorted(r["gain"] for r in rows)
    print(
        f"{label:<34}{len(rows):>8}{statistics.median(gains):>+12.4f}"
        f"{gains[-1]:>+10.4f}{sum(1 for g in gains if g > 0):>10}"
        f"{statistics.median(r['t'] for r in rows):>+10.2f}"
        f"{pooled_t(rows):>+10.2f}"
    )


def planted() -> None:
    """A known factor, where the gain must appear, and none, where it must not."""
    import numpy as np

    print("=" * 104)
    print("ARM 0  planted: the gain must appear with a factor and not without one")
    print("=" * 104)
    rng = np.random.default_rng(5)
    spans, count = 900, 12
    # sd(log realised vol) over n returns is about 1/sqrt(2n), so a 24-bar
    # span carries roughly 0.14 - not an arbitrary choice.
    noise = 1.0 / math.sqrt(2.0 * SPAN)
    print(
        f"{'':<34}{'rows':>8}{'median gain':>12}{'best':>10}{'helped':>10}"
        f"{'median t':>10}{'pooled t':>10}"
    )
    # Swept, because the question is not only whether the detector works but
    # **at what loading it stops working** - that is the null's scope.
    for label, loading in (
        ("a dominant factor", 3.0),
        ("a strong factor", 1.5),
        ("a common factor", 0.8),
        ("a weak factor", 0.4),
        ("no common factor", 0.0),
    ):
        # One persistent common log-volatility factor, plus persistent
        # idiosyncratic parts, plus measurement noise on each observation.
        common = np.zeros(spans)
        for i in range(1, spans):
            common[i] = 0.95 * common[i - 1] + rng.standard_normal() * 0.3
        rows = []
        for _ in range(count):
            own = np.zeros(spans)
            for i in range(1, spans):
                own[i] = 0.9 * own[i - 1] + rng.standard_normal() * 0.3
            rows.append(loading * common + own + rng.standard_normal(spans) * noise)
        matrix = np.vstack(rows)
        names = [f"planted_{i}" for i in range(count)]
        summarise(label, compare(names, matrix))
    print(
        "\n`gain` is the share of the baseline's out-of-sample squared error\n"
        "removed. Two things in this table decide how the real arms are read.\n\n"
        "**The response is not monotone in the loading, and that is the\n"
        "mechanism rather than a defect.** At a dominant loading own volatility\n"
        "*is* the factor - `own = 3*common + idiosyncratic` - so HAR on own\n"
        "history already carries it and a cross-sectional term adds nothing. At\n"
        "a weak loading there is nothing to borrow. The factor pays only in a\n"
        "middle band where own volatility is a noisy but not dominant proxy, and\n"
        "the measured cross-instrument correlation of 0.52 sits in that band.\n\n"
        "**And the null is not zero, it is negative.** With no factor at all the\n"
        "extra parameter costs a pooled `t` near -4 out of sample. So the real\n"
        "arm is judged against the rotation null, which carries the identical\n"
        "penalty, rather than against nothing."
    )


def main() -> None:
    print(
        f"log-volatility over {SPAN}-bar spans, HAR({1},{WEEK},{MONTH}) baseline,\n"
        "factor is the leave-one-out cross-sectional mean, fitted on the first\n"
        "half and scored on the second\n"
    )
    planted()

    import numpy as np

    traded = [n for n in screen.TRADED if screen.load(n) is not None]
    synthetic = [
        n for n in screen.universe(screen.FRAME, cap=40) if screen.load(n) is not None
    ]
    series = {n: screen.load(n) for n in traded + synthetic}

    print("\n" + "=" * 104)
    print("ARM 1  the traded universe, against its own rotation")
    print("=" * 104)
    print(
        f"{'':<34}{'rows':>8}{'median gain':>12}{'best':>10}{'helped':>10}"
        f"{'median t':>10}{'pooled t':>10}"
    )
    names, matrix = aligned(traded, series)
    if names is None:
        print("  not enough common spans")
        return
    real = compare(names, matrix)
    summarise(f"traded, {len(names)} instruments", real)

    picker = random.Random(SEED)
    null_rows = []
    for _ in range(REPS):
        spun = {n: series[n] for n in names}
        # Rotate every instrument but keep the one being forecast intact, so
        # only the factor is destroyed.
        for n in names[1:]:
            spun[n] = rotated(series[n], picker)
        spun_names, spun_matrix = aligned(names, spun)
        if spun_names is None:
            continue
        null_rows.extend(compare(spun_names, spun_matrix))
    summarise("  rotation null", null_rows)

    by_currency = compare(names, matrix, factor="currency")
    summarise("traded, currency factor", by_currency)
    null_currency = []
    picker2 = random.Random(SEED + 3)
    for _ in range(REPS):
        spun = {n: series[n] for n in names}
        for n in names[1:]:
            spun[n] = rotated(series[n], picker2)
        spun_names, spun_matrix = aligned(names, spun)
        if spun_names is None:
            continue
        null_currency.extend(compare(spun_names, spun_matrix, factor="currency"))
    summarise("  its rotation null", null_currency)
    print(
        "\nThe currency factor is a different regressor per instrument - the\n"
        "mean over instruments sharing a currency - which is what the residual\n"
        "correlations of 0.94 along currency lines imply. A global factor forces\n"
        "one driver on a universe with about eleven."
    )

    print("\n" + "=" * 104)
    print("ARM 5  a measured neighbourhood, which needs no labels and travels")
    print("=" * 104)
    print(
        f"the {NEAREST} instruments whose training-half log-volatility correlates\n"
        "most, so equities - 439 of them in the cache, with no sector labels -\n"
        "get the same treatment as a currency cross.\n\n"
        "**There are no commodities in this cache.** No sugar, cocoa, coffee,\n"
        "oil, gas or copper at any frame, so they are not screened here rather\n"
        "than being stood in for by the metals.\n"
    )
    print(
        f"{'':<34}{'rows':>8}{'median gain':>12}{'best':>10}{'helped':>10}"
        f"{'median t':>10}{'pooled t':>10}"
    )
    # **Chosen by coverage, not alphabetically.** Equities carry market-hours
    # bars and different listing dates, so intersecting 40 names taken from the
    # front of the alphabet left 5 survivors. Taking the best-covered names
    # first keeps the common grid wide.
    candidates = sorted(
        {
            ".".join(path.name.split(".")[:2])
            for path in screen.CACHE.glob(f"*.{screen.FRAME}.npz")
            if path.name.count(".") == 3
        }
    )
    covered = []
    for name in candidates:
        got = screen.load(name)
        if got is not None:
            covered.append((len(got[0]), name))
    covered.sort(reverse=True)
    equities = [name for _, name in covered[:EQUITIES]]
    print(
        f"{len(candidates):,} equities in the cache, {len(covered):,} loadable, "
        f"best {EQUITIES} by coverage taken\n"
    )

    for label, universe, kinds in (
        ("traded", names, ("nearest", "global")),
        ("equities", equities, ("nearest", "global")),
    ):
        pool = {n: screen.load(n) for n in universe}
        pool = {k: v for k, v in pool.items() if v is not None}
        got_names, got_matrix = aligned(list(pool), pool)
        if got_names is None:
            print(f"{label:<34}  not enough common spans")
            continue
        spun = dict(pool)
        spinner = random.Random(SEED + 11)
        for n in got_names[1:]:
            spun[n] = rotated(pool[n], spinner)
        spun_names, spun_matrix = aligned(got_names, spun)
        for kind in kinds:
            summarise(
                f"{label} ({len(got_names)}), {kind}",
                compare(got_names, got_matrix, factor=kind),
            )
            if spun_names is not None:
                summarise(
                    f"  rotation null, {kind}",
                    compare(spun_names, spun_matrix, factor=kind),
                )
    print(
        "\n**The global arm is a prediction, not a sweep.** Equities share one\n"
        "dominant market factor, so a global mean is the right basis for them;\n"
        "FX spans about eleven currency drivers, so it is the wrong basis there\n"
        "and already measured as such. The two universes should therefore split."
    )

    print("\n" + "=" * 104)
    print("ARM 2  the synthetics, whose volatilities are measured uncorrelated")
    print("=" * 104)
    print(
        f"{'':<34}{'rows':>8}{'median gain':>12}{'best':>10}{'helped':>10}"
        f"{'median t':>10}{'pooled t':>10}"
    )
    syn_names, syn_matrix = aligned(synthetic, series)
    if syn_names is not None:
        summarise(f"generated, {len(syn_names)} instruments", compare(syn_names, syn_matrix))
    print(
        "\nTheir log-volatility correlation is -0.0133 with 0 of 12 pairs beating\n"
        "a rotation null, so there is no factor to borrow and the gain must be\n"
        "zero. This control runs the same pipeline on the same bars."
    )

    print("\n" + "=" * 104)
    print("ARM 3  per instrument, and whether the factor weight has a consistent sign")
    print("=" * 104)
    local = {r["name"]: r for r in by_currency}
    print(
        f"{'instrument':<14}{'plain mse':>11}{'global gain':>13}{'t':>8}"
        f"{'currency gain':>15}{'t':>8}{'neighbours':>12}"
    )
    for row in sorted(real, key=lambda r: -r["gain"]):
        mine = local.get(row["name"])
        count = len(neighbours(names, names.index(row["name"])))
        print(
            f"{row['name']:<14}{row['plain']:>11.5f}{row['gain']:>+13.4f}"
            f"{row['t']:>+8.2f}"
            + (
                f"{mine['gain']:>+15.4f}{mine['t']:>+8.2f}"
                if mine
                else f"{'-':>15}{'-':>8}"
            )
            + f"{count:>12}"
        )
    print("\n" + "=" * 104)
    print("ARM 4  the prediction the neighbour count makes, rather than the winners")
    print("=" * 104)
    print(
        "Naming the instruments that gained would be selection after the fact.\n"
        "The mechanism makes a prediction instead: a currency factor is only\n"
        "**targeted** when the instrument has few neighbours. A USD pair shares\n"
        "a currency with 14 to 16 others, so its currency factor is the global\n"
        "one again; a cross shares with 6 and gets something specific.\n\n"
        "So the gain must fall with the neighbour count, and that is one number\n"
        "over all 20 instruments with nothing chosen.\n"
    )
    counts = [float(len(neighbours(names, names.index(r["name"])))) for r in by_currency]
    gains = [r["gain"] for r in by_currency]
    if len(counts) > 3:
        spread_c = float(np.std(counts))
        spread_g = float(np.std(gains))
        rho = (
            float(np.corrcoef(counts, gains)[0, 1])
            if spread_c > 0 and spread_g > 0
            else float("nan")
        )
        order_c = np.argsort(np.argsort(counts))
        order_g = np.argsort(np.argsort(gains))
        print(
            f"neighbours against currency gain: linear {rho:+.4f}, "
            f"rank {float(np.corrcoef(order_c, order_g)[0, 1]):+.4f}, "
            f"over {len(counts)} instruments"
        )
    print(f"\n{'neighbours':<14}{'instruments':>13}{'median gain':>14}{'pooled t':>11}")
    for low, high, label in ((0, 7, "6 or fewer"), (7, 99, "more than 6")):
        here = [
            r
            for r in by_currency
            if low <= len(neighbours(names, names.index(r["name"]))) < high
        ]
        if not here:
            continue
        print(
            f"{label:<14}{len(here):>13}"
            f"{statistics.median(r['gain'] for r in here):>+14.4f}"
            f"{pooled_t(here):>+11.2f}"
        )
    for low, high, label in ((0, 7, "6 or fewer"), (7, 99, "more than 6")):
        here = [
            r
            for r in null_currency
            if low <= len(neighbours(names, names.index(r["name"]))) < high
        ]
        if here:
            print(
                f"  null, {label:<21}{len(here):>5}"
                f"{statistics.median(r['gain'] for r in here):>+14.4f}"
                f"{pooled_t(here):>+11.2f}"
            )
    print(
        "\nA split that was decided by the mechanism rather than by the result,\n"
        "and each half nulled by the same rotation."
    )

    if real:
        positive = sum(1 for r in real if r["factor_weight"] > 0)
        print(
            f"\n{positive} of {len(real)} load positively on the factor. A shared\n"
            "volatility driver should give the same sign everywhere; mixed signs\n"
            "would mean the term is fitting something instrument-specific."
        )


if __name__ == "__main__":
    main()
