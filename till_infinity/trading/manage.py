"""Moving a stop after the trade is on. Off by default, and that is a finding.

Two rules, both standard, both switched off unless asked for:

* **break-even** - once price is `break_even_at` R in front, move the stop to
  the entry (plus a configurable cushion for the spread, because a stop
  *at* the entry on a long is hit by the bid while the fill paid the ask);
* **trailing** - thereafter, keep the stop `trail_vol` volatility units behind
  the best price the trade has seen, never moving it backwards.

**Why they are off.** Both cut the loss tail, and both cut winners. Which
dominates is an empirical question about this strategy on these instruments,
and nothing in this repository answers it - there is no evaluation of trading
outcomes yet, because until `structures.resolutions` was put on the bus there
was no ground truth to evaluate against. Shipping them on by default would be
asserting the answer.

They are here rather than absent because the experiment is worth running and
the machinery is the same either way. `TRADING_BREAK_EVEN_AT` and
`TRADING_TRAIL_VOL` turn each on independently, so the four combinations can be
compared on the journal once there are enough closed trades to compare.

**The stop only ever moves toward profit.** Every path returns the existing
stop unless the new one is strictly better, because a rule that can widen a
stop is not risk management - it is the trade quietly asking for more room
after it has started going wrong, which is the single most expensive habit in
discretionary trading and does not become cheaper for being automated.

The bridge has its own trailing-stop handler running on a twenty-second timer.
This does not use it: two things moving the same stop on different clocks would
race, and the one that lost would look like a broker fault. Ours is the one the
journal can explain, so ours is the one that runs - set the bridge's off.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..logging import get_logger
from .config import Settings
from .models import Intent, Position, Side, SymbolSpec
from .sizing import price_distance

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Move:
    """A stop that should be moved, and why. `None` means leave it alone."""

    ticket: int
    stop: float
    reason: str

    def __str__(self) -> str:
        return f"#{self.ticket} stop to {self.stop:.5g} ({self.reason})"


def advance(
    position: Position,
    intent: Intent,
    spec: SymbolSpec,
    settings: Settings,
    *,
    best: float,
    vol_bps: float = 0.0,
) -> Move | None:
    """Where this position's stop should be now, or None to leave it.

    `best` is the most favourable price the trade has seen - the high for a
    long, the low for a short - tracked by the caller from the quote stream,
    because a broker's `price_current` is a snapshot and a trailing stop
    anchored to snapshots trails whatever the last poll happened to catch.
    """
    # The strategy's own numbers win where it states them. A global threshold
    # cannot fit both a thirty-minute thesis and a two-minute one.
    even_at = intent.break_even_at or settings.break_even_at
    trail_at = intent.trail_vol or settings.trail_vol
    if not (even_at > 0 or trail_at > 0):
        return None

    risk = abs(intent.entry - intent.stop)
    if risk <= 0:
        return None

    sign = position.side.sign
    gained = (best - position.price_open) * sign
    if gained <= 0:
        return None

    proposed = position.stop
    reason = ""

    if even_at > 0 and gained >= risk * even_at:
        # The cushion covers the spread: a long exits on the bid, so a stop
        # exactly at the entry books a small loss rather than a scratch.
        cushion = spec.tick_size * max(0, settings.break_even_ticks)
        level = position.price_open + sign * cushion
        if _better(level, proposed, position.side):
            proposed, reason = level, f"break even at {gained / risk:.1f}R"

    if trail_at > 0 and vol_bps > 0:
        # How far behind, in the level's own terms rather than a flat number.
        #
        # `trail_vol` is already in volatility units, so it adapts across
        # instruments and regimes - 2v on gold is not 2v on the FTSE. What it
        # does not adapt to is how far *this level's* pullbacks run, and that
        # is the thing a trail has to survive: a level whose wicks reach 3v
        # will take out a 2v trail on an ordinary retracement while the move is
        # still going, which is being stopped by noise in profit.
        #
        # Same correction the pullback depth got, from the same numbers. The
        # side is the one price would retrace *into*, which is the side the
        # trade came from.
        features = intent.features or {}
        wick = (
            features.get("wick_below_vol" if position.side is Side.BUY else "wick_above_vol") or 0.0
        )
        spread_vol = (
            features.get("wick_below_sd" if position.side is Side.BUY else "wick_above_sd") or 0.0
        )
        seen = features.get("wick_n") or 0.0
        room = trail_at
        if seen >= 2:
            room = max(room, float(wick) + float(spread_vol) * settings.trail_sigmas)
        behind = price_distance(best, vol_bps, room)
        level = best - sign * behind
        # Only once the trail is actually in front of the original stop -
        # otherwise a trade that has barely moved gets a tighter stop than it
        # was sized for, which is a different trade from the one that was
        # judged.
        if _better(level, proposed, position.side) and _better(level, intent.stop, position.side):
            proposed = level
            reason = f"trailing {room:.2f}v behind {best:.5g}"

    if not reason:
        return None

    stop = spec.round_price(proposed)
    if not _better(stop, position.stop, position.side):
        return None
    # A broker refuses a stop closer to price than `stops_level`, and a
    # rejected modify on every heartbeat is noise that hides real failures.
    if spec.stops_level > 0 and abs(best - stop) < spec.min_stop_distance:
        return None
    return Move(ticket=position.ticket, stop=stop, reason=reason)


def better(candidate: float, current: float, side: Side) -> bool:
    """Whether `candidate` is a tighter stop than `current` for this side.

    Higher is better for a long, lower for a short. A stop of zero means the
    position has none, so anything beats it.

    Public because the hold extension in `service` asks the same question - it
    must not move a stop backwards either, and there should be one answer to
    "is this stop better" rather than two that can drift apart.
    """
    if not current:
        return True
    return candidate > current if side is Side.BUY else candidate < current


#: The private name this had before `service` needed it too.
_better = better
