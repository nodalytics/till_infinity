"""Monetary policy as a number a strategy can read.

`news/fred.py` collects thirty series of central-bank policy and market-priced
inflation, and until this existed nothing read them: 2,174 rows in the store,
zero consumers. Collection without consumption is not a head start, it is a
cost with no benefit, and it looks like progress from the outside.

This is the consumer, and it is deliberately two things at once.

## The cheap half: policy as features on a signal that already exists

Every level call already carries a float dictionary of the conditions it was
found in - volatility, activity, the hour's share, the venue spread. A rate
differential belongs in exactly that dictionary: it is a condition the trade
was taken in, it costs nothing to attach, and it lands in the journal beside
the outcome, so the question "does the carry gap predict which way a level
breaks" becomes answerable by a query rather than by a rebuild.

That is the whole argument for doing it this way first. The features are
published and **decide nothing**. If the gap turns out to be noise, nothing has
to be unwound.

## The expensive half: policy as a model with its own signals

`calls()` is the model. It reads the same state and emits a `Shape.MACRO`
signal when a currency pair's stance *changes* - not while it is merely
lopsided. The distinction is the whole design: a rate gap that has been wide
for a year is priced, and a signal that repeats it every poll is a constant
wearing a timestamp. What is not priced is the change, so the model fires on
turns and stays quiet in between.

## Why the differential is built the way it is

A differential is only meaningful when both legs are the **same measurement**.
Quoting an overnight policy rate for one currency against a ten-year yield for
another produces a number that moves with the shape of one curve rather than
with the gap between two countries, and it will look like signal because it
moves.

So the currencies are read off two OECD families, `IRSTCI01xxM156N` (overnight)
and `IRLTLT01xxM156N` (ten-year), which are one definition with the country
swapped. They are monthly and about two months behind - checked on the live
API, not assumed. Where a daily policy rate exists (the dollar, the euro and
sterling) it is preferred for the *level*, because it is current; the trend is
always taken from the monthly family, so a trend never compares a daily series
against a monthly one.

**A leg with no rate produces no gap**, rather than a gap against zero. Gold,
the indices, the crypto and the synthetics have no policy rate by construction,
and they are read on the dollar block instead - the real yield and the
breakeven - which is the correct macro reading for a dollar-quoted asset with
no carry of its own.

## What this does not claim

Nothing here is fast. The best of these series moves once a day and most move
once a month, so a macro call is context for a trade rather than a trade. It is
published, journalled and scored so the outcome machinery can say whether it
was worth anything, which is the only thing that can settle it.
"""

from __future__ import annotations

import sqlite3
import statistics as st
import time
from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from ..logging import get_logger
from .models import Shape, Signal
from .state import Restorable

log = get_logger(__name__)

DAY = 86_400.0

#: How far back a "change" looks. A quarter: long enough that a monthly series
#: has moved two or three times, short enough to still be about now.
TREND_DAYS = 90.0

#: The overnight rate per currency, one OECD definition with the country
#: swapped. Germany stands in for the euro area: the euro-area aggregate exists
#: and stops in January 2026, which is worse than a proxy that is current.
OVERNIGHT: dict[str, str] = {
    "USD": "IRSTCI01USM156N",
    "EUR": "IRSTCI01DEM156N",
    "GBP": "IRSTCI01GBM156N",
    "JPY": "IRSTCI01JPM156N",
    "CAD": "IRSTCI01CAM156N",
    "AUD": "IRSTCI01AUM156N",
}

#: The ten-year rate per currency, same argument. Two more currencies reach
#: here than reach `OVERNIGHT`, which is why the curve is carried separately
#: rather than folded into one score.
LONG: dict[str, str] = {
    "USD": "IRLTLT01USM156N",
    "EUR": "IRLTLT01DEM156N",
    "GBP": "IRLTLT01GBM156N",
    "JPY": "IRLTLT01JPM156N",
    "CAD": "IRLTLT01CAM156N",
    "AUD": "IRLTLT01AUM156N",
    "CHF": "IRLTLT01CHM156N",
    "NZD": "IRLTLT01NZM156N",
}

#: Daily policy rates, for the three currencies that publish one. Used for the
#: *level* only - see the module docstring on not mixing frequencies in a trend.
POLICY: dict[str, str] = {
    "USD": "DFF",
    "EUR": "ECBDFR",
    "GBP": "IUDSOIA",
}

#: The balance sheet behind each currency. How much money exists, which is the
#: other half of what a currency is worth and the half that moves gold.
BALANCE: dict[str, str] = {
    "USD": "WALCL",
    "EUR": "ECBASSETSW",
    "JPY": "JPNASSETS",
}

