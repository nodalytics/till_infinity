"""Cross-sectional pooling: the members of one cohort, oriented and combined.

`pooling.py` combines several *filters* on one feed. This combines several
*feeds* on one subject, which is a different axis and answers a different
question: given that EURUSD and USDJPY both carry USD, how much independent
information is there in reading both?

`regime-granularity.md` measured it. Two-state regime labels, pairwise
agreement against a circular-rotation null, on 66 instruments at 1h:

| cohort | volatility z | drift z |
| --- | ---: | ---: |
| fx emerging | +55.1 | **+104.7** |
| crypto | +24.9 | +65.6 |
| equity indices | +45.8 | +70.5 |
| us banks | +17.6 | +27.6 |
| **between traded families** | **+18.5** | **-1.7** |
| between synthetic families *(control)* | +0.2 | +0.1 |

So **volatility pools everywhere, including across cohorts, and direction
pools only inside one**. Nine synthetic families sit at the null on both, which
is what licenses reading the rest.

## This publishes exposure, not a forecast

The temptation is to read a +104.7 as a signal. It is not one, and this desk
has already measured why: `direction-is-closed-not-just-null` found the
directional gate earning 2% of a spread *while correctly finding a planted
drift at z +2.90*, and `prod-probability-up-needs-halving` put the published
`probability_up` at 0.5092 once its overlapping touches were removed. A shared
drift regime says the members **move together**, which is a statement about
co-movement, and co-movement is a risk quantity.

So the reading this module publishes is `independent`: how many independent
bets a set of simultaneous positions in one cohort actually amounts to. For `n`
members whose oriented signs agree pairwise at rate `a`, the implied pairwise
correlation is `2a - 1` and

    independent = n / (1 + (n - 1) * max(0, 2a - 1))

which is the standard effective-sample-size form. Six fx emerging positions at
the measured agreement are **not** six bets. Nothing here emits a direction,
and `rate` is carried as a reading for a consumer that has measured its own
use for it - not as a recommendation.

## What is actually pooled here, and why orientation is inert for it

**This service folds log variance, so the quantity on the wire is a
volatility rate - not a price drift.** That matters twice.

`|log return|` is invariant under price inversion, so **volatility carries no
sign**: EURUSD's variance rising and USDJPY's variance rising are the same
event whatever side of the pair USD sits on. The wired pool therefore orients
every member `+1`, and `Pool.oriented` is `False` by default. Orientation
below is kept because it is measured and tested and because `hmm.py` is a
direction source that could feed this pool later - but applying it to a
volatility rate would be wrong, not merely unnecessary.

The level is **not** pooled. `value` is log variance, and BTCUSD's sits far
above EURUSD's, so averaging it across a cohort mixes scales rather than
combining estimates. `stretch` is pooled instead: it is in half-band units
against each feed's own anchor, which `facade.payload_for` already records as
comparable across feeds because that band's coverage is measured.

The field is `rate`, never `drift`. Two naming hazards were already corrected
in this package for the same reason - `side` became `variance_side` and the
alert kind `break` became `surprise` - because a bare directional word on a
service that folds variance reads as a price claim.

## Orientation is declared, never fitted

The measurement found this the hard way. The fx majors read drift agreement
**z -10.0** - far *below* the null - because EURUSD and USDJPY carry USD on
opposite sides, so a USD trend labels them oppositely and the statistic read
the strongest shared drift in the cache as an absence of one. The same family
read |correlation| z **+178.6**.

Orientation therefore comes from the symbol against a cohort's declared
`reference` leg, with **zero estimated parameters**. Fitting it would be the
mistake `never-test-cointegration-on-a-live-ratio` records, where a relationship
fitted on a live series produced a null Dickey-Fuller t of -29 from noise; an
orientation re-fitted each bar would chase the same noise and flip sign in
quiet periods. A cohort with no shared leg declares `reference=None` and every
member orients `+1`, which is correct for equities, indices and crypto - they
are all long one factor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

#: How long a member's reading counts toward its cohort. A cohort pooled from
#: stale members overstates agreement, because the stale ones cannot disagree.
FRESH_SECONDS = 900.0

#: Below this many live members a cohort publishes nothing. Two members give a
#: single pair, so agreement is 0 or 1 and `independent` is a coin flip.
LEAST_LIVE = 3


@dataclass(frozen=True)
class Group:
    """One cohort: a shared leg, if any, and the feeds that carry it."""

    name: str
    reference: str | None
    feeds: tuple[str, ...]


#: The cohorts, named for the leg they share rather than for a market. `softs`
#: and `energy` share a factor that is not a currency, so they orient `+1`.
GROUPS: tuple[Group, ...] = (
    Group(
        "fx majors", "USD", ("EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "USDJPY")
    ),
    Group("fx emerging", "USD", ("USDMXN", "USDZAR", "USDNOK", "USDPLN", "USDSEK", "USDCNH")),
    Group("jpy crosses", "JPY", ("EURJPY", "GBPJPY", "AUDJPY", "CHFJPY", "USDJPY")),
    Group("crypto", None, ("BTCUSD", "ETHUSD", "SOLUSD", "LTCUSD")),
    Group("equity indices", None, ("Germany_40", "France_40", "UK_100", "Japan_225", "Europe_50")),
    Group("energy", None, ("US_Oil", "UK_Brent_Oil", "NGAS")),
)


def orient(feed: str, reference: str | None) -> int:
    """+1 if the feed rises when the reference leg strengthens, -1 if it falls.

    `0` means the feed does not carry the reference at all, and such a feed
    contributes nothing rather than defaulting to `+1` - a silent `+1` on a
    non-member is how a cohort acquires a member whose sign means nothing.
    """
    if reference is None:
        return 1
    symbol = feed.upper().replace("_", "")
    leg = reference.upper()
    if symbol.startswith(leg):
        return 1
    if symbol.endswith(leg):
        return -1
    return 0


@dataclass(frozen=True)
class Reading:
    """What one cohort currently says. `independent` is the point of it."""

    cohort: str
    live: int
    interval: str
    #: Precision-weighted mean of the members' **log-variance rate**. A
    #: reading about volatility, not a direction and not a recommendation.
    rate: float
    rate_sd: float
    #: Pairwise rate at which members' rate signs agree, in [0, 1]. 0.5 is
    #: independence; the rotation-null measurement put real cohorts far above it.
    agreement: float
    #: Effective number of independent readings among `live` members - and so
    #: of independent bets among that many simultaneous positions.
    independent: float
    #: Mean stretch against each member's own anchor, in half-band units, which
    #: is the one variance quantity comparable across feeds.
    stretch: float

    def to_dict(self) -> dict[str, float | str | int]:
        return {
            "cohort": self.cohort,
            "cohort_interval": self.interval,
            "cohort_live": self.live,
            "cohort_rate": round(self.rate, 8),
            "cohort_rate_sd": round(self.rate_sd, 8),
            "cohort_agreement": round(self.agreement, 4),
            "cohort_independent": round(self.independent, 3),
            "cohort_stretch": round(self.stretch, 4),
        }


@dataclass
class _Seen:
    rate: float
    rate_sd: float
    stretch: float
    sign: int
    at: float


@dataclass
class Pool:
    """Accumulates per-feed readings and pools them per cohort **and interval**.

    The interval is part of the key, not a detail. A cohort that mixed EURUSD's
    1m rate with GBPUSD's 5m rate would be combining incomparable quantities
    and reporting the result as agreement.
    """

    groups: tuple[Group, ...] = GROUPS
    fresh: float = FRESH_SECONDS
    least: int = LEAST_LIVE
    #: Whether members are signed against their cohort's reference leg. **False
    #: for the wired path**, because the subject there is a volatility rate and
    #: volatility carries no sign - see the module docstring. A caller pooling a
    #: directional quantity sets it, and then a feed that does not carry the
    #: reference drops out of that cohort instead of voting meaninglessly.
    oriented: bool = False
    _seen: dict[tuple[str, str], dict[str, _Seen]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._of: dict[str, list[tuple[str, int]]] = {}
        for group in self.groups:
            for feed in group.feeds:
                sign = orient(feed, group.reference) if self.oriented else 1
                if sign:
                    self._of.setdefault(feed, []).append((group.name, sign))

    def cohorts_of(self, feed: str) -> tuple[str, ...]:
        """Every cohort this feed belongs to. A feed can carry two legs."""
        return tuple(name for name, _ in self._of.get(feed, ()))

    def observe(
        self,
        feed: str,
        interval: str,
        rate: float,
        rate_sd: float,
        stretch: float,
        when: float,
    ) -> tuple[str, ...]:
        """Record one feed's readout at one interval. Returns cohorts touched."""
        touched = []
        for name, sign in self._of.get(feed, ()):
            signed = rate * sign
            self._seen.setdefault((name, interval), {})[feed] = _Seen(
                rate=signed,
                rate_sd=abs(rate_sd),
                stretch=stretch,
                # An exactly-zero rate takes no side rather than being folded in
                # as positive, which would let a cold member manufacture
                # agreement it has not expressed.
                sign=0 if signed == 0.0 else (1 if signed > 0 else -1),
                at=when,
            )
            touched.append(name)
        return tuple(touched)

    def read(self, cohort: str, interval: str, now: float) -> Reading | None:
        """Pool one cohort at one interval, or `None` if too few are fresh."""
        members = self._seen.get((cohort, interval))
        if not members:
            return None
        live = [s for s in members.values() if now - s.at <= self.fresh and s.sign != 0]
        if len(live) < self.least:
            return None
        weights = [1.0 / (s.rate_sd**2) if s.rate_sd > 0 else 0.0 for s in live]
        total = sum(weights)
        if total > 0:
            rate = sum(w * s.rate for w, s in zip(weights, live, strict=True)) / total
            rate_sd = math.sqrt(1.0 / total)
            stretch = sum(w * s.stretch for w, s in zip(weights, live, strict=True)) / total
        else:
            # Every member reported a zero spread, so precision says nothing and
            # an equal-weight mean is the honest fallback. `rate_sd` is 0.0 to
            # say "unstated", not "certain".
            rate = sum(s.rate for s in live) / len(live)
            rate_sd = 0.0
            stretch = sum(s.stretch for s in live) / len(live)
        agreement = agreement_of(tuple(s.sign for s in live))
        return Reading(
            cohort=cohort,
            interval=interval,
            live=len(live),
            rate=rate,
            rate_sd=rate_sd,
            agreement=agreement,
            independent=independent_of(len(live), agreement),
            stretch=stretch,
        )

    def readings(self, interval: str, now: float) -> tuple[Reading, ...]:
        return tuple(
            got
            for got in (self.read(group.name, interval, now) for group in self.groups)
            if got is not None
        )


def agreement_of(signs: tuple[int, ...]) -> float:
    """Pairwise rate at which signs agree. 0.5 is independence, not 0."""
    live = [s for s in signs if s != 0]
    if len(live) < 2:
        return 0.0
    up = sum(1 for s in live if s > 0)
    down = len(live) - up
    pairs = len(live) * (len(live) - 1) / 2.0
    same = up * (up - 1) / 2.0 + down * (down - 1) / 2.0
    return same / pairs


def independent_of(live: int, agreement: float) -> float:
    """Effective independent bets among `live` positions agreeing at `agreement`.

    `2a - 1` is the implied pairwise correlation, floored at zero: members that
    agree *less* than chance are not anti-correlated information to be credited,
    they are a small sample, and crediting them would let a cohort claim more
    independent bets than it has members.
    """
    if live <= 1:
        return float(max(live, 0))
    rho = max(0.0, 2.0 * agreement - 1.0)
    return live / (1.0 + (live - 1) * rho)
