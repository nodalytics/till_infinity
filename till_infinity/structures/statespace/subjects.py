"""One model, three subjects: a level, an instrument, a relationship.

This module is the thesis's central claim written as code rather than as prose.
`linear.Gaussian` does not know what it is tracking. What changes between the
three is only **what the three numbers mean and what a measurement is**:

| | the state | a measurement | the band |
| --- | --- | --- | --- |
| `LEVEL` | where the level is | a touch price | the zone |
| `INSTRUMENT` | this name against its kind | its deviation from its family | how far is normal |
| `RELATION` | the fair spread of a set | the realised spread | the deviation's dispersion |
| `DISPERSION` | how wide a bar is | its range-based variance, logged | the width's own spread |
| `RELATION_DISPERSION` | how wide a deviation swings | its variance, logged | the width's spread |
| `TURN_DEPTH` | how far the next swing runs | a swing's size, logged | the depth's spread |

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
process variance and intercept twice the measurement noise - and for `LEVEL` the
measurements are there: `entry` on the episode record is the touch price, at
eight decimal places, 250,412 of them as of 2026-10-10. An earlier version of
this file said that was blocked on a field the journal does not record; it was
the *resolutions* write that lacks it, not the episode write. Shipping a number
without saying it is a placeholder is how
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

    #: Which member this subject wants, by the name `family.members()` uses.
    #: **Item 7 on the README's priority list**, which complained that
    #: `filter()` always returned a `Gaussian` so *"no subject can declare that
    #: it wants the reverting member - which is now the one with evidence
    #: behind it"*. A subject and a member are composed here rather than paired
    #: by hand at every call site.
    member: str = "kalman"

    #: Initial state variance, `P(0)`. Named because the list named it: a
    #: subject that cannot say how uncertain it starts is a subject whose first
    #: reading is being handled by a default nobody chose.
    px0: float = 1.0

    #: `"level"` or `"dispersion"` - which half of the problem this subject is
    #: about. Added 2026-10-17 with the emission rule in the README: every
    #: member and component forecasts dispersion, and a subject that tracks a
    #: level has to say so, because the level half is the one this desk has
    #: measured closed. It is not cosmetic - a harness can select the
    #: dispersion subjects and a reader can see at a glance which subjects are
    #: claiming the open half.
    tracks: str = "level"

    def filter(self, *, at: float | None = None) -> object:
        """A filter configured for this subject. Nothing is wired to it.

        Returns the member this subject asked for, carrying its own `jerk` and
        `px0` where the member has them. A member that takes neither gets
        neither, rather than being handed a parameter that means nothing to
        it - which is why this inspects rather than assumes.
        """
        from .family import composable

        built = composable()[self.member]
        try:
            engine = built(jerk=self.jerk, at=at, p00=self.px0)  # type: ignore[call-arg]
        except TypeError:
            # The member does not take the integrated-jerk parameters. That is
            # a true statement about it - `reverting` has `theta`, `swarm` has
            # `wander` - so it gets its own defaults and the subject's `jerk`
            # is not silently forced into a field that does not mean the same
            # thing.
            engine = built(at=at)  # type: ignore[call-arg]
        return engine


#: **A level is a latent price, observed by touches.** The subject the desk
#: already runs, in the form the spec says it should take.
#:
#: `noise` is the one number here that *is* measured: `TOUCH_NOISE_VOL = 0.40`
#: from 2026-10-09, two independent estimates agreeing, replacing a chosen 0.5 -
#: so `R = 0.40^2`. `jerk` is not: its production counterpart is
#: `DRIFT_VOL_PER_HOUR = 0.02`, chosen per hour and applied at every timeframe
#: and never fitted - though the fit is available, not blocked: the episode
#: record carries `entry`, the touch price, at eight decimal places.
LEVEL = Subject(
    name="level",
    quantity="the price at which this level currently sits",
    measurement="the price at which a touch resolved",
    units="volatility units of the series' own bar",
    jerk=1e-4,
    noise=0.40**2,
    provenance=(
        "noise measured 2026-10-09 (TOUCH_NOISE_VOL, two independent estimates); "
        "jerk a placeholder - DRIFT_VOL_PER_HOUR = 0.02 was chosen and never "
        "fitted; the fit is available on the episode record's touch price"
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
#: **The cost, as a quantity with its own dynamics.** Every cost gate on this
#: desk uses a constant - one spread, or 4bp - and the SEC's payment-for-order-
#: flow study (DERA, January 2025) finds the number moves, and moves with the
#: *composition of the flow* rather than with volatility alone: after the
#: shock they measure, implied spreads, trade sizes and return volatility all
#: rise together for about $4.8 million a day in extra cost.
#:
#: A gate that forecasts the spread is a different gate from one that averages
#: it, and this is the subject that would carry it. `reverting` is the member
#: it asks for: a spread mean-reverts to a level set by the venue and the
#: session, and a random walk would let it wander to zero or to infinity,
#: neither of which a spread does.
#:
#: **The null is hard and is named here so it cannot be forgotten**: a trailing
#: average of the spread, out of sample. Nothing in this repository has beaten
#: a trailing average of the thing it is forecasting.
SPREAD = Subject(
    name="spread",
    quantity="the fair cost of crossing, for this instrument at this venue",
    measurement="the realised spread, in volatility units of the instrument",
    units="volatility units of the instrument's own bar move",
    jerk=1e-4,
    noise=0.25,
    provenance=(
        "**measured, and the answer is that this subject does not earn its "
        "place.** `statespace-spread.md` filtered the quoted spread on tick "
        "data and found it nearly constant: its hour-of-day profile is 1.02x "
        "to 1.09x peak to trough where volatility's is 2.7x to 3.7x, and on "
        "XAUUSD and every generated market the spread is flat enough that "
        "every forecaster scores an error of 0.000. Only BTCUSD has a "
        "forecastable spread at all, and there a five-observation trailing "
        "mean beats the filter - 0.060 against 0.062 - with a constant at "
        "0.072. `theta` fits at 200 an hour on both traded pairs, a half-life "
        "of twelve seconds, which is the fit saying the spread is a constant "
        "plus noise rather than a process. The parameters above stay "
        "placeholders because fitting them is degenerate on a constant: "
        "`sigma2` and `theta` pin at opposite grid edges on the synthetics. "
        "**The practical consequence is reassuring**: the constant cost gate "
        "every harness here uses is wrong by 0.6% on XAUUSD and 7.2% on "
        "BTCUSD, so no cost-gated conclusion in the repository changes. "
        "Roll's implied spread was named here as the independent estimate "
        "and **cannot be computed from this data**: it infers the spread from "
        "bid-ask bounce in *transaction* prices, and a mid-quote has no "
        "bounce by construction, so applied to mids it reads price dynamics - "
        "it swings from 12.06x the quoted spread at 60s intervals to 1.39x at "
        "10s on the same instrument. It would need trade prices, which this "
        "desk does not store"
    ),
    member="reverting",
)


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
        "shared-plus-idiosyncratic is tradeable. **The member now exists**: "
        "`relating.Relating` carries the hedge ratio as a state, so this "
        "subject's `member` is the one place that choice is written down"
    ),
    member="relating",
)

DISPERSION = Subject(
    name="dispersion",
    quantity="log realised variance of this instrument over one bar",
    measurement="the log of the bar's range-based variance estimate",
    units="log variance, which is unconstrained - the reason it is logged",
    jerk=1e-3,
    noise=0.30,
    provenance=(
        "**both placeholders, and this subject is the README's item 6 rather "
        "than a measurement.** The argument for it is the strongest in this "
        "package and it is still an argument: price is a near-martingale - it "
        "diffuses at 1.00 to 1.07 times sqrt(h), direction is a coin in every "
        "test, and a random walk wins the point forecast at every horizon on "
        "17 to 21 of 39 series - while log-variance is persistent and "
        "forecastable, 79% of achievable with HAR-Parkinson. Everything in "
        "this family that failed on price has a reason to work here: the "
        "multi-timescale basis because HAR's win *is* the multi-scale result, "
        "`reverting` because volatility mean-reverts and price does not, a "
        "persistent anchor because variance has a level to return to. "
        "`noise` is 0.30 because a single bar's range-based variance is a "
        "noisy estimate of the bar's true variance and its log carries about "
        "that much spread; the fit has the same shape as every other subject "
        "here - `var(m2 - m1) = jerk_equivalent * dt + 2R` over measurement "
        "pairs - and the measurements are available from any OHLC history, so "
        "this is unfitted rather than unfittable. **The null is named and "
        "cheap**: HAR-Parkinson is a linear regression on three realised "
        "variances and it already captures 79%, so a state space here has a "
        "high bar and a working incumbent to beat, which is the right shape "
        "for this package"
    ),
    member="reverting",
    tracks="dispersion",
)


RELATION_DISPERSION = Subject(
    name="relation dispersion",
    quantity="log variance of the deviation between this set of instruments",
    measurement="the log of the realised variance of the deviation over one bar",
    units="log variance of the deviation",
    jerk=1e-3,
    noise=0.30,
    provenance=(
        "**placeholders, and the subject exists because the level version of "
        "it is measured closed.** Asked for on 2026-10-17 - dispersion in the "
        "relationship component - and the measurements say it is the only "
        "half worth tracking. `crossing.md` ran a 16-pair study with "
        "unrelated-instrument controls and found contemporaneous correlations "
        "of **0.27 to 0.77** on related pairs against **-0.00 to 0.32** on "
        "the controls, and concluded *there is no lead; there is "
        "simultaneity* - in a 325-pair study the largest correlation anywhere "
        "was between two unrelated instruments. So the deviation's **level** "
        "has no lead-lag to forecast, and the cost table closes it "
        "independently: the largest implied move taking the best correlation "
        "at face value is 0.089bps against a 2.35bps spread, with all sixteen "
        "pairs negative net. The deviation's **dispersion** is a different "
        "quantity and is where the relationship actually lives, which is also "
        "why `never-test-cointegration-on-a-live-ratio` matters here: "
        "`relating.Relating`'s adaptive ratio returns a null Dickey-Fuller t "
        "of -29 out of pure noise, so any level claim about a live ratio has "
        "to be fitted on a training half before it means anything. A "
        "dispersion claim does not inherit that trap, because the ratio's "
        "adaptation does not manufacture variance the way it manufactures "
        "stationarity"
    ),
    member="reverting",
    tracks="dispersion",
)


TURN_DEPTH = Subject(
    name="turn depth",
    quantity="log size of the next move between confirmed reversals",
    measurement="the completed swing's size in volatility units, logged",
    units="log volatility units",
    jerk=1e-3,
    noise=0.25,
    provenance=(
        "**ported from v1 on 2026-10-17, and one of the few measured-positive "
        "results in `structures/cycles.py`.** That module's own docstring: "
        "*the turn depth is predictable where the process reverts - skill "
        "against the running mean is negative or zero on every simulated arm "
        "and positive on 8 of 8 constructed spreads, +0.03 to +0.19*; and "
        "*how long until the turn is not - `when` scores positive on the "
        "nulls too, so its positive values are a property of the metric "
        "rather than of the series*. Depth is a magnitude and timing is not, "
        "which is the same split `dispersion-forecast.md` reached by different "
        "machinery on different data, so this belongs in the dispersion half. "
        "**The numbers do not transfer**: v1 marks a turn when price retraces "
        "`TURN_SIGMAS = 2.0` of its leg, `statespace/depths.py` uses "
        "`displacements.sequence` over confirmed pivots, and those are "
        "different events - what transfers is whether a model beats a causal "
        "running mean. Both parameters are placeholders. `noise` is 0.25 and "
        "is **not** measurement error: a swing's size is an exact distance "
        "between two confirmed extremes, so it stands for the part of the "
        "next depth no state can carry. The member named here is the honest "
        "one and not the right one - depth reverts in **level** and "
        "`reverting` reverts the *rate*, leaving the value integrated, so the "
        "family still has no value-reverting member and `depths.AR1` is the "
        "arm that stands in for it"
    ),
    member="reverting",
    tracks="dispersion",
)


#: Every subject, so a test can assert the invariants hold for all of them rather
#: than for whichever one was added first.
SUBJECTS: tuple[Subject, ...] = (
    LEVEL,
    INSTRUMENT,
    RELATION,
    SPREAD,
    DISPERSION,
    RELATION_DISPERSION,
    TURN_DEPTH,
)

#: The subjects that claim the open half of the problem. A harness pointing the
#: family at dispersion walks this rather than filtering by name.
DISPERSIONS: tuple[Subject, ...] = tuple(s for s in SUBJECTS if s.tracks == "dispersion")