#: The dollar block, attached to every instrument whatever its legs. A
#: dollar-quoted asset with no carry of its own - gold, an index, the crypto -
#: is read on the real yield and the breakeven, and those are dollar series.
REAL_YIELD = "DFII10"
BREAKEVEN = "T10YIE"
CURVE_LONG, CURVE_SHORT = "DGS10", "DGS2"

#: Currencies this module can say anything about at all.
CODES: frozenset[str] = frozenset(OVERNIGHT) | frozenset(LONG) | frozenset(POLICY)

#: Codes that can appear in an FX pair's name. Wider than `CODES` on purpose:
#: `usdcnh` is a pair whether or not there is a Chinese rate series to read, and
#: treating it as an unrecognised instrument reported it as dollar-quoted -
#: which is the offshore yuan deleted from its own pair.
#:
#: A list rather than "six letters", because `silver` is six letters and splits
#: into a base of SIL and a quote of VER, which then quietly gets a dollar
#: reading attached to the wrong instrument.
ISO: frozenset[str] = frozenset(
    {
        "USD",
        "EUR",
        "GBP",
        "JPY",
        "CHF",
        "CAD",
        "AUD",
        "NZD",
        "CNH",
        "CNY",
        "HKD",
        "SGD",
        "SEK",
        "NOK",
        "DKK",
        "PLN",
        "HUF",
        "CZK",
        "MXN",
        "ZAR",
        "TRY",
        "INR",
        "KRW",
        "BRL",
    }
)

#: What a non-FX instrument is quoted in. Everything absent is quoted in
#: dollars, which is all of them except the European and Asian index CFDs.
#:
#: Kept here rather than imported from `trading.exposure`, which has the same
#: table for a different purpose: `trading` imports `structures` and reaching
#: back the other way would close the cycle. A test asserts the two agree, so
#: the duplication cannot drift silently.
QUOTED_IN: dict[str, str] = {
    "ger40": "EUR",
    "fra40": "EUR",
    "eu50": "EUR",
    "uk100": "GBP",
    "jp225": "JPY",
    "aus200": "AUD",
    # No Hong Kong rate series here, so this attaches nothing - which is the
    # point. Left at the dollar default it would attach a US reading to an
    # instrument this module has nothing to say about.
    "hk50": "HKD",
}

#: How many past changes a score needs before it is standardised against them.
#: Below this the size of a move cannot be judged, and the signal says so by
#: scoring 1.0 rather than by inventing a z-score from four points.
MIN_HISTORY = 8

#: How large a change in the gap has to be, relative to its own past changes,
#: before the model speaks. One typical quarter's move is not news.
MOVE_SCORE = 1.0


def currencies(feed: str) -> tuple[str, str]:
    """`(base, quote)` in currency terms, or `("", quote)` when the base is not one.

    A six-letter feed whose halves are both currencies is a pair and is split
    as one - a rule rather than a table, so a pair added to the book is covered
    the day it is added. Everything else is an instrument quoted in a currency:
    gold, an index, a synthetic. Its base is empty, which is the honest answer,
    and is what stops a carry gap being computed against a leg that has no
    carry.
    """
    name = feed.strip().lower()
    if len(name) == 6 and name.isalpha():
        base, quote = name[:3].upper(), name[3:].upper()
        # Split on both halves being currencies, not on the length. A leg with
        # no rate series still splits correctly - it produces an empty
        # `Reading` and therefore no gap, which is the right silence - but
        # `silver` is not a pair and must not become one.
        if base in ISO and quote in ISO:
            return base, quote
    return "", QUOTED_IN.get(name, "USD")


@dataclass(frozen=True, slots=True)
class Reading(Restorable):
    """What is known about one currency's monetary policy right now.

    Every field is optional and `None` means *not published*, never zero. A
    currency with no overnight series is not a currency at zero rates.

    `Restorable` and a default on every field although nothing pickles this:
    the guard that asks for it is a walk over every slotted dataclass in the
    package, and the version of that guard which named its classes passed while
    being blind to twenty others. Arguing the exemption is how the walk gets a
    hole in it, and inheriting costs nothing.
    """

    currency: str = ""
    policy: float | None = None
    overnight: float | None = None
    long: float | None = None
    #: Change in the overnight rate over `TREND_DAYS`, in percentage points.
    trend: float | None = None
    #: Relative change in the central bank's balance sheet over `TREND_DAYS`.
    liquidity: float | None = None

    @property
    def carry(self) -> float | None:
        """The rate a differential is built on: the daily one where it exists.

        Preferring the daily series for the level and the monthly one for the
        trend is not inconsistency - it is the reason both are carried. The
        level wants to be current and the trend wants both legs measured the
        same way, and no single series does both.
        """
        return self.policy if self.policy is not None else self.overnight

    @property
    def curve(self) -> float | None:
        """Ten-year minus overnight. Steepening is growth or inflation priced in."""
        if self.long is None or self.overnight is None:
            return None
        return self.long - self.overnight

    @property
    def known(self) -> bool:
        return self.carry is not None


