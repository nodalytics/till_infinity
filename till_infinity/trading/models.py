"""What a trade is, on the way there and on the way back.

These types are deliberately broker-agnostic. MT5 speaks in tickets, retcodes,
lots and points; a `Position` here does not, because the same scalper has to
read correctly against a paper book that has no tickets at all. The translation
happens once, at the edge, in each broker backend.

One type is worth reading before the rest. `Refusal` is a first-class result,
not an error path: the journal's own docstring makes the case - "a model
trained only on the times we acted learns nothing about when not to" - and a
scalper declines far more often than it fires. Returning `None` for "no trade"
would throw away the reason, which is the part worth keeping.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

_now = time.time


class Side(StrEnum):
    """Which way. `direction` on a signal is "up"/"down"; this is buy/sell."""

    BUY = "buy"
    SELL = "sell"

    @classmethod
    def from_direction(cls, direction: str) -> Side | None:
        """Map a signal's direction onto a side, or None if it claims neither.

        A signal with an empty direction is not a weak buy - it is a reading
        that declined to call one, and turning that into a trade would invent
        a conviction nobody had.
        """
        return {"up": cls.BUY, "down": cls.SELL}.get(direction.strip().lower())

    @property
    def sign(self) -> int:
        """+1 for a buy, -1 for a sell. Every price arithmetic below uses it."""
        return 1 if self is Side.BUY else -1

    @property
    def opposite(self) -> Side:
        return Side.SELL if self is Side.BUY else Side.BUY


@dataclass(frozen=True, slots=True)
class SymbolSpec:
    """What the broker will let us do with one instrument.

    Every field here is a reason an order can be rejected after it has already
    been decided, which is why they are fetched once at start-up rather than
    discovered at the moment of firing. `volume_step` in particular: a size of
    0.037 lots is a perfectly good answer from the sizing arithmetic and an
    instant rejection from the terminal.
    """

    symbol: str
    digits: int = 5
    point: float = 0.00001
    tick_size: float = 0.00001
    #: Money made by one lot moving one tick, in the account currency. The
    #: bridge between "how far is my stop" and "how much does it cost".
    tick_value: float = 1.0
    volume_min: float = 0.01
    volume_max: float = 100.0
    volume_step: float = 0.01
    contract_size: float = 0.0
    #: Minimum distance from price for a stop or target, in points. Zero means
    #: the broker did not say, not that anything goes.
    stops_level: float = 0.0
    tradable: bool = True

    @property
    def min_stop_distance(self) -> float:
        """`stops_level` as a price distance, which is how it gets compared."""
        return self.stops_level * self.point

    def round_volume(self, volume: float) -> float:
        """Snap to the broker's lot grid, **downwards**.

        Down rather than nearest, because rounding up is the one direction that
        can take a sized-to-the-limit position over the risk it was sized for.
        A trade one step smaller than intended is a rounding error; one step
        larger is a breached limit.
        """
        if self.volume_step <= 0:
            return volume
        steps = int(volume / self.volume_step + 1e-9)
        snapped = steps * self.volume_step
        # The step is a decimal like 0.01 that binary floats cannot hold, so
        # multiplying it back out leaves 0.30000000000000004. Terminals reject
        # that; the decimal places of the step itself are the right precision.
        places = max(0, len(f"{self.volume_step:.8f}".rstrip("0").partition(".")[2]))
        return round(min(max(snapped, 0.0), self.volume_max), places)

    def round_price(self, price: float) -> float:
        return round(price, self.digits)


@dataclass(frozen=True, slots=True)
class Tick:
    """One two-sided quote. The spread is the cost of the round trip."""

    symbol: str
    bid: float
    ask: float
    time: float = field(default_factory=_now)

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        return max(0.0, self.ask - self.bid)

    @property
    def spread_bps(self) -> float:
        mid = self.mid
        return (self.spread / mid) * 10_000 if mid else 0.0

    def entry(self, side: Side) -> float:
        """What a market order of this side actually pays.

        Buying lifts the ask and selling hits the bid - never the mid. Sizing a
        scalp off the mid understates the stop distance by half the spread on
        entry and again on exit, which on a target of a few volatility units is
        not a rounding error.
        """
        return self.ask if side is Side.BUY else self.bid

    def exit(self, side: Side) -> float:
        """What closing that side receives."""
        return self.bid if side is Side.BUY else self.ask


@dataclass(frozen=True, slots=True)
class Account:
    """The balance the risk limits are measured against."""

    login: int = 0
    currency: str = "USD"
    balance: float = 0.0
    equity: float = 0.0
    margin_free: float = 0.0
    leverage: int = 0

    def __str__(self) -> str:
        return f"#{self.login} {self.equity:,.2f} {self.currency} (balance {self.balance:,.2f})"


@dataclass(frozen=True, slots=True)
class Intent:
    """A trade we want to make, with the reasoning still attached.

    Kept whole rather than reduced to an order because the journal wants the
    reasoning and the notification wants the story. By the time this is an
    `Order` it is four numbers and a symbol, and the question "why did it think
    so" is unanswerable.
    """

    feed: str
    symbol: str
    side: Side
    volume: float
    #: The quote this was sized from, not the fill - the fill is on the result.
    entry: float
    stop: float
    target: float
    reason: str = ""
    interval: str = ""
    confluence: tuple[str, ...] = ()
    #: The signal's features, copied in. See `journal.decide` on why context is
    #: copied rather than pointed at.
    features: dict[str, float] = field(default_factory=dict)
    risk_money: float = 0.0
    #: Seconds this trade may stay open, as its strategy asked. Zero defers to
    #: the configured default. Carried on the intent rather than looked up from
    #: the strategy later, because by the time a position is being timed out
    #: the strategy that opened it is one of several and nothing links them.
    hold: float = 0.0
    time: float = field(default_factory=_now)

    @property
    def risk(self) -> float:
        """Entry to stop, as a price distance."""
        return abs(self.entry - self.stop)

    @property
    def reward(self) -> float:
        return abs(self.target - self.entry)

    @property
    def reward_to_risk(self) -> float:
        return self.reward / self.risk if self.risk else 0.0

    @property
    def title(self) -> str:
        return f"{self.side} {self.volume:g} {self.symbol} @ {self.entry:.5g}"

    def to_context(self) -> dict[str, Any]:
        """The numbers as they read at the moment of deciding."""
        return {
            "feed": self.feed,
            "symbol": self.symbol,
            "side": str(self.side),
            "volume": self.volume,
            "entry": self.entry,
            "stop": self.stop,
            "target": self.target,
            "risk_price": round(self.risk, 8),
            "reward_to_risk": round(self.reward_to_risk, 3),
            "risk_money": round(self.risk_money, 2),
            "interval": self.interval,
            "confluence": "+".join(self.confluence),
            **{k: round(v, 6) for k, v in self.features.items()},
        }


@dataclass(frozen=True, slots=True)
class Refusal:
    """Why we did not trade. Recorded, not raised.

    `gate` is the short machine-readable name of what stopped it - "spread",
    "daily_loss", "already_open" - so declines can be counted per gate over a
    week without parsing prose. A gate that never fires is a gate that is not
    doing anything, and one that fires constantly is mis-set; neither is
    visible without the tally.
    """

    gate: str
    detail: str
    feed: str = ""
    time: float = field(default_factory=_now)

    def __str__(self) -> str:
        return f"{self.feed or '-'}: {self.detail} [{self.gate}]"


#: What `consider` answers with. A trade, or the reason there is not one.
Verdict = Intent | Refusal


#: Symbols for the account currencies a retail terminal actually issues. Any
#: code not here is written out beside the number instead - `12.56 SGD` reads
#: fine, and a guessed symbol on the wrong currency does not.
CURRENCY_SYMBOLS: dict[str, str] = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "JPY": "¥",
    "AUD": "A$",
    "CAD": "C$",
    "NZD": "NZ$",
    "CHF": "CHF ",
}


def money(amount: float, currency: str = "", *, signed: bool = True) -> str:
    """An amount with its currency attached.

    `$` for dollars, `12.56 SGD` for anything without a well-known symbol - an
    unrecognised code is written out rather than guessed at, because a wrong
    symbol is worse than a verbose one. The sign sits outside the symbol:
    `+$12.56`, not `$+12.56`.

    Here rather than on `Trader` because more than one thing prints money. The
    running day total in `risk.Guard.summary` did not, and read as a bare
    number beside a title that had the symbol - which is the sort of
    inconsistency that makes a reader doubt both.
    """
    symbol = CURRENCY_SYMBOLS.get(currency.upper(), "")
    text = f"{amount:+,.2f}" if signed else f"{amount:,.2f}"
    if symbol:
        return f"{text[0]}{symbol}{text[1:]}" if signed else f"{symbol}{text}"
    return f"{text} {currency}".rstrip() if currency else text


@dataclass(frozen=True, slots=True)
class Order:
    """An intent reduced to what a terminal needs."""

    symbol: str
    side: Side
    volume: float
    stop: float
    target: float = 0.0
    comment: str = ""
    magic: int = 0
    deviation: int = 20


@dataclass(frozen=True, slots=True)
class OrderResult:
    """What came back. `ok` is the only field a caller must check."""

    ok: bool
    ticket: int = 0
    price: float = 0.0
    volume: float = 0.0
    retcode: int = 0
    comment: str = ""

    def __str__(self) -> str:
        if self.ok:
            return f"#{self.ticket} filled {self.volume:g} @ {self.price:.5g}"
        return f"rejected: {self.comment or self.retcode}"


@dataclass(frozen=True, slots=True)
class Position:
    """One open trade, as the broker currently sees it."""

    ticket: int
    symbol: str
    side: Side
    volume: float
    price_open: float
    stop: float = 0.0
    target: float = 0.0
    price_current: float = 0.0
    profit: float = 0.0
    opened: float = 0.0
    comment: str = ""
    magic: int = 0

    @property
    def age(self) -> float:
        return max(0.0, _now() - self.opened) if self.opened else 0.0

    def __str__(self) -> str:
        return (
            f"#{self.ticket} {self.side} {self.volume:g} {self.symbol} "
            f"@ {self.price_open:.5g} ({self.profit:+.2f})"
        )
