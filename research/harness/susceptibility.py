"""Does the variance of the order parameter lead a volatility change? Ising susceptibility on bars.

Run from the repository root:  python research/harness/susceptibility.py

Borrowed from a retired in-house detector suite, at the desk's suggestion that its concepts might
improve the volatility and breakout models. Two were worth taking and this tests the stronger one.

## What the borrowed quantity is, and why it is not a metaphor

The detector defines a **magnetization**

    M = (net signed returns) / (total absolute returns)

over a rolling window, and a **susceptibility**

    chi = var(M) over a rolling window of M

with the claim that `chi` spikes *before* a regime change and is therefore a leading indicator.

**That `M` is already in production here under another name.** It is exactly `trend.py`'s
efficiency ratio - net displacement over the sum of absolute steps - which was measured over 54,143
resolutions and separates outcomes better than anything else this repository has tried: the top
decile breaks 1.4% of the time against the chop's 11.3%.

So the borrowed idea is not the order parameter, which we have. **It is the variance of it**, which
we do not, and the physics behind that is a theorem rather than an analogy. In the Ising model the
susceptibility `chi = dM/dh` diverges at the critical point, and the fluctuation-dissipation theorem
makes it proportional to the variance of the order parameter. "The variance of `M` peaks at a phase
transition" is that statement, and it is the reason this is worth a harness instead of an opinion.

Whether a market has a critical point is a separate question and this file does not assume one. It
asks only the empirical form: **does `var(M)` today tell us anything about volatility tomorrow that
today's volatility does not already tell us?**

## The bar it has to clear, which is the whole design

Not chance. **A trailing standard deviation**, which in this folder has beaten:

* a three-state Gaussian HMM's variance forecast, by 3% to 72% (`linear-algebra.md`);
* a 50-neighbour analogue forecast, on 0 of 20 window-by-horizon cells (`similarity_grid.py`);
* persistence landscapes, per `vol_baseline.py`.

A volatility forecast that does not beat 100 bars of arithmetic is not a volatility forecast, so
`chi` is scored by **QLIKE** against exactly that - and then, more strictly, by whether it adds
anything **incrementally**: a regression of forward variance on trailing variance *and* `chi`, to
see whether `chi`'s coefficient survives once the baseline has had its say. A quantity correlated
with volatility is worthless if it is correlated only through volatility.

## And the "leading" claim, tested as stated

The claim is not that `chi` is high when volatility is high - that would be nearly circular, since
both are built from the same returns. It is that `chi` rises **before** volatility does. So the
target here is the **change** in realised volatility from the present window to the forward one, and
the question is whether `chi` predicts an increase. That is the form the claim was made in and it is
the form that could pay: anticipating a volatility rise is what `news_vol.py` does from the
calendar, and this would do it from price alone.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "training"))

import candles  # noqa: E402

#: The borrowed parameters, kept as the detector set them so this tests their claim and not a
#: variant of it. `window` is the magnetization window, `chi_window` the variance window over it.
WINDOW = 20
CHI_WINDOW = 10

#: Baseline volatility window, and the forward horizons scored.
VOL_WINDOW = 100
FORWARDS = (5, 20, 60)


def magnetization(rets: np.ndarray, window: int = WINDOW) -> np.ndarray:
    """Net signed returns over total absolute returns - the efficiency ratio, in [-1, 1].

    Signed here, unlike `trend.py`'s, which takes the absolute value. The sign is what makes it
    an order parameter: +1 is every step up, -1 every step down, 0 is cancellation. Taking the
    magnitude first would throw away the direction the variance is supposed to fluctuate in.
    """
    csum = np.concatenate([[0.0], np.cumsum(rets)])
    net = csum[window:] - csum[:-window]
    total = np.convolve(np.abs(rets), np.ones(window), mode="valid")
    out = np.full(len(rets), np.nan)
    out[window - 1 :] = np.where(total > 0, net / np.maximum(total, 1e-12), 0.0)
    return out


def susceptibility(mag: np.ndarray, chi_window: int = CHI_WINDOW) -> np.ndarray:
    """Rolling variance of the magnetization - `chi`, in the fluctuation-dissipation sense."""
    out = np.full(len(mag), np.nan)
    ok = np.isfinite(mag)
    if ok.sum() < chi_window * 2:
        return out
    # Rolling variance by cumulative sums, which is O(n) rather than O(n * window).
    filled = np.where(ok, mag, 0.0)
    c1 = np.concatenate([[0.0], np.cumsum(filled)])
    c2 = np.concatenate([[0.0], np.cumsum(filled**2)])
    cn = np.concatenate([[0.0], np.cumsum(ok.astype(float))])
    n = cn[chi_window:] - cn[:-chi_window]
    s1 = c1[chi_window:] - c1[:-chi_window]
    s2 = c2[chi_window:] - c2[:-chi_window]
    var = np.where(n > 1, s2 / np.maximum(n, 1) - (s1 / np.maximum(n, 1)) ** 2, np.nan)
    out[chi_window - 1 :] = np.where(n >= chi_window, np.maximum(var, 0.0), np.nan)
    return out


def qlike(actual: np.ndarray, forecast: np.ndarray) -> float:
    ok = (actual > 0) & (forecast > 0) & np.isfinite(actual) & np.isfinite(forecast)
    if ok.sum() < 200:
        return float("nan")
    ratio = actual[ok] / forecast[ok]
    return float(np.mean(ratio - np.log(ratio) - 1.0))


def regress(target: np.ndarray, columns: list[np.ndarray]) -> tuple[np.ndarray, float]:
    """Least squares with an intercept. Returns coefficients and in-sample R-squared."""
    design = np.column_stack([*columns, np.ones(len(target))])
    ok = np.isfinite(design).all(axis=1) & np.isfinite(target)
    if ok.sum() < 500:
        return np.zeros(len(columns) + 1), float("nan")
    beta, *_ = np.linalg.lstsq(design[ok], target[ok], rcond=None)
    fitted = design[ok] @ beta
    resid = target[ok] - fitted
    spread = float(np.var(target[ok]))
    return beta, (1.0 - float(np.var(resid)) / spread if spread > 0 else float("nan"))


# Four scored quantities per horizon with their controls; splitting it would mean recomputing
# the rolling windows per question.
def main() -> int:  # noqa: PLR0915
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "symbols",
        nargs="*",
        default=[s.strip() for s in os.environ.get("SYMBOLS", "").split(",") if s.strip()]
        or ["btcusd", "xauusd", "eurusd", "gbpusd"],
    )
    ap.add_argument("--where", default=os.environ.get("WHERE", ".secrets/broker-deep"))
    ap.add_argument("--interval", default="1h")
    args = ap.parse_args()

    print(
        f"Ising susceptibility: chi = var(M) over {CHI_WINDOW} readings of a {WINDOW}-bar\n"
        "magnetization M = net returns / total |returns| - which is the efficiency ratio\n"
        "trend.py already ships, so the borrowed quantity is its **variance**.\n"
        "\nScored against a trailing standard deviation, which has beaten an HMM, a\n"
        "50-neighbour analogue and persistence landscapes in this folder. QLIKE: lower is better.\n"
    )

    for symbol in args.symbols:
        found = sorted(Path(args.where).expanduser().glob(f"{symbol}_{args.interval}_*.csv.gz"))
        if not found:
            print(f"  {symbol:<10} no {args.interval} file")
            continue
        bars, _repaired = candles.read(found[0])
        close = bars[:, 4]
        close = close[close > 0]
        if len(close) < 5_000:
            continue
        rets = np.diff(np.log(close))
        mag = magnetization(rets)
        chi = susceptibility(mag)

        trail = np.full(len(rets), np.nan)
        c2 = np.concatenate([[0.0], np.cumsum(rets**2)])
        trail[VOL_WINDOW - 1 :] = np.sqrt((c2[VOL_WINDOW:] - c2[:-VOL_WINDOW]) / VOL_WINDOW)

        print(f"{symbol}  -  {args.interval}, {len(rets):,} bars")
        print(
            f"  {'fwd':>5}{'n':>8}{'r chi,|fwd|':>13}{'QLIKE chi':>11}{'QLIKE trail':>13}"
            f"{'QLIKE both':>12}{'beta chi':>10}{'t':>8}{'dR2':>8}"
            f"{'R2 rise':>9}{'lift':>9}"
        )
        for horizon in FORWARDS:
            # Realised variance over the bars **strictly after** `i`, so no row's target
            # contains the bar its predictors were computed on. The slice is written out rather
            # than folded, because the obvious `c2f[h:] - c2f[:-h]` is off by one *and* includes
            # bar `i` itself - two errors that would both inflate the result.
            fwd_var = np.full(len(rets), np.nan)
            c2f = np.concatenate([[0.0], np.cumsum(rets**2)])
            usable = len(rets) - horizon
            fwd_var[:usable] = c2f[1 + horizon : 1 + horizon + usable] - c2f[1 : 1 + usable]
            ok = np.isfinite(chi) & np.isfinite(trail) & np.isfinite(fwd_var) & (fwd_var > 0)
            ok &= trail > 0
            if ok.sum() < 1_000:
                continue
            x_chi, x_trail, y = chi[ok], trail[ok], fwd_var[ok]
            base = x_trail**2 * horizon
            # chi has no natural scale as a variance forecast, so it is calibrated by the mean
            # ratio - otherwise QLIKE would be measuring the units and not the information.
            scaled = x_chi * float(np.mean(y) / max(np.mean(x_chi), 1e-18))

            # Incremental: does chi survive once the trailing estimate has had its say?
            _beta_base, r2_base = regress(np.log(y), [np.log(base)])
            logchi = np.log(np.maximum(x_chi, 1e-18))
            beta_both, r2_both = regress(np.log(y), [np.log(base), logchi])
            design = np.column_stack([np.log(base), logchi, np.ones(len(base))])
            both = np.exp(design @ beta_both)
            resid = np.log(y) - design @ beta_both
            # A t-statistic for chi's coefficient. **Plainly computed and plainly too large**:
            # overlapping forward windows make these rows dependent, so the honest standard
            # error is a block bootstrap and this one understates it by roughly sqrt(horizon).
            try:
                cov = float(np.var(resid)) * np.linalg.inv(design.T @ design)
                spread = float(cov[1, 1])
                t_chi = beta_both[1] / np.sqrt(spread) if spread > 0 else float("nan")
            except np.linalg.LinAlgError:
                t_chi = float("nan")
            # The claim as the detector states it: chi rises **before** volatility does. So the
            # target is the *change* from the trailing level to the forward one, not the level -
            # a quantity built from returns is correlated with the volatility level almost by
            # construction, and testing the level would reward that rather than the claim.
            change = np.log(y) - np.log(base)
            _beta_rise, r2_rise = regress(change, [logchi])
            rose = change > 0
            loud = x_chi >= np.quantile(x_chi, 0.8)
            lift = float(rose[loud].mean() - rose[~loud].mean())

            print(
                f"  {horizon:>5}{int(ok.sum()):>8,}"
                f"{float(np.corrcoef(x_chi, np.sqrt(y))[0, 1]):>13.3f}"
                f"{qlike(y, scaled):>11.4f}{qlike(y, base):>13.4f}{qlike(y, both):>12.4f}"
                f"{beta_both[1]:>+10.4f}{t_chi:>8.1f}{r2_both - r2_base:>8.4f}"
                f"{r2_rise:>9.4f}{lift:>+9.1%}"
            )
        print()

    print(
        "  **`QLIKE trail` is the bar.** `chi` alone beating it would be a result; `QLIKE both`\n"
        "  beating it says only that two estimators are better than one, which is usually true\n"
        "  and rarely useful.\n"
        "\n  **`beta chi` with its `t`, and `dR2`, are the honest test.** They ask whether `chi`\n"
        "  says anything about forward variance that the trailing estimate does not already say.\n"
        "  A large correlation with a `dR2` near zero means `chi` is a volatility proxy - which\n"
        "  it is built from returns to be - and not a leading indicator of one.\n"
        "\n  **`R2 rise` and `lift` test the claim in the form it was made.** The claim is that\n"
        "  chi rises *before* volatility, so the target there is the **change** from the trailing\n"
        "  level to the forward one. `lift` is how much more often volatility rose after a chi in\n"
        "  its top fifth than after any other - the number a desk would act on, and the one a\n"
        "  t-statistic on 100,000 overlapping rows cannot stand in for."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
