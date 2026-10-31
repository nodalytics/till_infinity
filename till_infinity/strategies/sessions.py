"""When each instrument actually trades, learned from where its bars are.

The problem this solves is the other half of a shut market. `_shut_for` catches
one that has *already* closed, by noticing the broker has stopped quoting. It
cannot catch one about to close, and that is the case that costs money: a
position opened at 20:52 on a Friday cannot be closed until Sunday night, and
`max_hold_multiple` does not save it because the hold clock keeps running while
the market does not.

**The broker does not publish its hours.** MT5 carries session times behind
`symbol_info_session_quote`, and the bridge has no route for it - forty-seven
routes, none for sessions. `symbol_info` does have `session_open` and
`session_close`, which look promising and are not: they are the session's open
and close *prices*. Wall Street 30 reports `session_close: 53556.35`.

So the hours are learned from where bars exist, which is the same evidence by
a different road and needs no cooperation from the bridge. Fifteen-minute bars
over a few weeks give this, and it matches what the instrument visibly does:

    Wall Street 30   Mon-Thu 00:00-21:00, 22:00-24:00   Fri to 20:45
    Australia 200    same shape                          Fri to 21:00
    EURUSD           24h Mon-Thu                         Fri to 21:00
    BTCUSD           every day, all day

The 21:00-22:00 gap is the daily break a us30 position could not be closed
through, and Friday's 20:45 is seven minutes before the order the broker
refused with `Market closed`. Both were diagnosed from tick times first and
show up here independently.

**Times are UTC.** The bars arrive as ISO strings in the broker's server time,
which is UTC on this account: Wall Street 30's last Friday bar opens 20:45 and
its last tick was 20:44:58 UTC. Worth stating because a silent offset here
would put every session an hour or three out and nothing would look wrong.

**A minute is trading if it traded in any observed week.** The union, not the
intersection. A holiday, an outage, or a week that simply has not been fetched
would otherwise carve false closures into the schedule, and every one of those
would refuse a trade that should have been allowed. The union errs the other
way, towards allowing - Friday's close reads 21:00 rather than 20:45 for an
instrument that has done both - so this is a filter for the large, regular
closures it can see clearly, not a precise calendar. `_shut_for` remains the
backstop for everything it misses.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

#: Minutes in a week. The schedule is one bit per minute, which is 10,080 bits
#: per symbol - small enough that the clarity is worth more than the bytes.
WEEK = 7 * 24 * 60

#: How long to scan forward for a close before calling an instrument
#: continuously traded. Anything open this long has no close worth waiting for.
HORIZON = WEEK


def week_minute(when: float) -> int:
    """Minutes since Monday 00:00 UTC, wrapping at the week."""
    lt = time.gmtime(when)
    return (lt.tm_wday * 24 * 60 + lt.tm_hour * 60 + lt.tm_min) % WEEK


@dataclass
class Schedule:
    """One instrument's trading week, a minute at a time."""

    minutes: set[int] = field(default_factory=set)

    @property
    def known(self) -> bool:
        """Whether enough of the week has been seen to judge anything.

        A handful of bars would otherwise describe a market that trades for an
        hour on Tuesdays and refuse everything else. The threshold is a day's
        worth of minutes, well under the ~7,000 a genuine index week has and
        well over anything a failed fetch produces.
        """
        return len(self.minutes) >= 24 * 60

    @property
    def always(self) -> bool:
        """Whether this instrument never closes, like BTCUSD."""
        return len(self.minutes) >= WEEK

    def add(self, start: float, span: float) -> None:
        """Record that trading happened over `span` seconds from `start`."""
        first = week_minute(start)
        for step in range(max(1, int(span // 60))):
            self.minutes.add((first + step) % WEEK)

    def trading_at(self, when: float) -> bool:
        return week_minute(when) in self.minutes

    def closes_in(self, when: float) -> float | None:
        """Seconds until this market shuts, or None if it does not.

        Returns 0.0 when it is already shut. Counted from the start of the
        current minute, so the answer is never more optimistic than the truth
        by more than the minute in progress.
        """
        if not self.known:
            return None
        if self.always:
            return None
        now = week_minute(when)
        if now not in self.minutes:
            return 0.0
        for ahead in range(1, HORIZON + 1):
            if (now + ahead) % WEEK not in self.minutes:
                return float(ahead * 60)
        return None


@dataclass
class Sessions:
    """Every instrument's trading week.

    Symbols are keyed exactly as the broker names them - `"Wall Street 30"`,
    not `us30` - because that is what a position carries and what the bars are
    fetched against. An adopted position has no usable feed name, which is the
    bug that let a shut market read as trading for eight hours.
    """

    by_symbol: dict[str, Schedule] = field(default_factory=dict)

    def learn(self, symbol: str, times: list[float], span: float) -> Schedule:
        """Fold a symbol's bar open-times into its schedule.

        `span` is the bar interval in seconds: a 15-minute bar is evidence that
        all fifteen of its minutes traded, not just the one it opened on.
        """
        schedule = self.by_symbol.setdefault(symbol, Schedule())
        for at in times:
            if at > 0:
                schedule.add(at, span)
        return schedule

    def closes_in(self, symbol: str, when: float | None = None) -> float | None:
        schedule = self.by_symbol.get(symbol)
        if schedule is None:
            return None
        return schedule.closes_in(time.time() if when is None else when)

    def trading_at(self, symbol: str, when: float | None = None) -> bool | None:
        """Whether this instrument trades then, or None if we do not know."""
        schedule = self.by_symbol.get(symbol)
        if schedule is None or not schedule.known:
            return None
        return schedule.trading_at(time.time() if when is None else when)

    @property
    def learned(self) -> int:
        return sum(1 for s in self.by_symbol.values() if s.known)
