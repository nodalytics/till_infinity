"""Which state follows which, with what probability and what expected time.

`docs/todo.md`, "Statespace should track transitions, and predict the next
one": the package models *states* and reports where it is, and does not model
the transitions between them. The pieces were present and unconnected -
`switching.py` has three regimes with a hazard *rate* per state but no matrix,
`indicators/changepoint.py` carries a posterior over run length, which is the
duration a hazard needs, and `indicators/levels.py`'s `Pips` labels HH / LH /
HL / LL, which is a transition alphabet with no model over it. This is the
model over them.

## The two cautions from the todo, built in rather than noted

**The null is a matrix fitted to a walk through the same inference.** A matrix
estimated on *inferred* states inherits the inference's errors, those errors
are correlated in time, and so the diagonal is inflated by the smoother rather
than by persistence. A uniform null - `1/k` off the diagonal - cannot see that
at all: it compares a smoothed diagonal against a number no smoother produced.
`against()` therefore takes null matrices and not a constant, and
`Comparison.inflation` is the quantity that answers the question: how much of
the diagonal is the labeller.

**"Predict the next transition" is strategy rotation in a new costume.** Every
pause rule this desk tried matched random pausing at the same duty cycle, so
the control is a duty-cycle-matched random transition - `duty_cycle_matched`
below, which keeps the marginal distribution of labels *and* the number of
switches and destroys only which state follows which. `forecast_skill` scores
a predictor against it and against nothing else, because a predictor beating a
uniform guess has beaten the wrong thing.

## The duration question is the one worth asking

The todo's own conclusion: the useful version is not "when does the regime
change" but "given it has held this long, what is the hazard" - which is the
one the changepoint posterior can answer and the one a flat Markov chain gets
wrong. A plain chain assumes the hazard is flat in time already spent;
`Durations` estimates it empirically and `duration_gain` is the **nested**
likelihood test that makes the extra parameter earn itself, because a
switching model carries more parameters and has to pay for them.

`Changepoint.run_hours` is the live input to `Durations.hazard`: it is the
expected hours since the last change, marginalised over the run-length
posterior, and it is in hours rather than bars on purpose - "this has held for
two days" means the same thing on every series and "forty bars" does not.

## What the first run found, 2026-11-01: nothing, and the placebo said so

`research/ideas/statespace_discovery.py transitions` on 4,000 bars of eurusd
1h, two alphabets, 30 nulls each, against a gaussian walk as the placebo and a
planted drift and a reflected band as the positive controls.

**The `Pips` structure alphabet - HH / LH / HL / LL.** 190 confirmed swings.
Every statistic on eurusd is beaten by the walk placebo on the same statistic:

| statistic | eurusd inflation | the placebo's |
| --- | ---: | ---: |
| diagonal | **-0.0360** | +0.0066 |
| mean duration gain | +1.3754 | **+2.9144** |
| forecast excess over the duty-cycle control | +0.0940 | **+0.1808** |

The duration gain is the one that would have been published. It reads 2.1018
nats against its own walk-through-the-same-inference null at 0.7265 - percentile
1.000, p 0.0645, the floor at 30 draws two-sided - and the Weibull shapes behind
it are 0.695 and 0.782, a decreasing hazard on two of four states. **It clears
its own arm.** The placebo walk reads **4.3542 against 1.4398 at the same
percentile**, with shapes *above* one - so the decreasing hazard is the
labeller and the censoring, and the arm alone would not have said so. The
placebo pool is what said it.

The diagonal is the cleanest reading: 0.1845 against the walk's 0.2205. Real
market shape transitions are **less** persistent than a walk through the same
labeller, and against a uniform 0.25 they would have looked like a finding.
The off-diagonal alternation is mechanical for the same reason - HL to HH reads
0.635 on eurusd and 0.506 on the walk, because a swing high is followed by a
swing low by construction.

**The `VarianceRatio.regime` alphabet** is degenerate on real data and that is
itself a reading: `z` crosses +/-2 rarely enough that the sequence is 93% one
state, the mean `walk` dwell is 131 hours against 3.17 for `reverting`, and
`forecast_skill` reads hits 0.9860 against a control of 0.9877 at a stay rate
of 0.9860 - so the hit rate is the stay rate and the matrix adds nothing, which
is `most_likely_next`'s limitation measured on real data. The diagonal clears
the placebo (+0.0682 against -0.0322) and **fails its own null** at percentile
0.767, p 0.5161. Both readings have to be satisfied, and the placebo gate is a
second filter rather than a substitute for the arm.

**The power is there.** The planted-drift control clears the placebo on the
diagonal (+0.0318) and on the forecast (+0.2333), and the reflected band clears
it on the forecast (+0.1952). So a transition structure that is really present
is found, on the same code path, at the same budget.

## The censored run, which is small and biases one way

A dwell is a run of identical labels. The **last** run in a sequence has not
ended, so counting its observed length as a completed dwell biases every mean
duration downward and every hazard upward. `fit` drops it, and
`Transitions.censored` records that it did - a dropped observation that is not
reported is an observation a later reader cannot put back.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from random import Random

#: Add-alpha prior on each transition count. **Not zero**, because a null
#: matrix fitted to a walk may never visit a state the real one did, and a
#: zero row is a probability of zero for something that was simply not seen -
#: which makes a likelihood comparison infinite rather than close.
PRIOR = 0.5

#: Dwells a state needs before its own hazard is estimated rather than pooled.
#: 20 because a hazard is a ratio of two counts and a state with five dwells
#: gives a hazard of 0.0 or 0.2 and nothing in between.
LEAST_DWELLS = 20

#: Weibull shape bounds for the duration fit. Outside this the fit is chasing
#: one dwell: a shape of 0.1 is a hazard that falls by four orders of
#: magnitude over the observed range, which no regime does.
LEAST_SHAPE = 0.2
MOST_SHAPE = 5.0


@dataclass(slots=True)
class Transitions:
    """Counts, a matrix, and the dwell distribution behind the hazards.

    The alphabet is **declared** rather than discovered from the data. A
    matrix whose rows are whichever states happened to appear cannot be
    compared with one fitted to a null that visited a different subset, and
    comparing them is the entire purpose of this class.
    """

    alphabet: tuple[str, ...]
    counts: dict[tuple[str, str], int] = field(default_factory=dict)
    #: Completed dwell lengths in hours, per state.
    dwells: dict[str, list[float]] = field(default_factory=dict)
    #: The trailing run that was dropped as censored, as `(label, hours)`.
    censored: tuple[str, float] | None = None
    #: Transitions folded in, self-transitions included.
    steps: int = 0

    def __post_init__(self) -> None:
        if len(self.alphabet) < 2:
            raise ValueError(
                f"an alphabet of {len(self.alphabet)} has no transitions to model. "
                f"Declare every state the labeller can emit, including ones this "
                f"sample did not visit - a null fitted to a walk may visit others, "
                f"and the two matrices have to be the same shape to be compared."
            )

    def observe(self, previous: str, current: str) -> None:
        """One step. Self-transitions count: they are the diagonal."""
        key = (previous, current)
        self.counts[key] = self.counts.get(key, 0) + 1
        self.steps += 1

    def row(self, state: str) -> dict[str, float]:
        """P(next | this), add-alpha smoothed over the declared alphabet."""
        total = sum(self.counts.get((state, j), 0) for j in self.alphabet)
        bottom = total + PRIOR * len(self.alphabet)
        return {j: (self.counts.get((state, j), 0) + PRIOR) / bottom for j in self.alphabet}

    def matrix(self) -> dict[tuple[str, str], float]:
        """The whole transition matrix, row-normalised."""
        return {(i, j): p for i in self.alphabet for j, p in self.row(i).items()}

    def diagonal(self) -> float:
        """Mean P(stay), over the states this sample actually visited.

        **Over visited states, not over the alphabet.** A state with no
        observations has a row that is the prior - `1/k` on the diagonal - and
        averaging that in would pull a real diagonal toward chance by however
        many states went unseen, which is a property of the sample rather than
        of the persistence being measured.
        """
        seen = [i for i in self.alphabet if any(self.counts.get((i, j), 0) for j in self.alphabet)]
        if not seen:
            return math.nan
        return statistics.fmean(self.row(i)[i] for i in seen)

    def expected_time(self, state: str) -> float:
        """Mean completed dwell in hours, or `nan` with nothing to average.

        The reading `switching.py`'s per-hour hazards assert and this one
        measures: `balance_hours` and `imbalance_hours` are *parameters* there,
        and this is the same quantity estimated from a label sequence.
        """
        got = self.dwells.get(state) or []
        return statistics.fmean(got) if got else math.nan

    def durations(self, state: str) -> Durations:
        """This state's dwell distribution, as something a hazard comes off."""
        return Durations(state=state, hours=tuple(self.dwells.get(state) or ()))

    def forecast(self, state: str) -> tuple[str, float]:
        """The most likely next state and its probability.

        Ties go to **staying**, and that is a choice rather than an accident:
        the diagonal is the cell the inference inflates, so breaking a tie
        toward it is the conservative direction for a predictor that will be
        scored against a duty-cycle-matched control.
        """
        row = self.row(state)
        best = max(row, key=lambda j: (row[j], j == state))
        return best, row[best]

    def lines(self) -> list[str]:
        """The matrix and the dwell means, for a report."""
        out = [f"{self.steps} steps over {len(self.alphabet)} states"]
        for i in self.alphabet:
            row = self.row(i)
            cells = " ".join(f"{j} {row[j]:.3f}" for j in self.alphabet)
            hours = self.expected_time(i)
            held = "" if math.isnan(hours) else f" | mean dwell {hours:.2f}h"
            out.append(f"  {i}: {cells}{held}")
        if self.censored is not None:
            out.append(f"  censored trailing run: {self.censored[0]} for {self.censored[1]:.2f}h")
        return out


