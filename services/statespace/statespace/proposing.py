"""Statespace as a producer of trading signals, in the contract trading reads.

`structures.signals` does **not** carry an Intent. `trading/service.py`'s
`on_signal` takes a signal payload and hands it to each configured strategy,
whose `wants` then `consider_async` builds the side, entry, stop, target and
size. So for statespace to drive the desk it does not need to emit Intents - it
needs to emit a payload in the signal contract, and then `risk.Guard`, the
sizing, the per-instrument limits and the journal all apply unchanged.

The contract, taken from what the strategies actually read: `feed`, `interval`,
`direction`, `features`, `confluence`, `time`, `level_id`, `shape`, `detail`.

## The sign cannot come from the readout, and this is the third time

`signalling.terms_from` offers `surprise` as "statespace's own reading of the
bar", and `Signal.side` turns it into a sign - but **this service folds log
variance**, so that is the side of a *volatility* move. Publishing it as
`direction` would be the category error already corrected twice in this
package, where `side` became `variance_side` and the alert kind `break` became
`surprise`, both because a bare directional word on a variance service reads as
a price claim. The same applies to `Desk`'s discrete chain, whose own comment
says it "forecasts whether dispersion rises next, not whether price" does.

So statespace supplies the **trigger and the magnitude**, and the **sign comes
from the triggering bar's own body**. That is continuation, which is the only
directional thing measured to work here: the 5-sigma anomaly bar at +0.62R on
record, and +0.1436R +/- 0.0485 over 905 trades at t 2.96 in `exit-urgency.md`.
`direction-is-closed-not-just-null` is why nothing cleverer is attempted - a
gate that correctly finds a planted drift at z +2.90 still earned 2% of a
spread.

## Why this needs its own strategy rather than the seven configured ones

Every strategy on the desk is level-based - `level-scalp`, `approach-scalp`,
`sweep-aware`, `fade-to-value` - and reads `level`, `origin_above_*`,
`origin_below_*`, `swing_range_position` and `break_probability`. **Statespace
has no levels**; it folds log variance. A proposal from here would be refused
by `wants` on nearly all of them, and two configured gates refuse it outright:

* `TRADING_MIN_PROBABILITY=0.75`, against a barrier probability that cannot
  exceed 1/3 for a 2R target. `probability` here is therefore a **touch**
  probability, which is what structures' field also means -
  `prod-probability-up-needs-halving` records the 0.6365 as overlapping touches
  and 0.5092 de-overlapped.
* `TRADING_MIN_BASE_RATE=0.51`, against an honest statespace base rate of
  **0.50**. Direction is a coin here and the module says so rather than
  reporting 0.51 to clear a gate.

Those are stated rather than worked around. A statespace-native strategy with
its own gates is the next step; this module is the producer it would consume,
and until that strategy exists these proposals are recorded and not acted on -
the `turning.py` pattern, which is also the warning: `trading.turn_exit` "has
never once run in production" while its end-to-end path passed every test.

## What statespace should drive regardless of any of that

`vol_bps` is read by three strategies and is currently structures' estimate.
This module's is the folded log variance, `exp(value / 2)` in basis points, and
the case for it is measured: `drive-q-from-the-range` put the range-vs-close
estimator ratio at 0.648 within strata on FX and 0.667 on 371 of 392 equities,
and the band holds coverage at 1.02 to 1.10 where a Gaussian of the same
nominal width degrades to 14.80.
"""

from __future__ import annotations

import math

#: The topic. Separate from `structures.signals` on purpose: two producers on a
#: topic named after one of them is how a consumer loses track of which
#: produced what, and a separate topic is one subscription to remove.
TOPIC = "statespace.proposals"

#: Standardised surprise that counts as a trigger. 3.0 rather than 5.0 because
#: `origin-returns-turn-at-z-one-three` measured returns turning at z 1.3 to
#: 1.95 and non-returners reaching 2.2, so z 2.5 already misses 85-89% of them.
#: The 5-sigma figure came from a bar-level anomaly study, not from this
#: service's standardised innovation, and the two are not the same scale.
TRIGGER = 3.0

#: Reward to risk the geometry is solved for.
TARGET_R = 2.0

#: Stop distance in units of the feed's own per-bar volatility.
STOP_VOL = 2.0

#: The base rate this module reports. **0.50, which is below the desk's
#: configured floor of 0.51**, because direction is a coin here and reporting
#: 0.51 would be clearing a gate rather than measuring anything.
BASE_RATE = 0.5


