"""Is the innovation's mean reversion bigger than the spread it would cost to trade?

Asked on 2026-10-10, and the order is deliberate: **the cost test gates
everything else.** The reversion is real - signed `z` predicts the move against
it with `t = -4.3` at 3m rising to `-8.1` at ten bars - and real is not the same
as usable. At 3m one volatility unit is a fraction of a pip and the spread is
around a pip, so the whole effect may sit inside the cost of taking it. If it
does, improving the estimate is worthless and the honest thing is to stop.

`data/seqlab/*.npz` carries a `spread` array beside `close`, which is what makes
this answerable rather than arguable.

## The four things asked for, in the order that decides

1. **Against the spread.** Convert the predicted reversion into price and divide
   by the median spread. **Below 1.0 and the idea is dead** whatever the t-stat
   says. Reported in spread units at every horizon.
2. **Robustified.** A `z` driven by a wick is a liquidity grab - information
   about where stops were, not about where the level is - and at fast timeframes
   the innovation is dominated by which side of the book the close printed on,
   which mean-reverts by construction. Clipping `z` at the Huber gate is the one
   change that could separate the two, because it discards exactly the prints
   that cause the bounce. Reported against the unclipped version.
3. **Held for ten bars, not one.** The effect accrues monotonically to `h = 10`
   at 3m, so one spread paid over ten bars is the only version with a chance of
   clearing cost. The table is per horizon for that reason.
4. **Confirmed across resolutions.** 3m and 15m both show it. A surprise
   confirmed at both is a stronger claim than either alone, and it is D3/MIMO
   stated as a measurement rather than as a design.

## What this is not

Not a backtest. There is no entry rule, no stop, no sizing and no slippage
beyond the quoted spread, and a regression slope is not a trade. It answers one
question - is the effect larger than the most optimistic estimate of its cost -
and a yes would mean the next step is a real harness, not a position.

Runs on the lab. Production has two cores and a 2.6GB container limit, and
research on it OOM-killed the live desk three times - see `research/starving.md`.
"""

from __future__ import annotations

import math
import os
import statistics
from pathlib import Path

from till_infinity.statespace.selective import Selective

#: `(label, seqlab stem)`. The fast timeframes are where the effect lives, so
#: this does not bother with the slow end that showed nothing.
SYMBOLS = (
    ("eurusd", "EURUSD"),
    ("xauusd", "XAUUSD"),
    ("gbpusd", "GBPUSD"),
    ("usdjpy", "USDJPY"),
    ("v75", "Volatility_75_Index"),
)

#: 3m and 15m carried the effect; 1h is the control that did not.
FRAMES = ("3m", "15m", "1h")

HORIZONS = (1, 2, 5, 10, 20)

#: The Huber gate, in standard deviations of the innovation. `robust.py`'s
#: starting point, and it is **not measured** there either - the honest way to
#: set it is the distribution of realised innovations, which is what this
#: harness happens to produce.
GATE = float(os.environ.get("GATE", "2.5"))

LIMIT = int(os.environ.get("LIMIT", "20000"))
NOISE = float(os.environ.get("NOISE", "0.4"))

#: The winning S4D-Real parameters from the four-symbol run: `scale = 0` makes
#: it the LTI nested null, which is the member that was both best-fitting and
#: best-calibrated.
DRIFT = float(os.environ.get("DRIFT", "4.0"))


def load(stem: str, frame: str):
    """`(times, closes, spreads)` from a seqlab npz, oldest first."""
    import numpy as np

    path = Path(f"data/seqlab/{stem}.{frame}.npz")
    if not path.exists():
        return None
    with np.load(path) as bundle:
        keys = set(bundle.keys())
        if not {"time", "close"} <= keys:
            return None
        order = np.argsort(bundle["time"])
        times = bundle["time"][order]
        closes = bundle["close"][order]
        spreads = bundle["spread"][order] if "spread" in keys else np.zeros_like(closes)
    if len(closes) > LIMIT:
        times, closes, spreads = times[-LIMIT:], closes[-LIMIT:], spreads[-LIMIT:]
    return times, closes, spreads


def tick_size(closes) -> float:
    """The smallest price increment, inferred from the series itself.

    **The npz `spread` is in points, not price**, and the first run of this
    harness divided as though it were price - which inflated the cost by
    `1/tick`, a factor of 100,000 on EURUSD, and reported the median spread as
    **136 volatility units** when a bar moves about one. A spread 136 times the
    bar move would mean the market is untradeable, which is how the error
    announced itself.

    Inferring it beats hard-coding digits per symbol: the minimum non-zero
    absolute change recovers 0.00001 for EURUSD, 0.001 for USDJPY and 0.01 for
    XAUUSD and the synthetics, which are the right answers.
    """
    diffs = [abs(closes[i] - closes[i - 1]) for i in range(1, len(closes))]
    positive = [d for d in diffs if d > 0]
    return min(positive) if positive else 0.0


def normalise(closes):
    """To volatility units of the series' own bar, and the price of one unit.

    The second return value is what makes the cost test possible: everything
    downstream is in volatility units and a spread is in price, so the
    conversion has to be explicit rather than assumed.
    """
    alpha = 1.0 - 0.5 ** (1.0 / 60.0)
    average = 0.0
    for i in range(1, len(closes)):
        move = abs(closes[i] - closes[i - 1]) / closes[i - 1] * 10_000
        average = move if i == 1 else average + alpha * (move - average)
    bps = max(average, 0.25)
    values = [(c / closes[0] - 1.0) * 10_000 / bps for c in closes]
    #: Price of one volatility unit: `bps` basis points of the first close.
    unit = bps * closes[0] / 10_000
    return values, unit


