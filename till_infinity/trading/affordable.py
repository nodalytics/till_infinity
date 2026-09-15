"""Which instruments this account cannot afford to trade, before one is signalled.

`sizing.lots` already refuses a trade whose minimum lot would breach the risk
budget, and it refuses **rather than rounding up** - which is the failure worth
naming, because placing `volume_min` anyway is how a 0.25% risk budget quietly
becomes 3%.

So the per-trade guard is sound. What is missing is the **catalogue**: that
refusal arrives one signal at a time, discovered and re-discovered, so an
instrument nobody can afford is still watched, still modelled, still signalled
and still refused, for ever. Nothing anywhere says "this feed is not tradeable
at this equity", and that is a different sentence from "this trade was refused".

## What makes an instrument unaffordable

Three things multiply, and only the first is obvious.

* **The minimum lot.** A broker's `volume_min` sets a floor under position size,
  and the loss that floor implies is the smallest loss the instrument can
  produce.
* **The stop the broker will accept.** `stops_level` forbids a stop closer than
  some distance, so on a quiet instrument the *narrowest legal* stop can still
  be wide - and it is the wider of "what the strategy wants" and "what the
  broker permits" that gets placed.
* **What a stop actually costs**, which is not the distance it is drawn at.
  `sizing.lots` inflates by measured slippage of 0.087, two thirds of it the
  exit, because a broker stop is a market order once triggered and fills through
  the spread. On the spike side of Boom and Crash that multiple is far larger -
  `research/generators.md` measured every adverse tick there as a spike - which
  is exactly the case where one loss is catastrophic.

## The verdict this returns

Not a number but a decision, because the useful output is a list to stop
watching:

* **affordable** - the budget covers a sensible size.
* **minimum only** - the budget covers `volume_min` and nothing above it, so
  every trade is the same size whatever the conviction, and sizing has stopped
  being a lever.
* **unaffordable** - `volume_min` alone breaches the budget. The desk will
  refuse every signal on this feed, so the honest thing is to stop producing
  them.

**It is deliberately not automatic.** Dropping a feed is a decision about what
the desk is for, and an account that grows makes an unaffordable instrument
affordable again without anything changing about the instrument. This reports;
somebody decides.

## Its runtime counterpart

This is a catalogue, produced on demand by `till-infinity trading affordable`.
The refusal it predicts happens in `sizing.lots`, which declares
`trading.unaffordable_refusal` - so `shared/effects.py` answers the other half
of the question without anybody running a report. **If that effect never fires,
this catalogue is describing a problem the desk does not have.** If it fires
constantly, instruments need dropping rather than being re-refused one signal at
a time, for ever, which is the situation this module was written to make
visible.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import SymbolSpec
from .sizing import lots

#: Stop distances to test, in volatility units. The desk's own stop multiples
#: live in this range, and an instrument that is affordable at four sigma and
#: not at one is affordable only for trades nobody wants to take.
STOPS = (1.0, 2.0, 4.0)

#: Above this share of equity at the minimum lot, an instrument is reported as
#: unaffordable even when the configured risk budget happens to permit it.
#: A single position that can take a fifth of the account is a different kind of
#: risk from a budget overrun, and the budget is not always set with that in
#: mind.
CATASTROPHIC = 0.20


@dataclass(slots=True)
class Affordability:
    """One instrument, and whether this account can trade it.

    Not `Verdict`, which `trading.models` already uses for whether a *trade*
    passed its gates. Two objects called the same thing in one package is how a
    reader ends up sure they know what an import means.
    """

    feed: str
    symbol: str
    stop_units: float
    min_lot_risk: float
    share_of_equity: float
    volume: float
    verdict: str
    reason: str = ""

    @property
    def tradeable(self) -> bool:
        return self.verdict == "affordable"

    def to_dict(self) -> dict:
        return {
            "feed": self.feed,
            "symbol": self.symbol,
            "stop_units": self.stop_units,
            "min_lot_risk": round(self.min_lot_risk, 2),
            "share_of_equity": round(self.share_of_equity, 4),
            "volume": self.volume,
            "verdict": self.verdict,
            "reason": self.reason,
        }


def judge(
    spec: SymbolSpec,
    *,
    feed: str,
    equity: float,
    risk_fraction: float,
    price: float,
    vol_bps: float,
    stop_units: float = 2.0,
    slippage: float = 0.0,
) -> Affordability:
    """Can this account trade this instrument at a `stop_units` stop?

    Sized through `sizing.lots` rather than by arithmetic repeated here, so the
    verdict is the same decision the desk makes at the moment of the trade. A
    report that disagrees with the thing it reports on is worse than none.

    The stop tested is the wider of what the strategy asks for and what the
    broker will accept: a strategy stop inside `stops_level` is not the stop
    that gets placed, and pricing the instrument on it would call something
    affordable that is not.
    """
    wanted = price * (vol_bps / 10_000.0) * stop_units
    distance = max(wanted, spec.min_stop_distance)
    if distance <= 0 or equity <= 0:
        return Affordability(
            feed=feed,
            symbol=spec.symbol,
            stop_units=stop_units,
            min_lot_risk=0.0,
            share_of_equity=0.0,
            volume=0.0,
            verdict="unknown",
            reason="no stop distance or no equity",
        )

    sized = lots(
        spec,
        equity=equity,
        risk_fraction=risk_fraction,
        stop_distance=distance,
        slippage=slippage,
    )
    at_min = spec.volume_min * sized.loss_per_lot if sized.loss_per_lot > 0 else 0.0
    share = at_min / equity if equity > 0 else 0.0

    if not sized.ok:
        verdict = "unaffordable"
        reason = sized.reason
    elif share >= CATASTROPHIC:
        # The budget permitted it and it is still too large to hold.
        verdict = "unaffordable"
        reason = f"one minimum lot is {share:.1%} of equity"
    elif sized.volume <= spec.volume_min:
        verdict = "minimum only"
        reason = "the budget buys the minimum lot and nothing above it"
    else:
        verdict = "affordable"
        reason = ""

    return Affordability(
        feed=feed,
        symbol=spec.symbol,
        stop_units=stop_units,
        min_lot_risk=at_min,
        share_of_equity=share,
        volume=sized.volume,
        verdict=verdict,
        reason=reason,
    )


def survey(
    specs: dict[str, SymbolSpec],
    *,
    equity: float,
    risk_fraction: float,
    prices: dict[str, float],
    vols: dict[str, float],
    slippage: float = 0.0,
    stops: tuple[float, ...] = STOPS,
) -> list[Affordability]:
    """Every instrument judged at each stop width, worst first.

    Sorted by how much of the account a single minimum lot puts at risk, because
    that is the number that decides whether one loss is survivable - and it is
    the question that motivated this, not the average outcome.
    """
    out: list[Affordability] = []
    for feed, spec in sorted(specs.items()):
        price = prices.get(feed, 0.0)
        vol = vols.get(feed, 0.0)
        if price <= 0 or vol <= 0:
            continue
        out.extend(
            judge(
                spec,
                feed=feed,
                equity=equity,
                risk_fraction=risk_fraction,
                price=price,
                vol_bps=vol,
                stop_units=stop_units,
                slippage=slippage,
            )
            for stop_units in stops
        )
    return sorted(out, key=lambda v: -v.share_of_equity)


def unaffordable(verdicts: list[Affordability]) -> list[str]:
    """Feeds that cannot be traded at **any** of the stop widths tested.

    Any rather than all: an instrument affordable only at a four-sigma stop is
    affordable only for trades nobody wants to take, but it is not unaffordable,
    and calling it so would drop a feed the desk can still use.
    """
    by_feed: dict[str, list[Affordability]] = {}
    for v in verdicts:
        by_feed.setdefault(v.feed, []).append(v)
    return sorted(
        feed for feed, rows in by_feed.items() if all(r.verdict == "unaffordable" for r in rows)
    )
