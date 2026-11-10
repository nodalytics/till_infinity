"""Warming a desk from history, and when a warm signal is still actionable.

**A cold detector cannot produce a signal for days, and that is measured.**
`structure.py` replayed cold on production M15 bars put its first BOS at bar
508-939 - five to ten days of continuous bars after every deploy - and on
2026-11-07 a desk 7.8 hours old had zero confirmed swings on all 32 feeds.
`zones.py` is worse placed: `BjorgumLevels` needs `left + right` bars for a
pivot and an ATR window on top, so the `script` preset cannot nominate a zone
until roughly 50 bars have closed, which is **twelve hours of 15m** during
which a desk that cannot possibly fire is indistinguishable from one choosing
not to.

So every rule with a stateful detector wants its own history on start, and
three of them were about to grow their own copy of the same request. This is
the one copy.

## The part that is a judgement, not plumbing

**A warm signal is not automatically stale.** The original rule was that warm
events never act, and its reason was sound as far as it went: "a BOS on a bar
hours old names a price that has gone". But a break confirmed on the *last*
bar of the requested history is a break that happened minutes ago, and
discarding it means a deploy throws away the one setup it can see and waits for
the next - which on a 15m rule with a 50-bar warm-up is a self-inflicted blind
spot, not caution.

`fresh` draws that line **by time and never by position**, because Nautilus
delivers a `request_bars` response **one bar per call** rather than as a batch,
so a handler cannot know while processing a bar whether another is coming. Age
against the strategy's own clock is knowable on the first call and is the
honest definition anyway: what makes a signal stale is that its price has
moved on, which is a question about elapsed time.

**The entry price is never the historical one.** Every rule here prices its
entry from `self._tick()` - the live quote - and takes only the *stop* from the
signal's own geometry. That is what makes forwarding a fresh warm event safe:
the trade is placed at the market now, and the historical bar contributes the
level, not the price.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from nautilus_trader.model.data import Bar

from .timeframes import seconds_of

#: Nanoseconds in a second. `Bar.ts_event` is the bar's **close**, in ns.
NANOS = 1_000_000_000.0

#: Bars of history to ask for when a profile names no number of its own. Zero,
#: because warming is a per-rule decision: a rule whose detector is stateless
#: gains nothing and would pay for the request.
DEFAULT_WARM_BARS = 0

#: How recently a warm signal must have been confirmed to be forwarded, in
#: bars of the desk's own interval. One, so only a break on the final bar of
#: history can act - the bar that is indistinguishable from one that would have
#: arrived live a moment later. Raising it trades promptness for staleness and
#: is a sweepable parameter, not a constant anyone measured.
DEFAULT_FRESH_BARS = 1


def bar_seconds(bar_type: Any) -> float:
    """How long one bar of `bar_type` covers. `timeframes.seconds_of`.

    **The version this replaces read `str(spec.aggregation)` and never
    matched.** `BarSpecification.aggregation` is an **int** - 12 for MINUTE, 13
    for HOUR, 14 for DAY - so `"MINUTE" in str(spec.aggregation)` compared
    against `"12"`, every branch missed, and the fallback returned
    `step * 900`. On M15 that is **13,500 seconds for a 900-second bar**, a
    factor of fifteen, and it had been that way unnoticed because the only
    consumer was a warm request's *window*: asking for 156 days instead of 10
    and taking the same `limit` of bars looks identical from outside.

    It stops being harmless the moment a freshness window is measured in bar
    spans, which is what `fresh` does - a 15x span would call a bar 3.75 hours
    old "fresh" and reintroduce exactly the staleness the old discard-all rule
    existed to prevent. Caught by a test asserting the number rather than the
    behaviour.

    `timeframes.seconds_of` parses the bar type's **string** form, is already
    tested, and handles the two shapes a second derivation gets wrong: a
    composite naming its aggregation source after an `@`, and a symbol
    containing a hyphen. One derivation, so three rules cannot disagree about
    how long a bar is.
    """
    return seconds_of(bar_type)


class WarmFromHistory:
    """Request this desk's own bar type as history, and say what is still fresh.

    A mixin for `Desk`. The subclass feeds its own detectors in
    `warm_bar(bar)`; this handles the request, the delivery shape, the
    counters, and the freshness judgement.
    """

    #: Warm events counted apart from live ones, so a detector warmed by replay
    #: and one filled by the market can be told apart in a tally. A port is
    #: judged on these before it is judged on any money.
    warmed: dict[str, int]

    def warm_bar(self, bar: Bar) -> None:
        """Fold one historical bar into this rule's detectors.

        Implemented by the rule. It must **not** place anything: whether a warm
        signal acts is decided by `fresh`, at the call site, where the rule's
        own notion of a signal lives.
        """
        raise NotImplementedError

    def warm_bar_types(self) -> list[Any]:
        """Which bar types to request history for. This desk's own, by default.

        **A rule reading more than one instrument overrides this.**
        `identity-arb` is a currency triangle: it subscribes two partner legs
        beside the traded one and its residual needs all three at the same bar,
        so warming the traded leg alone would leave `_residual` returning None
        for the whole replay and the rule would look warm while holding no
        residuals at all.
        """
        return [self._cfg.bar_type]

    def start_warming(self) -> None:
        """Ask the venue for this desk's own history. Call after `super().on_start()`.

        Asked as a **span of this bar type** rather than a date, so the same
        number of bars is covered whatever the interval. `start` is positional
        and required: a request with no window is a `TypeError`, not a request
        for everything.
        """
        # **Does not clobber a rule's own counters.** `structure.py` sets up a
        # richer `warmed` - breaks, bos, choch - before `super().on_start()`,
        # and this runs after it, so assigning a fresh dict here would discard
        # them and the tally would read every warm break as live.
        if not isinstance(getattr(self, "warmed", None), dict):
            self.warmed = {}
        self.warmed.setdefault("bars", 0)
        #: `(bar type, close stamp)` already folded, so one bar is folded once
        #: however many times it is delivered. Bounded by the request limit.
        self._warm_seen: set[tuple[str, int]] = set()
        wanted = int(getattr(self.profile, "warm_bars_request", DEFAULT_WARM_BARS) or 0)
        if wanted <= 0:
            return
        span = timedelta(seconds=self.warm_seconds() * wanted)
        start = self.clock.utc_now() - span
        for bar_type in self.warm_bar_types():
            self._request_warm(bar_type, start, wanted)

    def _request_warm(self, bar_type: Any, start: Any, wanted: int) -> None:
        """One history request, composite or standard."""
        # **A composite bar type cannot be requested.** Nautilus refuses
        # `request_bars` for one outright - "Use a standard bar type with
        # request_bars. Composite bar types can be used with
        # request_aggregated_bars" - and these rules are configured both ways:
        # a live desk runs `...-15-MINUTE-LAST-EXTERNAL`, which is standard,
        # while a backtest may aggregate from an M1 feed. Asking the wrong one
        # raises in `on_start`, which takes the desk down rather than leaving
        # it cold, and it did once.
        if bar_type.is_composite():
            self.request_aggregated_bars(
                [bar_type],
                start,
                limit=wanted,
                include_external_data=False,
            )
        else:
            self.request_bars(bar_type, start, limit=wanted)

    def warm_seconds(self) -> float:
        """This desk's bar span in seconds."""
        return bar_seconds(self._cfg.bar_type)

    def warm_age(self, bar: Bar) -> float:
        """Seconds between this bar's close and now, by the strategy's clock.

        The strategy's clock and not `time.time()`, so a backtest's notion of
        now is the engine's. A negative age - a bar closing after now - reads
        as 0.0 rather than as fresh-by-a-margin, because the only way to get
        one is a clock disagreement and that should not widen the window.
        """
        now = float(self.clock.timestamp_ns()) / NANOS
        return max(0.0, now - float(bar.ts_event) / NANOS)

    def fresh(self, bar: Bar) -> bool:
        """Whether a signal on `bar` is recent enough to act on.

        By time, never by position: Nautilus delivers history one bar per call,
        so a handler cannot know whether another is coming. See the module
        docstring for why this is a judgement rather than plumbing.
        """
        allowed = float(getattr(self.profile, "warm_fresh_bars", DEFAULT_FRESH_BARS) or 0)
        if allowed <= 0:
            return False
        return self.warm_age(bar) <= allowed * self.warm_seconds()

    def on_historical_data(self, data: Any) -> None:
        """Fold requested history. **No log line here.**

        Nautilus delivers a `request_bars` response one bar per call rather
        than as a batch, so logging a running total once per call wrote
        "warmed 1 bars", "warmed 2 bars" and so on up to the request limit,
        per feed: measured at **38,748 lines** on a 32-feed start, which buries
        everything else on a two-core box. A tally reports `warm=` on one line
        every `TALLY_EVERY` seconds, which is the number anyone wants.
        """
        rows = data if isinstance(data, (list, tuple)) else [data]
        asked = {str(bar_type) for bar_type in self.warm_bar_types()}
        seen = getattr(self, "_warm_seen", None)
        if seen is None:
            seen = self._warm_seen = set()
        for row in rows:
            if not isinstance(row, Bar):
                continue
            spelling = str(row.bar_type)
            # **A desk is delivered history it never asked for.** Measured on
            # the live instance on 2026-11-10: a `zones` desk on `bnbusd`
            # folded 401 bars for a 400-bar request, `btcusd` 651, `audcad`
            # 617 and `euraud` **1,255** - and euraud has six requesters on
            # its clock (zones, structure, vol-impulse, and identity-arb's
            # three legs). So the responses arrive per bar type rather than
            # per requester, and before this guard every rule folded the
            # others' history into its own detectors.
            #
            # The instrument half is the damaging one: `identity-arb` requests
            # its *partner* legs, so a desk on EURAUD was folding EURUSD and
            # AUDUSD closes into one `BjorgumLevels`. Reproduced offline -
            # interleaving three legs took the ATR from **0.00132 to 0.62083**,
            # a factor of 470, which makes every zone width and every stop
            # distance derived from it meaningless.
            if spelling not in asked:
                self.warmed["foreign"] = self.warmed.get("foreign", 0) + 1
                continue
            # The same bar type can also be requested by several desks, so a
            # bar of this rule's *own* clock can still arrive more than once.
            # Keyed on the close stamp, which is what makes a bar that bar.
            key = (spelling, int(row.ts_event))
            if key in seen:
                self.warmed["repeat"] = self.warmed.get("repeat", 0) + 1
                continue
            seen.add(key)
            self.warmed["bars"] = self.warmed.get("bars", 0) + 1
            # Every class that mixes this in is a `Desk`, which carries the
            # stop-floor forecast; the guard is for this mixin's own test
            # doubles, which are not.
            observe = getattr(self, "observe_forecast", None)
            if observe is not None:
                observe(row)
            self.warm_bar(row)


__all__ = [
    "DEFAULT_FRESH_BARS",
    "DEFAULT_WARM_BARS",
    "NANOS",
    "WarmFromHistory",
    "bar_seconds",
]
