"""Do corrections retrace 86% of the rally before them, and is 0.86 a market fact?

A specific, falsifiable constant is a rare thing to be handed, and this one is
sharp: **a cycle is a rally followed by a correction of `alpha` times it, with
`alpha = 0.86`, so the cycle nets 14%.** A number that precise either survives
contact with data or dies on it, which is more than most claims offer.

## Why the first question is about the detector and not the market

A retracement fraction is not read off prices. It is read off **swings**, and a
swing only exists once a detector says so. Every zigzag-family detector takes a
threshold `theta` and records a turn only when price reverses by at least that
much - which means **every correction it records is at least `theta`, and every
rally it records is at least `theta`.** The ratio of two quantities that have
both been truncated from below is not the ratio of the underlying quantities,
and its central tendency is a function of `theta`.

So the constant has three possible explanations and they need separating:

1. **A market fact** - real feeds show it, simulated Brownian motion does not.
2. **A martingale fact** - everything shows it, including pure Brownian motion,
   in which case it is a property of random walks and not of markets, and
   carries no information about what happens next.
3. **A detector artefact** - it moves with `theta`, in which case it is a
   property of the measuring instrument and nothing else.

Only the first would be worth anything, and the prior is strongly against it.
`research/deriving.md` proves these feeds are martingales and
`research/generated.md` found the synthetics are textbook geometric Brownian
motion at `H = 0.50` - so if 0.86 appears on *them* it cannot be a market fact,
because there is no market in them.

## The design

**Three populations, one detector, one threshold sweep.**

* **real** - the five real feeds, where a market fact would live.
* **volatility** - the generated family, where `generated.md` says there is no
  structure at all, so anything found is the detector.
* **gbm** - a simulator at each feed's own measured sigma, which is the same
  claim with the data manufactured rather than collected.

The threshold is swept in **volatility units** rather than price, because a
fixed pip threshold means something different on gold at $4,400 and on
`volatility_10_index` at 1.0, and a sweep in price would be a sweep in how many
swings exist rather than in how they are measured.

**The reading is the sweep, not the level.** If `alpha` sits at 0.86 on one
threshold and moves to 0.6 or 1.1 on another, the constant is the instrument. If
it is flat in `theta` and equal across all three populations, it is a property of
random walks. If it is flat in `theta` and *differs* between real and simulated,
that is the one outcome worth a second study.

    ./.secrets/lab.sh run research/harness/retracing.py
"""

from __future__ import annotations

import math
import sys

import numpy as np

from research.harness import seqlab

#: The claimed constant, so the comparison is against a number rather than a
#: vibe.
CLAIMED = 0.86

#: Threshold sweep, in units of the series' own per-bar standard deviation. The
#: span is deliberately wide: the whole question is whether the answer moves.
THETAS = (0.5, 1.0, 2.0, 4.0, 8.0)

#: Timeframes. The claim is about cycles rather than a timeframe, so if it is
#: real it should not care which one it is measured on.
GRID = ("15m", "1h", "4h", "1d")

#: Fewest complete rally/correction pairs before a cell is reported.
FEWEST = 40


def zigzag(prices: np.ndarray, theta: float) -> list[int]:
    """Indices of alternating extremes, confirmed by a reversal of `theta`.

    Written out rather than imported so the truncation this study is about is
    visible: a candidate extreme becomes a turn **only** once price has moved
    `theta` against it, so nothing smaller than `theta` is ever recorded.

    **The first version of this returned one turn on every series and the study
    reported "no cell reached 40 pairs".** It tracked a single extreme and, while
    the direction was still undecided, moved that extreme toward price on *both*
    sides - so the distance from price to the extreme was always zero, no
    reversal could ever accumulate, and the direction never left undecided. The
    three states are explicit here for that reason: undecided looks both ways,
    an up leg only raises its high, a down leg only lowers its low.
    """
    n = len(prices)
    if n < 3 or theta <= 0:
        return []
    turns: list[int] = []
    hi = lo = float(prices[0])
    hi_at = lo_at = 0
    direction = 0  # 0 undecided, +1 up leg, -1 down leg
    for i in range(1, n):
        p = float(prices[i])
        if direction == 0:
            if p > hi:
                hi, hi_at = p, i
            if p < lo:
                lo, lo_at = p, i
            if p <= hi - theta:
                turns.append(hi_at)
                direction, lo, lo_at = -1, p, i
            elif p >= lo + theta:
                turns.append(lo_at)
                direction, hi, hi_at = 1, p, i
        elif direction == 1:
            if p > hi:
                hi, hi_at = p, i
            if p <= hi - theta:
                turns.append(hi_at)
                direction, lo, lo_at = -1, p, i
        else:
            if p < lo:
                lo, lo_at = p, i
            if p >= lo + theta:
                turns.append(lo_at)
                direction, hi, hi_at = 1, p, i
    return turns


