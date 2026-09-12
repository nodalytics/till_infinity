"""Walking a trade forward over bars, once, where CI can see it.

## Why this is library code and not a harness

On 2026-09-11 a replay harness reported that suspending the stop for ten bars
was worth **+1.335R against the shipping policy's +0.344R**, better on 63.5% of
the same trades, holding in both halves of a split sample, passing a
shuffled-label control and a within-interval Simpson check.

It was a look-ahead. The trail kept tightening through the window while exits
were forbidden, so the exit at bar ten booked a price the market had already
passed through and left. Corrected, the policy scores **+0.014R**.

**Every statistical guard passed, because none of them can see a replay that is
cheating.** A look-ahead produces a clean, stable, reproducible result - which
is precisely what those guards test for.

It survived in the code because `pyproject.toml` excludes `research` from ruff
and pytest's `testpaths` is `tests` alone, so the code that produces this
project's conclusions was the only code in the repository with no lint gate and
no test gate. That rationale is right for about a hundred of the 103 harnesses -
they are written to be read beside their results and thrown away when the
question is answered. It is wrong for the forward walk, which is the function
that decides what ships: `exits.py` scored ride's exit at +0.655R against
+0.099R over 30,875 calls, and that is why `SweepAware` carries its current exit
in production today.

So the walk lives here, linted and tested, and the harnesses import it.

## The fill rules, which are the whole content

1. **Exits are tested against the levels resting when the bar opened**, and only
   then does that bar's extreme move them for the next one. The order of prices
   inside a bar is not knowable from OHLC.
2. **A bar that opens through a level fills at the open.** Filling at the level
   pays the trade a price the market never offered.
3. **A stop and a target both touched in one bar resolve as the stop** - which
   is a convention, not a rule, and `ambiguous="expected"` is the alternative.
   Measured on 2026-09-12 against a five-state forward-backward reconstruction
   over 18 synthetic cells, "always stop" is **0.47 to 0.68 accurate** and on
   btc **0.415 - worse than a coin.** Because it always says the same thing its
   error is a one-sided bias rather than noise, worth **-9 to -44 points of risk
   per resolved trade**, and `research/calibrating.md` puts the largest claim on
   `research/spending.md`'s strategy table at 34 points. **The bias is the size
   of the findings and it points the same way every time.**

   It costs a *fresh* entry nothing: at `target_mult` 6.0, this module's own
   default, **0.00% of bars are ambiguous** on every feed tested. It binds once
   the stop has trailed up near price, which is where `manage.advance` puts
   every winner - 10% to 43% of resolving bars.
4. **The spread is charged on both legs**, so a round trip pays one spread.
5. **A stop that cannot fire does not move.** Rule 1, restated for the case that
   broke it.

## `cost` and `hold` are required

Both are modelling choices, and a default is how a modelling choice stops being
a decision. Four of 103 harnesses charged a spread, and charging zero moved a
replayed population from -0.015R to +0.348R. One harness held trades for 1,440
bars while the live desk holds for 30 - a 48-fold error that was invisible
because it sat in a module constant.

Loading bars is **not** here. Sources differ per question - `multi.db` keys on
`(feed, venue, ts)` in seconds, `research.db` on `(feed, interval, ts)` in
milliseconds - and a loader covering both would grow a schema registry. What
must not differ is what happens to the bars once loaded.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

#: `(ts, open, high, low, close)`.
#:
#: **The open is load-bearing.** Without it rule 2 cannot be applied at all, and
#: when it was added late to one harness the positional read `rows[i][3]`
#: silently turned from close into low - pricing every hold-expiry exit at the
#: worst tick of the last bar.
Bar = tuple[float, float, float, float, float]

#: What a replayed entry needs. A `Mapping` rather than a new dataclass: this is
#: the shape the harnesses already build, and making them construct a type would
#: be churn in the scratch layer for no gain.
Trade = Mapping[str, Any]


def _number(source: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    got = source.get(key)
    return float(got) if isinstance(got, int | float) else default


#: The Broadie-Glasserman-Kou continuity correction, in units of the bar's own
#: range. Duplicated from `trading/barriers.SHIFT` rather than imported: `shared`
#: sits **under** `trading` and a module here reaching up into it would invert
#: the layering for one constant. The tests assert the two agree, so a change to
#: either fails rather than drifts.
SHIFT = 0.5826


def _first_target(opened: float, stop: float, target: float, high: float, low: float) -> float:
    """P(the target was reached first), given a bar that touched both.

    The first-passage form `trading/barriers.probability` derives, with the
    distances measured **from the bar's open** and expressed in units of the
    bar's own range - which is the only volatility scale a single bar carries.

    Nearer barrier first, in proportion, with the overshoot pushing both walls
    out equally so an open exactly between them is a coin. That last property is
    what makes this a refusal to guess rather than a different guess: it cannot
    manufacture a direction the bar does not contain.
    """
    span = max(high - low, 0.0)
    if span <= 0:
        return 0.5
    to_stop = abs(opened - stop) / span
    to_target = abs(opened - target) / span
    total = to_stop + to_target + 2.0 * SHIFT
    if total <= 0:
        return 0.5
    return (to_stop + SHIFT) / total


def _risk_price(trade: Trade, policy: Mapping[str, Any], unit: float) -> float | None:
    """The stop distance in price, or None when the policy cannot place one."""
    if policy.get("beyond_pool"):
        # Past the resting liquidity the strategy normally refuses to stand in
        # front of, plus a tenth of a unit so a touch is not a stop.
        beyond = _number(trade.get("context") or {}, "liquidity_beyond_vol")
        return (beyond + 0.1) * unit if beyond > 0 else None
    risk = trade["risk_vol"] * unit * policy.get("stop_mult", 1.0)
    return risk if risk > 0 else None


def _trail_step(trade: Trade, policy: Mapping[str, Any], unit: float, risk: float) -> float:
    """How far behind the extreme the stop sits, in price.

    `wick_trail` reproduces what `manage.stop_for` actually applies rather than
    what the strategy asks for: the trail is widened to clear the level's own
    wicks, and **that rule has no ceiling**. Over 47,233 level calls the
    computed trail is the 0.5v floor only 59% of the time, exceeds 1v on 30.2%,
    exceeds 3v on 9.4%, and its maximum is 2,239v.
    """
    if policy.get("trail_risk") is not None:
        return float(policy["trail_risk"]) * risk

    trail_vol = policy.get("trail_vol", 0.5)
    if policy.get("wick_trail"):
        context = trade.get("context") or {}
        side = "below" if trade["up"] else "above"
        if _number(context, "wick_n") >= 2:
            room = _number(context, f"wick_{side}_vol") + _number(context, f"wick_{side}_sd") * 0.5
            trail_vol = max(trail_vol, room)
        if policy.get("cap_vol"):
            trail_vol = min(trail_vol, float(policy["cap_vol"]))
        if policy.get("cap_risk"):
            trail_vol = min(trail_vol, trade["risk_vol"] * float(policy["cap_risk"]))
    return trail_vol * unit


def walk(
    bars: Sequence[Bar],
    start: int,
    trade: Trade,
    *,
    cost: float,
    hold: int,
    policy: Mapping[str, Any],
    ambiguous: str = "stop",
) -> tuple[float, str] | None:
    """R and how the trade ended - "stop", "target" or "hold" - or None.

    None means the trade could not be replayed at all: no volatility unit, no
    modelled push, no stop the policy could place, or no bars left after
    `start`. **Not zero** - scoring an absence as a flat trade is how a replay
    gains a population it never made.

    The exit kind matters as much as the R. A policy that lifts mean R while
    being stopped just as often has bought something other than what was asked.

    `ambiguous` decides a bar that touched both barriers - see rule 3.

    * `"stop"` keeps the historical convention and its one-sided bias, so an
      existing result is reproducible rather than silently restated.
    * `"expected"` returns the **probability-weighted R** and the exit kind
      `"both"`. Not a better guess at which happened - a refusal to guess. Over
      many trades the weighted value is unbiased where a guess is not, and the
      bias is the whole problem: it is worth more than the findings it feeds.

    The weight is the first-passage probability from the bar's open, with the
    discrete-monitoring shift that `trading/barriers.py` derives. Implemented
    here rather than imported because `shared` sits under `trading` and must not
    reach up into it; the two are checked against each other in the tests.
    """
    up, unit = trade["up"], trade["unit"]
    if unit <= 0 or trade["push_vol"] <= 0:
        return None
    risk = _risk_price(trade, policy, unit)
    if risk is None:
        return None

    half = cost / 2 if up else -cost / 2
    entry = trade["level"] + half
    stop = entry - risk if up else entry + risk
    target = entry + trade["push_vol"] * policy.get("target_mult", 6.0) * unit * (1 if up else -1)
    protect = policy.get("protect_r", 1.0)
    trail_after = policy.get("trail_after_r", 0.0)
    grace = policy.get("grace", 0)
    close_only = policy.get("close_only", False)
    best = entry

    def out_of(price: float) -> tuple[float, str]:
        left = price - half
        return ((left - entry) if up else (entry - left)) / risk, ""

    last_bar = min(start + hold, len(bars))
    for i in range(start, last_bar):
        _ts, opened, high, low, close = bars[i]
        if None in (opened, high, low, close):
            continue
        resting = i - start < grace

        # Rule 1: the levels that were resting when this bar opened, before this
        # bar's own extreme is allowed to move them.
        if not resting:
            low_seen, high_seen = (close, close) if close_only else (low, high)
            hit_stop = (low_seen <= stop) if up else (high_seen >= stop)
            hit_target = (high >= target) if up else (low <= target)
            if hit_stop and hit_target and ambiguous == "expected" and not close_only:
                # Rule 3, declined. Both barriers were touched and the order is
                # not knowable from OHLC, so this returns the expected R rather
                # than asserting the worse one.
                reached = _first_target(opened, stop, target, high, low)
                on_stop = out_of(opened if (opened <= stop if up else opened >= stop) else stop)[0]
                on_target = out_of(
                    opened if (opened >= target if up else opened <= target) else target
                )[0]
                return reached * on_target + (1.0 - reached) * on_stop, "both"
            if hit_stop:
                # Rule 2. `close_only` exits on the close by construction.
                through = (opened <= stop) if up else (opened >= stop)
                price = close if close_only else (opened if through else stop)
                return out_of(price)[0], "stop"
            # Rule 3: the stop is checked first, so a bar touching both is a stop.
            if hit_target:
                through = (opened >= target) if up else (opened <= target)
                return out_of(opened if through else target)[0], "target"

        best = max(best, high) if up else min(best, low)
        gained = ((best - entry) if up else (entry - best)) / risk

        # Rule 5: a stop that cannot fire does not move.
        if resting:
            continue
        if protect and gained >= protect:
            stop = max(stop, entry) if up else min(stop, entry)
        if gained >= trail_after:
            step = _trail_step(trade, policy, unit, risk)
            if step:
                pull = best - step if up else best + step
                stop = max(stop, pull) if up else min(stop, pull)

    if start >= last_bar:
        return None
    return out_of(bars[last_bar - 1][4])[0], "hold"
