"""One model, three subjects: a level, an instrument, a relationship.

This module is the thesis's central claim written as code rather than as prose.
`linear.Gaussian` does not know what it is tracking. What changes between the
three is only **what the three numbers mean and what a measurement is**:

| | the state | a measurement | the band |
| --- | --- | --- | --- |
| `LEVEL` | where the level is | a touch price | the zone |
| `INSTRUMENT` | this name against its kind | its deviation from its family | how far is normal |
| `RELATION` | the fair spread of a set | the realised spread | the deviation's dispersion |

Statistical arbitrage is not a second system here. It is `RELATION`: level
becomes relationship, distance becomes deviation, zone becomes deviation
dispersion, and the slope becomes a drifting hedge ratio. If that reads as a
coincidence, it is the thesis being right about something; if the three need
genuinely different filters, that is a finding and this table is where it will
show up.

## What each `Subject` is for

It carries the things a feature list never writes down - the units, what the
measurement actually is, and **where the noise parameters came from**. I8 in the
spec is precisely this complaint: "state, input or output - the question a
feature list never asks". A subject that cannot say what its `jerk` means in
words has not been specified, whatever its value is.

**Every `jerk` below is a placeholder and every one says so.** None has been
fitted. The fit is the same shape for all three -
`var(m2 - m1) = jerk_equivalent * dt + 2R` over measurement pairs, slope the
process variance and intercept twice the measurement noise - and for `LEVEL` it
is blocked on the structures outcomes journal recording a raw touch price, which
it does not. Shipping a number without saying that is how
`DRIFT_VOL_PER_HOUR = 0.02` came to be applied at every timeframe without anyone
having measured it once.

## Scale

All three work in **volatility units**, not price. That is not tidiness: it is
the condition that lets one model span fifty instruments, and `vol/volatility.py`
is explicit that a fixed threshold in price units encodes one market regime and
quietly stops describing the next. So `jerk` is in volatility units squared per
hour to the fifth, and a subject is responsible for dividing by its own unit
before it calls `update`.

**And the unit is per bar while the rate is per hour.** That inconsistency is
real, it is live in production, and it is I6 - the volatility unit is an EWMA of
the absolute close-to-close move with a 60-bar half-life, one estimate per
`(feed, interval)`, so at 4h that half-life is ten days. Nothing here fixes it;
`rates.py` is where the fix starts, and this note is here so the next person does
not have to rediscover it from the arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass

from .linear import Gaussian


@dataclass(frozen=True, slots=True)
class Subject:
    """What the three numbers mean for one kind of tracked quantity."""

    #: Short name, used in scores and logs.
    name: str
    #: What the state's first component is, in words.
    quantity: str
    #: What arrives as a measurement, in words. If this cannot be written as one
    #: clause, the subject is not specified yet.
    measurement: str
    #: Units the state is carried in. Volatility units throughout - see the
    #: module note on why that is load-bearing rather than tidy.
    units: str
    #: Jerk spectral density, (units)^2 / hour^5. A placeholder in every case.
    jerk: float
    #: Measurement variance `R`, in units squared.
    noise: float
    #: Where `jerk` and `noise` came from. "placeholder" is an acceptable answer
    #: and a measured one is the goal; a blank is not allowed.
    provenance: str

    def filter(self, *, at: float | None = None) -> Gaussian:
        """A filter configured for this subject. Nothing is wired to it."""
        return Gaussian(jerk=self.jerk, at=at, p00=1.0)


#: **A level is a latent price, observed by touches.** The subject the desk
#: already runs, in the form the spec says it should take.
#:
#: `noise` is the one number here that *is* measured: `TOUCH_NOISE_VOL = 0.40`
#: from 2026-10-09, two independent estimates agreeing, replacing a chosen 0.5 -
#: so `R = 0.40^2`. `jerk` is not: its production counterpart is
#: `DRIFT_VOL_PER_HOUR = 0.02`, chosen per hour and applied at every timeframe,
#: and the fit that would settle it needs a raw touch price the outcomes journal
#: does not record.
LEVEL = Subject(
    name="level",
    quantity="the price at which this level currently sits",
    measurement="the price at which a touch resolved",
    units="volatility units of the series' own bar",
    jerk=1e-4,
    noise=0.40**2,
    provenance=(
        "noise measured 2026-10-09 (TOUCH_NOISE_VOL, two independent estimates); "
        "jerk a placeholder - DRIFT_VOL_PER_HOUR = 0.02 was chosen, never fitted, "
        "and the fit is blocked on the outcomes journal recording a touch price"
    ),
)

#: **An instrument is a latent position against its own kind**, observed by how
#: far it has moved from its family. Improvement I11.
#:
#: Everything on the instrument side today is a name against *itself* - its
#: volatility, its trendiness, its busyness. This is the second axis: gold
#: against silver and platinum, BTC against the majors. The rate is the one thing
#: a rolling PCA cannot give, because a subtraction has no memory of which way the
#: residual was heading.
#:
#: **Measured twice and failed twice**, and the failures are specific rather than
#: general: `research/docs/pca-residuals.md` returned net Sharpe -0.97 against an
#: OU control of +10.47, and `research/docs/peering.md` found the synthetic
#: control showing a larger effect than the real assets. Both tested the residual
#: as a market-neutral **book**, which must clear its own hedging costs. As an
#: instrument *state* it carries no hedge, no turnover and no funding - which is
#: the one escape left and the reason this subject exists at all.
INSTRUMENT = Subject(
    name="instrument",
    quantity="this instrument's standardised deviation from its family",
    measurement="its move this bar less its family's, over its own volatility",
    units="volatility units of its own bar",
    jerk=1e-3,
    noise=1.0,
    provenance=(
        "both placeholders; the family itself is unbuilt (factor.py). The prior "
        "evidence is against the tradeable form of this - see pca-residuals.md "
        "and peering.md - and for the state form there is none either way"
    ),
)

#: **A relationship is a latent fair spread, observed by the realised one.**
#: Statistical arbitrage, which is this thesis with the subject changed.
#:
#: The mapping is exact rather than analogous: level becomes relationship,
#: distance becomes deviation, zone becomes deviation dispersion, and the slope
#: becomes a **drifting hedge ratio** - which is the part a static cointegrating
#: vector cannot express and the reason a state space is the right form for it.
#:
#: **N assets, not two.** The spec is specific: the N-k residual directions *are*
#: the cointegrating space, so a pair is the degenerate case rather than the
#: subject. One universe, not one model per sector, because a per-sector model
#: cannot see rotation between sectors. Which leg to take is loading strength
#: times standardised deviation times reversion speed.
#:
#: Nothing here is built. The subject is declared so that the shared filter is
#: not quietly specialised to levels before the other two arrive, which is how a
#: "general" model ends up with a level-shaped hole in it.
RELATION = Subject(
    name="relation",
    quantity="the fair spread between this set of instruments",
    measurement="the realised spread, at the current hedge ratio",
    units="volatility units of the spread's own dispersion",
    jerk=1e-3,
    noise=1.0,
    provenance=(
        "both placeholders; nothing is built. The pairwise question is genuinely "
        "open - families.md is entirely univariate - and the Deriv synthetics "
        "case has three outcomes of which two are fatal: a shared stream makes "
        "the deviation zero, independent streams make it a random walk, and only "
        "shared-plus-idiosyncratic is tradeable"
    ),
)

#: Every subject, so a test can assert the invariants hold for all of them rather
#: than for whichever one was added first.
SUBJECTS: tuple[Subject, ...] = (LEVEL, INSTRUMENT, RELATION)
