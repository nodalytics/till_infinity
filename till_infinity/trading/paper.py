"""A book with no broker behind it.

The default, and not only as a convenience. Three quite different situations
land here: a laptop with no terminal, a server whose bridge is down, and a
deliberate dry run before arming. All three want the same thing - the whole
path exercised, orders sized, stops placed, outcomes journalled - with nothing
reaching an account.

**Fills are against the live quote, not the mid.** A paper book that fills at
the mid reports an edge the spread would have eaten, which on a scalp is most
of it. Quotes arrive from the bus, the same ones `structures` reads, so the
simulated fill is the price a market order would actually have paid at that
instant. Where no quote has arrived yet, the configured spread is applied to
the level price and the fill is marked as synthetic rather than quietly passed
off as real.

**Stops and targets are checked on every tick.** A real terminal holds them
server-side; here the book has to do it, and doing it on the quote stream
rather than on a timer is what stops a 20-second poll from turning a stop into
a gap.

The money arithmetic is exact for USD-quoted instruments - gold, BTC, and the
majors quoted against the dollar - because one lot moving one tick is then
`contract_size * tick_size` dollars. For USDJPY and the cross-quoted rest it is
an approximation, and deliberately not corrected: paper exists to exercise the
path, and any real question about position size should be asked of a terminal
that knows the conversion.
"""

from __future__ import annotations

import time
from typing import ClassVar

from ..logging import get_logger
from .broker import Broker, RejectedError
from .config import Settings, feed_for
from .models import Account, Order, OrderResult, Position, Side, SymbolSpec, Tick

log = get_logger(__name__)

#: Contract size and digits per instrument, for the simulated specs. Chosen to
#: match the common retail conventions rather than any one broker: 100 ounces
#: of gold, one coin of BTC, 100,000 units of a currency pair.
PAPER_SPECS: dict[str, tuple[float, int]] = {
    "gold": (100.0, 2),
    "btc": (1.0, 2),
    "eth": (1.0, 2),
    "sol": (1.0, 3),
    "us100": (1.0, 2),
    "spx500": (1.0, 2),
    "usdjpy": (100_000.0, 3),
}
#: Everything else is a currency pair.
DEFAULT_SPEC = (100_000.0, 5)