def fit(
    sequence: Sequence[tuple[str, float]], alphabet: Sequence[str] | None = None
) -> Transitions:
    """A matrix and a dwell distribution from `(label, hours)` observations.

    `hours` is the time that observation covers - the bar length, typically -
    so the dwells come out in hours and a 15m sequence and a 1h sequence are
    comparable. A per-bar transition probability would be a different model on
    every timeframe, which is the mistake `switching.py` audits for.

    The trailing run is dropped as censored. See the module docstring.
    """
    letters = tuple(dict.fromkeys(alphabet if alphabet is not None else (s for s, _ in sequence)))
    got = Transitions(alphabet=letters)
    if len(sequence) < 2:
        return got
    held = float(sequence[0][1])
    for index in range(1, len(sequence)):
        previous, current = sequence[index - 1][0], sequence[index][0]
        got.observe(previous, current)
        if current == previous:
            held += float(sequence[index][1])
            continue
        got.dwells.setdefault(previous, []).append(held)
        held = float(sequence[index][1])
    got.censored = (sequence[-1][0], held)
    return got


@dataclass(frozen=True, slots=True)
class Durations:
    """One state's completed dwells, and the hazard off them."""

    state: str
    hours: tuple[float, ...]

    @property
    def mean(self) -> float:
        return statistics.fmean(self.hours) if self.hours else math.nan

    def hazard(self, held: float, *, step: float = 0.0) -> float:
        """P(this run ends in the next `step` hours | it has lasted `held`).

        The empirical conditional, which is what a duration-dependent
        transition needs and what a flat Markov chain gets wrong. `step`
        defaults to the mean dwell divided by ten, which gives ten usable bins
        over the bulk of the distribution without reading one dwell per bin.

        `Changepoint.run_hours` is the live input to `held`: the expected hours
        since the last change, marginalised over the run-length posterior.
        """
        if not self.hours:
            return math.nan
        width = step if step > 0 else max(self.mean / 10.0, 1e-9)
        at_risk = sum(1 for h in self.hours if h >= held)
        if at_risk == 0:
            return math.nan
        ending = sum(1 for h in self.hours if held <= h < held + width)
        return ending / at_risk

    def flat_hazard(self, *, step: float = 0.0) -> float:
        """The hazard a plain Markov chain assumes: constant, `step / mean`."""
        if not self.hours or self.mean <= 0:
            return math.nan
        width = step if step > 0 else max(self.mean / 10.0, 1e-9)
        return 1.0 - math.exp(-width / self.mean)

    def shape(self) -> float:
        """Fitted Weibull shape. 1.0 is a flat hazard, above 1 is ageing.

        Fitted by a bisection on the profile likelihood's derivative, which
        for a Weibull is a single monotone equation in the shape - so there is
        no optimiser and no dependency, in the same spirit as
        `node.metrics.phi_inverse` being Acklam's rational approximation
        rather than scipy.
        """
        usable = [h for h in self.hours if h > 0]
        if len(usable) < 4:
            return math.nan
        logs = [math.log(h) for h in usable]
        mean_log = statistics.fmean(logs)

        def slope(k: float) -> float:
            powers = [h**k for h in usable]
            total = sum(powers)
            if total <= 0:
                return math.inf
            weighted = sum(p * math.log(h) for p, h in zip(powers, usable, strict=True))
            return weighted / total - mean_log - 1.0 / k

        low, high = LEAST_SHAPE, MOST_SHAPE
        if slope(low) > 0 or slope(high) < 0:
            return math.nan  # the root is outside the band; the fit is chasing a tail
        for _ in range(60):
            middle = 0.5 * (low + high)
            if slope(middle) < 0:
                low = middle
            else:
                high = middle
        return 0.5 * (low + high)

    def duration_gain(self) -> float:
        """Weibull log-likelihood minus exponential's, on these dwells.

        **Nested, so the extra parameter has to earn itself.** An exponential
        is a Weibull at shape 1, so twice this is a chi-square on one degree
        of freedom: above **1.92** is p < 0.05 and below it the duration
        dependence has not paid for the parameter it costs.

        `nan` where the shape fit failed, which is the honest answer rather
        than a zero that reads as "no duration dependence".
        """
        usable = [h for h in self.hours if h > 0]
        k = self.shape()
        if math.isnan(k) or len(usable) < 4:
            return math.nan
        n = len(usable)
        scale = (sum(h**k for h in usable) / n) ** (1.0 / k)
        weibull = sum(
            math.log(k / scale) + (k - 1.0) * math.log(h / scale) - (h / scale) ** k for h in usable
        )
        mean = statistics.fmean(usable)
        exponential = sum(-math.log(mean) - h / mean for h in usable)
        return weibull - exponential


