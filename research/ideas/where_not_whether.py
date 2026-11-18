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
    shuffled,
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
    #: For a race that stopped: did price later reach the original target, how
    #: far did it go the intended way afterwards, and what did holding instead
    #: of stopping have been worth - all in R, where R is the stop distance.
    #:
    #: **The stop's counterfactual, which production already watches and has
    #: never had a null.** `strategies/counterfactual.py` keeps a `Shadow` of
    #: every stopped trade for exactly this. The number it produces is not
    #: evidence the stop was wrong: on a driftless walk a stopped trade
    #: reaches its target later most of the time, because price wanders back.
    #: What makes it readable here is that the side is a coin.
    recovered: bool = False
    best_after: float = 0.0
    held_r: float = 0.0
    #: What the race actually paid, in R, where R is the stop distance.
    #:
    #: **Not -1.00 by assumption, which is how a close-based stop reads as an
    #: edge.** A stop that triggers on the close is a *wider* stop - price may
    #: wick through it untouched - while the target still fills on the
    #: extreme, so the race is no longer the geometry its reward-to-risk
    #: claims. Measured on the hit rate alone it goes from 0.500 to 0.586,
    #: which is arithmetic rather than skill: the exit price is already beyond
    #: the stop, so each loss is bigger than 1R by exactly enough to pay for
    #: it. Carrying the realised figure is what makes the two comparable.
    paid: float = 0.0
    #: `wick` or `body`, and how violent the bar was, and how long it took.
    killed: str = ""
    kill_bar: float = 0.0
    took: int = 0
    #: The same two questions asked of the **target**. A target that fills more
    #: often at the same distance is the version of this claim that pays, and
    #: it is a different question from the stop: `fade-to-value` was killed by
    #: its stop while its targets paid +28.16, so the two sides of a race do
    #: not have to answer alike.
    target_level: bool = False
    target_placebo: bool = False


