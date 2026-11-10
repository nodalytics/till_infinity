"""`identity-arb` - a directional bet on a currency triangle's own arithmetic.

**Not a triangular arbitrage.** It trades a *single* leg in the direction the
identity says the gap must close, so the cost is that leg's own round trip and
not the basket's three.

## The measurement this rests on, and its error bars

`research/docs/statespace-exploiting-relationships.md`, re-run 2026-11-07 on
3.2 years of broker data the harness had never seen, reproduces its published
figures: at an hourly clock the residual earns **+2.2023** round trips entered
at the bar it is seen, **+0.7938** one bar later, and nothing by two - the
decay of a signal whose life is about a day against a bar that costs half of
it.

At **M15 the decay is gone**, which is the test the original said the claim
stands or falls on. De-overlapped to one entry per horizon:

    delay 0  +2.9782     control +0.3507     p = 0.0050
    delay 1  +2.4721     control +0.3193     p = 0.0050
    delay 2  +2.7398     control +0.3592     p = 0.0050
    delay 3  +2.8453     control +0.3397     p = 0.0050

**What it cost to de-overlap is the honest headline**: the edge fell from
+6.71 to +2.47 at delay 1, the configurations from 252 to 93, and the median
`t` from +3.26 to **+1.18**. Sixty-three percent of the apparent edge and all
of the per-row significance were overlapping forward windows. The aggregate
clears its broken-link null; **the typical configuration does not**. So this
rule is a measured edge with wide error bars - plausibly anywhere from zero to
five round trips - and is to be sized as one.

Two caveats carried from the measurement rather than hidden:

* the non-identity control triples sit at **+0.33** and not zero, unexplained,
  which is 13% of the identity edge. FX pairs share factors, so any triple is
  weakly cointegrated and a small positive is expected - but that is a
  hypothesis, not a result.
* 93 configurations over 290 days is thin, and one regime.

## `GAP` is not optional

Trading **every** qualifying bar is what inflated the backtest by 63%. A run
of bars above the threshold is one episode, not forty trades, so an entry is
taken only once per `gap_bars` - and the number is the horizon, because that
is what makes the forward windows disjoint.

## Why the weights are not fitted

An identity's weights are arithmetic: `cross = (a/USD) x (USD/b)` exactly, so
the residual is a log difference with no free parameters. The relationship
screen that found this fits weights by least squares because it screens
*candidate* relationships; applying that here would turn a known identity into
a fitted guess and re-introduce the overfitting the identity restriction was
chosen to avoid.

## Staleness is the failure mode to guard

The residual is a ratio of three prices and is meaningless if one of them is
old: a partner quote that has not moved makes the triangle look deviated and
"revert" when it updates. That is measurement noise, not an inefficiency, and
it is the alternative explanation the original tested with its entry delay. So
a partner leg older than `stale_bars` bars refuses the reading outright.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any, ClassVar

from nautilus_trader.model.data import Bar, BarType

from ..domain.models import Intent, Refusal, Side
from .desk import Desk
from .entries import EdgeEntry
from .exits import ManagedExit
from .profile import Profile
from .warming import WarmFromHistory

#: Every complete triangle among the majors, as `(a, b)` - the legs are
#: resolved against what the venue actually lists, in either orientation.
TRIANGLES: tuple[tuple[str, str], ...] = (
    ("EUR", "GBP"),
    ("EUR", "JPY"),
    ("EUR", "CHF"),
    ("EUR", "AUD"),
    ("EUR", "CAD"),
    ("EUR", "NZD"),
    ("GBP", "JPY"),
    ("GBP", "CHF"),
    ("GBP", "AUD"),
    ("GBP", "CAD"),
    ("GBP", "NZD"),
    ("JPY", "CHF"),
    ("JPY", "AUD"),
    ("JPY", "CAD"),
    ("JPY", "NZD"),
    ("CHF", "AUD"),
    ("CHF", "CAD"),
    ("CHF", "NZD"),
    ("AUD", "CAD"),
    ("AUD", "NZD"),
    ("CAD", "NZD"),
)


#: How the venue names each major's USD leg. **Convention, not arithmetic.**
#: EUR, GBP, AUD and NZD are quoted as `XXXUSD`; JPY, CHF and CAD as `USDXXX`.
#: Composing the name instead - `f"{ccy}USD"` - produces `JPYUSD` and
#: `USDCHF`'s mirror, neither of which the venue lists, so every subscription
#: on half the triangles would have failed and the desk would have read as
#: quiet rather than broken.
USD_LEG: dict[str, str] = {
    "EUR": "EURUSD",
    "GBP": "GBPUSD",
    "AUD": "AUDUSD",
    "NZD": "NZDUSD",
    "JPY": "USDJPY",
    "CHF": "USDCHF",
    "CAD": "USDCAD",
}


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


class IdentityProfile(Profile):
    """The numbers the measurement fixed, and nothing tuned here."""

    name: ClassVar[str] = "identity-arb"
    description: ClassVar[str] = "identity_z3|M15|gap=h|one-leg"
    #: Its own shape, so a statespace proposal is skipped rather than judged.
    shape: ClassVar[str] = "identity"
    style: ClassVar[str] = "swing"
    #: `ENTRY` in the harness. Pre-specified, never swept here.
    entry_z: ClassVar[float] = 3.0
    #: The z's lookback in bars. Five days at M15, as measured.
    window: ClassVar[int] = 480
    #: Bars of history to warm the residual window with on start.
    #:
    #: **This rule had the longest blind window on the desk, by far.** `_step`
    #: refuses to score until `window // 2` residuals are in hand - 240 bars,
    #: which is **two and a half days** of 15m - and before that the tally read
    #: `fired=0` while the desk could not have fired at all. 600 fills the
    #: window outright, with room for the `cold` and `stale` refusals that eat
    #: into it.
    warm_bars_request: ClassVar[int] = 600
    #: A breach on the last warm bar is still actionable. The z is computed
    #: from residuals *before* the current one either way, so a replayed breach
    #: was scored exactly as a live one would have been; what makes the final
    #: bar special is only that its price has not moved on.
    warm_fresh_bars: ClassVar[int] = 1
    #: The horizon the edge was measured over, in bars: 24 hours at M15.
    hold_bars: ClassVar[int] = 96
    #: One entry per horizon, so forward windows are disjoint. **Not a knob.**
    gap_bars: ClassVar[int] = 96
    #: A partner leg older than this refuses the reading.
    stale_bars: ClassVar[int] = 2
    #: The stop, in residual-sigma of the traded leg's own move. The
    #: measurement has no stop at all - it holds to the horizon - so this is
    #: **this rule's own addition** and is the first thing to question if the
    #: live result disagrees with the backtest.
    stop_sigma: ClassVar[float] = 3.0
    #: Minimum stop, in spreads, when the sigma estimate is small.
    stop_spreads: ClassVar[float] = 20.0


class Identity(WarmFromHistory, Desk):
    """One traded leg, two partner legs, and the arithmetic between them."""

    profile: ClassVar[IdentityProfile] = IdentityProfile.__new__(IdentityProfile)

    def on_start(self) -> None:
        """Subscribe the two partner legs beside the traded one.

        `context_bar_types` is documented for a slower clock of the *same*
        instrument, but a `BarType` carries its own `InstrumentId`, so the same
        mechanism carries another symbol. The traded leg stays `bar_type`,
        which keeps sizing, quoting and the venue route unchanged.
        """
        self.resid: deque[float] = deque(maxlen=self.profile.window)
        #: Latest close and bar stamp per partner symbol.
        self.partners: dict[str, tuple[float, float]] = {}
        #: The bar index of the last entry, for the gap.
        self.bars_seen = 0
        self.last_entry = -(10**9)
        self.tally: dict[str, int] = {
            "bars": 0,
            "resid": 0,
            "fired": 0,
            "stale": 0,
            "gapped": 0,
            "cold": 0,
        }
        self.trio = self._trio()
        #: Historical bars from all three legs, held until they can be replayed
        #: **in timestamp order**. See `_drain` for why buffering is required
        #: rather than tidy. Set before `super()`, because a request answered
        #: quickly could reach `warm_bar` before the next statement here.
        self._warm: list[Bar] = []
        super().on_start()
        if self.trio is None:
            # Said out loud, because a desk that can never trade and a desk
            # with no setups read identically in a log - the lesson of
            # `statespace-surprise`'s hardcoded feed allowlist.
            self.log.warning(
                f"identity-arb has no triangle for "
                f"{self._cfg.instrument_id.symbol.value}; this desk can never trade"
            )
            return
        traded, first, second = self.trio
        for name in (first, second):
            #: The traded bar type with the symbol swapped: same venue, same
            #: spec, same aggregation, so the partner arrives on the same clock.
            frame = BarType.from_str(str(self._cfg.bar_type).replace(traded, name, 1))
            self.subscribe_bars(frame)
        self.start_warming()
        self.log.info(
            f"identity-arb on {traded}: partners {first} and {second}, "
            f"z>{self.profile.entry_z}, gap {self.profile.gap_bars} bars"
        )

    # ------------------------------------------------------------- the triangle

    def _trio(self) -> tuple[str, str, str] | None:
        """`(traded, partner, partner)` for this desk's symbol, or None.

        The traded leg is the **cross**: it is the single instrument the
        residual speaks about most directly, and its direction follows from the
        arithmetic with no further choice. A desk on a USD leg has two
        triangles it could belong to and no way to pick, so it declines.
        """
        symbol = self._cfg.instrument_id.symbol.value.upper()
        if len(symbol) != 6:
            return None
        base, quote = symbol[:3], symbol[3:]
        if "USD" in (base, quote):
            return None
        if not any({a, b} == {base, quote} for a, b in TRIANGLES):
            return None
        #: **Ordered by the traded symbol, not by the table.** `_residual`
        #: asks the first partner for `(base, USD)` and the second for
        #: `(USD, quote)`, so returning them in `TRIANGLES`' own order made
        #: `_oriented` return None on every triangle whose table entry was
        #: the other way round - half of them, silently, reading as no setups.
        first, second = USD_LEG.get(base), USD_LEG.get(quote)
        if not first or not second:
            return None
        return symbol, first, second

    @staticmethod
    def _oriented(name: str, want: tuple[str, str], price: float) -> float | None:
        """`price` as units of `want[1]` per one `want[0]`, or None."""
        base, quote = name[:3], name[3:]
        if (base, quote) == want:
            return price
        if (quote, base) == want and price > 0:
            return 1.0 / price
        return None

    def _residual(self, cross: float) -> float | None:
        """`log(actual) - log(implied)`, or None if a leg is missing or stale."""
        if self.trio is None:
            return None
        traded, first, second = self.trio
        a, b = traded[:3], traded[3:]
        legs = []
        for name, want in ((first, (a, "USD")), (second, ("USD", b))):
            got = self.partners.get(name)
            if got is None:
                self.tally["cold"] += 1
                return None
            price, when = got
            if self.bars_seen - when > self.profile.stale_bars:
                self.tally["stale"] += 1
                return None
            rate = self._oriented(name, want, price)
            if rate is None or rate <= 0:
                return None
            legs.append(rate)
        implied = legs[0] * legs[1]
        if implied <= 0 or cross <= 0:
            return None
        return math.log(cross) - math.log(implied)

    # ---------------------------------------------------------------- the bars

    def warm_bar_types(self) -> list[Any]:
        """All three legs: the residual needs them at the same bar."""
        if self.trio is None:
            return [self._cfg.bar_type]
        traded, first, second = self.trio
        spelling = str(self._cfg.bar_type)
        return [self._cfg.bar_type] + [
            BarType.from_str(spelling.replace(traded, name, 1)) for name in (first, second)
        ]

    def warm_bar(self, bar: Bar) -> None:
        """Hold a historical bar. It cannot be scored where it arrives.

        **Three requests and no guarantee about how they interleave.** Nautilus
        answers each `request_bars` separately and delivers one bar per call,
        so scoring a bar as it lands would feed this rule a block of one leg
        and then a block of another - and `_residual` reads the partners'
        stored closes against `bars_seen`, which is a bar **count**. A
        leg-at-a-time replay would pair the cross's close with a partner's
        close from a different time, and either refuse everything as `stale`
        or, worse, compute a residual from two different moments.

        `difference-before-aligning` is the same failure one level down: align
        first and difference second, or every gap becomes a fake reading.
        """
        self._warm.append(bar)

    def _drain(self) -> None:
        """Replay the buffered history in timestamp order, then forget it.

        Driven from the first live bar rather than a timer: a `request_bars`
        response carries no completion signal, and the first live bar is the
        earliest moment at which every request that was going to answer has.
        """
        buffered, self._warm = self._warm, []
        buffered.sort(key=lambda row: row.ts_event)
        self.tally["warm"] = self.tally.get("warm", 0) + len(buffered)
        for row in buffered:
            self._step(row, act=self.fresh(row))

    def on_bar(self, bar: Bar) -> None:
        """A partner close is stored; the traded leg's close is a decision."""
        super().on_bar(bar)
        if self._warm:
            self._drain()
        self._step(bar, act=True)

    def _step(self, bar: Bar, *, act: bool) -> None:
        """One bar through the triangle. **One derivation, two callers.**"""
        self.bars_seen += 1
        symbol = bar.bar_type.instrument_id.symbol.value.upper()
        if self.trio is None:
            return
        traded = self.trio[0]
        if symbol != traded:
            self.partners[symbol] = (float(bar.close), float(self.bars_seen))
            return
        self.tally["bars"] += 1
        res = self._residual(float(bar.close))
        if res is None:
            return
        #: **The z uses only residuals before this one.** Including the
        #: current reading in its own mean and sd shrinks every z toward zero
        #: and is the standard way this kind of trigger gets quietly blunted.
        past = list(self.resid)
        self.resid.append(res)
        self.tally["resid"] += 1
        if len(past) < self.profile.window // 2:
            return
        mean = sum(past) / len(past)
        var = sum((x - mean) ** 2 for x in past) / max(1, len(past) - 1)
        sd = math.sqrt(var)
        if sd <= 0:
            return
        z = (res - mean) / sd
        if abs(z) < self.profile.entry_z:
            return
        if self.bars_seen - self.last_entry < self.profile.gap_bars:
            self.tally["gapped"] += 1
            return
        if not act:
            # A breach this rule was not running for. `last_entry` is still
            # stamped, so the gap rule counts a replayed breach against the
            # next live one exactly as it would a live predecessor.
            self.last_entry = self.bars_seen
            self.tally["replayed"] = self.tally.get("replayed", 0) + 1
            return
        self.last_entry = self.bars_seen
        self.tally["fired"] += 1
        self.on_data(
            {
                "feed": self._feed_name(),
                "shape": self.profile.shape,
                "interval": self.interval or self.profile.interval,
                #: A rich cross closes by falling, so the side is `-sign(z)`.
                "direction": -1 if z > 0 else 1,
                "features": {
                    "identity_z": float(z),
                    "identity_resid": float(res),
                    "identity_sd": float(sd),
                    "identity_close": float(bar.close),
                },
            }
        )

    def _tally_extra(self) -> str:
        return (
            f" bars={self.tally['bars']} resid={self.tally['resid']}"
            f" fired={self.tally['fired']} gapped={self.tally['gapped']}"
            f" stale={self.tally['stale']} cold={self.tally['cold']}"
        )

    # ------------------------------------------------------------ the decision

    def wants(self, payload: dict[str, Any]) -> bool:
        return str(payload.get("shape") or "") == self.profile.shape

    def decide(self, payload: dict[str, Any]) -> Intent | Refusal | None:
        """The geometry. The filtering already happened in the residual."""
        feed = self._feed_name()
        tick = self._tick()
        if tick is None:
            return Refusal(gate="no-quote", detail=f"no quote for {feed}", feed=feed)
        features = payload.get("features") or {}
        if not isinstance(features, dict):
            return Refusal(gate="features", detail="no features on the proposal", feed=feed)
        side_raw = int(_number(payload.get("direction")))
        if side_raw == 0:
            return Refusal(gate="direction", detail="the residual took no side", feed=feed)
        side = Side.BUY if side_raw > 0 else Side.SELL
        entry = tick.ask if side is Side.BUY else tick.bid
        if entry <= 0.0:
            return Refusal(gate="quote", detail="a non-positive entry", feed=feed)
        #: The residual's own sd, converted from log space to price at the
        #: entry. **The measurement has no stop**, so this is the rule's
        #: addition and the first thing to doubt if live disagrees.
        sd = _number(features.get("identity_sd"))
        reach = self.profile.stop_sigma * sd * entry
        spreads = self.profile.stop_spreads * tick.spread
        stop = entry - side.sign * max(reach, spreads)
        if abs(entry - stop) <= 0.0:
            return Refusal(gate="stop", detail="a zero stop distance", feed=feed)
        return Intent(
            feed=feed,
            symbol=self._cfg.instrument_id.symbol.value,
            side=side,
            volume=0.0,
            entry=entry,
            stop=stop,
            features={k: _number(v) for k, v in features.items()},
            interval=self.interval or self.profile.interval,
        )


class IdentityEdge(Identity, ManagedExit, EdgeEntry):
    """At market on the close that produced the residual. One entry only:
    the measurement enters at a bar's close, so a rest at a named price and a
    wait for an arrival are both a different rule."""
