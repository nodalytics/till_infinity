"""Look-back against look-ahead: what the label's horizon does to the features' edge.

Part One is a **labelling** problem and Part Two is an **explanation** problem,
and mixing them is how both go wrong. So this builds one row per unique
hypothetical trade, with a permanent id, and only then attaches features that
were knowable at the entry bar.

Run:
  ./.secrets/lab.sh run research/harness/lookbacks.py \
      SEQLAB=$HOME/till_infinity/data/seqlab OMP_NUM_THREADS=1

## The four traps this is built around, each already paid for here

1. **A barrier label is mostly a volatility question.** AUC against a
   volatility target reads 0.805 on a *constant-volatility* process and 0.525
   within strata - the pooled number is nearly all free. So every feature is
   scored pooled **and** within volatility quintiles, and the gap between them
   is the result, not either number alone.
2. **Overlapping outcome windows leak.** Entries every bar with a 96-bar
   forward window are 96x overlapped; that shape once gave direction AUC 0.79
   which collapsed to 0.51 non-overlapped. Entries here are spaced by the
   horizon, and the overlapped version is run beside it to show the inflation
   rather than assert it.
3. **A fixed-pip target is a volatility bet.** +20 pips is a different trade
   at 03:00 than at 14:00, when FX volatility runs 3x. Targets are specified
   in volatility units, and a fixed-pip arm is carried alongside so the
   difference is measured.
4. **The spread is charged twice and it is in points, not price.** A BUY
   enters at ask and leaves against bid. Treating the bar series as mid once
   read EURUSD as a 476% round trip.

## The arms

* **real** - the instrument.
* **walk** - a random walk matched to the instrument's own step distribution
   by block shuffling its returns, carrying the same spread and the same
   label machinery. Anything the walk reproduces is geometry, not a market.

## What a positive result would have to look like

A feature whose within-strata AUC stays above 0.5 on the real arm, does not on
the walk arm, and holds its sign across instruments. A pooled AUC on its own
establishes nothing: it is the volatility of the period restated.
"""

from __future__ import annotations

import glob
import os
import statistics as st
from concurrent.futures import ProcessPoolExecutor

import numpy as np

SEQLAB = os.environ.get("SEQLAB", ".data/seqlab")
#: Forward windows, in 15m bars: 4h, 16h, 24h.
HORIZONS = (16, 64, 96)
#: Target distance as a multiple of ATR(14), and the reward:risk shape.
TARGETS = (0.5, 1.0, 2.0)
SHAPES = ((1.0, 1.0), (2.0, 1.0))
#: Look-back spans for the features, in bars.
SPANS = (14, 50)
STRATA = 5
MIN_BARS = 20_000
BLOCK = 96


# -------------------------------------------------------------- look-back
def rsi(close: np.ndarray, span: int) -> np.ndarray:
    """Wilder's RSI, past-only by construction."""
    delta = np.diff(close, prepend=close[0])
    up = np.where(delta > 0, delta, 0.0)
    dn = np.where(delta < 0, -delta, 0.0)
    au = ewma(up, span)
    ad = ewma(dn, span)
    rs = np.divide(au, ad, out=np.zeros_like(au), where=ad > 0)
    return 100.0 - 100.0 / (1.0 + rs)


def ewma(x: np.ndarray, span: int) -> np.ndarray:
    alpha = 1.0 / span
    out = np.empty_like(x)
    acc = 0.0
    for i, v in enumerate(x):
        acc = v if i == 0 else acc + alpha * (v - acc)
        out[i] = acc
    return out


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, span: int) -> np.ndarray:
    prev = np.roll(close, 1)
    prev[0] = close[0]
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    return ewma(tr, span)


def efficiency(close: np.ndarray, span: int) -> np.ndarray:
    """Net move over summed absolute moves: a trend measure with no fitting.

    Stands in for ADX. `research/docs` scored trend efficiency and ADX as the
    same question, and this one has no smoothing constants to get wrong.
    """
    step = np.abs(np.diff(close, prepend=close[0]))
    gross = ewma(step, span) * span
    net = close - np.roll(close, span)
    net[:span] = 0.0
    return np.divide(np.abs(net), gross, out=np.zeros_like(gross), where=gross > 0)


def features(bars: dict, span: int) -> dict[str, np.ndarray]:
    """Everything knowable at the close of each bar, and nothing after it."""
    close, high, low = bars["close"], bars["high"], bars["low"]
    a = atr(high, low, close, span)
    rel = np.divide(a, close, out=np.zeros_like(a), where=close > 0)
    mom = (close - np.roll(close, span)) / np.where(a > 0, a, 1.0)
    mom[:span] = 0.0
    #: The range-vs-close volatility ratio. The range estimator drives Q
    #: better than close-to-close - 0.648 within strata on FX - and the gap
    #: between them is itself a regime reading.
    rng = ewma(high - low, span)
    ratio = np.divide(rng, np.where(a > 0, a, 1.0), out=np.ones_like(a), where=a > 0)
    return {
        f"rsi{span}": rsi(close, span),
        f"eff{span}": efficiency(close, span),
        f"mom{span}": mom,
        f"relvol{span}": rel,
        f"rngratio{span}": ratio,
    }


