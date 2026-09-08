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

from collections.abc import Sequence
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


@dataclass(frozen=True, slots=True)
class Take:
    """Part of a position that should come off now, and why."""

    ticket: int
    volume: float
    reason: str

    def __str__(self) -> str:
        return f"#{self.ticket} take {self.volume:g} off ({self.reason})"


#: Why `partial` last declined. Read by the caller straight after the call, so
#: a single slot is enough - the trading loop is one task and awaits nothing
#: between the two.
#:
#: It exists because `partial` returned a bare `None` from five places, and
#: `scale_out_at` has been set to 1.0 for the whole life of this desk without a
#: single scale-out firing. That is the shape `research/inert.md` catalogues -
#: a feature that is configured, correct and inert - and with five silent exits
#: there was no way to ask which one was responsible.
_WHY: dict[str, str] = {"why": ""}


def _declined(why: str) -> None:
    """Record the reason and decline, so call sites stay one line."""
    _WHY["why"] = why


def why_no_bank() -> str:
    """The reason `partial` last declined, or "" if it did not."""
    return _WHY["why"]


def partial(
    position: Position,
    intent: Intent,
    spec: SymbolSpec,
    settings: Settings,
    *,
    best: float,
    current: float = 0.0,
    armed: bool = False,
) -> Take | None:
    """How much of this position to bank now, or None to leave it whole.

    **Measured from the current price, after the first version read `best` and
    was wrong.** The original argument was that a trade which touched 1.2R and
    retraced had already *earned* the partial, so the retracement should not
    cancel it. Production showed what that means in practice: a us30 position
    logged "banking 50% at 1.5R" and booked **-1.14**, because the trigger read
    a high-water mark while the close executed at market whenever the manage
    loop next ran, by which time price was back through the entry.

    The point of banking is to capture a gain that is *there*. A high-water
    mark is a gain that was there. Reading it arms a market order at a price
    nobody is offering any more, and the log line then describes an event that
    did not happen - which is worse than not banking at all.

    `best` is still taken, because break-even and trailing genuinely do want
    the high-water mark: they protect a trade against giving back what it made,
    which is a different question from realising it.

    **The volume arithmetic is where this goes wrong if it goes wrong.** A
    position of the minimum lot cannot be halved, and a broker asked to close
    0.005 of a 0.01 lot either refuses or - worse - closes the lot. So the
    slice is rounded down to the volume step, and both halves must survive:
    if what comes off or what stays behind lands under `volume_min`, nothing
    is taken and the position runs whole. That is the honest outcome, because
    a scale-out that silently closes everything is not a smaller version of
    this rule, it is a different and much worse one.
    """
    at = settings.scale_out_at
    if at <= 0:
        return _declined("scale_out_at is off")
    fraction = settings.scale_out_fraction
    if not 0.0 < fraction < 1.0:
        return _declined(f"scale_out_fraction {fraction} is not between 0 and 1")

    risk = abs(intent.entry - intent.stop)
    if risk <= 0:
        return _declined("the intent has no risk to measure against")
    # The price a market order would actually get, falling back to the
    # high-water mark only when no current price was supplied.
    now = current or best
    gained = (now - position.price_open) * position.side.sign
    # **Armed on the quote, executed here.** The trigger used to require the
    # position to be at `at` R *when the manage loop happened to look*, and the
    # loop looks far less often than the market moves: 19.6% of closes reached
    # 1.0R by their recorded high-water mark and not one scale-out ever fired,
    # because the peak and the poll are different moments. `_mark_best` sees
    # every quote, so it arms the ticket the instant the trigger is crossed and
    # this decides what to do about it.
    #
    # What does **not** change is the price this banks at. The us30 position
    # that logged "banking 50% at 1.5R" and booked -1.14 did so by reading a
    # high-water mark and sending a market order at whatever existed later.
    # Arming is a statement about the trigger; `gained > 0` below is still
    # measured on the price a market order would get right now.
    if not armed and gained < risk * at:
        return _declined(f"at {gained / risk:+.2f}R now, short of the {at:.2f}R trigger")
    # Never bank into a loss. The threshold above already implies this, but it
    # implied it before too - through a number that had stopped being true.
    if gained <= 0:
        return _declined(
            f"reached the {at:.2f}R trigger but is {gained / risk:+.2f}R now"
            if armed
            else "not in profit at the current price"
        )

    step = spec.volume_step or 0.01
    slice_ = _down_to_step(position.volume * fraction, step)
    stays = _down_to_step(position.volume - slice_, step)
    if slice_ < spec.volume_min or stays < spec.volume_min:
        # Not divisible into two tradeable halves. Runs whole.
        return _declined(
            f"{position.volume:g} lots will not split into two above the "
            f"{spec.volume_min:g} minimum"
        )
    _WHY["why"] = ""
    return Take(position.ticket, slice_, f"banking {fraction:.0%} at {gained / risk:.1f}R")


