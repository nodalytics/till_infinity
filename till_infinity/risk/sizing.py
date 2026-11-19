"""How far the stop goes, and how many lots that allows.

Two conversions, and everything depends on getting them the right way round.

**Volatility units to price.** `structures` measures everything in volatility
units - a stop 1.4v away means 1.4 times the typical recent move, not 1.4
dollars - because a fixed distance encodes one market regime and stops
describing the next. The signal carries `risk_vol` and `expected_push_vol` in
those units and `vol_bps` as the unit itself, so a distance in price is
`price * vol_bps * multiple / 10_000`. That is the same arithmetic
`volatility.price_units` does, written here rather than imported because
`trading` reads signals off the bus and never touches the level engine.

**Price to money.** MT5 states risk per lot as tick value over tick size: a
stop `d` away costs `d / tick_size * tick_value` per lot, in the account
currency. Inverting that against a risk budget gives lots, and it is the only
step that has to be right to the cent - everything upstream of it is an
estimate of what price will do, and this is an arithmetic fact about what a
loss will cost.

The order of clamping matters and is the reason this is a module rather than a
line. Round to the broker's lot step **downwards**, then check the result is
still at least the minimum lot. Doing it the other way - clamping up to the
minimum first - silently converts "this trade is too small to take" into "take
it anyway at a risk nobody authorised", which on a 0.25% budget and a tight
stop is most trades on an account whose minimum lot is 0.1.

## Moved here from `strategies/` on 2026-11-01

How much a trade may lose is a question about the account, and this file sat
under `strategies/` only because that is where its first caller was. Two things
settle it. `docs/specs/2026-10-31-service-becomes-nautilus-strategies.md` says
`till_infinity/risk/` decides size pre-trade; and `scaling.py` next door is the
other half of the same arithmetic - its opening line is "`lots()` risks a
constant share of equity per trade" - so the base size and the eight
multipliers that reduce it were being maintained in two different packages.

It could move because it imports nothing but `domain` and `utils`, which is
exactly what `guard.py` could not manage. See `risk/__init__.py`.

**`stop_for` and `target_for` came with it, and they are the awkward part.**
"Where the stop and target go" is the *strategy* row in that spec, not this
one. What these two actually do is narrower: they apply a distance somebody
else chose, beyond a level or out from a fill. Choosing it is
`strategies/profile.py`'s and `strategies/config.py`'s job and stayed there.
Neither function has a caller left in `till_infinity/` - only
`research/retire/` - so splitting the file to re-home two dead functions would
have cost a module and bought nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

from till_infinity.utils import effects

from ..domain.models import Side, SymbolSpec

#: **A trade refused because the minimum lot breaches the budget.** The runtime
#: counterpart of `affordable.py`: that module is a catalogue of instruments
#: this account cannot trade, and this is the refusal actually happening. If it
#: never fires, the catalogue is describing a problem the desk does not have;
#: if it fires constantly, instruments need dropping rather than re-refusing one
#: signal at a time, for ever, which is the situation the catalogue was written
#: to make visible.
effects.declare("trading.unaffordable_refusal", enabled=True)


def price_distance(price: float, vol_bps: float, multiple: float) -> float:
    """`multiple` volatility units as a price distance at `price`."""
    return abs(price * (vol_bps * multiple) / 10_000)


def stop_for(
    level: float,
    side: Side,
    distance: float,
    zone_edge: float = 0.0,
    clearance: float = 0.0,
) -> float:
    """Where the stop goes: beyond the level's **zone**, on the side price came from.

    See `trading-sizing.md` in research/docs.
    """
    beyond = level - distance if side is Side.BUY else level + distance
    if not zone_edge:
        return beyond
    outside = zone_edge - clearance if side is Side.BUY else zone_edge + clearance
    # Whichever is further from the level, so the zone can only widen a stop.
    return min(beyond, outside) if side is Side.BUY else max(beyond, outside)


def target_for(entry: float, side: Side, distance: float) -> float:
    """Where the target goes: the expected push, measured from the fill.

    From the fill rather than the level, because the push is what the model
    expects price to do from here and the money is made from where we got in.
    """
    return entry + distance if side is Side.BUY else entry - distance


@dataclass(frozen=True, slots=True)
class Sizing:
    """The answer, or the reason there is not one."""

    volume: float = 0.0
    #: What being stopped is **expected to cost**, not what it costs at the
    #: drawn stop. Once `slippage` is non-zero these differ: the figure is
    #: computed from the inflated distance, because a broker stop fills through
    #: the spread and the money that leaves the account is what a risk budget
    #: is about.
    #:
    #: The practical consequence, which is easy to trip over: this no longer
    #: reconciles against `volume x stop_distance x tick_value`. It reconciles
    #: against the budget - which is the comparison worth being able to make
    #: directly, and the reason it is defined this way round.
    risk_money: float = 0.0
    #: What one lot loses if the stop is hit, at the same inflated distance.
    #: The number the volume divides.
    loss_per_lot: float = 0.0
    reason: str = ""
    #: How many times the risk budget this trade actually risks. 1.0 or below
    #: on every normally-sized trade; above 1.0 **only** on a minimum lot taken
    #: under `floor_to_min`, and recorded so the journal can say a trade risked
    #: 3.2x what was intended rather than leaving that to be inferred from two
    #: columns nobody joins. `sizing-is-reduction-only` is the standing fact
    #: this breaks on purpose: every other path here clamps at 1.0.
    overshoot: float = 0.0

    @property
    def ok(self) -> bool:
        return self.volume > 0 and not self.reason


def lots(
    spec: SymbolSpec,
    *,
    equity: float,
    risk_fraction: float,
    stop_distance: float,
    max_risk_money: float = 0.0,
    slippage: float = 0.0,
    floor_to_min: float = 0.0,
) -> Sizing:
    """Lots to trade so that being stopped costs the risk budget.

    See `trading-sizing.md` in research/docs.
    """
    if equity <= 0:
        return Sizing(reason="no equity to size against")
    if stop_distance <= 0:
        return Sizing(reason="the stop is at the entry")
    if spec.tick_size <= 0 or spec.tick_value <= 0:
        # A broker that does not state these cannot be sized against, and
        # assuming a tick value is how a position ends up ten times too large.
        return Sizing(reason=f"{spec.symbol} reports no tick value")

    budget = equity * risk_fraction
    if max_risk_money > 0:
        budget = min(budget, max_risk_money)

    # The distance a stop actually costs, not the one it is drawn at.
    realised = stop_distance * (1.0 + max(0.0, slippage))
    loss_per_lot = (realised / spec.tick_size) * spec.tick_value
    if loss_per_lot <= 0:
        return Sizing(reason=f"{spec.symbol} prices a lot at nothing")

    volume = spec.round_volume(budget / loss_per_lot)
    if volume < spec.volume_min:
        at_min = spec.volume_min * loss_per_lot
        # **The minimum lot, deliberately over budget, and only to a ceiling
        # someone set.** Measured on 2026-11-19: a $5,999 account at the
        # default 0.25% fraction has a $15.00 budget, and the three feeds with
        # the widest stops in price terms - japan 225 at an ATR of 315,
        # volatility 75 at 214, us tech 100 at 143 - refused **every** signal
        # here, 55 of 55 in one cycle. The rule fired, the gate held, and the
        # desk looked like a quiet market.
        #
        # `floor_to_min` defaults to 0, so this path is **off** until a
        # ceiling is set and behaviour is unchanged for every caller that does
        # not. That default is the safety: the alternative - taking the minimum
        # lot whenever the budget falls short - has no bound at all, and on
        # japan 225 it would risk several times the intended fraction without
        # anything in the code saying how much.
        if 0.0 < at_min <= floor_to_min:
            return Sizing(
                volume=spec.volume_min,
                risk_money=at_min,
                loss_per_lot=loss_per_lot,
                overshoot=at_min / budget if budget > 0 else 0.0,
            )
        effects.fired("trading.unaffordable_refusal")
        ceiling = (
            f"; the minimum-lot ceiling is {floor_to_min:.2f}"
            if floor_to_min > 0
            else "; no minimum-lot ceiling is set"
        )
        return Sizing(
            loss_per_lot=loss_per_lot,
            reason=(
                f"{budget:.2f} does not cover the minimum {spec.volume_min:g} lot, "
                f"which risks {at_min:.2f} ({at_min / equity:.2%} of equity){ceiling}"
            ),
        )
    return Sizing(
        volume=volume,
        risk_money=volume * loss_per_lot,
        loss_per_lot=loss_per_lot,
        overshoot=(volume * loss_per_lot) / budget if budget > 0 else 0.0,
    )


def respects_stops_level(spec: SymbolSpec, entry: float, stop: float, target: float) -> str:
    """ "" if the broker will accept these, else why it will not.

    Brokers refuse a stop or target closer to price than `stops_level`, and the
    refusal arrives as a retcode after the decision has been made. Scalping
    lives exactly in that band - a tight stop on a quiet minute is often inside
    it - so it is checked before the order rather than discovered by it.
    """
    minimum = spec.min_stop_distance
    if minimum <= 0:
        return ""
    if abs(entry - stop) < minimum:
        return f"stop is {abs(entry - stop):.5g} from price, broker needs {minimum:.5g}"
    if target and abs(target - entry) < minimum:
        return f"target is {abs(target - entry):.5g} from price, broker needs {minimum:.5g}"
    return ""