# ──────────────────────────────── the nulls ────────────────────────────────


def duty_cycle_matched(labels: Sequence[str], rng: Random) -> list[str]:
    """A label sequence with the same duty cycle and the same switch count.

    **The control for "predict the next transition".**
    `strategy-rotation-is-not-timeable` is directly on point: every pause rule
    this desk tried matched random pausing at the same duty cycle, so the thing
    to beat is not a coin, it is a random transition that spends the same share
    of its time in each state and switches as often.

    Built by keeping the multiset of run lengths and the multiset of run labels
    and reassigning labels to runs, subject to no two neighbouring runs
    carrying the same label - which is what keeps the switch count. The
    marginal is then preserved up to the pairing of lengths to labels, and
    *which state follows which* is destroyed, which is the one property under
    test.

    **The arrangement is built greedily, not by rejection.** Shuffling until no
    two neighbours matched was the first version and it is hopeless at any real
    length: on 60 runs over three labels almost no shuffle qualifies, so it fell
    through its retry limit, adjacent runs merged, and the control came back
    with **39 switches against the real 59** - a *higher* stay rate than the
    data. A forecaster scored against that beats it by predicting "stay", which
    is the opposite of the comparison the control exists to make.

    The greedy rule is the standard one: among the labels still owed a run,
    take the one with the most left that is not the previous label. That
    produces a valid arrangement whenever one exists, which is whenever no
    label holds more than half the runs.
    """
    if len(labels) < 2:
        return list(labels)
    runs: list[tuple[str, int]] = []
    for label in labels:
        if runs and runs[-1][0] == label:
            runs[-1] = (label, runs[-1][1] + 1)
        else:
            runs.append((label, 1))
    owed: dict[str, int] = {}
    for label, _size in runs:
        owed[label] = owed.get(label, 0) + 1
    lengths = [size for _, size in runs]
    rng.shuffle(lengths)

    names: list[str] = []
    previous = ""
    for _ in runs:
        choices = [name for name, left in owed.items() if left > 0 and name != previous]
        if not choices:
            # One label holds more than half the runs, so some neighbour pair
            # has to match. Taking it keeps the duty cycle and loses one
            # switch, which is the only degree of freedom left.
            choices = [name for name, left in owed.items() if left > 0]
        most = max(owed[name] for name in choices)
        picked = rng.choice([name for name in choices if owed[name] == most])
        owed[picked] -= 1
        names.append(picked)
        previous = picked

    out: list[str] = []
    for label, size in zip(names, lengths, strict=True):
        out.extend([label] * size)
    return out[: len(labels)]


