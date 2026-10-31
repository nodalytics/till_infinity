"""The statespace-native strategy: a surprise, entered on continuation.

Every other strategy on this desk is level-based - `level-scalp` on a level,
`approach-scalp` on the approach to one, `sweep-aware` on sweeps of one,
`fade-to-value` targeting a displacement origin - and reads `level`,
`origin_above_*`, `origin_below_*`, `swing_range_position` and
`break_probability`. **Statespace has no levels.** It folds log variance, so a
proposal from `statespace/proposing.py` would be refused by `wants` on nearly
all of them.

This is the one strategy written against what statespace actually measures.

## What it trades, and the one measurement behind it

`statespace.proposals` fires when the standardised innovation clears a
threshold - a move much bigger than this feed's own usual - and carries the
**triggering bar's own direction**, because a side taken from a log-variance
innovation would be the side of a volatility move. The trade is continuation of
that bar.

That is the only directional thing measured to work here. The 5-sigma anomaly
bar is on record at **+0.62R**, and `exit-urgency.md` measured holding it to a
2R target at **+0.1436R +/- 0.0485 over 905 trades, t 2.96** across 15 feeds.
`direction-is-closed-not-just-null` is why nothing cleverer is attempted: a
gate that correctly finds a planted drift at z +2.90 still earned 2% of a
spread.

## Its own gates, because the desk's refuse it

Two configured gates refuse these proposals outright and are **not** the right
gates for this trade:

* `TRADING_MIN_PROBABILITY` at 0.75, against a 2R barrier that cannot exceed a
  third. `proposing.py` reports a *touch* probability for that reason, which is
  what structures' field also means.
* `TRADING_MIN_BASE_RATE` at 0.51, against the honest 0.50 statespace reports -
  direction is 0.50150 over 7,728,858 rows and reporting 0.51 would be clearing
  a gate rather than measuring.

So this strategy gates on what the measurement actually depends on.

**`cost_share` is the gate that matters and it is new.** Every edge measured
this month died on cost, not on significance: 57 cross-sectional cells with a
best breakeven of 16.88 bp against a 74.91 bp spread, and
`exotic-spreads-are-a-whole-bar-range` recording 0.40 to 0.97 **bar-ranges** of
round trip on the exotics. The anomaly edge is +0.1436R **gross**, so a round
trip costing more than a fraction of that R is not a trade. The default refuses
anything whose spread exceeds 10% of the stop distance, which leaves roughly
two thirds of the measured edge; a feed whose spread is a tenth of a 2-sigma
move is one this trade cannot pay for.

**`least_surprise` is a second gate on the same quantity the producer already
thresholded.** Deliberately: the producer's threshold is what makes a proposal
exist at all, and this is what makes it worth a position, so they move
independently. `origin-returns-turn-at-z-one-three` is why neither is 5.0 -
returns turn at z 1.3 to 1.95 and z 2.5 already misses 85-89% of them.

## It is registered and not configured

`TRADING_STRATEGIES` does not name it, so it does not run until somebody adds
it. The slot in `MAGIC_ORDER` is appended regardless, because that table's own
comment records two strategies that "ran live for an hour" without one and
whose trades are permanently unattributable - a magic with no inverse reads as
"unattributed" on every close and the strategy cannot be scored at all.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar

from ..models import Intent, Refusal, Side, SymbolSpec, Tick, Verdict
from ..sizing import lots, respects_stops_level
from .strategy import Strategy, register


@register
class Dispersing(Strategy):
    """Continuation of a bar statespace found surprising. See the module."""

    name: ClassVar[str] = "statespace-surprise"
    #: The proposal shape. `Strategy.wants` compares this to `payload["shape"]`,
    #: and it must be the same word `proposing.py` stamps and `NOTIFY_SHAPES`
    #: allows - that allowlist silently dropped every statespace alert while
    #: the whole path worked.
    shape: ClassVar[str] = "statespace"
    description: ClassVar[str] = (
        "A move much bigger than this feed's usual just printed; the trade is "
        "continuation of the bar that printed it, stopped and targeted off the "
        "statespace band rather than off a level."
    )

    #: **The measured breakeven, not a round number.** `exit-urgency.md` put
    #: holding this entry to a 2R target at a **38.1% win rate over 905
    #: trades**, so breakeven reward-to-risk is `(1 - 0.381) / 0.381 = 1.625`,
    #: and the hit rate's own standard error of 1.6% puts that at 1.625 +/-
    #: 0.07. 1.70 is a touch above the upper end rather than at the point
    #: estimate, because a floor set at an estimate is below breakeven half the
    #: time. The default `target_r` of 2.0 already clears it, so this only
    #: binds when something else has pulled the target in - and
    #: `floored_target` can only move a target *out*, so it cannot cost a sound
    #: trade anything.
    reward_floor: ClassVar[float] = 1.70

    #: **The feeds it is allowed on, because `TRADING_SYMBOLS` is global.**
    #: Naming the strategy in `TRADING_STRATEGIES` would otherwise make it
    #: eligible on all 32 configured symbols, and the restriction belongs in
    #: code rather than in an environment variable: it is a claim about where
    #: the spread clears `cost_share`, which is a measurement, not an operator
    #: preference.
    #:
    #: FX majors and crosses only. `exotic-spreads-are-a-whole-bar-range`
    #: measured round trips of **0.40 to 0.97 bar-ranges** on the exotics, and
    #: this week's cross-section died at 74.91 bp against a best breakeven of
    #: 16.88 - so on a wide feed the cost gate would refuse nearly every
    #: proposal anyway. Restricting the set makes those refusals deliberate
    #: rather than incidental, which is what lets the first week's journal
    #: answer one question instead of two.
    #:
    #: `usdcnh` is left out: it is neither a classic major nor a cross, and its
    #: spread is the one in that group the gate would be fighting.
    feeds: ClassVar[frozenset[str]] = frozenset(
        {
            # majors
            "eurusd",
            "gbpusd",
            "usdjpy",
            "usdcad",
            "usdchf",
            "audusd",
            "nzdusd",
            # crosses
            "eurgbp",
            "eurjpy",
            "gbpjpy",
            "eurchf",
            "audjpy",
            "chfjpy",
            "euraud",
        }
    )

    #: Standardised innovation a proposal needs before it is worth a position.
    least_surprise: ClassVar[float] = 3.5
    #: Most of the stop distance the spread may be. See the module docstring:
    #: the edge is +0.1436R gross and this is what keeps the cost inside it.
    cost_share: ClassVar[float] = 0.10
    #: Stop in volatility units, and reward to risk. Defaults match the arm
    #: `exit-urgency.md` measured, so the live trade and the measurement are
    #: the same geometry rather than two different ones.
    stop_vol: ClassVar[float] = 2.0
    target_r: ClassVar[float] = 2.0

    def wants(self, payload: dict[str, Any]) -> bool:
        """The shape **and** the feed. See `feeds`.

        Checked here rather than in `consider` so a proposal on an unlisted
        feed costs nothing and is not counted as a refusal - it was never
        this strategy's to decline.
        """
        if str(payload.get("shape") or "") != self.shape:
            return False
        return str(payload.get("feed") or "").lower() in self.feeds

    def consider(  # noqa: PLR0911 - one gate per return, in the order they are
        # applied, for the reason `service.on_signal` gives for the same
        # suppression: the order is the design, and each return is a distinct
        # way a proposal stops being a trade and is counted under its own gate.
        self,
        payload: dict[str, Any],
        *,
        spec: SymbolSpec,
        tick: Tick,
        equity: float,
        positions: Sequence[Any] = (),
        peak: float = 0.0,
    ) -> Verdict:
        feed = str(payload.get("feed") or "")
        self.seen += 1
        features = payload.get("features") or {}
        if not isinstance(features, dict):
            return Refusal("features", "no features on the proposal", feed)

        surprise = abs(_number(features.get("surprise")))
        if surprise < self.least_surprise:
            return Refusal(
                "surprise",
                f"{surprise:.2f} below {self.least_surprise:.2f}",
                feed,
            )

        side_raw = int(_number(payload.get("direction")))
        if side_raw == 0:
            # A doji expressed no direction. The producer drops these, so this
            # is a second line rather than the only one.
            return Refusal("direction", "the bar took no side", feed)
        side = Side.BUY if side_raw > 0 else Side.SELL

        # One volatility unit, as a price distance. `vol_bps` is the folded log
        # variance - `exp(value / 2)` in basis points - and nothing here reads
        # the spread *column*, whose conversion is a measured 476% error.
        vol_bps = _number(features.get("vol_bps"))
        entry = tick.ask if side is Side.BUY else tick.bid
        if vol_bps <= 0 or entry <= 0:
            return Refusal("volatility", f"vol_bps {vol_bps:.4f}", feed)
        unit = vol_bps / 1e4 * entry

        stop_vol = _number(features.get("stop_vol")) or self.stop_vol
        target_r = _number(features.get("target_r")) or self.target_r
        risk = stop_vol * unit
        if risk <= 0:
            return Refusal("volatility", "a zero stop distance", feed)

        # **The gate that decides this strategy.** Checked before the broker
        # geometry and before sizing, because a trade that cannot pay for its
        # spread is not worth the rest of the arithmetic.
        if tick.spread > 0:
            share = tick.spread / risk
            if share > self.cost_share:
                return Refusal(
                    "cost",
                    f"spread is {share:.1%} of the stop, over {self.cost_share:.0%}",
                    feed,
                )

        sign = 1.0 if side is Side.BUY else -1.0
        stop = entry - sign * risk
        target = entry + sign * target_r * risk
        target = self.floored_target(spec, side, entry, stop, target)
        if broker_says := respects_stops_level(spec, entry, stop, target):
            return Refusal("stops_level", broker_says, feed)

        interval = str(payload.get("interval") or "")
        sized = lots(
            spec,
            equity=equity,
            risk_fraction=(
                self.settings.risk_fraction
                # Crowding, volatility, measured edge and drawdown. All four
                # off unless set and none can enlarge - the same call every
                # other strategy makes, so this one is sized by the same rules.
                * self.risk_scale(feed, features, positions, equity, peak, interval, side)
            ),
            stop_distance=risk,
            max_risk_money=self.settings.max_risk_money,
            slippage=self.settings.stop_slippage,
        )
        if not sized.ok:
            return Refusal("size", sized.reason, feed)

        protect_at, protect_trail = self.protection(interval)
        self.wanted += 1
        return Intent(
            feed=feed,
            symbol=spec.symbol,
            side=side,
            volume=sized.volume,
            entry=entry,
            stop=stop,
            target=target,
            reason=str(payload.get("detail") or ""),
            interval=interval,
            confluence=tuple(str(x) for x in (payload.get("confluence") or ())),
            features={str(k): _number(v) for k, v in features.items()},
            risk_money=sized.risk_money,
            stop_vol=stop_vol,
            hold=self.hold_for(interval),
            break_even_at=protect_at,
            trail_vol=protect_trail,
        )


def _number(value: object) -> float:
    """A float, or 0.0. A proposal crossing a bus is data, not a promise."""
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