# -------------------------------------------------------------- look-ahead
def label(
    bid_h: np.ndarray, bid_l: np.ndarray, ask_h: np.ndarray, ask_l: np.ndarray,
    i: int, entry: float, tp: float, sl: float, horizon: int, buy: bool,
) -> tuple[str, int]:
    """TP first, SL first, or neither, on the executable side of the market.

    A BUY enters at ask and is taken out against bid; a SELL the reverse. The
    stop is checked first where both fall in one bar: which came first is
    unknowable at this resolution, and assuming the good one is how a backtest
    invents money.
    """
    end = min(i + 1 + horizon, len(bid_h))
    for j in range(i + 1, end):
        if buy:
            hit_sl = bid_l[j] <= entry - sl
            hit_tp = bid_h[j] >= entry + tp
        else:
            hit_sl = ask_h[j] >= entry + sl
            hit_tp = ask_l[j] <= entry - tp
        if hit_sl:
            return "SL", j
        if hit_tp:
            return "TP", j
    return "NEITHER", end - 1


def auc(values: np.ndarray, hit: np.ndarray) -> float:
    """Rank AUC of `values` against a binary outcome, ties at 0.5."""
    n_pos = int(hit.sum())
    n_neg = int(len(hit) - n_pos)
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=np.float64)
    ranks[order] = np.arange(1, len(values) + 1)
    #: Average ranks within ties, or a constant feature scores 1.0.
    _, inv, counts = np.unique(values, return_inverse=True, return_counts=True)
    sums = np.zeros(len(counts))
    np.add.at(sums, inv, ranks)
    ranks = (sums / counts)[inv]
    return (ranks[hit.astype(bool)].sum() - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def point_of(close: np.ndarray) -> float:
    d = np.abs(np.diff(np.unique(close)))
    d = d[d > 0]
    return float(np.min(d)) if d.size else 0.0


def walk_of(close: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """A block shuffle of the instrument's own returns.

    Block, not i.i.d.: shuffling bar by bar destroys the volatility clustering
    that every barrier label lives on, which makes the control easier than the
    thing and the comparison meaningless.
    """
    ret = np.diff(np.log(np.maximum(close, 1e-12)))
    n = len(ret) // BLOCK
    blocks = ret[: n * BLOCK].reshape(n, BLOCK)
    rng.shuffle(blocks)
    return float(close[0]) * np.exp(np.cumsum(np.concatenate([[0.0], blocks.reshape(-1)])))


def one_feed(path: str) -> list[tuple]:
    z = np.load(path)
    name = os.path.basename(path).split(".")[0]
    close = z["close"].astype(np.float64)
    if len(close) < MIN_BARS:
        return []
    point = point_of(close)
    spread = z["spread"].astype(np.float64) * point if "spread" in z else np.zeros_like(close)
    rng = np.random.default_rng(13)

    rows: list[tuple] = []
    for arm in ("real", "walk"):
        if arm == "real":
            bars = {
                "close": close,
                "high": z["high"].astype(np.float64),
                "low": z["low"].astype(np.float64),
            }
            sp = spread
        else:
            w = walk_of(close, rng)
            #: The walk keeps the instrument's own bar geometry: the same
            #: high-low reach around each close, so the barrier has the same
            #: chance of being touched.
            reach = (z["high"] - z["low"]).astype(np.float64)[: len(w)]
            bars = {"close": w, "high": w + reach / 2.0, "low": w - reach / 2.0}
            sp = spread[: len(w)]
        #: MT5 bars are the bid. The ask is the bid plus the spread.
        bid_h, bid_l = bars["high"], bars["low"]
        ask_h, ask_l = bid_h + sp, bid_l + sp
        feats: dict[str, np.ndarray] = {}
        for span in SPANS:
            feats.update(features(bars, span))
        a14 = atr(bars["high"], bars["low"], bars["close"], 14)
        warm = max(SPANS) * 3

        for horizon in HORIZONS:
            for mult in TARGETS:
                for rwd, rsk in SHAPES:
                    for overlap in (False, True):
                        step = 1 if overlap else horizon
                        taken: list[tuple] = []
                        for i in range(warm, len(close) - horizon - 1, step):
                            unit = a14[i] * mult
                            if unit <= 0:
                                continue
                            entry_buy = bars["close"][i] + sp[i]
                            res, _ = label(
                                bid_h, bid_l, ask_h, ask_l, i, entry_buy,
                                unit * rwd, unit * rsk, horizon, True,
                            )
                            taken.append((i, res))
                        if len(taken) < 300:
                            continue
                        idx = np.array([t[0] for t in taken])
                        hit = np.array([t[1] == "TP" for t in taken], dtype=bool)
                        #: Expectancy in R, with NEITHER marked to zero: a
                        #: window that expired is not a win.
                        got = np.where(hit, rwd, 0.0)
                        got = np.where(
                            np.array([t[1] == "SL" for t in taken], dtype=bool), -rsk, got
                        )
                        #: Volatility quintile at entry - the stratifier.
                        vol = a14[idx] / np.maximum(bars["close"][idx], 1e-12)
                        edges = np.quantile(vol, np.linspace(0, 1, STRATA + 1)[1:-1])
                        bucket = np.digitize(vol, edges)
                        for fname, series in feats.items():
                            v = series[idx]
                            pooled = auc(v, hit)
                            within = []
                            for b in range(STRATA):
                                m = bucket == b
                                if m.sum() >= 100 and 0 < hit[m].sum() < m.sum():
                                    within.append(auc(v[m], hit[m]))
                            if not within or not np.isfinite(pooled):
                                continue
                            rows.append(
                                (
                                    name, arm, horizon, mult, rwd, overlap, fname,
                                    len(taken), float(hit.mean()), float(got.mean()),
                                    float(pooled), float(st.fmean(within)),
                                )
                            )
    return rows


def main() -> int:
    paths = sorted(glob.glob(os.path.join(SEQLAB, "*.npz")))
    if not paths:
        print(f"no npz under {SEQLAB}")
        return 1
    print(f"{len(paths)} feeds | horizons {HORIZONS} bars | targets {TARGETS} x ATR14")
    print(f"shapes {SHAPES} | look-back spans {SPANS} | {STRATA} volatility strata\n")
    rows: list[tuple] = []
    with ProcessPoolExecutor(max_workers=min(12, os.cpu_count() or 4)) as pool:
        for got in pool.map(one_feed, paths):
            rows.extend(got)
            if got:
                print(f"  {got[0][0]:28s} {len(got):5d} rows")
    if not rows:
        print("no rows")
        return 1

    # ---- 1. what the horizon does to the TP rate and the expectancy
    print("\n=== the label: TP rate and expectancy by horizon and target ===")
    print(f"{'arm':>5s} {'horizon':>8s} {'target':>7s} {'rwd':>4s} {'trades':>8s} "
          f"{'TP rate':>8s} {'meanR':>8s}")
    seen: dict[tuple, list[tuple]] = {}
    for r in rows:
        if r[6] != f"rsi{SPANS[0]}" or r[5]:
            continue
        seen.setdefault((r[1], r[2], r[3], r[4]), []).append(r)
    for key in sorted(seen, key=lambda k: (k[0], k[1], k[2], k[3])):
        got = seen[key]
        n = sum(g[7] for g in got)
        print(f"{key[0]:>5s} {key[1]:8d} {key[2]:7.1f} {key[3]:4.0f} {n:8d} "
              f"{sum(g[7] * g[8] for g in got) / n:8.3f} "
              f"{sum(g[7] * g[9] for g in got) / n:+8.3f}")

    # ---- 2. the headline: pooled AUC against within-strata AUC
    print("\n=== the look-back features: pooled AUC is mostly volatility ===")
    print(f"{'feature':>12s} {'arm':>5s} {'horizon':>8s} {'pooled':>8s} {'within':>8s} "
          f"{'gap':>7s} {'feeds':>6s}")
    agg: dict[tuple, list[tuple]] = {}
    for r in rows:
        if r[5]:
            continue
        agg.setdefault((r[6], r[1], r[2]), []).append(r)
    best = []
    for key, got in sorted(agg.items()):
        n = sum(g[7] for g in got)
        pooled = sum(g[7] * g[10] for g in got) / n
        within = sum(g[7] * g[11] for g in got) / n
        best.append((abs(within - 0.5), key, pooled, within, len(got)))
        print(f"{key[0]:>12s} {key[1]:>5s} {key[2]:8d} {pooled:8.3f} {within:8.3f} "
              f"{pooled - within:+7.3f} {len(got):6d}")

    # ---- 3. what overlapping the windows is worth, measured not asserted
    print("\n=== overlap inflation: the same feature, entries every bar ===")
    pair: dict[tuple, dict[bool, float]] = {}
    for r in rows:
        pair.setdefault((r[6], r[1], r[2]), {})[r[5]] = r[11]
    print(f"{'feature':>12s} {'arm':>5s} {'horizon':>8s} {'spaced':>8s} {'overlapped':>11s}")
    for key in sorted(pair):
        d = pair[key]
        if True in d and False in d:
            print(f"{key[0]:>12s} {key[1]:>5s} {key[2]:8d} {d[False]:8.3f} {d[True]:11.3f}")

    # ---- 4. the verdict, stated as a comparison and not a number
    best.sort(reverse=True)
    print("\n=== strongest within-strata readings, real against walk ===")
    for dist, key, pooled, within, feeds in best[:12]:
        mate = next(
            (w for d, k, p, w, f in best if k == (key[0], "walk" if key[1] == "real" else "real", key[2])),
            float("nan"),
        )
        print(f"  {key[0]:>12s} {key[1]:>5s} h{key[2]:<4d} within {within:.3f}  "
              f"other arm {mate:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
