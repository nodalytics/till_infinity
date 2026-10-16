"""Does statespace's own innovation carry anything, or is it a trailing z-score?

`facade.Readout` now publishes `surprise`, the standardised one-step
innovation, because `Desk.read` already computed it for the quantile band and
a caller could not reconstruct it. That makes it the natural first term for
the output layer in
[`statespace/signalling.py`](../../till_infinity/structures/statespace/signalling.py),
and `terms_from` offers it.

**It is also the most suspicious term available**, and the suspicion is
measured rather than theoretical. `trailing-zscore-fakes-reversion`: a trailing
z-score's shuffled twin took **+0.111 of a +0.137 effect** at `z` 4.23, worth
more than an fx cross's spread. A Kalman innovation is a trailing z-score with
a better estimate of the centre, so it inherits the whole problem.

## The two arms that matter

**The twin.** Reorder 96-bar blocks of the returns and rebuild, so volatility
clustering survives inside a block and the path's memory across blocks does
not. Every bar then has the same geometry and the same filter runs over it.
Whatever the twin scores, the real series has to beat.

**The base of the forward return.** A surprise at bar `t` is computed from
`close(t)`, and a forward return measured from `close(t)` shares that price. A
positive measurement error in it - a bid-ask bounce, a bad print, a thin close
- inflates the surprise and depresses the return by the same amount, which is
reversion out of nothing. So the return is measured twice:

- from `close(t)`, the naive base, which carries the artefact;
- from `close(t+1)`, which does not share a price with the surprise.

The gap between those two columns **is** the artefact, measured.

## What is swept, and why the noise is a sweep and not a constant

`Desk.read` takes the measurement **variance**, and how much the filter trusts
each bar decides how much of the bar the innovation keeps. At a tiny noise the
filter chases the price and the innovation is small; at a large noise the
filter lags and the innovation is mostly the bar's own move. That is the whole
character of the term, so it is swept as a multiple of the bar's own range
rather than fixed and hoped over.

Log prices are filtered rather than prices, so one noise setting means the same
thing on EURUSD and on gold. The innovation is standardised, so nothing about
the comparison depends on that choice.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from signal_layer import auc, load  # noqa: E402

from till_infinity.structures.statespace import terms_from  # noqa: E402
from till_infinity.structures.statespace.behaving import drives_q  # noqa: E402
from till_infinity.structures.statespace.facade import Desk  # noqa: E402

FRAME = "1h"
#: Measurement standard deviation as a multiple of a quarter of the bar's own
#: log range, since a bar spans roughly four standard deviations.
NOISES = (0.25, 1.0, 4.0)
HORIZONS = (1, 3, 12)
#: Bars per instrument. The filter costs about 0.9ms a bar, so this is the
#: budget rather than a statistical choice.
BARS = 12000
BLOCK = 96
SEED = 20261016
TRADED = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "AUDUSD", "USDCAD", "EURJPY", "XAGUSD")
GENERATED = ("Volatility_75_Index", "Step_Index_200")
ARMS = ("real", "blocks")


def shuffled(bars: dict, rng) -> dict:
    """96-bar blocks of the returns reordered, the bar geometry preserved.

    The same twin `signal_layer.py` uses: clustering survives inside a block,
    the path's memory across blocks does not, and `volume` is left in place so
    the pacing mechanism sees exactly what it saw on the real series.
    """
    closes = bars["close"]
    steps = np.diff(np.log(np.maximum(closes, 1e-12)))
    pieces = np.array_split(steps, max(len(steps) // BLOCK, 2))
    rng.shuffle(pieces)
    rebuilt = float(closes[0]) * np.exp(np.cumsum(np.concatenate(pieces)))
    span = slice(1, len(rebuilt) + 1)
    scale = rebuilt / np.maximum(closes[span], 1e-12)
    out = {}
    for key, column in bars.items():
        cut = column[span]
        out[key] = cut * scale if key in {"open", "high", "low", "close"} else cut
    return out


def readings(bars: dict, feed: str, noise_scale: float) -> dict[str, np.ndarray]:
    """Run the filter over one series and keep every term it offers."""
    price = np.log(np.maximum(bars["close"], 1e-12))
    high = np.log(np.maximum(bars["high"], 1e-12))
    low = np.log(np.maximum(bars["low"], 1e-12))
    volume = bars.get("volume")
    reach = np.maximum(high - low, 1e-9)
    desk = Desk()
    surprise = np.full(len(price), np.nan)
    pace = np.full(len(price), np.nan)
    for i in range(len(price)):
        got = desk.read(
            feed,
            FRAME,
            float(bars["time"][i]),
            float(price[i]),
            float((noise_scale * reach[i] / 4.0) ** 2),
            volume=float(volume[i]) if volume is not None else 0.0,
        )
        if got.warm:
            terms = terms_from(got)
            surprise[i] = terms["surprise"]
            pace[i] = terms["pace"]
    return {"surprise": surprise, "pace": pace, "price": price}


def scored(got: dict[str, np.ndarray], horizon: int, base: str) -> dict[str, float]:
    """AUC of each term against the forward direction, on one base.

    The sign convention: `-surprise` is scored, so a reading above 0.5 means
    **reversion** - a bar that came in above the filter is followed by a move
    down.
    """
    price = got["price"]
    start = 1 if base == "t+1" else 0
    out = {}
    ahead = np.full(len(price), np.nan)
    top = len(price) - horizon - start
    if top > 0:
        ahead[:top] = price[start + horizon : start + horizon + top] - price[start : start + top]
    for name, column in (("surprise", -got["surprise"]), ("pace", got["pace"])):
        keep = np.isfinite(column) & np.isfinite(ahead)
        out[name] = (
            auc(column[keep], (ahead[keep] > 0).astype(float)) if keep.sum() > 500 else float("nan")
        )
    usable = np.isfinite(got["surprise"]) & np.isfinite(ahead)
    out["n"] = float(usable.sum())
    return out


def main() -> None:
    rng = np.random.default_rng(SEED)
    print(
        "Statespace's own innovation, against a block twin and against the base of\n"
        f"the forward return. {FRAME} bars, up to {BARS:,} per instrument,\n"
        f"noise swept at {NOISES} times a quarter of each bar's log range.\n"
    )
    names = (*TRADED, *GENERATED)
    series: dict[str, dict] = {}
    for name in names:
        bars = load(name, FRAME)
        if bars is None:
            continue
        bars = {k: np.asarray(v, dtype=float)[-BARS:] for k, v in bars.items()}
        series[name] = bars
    print(f"  loaded {len(series)} instruments, pacing live on: ", end="")
    print(", ".join(n for n in series if drives_q(n)) or "none")

    for noise in NOISES:
        print("\n" + "=" * 100)
        print(f"noise {noise} x range/4")
        print("=" * 100)
        head = "".join(f"{b:>9}{'twin':>8}{'edge':>8}" for b in ("t", "t+1"))
        print(f"  {'instrument':<22}{'h':>3}" + head + f"{'pace':>9}{'twin':>8}{'edge':>8}")
        pooled: dict[tuple[int, str, bool], list[float]] = {}
        for name, bars in series.items():
            # Pooled separately, because the pacing mechanism is inert on a feed
            # whose generator fixes its tick count and reads **exactly** 0.5
            # there. Pooling those zeros with the live feeds put the median of
            # ten instruments on a control, which reads as "perfectly neutral"
            # and is nothing of the kind.
            live = bool(drives_q(name))
            got = {
                "real": readings(bars, name, noise),
                "blocks": readings(shuffled(bars, rng), name, noise),
            }
            for horizon in HORIZONS:
                line = f"  {name:<22}{horizon:>3}"
                for base in ("t", "t+1"):
                    here = scored(got["real"], horizon, base)
                    there = scored(got["blocks"], horizon, base)
                    line += f"{here['surprise']:>9.4f}{there['surprise']:>8.4f}"
                    line += f"{here['surprise'] - there['surprise']:>+8.4f}"
                    pooled.setdefault((horizon, base, live), []).append(
                        here["surprise"] - there["surprise"]
                    )
                    if base == "t+1":
                        # `pace` is read on the honest base only. It is the one
                        # term here with a relative in the measured column:
                        # `signal-layer.md` found tick volume carrying +0.026
                        # to +0.055 of edge where every price term was a coin.
                        line += f"{here['pace']:>9.4f}{there['pace']:>8.4f}"
                        line += f"{here['pace'] - there['pace']:>+8.4f}"
                        pooled.setdefault((horizon, "pace", live), []).append(
                            here["pace"] - there["pace"]
                        )
                print(line)
        print()
        for horizon in HORIZONS:
            parts = []
            for base in ("t", "t+1", "pace"):
                edges = [e for e in pooled.get((horizon, base, True), []) if e == e]
                parts.append(float(np.median(edges)) if edges else float("nan"))
            held = [e for e in pooled.get((horizon, "t+1", False), []) if e == e]
            other = float(np.median(held)) if held else float("nan")
            print(
                f"  h {horizon:<3} median edge, feeds where pacing is live:  surprise base t"
                f" {parts[0]:+.4f}   base t+1 {parts[1]:+.4f}"
                f"   artefact {parts[0] - parts[1]:+.4f}   pace {parts[2]:+.4f}"
                f"   | generated, surprise {other:+.4f}"
            )
    print(
        "\n  `artefact` is the base-t edge minus the base-t+1 edge: the part of the\n"
        "  reversion that comes from the surprise and the return sharing a close.\n"
    )


if __name__ == "__main__":
    main()
