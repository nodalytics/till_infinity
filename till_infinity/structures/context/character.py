"""Whether an instrument is still behaving like itself.

See `structures-context-character.md` in research/docs.

This watches the change detectors in `cusum.py` rather than the price, and it is a
**monitor, not a signal**. Nothing gates a trade on it. It answers one operational
question: has this instrument stopped being the instrument the desk was configured for.

## Why the asymmetry and not the rate

The research this comes from validated a jump detector against the one piece of ground
truth available here: Boom indices are built to spike upward against a slow grind down and
Crash indices are the mirror, so an up-channel must fire far more than a down-channel on
Boom and the reverse on Crash. It does, and by a wide margin - +3.7 against -3.6 firings per
thousand bars, with a symmetric synthetic coming out symmetric.

**That asymmetry is the instrument's character, and it is the thing worth watching.** A
synthetic index is generated, its parameters are the broker's to change, and if Boom stops
spiking upward then every assumption the desk holds about it is void. Nothing here would
otherwise notice: the price would still arrive, the feed would still be healthy, and the
volatility estimate would still be correct.

## Two alarms, and why each is separate

**Balance** is the up-versus-down share of firings. It is compared against the same
instrument's own long-run share rather than against any absolute expectation, so it needs no
per-instrument configuration and works the first time a new symbol is added.

**Rate** is how often anything fires at all. This is a distinct fault with a distinct cause:
the `Focus` threshold in `engine._note_change` is fixed per interval, and a fixed threshold
on a changing series does not hold its firing rate. The research measured that directly - a
fixed threshold fired 0.06 times per thousand bars in a quiet stretch and 43.16 in a loud
one, seven hundred times more, while a rate-regulated one held near 2 throughout. So a rate
that departs from its own history says the detector has stopped discriminating, which is a
fault in the *reading* rather than in the instrument, and conflating the two would send the
wrong person looking.

## Balance is counted per event; rate is counted per bar

The balance windows average over **firings**, because a share estimated over "the last forty
events" means the same thing whether those arrived in a week or a month, while a fixed bar
window holds a different number of events in a quiet period than a busy one and would drift
on that alone.

The rate windows average over **bars**, because a rate is a per-bar quantity and a window
measured in events cannot see the rate falling - if firings stop, an event-counted window
simply stops updating and reports the last thing it saw.

Both are **bias corrected**, dividing out the accumulated weight, so neither carries its
starting value. Without that the balance alarm fires spuriously on any lopsided instrument;
with it, 400,000 bars of a simulated Boom at 85% up produced no false alarm and converged to
a baseline of 0.852.

**The rate alarm is deliberately coarse.** At a realistic firing rate of a few per thousand
bars, the short window holds under ten events, so its fold change is noisy; the threshold is
set wide enough that the noise does not reach it, which costs sensitivity and buys an alarm
that can be trusted. It is there to catch the order-of-magnitude failure a fixed threshold
produces across regimes, not a subtle drift.

Only floats are held, deliberately. A capped `deque` field restored from an older save comes
back **uncapped** - that has already happened once in this codebase and was found on the live
heap rather than in the declaration - so a monitor that must survive every deploy holds
nothing that has a length.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ...shared.state import Restorable

#: Effective number of firings the short window averages over. Small enough to move
#: within days on an active series, large enough that a handful of events cannot trip it.
SHORT_EVENTS = 40.0

#: And the long window, which is the instrument's own history to compare against.
LONG_EVENTS = 600.0

#: Firings before anything is judged.
#:
#: **This is not only about sample size, and the first version was wrong.** An
#: exponential average started at one half carries that half for several time constants,
#: so a genuinely lopsided instrument compared against its own unconverged baseline
#: alarms immediately and spuriously - a simulated Boom at 85% up read a baseline of 56%
#: at event 120 and raised +3.7 sigma against itself. The averages below are therefore
#: **bias corrected**, which removes the starting value rather than waiting it out, and
#: this threshold is then only about having enough events for the error bar to mean
#: something.
WARM_EVENTS = 60

#: Bars the rate windows average over, short and long. Fixed bar counts rather than a
#: rate-adaptive window: the adaptive version had to bootstrap from a rate it did not
#: know yet, and its early behaviour depended on that guess.
SHORT_BARS = 2000.0
LONG_BARS = 30000.0

#: Standard errors the short share must sit from the long share before the balance alarm
#: raises. Three, not two: this fires into an operator's lap rather than into a tally, and
#: the cost of a false alarm is somebody's afternoon.
BALANCE_SIGMA = 3.0

#: Fold change in firing rate that raises the rate alarm, in either direction. Wide,
#: because the fixed-threshold behaviour it is there to catch moves by factors of tens
#: and a factor of two is ordinary regime noise.
RATE_FOLD = 4.0


@dataclass(slots=True)
class Character(Restorable):
    """One series' firing balance and rate, short window against long."""

    #: Shares, as exponential moving averages over firings. Held **uncorrected**, with
    #: the accumulated weight beside them; the properties divide the two. Storing the
    #: raw pair rather than a corrected value keeps the update one line and means a
    #: restored state needs no knowledge of how many events produced it.
    short_up: float = 0.0
    long_up: float = 0.0
    short_w: float = 0.0
    long_w: float = 0.0
    #: Firings per bar, over fixed bar windows, same correction.
    short_rate: float = 0.0
    long_rate: float = 0.0
    short_rate_w: float = 0.0
    long_rate_w: float = 0.0
    events: int = 0
    bars: int = 0
    #: Latched so a standing shift is reported once rather than on every bar. Cleared
    #: when the reading comes back inside its band, so a genuine second shift is seen.
    balance_alarmed: bool = False
    rate_alarmed: bool = False

    def observe(self, up_fired: bool, down_fired: bool) -> None:
        """One bar's worth of detector output."""
        self.bars += 1
        fired = int(up_fired) + int(down_fired)

        # Rate is per bar, so it updates on every bar including the quiet ones - that is
        # what makes a *fall* in rate visible rather than only a rise.
        for name, window in (("short_rate", SHORT_BARS), ("long_rate", LONG_BARS)):
            a = 1.0 / window
            setattr(self, name, getattr(self, name) + a * (fired - getattr(self, name)))
            wname = f"{name}_w"
            setattr(self, wname, getattr(self, wname) + a * (1.0 - getattr(self, wname)))

        if not fired:
            return
        # Balance is per event. Both directions firing on one bar counts as one each way,
        # which leaves the share at one half - correctly, because a bar that fired both
        # ways says nothing about direction.
        share = int(up_fired) / fired
        self.events += 1
        for name, window in (("short_up", SHORT_EVENTS), ("long_up", LONG_EVENTS)):
            a = 1.0 / window
            setattr(self, name, getattr(self, name) + a * (share - getattr(self, name)))
            wname = "short_w" if name == "short_up" else "long_w"
            setattr(self, wname, getattr(self, wname) + a * (1.0 - getattr(self, wname)))

    @staticmethod
    def _corrected(total: float, weight: float, default: float) -> float:
        """An exponential average with its starting value divided back out."""
        return total / weight if weight > 1e-9 else default

    @property
    def up_share(self) -> float:
        return self._corrected(self.short_up, self.short_w, 0.5)

    @property
    def up_share_long(self) -> float:
        return self._corrected(self.long_up, self.long_w, 0.5)

    @property
    def warm(self) -> bool:
        return self.events >= WARM_EVENTS

    def balance_shift(self) -> float:
        """Standard errors the short share sits from the long one, signed.

        The error is the binomial one at the long-run share over the short window's
        effective sample size - `SHORT_EVENTS` once the window is full, and the number of
        events seen while it is filling, because an error bar that claims forty events
        when it has had six is how a monitor alarms on its own first week.
        """
        if not self.warm:
            return 0.0
        p = min(max(self.up_share_long, 1e-6), 1 - 1e-6)
        n = min(float(self.events), SHORT_EVENTS)
        se = math.sqrt(p * (1 - p) / n) if n > 0 else 0.0
        return (self.up_share - p) / se if se > 0 else 0.0

    def rate_fold(self) -> float:
        """Short-run firing rate over long-run, or 0 when there is nothing to compare."""
        if not self.warm:
            return 0.0
        long = self._corrected(self.long_rate, self.long_rate_w, 0.0)
        short = self._corrected(self.short_rate, self.short_rate_w, 0.0)
        return short / long if long > 0 else 0.0

    def alarms(self) -> list[str]:
        """Any fault worth telling an operator about, each at most once per shift."""
        out: list[str] = []
        shift = self.balance_shift()
        if abs(shift) >= BALANCE_SIGMA:
            if not self.balance_alarmed:
                self.balance_alarmed = True
                way = "upward" if shift > 0 else "downward"
                out.append(
                    f"jump balance has moved {way}: {self.up_share:.0%} of recent changes "
                    f"are up against {self.up_share_long:.0%} historically "
                    f"({shift:+.1f} sigma)"
                )
        else:
            self.balance_alarmed = False

        fold = self.rate_fold()
        if fold and (fold >= RATE_FOLD or fold <= 1.0 / RATE_FOLD):
            if not self.rate_alarmed:
                self.rate_alarmed = True
                out.append(
                    f"change detections have gone {fold:.1f}x their usual rate "
                    f"({self._corrected(self.short_rate, self.short_rate_w, 0.0):.4f} "
                    f"against {self._corrected(self.long_rate, self.long_rate_w, 0.0):.4f} "
                    "per bar) - "
                    "this is the detector, not the instrument"
                )
        else:
            self.rate_alarmed = False
        return out

    def to_dict(self) -> dict:
        """The reading, for the context payload and the service's state view."""
        return {
            "up_share": round(self.up_share, 4),
            "up_share_long": round(self.up_share_long, 4),
            "balance_sigma": round(self.balance_shift(), 2),
            "rate": round(self._corrected(self.short_rate, self.short_rate_w, 0.0), 5),
            "rate_fold": round(self.rate_fold(), 3),
            "events": self.events,
            "warm": self.warm,
        }