def most_likely_next(model: Transitions, state: str) -> str:
    """The argmax of the row. The default predictor, and a limited one.

    **On a persistent chain the argmax is always "stay"**, so a transition
    matrix buys a forecaster nothing at all - measured on a planted three-state
    cycle with a 20-step dwell, the predictor and its duty-cycle-matched
    control both score the stay rate of 0.952 and the excess is zero. The
    matrix is full of real transition information and an argmax predictor
    cannot reach any of it.

    That is the todo's own conclusion arriving from a second direction: the
    useful question is not "what comes next" but a conditional one - given it
    changes, to what, and given it has held this long, how likely is a change.
    `most_likely_change` is the first of those and `Durations.hazard` is the
    second.
    """
    return model.forecast(state)[0]


def most_likely_change(model: Transitions, state: str) -> str:
    """The most likely state **other than this one**.

    Only meaningful on steps where a change happened, so a `forecast_skill`
    run using it scores the change rate and not the hit rate unless the
    sequence is one where changing is the usual thing. Offered because it is
    the half of the row an argmax never reads.
    """
    row = {j: p for j, p in model.row(state).items() if j != state}
    return max(row, key=lambda j: row[j]) if row else state


@dataclass(frozen=True, slots=True)
class Comparison:
    """A real matrix against matrices fitted to the same inference on nulls.

    `inflation` is the todo's question answered: how much of the diagonal is
    the labeller rather than persistence. Positive means the real sequence is
    more persistent than the labeller alone makes it; zero or negative means
    the diagonal was the smoother, which is the measured expectation.
    """

    observed: float
    draws: tuple[float, ...]
    #: What the nulls were. A control is only ever for a named property.
    removes: str
    #: Which statistic this is. Named, because a `Comparison` of the diagonal
    #: and one of the duration gain print the same way otherwise - and the two
    #: disagree: on eurusd 1h the diagonal is null and the duration gain looks
    #: large until its own null is read.
    statistic: str = "diagonal"

    @property
    def null_mean(self) -> float:
        usable = [d for d in self.draws if not math.isnan(d)]
        return statistics.fmean(usable) if usable else math.nan

    @property
    def inflation(self) -> float:
        """Observed minus the null's mean. The todo's question, as a number."""
        return self.observed - self.null_mean

    @property
    def percentile(self) -> float:
        usable = [d for d in self.draws if not math.isnan(d)]
        if not usable:
            return math.nan
        return sum(1 for d in usable if d < self.observed) / len(usable)

    @property
    def p_value(self) -> float:
        """**Two-sided**, with the observed value included.

        Two-sided because a *deflated* diagonal is a reading too, and on real
        data it is the reading: eurusd 1h comes out at -0.0360 against the
        walk's +0.0066, which says market shape transitions are **less**
        persistent than a walk through the same labeller. A one-sided test
        would report that as "no finding" rather than as what it is.
        """
        usable = [d for d in self.draws if not math.isnan(d)]
        if not usable:
            return 1.0
        above = sum(1 for d in usable if d >= self.observed)
        below = sum(1 for d in usable if d <= self.observed)
        return min(1.0, 2.0 * (min(above, below) + 1) / (len(usable) + 1))

    @property
    def survives(self) -> bool:
        """Outside the null's 0.5% tails, either side. See `p_value`."""
        if not self.draws:
            return False
        return self.percentile >= 0.995 or self.percentile <= 0.005

    def line(self) -> str:
        return (
            f"{self.statistic} {self.observed:.4f} against {self.null_mean:.4f} on "
            f"{len(self.draws)} nulls - inflation {self.inflation:+.4f}, percentile "
            f"{self.percentile:.3f}, p {self.p_value:.4f} "
            f"({'survives' if self.survives else 'null'}) - removes {self.removes}"
        )


