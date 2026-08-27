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
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Side, SymbolSpec


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

    Beyond the *level*, not beyond the entry. The level is the thing being
    traded - the price at which this instrument has repeatedly turned - so the
    trade is wrong when price is through it, whatever the fill happened to be.
    Anchoring the stop to the fill instead would move the invalidation point
    every time the spread widened.

    **And beyond the zone, not beyond the origin.** A level is a range, not a
    line: the origin is where the leg in met the leg out, and the band extends
    by however far the wick ran past it on that side. A stop placed at
    `origin - distance` can therefore sit *inside* the band where wicks
    routinely reach, which is not a stop at all - it is a standing offer to be
    swept and then watch the trade work without you. `zone_edge` is that
    band's far edge and the stop is pushed outside it, plus `clearance` so it
    is not resting exactly where the last wick stopped.

    Being wrong and being swept look identical in the account and are not the
    same event. This is the difference.
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
) -> Sizing:
    """Lots to trade so that being stopped costs the risk budget.

    `slippage` is how much further than the placed stop a stopped trade
    actually costs, as a fraction of the stop distance. It inflates the
    distance sized against, so a stop that fills 9% past still loses the
    budgeted money rather than 9% more of it.

    Measured at 0.087 across the stopped trades in the journal, of which
    two-thirds is the exit rather than the entry: a broker stop is a market
    order once triggered and fills through the spread. Sizing against the stop
    we *place* rather than the one we *get* breaches the risk budget on every
    loss, quietly and by a constant.
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
        return Sizing(
            loss_per_lot=loss_per_lot,
            reason=(
                f"{budget:.2f} does not cover the minimum {spec.volume_min:g} lot, "
                f"which risks {at_min:.2f} ({at_min / equity:.2%} of equity)"
            ),
        )
    return Sizing(volume=volume, risk_money=volume * loss_per_lot, loss_per_lot=loss_per_lot)


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