def _gap(left: float | None, right: float | None) -> float | None:
    """One leg minus the other, or None when either leg is missing.

    Missing is not zero, and this is the function that keeps it from becoming
    zero. A gap against an absent leg is the yen's rate reported as the whole
    differential, which reads as an enormous carry trade in whichever direction
    the present leg points.
    """
    if left is None or right is None:
        return None
    return left - right


class Macro:
    """Every FRED series that has arrived, and what they say per currency.

    Rebuilt from the store rather than persisted: the observations are already
    durable in `news`, and a second copy of them would be a second thing to
    keep correct. Cheap to rebuild - thirty series of daily-at-fastest data
    over four hundred days is a few thousand floats.
    """

    def __init__(self, memory: int = 600) -> None:
        self.memory = memory
        #: series -> parallel, time-sorted lists. Two lists rather than a list
        #: of pairs so `bisect` can search the times directly.
        self._when: dict[str, list[float]] = {}
        self._value: dict[str, list[float]] = {}
        #: feed -> the stance last announced, so `calls` fires on the turn and
        #: not on every poll of a gap that has not moved.
        self._stance: dict[str, int] = {}

    # ------------------------------------------------------------ collecting

    def observe(self, series: str, when: float, value: float) -> bool:
        """Take one observation. True when it was new.

        Out-of-order arrival is normal here - FRED answers newest-first and a
        revision restates an old date - so the insert keeps the list sorted
        rather than assuming an append is correct.
        """
        if not series or not when:
            return False
        times = self._when.setdefault(series, [])
        values = self._value.setdefault(series, [])
        at = bisect_left(times, when)
        if at < len(times) and times[at] == when:
            if values[at] == value:
                return False
            values[at] = value  # a revision
            return True
        times.insert(at, when)
        values.insert(at, value)
        if len(times) > self.memory:
            del times[: len(times) - self.memory]
            del values[: len(values) - self.memory]
        return True

    def take(self, rows: Iterable[object]) -> int:
        """Take a batch of stored observations. Anything unshaped is skipped."""
        taken = 0
        for row in rows:
            series = getattr(row, "series", None)
            when = getattr(row, "time", None)
            value = getattr(row, "value", None)
            if not isinstance(series, str) or not isinstance(when, int | float):
                continue
            if not isinstance(value, int | float):
                continue
            taken += self.observe(series, float(when), float(value))
        return taken

    @property
    def warm(self) -> bool:
        """True once anything has arrived. Nothing is published before that."""
        return bool(self._when)

    # -------------------------------------------------------------- reading

    def latest(self, series: str) -> float | None:
        values = self._value.get(series)
        return values[-1] if values else None

    def at(self, series: str, ago: float) -> float | None:
        """The value `ago` seconds before the newest one, or None if unreachable.

        The nearest observation *at or before* that point, which is what a
        monthly series forces: asking for ninety days ago on a series published
        on the first of the month has to land on a published date or on
        nothing, and landing on nothing every time would make the trend always
        absent.
        """
        times, values = self._when.get(series), self._value.get(series)
        if not times or not values:
            return None
        # The newest observation at or before the point asked for, and **None**
        # when every observation is newer than it. Returning the oldest one
        # instead made a single observation its own past, so a series with one
        # point reported a change of exactly zero - which is a claim, and a
        # confident one, made from no evidence at all.
        at = bisect_right(times, times[-1] - ago) - 1
        return values[at] if at >= 0 else None

    def change(self, series: str, ago: float = TREND_DAYS * DAY) -> float | None:
        """Newest minus `ago`, absolutely. None unless both ends exist."""
        now, then = self.latest(series), self.at(series, ago)
        if now is None or then is None:
            return None
        return now - then

    def relative(self, series: str, ago: float = TREND_DAYS * DAY) -> float | None:
        """The same change as a fraction of where it started.

        Balance sheets are read this way and rates are not: a trillion dollars
        means nothing without the level it is a trillion out of, while a rate
        moving a point means a point wherever it started.
        """
        now, then = self.latest(series), self.at(series, ago)
        if now is None or then is None or then == 0:
            return None
        return (now - then) / abs(then)

    def reading(self, currency: str) -> Reading:
        """Everything known about one currency. Absent series stay `None`."""
        code = currency.strip().upper()
        overnight = OVERNIGHT.get(code, "")
        balance = BALANCE.get(code, "")
        return Reading(
            currency=code,
            policy=self.latest(POLICY[code]) if code in POLICY else None,
            overnight=self.latest(overnight) if overnight else None,
            long=self.latest(LONG[code]) if code in LONG else None,
            trend=self.change(overnight) if overnight else None,
            liquidity=self.relative(balance) if balance else None,
        )

    # -------------------------------------------------- the cheap half

    def features(self, feed: str) -> dict[str, float]:
        """Policy as floats, for a signal's feature dictionary.

        Only what is actually known. An absent series leaves its key out rather
        than writing a zero, because a zero here is indistinguishable from a
        rate of zero and the yen would read as the flattest curve in the book.

        Every key is prefixed `macro_` so a journal query can select the block
        without knowing what is in it, and every value is a float, which is the
        contract `Signal.features` enforces - a string put here raised on the
        first signal and stopped the structures consumer for four minutes.
        """
        if not self.warm:
            return {}
        base, quote = currencies(feed)
        out: dict[str, float] = {}

        left, right = self.reading(base) if base else None, self.reading(quote)
        if left is not None and left.known and right.known:
            gap = _gap(left.carry, right.carry)
            if gap is not None:
                out["macro_carry_gap"] = gap
            trend = _gap(left.trend, right.trend)
            if trend is not None:
                out["macro_carry_gap_change"] = trend
            curve = _gap(left.curve, right.curve)
            if curve is not None:
                out["macro_curve_gap"] = curve
            liquidity = _gap(left.liquidity, right.liquidity)
            if liquidity is not None:
                out["macro_liquidity_gap"] = liquidity
        elif right.liquidity is not None:
            # No base leg, so no differential - but the currency it is quoted
            # in still has a balance sheet, and that is the reading that
            # matters for a dollar-quoted asset with no carry of its own.
            out["macro_liquidity"] = right.liquidity

        # The dollar block, on everything. The dollar is on one side of almost
        # every instrument here by construction, so this is not US-specific
        # trivia attached to a euro cross - it is the discount rate the whole
        # book is priced against.
        for key, series in (
            ("macro_us_real_yield", REAL_YIELD),
            ("macro_us_breakeven", BREAKEVEN),
        ):
            value = self.latest(series)
            if value is not None:
                out[key] = value
            moved = self.change(series)
            if moved is not None:
                out[key + "_change"] = moved
        curve = _gap(self.latest(CURVE_LONG), self.latest(CURVE_SHORT))
        if curve is not None:
            out["macro_us_curve"] = curve
        return out

    # ------------------------------------------------ the expensive half

    def _typical(self, series: str) -> float:
        """A typical `TREND_DAYS` move in this series, from its own history.

        The median absolute change across the history held, which is what makes
        a score scale-free: half a point is enormous for the yen and ordinary
        for sterling, and a threshold in percentage points would be one or the
        other. Returns 0.0 when there is not enough history to say, and the
        caller then declines to score rather than inventing one.
        """
        times, values = self._when.get(series), self._value.get(series)
        if not times or len(times) < MIN_HISTORY:
            return 0.0
        step = TREND_DAYS * DAY
        moves: list[float] = []
        for index, when in enumerate(times):
            past = bisect_left(times, when - step)
            if past and times[past] > when - step:
                past -= 1
            if past < index:
                moves.append(abs(values[index] - values[past]))
        moves = [m for m in moves if m > 0]
        return st.median(moves) if len(moves) >= MIN_HISTORY else 0.0

    def stance(self, feed: str) -> tuple[int, float, str]:
        """`(direction, score, why)` for one instrument. Direction 0 means silent.

        Two rules, and both ask for the level and the change to **agree**:

        * a currency pair follows the carry. The base is favoured when it pays
          more *and* the gap is widening. A wide gap on its own is priced - it
          has been there for everyone to see - so the level alone says nothing
          and this declines to speak on it.
        * a dollar-quoted asset with no carry follows the discount rate. Gold,
          the crypto and the indices go up when the real yield falls and the
          balance sheet expands, and the two have to agree for the same reason.

        Disagreement returns 0, which is the common case and is the point. A
        model that always has an opinion is not reading anything.
        """
        base, quote = currencies(feed)
        if base:
            left, right = self.reading(base), self.reading(quote)
            gap = _gap(left.carry, right.carry)
            moved = _gap(left.trend, right.trend)
            if gap is None or moved is None or gap == 0 or moved == 0:
                return 0, 0.0, ""
            if (gap > 0) != (moved > 0):
                return 0, 0.0, ""
            typical = max(
                self._typical(OVERNIGHT.get(base, "")),
                self._typical(OVERNIGHT.get(quote, "")),
            )
            score = abs(moved) / typical if typical > 0 else 1.0
            side = 1 if gap > 0 else -1
            return (
                side,
                score,
                f"{base} pays {abs(gap):.2f}pp {'more' if gap > 0 else 'less'} than {quote} "
                f"and the gap moved {moved:+.2f}pp over {TREND_DAYS:.0f} days",
            )

        real = self.change(REAL_YIELD)
        liquidity = self.relative(BALANCE.get(quote, ""))
        if real is None or liquidity is None or real == 0 or liquidity == 0:
            return 0, 0.0, ""
        # Falling real yield and expanding balance sheet both argue up.
        if (real < 0) != (liquidity > 0):
            return 0, 0.0, ""
        typical = self._typical(REAL_YIELD)
        score = abs(real) / typical if typical > 0 else 1.0
        side = 1 if real < 0 else -1
        return (
            side,
            score,
            f"the {quote} real yield moved {real:+.2f}pp and its balance sheet "
            f"{liquidity:+.1%} over {TREND_DAYS:.0f} days",
        )

    def calls(self, feeds: Sequence[str]) -> list[Signal]:
        """Signals for the instruments whose stance has just changed.

        Fires on the turn, not on the state. A gap that has been wide all year
        is priced and repeating it every poll would publish a constant wearing
        a timestamp; what is not priced is the change, so a feed already
        announced in this direction stays quiet until it flips.
        """
        found: list[Signal] = []
        for feed in feeds:
            if not feed:
                continue
            side, score, why = self.stance(feed)
            was = self._stance.get(feed, 0)
            if side == 0:
                # Not a reversal - the evidence went quiet. Forgotten so the
                # next reading is announced, rather than treated as a flip.
                self._stance.pop(feed, None)
                continue
            if side == was:
                continue
            if score < MOVE_SCORE:
                # Below its own typical move. Not announced and not remembered,
                # so it is reconsidered rather than suppressed once it grows.
                continue
            self._stance[feed] = side
            found.append(
                Signal(
                    shape=Shape.MACRO,
                    feed=feed,
                    venue="policy",
                    score=min(score, 10.0),
                    direction="up" if side > 0 else "down",
                    detail=why,
                    interval="1d",
                    features=self.features(feed),
                )
            )
        return found