def slope(xs, ys):
    """`(beta, t, n)` for `ys = a + beta*xs`."""
    n = len(xs)
    if n < 50:
        return 0.0, 0.0, n
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return 0.0, 0.0, n
    beta = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sxx
    resid = [y - my - beta * (x - mx) for x, y in zip(xs, ys, strict=True)]
    s2 = sum(r * r for r in resid) / max(n - 2, 1)
    se = math.sqrt(s2 / sxx) if sxx > 0 else 0.0
    return beta, (beta / se if se > 0 else 0.0), n


def innovations(times, values):
    """Run the member and keep its standardised innovation at every bar."""
    engine = Selective(drift=DRIFT, scale=0.0, gain=1.0, noise=1.0)
    zs = []
    for when, value in zip(times, values, strict=True):
        engine.predict(float(when))
        engine.update(value, NOISE, float(when))
        zs.append(engine.last_standardised)
    return zs


def main() -> None:
    print("Is the innovation's reversion bigger than the spread?")
    print(f"gate={GATE} sigma, drift={DRIFT}, up to {LIMIT} bars a series\n")

    multi: dict[tuple[str, str], tuple] = {}

    print("=== 1 to 3. the reversion, robustified, per horizon, in SPREAD UNITS ===")
    print("    'edge' is the predicted move for a 2-sigma surprise, divided by")
    print("    the median spread. **Below 1.0 the effect is inside the cost.**\n")
    for label, stem in SYMBOLS:
        for frame in FRAMES:
            loaded = load(stem, frame)
            if loaded is None:
                print(f"  {label} {frame:<4} no file")
                continue
            times, closes, spreads = loaded
            values, unit = normalise(closes)
            zs = innovations(times, values)
            tick = tick_size(closes)
            points = [float(s) for s in spreads if s > 0]
            if not points or tick <= 0:
                print(f"  {label} {frame:<4} no spread recorded, cannot cost it")
                continue
            # Points to price, which is the whole point of `tick`.
            median_spread = float(statistics.median(points)) * tick
            multi[(label, frame)] = (times, values, zs)

            print(
                f"  {label} {frame}  1 vol unit = {unit:.6g} price, tick = {tick:.6g},"
                f" median spread = {statistics.median(points):.0f} points"
                f" = {median_spread:.6g} price = {median_spread / unit:.3f} vol units"
            )
            print(f"    {'h':>4}{'slope':>10}{'t':>7}{'clipped':>10}{'t':>7}"
                  f"{'edge (spreads)':>16}{'clipped edge':>14}")
            for h in HORIZONS:
                raw_x, raw_y, cut_x = [], [], []
                for k in range(len(values) - h):
                    raw_x.append(zs[k])
                    cut_x.append(max(-GATE, min(GATE, zs[k])))
                    raw_y.append(values[k + h] - values[k])
                b, t, _ = slope(raw_x, raw_y)
                bc, tc, _ = slope(cut_x, raw_y)
                # A two-sigma surprise, in price, against one spread.
                edge = abs(b * 2.0) * unit / median_spread
                edge_c = abs(bc * 2.0) * unit / median_spread
                print(f"    {h:>4}{b:>+10.4f}{t:>+7.1f}{bc:>+10.4f}{tc:>+7.1f}"
                      f"{edge:>16.3f}{edge_c:>14.3f}")
            print()

    print("=== 4. confirmed across resolutions: 3m and 15m agreeing ===")
    print("    the 15m innovation carried onto the 3m clock, and the 3m move")
    print("    regressed on each alone and on the pair agreeing in sign\n")
    for label, _stem in SYMBOLS:
        fast = multi.get((label, "3m"))
        slow = multi.get((label, "15m"))
        if not fast or not slow:
            continue
        ftimes, fvalues, fzs = fast
        stimes, _svalues, szs = slow
        # Carry the most recent **completed** 15m innovation onto each 3m bar.
        #
        # **The lag is the whole correctness of this.** A 15m bar stamped at T
        # does not close until T+15m, so its innovation is not known until
        # then; attaching it to 3m bars from T onward uses up to twelve minutes
        # of the future. The first version did exactly that and reported slopes
        # of +0.43 to +0.73 at t of +14.5 to +20.8, uniformly positive across
        # all five symbols **including the synthetic generator** - which is the
        # signature of leakage rather than of structure, and is how it was
        # caught. One bar of lag is the fix.
        carried, j = [], 0
        for when in ftimes:
            while j + 1 < len(stimes) and stimes[j + 1] <= when:
                j += 1
            # `j` is the bar containing `when`; `j - 1` is the last one that
            # had closed by then.
            carried.append(szs[j - 1] if j >= 1 and stimes[j] <= when else 0.0)

        h = 10
        both_x, both_y, alone_x = [], [], []
        for k in range(len(fvalues) - h):
            move = fvalues[k + h] - fvalues[k]
            alone_x.append(fzs[k])
            # Agreement: same sign, and the magnitude is the smaller of the two.
            agree = (
                math.copysign(min(abs(fzs[k]), abs(carried[k])), fzs[k])
                if fzs[k] * carried[k] > 0
                else 0.0
            )
            both_x.append(agree)
            both_y.append(move)
        b1, t1, n1 = slope(alone_x, both_y)
        b2, t2, _ = slope(both_x, both_y)
        share = statistics.fmean(1.0 if x != 0.0 else 0.0 for x in both_x)
        print(f"  {label:<8} 3m alone  slope {b1:+.4f} t {t1:+5.1f}   "
              f"3m+15m agreeing  slope {b2:+.4f} t {t2:+5.1f}   "
              f"(agreed on {share:.0%} of {n1:,} bars)")


if __name__ == "__main__":
    main()
