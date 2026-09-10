"""Test one from `implied.md`: does VIX say anything our own estimate does not?

The cheapest of the four and the one most likely to end the idea. `vol_bps` is
already a volatility estimate; VIX is another. If they are the same number in
different units then VIX adds nothing and the other three tests are moot.

## What is compared

Three models of **forward realised volatility**, at several horizons:

* `hist` - trailing realised volatility alone. This is the incumbent: `vol_bps`
  is an exponentially weighted mean absolute return, so a trailing realised
  estimate is what it amounts to.
* `vix` - the implied number alone.
* `both` - the two together.

**`both` has to beat `hist` or there is nothing here.** That is the incremental
question and it is the only one that matters: VIX beating `hist` on its own
would be interesting, VIX adding nothing to `hist` would settle it.

## Walk-forward, not in-sample

Every fit uses only data before the point it predicts, refitting as it goes. An
in-sample R-squared on two collinear volatility measures would be high and
would mean nothing - and `research/forecasting.md` records three occasions in
one day where a clean table was mistaken for a finding.

The baseline is the same one that has beaten every model in that document:
**predicting that forward realised equals trailing realised**. R-squared is
reported against the mean *and* against that, because against the mean almost
anything scores well on a series this autocorrelated.

## What would kill it

`both` failing to beat `hist` by more than the noise in the difference. Or the
gain living entirely at the 21-day horizon, which VIX prices, while this desk
holds trades for minutes to a day - a real result about the wrong horizon.
"""

from __future__ import annotations

import math
import os
import statistics as st
import sys

import yfinance as yf

#: Forward horizons in trading days. VIX prices roughly 21.
HORIZONS = (1, 5, 21)
#: Trailing window for the historical estimate, in trading days.
LOOKBACK = int(os.environ.get("LOOKBACK", "21"))
#: Rows before the walk-forward starts predicting.
WARMUP = int(os.environ.get("WARMUP", "500"))
YEARS = os.environ.get("YEARS", "15y")


def series(ticker: str) -> dict[str, float]:
    got = yf.Ticker(ticker).history(period=YEARS, interval="1d", auto_adjust=False)
    out = {}
    for when, row in got.iterrows():
        close = row.get("Close")
        if close is None or not (close == close) or close <= 0:
            continue
        out[str(when.date())] = float(close)
    return out


def solve(rows: list[tuple[list[float], float]]) -> list[float] | None:
    """Least squares with an intercept, by normal equations.

    Two predictors at most, so this is a 3x3 solve and writing it out avoids a
    dependency for something the standard library can do.
    """
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
    # Gauss-Jordan with partial pivoting.
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
    spx = series("^GSPC")
    vix = series("^VIX")
    vvix = series("^VVIX")
    days = sorted(set(spx) & set(vix))
    print(f"^GSPC {len(spx)} days, ^VIX {len(vix)}, ^VVIX {len(vvix)}, "
          f"{len(days)} aligned\n")
    if len(days) < WARMUP + 100:
        print("not enough history")
        sys.exit(1)

    # Daily log returns, and trailing realised volatility annualised into the
    # same units VIX quotes - percent, annualised - so the two are comparable
    # and a coefficient near 1 means something.
    rets = {}
    for i in range(1, len(days)):
        a, b = spx[days[i - 1]], spx[days[i]]
        if a > 0 and b > 0:
            rets[days[i]] = math.log(b / a)

    keys = [d for d in days if d in rets]
    hist, fwd = {}, {h: {} for h in HORIZONS}
    for i, d in enumerate(keys):
        if i >= LOOKBACK:
            window = [rets[k] for k in keys[i - LOOKBACK : i]]
            hist[d] = st.pstdev(window) * math.sqrt(252) * 100
        for h in HORIZONS:
            if i + h < len(keys):
                ahead = [rets[k] for k in keys[i + 1 : i + 1 + h]]
                if len(ahead) == h:
                    fwd[h][d] = (
                        st.pstdev(ahead) * math.sqrt(252) * 100 if h > 1
                        else abs(ahead[0]) * math.sqrt(252) * 100
                    )

    print(f"  {'horizon':>8s} {'n':>6s} "
          f"{'R2_hist':>9s} {'R2_vix':>9s} {'R2_both':>9s} {'both-hist':>10s} "
          f"{'vs naive':>9s}")
    for h in HORIZONS:
        usable = [d for d in keys if d in hist and d in fwd[h] and d in vix]
        if len(usable) < WARMUP + 50:
            print(f"  {h:>7d}d  too few")
            continue
        preds = {"hist": [], "vix": [], "both": []}
        truth, naive = [], []
        for i in range(WARMUP, len(usable)):
            train = usable[:i]
            d = usable[i]
            y = fwd[h][d]
            for name, cols in (("hist", ("h",)), ("vix", ("v",)), ("both", ("h", "v"))):
                rows = [
                    ([hist[t] if c == "h" else vix[t] for c in cols], fwd[h][t])
                    for t in train
                ]
                beta = solve(rows)
                if beta is None:
                    continue
                xs = [hist[d] if c == "h" else vix[d] for c in cols]
                preds[name].append(beta[0] + sum(b * x for b, x in zip(beta[1:], xs, strict=True)))
            truth.append(y)
            naive.append(hist[d])
        if len(truth) < 50:
            print(f"  {h:>7d}d  too few after warmup")
            continue
        mean = st.fmean(truth)
        ss_mean = math.fsum((t - mean) ** 2 for t in truth)
        ss_naive = math.fsum((n - t) ** 2 for n, t in zip(naive, truth, strict=True))

        def r2(name):
            got = preds[name]
            if len(got) != len(truth):
                return float("nan")
            ss = math.fsum((p - t) ** 2 for p, t in zip(got, truth, strict=True))
            return 1 - ss / ss_mean

        rh, rv, rb = r2("hist"), r2("vix"), r2("both")
        ss_both = math.fsum(
            (p - t) ** 2 for p, t in zip(preds["both"], truth, strict=True)
        ) if len(preds["both"]) == len(truth) else float("nan")
        vs_naive = 1 - ss_both / ss_naive if ss_naive > 0 else float("nan")
        print(f"  {h:>7d}d {len(truth):6d} {rh:9.4f} {rv:9.4f} {rb:9.4f} "
              f"{rb - rh:+10.4f} {vs_naive:+9.4f}")

    print("\nR2 is against predicting the mean, walk-forward, refit at every step.")
    print("`both-hist` is the whole test: what VIX adds to what we already have.")
    print("`vs naive` is against predicting that forward realised equals trailing")
    print("realised - the baseline that has beaten every model in forecasting.md.")


if __name__ == "__main__":
    run()