def _down_to_step(volume: float, step: float) -> float:
    """`volume` rounded down to a whole number of steps.

    Down rather than nearest, so neither half of a scale-out can be rounded up
    into more than the position holds.
    """
    if step <= 0:
        return volume
    # Floats: 0.03 / 0.01 is 2.9999... and floor would take it to 2. The
    # epsilon is a hair under one step, so a value that is a whole number of
    # steps stays one.
    return int(volume / step + 1e-9) * step


def _behind_the_last_rung(
    rungs: Sequence[float], best: float, sign: int, clearance: float
) -> float | None:
    """A stop just beyond the nearest level price has already cleared.

    "Cleared" is doing the work. For a long that is the **highest** rung below
    the high-water mark: the last price the market agreed on that the trade has
    got past, and therefore the last one it can fall back to and still be
    right. A rung above `best` has not been reached and is a target.

    `clearance` puts the stop beyond the level rather than on it, because a
    level is where price turns and a stop sitting exactly there is taken by the
    turn it is meant to survive.
    """
    if sign > 0:
        cleared = [r for r in rungs if r < best]
        return max(cleared) - clearance if cleared else None
    cleared = [r for r in rungs if r > best]
    return min(cleared) + clearance if cleared else None


def advance(
    position: Position,
    intent: Intent,
    spec: SymbolSpec,
    settings: Settings,
    *,
    best: float,
    vol_bps: float = 0.0,
    rungs: Sequence[float] = (),
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
        # **Behind a level, when the intent asked for that and one is cleared.**
        #
        # A fixed distance is a distance nobody chose for this instrument at
        # this moment: 2v behind a price that has run four is giving back two,
        # and 2v behind one that has run half is a stop inside the noise. A
        # rung is a price the market has already agreed on, so a stop just
        # beyond one is protected by the same thing the entry was.
        #
        # Only rungs price has actually **cleared** - a level ahead of the
        # trade is a target, not a stop - and only when the result is tighter
        # than the volatility trail, so this can shorten the leash and never
        # lengthen it. A move that has cleared nothing keeps the trail it had.
        if intent.trail_levels and rungs:
            step = _behind_the_last_rung(rungs, best, sign, price_distance(best, vol_bps, 0.25))
            if step is not None and better(step, level, position.side):
                level = step
                reason = f"behind the {step:.5g} level"
        # Only once the trail is actually in front of the original stop -
        # otherwise a trade that has barely moved gets a tighter stop than it
        # was sized for, which is a different trade from the one that was
        # judged.
        if _better(level, proposed, position.side) and _better(level, intent.stop, position.side):
            proposed = level
            reason = reason or f"trailing {room:.2f}v behind {best:.5g}"

    if not reason:
        return None

    stop = spec.round_price(proposed)
    if not _better(stop, position.stop, position.side):
        return None
    # A broker refuses a stop closer to price than `stops_level`, and a
    # rejected modify on every heartbeat is noise that hides real failures.
    #
    # Held to the same clearance the entry stop is, and for the same reason:
    # the minimum is checked against the price when the modify lands, and
    # `best` is by definition the most favourable price seen rather than the
    # current one, so the true distance is this or smaller - never larger.
    room = spec.min_stop_distance * settings.stops_level_margin
    if spec.stops_level > 0 and abs(best - stop) < room:
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