class Point(NamedTuple):
    """One stored observation, in the three fields `Macro.take` reads."""

    series: str
    time: float
    value: float


def stored(path: str | Path, *, since: float = 0.0, source: str = "fred") -> list[Point]:
    """Observations out of the news store, read-only.

    Read directly rather than through `news.store`, and that is the same choice
    the level warm-up already makes with the prices database: `structures` is
    downstream of `news` on the bus and importing its store to read it would
    put a writer's lock handling in a consumer that only ever reads.

    A missing or unreadable database is not an error here. Macro features are
    an enrichment - the level calls they attach to are correct without them -
    so this returns nothing and says so once, rather than stopping the service
    that consumes it.
    """
    uri = f"file:{Path(path)}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    except sqlite3.Error as exc:
        log.warning("macro: no policy data at %s: %s", path, exc)
        return []
    try:
        rows = conn.execute(
            "SELECT series, time, value FROM observations"
            " WHERE source = ? AND time >= ? ORDER BY time ASC",
            (source, since),
        ).fetchall()
    except sqlite3.Error as exc:
        log.warning("macro: could not read %s: %s", path, exc)
        return []
    finally:
        conn.close()
    return [Point(str(a), float(b), float(c)) for a, b, c in rows]


#: How far back the first read reaches. Enough for `TREND_DAYS` of history
#: several times over, so a change is computable the moment the service starts
#: rather than a quarter after it.
HISTORY_DAYS = 500.0


def since_default(now: float | None = None) -> float:
    """The epoch second `stored` should read from on a cold start."""
    return (time.time() if now is None else now) - HISTORY_DAYS * DAY
