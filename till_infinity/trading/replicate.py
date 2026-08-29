"""One decision, several accounts.

The mode is **copy**: the strategy decides once and the position is replicated
onto every configured terminal. `docs/todo.md` §6i sets out why this and the
other mode - *split*, one book across several terminals - are not variations of
each other, and why several questions here have opposite correct answers
depending on which is meant. This module implements copy only, and says so
where the difference bites.

## Risk is replicated. Lots are not.

The correctness point everything else is downstream of. A 0.05-lot trade sized
for a 10,000-unit account is a quarter percent of it; the same 0.05 lots on a
2,000-unit account is one and a quarter percent - **five times** the risk the
plan authorised, on the account least able to carry it.

So what travels is the decision and its price levels. Every follower re-runs
`sizing.lots` against its own equity and its own symbol spec, and the volume is
computed there or the trade does not happen there. An account whose minimum lot
is more than its risk budget allows is refused rather than rounded up, which is
the same argument `min_stop_vol` makes in a different variable.

## Partial failure is the normal case

Account A fills and account B is refused - not enough margin, the instrument
not carried, a different filling mode, AutoTrading switched off on that
terminal. The resulting state is genuinely divergent, and the policy is chosen
rather than discovered: unwinding A to stay symmetric turns one broker's
problem into a realised loss on an account that did nothing wrong. So they are
allowed to diverge, and every outcome is recorded per account.

What must never happen is one decision with three fills being reported as one
trade. `Replication` therefore carries a result per account and no summary that
could be mistaken for a single fill.

## The magic base stays the same

Magic distinguishes our trades from a hand-placed one on that terminal, and
every account should mark them identically. The collision that matters is two
processes against *one* account, which is a different problem and still real -
and the one place where split mode's answer inverts.

## What is deliberately per-account

Symbol resolution, equity, exposure and risk limits. The same position on five
accounts is five accounts holding it against their own capital, not one
position sized five times; aggregating would refuse the replication that is the
entire point. A follower that hits its own daily halt stops copying while the
others carry on, which is correct and needs to be visible rather than silent.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from ..logging import get_logger
from . import symbols as sym
from .broker import Broker, BrokerError
from .config import Settings
from .models import Intent, Order, SymbolSpec
from .sizing import lots

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Copied:
    """What happened on one account. `ok` is the only field a caller must check."""

    account: str
    ok: bool
    detail: str = ""
    volume: float = 0.0
    ticket: int = 0

    def __str__(self) -> str:
        if self.ok:
            return f"{self.account}: {self.volume:g} lots (#{self.ticket})"
        return f"{self.account}: {self.detail}"


@dataclass(frozen=True, slots=True)
class Replication:
    """Every account's outcome for one decision.

    Deliberately a list rather than a count. One decision that filled on two
    accounts and was refused on a third is three facts, and any summary that
    reads as a single fill would be a lie about the position actually held.
    """

    results: tuple[Copied, ...] = ()

    @property
    def filled(self) -> tuple[Copied, ...]:
        return tuple(r for r in self.results if r.ok)

    @property
    def refused(self) -> tuple[Copied, ...]:
        return tuple(r for r in self.results if not r.ok)

    @property
    def diverged(self) -> bool:
        """Whether the accounts now hold different things."""
        return bool(self.filled) and bool(self.refused)

    def __str__(self) -> str:
        if not self.results:
            return "no followers"
        return " · ".join(str(r) for r in self.results)


@dataclass
class Follower:
    """One extra terminal that copies the decisions taken on the primary."""

    name: str
    broker: Broker
    #: Its own equity, read from its own account rather than shared.
    equity: float = 0.0
    #: Its own resolved symbol map. An account that does not carry `Germany 40`
    #: simply never receives those trades - no new mechanism, just not sharing
    #: one resolved map.
    specs: dict[str, SymbolSpec] = field(default_factory=dict)
    ready: bool = False

    async def start(self, feeds: list[str]) -> None:
        """Attach, read this account's equity, resolve its own symbols."""
        account = await self.broker.connect()
        self.equity = account.equity or account.balance
        resolution = await sym.resolve(self.broker, feeds)
        self.specs = dict(resolution.found)
        self.ready = bool(self.specs)
        log.info(
            "trading: follower %s ready - %.2f %s, %d of %d instruments",
            self.name,
            self.equity,
            account.currency or "",
            len(self.specs),
            len(feeds),
        )

    async def copy(
        self,
        intent: Intent,
        *,
        risk_fraction: float,
        magic: int,
        by: str = "",
        deviation: int = 20,
        **sizing: float,
    ) -> Copied:
        """Take the same decision on this account, at this account's size.

        `magic` is passed in rather than read off the intent because it is
        derived from the strategy name at send time, and it is the **same**
        number the primary stamps - see the module docstring.
        """
        if not self.ready:
            return Copied(self.name, False, "follower never started")
        spec = self.specs.get(intent.feed)
        if spec is None:
            return Copied(self.name, False, f"{intent.feed} is not carried on this account")

        distance = abs(intent.entry - intent.stop)
        if distance <= 0:
            return Copied(self.name, False, "no stop distance to size against")

        # Re-derived here, never copied. See the module docstring.
        sized = lots(
            spec,
            equity=self.equity,
            risk_fraction=risk_fraction,
            stop_distance=distance,
            **sizing,
        )
        if not sized.ok:
            return Copied(self.name, False, sized.reason)

        order = Order(
            symbol=spec.symbol,
            side=intent.side,
            volume=sized.volume,
            stop=intent.stop,
            target=intent.target,
            comment=f"till {by or 'scalp'}"[:31],
            # The same base as the primary: magic marks these as ours on that
            # terminal, and every account should mark them identically.
            magic=magic,
            deviation=deviation,
        )
        try:
            result = await self.broker.send(order)
        except BrokerError as exc:
            return Copied(self.name, False, str(exc))
        if not result.ok:
            return Copied(self.name, False, str(result))
        return Copied(self.name, True, volume=sized.volume, ticket=result.ticket)