def retracements(prices: np.ndarray, theta: float) -> np.ndarray:
    """`|correction| / |rally|` for every completed pair.

    Three consecutive turns are a rally and the correction that ended it. The
    pair is skipped when the rally is degenerate, which cannot happen under a
    working detector and is guarded rather than assumed.
    """
    turns = zigzag(prices, theta)
    out = []
    for a, b, c in zip(turns, turns[1:], turns[2:], strict=False):
        rally = abs(prices[b] - prices[a])
        correction = abs(prices[c] - prices[b])
        if rally > 0:
            out.append(correction / rally)
    return np.asarray(out, dtype=float)


def summarise(values: np.ndarray) -> dict:
    if len(values) < FEWEST:
        return {}
    return {
        "n": int(len(values)),
        "median": float(np.median(values)),
        "mean": float(np.mean(values)),
        # Share landing in a band around the claim. A constant that is real
        # should concentrate; one that is an artefact of a ratio will not.
        "near": float(np.mean((values >= 0.8) & (values <= 0.9))),
    }


def series_for(broker: str, interval: str, rng: np.random.Generator) -> dict[str, np.ndarray]:
    """The real closes, and a simulated path matched to their own volatility."""
    bars = seqlab.load(broker, interval)
    closes = np.asarray(bars["close"], dtype=float)
    logs = np.log(np.maximum(closes, 1e-12))
    sigma = float(np.std(np.diff(logs), ddof=1))
    n = len(logs)
    walk = logs[0] + np.cumsum(rng.normal(0.0, sigma, n))
    return {"feed": logs, "gbm": walk, "sigma": np.array([sigma])}


#: Simulated paths per cell when testing the gap. Each is an independent draw
#: at the feed's own measured sigma and its own length, so the spread of their
#: medians **is** the null distribution of the statistic - no bootstrap, no
#: normality assumption, and no serial-dependence correction to get wrong.
DRAWS = 200


def significance(theta: float, symbols: list[str], rng: np.random.Generator) -> dict:
    """Is a feed's retracement median below what its own Brownian null gives?

    The gap measured on one simulated path is not evidence: one path is one
    draw. `DRAWS` paths at the same sigma and the same length give the null
    distribution of the median directly, and the feed's rank in it is the
    p-value with nothing assumed about its shape.

    Two readings are returned because they answer different questions. The
    **per-cell rank** says whether this instrument is unusual against its own
    null. The **sign test across cells** says whether the direction is
    consistent, which is the claim that matters: twenty cells each at p = 0.3
    all leaning the same way is a result, and twenty cells scattered is not.
    """
    below = 0
    scored = 0
    ranks: list[float] = []
    gaps: list[float] = []
    for broker in symbols:
        for interval in GRID:
            try:
                bars = seqlab.load(broker, interval)
            except Exception:  # noqa: BLE001 - counted by the caller's table
                continue
            closes = np.asarray(bars["close"], dtype=float)
            logs = np.log(np.maximum(closes, 1e-12))
            sigma = float(np.std(np.diff(logs), ddof=1))
            if sigma <= 0:
                continue
            step = theta * sigma
            feed = retracements(logs, step)
            if len(feed) < FEWEST:
                continue
            got = float(np.median(feed))

            nulls = []
            for _ in range(DRAWS):
                walk = logs[0] + np.cumsum(rng.normal(0.0, sigma, len(logs)))
                drawn = retracements(walk, step)
                if len(drawn) >= FEWEST:
                    nulls.append(float(np.median(drawn)))
            if len(nulls) < DRAWS // 2:
                continue
            null = np.asarray(nulls)
            scored += 1
            # Share of the null at or below the feed: small means the feed sits
            # in the null's lower tail, which is the direction the gap points.
            rank = float((null <= got).mean())
            ranks.append(rank)
            gaps.append(got - float(np.median(null)))
            if got < float(np.median(null)):
                below += 1
    if not scored:
        return {}
    # Sign test: under no effect each cell is below its own null median with
    # probability one half, so the count is Binomial(scored, 0.5).
    mean = scored / 2.0
    sd = math.sqrt(scored * 0.25)
    z = (below - mean) / sd if sd > 0 else float("nan")
    return {
        "cells": scored,
        "below": below,
        "sign_z": z,
        "median_gap": float(np.median(gaps)),
        "median_rank": float(np.median(ranks)),
        "tail_cells": int(sum(1 for r in ranks if r <= 0.05)),
    }


