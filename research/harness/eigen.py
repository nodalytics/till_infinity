"""How many of this book's correlations are real? Eigenvalues, against the noise they must clear.

Run from the repository root:  python research/harness/eigen.py

The desk asked to *"try eigen values and vectors, try matrices and linear algebra"*. There is one
result in that family which is genuinely load-bearing for a desk with a book of instruments, and
it is this: **most of a correlation matrix is noise, and random matrix theory says exactly how
much.**

## The theorem, and why it is not optional

Estimate a correlation matrix for `N` instruments from `T` bars. Even if the true correlations
are **all zero**, the sample matrix has non-zero entries, and its eigenvalues spread out in a way
Marchenko and Pastur derived in closed form. With `q = N / T`, the noise eigenvalues fill

    lambda_min = (1 - sqrt(q))^2   ...   lambda_max = (1 + sqrt(q))^2

and the density between them is

    rho(x) = sqrt((lambda_max - x)(x - lambda_min)) / (2 pi q x)

**An eigenvalue inside that band is indistinguishable from noise**, however large it looks. With
20 instruments and 2,000 bars, `q = 0.01` and the band runs to 1.21 - so a factor explaining 1.2
times an average instrument's variance has explained nothing at all.

This is the linear-algebra version of the discipline this folder already runs everywhere else:
compute the noise floor before reading the number. `power.py` does it for effect sizes; this does
it for correlations, and without it a correlation matrix is 190 numbers with no error bars.

## The positive control, which this book happens to own

A method that reports "k real factors" is worthless until it reports **zero** on something known
to have none. `generated.md` measured the Deriv synthetics across **325 pairs** and found no
shared driver - the largest correlation in the book was between two unrelated instruments.

So the synthetics are a set of instruments known to be independent, which makes them a positive
control for this exact method: **their spectrum should lie entirely inside the Marchenko-Pastur
band.** If it does not, the harness is broken and nothing it says about the real book counts.
This is `controls.md`'s argument - *"a folder of negative results is worth nothing until
something proves the instrument can detect a positive"* - run in the other direction.

## What the eigenvectors are for, and the test that matters

The largest eigenvalue of a real market's correlation matrix is the **market mode**: one factor
everything loads on, and its eigenvector is roughly uniform in sign. It is not tradeable - it is
the thing a pair trade exists to remove.

`metals_pair.py` measured gold against silver at **+0.7631 contemporaneously with nothing off
zero at any lag**, and could not say why. This says why: both load on one factor, so the
correlation is a shared exposure rather than a lead-lag relationship, and there is nothing to
trade in it. Removing the top eigenvector leaves the instrument-specific residual, which is where
a relative-value trade would have to live.

**The test that decides whether any of this is usable is out-of-sample eigenvector stability.**
An eigenvector fitted on the first half and still pointing the same way in the second half is a
structure; one that rotates is a fit. Measured here as the overlap `|v_early . v_late|`, against
the overlap two random unit vectors in `N` dimensions produce, which is about `1/sqrt(N)` and is
printed beside it rather than assumed.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "training"))

import candles  # noqa: E402

#: The real book this desk trades, and the synthetics that serve as the null control.
REAL = ("btcusd", "xauusd", "xagusd", "eurusd", "gbpusd", "usdjpy", "usdcad")
SYNTHETIC = (
    "boom_1000_index",
    "boom_300_index",
    "boom_500_index",
    "crash_1000_index",
    "crash_300_index",
    "crash_500_index",
    "volatility_75_index",
    "volatility_100_index",
)


def mp_edges(n: int, t: int, variance: float = 1.0) -> tuple[float, float]:
    """Marchenko-Pastur band for `n` series and `t` observations, scaled by `variance`.

    `variance` is what makes this usable on a real book rather than a textbook example.

    A correlation matrix has every diagonal entry equal to one, so its eigenvalues **must** sum
    to `n`. A large first eigenvalue therefore forces every other one down - not because those
    directions carry information, but by arithmetic. Comparing the whole spectrum against the
    unit-variance band counts that deformation as signal, and would report most of a book as
    structure whenever one factor is strong.

    So the band is also fitted to the variance the market mode leaves behind,
    `sigma^2 = 1 - lambda_1 / n`, which is Laloux's correction and the reason this function
    takes the argument at all. Both bands are printed: the naive one shows where the textbook
    floor sits, the adjusted one is the floor the remaining factors actually have to clear.
    """
    q = n / t
    return variance * (1.0 - math.sqrt(q)) ** 2, variance * (1.0 + math.sqrt(q)) ** 2


def aligned(where: Path, names: tuple[str, ...], interval: str) -> tuple[list[str], np.ndarray]:
    """Log returns on the timestamps every named instrument shares.

    Intersecting rather than forward-filling: a filled bar is a repeated price, which reads as
    zero return and **pulls every correlation toward zero** - so filling would bias this study
    toward its own null, which is the direction that would look like rigour and be a mistake.
    """
    series: dict[str, dict[int, float]] = {}
    for name in names:
        found = sorted(where.glob(f"{name}_{interval}_*.csv.gz"))
        if not found:
            continue
        bars, _repaired = candles.read(found[0])
        got = {int(row[0]): float(row[4]) for row in bars if row[4] > 0}
        if len(got) > 500:
            series[name] = got
    if len(series) < 3:
        return [], np.empty((0, 0))
    common = sorted(set.intersection(*(set(v) for v in series.values())))
    if len(common) < 500:
        return [], np.empty((0, 0))
    kept = sorted(series)
    prices = np.array([[series[k][t] for k in kept] for t in common])
    return kept, np.diff(np.log(prices), axis=0)


def spectrum(rets: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Eigenvalues (descending) and eigenvectors of the correlation matrix."""
    sd = rets.std(axis=0)
    ok = sd > 0
    z = (rets[:, ok] - rets[:, ok].mean(axis=0)) / sd[ok]
    corr = (z.T @ z) / len(z)
    values, vectors = np.linalg.eigh(corr)
    order = np.argsort(values)[::-1]
    return values[order], vectors[:, order]