def volatility_bps(readout) -> float:
    """Per-bar return volatility in basis points, from the folded log variance.

    `readout.value` is log variance in the space the members were fitted in, so
    `exp(value / 2)` is a return standard deviation and `* 1e4` is basis
    points. Nothing here converts a spread column, which is in points and whose
    conversion `spread-column-is-in-points` records as a 476% error.
    """
    return math.exp(float(readout.value) / 2.0) * 1e4


def direction_of(bar: dict) -> int:
    """Sign of the triggering bar's body, which is the continuation side.

    A doji takes no side rather than defaulting to long: a bar whose open and
    close agree has expressed no direction, and `0` lets the caller drop the
    proposal instead of inventing one.
    """
    try:
        opened = float(bar.get("open", 0.0))
        closed = float(bar.get("close", 0.0))
    except (TypeError, ValueError):
        return 0
    if closed > opened:
        return 1
    if closed < opened:
        return -1
    return 0


def proposal_for(
    readout,
    bar: dict,
    *,
    trigger: float = TRIGGER,
    target_r: float = TARGET_R,
    stop_vol: float = STOP_VOL,
) -> dict[str, object] | None:
    """One proposal, or `None` if this bar is not one.

    Returns the signal contract rather than an Intent, for the reason the module
    docstring gives: the strategies build the Intent, and reusing their layer
    keeps the measured sizing and risk rather than reimplementing it.
    """
    surprise = abs(float(readout.surprise))
    if surprise < trigger:
        return None
    side = direction_of(bar)
    if side == 0:
        return None
    vol = volatility_bps(readout)
    if not (vol > 0) or not math.isfinite(vol):
        return None

    reach = readout.covering(0.90)
    features: dict[str, float] = {
        "vol_bps": round(vol, 4),
        "surprise": round(float(readout.surprise), 4),
        "stop_vol": float(stop_vol),
        "target_r": float(target_r),
        # **A touch probability, not a win probability.** See the docstring: the
        # desk's `probability` gate is about reaching a level, and a win
        # probability for a 2R target cannot exceed 1/3 on a driftless path.
        "probability": round(_touch(readout, target_r * stop_vol), 4),
        "base_rate_up": BASE_RATE,
        "log_variance": round(float(readout.value), 6),
        "spread": round(float(readout.spread), 6),
    }
    if reach is not None:
        features["band_coverage"] = round(float(reach.coverage), 4)
    if getattr(readout, "stretch", 0.0):
        features["stretch"] = round(float(readout.stretch), 4)

    return {
        "feed": str(readout.feed),
        "interval": str(readout.interval),
        "time": float(readout.at),
        "direction": side,
        # Routed on by `notifications/filters.py` and stamped by `agents`, so it
        # must be the same word in both places or a card renders as the wrong
        # shape - which is how `NOTIFY_SHAPES` silently dropped every statespace
        # alert while the path itself worked.
        "shape": "statespace",
        "confluence": ("statespace:surprise",),
        "detail": _detail(readout, side, vol),
        "features": features,
    }


def _touch(readout, distance_vol: float) -> float:
    """P(touch a level `distance_vol` volatilities away), or 0.0 if unknown.

    Delegated to the readout, because optional stopping leaves two degrees of
    freedom in four quantities and a caller choosing all four is choosing a
    contradiction - `facade.Readout.barrier` says so and `least_horizon` is
    what says which combinations are not even reachable.
    """
    try:
        got = readout.barrier(probability=0.5, horizon=float(distance_vol))
    except Exception:
        return 0.0
    if not isinstance(got, dict):
        return 0.0
    for key in ("probability", "touch", "p"):
        if key in got:
            try:
                return max(0.0, min(1.0, float(got[key])))
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _detail(readout, side: int, vol: float) -> str:
    """Plain words. No directional verb, for the reason the alert line has none.

    The alert vocabulary on this service is deliberately free of up, down,
    bullish and bearish, because a variance service using them reads as a price
    forecast. This line therefore says what printed and how big it was, and
    leaves `direction` to carry the side as a field rather than as prose.
    """
    which = "higher" if side > 0 else "lower"
    return (
        f"a move about {abs(float(readout.surprise)):.1f} times the usual size "
        f"just printed and closed {which}; typical bar is {vol:.1f} bp"
    )