class PaperBroker(Broker):
    """Simulated fills against real quotes."""

    name: ClassVar[str] = "paper"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._equity = settings.paper_equity
        self._balance = settings.paper_equity
        self._ticks: dict[str, Tick] = {}
        self._positions: dict[int, Position] = {}
        self._next = 1
        #: Positions the book closed on its own, waiting to be reported. The
        #: service drains this; a real terminal's server-side stop is noticed
        #: the same way, by the position having gone.
        self._closed: list[tuple[Position, float, str]] = []

    # ------------------------------------------------------------- lifecycle

    async def connect(self) -> Account:
        log.info("trading: paper book opened with %.2f", self._equity)
        return await self.account()

    async def healthy(self) -> bool:
        return True

    # ----------------------------------------------------------------- reads

    async def account(self) -> Account:
        return Account(
            login=0,
            currency="USD",
            balance=self._balance,
            equity=self._equity + self._floating(),
            margin_free=self._equity,
            leverage=0,
        )

    async def spec(self, symbol: str) -> SymbolSpec | None:
        """Every symbol exists on paper - that is the point of paper.

        Availability is a question about a broker, and there is no broker here.
        Answering None would make a dry run refuse the very instruments it is
        meant to be dry-running.
        """
        contract, digits = PAPER_SPECS.get(self._feed_of(symbol), DEFAULT_SPEC)
        tick_size = 10.0**-digits
        return SymbolSpec(
            symbol=symbol,
            digits=digits,
            point=tick_size,
            tick_size=tick_size,
            tick_value=contract * tick_size,
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
            contract_size=contract,
            tradable=True,
        )

    async def quote(self, symbol: str) -> Tick | None:
        return self._ticks.get(symbol)

    async def positions(self) -> list[Position]:
        return [self._mark(p) for p in self._positions.values()]

    # ---------------------------------------------------------------- writes

    async def send(self, order: Order) -> OrderResult:
        tick = self._ticks.get(order.symbol)
        if tick is None:
            raise RejectedError(f"paper: no quote for {order.symbol} yet")
        price = tick.entry(order.side)
        ticket = self._next
        self._next += 1
        self._positions[ticket] = Position(
            ticket=ticket,
            symbol=order.symbol,
            side=order.side,
            volume=order.volume,
            price_open=price,
            stop=order.stop,
            target=order.target,
            price_current=price,
            opened=time.time(),
            comment=order.comment,
            magic=order.magic,
        )
        return OrderResult(
            ok=True, ticket=ticket, price=price, volume=order.volume, comment="paper"
        )

    async def close_position(self, ticket: int, volume: float = 0.0) -> OrderResult:
        position = self._positions.pop(ticket, None)
        if position is None:
            raise RejectedError(f"paper: no position {ticket}")
        tick = self._ticks.get(position.symbol)
        price = tick.exit(position.side) if tick else position.price_current
        self._settle(position, price)
        return OrderResult(ok=True, ticket=ticket, price=price, volume=volume or position.volume)

    async def modify(self, ticket: int, stop: float, target: float = 0.0) -> OrderResult:
        position = self._positions.get(ticket)
        if position is None:
            raise RejectedError(f"paper: no position {ticket}")
        from dataclasses import replace

        self._positions[ticket] = replace(position, stop=stop, target=target or position.target)
        return OrderResult(ok=True, ticket=ticket, price=position.price_current)

    # ------------------------------------------------------------ the market

    def observe(self, tick: Tick) -> list[tuple[Position, float, str]]:
        """Take one quote in; return anything it closed.

        Stops are checked before targets. When a single tick spans both - a bar
        that traded through the stop and the target - assuming the good one
        filled first is how a paper book flatters itself, so the loss wins.
        """
        self._ticks[tick.symbol] = tick
        closed: list[tuple[Position, float, str]] = []
        for ticket, position in list(self._positions.items()):
            if position.symbol != tick.symbol:
                continue
            price = tick.exit(position.side)
            hit = self._hit(position, price)
            if hit is None:
                self._positions[ticket] = self._mark(position, price)
                continue
            del self._positions[ticket]
            level = position.stop if hit == "stop" else position.target
            self._settle(position, level)
            closed.append((position, level, hit))
        self._closed.extend(closed)
        return closed

    def drain_closed(self) -> list[tuple[Position, float, str]]:
        """Everything the book closed since this was last called."""
        out, self._closed = self._closed, []
        return out

    # ---------------------------------------------------------------- inside

    @staticmethod
    def _hit(position: Position, price: float) -> str | None:
        down = position.side is Side.BUY
        if position.stop and ((price <= position.stop) if down else (price >= position.stop)):
            return "stop"
        if position.target and ((price >= position.target) if down else (price <= position.target)):
            return "target"
        return None

    def _money(self, position: Position, price: float) -> float:
        contract, _ = PAPER_SPECS.get(self._feed_of(position.symbol), DEFAULT_SPEC)
        return (price - position.price_open) * position.side.sign * position.volume * contract

    def _mark(self, position: Position, price: float | None = None) -> Position:
        from dataclasses import replace

        tick = self._ticks.get(position.symbol)
        if price is None:
            price = tick.exit(position.side) if tick else position.price_current
        return replace(position, price_current=price, profit=self._money(position, price))

    def _settle(self, position: Position, price: float) -> None:
        profit = self._money(position, price)
        self._balance += profit
        self._equity += profit
        log.info(
            "paper: closed #%d %s %s @ %.5g for %+.2f",
            position.ticket,
            position.side,
            position.symbol,
            price,
            profit,
        )

    def _floating(self) -> float:
        return sum(self._mark(p).profit for p in self._positions.values())

    def _feed_of(self, symbol: str) -> str:
        """Which instrument a broker symbol belongs to, for the spec table.

        The resolved map when there is one - it is exact, and covers a symbol
        named in a way `feed_for` cannot guess - and the name otherwise. The
        fallback is not an optimisation: `spec` is called *during* resolution,
        when the map is still empty. See `config.feed_for`.
        """
        for feed, resolved in self.settings.resolved.items():
            if resolved == symbol:
                return feed
        return feed_for(symbol) or symbol.lower()
