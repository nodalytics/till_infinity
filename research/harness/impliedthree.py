"""Test three from `implied.md`: does VVIX lead VIX, or only move with it?

VVIX is the volatility of VIX - the options market pricing uncertainty about its
own forecast. A rise in VVIX while VIX is flat is a different statement from the
two rising together, and if it *precedes* a VIX move rather than accompanying it,
that is a lead rather than a correlation.

Two questions, because they are not the same and only one is tradeable here:

1. **Does VVIX add to VIX and the slope** in predicting forward realised
   volatility? Same regression as tests one and two, one predictor further.
2. **Does yesterday's VVIX change predict today's VIX change?** A lead. This is
   the stronger claim and the one that would matter, because it says something
   about *when*.

## The control decides the second question

Contemporaneous correlation between VVIX and VIX changes will be high - they are
the same market reacting to the same news, and finding that would be finding
nothing. The number that matters is whether the correlation at a **lag** stands
above the contemporaneous one, and above what an unrelated pair produces.

`research/generated.md` is the reason this is not optional: the largest
correlation in a 325-pair study there was between two entirely unrelated
instruments. A lag correlation of 0.05 means nothing without knowing what 0.05
looks like when there is nothing to find.
"""

from __future__ import annotations

import math
import os
import statistics as st
import sys

import yfinance as yf

HORIZONS = (1, 5, 21)
WARMUP = int(os.environ.get("WARMUP", "500"))
YEARS = os.environ.get("YEARS", "15y")
LAGS = (-3, -2, -1, 0, 1, 2, 3)


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


def corr(xs, ys):
    n = len(xs)
    if n < 100:
        return float("nan")
    mx, my = st.fmean(xs), st.fmean(ys)
    num = math.fsum((a - mx) * (b - my) for a, b in zip(xs, ys, strict=True))
    dx = math.sqrt(math.fsum((a - mx) ** 2 for a in xs))
    dy = math.sqrt(math.fsum((b - my) ** 2 for b in ys))
    return num / (dx * dy) if dx > 0 and dy > 0 else float("nan")


def run() -> None:
    spx, vix, vix3m, vvix = (series(t) for t in ("^GSPC", "^VIX", "^VIX3M", "^VVIX"))
    # A control that shares the market but not the mechanism: gold's own
    # volatility index. If a VVIX->VIX lag looks like something, this says what
    # an unrelated pair scores on the same days.
    gvz = series("^GVZ")
    days = sorted(set(spx) & set(vix) & set(vix3m) & set(vvix))
    print(f"aligned {len(days)} days (^VVIX {len(vvix)}, ^GVZ {len(gvz)})\n")
    if len(days) < WARMUP + 200:
        print("not enough overlapping history")
        sys.exit(1)

    rets = {}
    for i in range(1, len(days)):
        a, b = spx[days[i - 1]], spx[days[i]]
        if a > 0 and b > 0:
            rets[days[i]] = math.log(b / a)
    keys = [d for d in days if d in rets]
    fwd = {h: {} for h in HORIZONS}
    for i, d in enumerate(keys):
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
                got.append(vvix[d])
        return got

    print("=== does VVIX add to level + slope? ===")
    models = (("level+slope", ("l", "s")), ("+vvix", ("l", "s", "v")))
    print(f"  {'horizon':>8s} {'n':>6s} {'level+slope':>12s} {'+vvix':>9s} {'gain':>9s}")
    for h in HORIZONS:
        usable = [d for d in keys if d in fwd[h] and d in vvix and d in vix3m]
        if len(usable) < WARMUP + 50:
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
        ss = math.fsum((t - mean) ** 2 for t in truth)
        got = {}
        for m, _ in models:
            if len(preds[m]) == len(truth):
                got[m] = 1 - math.fsum(
                    (p - t) ** 2 for p, t in zip(preds[m], truth, strict=True)
                ) / ss
        if len(got) == 2:
            a, b = got["level+slope"], got["+vvix"]
            print(f"  {h:>7d}d {len(truth):6d} {a:12.4f} {b:9.4f} {b - a:+9.4f}")

    print("\n=== does a VVIX change lead a VIX change? ===")
    ch_vix, ch_vvix, ch_gvz = {}, {}, {}
    for i in range(1, len(keys)):
        p, d = keys[i - 1], keys[i]
        if vix.get(p, 0) > 0:
            ch_vix[d] = math.log(vix[d] / vix[p])
        if vvix.get(p, 0) > 0:
            ch_vvix[d] = math.log(vvix[d] / vvix[p])
        if gvz.get(p, 0) > 0 and gvz.get(d, 0) > 0:
            ch_gvz[d] = math.log(gvz[d] / gvz[p])
    idx = {d: i for i, d in enumerate(keys)}
    print(f"  {'lag':>5s} {'vvix->vix':>11s} {'control gvz->vix':>18s} {'n':>7s}")
    for lag in LAGS:
        xs, ys, cs = [], [], []
        for d, i in idx.items():
            j = i + lag
            if j < 0 or j >= len(keys):
                continue
            other = keys[j]
            if d in ch_vvix and other in ch_vix:
                xs.append(ch_vvix[d])
                ys.append(ch_vix[other])
                cs.append(ch_gvz.get(d, float("nan")))
        pairs = [(a, b, c) for a, b, c in zip(xs, ys, cs, strict=True) if c == c]
        if len(xs) < 200:
            continue
        c1 = corr(xs, ys)
        c2 = corr([p[2] for p in pairs], [p[1] for p in pairs]) if len(pairs) > 200 else float("nan")
        note = "  <- same day" if lag == 0 else ("  <- vvix leads" if lag > 0 else "")
        print(f"  {lag:+5d} {c1:11.4f} {c2:18.4f} {len(xs):7d}{note}")

    print("\nA lead means the correlation at lag > 0 stands above the same-day one.")
    print("The control is gold's volatility index against VIX on the same days -")
    print("what an unrelated pair scores when there is nothing to find.")


if __name__ == "__main__":
    run()