def mean_diagonal(fitted: Transitions) -> float:
    """`Transitions.diagonal`, as a selector for `against`."""
    return fitted.diagonal()


def mean_duration_gain(fitted: Transitions) -> float:
    """Mean nested Weibull-over-exponential gain across the visited states.

    **Offered as a selector because reporting it without its null is how it
    gets quoted.** Measured on eurusd 1h with the `Pips` structure alphabet,
    the `walk` state's gain is +7.44 nats against a bar of 1.92 - and a
    gaussian walk through the same labeller reads **+13.66** with a Weibull
    shape of 0.319. So the decreasing hazard is the labeller and the censoring,
    not the market, and the only way to see that is to run the same statistic
    through the same arm.
    """
    got = [
        fitted.durations(state).duration_gain()
        for state in fitted.alphabet
        if fitted.dwells.get(state)
    ]
    usable = [g for g in got if not math.isnan(g)]
    return statistics.fmean(usable) if usable else math.nan


def against(
    observed: Transitions,
    nulls: Sequence[Transitions],
    *,
    removes: str,
    of: Callable[[Transitions], float] = mean_diagonal,
    statistic: str = "diagonal",
) -> Comparison:
    """Score any matrix statistic against matrices fitted the same way.

    `nulls` are `Transitions` fitted to label sequences produced by running
    **the same labeller** over null data. Passing a uniform `1/k` instead is
    the mistake the todo names: it compares a smoothed diagonal against a
    number no smoother produced, so it passes whatever the labeller does.

    `of` is the statistic, so the duration gain gets the same arm as the
    diagonal rather than being reported bare - which is exactly how it was
    nearly quoted as a finding at +7.44 nats on eurusd, where a walk through
    the same labeller reads +13.66.
    """
    if not nulls:
        raise ValueError(
            "a transition matrix needs matrices fitted to a walk through the same "
            "inference as its null. A uniform 1/k cannot see the diagonal the "
            "smoother inflated, which is what this comparison exists to measure."
        )
    if not removes.strip():
        raise ValueError("name the property these nulls remove - a control is only for one")
    return Comparison(
        observed=of(observed),
        draws=tuple(of(n) for n in nulls),
        removes=removes,
        statistic=statistic,
    )