def report(label: str, names: list[str], rets: np.ndarray) -> None:
    t, n = rets.shape
    values, vectors = spectrum(rets)
    lo, hi = mp_edges(n, t)
    # The band the *remaining* factors have to clear, once the market mode's share of the
    # fixed trace is taken out. Without this the trace constraint reads as signal.
    above = int((values > hi).sum())
    # **The adjustment only applies if the naive band found an outlier to remove.** Applying it
    # unconditionally was a false-positive generator: on the synthetics, where every eigenvalue
    # sits at 1.00, it reported 8 of 8 as signal - because subtracting a first "factor" worth
    # 1.0 shrinks the band below a bulk that was never dispersed. One pass, not iterated: with
    # q this small each pass finds more outliers and the procedure runs away, which is the
    # pathology the window sweep below exists to show rather than hide.
    if above:
        keep = n - above
        left = max((n - values[:above].sum()) / max(keep, 1), 1e-6)
        adj_lo, adj_hi = mp_edges(keep, t, left)
        real = above + int((values[above:] > adj_hi).sum())
    else:
        adj_lo, adj_hi = lo, hi
        left = 1.0
        real = 0

    print(f"\n{label}: {n} instruments, {t:,} shared bars")
    print(f"  Marchenko-Pastur band, unit variance:  [{lo:.3f}, {hi:.3f}]   (q = {n / t:.4f})")
    print(
        f"  adjusted for the first factor's share:  [{adj_lo:.3f}, {adj_hi:.3f}]   "
        f"(sigma^2 = {left:.3f})"
    )
    print("  eigenvalues: " + "  ".join(f"{v:.3f}" for v in values[: min(n, 8)]))
    print(
        f"  **{above} above the naive floor, {real} above the adjusted one** - "
        f"{values[0] / n:.1%} of total variance is in the first"
    )

    # The top eigenvector: is it the market mode - everything loading the same way?
    top = vectors[:, 0]
    same = max((top > 0).sum(), (top < 0).sum()) / n
    print(f"  top eigenvector: {same:.0%} of loadings share a sign", end="")
    if above:
        heavy = np.argsort(np.abs(top))[::-1][:3]
        print("  |  heaviest: " + ", ".join(f"{names[i]} {top[i]:+.2f}" for i in heavy))
    else:
        print()

    # Out-of-sample stability, which is the test that decides whether any of it is usable.
    half = t // 2
    early_v, early_vec = spectrum(rets[:half])
    _late_v, late_vec = spectrum(rets[half:])
    chance = 1.0 / math.sqrt(n)
    print(f"  {'factor':>7}{'eigenvalue':>12}{'in band?':>10}{'overlap':>9}{'chance':>8}")
    for k in range(min(n, 4)):
        overlap = abs(float(early_vec[:, k] @ late_vec[:, k]))
        bar = hi if k < max(above, 1) else adj_hi
        inside = "noise" if values[k] <= bar else "signal"
        mark = "  <-" if overlap > 3 * chance and values[k] > bar else ""
        print(
            f"  {k:>7}{values[k]:>12.3f}{inside:>10}{overlap:>9.3f}{chance:>8.3f}{mark}"
            + (f"   ({early_v[k]:.2f} early)" if k == 0 else "")
        )


