"""When each market shuts, learned from its bars and published for every desk.

**`sessions.py` solved this and nothing called it.** That module learns an
instrument's trading week from where its bars are, exposes
`closes_in(symbol)`, and opens by describing the exact case this actor exists
to cover: *"a position opened at 20:52 on a Friday cannot be closed until
Sunday night, and `max_hold_multiple` does not save it because the hold clock
keeps running while the market does not."* It had **no importer anywhere**, and
`Settings.session_margin` had no reader. This is the producer they were missing.

## Why an actor and not a desk

A desk could learn its own symbol from the bars it sees, and it would not be
enough twice over:

* **It cannot see a week.** A desk requests `warm_bars_request` bars at start -
  250 at 15m is 2.6 days - so a desk that started on a Monday has never
  observed a Friday close and `closes_in` would answer `None` for the one
  question this is for.
* **It would not survive a deploy.** The schedule would live on the strategy
  instance, and every restart drops it. There were several restarts on
  2026-11-20 alone.

So the history is fetched once, per symbol, over a span long enough to contain
several Fridays, and the answer is published on a timer like `VOLATILE` is.

## What it publishes, and what a reader must not infer

`topics.SESSIONS`, every `every` seconds:

    {"known": 12, "always": 3, "closes_in": {"EURUSD": 4380.0, "BTCUSD": None}}

**`None` means "do not act", and it means two different things.** Either the
instrument never closes - BTCUSD and the Deriv synthetics trade continuously,
so `Schedule.always` is true and there is no close to prepare for - or too
little of its week has been seen to judge. A reader that treated an unknown
schedule as "closing now" would flatten the book on a failed fetch, and one
that treated it as "never closes" would carry a position through a weekend it
could not exit. Both readings are wrong, so the only safe action on `None` is
none, and the counts above are published so a reader can see which case it is
in aggregate.

**The schedule errs towards allowing**, as `sessions.py` says: a minute counts
as trading if it traded in *any* observed week, so a holiday or an outage
cannot carve a false closure. That means this is a filter for the large,
regular closures - the weekend, and the daily index break - and never a precise
calendar. `_shut_for` remains the backstop.

**Times are the broker's, which is UTC on this account.** A silent offset here
would put every weekend an hour or three out and nothing would look wrong.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from nautilus_trader.common.actor import Actor
from nautilus_trader.config import ActorConfig
from nautilus_trader.model.data import Bar, BarType

from ..utils import topics
from .sessions import Sessions
from .timeframes import seconds_of

#: How much history to fetch per symbol. **Three weeks, because one is not
#: enough.** A week of bars contains one Friday, and a single Friday that
#: happened to be a holiday would teach the wrong close for the whole quarter.
#: Three gives the union something to work with, and `sessions.py` asks for
#: "fifteen-minute bars over a few weeks" in as many words.
DEFAULT_WEEKS = 3.0

#: Seconds between publications. A trading calendar moves on the scale of
#: hours, so this is slow on purpose - but not so slow that the answer is
#: stale by more than a margin can absorb.
DEFAULT_EVERY = 60.0


class CalendarConfig(ActorConfig, frozen=True):
    """Which bar types to learn from, and how often to say what they taught."""

    bar_types: tuple[str, ...] = ()
    weeks: float = DEFAULT_WEEKS
    every: float = DEFAULT_EVERY


class SessionCalendar(Actor):
    """Learns each instrument's trading week and publishes the time to its close."""

    def __init__(self, config: CalendarConfig) -> None:
        super().__init__(config)
        self._cfg = config
        self._sessions = Sessions()
        #: Bar interval per bar type, so `learn` can be told what a bar covers.
        self._spans: dict[str, float] = {}
        self._published = 0

    def on_start(self) -> None:
        for raw in self._cfg.bar_types:
            bar_type = BarType.from_str(raw)
            self._spans[str(bar_type)] = float(seconds_of(bar_type) or 0.0)
            self.subscribe_bars(bar_type)
        if not self._cfg.bar_types:
            # **Said once, loudly.** A calendar with nothing to learn from
            # publishes `None` for every symbol for ever, and `None` means "do
            # not act" - so the weekend exit would be silently off while both
            # sides looked healthy. That shape has hidden a topic in this
            # repository four times.
            self.log.warning(
                "SessionCalendar has no bar types, so it can learn no schedule and "
                "every weekend check will read 'unknown' and do nothing. Set its "
                "bar types or do not register it."
            )
            return
        self._warm()
        self.clock.set_timer(
            name="session-calendar",
            interval=timedelta(seconds=max(30.0, self._cfg.every)),
            callback=lambda _event: self._publish(),
        )
        self.log.info(
            f"learning sessions from {len(self._cfg.bar_types)} bar type(s) over "
            f"{self._cfg.weeks:g} week(s), publishing every {self._cfg.every:.0f}s"
        )

    def _warm(self) -> None:
        """One history request per bar type, spanning `weeks`.

        **Never raises.** A calendar that cannot warm still learns from live
        bars - slowly, and a week late for the first Friday - and that is a
        worse answer rather than a reason not to start. The failure is logged
        at error because the weekend exit depends on it.
        """
        span = timedelta(seconds=self._cfg.weeks * 7 * 24 * 3600)
        start = self.clock.utc_now() - span
        for raw in self._cfg.bar_types:
            try:
                self.request_bars(BarType.from_str(raw), start=start)
            except Exception as exc:
                self.log.error(f"could not request session history for {raw}: {exc}")

    def on_historical_data(self, data: Any) -> None:
        """History arrives here rather than at `on_bar`, and both are folded."""
        if isinstance(data, Bar):
            self._learn(data)

    def on_bar(self, bar: Bar) -> None:
        self._learn(bar)

    def _learn(self, bar: Bar) -> None:
        """Fold one bar's minutes into its symbol's week.

        Keyed by the **broker's own symbol name** - `"Wall Street 30"`, not
        `us30` - because that is what a position carries and what `closes_in`
        will be asked about. `sessions.py` records that an adopted position has
        no usable feed name, "which is the bug that let a shut market read as
        trading for eight hours".
        """
        name = str(bar.bar_type)
        span = self._spans.get(name) or float(seconds_of(bar.bar_type) or 0.0)
        if span <= 0:
            return
        symbol = bar.bar_type.instrument_id.symbol.value
        # The bar's **open**, which is what `Schedule.add` spans forward from.
        # Nautilus stamps `ts_event` at the close, so the open is one span back;
        # using the close would shift every session forward by one bar and put
        # the Friday close an interval late - on the wrong side of it.
        self._sessions.learn(symbol, [bar.ts_event / 1e9 - span], span)

    def _publish(self) -> None:
        known = sum(1 for s in self._sessions.by_symbol.values() if s.known)
        always = sum(1 for s in self._sessions.by_symbol.values() if s.always)
        self._published += 1
        topics.publish(
            self,
            topics.SESSIONS,
            {
                "known": known,
                "always": always,
                "closes_in": {
                    symbol: self._sessions.closes_in(symbol) for symbol in self._sessions.by_symbol
                },
            },
        )
        if self._published == 1 or self._published % 60 == 0:
            self.log.info(
                f"sessions: {len(self._sessions.by_symbol)} symbol(s), {known} with a "
                f"week worth judging, {always} that never close"
            )
