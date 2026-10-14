"""The gold-to-commodity-currency leg, costed - the one survivor of the screen.

`direction-rules.md` left exactly one reading alive out of 21: after gold moves
and a commodity currency has not, the currency follows. Four positive readings
at `z` 2.2 to 2.8 across two laggards and two horizons, hit rates 0.57 to 0.60,
Deriv placebo clean, and the two laggards carry opposite raw signs yet both come
out positive once each sign is fitted - one effect seen twice.

It was reported as **not established**, for stated reasons: the two laggards
share a leader and overlapping events, and 21 tests puts a single `z` of 2.81
near 0.1 family-wise. It also had no cost measurement. Unlike the exotics -
where a round trip runs 0.40 to 0.97 bar-ranges and closed a real effect - gold
and AUDUSD spreads are small, so this is the one leg where costing is worth the
run rather than a formality.

## What is costed, and in what units

The screen measured the forward move in units of the **laggard's own 4-bar
return standard deviation**, so the cost has to arrive in the same units or the
comparison is meaningless. It is built from the actual `spread` at entry and at
exit rather than a median, because an event is selected on a volatility
condition and spreads widen exactly then - using a median spread here would
flatter the result in a way that is specific to this kind of event.

`spread` is in **points, not price** - an error that once read a 476% round trip
on EURUSD here - so the point size is inferred per feed from the series' own
tick grid rather than from an assumed digit count.

## The threshold sweep, which matters more than the cost

`MOVE` of 2.0 sigma and `STILL` of 0.5 sigma were picked out of the air when the
screen was written. **An effect that exists only at the pair of thresholds that
found it is a fitted effect**, and sweeping them is the cheaper half of this
run. A real lead-lag should strengthen smoothly as the leader's move gets
larger and the laggard's stillness gets stricter, and should not appear in one
cell and vanish either side of it.

Everything is reported per pair, never pooled across the two, because a pooled
median has already agreed here with a claim that every subgroup refuted.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from screen import load  # noqa: E402
from swap_squeeze import tick_of  # noqa: E402

WINDOW = int(os.environ.get("WINDOW", "4"))
HORIZON = tuple(int(k) for k in os.environ.get("HORIZON", "8,24,48").split(","))
MOVES = tuple(float(k) for k in os.environ.get("MOVES", "1.0,1.5,2.0,2.5,3.0").split(","))
STILLS = tuple(float(k) for k in os.environ.get("STILLS", "0.25,0.5,0.75,1.0").split(","))

PAIRS = (
    ("gold -> AUDUSD", "XAUUSD", "AUDUSD"),
    ("gold -> USDCAD", "XAUUSD", "USDCAD"),
    ("placebo gold -> EURGBP", "XAUUSD", "EURGBP"),
)


def frames(lead: str, lag: str):
    """Shared timestamps first, then difference - never the other way round."""
    one, two = load(lead, "1h"), load(lag, "1h")
    if one is None or two is None:
        return None
    shared = np.intersect1d(one["time"], two["time"])
    if len(shared) < 4000:
        return None
    pick_one, pick_two = np.isin(one["time"], shared), np.isin(two["time"], shared)
    close = two["close"][pick_two]
    tick = tick_of(close)
    if tick <= 0:
        return None
    # Round-trip cost in log-price terms, per bar, from the spread as quoted.
    cost = 2.0 * two["spread"][pick_two] * tick / close
    return (
        np.diff(np.log(one["close"][pick_one])),
        np.diff(np.log(close)),
        cost[1:],
    )


def events(lead, lag, move: float, still: float, horizon: int, sign: int):
    """`(gross, cost)` per accepted event, in the laggard's own sigma units."""
    rolled_lead = np.convolve(lead, np.ones(WINDOW), mode="valid")
    rolled_lag = np.convolve(lag, np.ones(WINDOW), mode="valid")
    unit_lead = float(np.std(rolled_lead)) or 1.0
    unit_lag = float(np.std(rolled_lag)) or 1.0
    gross, paid = [], []
    last = -(10**9)
    for i in range(len(rolled_lead)):
        if i - last < horizon or i + WINDOW + horizon >= len(lag):
            continue
        moved = rolled_lead[i] / unit_lead
        if abs(moved) < move or abs(rolled_lag[i]) / unit_lag > still:
            continue
        last = i
        start = i + WINDOW
        ahead = float(np.sum(lag[start : start + horizon]))
        gross.append(sign * np.sign(moved) * ahead / unit_lag)
        # Entry here, exit at the far end - both at the spread actually quoted.
        paid.append(0.5 * (cost_at(i + WINDOW) + cost_at(start + horizon)) / unit_lag)
    return np.asarray(gross), np.asarray(paid)


_COST: np.ndarray | None = None


def cost_at(i: int) -> float:
    assert _COST is not None
    return float(_COST[min(i, len(_COST) - 1)])