#: Swings per block when asking whether alpha moves. Small enough that a block
#: is a period rather than the whole record, large enough that a block median is
#: not mostly its own noise.
BLOCK = 120


def moves(theta: float, symbols: list[str], rng: np.random.Generator) -> dict:
    """Does alpha vary over time, or is it a constant plus noise?

    **This is the question that decides whether an online estimator is worth
    building.** Tracking a quantity as it streams is trivial - `river` is already
    a dependency and a streaming quantile would do it in three lines. What that
    buys depends entirely on whether the quantity *moves*: if alpha is constant,
    an online estimate converges to the batch number and the only thing it adds
    over a batch fit is recency bias, which is a cost rather than a feature.

    Two readings, and they answer different halves:

    * **lag-1 autocorrelation of the block medians.** If this period's alpha
      predicts the next one, there is a state to track and online learning has a
      target. If it is zero, each block is an independent draw around one number.
    * **dispersion of the block medians against a matched Brownian null.** Real
      alpha wanders more than a constant would *by construction*, because a
      median of 120 ratios is noisy - so the question is whether it wanders more
      than the same statistic computed on simulated paths of the same length.
      The null supplies exactly the noise a constant alpha would produce.

    `research/predictable.py` asks the same shape of question about magnitude and
    direction, and its warning applies here: a series scored against itself
    autocorrelates by construction, so the blocks are disjoint and the medians
    are taken over non-overlapping swings.
    """
    real_ac, null_ac, real_sd, null_sd = [], [], [], []
    for broker in symbols:
        for interval in GRID:
            try:
                bars = seqlab.load(broker, interval)
            except Exception:  # noqa: BLE001
                continue
            closes = np.asarray(bars["close"], dtype=float)
            logs = np.log(np.maximum(closes, 1e-12))
            sigma = float(np.std(np.diff(logs), ddof=1))
            if sigma <= 0:
                continue
            step = theta * sigma

            def blocks(series: np.ndarray) -> np.ndarray:
                got = retracements(series, step)
                keep = (len(got) // BLOCK) * BLOCK
                if keep < BLOCK * 4:
                    return np.array([])
                return np.median(got[:keep].reshape(-1, BLOCK), axis=1)

            here = blocks(logs)
            if len(here) < 4:
                continue
            walk = logs[0] + np.cumsum(rng.normal(0.0, sigma, len(logs)))
            there = blocks(walk)
            if len(there) < 4:
                continue

            def lag1(x: np.ndarray) -> float:
                x = x - x.mean()
                denominator = float((x * x).sum())
                return float((x[:-1] * x[1:]).sum() / denominator) if denominator else np.nan

            for source, acs, sds in ((here, real_ac, real_sd), (there, null_ac, null_sd)):
                a = lag1(source)
                if np.isfinite(a):
                    acs.append(a)
                    sds.append(float(np.std(source, ddof=1)))
    if not real_ac:
        return {}
    ra, na = np.asarray(real_ac), np.asarray(null_ac)
    rs, ns = np.asarray(real_sd), np.asarray(null_sd)
    # Standard error of a lag-1 autocorrelation over k blocks is about
    # 1/sqrt(k); pooled over cells it shrinks by sqrt(cells).
    return {
        "cells": len(ra),
        "ac_feed": float(np.mean(ra)),
        "ac_null": float(np.mean(na)),
        "ac_t": float((np.mean(ra) - np.mean(na)) / (np.std(ra - na, ddof=1) / math.sqrt(len(ra)))),
        "sd_feed": float(np.mean(rs)),
        "sd_null": float(np.mean(ns)),
        "sd_ratio": float(np.mean(rs) / np.mean(ns)) if np.mean(ns) else float("nan"),
    }


def main() -> int:
    rng = np.random.default_rng(23)
    print("Does a correction retrace 0.86 of its rally, and is that a market fact?\n")
    print("alpha is the median of |correction| / |rally| over completed pairs.")
    print("theta is the zigzag threshold, in the series' own per-bar sigma.\n")

    groups = {
        "real": list(seqlab.REAL),
        "volatility": list(seqlab.VOLATILITY),
    }

    for name, symbols in groups.items():
        print("=" * 92)
        print(f"{name.upper()}")
        print("=" * 92)
        print(
            f"{'theta':>6} {'cells':>6} {'pairs':>9}  "
            f"{'alpha feed':>11} {'alpha gbm':>10} {'feed-gbm':>9}  "
            f"{'near.86 feed':>12} {'near.86 gbm':>11}"
        )
        for theta in THETAS:
            feed_all, gbm_all, cells = [], [], 0
            skipped: dict[str, int] = {}
            for broker in symbols:
                for interval in GRID:
                    try:
                        got = series_for(broker, interval, rng)
                    except Exception as exc:  # noqa: BLE001 - counted, not hidden
                        # **Reported rather than swallowed.** A bare `continue`
                        # here turned a detector that returned one turn on every
                        # series into the message "no cell reached 40 pairs",
                        # which reads as thin data rather than as a broken
                        # instrument.
                        skipped.setdefault(type(exc).__name__, 0)
                        skipped[type(exc).__name__] += 1
                        continue
                    sigma = float(got["sigma"][0])
                    if sigma <= 0:
                        continue
                    step = theta * sigma
                    f = retracements(got["feed"], step)
                    g = retracements(got["gbm"], step)
                    if len(f) >= FEWEST and len(g) >= FEWEST:
                        feed_all.append(f)
                        gbm_all.append(g)
                        cells += 1
            if not cells:
                why = ", ".join(f"{k} x{v}" for k, v in sorted(skipped.items())) or "none raised"
                print(f"{theta:>6.1f} {0:>6}  no cell reached {FEWEST} pairs ({why})")
                continue
            f = np.concatenate(feed_all)
            g = np.concatenate(gbm_all)
            sf, sg = summarise(f), summarise(g)
            print(
                f"{theta:>6.1f} {cells:>6} {sf['n']:>9,}  "
                f"{sf['median']:>11.4f} {sg['median']:>10.4f} "
                f"{sf['median'] - sg['median']:>9.4f}  "
                f"{sf['near']:>12.3f} {sg['near']:>11.3f}"
            )
        print()

    # ------------------------------------------------------------------ the gap
    print("=" * 92)
    print("IS THE REAL-MINUS-SIMULATED GAP SIGNIFICANT?")
    print("=" * 92)
    print(f"{DRAWS} independent Brownian paths per cell, at the feed's own sigma and length.")
    print("A cell counts as 'below' when its median sits under its own null's median.")
    print("sign z is that count against Binomial(cells, 0.5) - no effect means half.\n")
    print(
        f"{'group':12} {'theta':>6} {'cells':>6} {'below':>6} {'sign z':>8} "
        f"{'median gap':>11} {'median rank':>12} {'cells p<=.05':>13}"
    )
    for name, symbols in groups.items():
        for theta in (1.0, 4.0):
            got = significance(theta, symbols, rng)
            if not got:
                print(f"{name:12} {theta:>6.1f}  nothing scored")
                continue
            print(
                f"{name:12} {theta:>6.1f} {got['cells']:>6} {got['below']:>6} "
                f"{got['sign_z']:>8.2f} {got['median_gap']:>11.4f} "
                f"{got['median_rank']:>12.3f} {got['tail_cells']:>13}"
            )
    print()

    # ------------------------------------------------------- does alpha move?
    print("=" * 92)
    print("DOES ALPHA MOVE - is there anything for an online estimator to track?")
    print("=" * 92)
    print(f"Block medians over {BLOCK} disjoint swings. `ac` is their lag-1 autocorrelation:")
    print("a constant plus noise gives zero. `sd ratio` is how much more the feed's")
    print("blocks wander than the same statistic on a matched Brownian path.\n")
    print(
        f"{'group':12} {'theta':>6} {'cells':>6} {'ac feed':>9} {'ac null':>9} "
        f"{'t':>7} {'sd feed':>9} {'sd null':>9} {'sd ratio':>9}"
    )
    for name, symbols in groups.items():
        for theta in (1.0, 4.0):
            got = moves(theta, symbols, rng)
            if not got:
                print(f"{name:12} {theta:>6.1f}  nothing scored")
                continue
            print(
                f"{name:12} {theta:>6.1f} {got['cells']:>6} {got['ac_feed']:>9.4f} "
                f"{got['ac_null']:>9.4f} {got['ac_t']:>7.2f} {got['sd_feed']:>9.4f} "
                f"{got['sd_null']:>9.4f} {got['sd_ratio']:>9.3f}"
            )
    print()

    print("Reading it:")
    print("  * alpha moving with theta means the constant is the detector.")
    print("  * alpha equal on feed and gbm means it is a property of random walks,")
    print("    not of markets - and the generated family has no market in it at all.")
    print(f"  * only a gap between feed and gbm that is flat in theta would make {CLAIMED}")
    print("    a fact about the instrument being traded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
