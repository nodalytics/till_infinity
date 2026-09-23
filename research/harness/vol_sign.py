"""Which side does the volatility land on? Susceptibility, semivariance, and the trend.

Run from the repository root:  python research/harness/vol_sign.py

Three of the desk's requests turn out to be one question, so they are tested together.

> *mean reverting volatility, if the trend is currently up and we are expecting vol, there is a
> chance that there will be a downward crash* [...] *see if it catches volatility before it happens
> and the direction of the volatility too* [...] *it does not have to work for both up and down, if
> it works for one side perfectly well that is a good thing too*

And, on the finding that a high susceptibility is followed by volatility **falling**:

> *which we can use too*

That last one is right in principle and this file is built to check it properly, because there is
an obvious way for it to be an illusion. See the control below.

## The quantities

`susceptibility.py` establishes the two inputs and found that `chi = var(M)` does not forecast the
volatility **level**: 2 to 5 times worse than a trailing standard deviation on QLIKE, with an
incremental R-squared of 0.0008 to 0.0085. What it did find is a consistent *negative* lift - after
a high `chi`, volatility rose **6 to 9 points less often** at 20 and 60 bars on three of four
instruments.

This file asks whether that is real and whether it has a side.

**Up and down volatility are separated by realised semivariance** - Barndorff-Nielsen's
decomposition, which is just the sum of squared returns split by the sign of each return:

    RS+ = sum of r^2 over bars with r > 0
    RS- = sum of r^2 over bars with r < 0

so `RS+ + RS- = RV`, and the asymmetry

    A = (RS+ - RS-) / (RS+ + RS-)

is in [-1, +1] and says which side carried the variance. **This is the "direction of volatility"
the desk asked for**, and unlike a return sign it is a magnitude question, which is the kind this
folder has occasionally been able to answer.

## The control that decides the inverted finding

**"High chi is followed by falling volatility" may be nothing more than "volatility is currently
high, and volatility mean-reverts."** `chi` is built from returns; it is large in choppy stretches;
chop follows violence. If that is all it is, a trailing standard deviation already knows it and
`chi` adds nothing.

So the lift is reported **twice**: raw, and within deciles of trailing volatility. If the effect
survives the second, `chi` knows something the level does not. If it vanishes, the finding was
volatility mean reversion wearing a physics name - which would be worth knowing, since it is the
same shape as `diverging.md`'s warning that a detector built to find exhaustion will label the
exhausted move, measured twice there already.

`diverging.md` also warns that **inverting an anti-signal is a trap**. That warning is about
flipping a signed return, where the inversion is arithmetic and carries no new information. A
statement about which way a *magnitude* moves is not that, so it is not excluded by the same
argument - but it has to clear the decile control before it counts.

## The synthetics are the control on the method

Included at the desk's request, and they earn their place: `generated.md` and `deriving.md`
establish that a Volatility index is GBM at a published constant sigma. **A constant-sigma process
has no volatility to forecast**, so any apparent skill there is a bug in this file. Boom and Crash
are the opposite and equally useful - they are built with a known one-sided jump asymmetry, so an
asymmetry measure that reads zero on them is broken.
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
from susceptibility import (  # noqa: E402
    CHI_WINDOW,
    WINDOW,
    magnetization,
    regress,
    susceptibility,
)

VOL_WINDOW = 100
FORWARDS = (20, 60)

#: Trailing-volatility deciles used to control the lift.
DECILES = 10

#: Real instruments, then the synthetics - which serve two different control purposes.
REAL = ("btcusd", "xauusd", "xagusd", "eurusd", "gbpusd", "usdjpy", "usdcad")
SYNTHETIC = (
    "volatility_75_index",
    "volatility_100_index",
    "boom_1000_index",
    "crash_1000_index",
)


def rolling_sum(values: np.ndarray, window: int) -> np.ndarray:
    """Sum over `[i+1, i+1+window)` - strictly forward, so no row includes its own bar."""
    out = np.full(len(values), np.nan)
    csum = np.concatenate([[0.0], np.cumsum(values)])
    usable = len(values) - window
    if usable <= 0:
        return out
    out[:usable] = csum[1 + window : 1 + window + usable] - csum[1 : 1 + usable]
    return out


def lift(flag: np.ndarray, loud: np.ndarray, buckets: np.ndarray | None = None) -> float:
    """How much more often `flag` holds when `loud`, optionally within buckets.

    With buckets the comparison is made **inside** each one and averaged, weighted by size - so a
    quantity that is merely a proxy for the bucketing variable scores zero here by construction.
    That is the point: it is the difference between "chi knows something" and "chi is a restatement
    of the volatility level".
    """
    if buckets is None:
        if loud.sum() < 50 or (~loud).sum() < 50:
            return float("nan")
        return float(flag[loud].mean() - flag[~loud].mean())
    total = 0.0
    weight = 0.0
    for b in np.unique(buckets):
        here = buckets == b
        hi, lo = here & loud, here & ~loud
        if hi.sum() < 20 or lo.sum() < 20:
            continue
        total += here.sum() * (flag[hi].mean() - flag[lo].mean())
        weight += here.sum()
    return total / weight if weight else float("nan")


def study(rets: np.ndarray, horizon: int) -> dict | None:
    mag = magnetization(rets, WINDOW)
    chi = susceptibility(mag, CHI_WINDOW)

    squared = rets**2
    up = np.where(rets > 0, squared, 0.0)
    down = np.where(rets < 0, squared, 0.0)
    fwd_rv = rolling_sum(squared, horizon)
    fwd_up = rolling_sum(up, horizon)
    fwd_down = rolling_sum(down, horizon)

    trail = np.full(len(rets), np.nan)
    c2 = np.concatenate([[0.0], np.cumsum(squared)])
    trail[VOL_WINDOW - 1 :] = (c2[VOL_WINDOW:] - c2[:-VOL_WINDOW]) / VOL_WINDOW

    ok = np.isfinite(chi) & np.isfinite(mag) & np.isfinite(trail) & np.isfinite(fwd_rv)
    ok &= (trail > 0) & (fwd_rv > 0)
    if ok.sum() < 2_000:
        return None

    x_chi, m, base, rv = chi[ok], mag[ok], trail[ok] * horizon, fwd_rv[ok]
    u, d = fwd_up[ok], fwd_down[ok]
    asym = (u - d) / np.maximum(u + d, 1e-300)
    logchi = np.log(np.maximum(x_chi, 1e-18))

    loud = x_chi >= np.quantile(x_chi, 0.8)
    fell = rv < base
    edges = np.quantile(base, np.linspace(0, 1, DECILES + 1)[1:-1])
    buckets = np.clip(np.searchsorted(edges, base), 0, DECILES - 1)

    # Does chi say anything about the *level* of each side, beyond the trailing estimate?
    _b, r2_base_up = regress(np.log(np.maximum(u, 1e-300)), [np.log(base)])
    _b, r2_both_up = regress(np.log(np.maximum(u, 1e-300)), [np.log(base), logchi])
    _b, r2_base_dn = regress(np.log(np.maximum(d, 1e-300)), [np.log(base)])
    _b, r2_both_dn = regress(np.log(np.maximum(d, 1e-300)), [np.log(base), logchi])

    # The desk's hypothesis: trend up plus expected volatility resolves downward, and the mirror.
    rising, falling = m > 0, m < 0
    up_side = asym > 0
    enough = 200
    hyp_up = lift(~up_side, loud & rising, buckets) if (loud & rising).sum() > enough else np.nan
    hyp_dn = lift(up_side, loud & falling, buckets) if (loud & falling).sum() > enough else np.nan

    return {
        "n": int(ok.sum()),
        "fell_raw": lift(fell, loud),
        "fell_held": lift(fell, loud, buckets),
        "dr2_up": r2_both_up - r2_base_up,
        "dr2_dn": r2_both_dn - r2_base_dn,
        "asym_r": float(np.corrcoef(logchi, asym)[0, 1]),
        "asym_mean": float(np.mean(asym)),
        "hyp_up": hyp_up,
        "hyp_dn": hyp_dn,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--where", default=os.environ.get("WHERE", ".secrets/broker-deep"))
    ap.add_argument("--interval", default="1h")
    args = ap.parse_args()

    print(
        "chi = var(M) against forward realised **semivariance**, so up and down volatility are\n"
        "separate targets. Two things are being tested:\n"
        "\n  `fell raw` vs `fell held` - does a high chi predict volatility falling, and does it\n"
        "  still do so **inside deciles of current volatility**? If only the raw column holds,\n"
        "  the finding is volatility mean reversion and the trailing estimate already has it.\n"
        "\n  `hyp up` / `hyp dn` - the desk's hypothesis: trend up plus a loud chi resolving\n"
        "  **downward**, and its mirror. Controlled by the same deciles.\n"
    )

    for label, names in (("REAL", REAL), ("SYNTHETIC - the control on the method", SYNTHETIC)):
        print(f"{label}")
        print(
            f"  {'symbol':<22}{'fwd':>4}{'n':>8}{'fell raw':>10}{'fell held':>11}"
            f"{'dR2 up':>9}{'dR2 dn':>9}{'r(chi,A)':>10}{'mean A':>8}"
            f"{'hyp up':>9}{'hyp dn':>9}"
        )
        for symbol in names:
            found = sorted(Path(args.where).expanduser().glob(f"{symbol}_{args.interval}_*.csv.gz"))
            if not found:
                continue
            bars, _repaired = candles.read(found[0])
            close = bars[:, 4]
            close = close[close > 0]
            if len(close) < 6_000:
                continue
            rets = np.diff(np.log(close))
            for horizon in FORWARDS:
                got = study(rets, horizon)
                if got is None:
                    continue
                print(
                    f"  {symbol:<22}{horizon:>4}{got['n']:>8,}"
                    f"{got['fell_raw']:>+10.1%}{got['fell_held']:>+11.1%}"
                    f"{got['dr2_up']:>9.4f}{got['dr2_dn']:>9.4f}"
                    f"{got['asym_r']:>+10.3f}{got['asym_mean']:>+8.3f}"
                    f"{got['hyp_up']:>+9.1%}{got['hyp_dn']:>+9.1%}"
                )
        print()

    print(
        "  **`fell held` is the one that counts.** `fell raw` can be large purely because chi is\n"
        "  high when volatility is high and volatility mean-reverts - which a trailing sigma\n"
        "  already captures. The held column makes the comparison inside deciles of current\n"
        "  volatility, so a proxy for the level scores zero there by construction.\n"
        "\n  **`mean A` on the synthetics checks the asymmetry measure itself.** Boom is built\n"
        "  to spike upward against a slow grind down and Crash is its mirror, so their mean\n"
        "  asymmetry must come out opposite and the Volatility indices near zero. If not, the\n"
        "  decomposition is wrong and no other column here means anything.\n"
        "\n  **A constant-sigma synthetic has no volatility to forecast**, so any skill on the\n"
        "  Volatility rows is this file being wrong rather than a discovery."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