def barriers(
    bars: Candles,
    levels: list[float],
    placebos: list[float],
    *,
    stop_atr: float,
    reward: float,
    seed: int,
    on_close: bool = False,
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
        stopped_at = -1
        paid = 0.0
        for j in range(i + 1, i + 1 + patience):
            high, low = float(bars.high[j]), float(bars.low[j])
            # **The stop on the extreme, or on the close.** Half of all
            # stop-outs are taken by a wick whose bar closes back on the right
            # side, and those trades average -0.59R if held against the -1.00R
            # the stop pays - so whether the stop reads the extreme or the
            # close is worth measuring rather than assuming.
            if on_close:
                shut = float(bars.close[j])
                hit_stop = shut <= stop if side > 0 else shut >= stop
            else:
                hit_stop = low <= stop if side > 0 else high >= stop
            hit_target = high >= target if side > 0 else low <= target
            if hit_stop or hit_target:
                # Both inside one bar is a loss: the order of the two touches
                # is unknowable from a bar and assuming the good one is how a
                # backtest manufactures an edge.
                resolved, won = True, (hit_target and not hit_stop)
                stopped_at = j
                if won:
                    paid = stop_atr * reward * unit / (stop_atr * unit)
                else:
                    # Where the trade actually left, which for a close-based
                    # stop is the close and not the stop price.
                    out_at = float(bars.close[j]) if on_close else stop
                    paid = ((out_at - entry) * side) / (stop_atr * unit)
                break

        recovered, best_after, held_r = False, 0.0, 0.0
        killed, bar_atr, took = "", 0.0, 0
        if resolved and not won and stopped_at > 0:
            # **What the stop cost, measured against holding.** The window is
            # the rest of the original patience and no more: extending it
            # until the target arrives would measure how long a walk takes to
            # wander, which is unbounded and says nothing.
            risk = stop_atr * unit
            best = 0.0
            for j in range(stopped_at, i + 1 + patience):
                favourable = (float(bars.high[j]) - entry) * side
                against = (float(bars.low[j]) - entry) * side
                if side < 0:
                    favourable, against = -against, -favourable
                best = max(best, favourable / risk)
                reached = (
                    float(bars.high[j]) >= target if side > 0 else float(bars.low[j]) <= target
                )
                if reached:
                    recovered = True
            end = min(i + patience, len(bars) - 1)
            held_r = ((float(bars.close[end]) - entry) * side) / risk
            best_after = best
            # **What took the stop: a wick or a body.** A bar whose extreme
            # reached the stop and whose close came back on the right side of
            # it took the trade with a wick - the shape a wider or a
            # close-based stop would have survived. One that closed beyond it
            # is price having actually gone there, and no stop placement
            # rescues that.
            closed = float(bars.close[stopped_at])
            beyond = (closed - stop) * side < 0
            killed = "body" if beyond else "wick"
            bar_atr = (float(bars.high[stopped_at]) - float(bars.low[stopped_at])) / unit
            took = stopped_at - i
        out.append(
            Race(
                feed=bars.symbol,
                side=side,
                won=won,
                resolved=resolved,
                paid=paid,
                recovered=recovered,
                best_after=best_after,
                held_r=held_r,
                killed=killed,
                kill_bar=bar_atr,
                took=took,
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
        paid = float(np.mean([r.paid for r in group]))
        # The standard error of a share, which is the only honest band here:
        # the races are spaced `EVERY` bars apart to keep them near-independent.
        err = (hit * (1 - hit) / len(group)) ** 0.5
        print(
            f"    {name:<24} n {len(group):>6,}  {hit:.3f} +/- {err:.3f}"
            f"   vs walk {hit - fair:+.3f}   mean {paid:+.4f}R"
        )


def autopsy(races: list[Race], reward: float, label: str) -> None:
    """What took the stops, and what the stopped trades did afterwards.

    **The recovery rate is not evidence the stop was wrong.** On a driftless
    walk a stopped trade reaches its target later most of the time, because
    price wanders back - and these entries are coin-sided, so there is no
    direction in them at all. The number is here to be *sized*, not believed:
    it says what holding would have cost or saved against a known-zero signal,
    which is the only way to read a counterfactual that always looks good.
    """
    dead = [r for r in races if r.resolved and not r.won]
    if len(dead) < 200:
        print(f"  {label}: {len(dead)} stop-outs - too few")
        return
    wick = [r for r in dead if r.killed == "wick"]
    body = [r for r in dead if r.killed == "body"]
    print(f"  {label}: {len(dead):,} stop-outs, each paying -1.00R by construction")
    for name, group in (("taken by a wick", wick), ("taken by a body", body)):
        if len(group) < 50:
            continue
        share = len(group) / len(dead)
        back = sum(r.recovered for r in group) / len(group)
        best = float(np.mean([r.best_after for r in group]))
        held = float(np.mean([r.held_r for r in group]))
        took = float(np.median([r.took for r in group]))
        size = float(np.mean([r.kill_bar for r in group]))
        print(
            f"    {name:<16} {share:5.1%}  later reached target {back:5.1%}"
            f"   best after {best:+5.2f}R   holding instead {held:+5.2f}R"
            f"   killing bar {size:4.2f} ATR   after {took:3.0f} bars"
        )
    held_all = float(np.mean([r.held_r for r in dead]))
    print(
        f"    {'all stop-outs':<16} {1.0:5.1%}  later reached target "
        f"{sum(r.recovered for r in dead) / len(dead):5.1%}"
        f"   best after {np.mean([r.best_after for r in dead]):+5.2f}R"
        f"   holding instead {held_all:+5.2f}R"
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
    parser.add_argument("--buffers", default="", help="comma-separated entry buffers, in ATR")
    parser.add_argument("--pads", default="0.0", help="comma-separated stop pads, in ATR")
    parser.add_argument("--ambiguous", default="loss", choices=("loss", "coin"))
    parser.add_argument("--shuffle", action="store_true", help="day-block shuffle the bars first")
    parser.add_argument(
        "--on-close",
        action="store_true",
        help="trigger the stop on a close beyond it rather than on the extreme",
    )
    args = parser.parse_args()

    loaded = {}
    for symbol in (s for s in args.symbols.split(",") if s):
        base = window(load(Path(args.catalogue), symbol), args.years)
        if args.shuffle:
            # **The twin that prices the mechanical part of reversion.**
            # `trailing-zscores-fake-reversion` records a shuffled twin taking
            # +0.111 of a +0.137 effect, so an entry-offset ladder that reads
            # antisymmetric is not evidence until this arm is subtracted.
            base = shuffled(base, seed=11)
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
                    on_close=args.on_close,
                )
                pooled += races
                report(races, reward, symbol)
            report(pooled, reward, "POOLED")
            print("\n  --- what took the stops, and what happened next")
            autopsy(pooled, reward, "POOLED")
            if args.buffers:
                print("\n  --- a limit entry `buffer` better, stop shifted to match")
                for buffer_atr in (float(x) for x in args.buffers.split(",") if x):
                    pads = [
                        buffer_atr if x.strip() == "match" else float(x)
                        for x in args.pads.split(",")
                        if x.strip()
                    ]
                    for stop_pad in pads:
                        sig = fil = 0
                        weighted = 0.0
                        ratio = 0.0
                        for seed, (symbol, (fast, _real, _fake)) in enumerate(loaded.items()):
                            a, b, _per_fill, per_signal, ratio = buffered(
                                fast,
                                stop_atr=stop_atr,
                                reward=reward,
                                buffer_atr=buffer_atr,
                                stop_pad=stop_pad,
                                ambiguous=args.ambiguous,
                                seed=seed,
                            )
                            sig += a
                            fil += b
                            weighted += per_signal * a
                        print(
                            f"    entry -{buffer_atr:.2f} stop +{stop_pad:.2f}"
                            f"{' (R held)' if abs(stop_pad - buffer_atr) < 1e-9 and buffer_atr else '':<9}"
                            f"   R:R {ratio:5.2f}   filled {fil / sig:5.1%}"
                            f"   per signal {weighted / sig:+.4f}R"
                        )




# --- the buffered entry ------------------------------------------------------


def buffered(
    bars: Candles,
    *,
    stop_atr: float,
    reward: float,
    buffer_atr: float,
    stop_pad: float = 0.0,
    ambiguous: str = "loss",
    seed: int,
    wait: int = 8,
    patience: int = PATIENCE,
) -> tuple[int, int, float, float, float]:
    """A limit entry `buffer` better, with the stop pushed out to match.

    **The stop and the target are prices, not distances, so shifting the entry
    changes both sides of the ratio.** The operator's correction: moving the
    entry `buffer` closer to the stop leaves `risk = d - buffer` and
    `reward = N*d + buffer`, so the reward-to-risk improves twice over - the
    denominator shrinks as the numerator grows. An earlier version of this
    moved the stop along with the entry and held R constant, which is a
    different and much weaker claim.

    What is paid for it is **fill rate**: price has to come back `buffer`
    before it goes, and when it does not the trade never happens. Whether that
    pays is the whole question, and it is why the figure that matters is per
    **signal** rather than per fill - an unfilled signal is a forgone trade,
    not a free option.

    Everything is reported in units of the **original** risk `d`, so a win is
    `N + buffer/d` and a loss is `-(1 - buffer/d)`, and the arms are
    comparable with the market-entry baseline.

    Returns `(signals, fills, mean R per fill, mean R per signal)`. The second
    is the number that matters - an unfilled signal is a forgone trade, not a
    free option, and reporting only the filled ones is how a limit-entry study
    reports the trades it chose to count.
    """
    band = atr(bars, ATR_LEN)
    rng = np.random.default_rng(seed)
    signals = fills = 0
    total = 0.0
    for i in range(ATR_LEN + 1, len(bars) - patience - wait, EVERY):
        unit = float(band[i])
        if not np.isfinite(unit) or unit <= 0:
            continue
        signals += 1
        side = 1 if rng.random() < 0.5 else -1
        want = float(bars.close[i]) - side * buffer_atr * unit

        # **A negative buffer is a stop-entry, and it is the control.** With a
        # positive buffer the order rests *better* than the signal and fills
        # only after a retracement, which is precisely the condition under
        # which short-horizon reversion would pay - so a limit arm that reads
        # positive proves nothing on its own. Flipping the sign enters *with*
        # the move instead. If reversion is what is being harvested the two
        # arms must be mirror images; if both read positive the machinery is
        # at fault.
        filled_at = -1
        for j in range(i + 1, i + 1 + wait):
            if buffer_atr >= 0:
                reached = float(bars.low[j]) <= want if side > 0 else float(bars.high[j]) >= want
            else:
                reached = float(bars.high[j]) >= want if side > 0 else float(bars.low[j]) <= want
            if reached:
                filled_at = j
                break
        if filled_at < 0:
            continue

        fills += 1
        risk = stop_atr * unit
        # **The target is the only fixed price.** The entry moves `buffer`
        # better and the stop moves `stop_pad` further away, so the risk is
        # `d - buffer + pad` and the reward is `N*d + buffer` - the operator's
        # construction, where the shift gives the asymmetry natively rather
        # than by choosing a reward-to-risk number.
        signal = float(bars.close[i])
        stop = signal - side * (risk + stop_pad * unit)
        target = signal + side * risk * reward
        risk_now = (stop_atr - buffer_atr + stop_pad) or 1e-9
        win = (reward + buffer_atr) / stop_atr
        lose = -risk_now / stop_atr
        # **From the fill bar, not the one after it.** At a 0.75 buffer the
        # risk is a quarter of an ATR, well inside a typical 15m bar, so a
        # limit can fill and be stopped within the same bar. Starting the race
        # at `filled_at + 1` skips exactly that, and skips it more often the
        # larger the buffer - which manufactures a monotone improvement out of
        # nothing. Both barriers inside one bar resolves as a loss.
        for j in range(filled_at, filled_at + 1 + patience):
            high, low = float(bars.high[j]), float(bars.low[j])
            hit_stop = low <= stop if side > 0 else high >= stop
            hit_target = high >= target if side > 0 else low <= target
            if hit_stop and hit_target:
                # **The ambiguous bar, and it is not a detail here.** Which
                # barrier was touched first inside a bar is unknowable, and
                # resolving it as a loss - the conservative choice - penalises
                # exactly the geometries whose barriers are close together. The
                # unbuffered 1:1 race has its two barriers 2 ATR apart and a
                # typical bar spans that; the buffered one has them 2.5 apart
                # and almost never does. So the rule itself can manufacture a
                # monotone preference for wider geometry. `coin` resolves it
                # at random instead, which is unbiased across geometries, and
                # the gap between the two settings is the size of the problem.
                total += win if (ambiguous == "coin" and rng.random() < 0.5) else lose
                break
            if hit_stop:
                total += lose
                break
            if hit_target:
                total += win
                break
    per_fill = total / fills if fills else float("nan")
    per_signal = total / signals if signals else float("nan")
    ratio = (reward + buffer_atr) / max(stop_atr - buffer_atr + stop_pad, 1e-9)
    return signals, fills, per_fill, per_signal, ratio


if __name__ == "__main__":
    main()
