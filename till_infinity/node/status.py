"""What the node writes down about itself, so a probe reads the venue's word.

## Why a file at all

`Dockerfile`'s `HEALTHCHECK` used to run `till-infinity health`, and that
command had nothing to read - it now runs `python -m till_infinity.node.status`,
which reads this. The history in `lifecycle.py` says why it matters: three
deploys on 2026-10-09 were built, tagged, deployed, health-checked and
reported up **while running none of the code they claimed**, because every
check read our own side of the wire. One of them was then measured as having
no effect, which is what code that is not running looks like.

So a probe that answers from inside the process is worthless - it proves a
process is alive, which Docker already knew. What it has to read is the claim
`lifecycle.wait_until_up` produced, including which step it stalled on, and it
has to be able to tell a *stale* claim from a current one. Hence a file: the
node writes what it has established and when, and `health` refuses anything
older than `STALE_AFTER`.

## Why an Actor writes it

Because the node's clock is the only thing that knows the node is still
running. A thread would keep writing a cheerful file after the kernel had
stopped dispatching, which is the failure this module exists to prevent
wearing a different hat - and `Actor` gets `clock.set_timer` for free, so the
heartbeat stops exactly when the component does.

## What "healthy" means here

Up, fresh, **and trading something**. A node with no strategies connects,
reconciles, reports up and trades nothing, which is the shape `live.build`
already refuses at construction - this is the same refusal where a monitoring
system can see it. Armed is reported and **not** required: an unarmed node is
a deliberate state (`TRADING_LIVE` unset puts the risk engine in `HALTED`),
and a probe that failed on it would make a dry run impossible.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from nautilus_trader.common.actor import Actor
from nautilus_trader.config import ActorConfig

from till_infinity.node import probe
from till_infinity.utils.topics import ALERTS, VENUE_TRADING, alert, publish

#: The reader lives in `probe`, which imports the standard library and nothing
#: else, because this module imports a Nautilus `Actor` and the `HEALTHCHECK`
#: was paying 1.6s of import time and about 1.2 cores a minute to read a JSON
#: file. Re-exported so `status.read` and `status.healthy` keep working.
DEFAULT_PATH = probe.DEFAULT_PATH
STALE_AFTER = probe.STALE_AFTER
read = probe.read
healthy = probe.healthy
main = probe.main

#: How often the node refreshes it.
HEARTBEAT = 30.0


def startup_alert(reading: dict[str, Any]) -> dict[str, Any] | None:
    """One alert when the node is **fully** up, or `None` while it is not.

    A free function for the reason `tally_reading` is one: the wording is the
    diagnostic, and `log` and `msgbus` are read-only on the Cython `Actor`, so
    the decision has to be testable on its own.

    **Why the desk announces itself.** On 2026-11-08, hours before the first
    fill this desk ever expected, the notifier tally read `0 sent, 1 dropped`
    and nothing had been delivered on that deploy. Whether the Telegram token
    was even valid was unknown, and the first message ever attempted would
    have been the fill alert. Announcing on start makes every deploy prove the
    path while somebody is watching, which is the only time a broken path is
    cheap to find.

    **`critical`, deliberately.** `Filter` bypasses the shape list and the
    hourly cap only for urgent alerts, and production sets `NOTIFY_SHAPES` to a
    list that does not contain `desk` - so at any other level this message
    would be dropped by the very filter it exists to test. A silent alarm path
    is an alarm condition.

    Fully up means the node is running, the venue has answered, and strategies
    are registered. A process that merely exists is what the retired
    `--version` healthcheck reported for three hours over a desk that could
    not trade.
    """
    if not reading.get("running"):
        return None
    if not reading.get("venue_connected"):
        return None
    strategies = int(reading.get("strategies") or 0)
    if strategies <= 0:
        return None
    armed = bool(reading.get("armed"))
    return alert(
        shape="desk",
        level="critical",
        source="desk",
        title=f"desk up: {strategies} strategies, {'armed' if armed else 'NOT armed'}",
        body=(
            f"venue connected, {strategies} strategies registered, "
            f"armed={armed}. This message also proves the alert path works - "
            f"if you are reading it, a fill will reach you too."
        ),
        strategies=str(strategies),
        armed=str(armed).lower(),
    )


class HeartbeatConfig(ActorConfig, frozen=True):
    """Where to write, and how often.

    Frozen `ActorConfig` like every other actor here, so it can be carried as
    an `ImportableActorConfig` - a `TradingNodeConfig` holds importable
    configs rather than instances, and an actor that can only be built by hand
    cannot go in one.
    """

    path: str = str(DEFAULT_PATH)
    seconds: float = HEARTBEAT
    #: How many strategies the node registered, **told to the actor because an
    #: `Actor` cannot see the trader.** It has `trader_id` and nothing else.
    #:
    #: The count used to come from `cache.strategy_ids()`, which is **empty
    #: until a strategy has an order**: measured, `trader.strategies()` reads 4
    #: where `cache.strategy_ids()` reads 0 on a node that has just built. So
    #: the healthcheck reported `0 strategies: the node is up and trading
    #: nothing` on every healthy fresh desk and marked the container unhealthy
    #: - a false alarm on the one check that is supposed to be trusted, and it
    #: fired within an hour of that check correctly catching a real outage.
    registered: int = 0


class Heartbeat(Actor):
    """Writes the node's own status on the node's own clock."""

    def __init__(self, config: HeartbeatConfig | None = None) -> None:
        config = config or HeartbeatConfig()
        super().__init__(config)
        self._cfg = config
        self._path = Path(config.path)
        self._wrote = 0
        self._failed = 0
        #: Whether the one-shot "desk up" alert has gone out. One per process:
        #: it exists to prove the alert path on a deploy, and a repeat every
        #: heartbeat would be the log flood this desk has already produced once.
        self._announced = False
        #: `None` means the venue has not said. Not `False`: "never asked" and
        #: "the terminal is refusing orders" are different facts and the file
        #: has to be able to say which.
        self._can_trade: bool | None = None
        self._can_trade_at: float | None = None
        self._can_trade_cause: str = ""

    def on_start(self) -> None:
        # **The venue's trading flag arrives on the bus, because an `Actor`
        # cannot read it.** This actor has the bus, the cache, the clock and
        # the portfolio and no transport; the execution client holds the
        # bridge. Subscribed before the first write so a flag published during
        # connect is not missed.
        self.msgbus.subscribe(VENUE_TRADING, self._venue_trading)
        # Written once immediately, so a probe in the start period sees
        # "starting" rather than nothing - the difference between a node that
        # is warming up and one that never began.
        self._write()
        self.clock.set_timer(
            name="till-status",
            interval=_interval(self._cfg.seconds),
            callback=lambda _event: self._write(),
        )

    def on_stop(self) -> None:
        # A last write on the way down, so the file says stopped rather than
        # going stale and reading as a crash. A clean stop and a kill are
        # different events and a deploy wants to tell them apart.
        self._write(running=False)

    def _write(self, running: bool = True) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            reading = self.reading(running=running)
            self._path.write_text(json.dumps(reading, indent=2))
            self._wrote += 1
            self._announce(reading)
        except OSError as exc:
            # Counted and said once per failure, never raised: a node must not
            # come down because it could not describe itself.
            self._failed += 1
            self.log.warning(f"status: could not write {self._path}: {exc}")

    def _announce(self, reading: dict[str, Any]) -> None:
        """Publish the startup alert the first time the node is fully up.

        After the write rather than before it, so the status file a person can
        read and the message they receive cannot disagree.
        """
        if self._announced:
            return
        payload = startup_alert(reading)
        if payload is None:
            return
        self._announced = True
        try:
            publish(self, ALERTS, payload)
        except Exception as exc:
            # A heartbeat that cannot announce must still beat: this writes the
            # status file the healthcheck reads, and failing here would take
            # the container down over a notification.
            self.log.warning(f"status: could not announce startup: {type(exc).__name__}: {exc}")

    def reading(self, running: bool = True) -> dict[str, Any]:
        """The claims, each with its source.

        `strategies` is the count the node registered, handed over at
        construction because an `Actor` cannot reach the trader. `venue` comes
        from whether an execution client reports connected - **the venue's word
        and not ours**, which is the whole argument of `lifecycle.py`.
        """
        # **`Cache` has no `exec_clients` method.** This read
        # `self.cache.exec_clients() if hasattr(...) else []`, so the guard
        # turned a missing method into an empty list, `any([])` into `False`,
        # and `venue_connected` into a value that was **permanently false** -
        # a check that could never pass whatever the venue was doing. The
        # container therefore reported `unhealthy` from the day this shipped,
        # which is the most expensive kind of broken check: one nobody trusts.
        #
        # An account is the right source and is still **the venue's word and
        # not ours**, which is `lifecycle.py`'s whole argument: the account
        # arrives from the execution client's own reply, which logs the
        # account and its equity on connect - so its presence in the cache
        # means the venue answered. No `hasattr`: if `accounts()` disappears,
        # this should
        # raise and be seen rather than silently read false forever.
        venue = False
        try:
            venue = any(
                getattr(found, "balance_total", None) is not None for found in self.cache.accounts()
            )
        except Exception as exc:  # the shape is the framework's, so say so
            self.log.warning(f"status: could not read accounts: {exc}")
            venue = False
        return {
            "at": time.time(),
            "running": running,
            "trader": str(self.trader_id),
            "venue_connected": venue,
            # What was registered, which is what "is this node running any
            # desks" means. `with_orders` is the cache's view and is reported
            # beside it rather than instead of it: "registered 12, none
            # trading yet" and "registered 0" are different problems and the
            # old reading could not tell them apart.
            "strategies": max(int(self._cfg.registered), len(self._strategy_ids())),
            "with_orders": len(self._strategy_ids()),
            "armed": self._armed(),
            # **Reported, and deliberately not part of the healthy verdict.**
            # `None` until the venue has said either way, so "not yet asked"
            # and "the venue is shut" stay different answers.
            #
            # A terminal with AutoTrading off cannot fill anything, and it is
            # also what every weekend looks like - so failing the container
            # healthcheck on it would mark a correctly idle desk unhealthy
            # every Saturday and get the check ignored, which is how the
            # `exec_clients` fault cost its whole value. This exists so a
            # person or an alert can see a desk that is up and unable to
            # trade, which on 2026-11-04 no signal showed.
            "can_trade": self._can_trade,
            "can_trade_at": self._can_trade_at,
            "can_trade_cause": self._can_trade_cause,
            "wrote": self._wrote,
            "write_failures": self._failed,
        }

    def _venue_trading(self, message: Any) -> None:
        """Remember whether the venue will take an order, and when it said so."""
        if not isinstance(message, dict) or "can_trade" not in message:
            return
        self._can_trade = bool(message["can_trade"])
        self._can_trade_at = time.time()
        self._can_trade_cause = str(message.get("cause") or "")

    def _strategy_ids(self) -> list[str]:
        try:
            return [str(found) for found in self.cache.strategy_ids()]
        except Exception:  # pragma: no cover
            return []

    def _armed(self) -> bool:
        """Is the risk engine letting orders through?

        Reported rather than required: `TRADING_LIVE` unset puts the engine in
        `HALTED` deliberately, and a probe that failed on it would make a dry
        run impossible.
        """
        from till_infinity.utils.env import flag

        return flag("TRADING_LIVE")


def _interval(seconds: float):
    """Seconds as the `timedelta` Nautilus's timer wants."""
    from datetime import timedelta

    return timedelta(seconds=max(1.0, float(seconds)))


if __name__ == "__main__":
    raise SystemExit(main())