def zed(got: np.ndarray) -> float:
    """`z` against a sign-flip null, in closed form rather than by simulation.

    Flipping each event's sign at random gives a mean of zero and a variance of
    `mean(x^2) / n` exactly, so the standard error needs no draws. That is both
    exact and instant, which is what makes the 60-cell threshold grid cheap
    enough to be worth printing.
    """
    if len(got) < 20:
        return float("nan")
    spread = float(np.sqrt(np.mean(got**2) / len(got)))
    return float(np.mean(got)) / spread if spread else float("nan")


def main() -> None:
    global _COST
    print(
        "Gross and cost both in units of the laggard's 4-bar return sd, so they\n"
        "are comparable. Cost is the spread actually quoted at entry and exit,\n"
        "not a median, because these events are selected on a volatility\n"
        "condition and spreads widen exactly then.\n"
    )
    for label, lead_name, lag_name in PAIRS:
        got = frames(lead_name, lag_name)
        if got is None:
            print(f"{label}: not enough shared history\n")
            continue
        lead, lag, cost = got
        half = len(lead) // 2
        denom = float(np.dot(lead[:half], lead[:half]))
        beta = float(np.dot(lead[:half], lag[:half])) / denom if denom else 0.0
        sign = 1 if beta > 0 else -1
        _COST = cost[half:]
        lead_out, lag_out = lead[half:], lag[half:]
        unit = float(np.std(np.convolve(lag_out, np.ones(WINDOW), mode="valid"))) or 1.0

        print(f"{label}   beta {beta:+.3f}  bet sign {sign:+d}")
        print(
            f"  median round trip: {float(np.median(_COST)) / unit:.4f} sd"
            f"  ({1e4 * float(np.median(_COST)):.2f} bp of price)"
        )
        print(
            f"  {'h':<4}{'n':>5}{'gross':>8}{'cost':>8}{'net':>8}{'net z':>8}{'hit':>7}{'median':>9}"
        )
        for horizon in HORIZON:
            gross, paid = events(lead_out, lag_out, 2.0, 0.5, horizon, sign)
            if len(gross) < 25:
                print(f"  {horizon:<4}{len(gross):>5}   too few")
                continue
            net = gross - paid
            print(
                f"  {horizon:<4}{len(net):>5}{float(np.mean(gross)):>8.3f}"
                f"{float(np.mean(paid)):>8.3f}{float(np.mean(net)):>8.3f}"
                f"{zed(net):>8.2f}{float(np.mean(net > 0)):>7.3f}"
                f"{float(np.median(net)):>9.3f}"
            )
        # Does it survive its own thresholds being moved? The grid has to show
        # the **mean**, not `z`: `n` falls fast as `move` rises and `z` is about
        # the effect times the root of `n`, so a `z` peak at the threshold that
        # was originally picked may be nothing but power. The mean is the thing
        # that should rise monotonically if a bigger leader move really implies
        # a bigger catch-up.
        for label_grid, want_mean in (("net mean", True), ("n", False)):
            print(f"  {label_grid} over the threshold grid at h=24 (move down, still across):")
            print("       " + "".join(f"{s:>8.2f}" for s in STILLS))
            for move in MOVES:
                cells = []
                for still in STILLS:
                    gross, paid = events(lead_out, lag_out, move, still, 24, sign)
                    if len(gross) < 25:
                        cells.append("     .  ")
                        continue
                    got = gross - paid
                    cells.append(f"{float(np.mean(got)):>8.3f}" if want_mean else f"{len(got):>8d}")
                print(f"  {move:>4.1f} " + "".join(cells))

        # Is the stillness condition doing anything? The idea's whole premise is
        # that the laggard has **not** moved yet, so it is "forced to catch up".
        # If dropping that condition changes nothing, the divergence framing is
        # decoration and what is left is plain cross-asset momentum.
        loose, loose_paid = events(lead_out, lag_out, 2.0, 1e9, 24, sign)
        if len(loose) >= 25:
            net_loose = loose - loose_paid
            print(
                f"  with NO stillness condition: {len(net_loose)} events,"
                f" net {float(np.mean(net_loose)):+.3f}, z {zed(net_loose):.2f}"
            )
        # And in both halves of the holdout, which the sign never saw.
        gross, paid = events(lead_out, lag_out, 2.0, 0.5, 24, sign)
        if len(gross) >= 50:
            net = gross - paid
            cut = len(net) // 2
            print(
                f"  split halves of the holdout at h=24:"
                f" first {float(np.mean(net[:cut])):+.3f},"
                f" second {float(np.mean(net[cut:])):+.3f}"
            )
            # Thirds too, because two halves cannot tell a decay from a dip.
            step = len(net) // 3
            parts = [net[:step], net[step : 2 * step], net[2 * step :]]
            print(
                "  thirds: "
                + ", ".join(f"{float(np.mean(part)):+.3f} (n={len(part)})" for part in parts)
            )
        print()
    print(
        "  For this to be worth anything the net z has to clear the 21 tests the\n"
        "  screen already spent - about 3.0 for a family-wise 0.05 - the placebo\n"
        "  pair has to stay at zero, the threshold grid has to be smoothly\n"
        "  positive rather than one hot cell, and both halves have to agree."
    )


if __name__ == "__main__":
    main()
