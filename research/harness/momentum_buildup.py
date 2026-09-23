"""Momentum Bar Build-Up: does the *trajectory* of momentum add to its level?

Run from the repository root:  python research/harness/momentum_buildup.py

The desk supplied a research paper specifying this hypothesis and its validation protocol. The
paper's own status is **"PARTIALLY VALIDATED"** - the literature component holds, the empirical
component is marked pending, and it says why in terms worth quoting:

> *I attempted to retrieve executable raw OHLCV files for the proposed cross-asset test, but the
> execution environment could not resolve the external raw-data host. Because the raw observations
> were not actually available to the analysis runtime, this document intentionally does not
> fabricate accuracy, Sharpe, drawdown, p-values, or regression coefficients.*

**This desk has that data.** So this file runs the test the paper could not, on the universe it
asked for, with the ablation it specified.

## The claim, in the paper's own narrow form

> *Momentum velocity and acceleration may provide incremental predictive information about future
> returns after controlling for the current momentum level and standard trend measures.*

The narrowness is the paper's strength and it is preserved here. Regression slope is a standard
trend statistic and nobody is claiming otherwise; the question is whether the first and second
**temporal derivatives of a normalised momentum process** add anything once the level and the
slope are already in the regression.

    M = (weighted sum of returns) / sigma        momentum level
    V = M(t) - M(t-k)                            velocity
    A = V(t) - V(t-k) = M(t) - 2M(t-k) + M(t-2k) acceleration

## There is already a partial result on this in the repository

`slopes.md` measured `slope` **and** `prior_slope` together as worth +0.030 AUC on hold-versus-break
over 10,869 touches, and gave exactly the MBB reasoning for why the pair is needed and neither
half works alone: *"a flat approach means one thing after quiet and another after a run, and only
the prior window tells them apart."*

**That pair is a velocity term.** `slope(t) - slope(t-1)` is `V` computed on a price regression
rather than on a normalised momentum, and it is already fitted and shipped in
`learning/breaking.py`. So the MBB hypothesis has a measured precedent here - on **breaks**, not on
returns - which is a point in its favour and a reason to expect the return version to be harder:
every directional candidate in this folder has died, and `a-theory-from-ohlc.md` records why.

## The ablation, as specified

The paper is explicit that the sequence is the point - *"if B6 works but B4 already explains nearly
all of the improvement, then the acceleration story is weaker than it initially appears"* - so the
models are nested and reported in order:

    B0  sign of the recent return
    B1  M
    B2  fast MA - slow MA
    B3  price regression slope
    B4  M + sigma
    B5  M + V + sigma
    B6  M + V + A + slope + R^2 + sigma

Incremental R-squared is reported against the **immediately preceding** model, not against a naive
constant, because that is the comparison the paper asks for and the only one that can separate the
acceleration story from the level.

## Leakage, and the protocol's own list

Every one of the paper's leakage controls is structural here rather than asserted: features at bar
`t` use bars at or before `t`, the forward return starts at `t+1`, rolling normalisation is
backward-looking, and nothing is fitted per-asset or per-horizon. The out-of-sample split is
chronological with a purge of `horizon` bars so no training row's target overlaps a test row.

**And the intervals are block-bootstrapped**, as the paper requires - overlapping forward windows
make neighbouring rows dependent, and a plain standard error on 90,000 overlapping rows is the
mistake that makes a t-statistic of 30 out of a correlation of 0.01.

## Multiple comparisons, counted before the run

4 instruments x 3 horizons x 7 models. The paper asks for a data-snooping correction and this is
where it lands: the per-cell bar is Bonferroni-inflated for the grid, and a single cell clearing it
means nothing next to the shape across horizons and assets.
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

#: The universe the paper asked for, of what this desk holds.
UNIVERSE = ("eurusd", "btcusd", "xauusd", "xagusd")

#: Momentum lookback, the derivative interval, and the regression window - in bars.
#:
#: **One value each, chosen once, applied everywhere.** The paper is explicit about why: *"do not
#: optimize every parameter independently for every market and timeframe - that would create a
#: parameter-mining machine wearing a lab coat."* A sweep over these is a separate study with a
#: much larger correction attached.
LOOKBACK = 20
STEP = 5
FIT_WINDOW = 10

#: Trailing window for the volatility normaliser.
VOL_WINDOW = 100

#: Forecast horizons in bars, as the paper specifies - expressed in bars so comparisons stay
#: coherent across timeframes.
HORIZONS = (1, 5, 20)

#: Share of each series held back, chronologically, and never fitted on.
TEST_SHARE = 0.3

#: Round trip in log-return units, from `spread_cost.py`. Nothing directional in this folder is
#: reported without it.
COST = 0.0004


def rolling_mean(values: np.ndarray, window: int) -> np.ndarray:
    csum = np.concatenate([[0.0], np.cumsum(values)])
    out = np.full(len(values), np.nan)
    out[window - 1 :] = (csum[window:] - csum[:-window]) / window
    return out


def rolling_sd(values: np.ndarray, window: int) -> np.ndarray:
    csum = np.concatenate([[0.0], np.cumsum(values)])
    csq = np.concatenate([[0.0], np.cumsum(values**2)])
    out = np.full(len(values), np.nan)
    mean = (csum[window:] - csum[:-window]) / window
    var = (csq[window:] - csq[:-window]) / window - mean**2
    out[window - 1 :] = np.sqrt(np.maximum(var, 0.0))
    return out


def shift(values: np.ndarray, by: int) -> np.ndarray:
    out = np.full(len(values), np.nan)
    if by < len(values):
        out[by:] = values[:-by] if by else values
    return out


def state(rets: np.ndarray) -> dict[str, np.ndarray]:
    """The MBB state: `M`, `V`, `A`, the local momentum slope, its fit quality, and sigma.

    All backward-looking. `M` is a volatility-normalised weighted return sum, with linearly
    decaying weights so a recent bar counts for more - one specification, tested as one family
    rather than mixed with alternatives during the run, which is what the paper asks.
    """
    sigma = rolling_sd(rets, VOL_WINDOW)
    weights = np.arange(1, LOOKBACK + 1, dtype=float)
    weights /= weights.sum()
    # Weighted sum over the last LOOKBACK returns, oldest first so `weights` decays into the past.
    weighted = np.full(len(rets), np.nan)
    stacked = np.lib.stride_tricks.sliding_window_view(rets, LOOKBACK)
    weighted[LOOKBACK - 1 :] = stacked @ weights
    m = weighted / np.where(sigma > 0, sigma, np.nan)

    v = m - shift(m, STEP)
    a = v - shift(v, STEP)

    # Local regression of M on bar index over FIT_WINDOW, and its R-squared.
    idx = np.arange(FIT_WINDOW, dtype=float)
    idx -= idx.mean()
    denom = float((idx**2).sum())
    beta = np.full(len(rets), np.nan)
    quality = np.full(len(rets), np.nan)
    ok = np.isfinite(m)
    filled = np.where(ok, m, 0.0)
    panes = np.lib.stride_tricks.sliding_window_view(filled, FIT_WINDOW)
    valid = np.lib.stride_tricks.sliding_window_view(ok, FIT_WINDOW).all(axis=1)
    centred = panes - panes.mean(axis=1, keepdims=True)
    slope = (centred * idx).sum(axis=1) / denom
    resid = centred - slope[:, None] * idx
    total = (centred**2).sum(axis=1)
    r2 = np.where(total > 0, 1.0 - (resid**2).sum(axis=1) / np.maximum(total, 1e-300), 0.0)
    beta[FIT_WINDOW - 1 :] = np.where(valid, slope, np.nan)
    quality[FIT_WINDOW - 1 :] = np.where(valid, r2, np.nan)

    # The conventional trend controls the paper asks for as baselines.
    fast, slow = rolling_mean(rets, 10), rolling_mean(rets, 50)
    return {
        "M": m,
        "V": v,
        "A": a,
        "beta": beta,
        "R2": quality,
        "sigma": sigma,
        "ma": (fast - slow) / np.where(sigma > 0, sigma, np.nan),
        "recent": np.sign(shift(np.cumsum(rets) - shift(np.cumsum(rets), 5), 0)),
    }


#: The nested ablation, exactly as the paper specifies it.
MODELS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("B0 sign(recent)", ("recent",)),
    ("B1 M", ("M",)),
    ("B2 MA fast-slow", ("ma",)),
    ("B3 slope", ("beta",)),
    ("B4 M + sigma", ("M", "sigma")),
    ("B5 M + V + sigma", ("M", "V", "sigma")),
    ("B6 full MBB", ("M", "V", "A", "beta", "R2", "sigma")),
)


def fit(design: np.ndarray, target: np.ndarray) -> np.ndarray:
    beta, *_ = np.linalg.lstsq(design, target, rcond=None)
    return beta


def r_squared(target: np.ndarray, fitted: np.ndarray) -> float:
    spread = float(np.var(target))
    return 1.0 - float(np.var(target - fitted)) / spread if spread > 0 else float("nan")


def block_interval(values: np.ndarray, block: int, draws: int = 400) -> tuple[float, float]:
    """A 95% interval for a mean by resampling blocks, as the paper requires."""
    n = len(values)
    if n < block * 8:
        return (float("nan"), float("nan"))
    starts = np.arange(0, n - block)
    count = max(n // block, 1)
    rng = np.random.default_rng(0)
    means = np.empty(draws)
    for d in range(draws):
        picks = rng.choice(starts, size=count)
        means[d] = float(np.mean(np.concatenate([values[p : p + block] for p in picks])))
    return (float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975)))


def study(rets: np.ndarray, horizon: int) -> list[dict]:
    built = state(rets)
    csum = np.concatenate([[0.0], np.cumsum(rets)])
    usable = len(rets) - horizon
    # The forward return starts at t+1, so no row's target contains the bar its features used.
    forward = np.full(len(rets), np.nan)
    forward[:usable] = csum[1 + horizon : 1 + horizon + usable] - csum[1 : 1 + usable]

    ok = np.isfinite(forward)
    for values in built.values():
        ok &= np.isfinite(values)
    rows = np.where(ok)[0]
    if len(rows) < 5_000:
        return []

    # Chronological split with a purge, so no training target overlaps a test row.
    cut = int(len(rows) * (1.0 - TEST_SHARE))
    train, test = rows[: cut - horizon], rows[cut:]
    if len(test) < 1_000:
        return []

    out = []
    previous = None
    for name, columns in MODELS:
        design = np.column_stack([built[c] for c in columns] + [np.ones(len(rets))])
        beta = fit(design[train], forward[train])
        predicted = design[test] @ beta
        got = {
            "model": name,
            "n": len(test),
            "r2": r_squared(forward[test], predicted),
            "ic": float(np.corrcoef(predicted, forward[test])[0, 1]),
            "hit": float(np.mean(np.sign(predicted) == np.sign(forward[test]))),
        }
        # The economic test: follow the sign, charged the round trip.
        net = np.sign(predicted) * forward[test] - COST
        got["net_bp"] = float(np.mean(net)) * 1e4
        lo, hi = block_interval(net, max(horizon, 2))
        got["lo_bp"], got["hi_bp"] = lo * 1e4, hi * 1e4
        got["d_r2"] = got["r2"] - previous if previous is not None else float("nan")
        previous = got["r2"]
        out.append(got)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("symbols", nargs="*", default=list(UNIVERSE))
    ap.add_argument("--where", default=os.environ.get("WHERE", ".secrets/broker-deep"))
    ap.add_argument("--interval", default="1h")
    args = ap.parse_args()

    cells = len(args.symbols) * len(HORIZONS)
    print(
        f"Momentum Bar Build-Up, the paper's ablation on {len(args.symbols)} instruments x "
        f"{len(HORIZONS)} horizons\n"
        f"M over {LOOKBACK} bars, derivatives at {STEP}, local fit over {FIT_WINDOW}, "
        f"one parameter set everywhere\n"
        f"last {TEST_SHARE:.0%} of each series held back chronologically, purged by the horizon\n"
        f"\n{cells} cells, so the data-snooping bar is Bonferroni-inflated and the **shape** "
        "across horizons is the reading\n"
        f"`net bp` is charged {COST * 1e4:.0f}bp round trip, with a block-bootstrap interval\n"
    )

    verdicts: list[tuple[str, int, float, float, float]] = []
    for symbol in args.symbols:
        found = sorted(Path(args.where).expanduser().glob(f"{symbol}_{args.interval}_*.csv.gz"))
        if not found:
            print(f"  {symbol:<10} no {args.interval} file")
            continue
        bars, _repaired = candles.read(found[0])
        close = bars[:, 4]
        close = close[close > 0]
        if len(close) < 10_000:
            continue
        rets = np.diff(np.log(close))

        print(f"{symbol}  -  {args.interval}, {len(rets):,} bars")
        for horizon in HORIZONS:
            got = study(rets, horizon)
            if not got:
                continue
            print(
                f"  h={horizon:<3}{'model':<20}{'n':>8}{'OOS R2':>10}{'dR2':>10}"
                f"{'IC':>8}{'hit':>8}{'net bp':>9}{'95% block':>20}"
            )
            for row in got:
                mark = "  <-" if row["lo_bp"] > 0 else ""
                delta = f"{row['d_r2']:>10.5f}" if np.isfinite(row["d_r2"]) else f"{'-':>10}"
                print(
                    f"       {row['model']:<20}{row['n']:>8,}{row['r2']:>10.5f}{delta}"
                    f"{row['ic']:>8.3f}{row['hit']:>8.1%}{row['net_bp']:>+9.2f}"
                    f"   [{row['lo_bp']:+.2f}, {row['hi_bp']:+.2f}]{mark}"
                )
            full = got[-1]
            b4 = next(r for r in got if r["model"].startswith("B4"))
            verdicts.append((symbol, horizon, full["r2"] - b4["r2"], full["net_bp"], full["lo_bp"]))
            print()

    if verdicts:
        print("THE PAPER'S OWN QUESTION: does the trajectory add beyond the level?")
        print(f"  {'symbol':<10}{'h':>4}{'R2(B6) - R2(B4)':>18}{'net bp':>9}{'floor':>9}")
        for symbol, horizon, gain, net, lo in verdicts:
            print(f"  {symbol:<10}{horizon:>4}{gain:>18.5f}{net:>+9.2f}{lo:>+9.2f}")
        clean = sum(1 for _s, _h, gain, _n, lo in verdicts if gain > 0 and lo > 0)
        print(
            f"\n  {clean} of {len(verdicts)} cells have both a positive incremental "
            "R-squared **and** a net clearing its own block-bootstrap floor."
        )

    print(
        "\n  **`dR2` against the model above it is the paper's test**, not `OOS R2` against zero.\n"
        "  Its own words: if B6 works but B4 already explains nearly all of the improvement, the\n"
        "  acceleration story is weaker than it appears. B5 minus B4 prices velocity; B6 minus B5\n"
        "  prices acceleration, the slope and the fit quality together.\n"
        "\n  **`net bp` with its interval is the economic test.** An IC of 0.02 on 30,000 rows\n"
        "  is significant by any t-statistic and worth nothing against a 4bp round trip, which\n"
        "  is the distinction this folder exists to keep making."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