def from_settings(settings: Settings) -> Replicator:
    """Build the followers named in `TRADING_FOLLOWERS`.

    Each entry is `name=url` or `name=url|api_key`. A malformed one is dropped
    with a warning rather than raising: a typo in a follower must not stop the
    primary account trading, which is the account the decision was made for.
    """
    from .broker import build as build_broker

    made: list[Follower] = []
    for entry in settings.followers:
        name, _, rest = entry.partition("=")
        url, _, key = rest.partition("|")
        if not name.strip() or not url.strip():
            log.warning("trading: follower %r is not name=url[|key] - skipped", entry)
            continue
        theirs = replace(settings, url=url.strip(), api_key=key.strip() or settings.api_key)
        made.append(Follower(name=name.strip(), broker=build_broker(theirs)))
    return Replicator(made)


@dataclass
class Replicator:
    """Every follower, and the fan-out across them."""

    followers: list[Follower] = field(default_factory=list)

    @property
    def live(self) -> list[Follower]:
        return [f for f in self.followers if f.ready]

    async def start(self, feeds: list[str]) -> None:
        """Bring up every follower. One that will not start is dropped, loudly.

        A follower that cannot attach must not stop the primary trading: the
        decision is still good and the account it was decided for is still
        reachable. It is logged as an error rather than raised.
        """
        for follower in self.followers:
            try:
                await follower.start(feeds)
            except Exception as exc:  # a broker raises a family of these
                log.error("trading: follower %s will not start: %s", follower.name, exc)

    async def copy(
        self, intent: Intent, *, risk_fraction: float, magic: int, by: str = "", **sizing: float
    ) -> Replication:
        """Replicate one decision. Never raises; every outcome is a result."""
        out: list[Copied] = []
        for follower in self.live:
            try:
                out.append(
                    await follower.copy(
                        intent, risk_fraction=risk_fraction, magic=magic, by=by, **sizing
                    )
                )
            except Exception as exc:  # nothing here may break the primary
                out.append(Copied(follower.name, False, str(exc)))
        made = Replication(tuple(out))
        if made.results:
            if made.diverged:
                log.warning("trading: accounts diverged on %s - %s", intent.title, made)
            else:
                log.info("trading: copied %s - %s", intent.title, made)
        return made
