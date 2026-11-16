"""Does a level change the barrier race when it sits at the barrier?

Every levels study in [`reactive-zones.md`](../docs/reactive-zones.md) asked
whether a level **predicts** - does trading it pay, does an excursion past it
end anywhere special, does it matter who computes the price. Six kinds, every
control matching the real arm. That family is closed.

This asks the question none of them did. A rule makes two decisions:

* **whether** to act, which is the signal - measured, and null;
* **where** to act, which is the entry, the stop and the target.

**Nominating a price is not predicting one.** A level could be worthless as a
signal and still be the right place to put a stop, and nothing measured so far
touches that. If it were true it would be worth more than a directional edge,
because it costs nothing: the same stop distance surviving more often is free,
and it is immune to direction being closed.

## The design, and the trap it avoids

The obvious comparison - "a stop at a level" against "a stop at the same
distance with no level" - is incoherent: at the same distance it is the **same
price**. So the split has to be conditional. Entries are taken at random with
the side decided by a **seeded coin**, barriers are placed at fixed ATR
distances, and each race is labelled by whether a level happens to sit within
tolerance of the stop price. The question is then whether the race differs
between those two groups.

The coin is doing real work. It means no directional claim can be smuggled in
and every arm has the same expectation on a driftless walk - **1/(1+N)**,
where `N` is the reward-to-risk - so a departure is about placement alone.

Three controls, each of which has caught a wrong answer in this repository:

* **the placebo level**, mirrored to the same distance with no pivot behind
  it, which is what separates "a level is here" from "a price at this distance
  is here" - `a-return-rate-is-geometry` records an 82% return rate matched by
  exactly that on every class;
* **per instrument**, because a pooled barrier rate once agreed with a claim
  every subgroup refuted;
* **the walk's own rate**, printed beside every cell, since a reward-to-risk
  alone moves the hit rate and that movement is not an edge.

Run as:

    uv run python research/ideas/where_not_whether.py --years 8
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reactive_zones import (  # noqa: E402
    ATR_LEN,
    CATALOGUE,
    Candles,
    adaptive_band,
    atr,
    fold,
    load,
    window,
    zones_of,
)

SYMBOLS = ("EURUSD", "GBPUSD", "GOLD", "USDJPY", "AUDUSD")

#: Bars a race is allowed, on the execution frame. Beyond this the trade is
#: abandoned unresolved - a desk would not hold a scalp for two days, and an
#: unbounded race measures the series' drift rather than the barrier.
PATIENCE = 96

#: How close a level must be to the barrier to count as sitting at it, in ATR.
#: **The tolerance is the experiment's resolution**: too tight and nothing
#: qualifies, too loose and every race is labelled "at a level" and the split
#: is empty. Swept rather than chosen.
TOUCH = 0.25

#: One entry every this many bars. Entries must not overlap more than they
#: have to: `overlapping-outcome-windows-leak` records direction AUC of 0.79
#: collapsing to 0.51 once overlapping windows were removed, and a race lasts
#: up to `PATIENCE` bars.
EVERY = 32


@dataclass(slots=True)
class Race:
    """One barrier race from one entry."""

    feed: str
    side: int
    won: bool
    resolved: bool
    at_level: bool
    at_placebo: bool
    #: The same two questions asked of the **target**. A target that fills more
    #: often at the same distance is the version of this claim that pays, and
    #: it is a different question from the stop: `fade-to-value` was killed by
    #: its stop while its targets paid +28.16, so the two sides of a race do
    #: not have to answer alike.
    target_level: bool
    target_placebo: bool


def barriers(
    bars: Candles,
    levels: list[float],
    placebos: list[float],
    *,
    stop_atr: float,
    reward: float,
    seed: int,
    patience: int = PATIENCE,
    every: int = EVERY,
    touch: float = TOUCH,
) -> list[Race]:
    """Coin-sided races, each labelled by what sits at its stop.

    The side is a seeded coin, so the expectation on a driftless walk is
    `1/(1+reward)` whatever the levels do. `won` is "the target came before the
    stop", judged on bar extremes; a bar that spans both is counted as a
    **loss**, which is the conservative reading and the one `barriers.py` in
    production already takes.
    """
    band = atr(bars, ATR_LEN)
    rng = np.random.default_rng(seed)
    ladder = np.sort(np.asarray(levels)) if levels else np.empty(0)
    shadow = np.sort(np.asarray(placebos)) if placebos else np.empty(0)

    def near(price: float, where: np.ndarray, unit: float) -> bool:
        """Is any member of `where` within `touch` ATR of `price`?"""
        if where.size == 0:
            return False
        index = int(np.searchsorted(where, price))
        for candidate in where[max(0, index - 1) : index + 1]:
            if abs(float(candidate) - price) <= touch * unit:
                return True
        return False

    out: list[Race] = []
    for i in range(ATR_LEN + 1, len(bars) - patience, every):
        unit = float(band[i])
        if not np.isfinite(unit) or unit <= 0:
            continue
        side = 1 if rng.random() < 0.5 else -1
        entry = float(bars.close[i])
        stop = entry - side * stop_atr * unit
        target = entry + side * stop_atr * reward * unit

        won = resolved = False
        for j in range(i + 1, i + 1 + patience):
            high, low = float(bars.high[j]), float(bars.low[j])
            hit_stop = low <= stop if side > 0 else high >= stop
            hit_target = high >= target if side > 0 else low <= target
            if hit_stop or hit_target:
                # Both inside one bar is a loss: the order of the two touches
                # is unknowable from a bar and assuming the good one is how a
                # backtest manufactures an edge.
                resolved, won = True, (hit_target and not hit_stop)
                break
        out.append(
            Race(
                feed=bars.symbol,
                side=side,
                won=won,
                resolved=resolved,
                at_level=near(stop, ladder, unit),
                at_placebo=near(stop, shadow, unit),
                target_level=near(target, ladder, unit),
                target_placebo=near(target, shadow, unit),
            )
        )
    return out


# --- reporting ---------------------------------------------------------------


def report(races: list[Race], reward: float, label: str) -> None:
    """Hit rate at the stop with a level there, against the stop without one.

    The walk's rate is printed beside every cell because a reward-to-risk
    alone moves the hit rate - `1/(1+N)` - and that movement is arithmetic
    rather than an edge. `fade-to-value` bought hit rate from 31% to 48% at
    almost exactly the fair price and the repository records it as the reason
    "improve the entry" was never the answer.
    """
    done = [r for r in races if r.resolved]
    if len(done) < 200:
        print(f"  {label}: {len(done)} resolved - too few")
        return
    fair = 1.0 / (1.0 + reward)
    print(f"  {label}: {len(done):,} resolved of {len(races):,}, a walk gives {fair:.3f}")
    for name, pick in (
        ("a level at the stop", lambda r: r.at_level),
        ("no level there", lambda r: not r.at_level),
        ("a PLACEBO at the stop", lambda r: r.at_placebo),
        ("no placebo there", lambda r: not r.at_placebo),
        ("a level at the TARGET", lambda r: r.target_level),
        ("no level at the target", lambda r: not r.target_level),
        ("a PLACEBO at the target", lambda r: r.target_placebo),
        ("no placebo at target", lambda r: not r.target_placebo),
    ):
        group = [r for r in done if pick(r)]
        if len(group) < 100:
            print(f"    {name:<24} n {len(group):>6,}  too few")
            continue
        hit = sum(r.won for r in group) / len(group)
        # The standard error of a share, which is the only honest band here:
        # the races are spaced `EVERY` bars apart to keep them near-independent.
        err = (hit * (1 - hit) / len(group)) ** 0.5
        print(
            f"    {name:<24} n {len(group):>6,}  {hit:.3f} +/- {err:.3f}"
            f"   vs walk {hit - fair:+.3f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", default=str(CATALOGUE))
    parser.add_argument("--symbols", default=",".join(SYMBOLS))
    parser.add_argument("--years", type=float, default=8.0)
    parser.add_argument("--frame", default="15m")
    parser.add_argument("--structure", default="4h")
    parser.add_argument("--stops", default="1.0,2.0,3.0")
    parser.add_argument("--rewards", default="1.0,2.0")
    parser.add_argument("--touch", type=float, default=TOUCH)
    args = parser.parse_args()

    loaded = {}
    for symbol in (s for s in args.symbols.split(",") if s):
        base = window(load(Path(args.catalogue), symbol), args.years)
        slow = fold(base, args.structure)
        fast = fold(base, args.frame)
        band = adaptive_band(slow, 25.0)
        # The real levels, and the placebo: mirrored about the confirming
        # close, so the same distance from price with no pivot behind it.
        real = zones_of(slow, band, 1.0)
        fake = zones_of(slow, band, 1.0, placebo=True)
        loaded[symbol] = (
            fast,
            [(z.top + z.bottom) / 2.0 for z in real],
            [(z.top + z.bottom) / 2.0 for z in fake],
        )
        print(f"{symbol}: {len(fast):,} {args.frame} bars, {len(real):,} levels")

    for stop_atr in (float(x) for x in args.stops.split(",") if x):
        for reward in (float(x) for x in args.rewards.split(",") if x):
            print(f"\n=== stop {stop_atr:.1f} ATR, target {stop_atr * reward:.1f} ATR")
            pooled: list[Race] = []
            for seed, (symbol, (fast, real, fake)) in enumerate(loaded.items()):
                races = barriers(
                    fast,
                    real,
                    fake,
                    stop_atr=stop_atr,
                    reward=reward,
                    seed=seed,
                    touch=args.touch,
                )
                pooled += races
                report(races, reward, symbol)
            report(pooled, reward, "POOLED")


if __name__ == "__main__":
    main()