# ─────────────────────────────── the forecast ───────────────────────────────


@dataclass(frozen=True, slots=True)
class Skill:
    """How often a predictor named the next label, against its own control."""

    hits: float
    control: float
    attempts: int
    #: The share of steps that were self-transitions, so a reader can see how
    #: much of `hits` is predicting that nothing happens.
    stay_rate: float

    @property
    def excess(self) -> float:
        return self.hits - self.control

    @property
    def survives(self) -> bool:
        """Does it beat the duty-cycle-matched control at all?

        A share rather than a significance test, reported with `attempts` so a
        reader can form one. The bar that matters is the control's share and
        not 1/k: a predictor that always says "stay" scores the stay rate, and
        on an inferred label sequence the stay rate is high because the
        smoother made it so.

        **One-sided, unlike `Comparison`**, and for a reason rather than by
        omission: a predictor that does worse than its control has the sign
        wrong, and on a k-state alphabet "not this state" is not a prediction -
        there is nothing to invert it into.
        """
        return self.attempts > 0 and self.excess > 0.0


def forecast_skill(
    sequence: Sequence[tuple[str, float]],
    alphabet: Sequence[str],
    *,
    draws: int = 100,
    seed: int = 0,
    predictor: Callable[[Transitions, str], str] | None = None,
) -> Skill:
    """Fit on the first half, predict the second, score against the control.

    Split in time rather than cross-validated, because the quantity under test
    is whether the matrix learned in one period still holds in the next - and
    a shuffle-based split answers a different question by construction.

    The control is `duty_cycle_matched`: the same labels, the same number of
    switches, a random ordering. A predictor is only reported as skilled if it
    beats that, because "predict the next transition" is strategy rotation in
    a new costume and every pause rule this desk tried matched random pausing
    at the same duty cycle.
    """
    if len(sequence) < 8:
        return Skill(hits=math.nan, control=math.nan, attempts=0, stay_rate=math.nan)
    pick = predictor or most_likely_next
    half = len(sequence) // 2
    model = fit(sequence[:half], alphabet)
    tail = list(sequence[half:])

    def hit_rate(labels: Sequence[str], trained: Transitions) -> float:
        got = 0
        for i in range(1, len(labels)):
            if pick(trained, labels[i - 1]) == labels[i]:
                got += 1
        return got / max(1, len(labels) - 1)

    labels = [s for s, _ in tail]
    hits = hit_rate(labels, model)
    stays = sum(1 for i in range(1, len(labels)) if labels[i] == labels[i - 1])
    controls: list[float] = []
    for draw in range(draws):
        # A fresh `Random` per draw rather than one stream, so a single draw
        # can be reproduced from its own seed when it looks wrong.
        shuffled = duty_cycle_matched([s for s, _ in sequence], Random(seed * 7_919 + draw))
        null_model = fit(
            list(zip(shuffled[:half], [h for _s, h in sequence[:half]], strict=True)), alphabet
        )
        controls.append(hit_rate(shuffled[half:], null_model))
    return Skill(
        hits=hits,
        control=statistics.fmean(controls) if controls else math.nan,
        attempts=max(0, len(labels) - 1),
        stay_rate=stays / max(1, len(labels) - 1),
    )


__all__ = [
    "LEAST_DWELLS",
    "PRIOR",
    "Comparison",
    "Durations",
    "Skill",
    "Transitions",
    "against",
    "duty_cycle_matched",
    "fit",
    "forecast_skill",
    "mean_diagonal",
    "mean_duration_gain",
    "most_likely_change",
    "most_likely_next",
]
