"""Test two from `implied.md`: is the term structure the signal, or just the level?

Test one established that VIX beats a trailing realised estimate and subsumes
it - `both` was not better than `vix` alone. This asks the next question: is the
*level* of VIX doing the work, or is the shape?

Three quantities that are not the same thing:

* **level** - VIX itself. What test one used.
* **slope** - VIX3M over VIX. Above one is contango, the ordinary state; below
  one is backwardation, which is the market pricing near-term stress above
  longer-term. The standard reading, and a different number from the level.
* **change** - VIX against its own recent average. VIX at 18 having risen from
  14 is not VIX at 18 having fallen from 25, and the level cannot tell them
  apart.

Each is added to the level and asked whether it earns its place. `vix` alone is
the incumbent here, not the trailing estimate - test one already retired that.

## Why this could easily be nothing

The three are strongly related: VIX rises when stress arrives, the curve
inverts when stress arrives, and VIX rises above its average when stress
arrives. Adding correlated predictors to a walk-forward regression usually buys
a little in-sample and nothing out of it, which is exactly what the discipline
below is for.

A gain of a few thousandths of R-squared on 3,200 points is not a finding. The
number to look at is `over level`, and it has to be large enough to survive
being one of six comparisons.
"""

from __future__ import annotations

import math
import os
import statistics as st
import sys

import yfinance as yf

HORIZONS = (1, 5, 21)
LOOKBACK = int(os.environ.get("LOOKBACK", "21"))
WARMUP = int(os.environ.get("WARMUP", "500"))
YEARS = os.environ.get("YEARS", "15y")
#: Days over which "change" is measured - VIX against its own recent mean.
DRIFT = int(os.environ.get("DRIFT", "10"))


def series(ticker: str) -> dict[str, float]:
    got = yf.Ticker(ticker).history(period=YEARS, interval="1d", auto_adjust=False)
    out = {}
    for when, row in got.iterrows():
        close = row.get("Close")
        if close is None or not (close == close) or close <= 0:
            continue
        out[str(when.date())] = float(close)
    return out


def solve(rows):
    if not rows:
        return None
    width = len(rows[0][0]) + 1
    xtx = [[0.0] * width for _ in range(width)]
    xty = [0.0] * width
    for xs, y in rows:
        v = [1.0, *xs]
        for i in range(width):
            xty[i] += v[i] * y
            for j in range(width):
                xtx[i][j] += v[i] * v[j]
    for i in range(width):
        pivot = max(range(i, width), key=lambda r: abs(xtx[r][i]))
        if abs(xtx[pivot][i]) < 1e-12:
            return None
        xtx[i], xtx[pivot] = xtx[pivot], xtx[i]
        xty[i], xty[pivot] = xty[pivot], xty[i]
        d = xtx[i][i]
        xtx[i] = [v / d for v in xtx[i]]
        xty[i] /= d
        for r in range(width):
            if r == i:
                continue
            f = xtx[r][i]
            if f:
                xtx[r] = [a - f * b for a, b in zip(xtx[r], xtx[i], strict=True)]
                xty[r] -= f * xty[i]
    return xty


def run() -> None:
    spx, vix, vix3m = series("^GSPC"), series("^VIX"), series("^VIX3M")
    days = sorted(set(spx) & set(vix) & set(vix3m))
    print(f"^GSPC {len(spx)}, ^VIX {len(vix)}, ^VIX3M {len(vix3m)} -> {len(days)} aligned\n")
    if len(days) < WARMUP + 200:
        print("not enough overlapping history - ^VIX3M starts later than ^VIX")
        sys.exit(1)

    rets = {}
    for i in range(1, len(days)):
        a, b = spx[days[i - 1]], spx[days[i]]
        if a > 0 and b > 0:
            rets[days[i]] = math.log(b / a)
    keys = [d for d in days if d in rets]

    fwd = {h: {} for h in HORIZONS}
    drift = {}
    for i, d in enumerate(keys):
        if i >= DRIFT:
            past = [vix[k] for k in keys[i - DRIFT : i]]
            drift[d] = vix[d] / st.fmean(past) if st.fmean(past) > 0 else 1.0
        for h in HORIZONS:
            if i + h < len(keys):
                ahead = [rets[k] for k in keys[i + 1 : i + 1 + h]]
                if len(ahead) == h:
                    fwd[h][d] = (
                        st.pstdev(ahead) * math.sqrt(252) * 100 if h > 1
                        else abs(ahead[0]) * math.sqrt(252) * 100
                    )

    def cols(d, which):
        got = []
        for c in which:
            if c == "l":
                got.append(vix[d])
            elif c == "s":
                got.append(vix3m[d] / vix[d] if vix[d] > 0 else 1.0)
            else:
                got.append(drift[d])
        return got

    models = (
        ("level", ("l",)),
        ("+slope", ("l", "s")),
        ("+change", ("l", "c")),
        ("+both", ("l", "s", "c")),
    )
    print(f"  {'horizon':>8s} {'n':>6s} " + " ".join(f"{m:>9s}" for m, _ in models)
          + f" {'best over level':>16s}")
    for h in HORIZONS:
        usable = [d for d in keys if d in fwd[h] and d in drift and d in vix and d in vix3m]
        if len(usable) < WARMUP + 50:
            print(f"  {h:>7d}d  too few")
            continue
        preds = {m: [] for m, _ in models}
        truth = []
        for i in range(WARMUP, len(usable)):
            train, d = usable[:i], usable[i]
            for name, which in models:
                beta = solve([(cols(t, which), fwd[h][t]) for t in train])
                if beta is None:
                    continue
                xs = cols(d, which)
                preds[name].append(
                    beta[0] + sum(b * x for b, x in zip(beta[1:], xs, strict=True))
                )
            truth.append(fwd[h][d])
        mean = st.fmean(truth)
        ss_mean = math.fsum((t - mean) ** 2 for t in truth)

        def r2(name):
            got = preds[name]
            if len(got) != len(truth):
                return float("nan")
            return 1 - math.fsum(
                (p - t) ** 2 for p, t in zip(got, truth, strict=True)
            ) / ss_mean

        scores = {m: r2(m) for m, _ in models}
        gain = max(v for k, v in scores.items() if k != "level") - scores["level"]
        print(f"  {h:>7d}d {len(truth):6d} "
              + " ".join(f"{scores[m]:9.4f}" for m, _ in models)
              + f" {gain:+16.4f}")

    print("\n`level` is the incumbent - test one retired the trailing estimate.")
    print("slope  = VIX3M / VIX. Above 1 is contango; below 1, backwardation.")
    print(f"change = VIX over its own {DRIFT}-day mean.")
    print("\nThese three move together, so a few thousandths is not a finding.")
    print("Six comparisons here; the gain has to be large enough to survive that.")


if __name__ == "__main__":
    run()
