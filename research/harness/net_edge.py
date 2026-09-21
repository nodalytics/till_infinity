"""The only positive result, costed properly: edge minus spread minus financing.

Run from the repository root:  python research/harness/net_edge.py

`jump_odds.py` found the one large structural deviation in this research: on Boom,
shorts beat the driftless fair-odds line by +4.1 points at a reward-to-risk of one, with
Crash mirroring it on longs and FX flat. Gross expectancy at that ratio is

    p (1 + r) - 1    with p = 0.541, r = 1  ->  +0.082 R

and this harness asks whether anything is left after paying to trade it.

## Two costs, and the second one nearly went unmeasured

**Spread** is settled and it is small. Measured from 20,000 hourly bars per symbol in
`spread_cost.py`, the synthetics quote a spread of **0.4% of one true range**, and it does
not widen - the median on the loudest 5% of bars is the same 0.004 as the median on all
bars, so a spike trade pays no premium. That is a twentieth of the 8.2% the edge can
afford, and it was the objection this study was originally set up to answer.

**Financing is the one that matters, and it is an order of magnitude larger.** The bridge
reports `swap_mode 5` on the synthetics, which is `SYMBOL_SWAP_MODE_INTEREST_CURRENT`: the
swap figure is an **annual percentage of notional**, not a number of points. Read as points
it would have come out around a thousandth of the truth. Boom 1000 charges 36% a year and
Crash 1000 18%, and - unusually - **both sides pay**, so there is no direction that earns
the carry back.

Converting at the measured true range, where 1 TR is 0.307% of notional on Boom 1000:

| instrument | annual | per day | in R per day | what 0.082 R buys |
|---|---|---|---|---|
| Boom 1000 | 36% | 0.0986% | 0.321 R | **6.1 hours** |
| Crash 1000 | 18% | 0.0493% | 0.161 R | **12.2 hours** |

So the edge pays for six hours of carry on Boom. `jump_odds.py` allowed **192 bars** to
resolve, which is eight days. If the average trade stays open anywhere near its horizon
the result is not merely reduced, it is inverted several times over.

That is what this measures: the same trades, with the **holding time recorded**, and the
carry charged against every one of them.

## Why the holding time is the whole answer

The gross edge does not depend on the horizon - it is a property of where the barriers
sit. The carry is strictly proportional to how long the position is open. So there is a
break-even holding time, and the study either comes in under it or it does not. Nothing
about this is a matter of interpretation, which is the reason it is worth running.

The mean holding time is charged, not the median, because carry is paid per hour and the
mean is what a sum of hours converges to. Trades that never resolve inside the horizon are
excluded from the hit rate, as in `jump_odds.py`, but they are the ones holding longest -
so excluding them **understates** the carry, and the honest reading of a marginal result
here is that it is worse than it looks.
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

#: Stop distance, in true ranges, held fixed as in `jump_odds.py`.
RISK = 1.0

#: Target distances, in true ranges.
REWARDS = (0.25, 0.5, 1.0, 2.0, 4.0)

#: Bars allowed to resolve, and the hours one bar represents.
HORIZON = 192
HOURS_PER_BAR = 1.0

#: Spread as a share of one true range, measured in `spread_cost.py` from 20,000 bars
#: per symbol. Flat across quiet bars, the 99th percentile and the loudest 5%.
SPREAD_R = {"boom": 0.004, "crash": 0.004, "default": 0.020}

#: Annual financing, percent of notional, from the bridge's `swap_long`/`swap_short`
#: with `swap_mode 5`. Both sides pay the same on the synthetics, so the direction of
#: the trade cannot avoid it. FX and metals use `swap_mode 1` (points) and are not
#: comparable here, so they are left out rather than converted wrongly.
ANNUAL_SWAP = {
    "boom_1000_index": 36.0,
    "crash_1000_index": 18.0,
    "boom_900_index": 36.0,
    "crash_900_index": 18.0,
    "boom_500_index": 36.0,
    "crash_500_index": 18.0,
}


def resolve(bars: np.ndarray, tr: np.ndarray, at: int, side: int, reward: float, horizon: int):
    """`(outcome, bars_held, overshoot)`; outcome 1 target, -1 stop, 0 unresolved.

    Both barriers in one bar counts as a stop, as everywhere in this repository, which
    biases every hit rate slightly down and is shared across all rows.

    ## `overshoot` is the assumption this whole repository has been making for free

    Every barrier study here - patterns, gaps, premium/discount, displacement, this one -
    assumes a stop is **filled at the stop price**. That is a modelling choice and on most
    instruments it is a mild one. On Boom and Crash it is not: these series are built from
    instantaneous spikes, and a spike does not walk up to a short's stop and stop there. It
    jumps through it, and the order fills wherever the book is on the other side.

    The reason this matters is arithmetic rather than philosophical. Boom 1000 **rose 64.9%
    over the 7.43 years** of these bars, yet shorts win 54.1% of one-to-one barrier bets
    over the same bars, and at roughly six trades a day a net of +0.041 R would compound to
    about +32% a year of notional. Those three facts cannot all be innocent. The
    reconciliation is that the losing trades lose far more than the 1 R the model charges
    them, and the missing money is exactly the spike.

    So `overshoot` records **how far past the stop the bar actually reached**, in units of
    the stop, on the bar the stop was hit.

    ## It is an upper bound, and the truth is bracketed rather than known

    An hourly bar's extreme is the worst price printed in that hour, and a stop fills at the
    first price after it triggers - somewhere between the stop and that extreme. So the
    overshoot charged here is the **worst case, not the expected case**, and reading it as
    the actual cost overstates it. Settling it needs tick data, which these files are not.

    The other end of the bracket comes from the price series and is the more interesting
    half. If slippage were near zero, shorting Boom at six trades a day would return about
    +32% a year of notional - and Boom went *up* 64.9% over the same bars. For the strategy
    not to contradict the path it was measured on, effective slippage has to be **at least**
    enough to cancel the +0.041 R net, which is around 0.04 R, or half the gross edge.

    So the honest statement is `0.04 R <= slippage <= 0.24 R` against a gross edge of
    0.081 R. At the bottom of that range half the edge survives; at the top it is gone
    three times over. **Nothing in this data can narrow it further**, and the result should
    be treated as undemonstrated rather than either confirmed or refuted.
    """
    close, high, low = bars[:, 4], bars[:, 2], bars[:, 3]
    here = close[at]
    if here <= 0:
        return 0, 0, 0.0
    unit = tr[at] * here
    if unit <= 0:
        return 0, 0, 0.0
    if side > 0:
        target, stop = here + reward * unit, here - RISK * unit
    else:
        target, stop = here - reward * unit, here + RISK * unit
    for step in range(1, horizon + 1):
        i = at + step
        if i >= len(close):
            return 0, step, 0.0
        if side > 0:
            hit_t, hit_s = high[i] >= target, low[i] <= stop
            past = (stop - low[i]) / unit
        else:
            hit_t, hit_s = low[i] <= target, high[i] >= stop
            past = (high[i] - stop) / unit
        if hit_t and hit_s:
            return -1, step, max(past, 0.0)
        if hit_t:
            return 1, step, 0.0
        if hit_s:
            return -1, step, max(past, 0.0)
    return 0, horizon, 0.0


def spread_for(symbol: str) -> float:
    for key, value in SPREAD_R.items():
        if key in symbol:
            return value
    return SPREAD_R["default"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "symbols",
        nargs="*",
        default=[
            "boom_1000_index",
            "crash_1000_index",
            "boom_500_index",
            "xauusd",
            "eurusd",
            "volatility_75_index",
        ],
    )
    ap.add_argument("--where", default=os.environ.get("WHERE", ".secrets/broker-deep"))
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--horizon", type=int, default=HORIZON)
    ap.add_argument("--every", type=int, default=4)
    args = ap.parse_args()

    for symbol in args.symbols:
        found = sorted(Path(args.where).expanduser().glob(f"{symbol}_{args.interval}_*.csv.gz"))
        if not found:
            print(f"{symbol:<22} no {args.interval} file")
            continue
        bars, _repaired = candles.read(found[0])
        if len(bars) < args.horizon + 500:
            continue
        tr = candles.true_range(bars)
        # FX and metals use `swap_mode 1` (points) and cannot be converted the same way,
        # so their carry is shown as zero and clearly flagged. They are still worth
        # running, because the **slippage** column is the reason this harness exists and
        # the question of how far the fill-at-stop assumption is broken is not specific
        # to the synthetics - it applies to every barrier study in this repository.
        annual = ANNUAL_SWAP.get(symbol, 0.0)
        note = "" if symbol in ANNUAL_SWAP else "   (carry not converted - points mode)"

        # One true range as a share of notional, which converts a percentage-of-notional
        # financing charge into units of the stop. This is the bridge between the two.
        tr_frac = float(np.median(tr[np.isfinite(tr) & (tr > 0)]))
        carry_per_day = annual / 365.0 / 100.0
        carry_r_day = carry_per_day / tr_frac if tr_frac > 0 else float("inf")
        cost_spread = spread_for(symbol)

        # The favourable direction from `jump_odds.py`: Boom pays shorts, Crash longs.
        side = -1 if "boom" in symbol else 1
        way = "short" if side < 0 else "long"

        print(
            f"\n{symbol}  -  {way}, 1 TR = {tr_frac * 100:.3f}% of notional, "
            f"{annual:.0f}%/yr = {carry_r_day:.3f} R/day{note}"
        )
        print(
            f"  {'R:R':>5}{'fair':>7}{'hit':>7}{'gross':>8}{'hrs':>6}"
            f"{'carry':>7}{'sprd':>6}{'slip':>7}{'net R':>8}{'net+slip':>10}"
        )
        for reward in REWARDS:
            wins = held = total = 0
            overshoots: list[float] = []
            for at in range(0, len(bars) - args.horizon, args.every):
                got, bars_held, past = resolve(bars, tr, at, side, reward, args.horizon)
                if got == 0:
                    continue
                total += 1
                wins += got > 0
                held += bars_held
                if got < 0:
                    overshoots.append(past)
            if total < 200:
                continue
            p = wins / total
            fair = RISK / (RISK + reward)
            gross = p * (RISK + reward) - RISK
            hours = held / total * HOURS_PER_BAR
            carry = carry_r_day * hours / 24.0
            # Slippage is charged only on the losers, weighted by how often they happen.
            slip = (1.0 - p) * float(np.mean(overshoots)) if overshoots else 0.0
            net = gross - carry - cost_spread
            flag = "  <-" if net - slip > 0 else ""
            print(
                f"  {reward / RISK:>5.2f}{fair:>7.1%}{p:>7.1%}{gross:>+8.3f}{hours:>6.1f}"
                f"{carry:>7.3f}{cost_spread:>6.3f}{slip:>7.3f}{net:>+8.3f}"
                f"{net - slip:>+10.3f}{flag}"
            )

    print(
        "\n  `break-even hrs` is how long a trade could be held before financing eats\n"
        "  the gross edge net of spread. Compare it with `mean hrs`: if the trades last\n"
        "  longer than that, the result is negative however good the hit rate looks.\n"
        "\n  Unresolved trades are excluded from the hit rate but they are the ones held\n"
        "  longest, so the carry here is understated and a marginal row is worse than\n"
        "  it prints."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
