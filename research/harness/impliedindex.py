"""Does the VIX result transfer to the other equity indices we trade?

Test one in `implied.md` was measured on ^GSPC against ^VIX, and `spx500` is the
only instrument that describes directly. This desk also trades `us100`, `us30`
and `us2000`, and each has its own volatility index:

| feed | index | implied |
| --- | --- | --- |
| spx500 | ^GSPC | ^VIX |
| us100 | ^NDX | ^VXN |
| us30 | ^DJI | ^VXD |
| us2000 | ^RUT | ^RVX |

Two questions, and the second decides how much work this is worth:

1. **Does the result hold on each index with its own implied series?** If VIX
   only works on the S&P, the scope shrinks from four instruments to one.
2. **Does the matched series beat VIX for that index?** The four are strongly
   correlated - a stress day moves all of them - so VIX might carry the whole
   effect and the other three might be redundant. That would mean one data feed
   instead of four, and one thing to keep alive rather than four.

The second is the practical question. `own` beating `vix` by a wide margin means
each index needs its own; `own` and `vix` scoring alike means take VIX and stop.

Same discipline as the other three: walk-forward, refit at every step, R-squared
against predicting the mean, and `hist` - a trailing realised estimate, which is
what `vol_bps` amounts to - as the incumbent to beat.
"""

from __future__ import annotations

import math
import os
import statistics as st

import yfinance as yf

PAIRS = (
    ("spx500", "^GSPC", "^VIX"),
    ("us100", "^NDX", "^VXN"),
    ("us30", "^DJI", "^VXD"),
    ("us2000", "^RUT", "^RVX"),
)
HORIZONS = (1, 5, 21)
LOOKBACK = int(os.environ.get("LOOKBACK", "21"))
WARMUP = int(os.environ.get("WARMUP", "500"))
YEARS = os.environ.get("YEARS", "15y")

_cache: dict[str, dict[str, float]] = {}


def series(ticker: str) -> dict[str, float]:
    if ticker in _cache:
        return _cache[ticker]
    got = yf.Ticker(ticker).history(period=YEARS, interval="1d", auto_adjust=False)
    out = {}
    for when, row in got.iterrows():
        close = row.get("Close")
        if close is None or not (close == close) or close <= 0:
            continue
        out[str(when.date())] = float(close)
    _cache[ticker] = out
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
    vix = series("^VIX")
    print(f"  {'feed':>8s} {'index':>7s} {'implied':>8s} {'h':>4s} {'n':>6s} "
          f"{'hist':>8s} {'own':>8s} {'vix':>8s} {'own-hist':>9s} {'own-vix':>8s}")
    for feed, index, implied in PAIRS:
        px, iv = series(index), series(implied)
        days = sorted(set(px) & set(iv) & set(vix))
        if len(days) < WARMUP + 200:
            print(f"  {feed:>8s} {index:>7s} {implied:>8s}   only {len(days)} aligned days")
            continue
        rets = {}
        for i in range(1, len(days)):
            a, b = px[days[i - 1]], px[days[i]]
            if a > 0 and b > 0:
                rets[days[i]] = math.log(b / a)
        keys = [d for d in days if d in rets]
        hist, fwd = {}, {h: {} for h in HORIZONS}
        for i, d in enumerate(keys):
            if i >= LOOKBACK:
                hist[d] = st.pstdev([rets[k] for k in keys[i - LOOKBACK : i]]) * math.sqrt(252) * 100
            for h in HORIZONS:
                if i + h < len(keys):
                    ahead = [rets[k] for k in keys[i + 1 : i + 1 + h]]
                    if len(ahead) == h:
                        fwd[h][d] = (
                            st.pstdev(ahead) * math.sqrt(252) * 100 if h > 1
                            else abs(ahead[0]) * math.sqrt(252) * 100
                        )
        for h in HORIZONS:
            usable = [d for d in keys if d in hist and d in fwd[h]]
            if len(usable) < WARMUP + 50:
                continue
            models = {"hist": lambda d: [hist[d]],
                      "own": lambda d: [iv[d]],
                      "vix": lambda d: [vix[d]]}
            preds = {m: [] for m in models}
            truth = []
            for i in range(WARMUP, len(usable)):
                train, d = usable[:i], usable[i]
                for name, cols in models.items():
                    beta = solve([(cols(t), fwd[h][t]) for t in train])
                    if beta is None:
                        continue
                    xs = cols(d)
                    preds[name].append(
                        beta[0] + sum(b * x for b, x in zip(beta[1:], xs, strict=True))
                    )
                truth.append(fwd[h][d])
            mean = st.fmean(truth)
            ss = math.fsum((t - mean) ** 2 for t in truth)
            got = {}
            for m in models:
                if len(preds[m]) == len(truth):
                    got[m] = 1 - math.fsum(
                        (p - t) ** 2 for p, t in zip(preds[m], truth, strict=True)
                    ) / ss
            if len(got) < 3:
                continue
            print(f"  {feed:>8s} {index:>7s} {implied:>8s} {h:>3d}d {len(truth):6d} "
                  f"{got['hist']:8.4f} {got['own']:8.4f} {got['vix']:8.4f} "
                  f"{got['own'] - got['hist']:+9.4f} {got['own'] - got['vix']:+8.4f}")
        print()

    print("`own-hist` is whether the implied series beats a trailing estimate,")
    print("which is the test one result repeated per index.")
    print("`own-vix` is whether the *matched* series is needed: near zero means")
    print("take VIX for all four and keep one feed alive instead of four.")


if __name__ == "__main__":
    run()
