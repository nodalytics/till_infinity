"""The options book, and what it says about who has to hedge.

## Why this is different from everything else collected here

`positioning.py` argues that open interest is worth having because it separates
new money from closing, and the price path is identical either way. Options
carry a stronger version of the same argument: a strike is **a price somebody
committed at**, an expiry puts a clock on the commitment, and the size at each
strike is published rather than inferred.

The specific thing that connects to what this book already models is **gamma**.
A dealer who is short gamma must buy as price rises and sell as it falls, which
amplifies a move; long gamma is the mirror and damps it. That is a claim about
whether a level holds - exactly what `learning/breaking.py` models from price
alone at AUC 0.658 - arrived at from evidence a price-only model cannot reach.

## What is actually reachable, and it is not much of the book

Deribit is the one crypto options venue on the ccxt path this repository
already uses, and it lists **BTC and ETH**. Everything else this desk trades -
seven FX majors, gold, silver, the indices, and every synthetic - has no
options data reachable from here at all. Equity options are a paid feed the
broker does not carry.

So this is two instruments out of forty-two, and any feature built on it is a
feature that exists for two of them. `research/crypto.md` makes the same point
about coverage and it applies with more force here: **a reading present on a
twentieth of the book is a comparison between instruments rather than about
them**, and that is how it must be published if it is published at all.

## The honest limit: dealer sign is an assumption, not data

"Gamma exposure" as usually quoted assumes dealers are short calls and long
puts - that the public buys calls and dealers take the other side. **That is a
convention, not an observation.** The exchange publishes open interest, not who
holds it, and on crypto venues where retail sells covered calls the usual sign
is arguably backwards.

So this module publishes the **unsigned** quantity - gamma times open interest
per strike, which is a fact - and exposes the sign as an explicit, named
assumption a consumer applies if it wants to. Baking the convention in would
turn an observation into a guess wearing an observation's units, which is the
shape `research/inert.md` catalogues in its more dangerous form: not a number
nothing reads, but a number read as more than it is.

Nothing consumes any of this yet, deliberately, and for the reason
`positioning.py` already gives: open interest has sat there unread since it was
built, and a fourth collector feeding nothing is how that list gets longer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ..logging import get_logger

log = get_logger(__name__)

#: The venue. One, because it is the one ccxt reaches that lists options.
VENUE = "deribit"

#: What Deribit lists. Named rather than discovered so a silent expansion of
#: the exchange's board cannot quietly widen what this desk collects.
UNDERLYINGS: tuple[str, ...] = ("BTC", "ETH")

#: Strikes further than this from spot, as a share of spot, are dropped. A
#: 200%-out-of-the-money strike has a gamma indistinguishable from zero and an
#: open interest that is somebody's lottery ticket; keeping it adds rows and
#: moves no total.
NEAR = 0.35

#: Below this many contracts a strike is noise. Deribit lists a long tail of
#: strikes with a handful of contracts against them.
MIN_OI = 1.0


@dataclass(frozen=True, slots=True)
class Strike:
    """One expiry and strike, with the size standing at it."""

    feed: str
    underlying: str
    strike: float
    expiry: float
    kind: str
    #: Contracts outstanding. In **contracts**, which on Deribit is one unit of
    #: the underlying - so unlike perpetual open interest this one does compare
    #: across strikes of the same underlying, and still not across underlyings.
    open_interest: float
    #: The exchange's own greeks where it publishes them. Deribit does; nothing
    #: here recomputes them, because a Black-Scholes gamma from a mid price and
    #: a guessed rate is a worse number than the venue's own.
    gamma: float = 0.0
    mark_iv: float = 0.0
    spot: float = 0.0
    time: float = 0.0

    @property
    def gamma_size(self) -> float:
        """Gamma times the size standing at this strike - **unsigned**.

        The fact. Who is on which side of it is the assumption, and it lives in
        `dealer_sign` where a reader can see it rather than inherit it.
        """
        return self.gamma * self.open_interest

    @property
    def notional_gamma(self) -> float:
        """`gamma_size` in currency per 1% move, which is the usual quoting.

        Gamma is per one unit of price; multiplying by spot squared and a
        hundredth converts "delta change per unit" into "delta change per 1%",
        which is the form that compares across price levels.
        """
        return self.gamma_size * self.spot * self.spot * 0.01

    @property
    def moneyness(self) -> float:
        """How far the strike is from spot, as a share of spot. Signed."""
        return (self.strike - self.spot) / self.spot if self.spot else 0.0


def dealer_sign(kind: str, *, dealers_short_calls: bool = True) -> int:
    """+1 or -1 for a strike, under a **stated** assumption about who holds it.

    The convention behind every "GEX" chart is that the public buys calls and
    dealers sell them, so dealers are short call gamma and long put gamma. On
    crypto venues, where covered-call selling by holders is a large share of
    the flow, that is arguably backwards - which is exactly why this is a
    parameter with a default rather than arithmetic baked into a total.

    Nothing in this repository is entitled to use it without saying which way
    it set it and why.
    """
    if dealers_short_calls:
        return -1 if kind == "call" else 1
    return 1 if kind == "call" else -1


def _strike_from(row: dict[str, Any], feed: str, underlying: str, spot: float) -> Strike | None:
    """One ccxt option row, or None when it carries nothing usable."""
    info = row.get("info") if isinstance(row.get("info"), dict) else {}
    greeks = row.get("greeks") if isinstance(row.get("greeks"), dict) else {}
    oi = row.get("openInterest")
    if not isinstance(oi, int | float) or oi < MIN_OI:
        return None
    strike = row.get("strike") or info.get("strike")
    if not isinstance(strike, int | float) or not strike:
        return None
    if spot and abs(float(strike) - spot) / spot > NEAR:
        return None
    stamp = row.get("timestamp") or 0
    return Strike(
        feed=feed,
        underlying=underlying,
        strike=float(strike),
        expiry=float(row.get("expiry") or 0) / 1000.0,
        kind=str(row.get("optionType") or info.get("option_type") or "").lower(),
        open_interest=float(oi),
        gamma=float(greeks.get("gamma") or info.get("gamma") or 0.0),
        mark_iv=float(info.get("mark_iv") or 0.0),
        spot=spot,
        time=float(stamp) / 1000.0 if stamp else 0.0,
    )


async def chain(exchange: Any, feeds: dict[str, str]) -> list[Strike]:
    """Every near-the-money strike Deribit has open interest at.

    `feeds` maps an underlying - "BTC" - to the feed name this desk calls it.
    One call per underlying rather than per strike: `fetchOptionChain` returns
    the board, and asking strike by strike would be several hundred requests
    for one number.
    """
    if not getattr(exchange, "has", {}).get("fetchOptionChain"):
        log.debug("prices: %s has no option chain", VENUE)
        return []
    out: list[Strike] = []
    for underlying, feed in feeds.items():
        try:
            rows = await exchange.fetch_option_chain(underlying)
        except Exception as exc:
            log.debug("prices: %s option chain for %s failed: %s", VENUE, underlying, exc)
            continue
        board = rows.values() if isinstance(rows, dict) else rows
        spot = _spot_of(board)
        for row in board:
            if not isinstance(row, dict):
                continue
            got = _strike_from(row, feed, underlying, spot)
            if got is not None:
                out.append(got)
    return out


def _spot_of(board: Any) -> float:
    """The underlying price, from whichever row published it.

    Taken from the board rather than fetched separately so the strikes and the
    spot they are measured against come from one moment. Two calls would put
    the moneyness of a fast-moving underlying a few seconds out, which is the
    kind of small wrongness that survives review.
    """
    for row in board:
        if not isinstance(row, dict):
            continue
        info = row.get("info") if isinstance(row.get("info"), dict) else {}
        for key in ("underlying_price", "index_price"):
            got = info.get(key)
            if isinstance(got, int | float) and got:
                return float(got)
    return 0.0


@dataclass(frozen=True, slots=True)
class Profile:
    """The gamma standing at each strike for one underlying, and where it flips.

    A **profile**, not a number. The single "gamma exposure" figure everyone
    quotes is a sum over a distribution, and the distribution is the part with
    information in it: where the gamma is concentrated says which prices have
    hedging flow waiting at them, and a total says only how much there is.
    """

    feed: str
    spot: float
    by_strike: dict[float, float]
    time: float = 0.0

    @property
    def total(self) -> float:
        return sum(self.by_strike.values())

    @property
    def peak(self) -> float:
        """The strike carrying the most gamma - the price hedging flow clusters at."""
        return max(self.by_strike, key=lambda k: self.by_strike[k], default=0.0)

    def flip(self) -> float | None:
        """Where the running total crosses zero, walking strikes upward.

        The "gamma flip" - below it dealers are said to amplify moves and above
        it to damp them, **under whatever sign convention the caller applied**.
        None when the total never changes sign, which is the common case and
        should read as "there is no flip" rather than as a price.
        """
        running = 0.0
        previous: float | None = None
        for strike in sorted(self.by_strike):
            step = running + self.by_strike[strike]
            if previous is not None and (running < 0 <= step or running > 0 >= step):
                return strike
            running, previous = step, strike
        return None


def profile(strikes: list[Strike], *, dealers_short_calls: bool = True) -> list[Profile]:
    """Signed gamma per strike, per feed, under a stated assumption.

    The signing happens **here and only here**, so a reader following the value
    back reaches `dealer_sign` and its docstring rather than an unexplained
    minus sign in a sum.
    """
    grouped: dict[str, dict[float, float]] = {}
    spots: dict[str, float] = {}
    when: dict[str, float] = {}
    for one in strikes:
        if not math.isfinite(one.notional_gamma) or not one.gamma:
            continue
        sign = dealer_sign(one.kind, dealers_short_calls=dealers_short_calls)
        book = grouped.setdefault(one.feed, {})
        book[one.strike] = book.get(one.strike, 0.0) + sign * one.notional_gamma
        spots.setdefault(one.feed, one.spot)
        when[one.feed] = max(when.get(one.feed, 0.0), one.time)
    return [
        Profile(feed=feed, spot=spots.get(feed, 0.0), by_strike=book, time=when.get(feed, 0.0))
        for feed, book in grouped.items()
    ]
