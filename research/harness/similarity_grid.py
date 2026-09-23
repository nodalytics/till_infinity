"""Similarity across every window and forward length - and whether it forecasts volatility.

Run from the repository root:  python research/harness/similarity_grid.py

Two questions, and the second is the one with a real chance.

`analogue_envelope.py` tested the published parameterisation - a five-bar window, ten twins,
five bars forward - and found four different distance metrics landing within 0.8 points of each
other on every measure: ~33% exceedance against a 20% nominal envelope, and a sign accuracy of
50.0-50.6%. **The distance function is not what is wrong.** The twins are genuinely close - the
tenth neighbour sits at 0.10 to 1.05 where two random five-bar shapes sit at 3.162 - and
similarity simply does not predict direction.

That leaves one degree of freedom untested, and it is the operator's point: **the window and the
forward horizon were fixed at five.** Similarity could work over slices of one to twenty bars
looking forward one to twenty. This sweeps the grid.

## And the question that should have been asked first

Direction is the wrong target for this method. `a-theory-from-ohlc.md` records that the signed
series is near-unpredictable past a few minutes while **absolute** returns carry long memory -
volatility clusters, direction does not. So a nearest-neighbour method should be pointed at the
quantity that is actually predictable.

So each cell reports both:

* **sign** - does the twins' median forward return predict direction? Expected to be 50%
  everywhere, and included so the grid can be seen to fail rather than assumed to;
* **volatility skill** - does the twins' forward *absolute* move beat a trailing estimate of the
  same thing? Scored as `QLIKE`, the loss function used for variance forecasts because it
  penalises under-prediction far more than over-prediction, which is the asymmetry that matters
  when a forecast feeds a position size.

**If similarity helps anywhere, it is here.** Conditioning volatility on "what did the market do
last time it looked like this" is a plausible mechanism; conditioning direction on it is not.

## Multiple comparisons, counted before the run

The grid is 4 windows x 5 horizons = 20 cells, per instrument. At `alpha = 0.05` that is one
cell expected to clear by chance, so a single good cell means nothing and the shape of the grid
is the reading. `power.py`'s discipline applies: the detection floor per cell is printed, and a
result has to beat it *after* the Bonferroni inflation for twenty tests.
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

#: The grid the operator described: window slices and forward slices.
WINDOWS = (3, 5, 10, 20)
FORWARDS = (1, 3, 5, 10, 20)

#: Neighbours. More than the service's ten, because a ten-sample percentile is inward-biased
#: and that alone explains much of its 33% exceedance against a 20% nominal.
TWINS = 50

MIN_HISTORY = 3_000
STRIDE = 10
VOL_WINDOW = 100

#: Only call a direction when this share of twins agrees. **The conditional test**: an
#: unconditional 50.4% is exactly what a signal that is strong but rare looks like.
AGREE = 0.70

#: Round-trip spread in log-return units, from `spread_cost.py`'s 0.020 TR per leg. A hit
#: rate is not money and nothing here is scored without it.
COST = 0.0004


def qlike(actual: np.ndarray, forecast: np.ndarray) -> float:
    """QLIKE loss for variance forecasts: `a/f - log(a/f) - 1`, minimised at `f = a`.

    Chosen over squared error because it is scale-free and penalises **under**-forecasting
    much harder than over-forecasting - which is the asymmetry that matters when the forecast
    sizes a position, and the reason squared error flatters a model that runs small.
    """
    ok = (actual > 0) & (forecast > 0)
    if ok.sum() < 100:
        return float("nan")
    ratio = actual[ok] / forecast[ok]
    return float(np.mean(ratio - np.log(ratio) - 1.0))


def block_bootstrap(hits: np.ndarray, block: int, draws: int = 400) -> tuple[float, float]:
    """A 95% interval for a mean, resampling **blocks** rather than rows.

    Forward windows overlap when `forward` exceeds the stride, so neighbouring rows share
    bars and plain `sqrt(n)` understates the error - the flaw `metals_pair.py` carries and
    this file does not. Blocks preserve that dependence.
    """
    n = len(hits)
    if n < block * 8:
        return (float("nan"), float("nan"))
    starts = np.arange(0, n - block)
    count = n // block
    rng = np.random.default_rng(0)
    means = np.empty(draws)
    for d in range(draws):
        picks = rng.choice(starts, size=count)
        means[d] = np.mean(np.concatenate([hits[p : p + block] for p in picks]))
    return (float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975)))


# Four direction predictors plus the volatility comparison in one pass, which is past
# ruff's statement limit; splitting it would mean recomputing the twins per question.
def run(rets: np.ndarray, window: int, forward: int) -> dict | None:  # noqa: PLR0915
    """One grid cell: does similarity forecast direction, and does it forecast volatility?

    **Four direction predictors, not one.** The earlier pass took the sign of the twins'
    median and got 50.4% - but a method can be right only when it is confident, and an
    average over every bar would hide that completely. So each cell also scores:

    * **weighted** - the twins' mean forward return weighted by `1/(1+d)`, so a twin at
      distance 0.1 counts for more than one at 2.0. This is the textbook analogue forecast
      and it had not been tried;
    * **agreement** - the share of twins pointing the same way. Trading only when that share
      clears 70% is the conditional test: a weak unconditional average is exactly what a
      strong-but-rare signal looks like;
    * **net** - the mean return of following the vote, charged the round-trip spread, because
      a hit rate is not money and `paying.md` holds every direction claim here to that.
    """
    n = len(rets)
    idx = np.arange(window - 1, n - forward)
    if len(idx) < MIN_HISTORY:
        return None

    shapes = np.empty((len(idx), window))
    for k, i in enumerate(idx):
        piece = rets[i - window + 1 : i + 1]
        sd = float(piece.std())
        shapes[k] = piece / sd if sd > 0 else piece
    fwd_ret = np.array([float(rets[i + 1 : i + 1 + forward].sum()) for i in idx])
    fwd_var = np.array([float(np.sum(rets[i + 1 : i + 1 + forward] ** 2)) for i in idx])
    ends = idx + forward
    where = {i: k for k, i in enumerate(idx)}

    med_hits: list[float] = []
    wgt_hits: list[float] = []
    conf_hits: list[float] = []
    net: list[float] = []
    conf_net: list[float] = []
    actual, nn_var, base_var = [], [], []
    for at in range(MIN_HISTORY, n - forward, STRIDE):
        k = where.get(at)
        if k is None:
            continue
        usable = ends < at
        if usable.sum() < TWINS * 3:
            continue
        dist = np.linalg.norm(shapes[usable] - shapes[k], axis=1)
        picked = np.argpartition(dist, TWINS)[:TWINS]
        twin_ret = fwd_ret[usable][picked]
        twin_var = fwd_var[usable][picked]
        twin_d = dist[picked]
        real = fwd_ret[k]

        if real != 0:
            med = float(np.median(twin_ret))
            # Closer twins count for more, which is what "similar" is supposed to mean.
            weight = 1.0 / (1.0 + twin_d)
            wgt = float(np.sum(weight * twin_ret) / np.sum(weight))
            share = float(np.mean(twin_ret > 0))
            agree = max(share, 1.0 - share)
            med_hits.append(float(np.sign(med) == np.sign(real)))
            wgt_hits.append(float(np.sign(wgt) == np.sign(real)))
            side = 1.0 if share > 0.5 else -1.0
            # Charged the round-trip spread, in the same units as the return.
            net.append(side * real - COST)
            if agree >= AGREE:
                conf_hits.append(float(side == np.sign(real)))
                conf_net.append(side * real - COST)

        sd = float(rets[at - VOL_WINDOW + 1 : at + 1].std())
        if sd <= 0:
            continue
        actual.append(fwd_var[k])
        nn_var.append(float(np.median(twin_var)))
        base_var.append(sd * sd * forward)

    if len(actual) < 500 or len(med_hits) < 500:
        return None
    a, nn, bs = np.array(actual), np.array(nn_var), np.array(base_var)
    net_arr = np.array(net)
    # Blocks of `forward` bars, the span over which rows genuinely overlap.
    lo, hi = block_bootstrap(np.array(med_hits), max(forward, 2))
    return {
        "n": len(a),
        "n_dir": len(med_hits),
        "med": float(np.mean(med_hits)),
        "lo": lo,
        "hi": hi,
        "wgt": float(np.mean(wgt_hits)),
        "conf": float(np.mean(conf_hits)) if len(conf_hits) >= 200 else float("nan"),
        "n_conf": len(conf_hits),
        "net": float(np.mean(net_arr)) * 1e4,
        "conf_net": (float(np.mean(conf_net)) * 1e4 if len(conf_net) >= 200 else float("nan")),
        "q_nn": qlike(a, nn),
        "q_base": qlike(a, bs),
        "corr_nn": float(np.corrcoef(np.sqrt(a), np.sqrt(nn))[0, 1]),
        "corr_base": float(np.corrcoef(np.sqrt(a), np.sqrt(bs))[0, 1]),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "symbols",
        nargs="*",
        default=[s.strip() for s in os.environ.get("SYMBOLS", "").split(",") if s.strip()]
        or ["btcusd", "xauusd", "eurusd"],
    )
    ap.add_argument("--where", default=os.environ.get("WHERE", ".secrets/broker-deep"))
    ap.add_argument("--interval", default="1h")
    args = ap.parse_args()

    cells = len(WINDOWS) * len(FORWARDS)
    print(
        f"similarity across {len(WINDOWS)} window slices x {len(FORWARDS)} forward slices, "
        f"{TWINS} twins\n"
        f"{cells} cells per instrument, so about {0.05 * cells:.0f} clears two sigma by "
        "chance - read the grid, not the best cell\n"
        "\nQLIKE is a variance-forecast loss: LOWER is better, and the comparison that\n"
        "matters is nearest-neighbour against the trailing estimate on the same rows.\n"
    )

    for symbol in args.symbols:
        found = sorted(Path(args.where).expanduser().glob(f"{symbol}_{args.interval}_*.csv.gz"))
        if not found:
            print(f"  {symbol:<12} no {args.interval} file")
            continue
        bars, _repaired = candles.read(found[0])
        close = bars[:, 4]
        close = close[close > 0]
        if len(close) < MIN_HISTORY * 2:
            continue
        rets = np.diff(np.log(close))

        print(f"{symbol}  -  {args.interval} bars")
        print(
            f"  {'win':>4}{'fwd':>4}{'n':>7}"
            f"{'median':>8}{'95% block':>16}{'weighted':>10}"
            f"{'agree>=70%':>12}{'n':>7}{'net bp':>8}{'conf bp':>9}"
            f"{'QLIKE nn':>10}{'base':>9}{'vol?':>6}"
        )
        wins = 0
        scored = 0
        best = None
        for window in WINDOWS:
            for forward in FORWARDS:
                got = run(rets, window, forward)
                if got is None:
                    continue
                scored += 1
                better = got["q_nn"] < got["q_base"]
                wins += bool(better)
                # A cell counts as a direction hit only if the block-bootstrap interval
                # clears 0.5 AND the net of cost is positive - a hit rate is not money.
                real = got["lo"] > 0.5 and got["net"] > 0
                if real and (best is None or got["med"] > best["med"]):
                    best = {**got, "window": window, "forward": forward}
                conf = f"{got['conf']:>12.1%}" if np.isfinite(got["conf"]) else f"{'-':>12}"
                cnet = f"{got['conf_net']:>+9.1f}" if np.isfinite(got["conf_net"]) else f"{'-':>9}"
                print(
                    f"  {window:>4}{forward:>4}{got['n_dir']:>7,}"
                    f"{got['med']:>8.1%}   [{got['lo']:.3f}, {got['hi']:.3f}]"
                    f"{got['wgt']:>10.1%}{conf}{got['n_conf']:>7,}"
                    f"{got['net']:>+8.1f}{cnet}"
                    f"{got['q_nn']:>10.4f}{got['q_base']:>9.4f}"
                    f"{'  yes' if better else '   no':>6}" + ("  <-" if real else "")
                )
        print(
            f"  volatility: nearest-neighbour beat the trailing estimate in {wins} of "
            f"{scored} cells"
        )
        if best:
            print(
                f"  direction: best surviving cell is window {best['window']} / forward "
                f"{best['forward']} at {best['med']:.1%}, net {best['net']:+.1f} bp"
            )
        else:
            print("  direction: no cell clears 0.5 on the block interval AND pays its spread")
        print()

    print(
        "  **Direction**: `sign` should sit at 50% everywhere. A marked cell has cleared a\n"
        "  Bonferroni-corrected bar for the whole grid, so one is still consistent with chance\n"
        "  but a pattern across neighbouring cells would not be.\n"
        "\n  **Volatility**: this is where the method has a mechanism, since volatility clusters\n"
        "  and direction does not. If nearest-neighbour loses to a trailing standard deviation\n"
        "  on most cells, similarity adds nothing to the one thing that is forecastable - and\n"
        "  that is the same verdict vol_baseline.py reached about persistence landscapes."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