def sweep(rets: np.ndarray, rng) -> None:
    """How many bars before a correlation matrix means anything?

    **This is the question the full-sample panel cannot answer.** With 7 instruments and 20,000
    bars, `q = 0.0003` and the noise band is 0.07 wide - so almost any dispersion clears it, and
    "the structure is real" is true but says nothing a desk can use.

    A desk does not estimate correlations on twenty thousand bars. It estimates them on a rolling
    window, and there `q` is large enough for Marchenko-Pastur to bite: at 100 bars and 7
    instruments the band runs to **1.61**, so a factor has to be half again as large as an
    average instrument's variance before it is distinguishable from nothing.

    Each row estimates on non-overlapping windows of that length and reports the mean count of
    eigenvalues clearing the floor, beside the same count on a **column-shuffled** copy - which
    destroys the cross-sectional correlation while keeping every marginal distribution, so the
    control has the same fat tails and the same volatility clustering as the real thing.
    """
    t, n = rets.shape
    print(f"\n\nHOW MANY BARS BEFORE A CORRELATION MATRIX MEANS ANYTHING  ({n} instruments)")
    print(
        f"  {'window':>8}{'q':>9}{'band to':>9}{'factors':>9}{'shuffled':>10}"
        f"{'lambda_1':>10}{'shuf l_1':>10}{'windows':>9}"
    )
    for length in (50, 100, 250, 500, 1_000, 2_000, 5_000):
        if length * 3 > t:
            continue
        counts, fakes, tops, faketops = [], [], [], []
        for start in range(0, t - length, length):
            block = rets[start : start + length]
            if block.std() <= 0:
                continue
            _lo, hi = mp_edges(n, length)
            values, _vec = spectrum(block)
            counts.append(int((values > hi).sum()))
            tops.append(values[0])
            # Shuffle each column independently: same marginals, no cross-section.
            fake = np.column_stack([rng.permutation(block[:, j]) for j in range(n)])
            fvalues, _fv = spectrum(fake)
            fakes.append(int((fvalues > hi).sum()))
            faketops.append(fvalues[0])
        if len(counts) < 3:
            continue
        _lo, hi = mp_edges(n, length)
        print(
            f"  {length:>8,}{n / length:>9.3f}{hi:>9.3f}{np.mean(counts):>9.2f}"
            f"{np.mean(fakes):>10.2f}{np.mean(tops):>10.3f}{np.mean(faketops):>10.3f}"
            f"{len(counts):>9}"
        )
    print(
        "  `factors` against `shuffled` is the reading: the gap is the real cross-sectional\n"
        "  structure, and where the two columns meet is the window below which a correlation\n"
        "  matrix on this book is indistinguishable from independent series."
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--where", default=os.environ.get("WHERE", ".secrets/broker-deep"))
    ap.add_argument("--interval", default="1h")
    args = ap.parse_args()
    where = Path(args.where).expanduser()

    print(
        "Correlation eigenvalues against the Marchenko-Pastur noise floor.\n"
        "An eigenvalue inside the band is indistinguishable from the spectrum a matrix of\n"
        "pure noise produces, however large it looks - which is the whole point of computing\n"
        "the floor before reading the number."
    )

    rng = np.random.default_rng(0)
    names, rets = aligned(where, REAL, args.interval)
    if len(names) >= 3:
        report("REAL BOOK", names, rets)
    else:
        print("\nREAL BOOK: too few aligned instruments")

    syn_names, syn = aligned(where, SYNTHETIC, args.interval)
    if len(syn_names) >= 3:
        report("SYNTHETICS - the positive control, known to share no driver", syn_names, syn)
    else:
        print("\nSYNTHETICS: too few aligned instruments")

    # A matched noise matrix: the same shape, no structure at all. The band is a theorem, but
    # a theorem applied by hand is worth checking against a sample it was derived for.
    if len(names) >= 3:
        report("PURE NOISE - same shape, no structure", names, rng.normal(size=rets.shape))
        sweep(rets, rng)

    print(
        "\n  **The synthetics row is the check on the method.** generated.md measured no shared\n"
        "  driver across 325 pairs, so their spectrum should sit inside the band. If it does and\n"
        "  the real book's does not, the separation is the instrument working rather than a\n"
        "  number being generated.\n"
        "\n  **The overlap column is what decides usefulness.** A factor whose eigenvector points\n"
        "  the same way in both halves is a structure worth trading around; one that rotates is a\n"
        "  fit to the half it was measured on, and `chance` is what two random directions give."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
