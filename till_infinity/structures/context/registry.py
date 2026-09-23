"""Every measured signal in one place, scored live against its own claim.

See `signal-registry.md` in research/docs.

The desk asked for all of it: *"take the ones whose signal strength >=51% and add them to
production"*, and then *"we don't only need the strongest ... we need all >=51% signal"*. That
is the ensemble argument - individually weak, jointly maybe not - and it is a good one. This is
where they live.

## What this does and does not decide

It **publishes numbers and a combined reading, and gates nothing by default.** Not timidity:
every entry below is a point estimate from a backtest, and this folder's record is that point
estimates from backtests decay. `to-prod.md` had to be corrected the same day it was written;
`turns.md` reversed its own answer when the sample doubled; the efficiency candidate measured
+0.0861 early and -0.0308 late. So each signal arrives here with its **backtested** strength as
a claim and is then scored on **live** resolutions, and the ensemble weights come from the live
score rather than from the claim.

That is the difference between this and a config file of fitted weights. A registry that
weighted by its backtest would be re-asserting the backtest forever.

## The roster, and why each one is here

Read `strength` as "AUC on hold-versus-break unless the note says otherwise". Anything below
0.51, or above it but unreachable, is listed in `research/docs/signal-registry.md` with the
reason rather than carried here.

`clock` is the one that is new, the one that is largest, and the only one whose input is free.
The rest were measured over stored history or over the journal and are carried because the desk
asked for all of them, not because any is individually convincing.

## Why the ensemble is log-odds and not a vote

These are not independent readings of one quantity. `strength` and `experience` both describe
the level's record; `approach_vol`, `slowing` and `slope` all describe the approach. A majority
vote over correlated signals counts the same evidence several times, which is exactly how a
"weak individually, strong together" argument goes wrong.

Summing log-odds has the same failing if the weights are naive, so the weights here are
**inverse-variance from the live score and shrunk toward zero until a signal has earned
otherwise** - a signal at chance contributes nothing, and a signal with few observations
contributes little. `MIN_SEEN` is the gate, and it is deliberately high.

## Only floats, again

A capped `deque` restored from an older save comes back **uncapped** - that happened in this
codebase and was found on the live heap rather than in the declaration. So every running
statistic here is a pair of floats and a count, bias corrected the way `character.py` does it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..state import Restorable

#: Resolutions a signal needs before it is allowed any weight in the ensemble.
#:
#: High on purpose. At a break rate near 10% an AUC estimate over a few hundred touches has a
#: standard error of several points, which is the whole size of most of these effects.
MIN_SEEN = 500.0

#: Effective window for the live score, in resolutions. Long enough to measure an effect of a
#: few points, short enough to notice one dying - which is the failure mode this folder keeps
#: finding, not a signal that was never there.
WINDOW = 4000.0

#: Largest separation any one signal may claim, in pooled standard deviations. Six maps to an
#: AUC of essentially one, so the cap binds only on degenerate readings - but it binds there
#: rather than letting a constant feature dominate the sum.
D_CAP = 6.0

#: A live score this far from a coin before the signal is allowed to contribute. Two points of
#: AUC-equivalent; below it the ensemble treats the signal as absent.
MIN_EDGE = 0.02

#: The measured roster. `strength` is the backtested claim, `live` is what this class fills in.
#:
#: **The claim is provenance, not a weight.** It is carried so a live score can be read against
#: what was promised, which is the comparison that catches decay - and it is the comparison
#: nothing in this repository was set up to make until now.
#:
#: `sense` is +1 when a larger reading means a likelier break and -1 when it means the opposite.
#: Three of these are negative, and two of those are the strongest entries on the page, which is
#: the reason the field exists rather than a naming convention.
ROSTER: tuple[tuple[str, float, int, str], ...] = (
    # name, backtested strength, sense, where it was measured
    ("clock", 0.778, +1, "break-trade.md: 14.4% -> 77.8% by elapsed time, n=312,420"),
    ("experience", 0.624, -1, "break-trade.md: AUC 0.3764 unconditional, read inverted"),
    ("strength", 0.608, -1, "break-trade.md: AUC 0.3924 unconditional, read inverted"),
    ("depth_vol", 0.562, -1, "force.md: AUC 0.4180 in band, 0.4379 unconditional"),
    ("slowing", 0.543, +1, "force.md / breaking.py: AUC 0.5237 in band, 0.5433 unconditional"),
    ("approach_vol", 0.525, +1, "force.md: AUC 0.5429 in band, 0.5253 unconditional"),
    ("slope", 0.505, +1, "slopes.md: magnitude only, and only paired with prior_slope"),
)

#: Where `clock` crosses even money, in bars of the level's **own** timeframe.
#:
#: Measured at 4 to 7 bars across five timeframes spanning a factor of thirty - 300s on 1m,
#: 1,200s on 5m, 3,600s on 15m - so the rule is scale-free and this is its one parameter. See
#: the table in `research/docs/break-trade.md`.
CLOCK_BARS = 5.0

#: How sharply the clock reading rises either side of `CLOCK_BARS`. Solved against three
#: points of the measured 1m row - 54.7% at five bars and 77.8% at ten - rather than fitted by
#: least squares, because the row is five points and a least-squares curve through five points
#: would claim a precision the data does not carry.
CLOCK_SHARPNESS = 1.65

#: The break rate of a touch that has only just opened, which is where the curve has to start.
#:
#: **A logistic in log-age goes to zero as the age goes to zero, and that is wrong**: a
#: just-opened touch still breaks 14.4% of the time. Without this floor the reading is not even
#: monotone - it would put a fresh touch below a five-second-old one - which is what the test
#: caught. The curve is therefore `floor + (1 - floor) * logistic(...)`.
CLOCK_FLOOR = 0.12


def clock_odds(age_bars: float) -> float:
    """P(this level breaks | the touch is still open after `age_bars` of its own bars).

    The one conditional in this repository that costs nothing to observe. "Resolution took at
    least t" and "still open at t" are the same event, so a table built on finished touches is
    a table a live timer can act on - which is what separates this from every other conditional
    here, all of which need to know how the touch ended.

    Measured on 1m: 14.4% at open, 22.4% at two minutes, **54.7% at five**, 77.8% at ten. The
    same shape on 3m, 5m, 15m and 30m once time is counted in the level's own bars.
    """
    if age_bars <= 0.0:
        return CLOCK_FLOOR
    # A logistic in log-age, which is what the measured rows look like on a log axis and which
    # cannot leave [0, 1] however long a touch stays open - lifted onto the floor, so a fresh
    # touch reads its unconditional rate instead of zero.
    z = CLOCK_SHARPNESS * math.log(age_bars / CLOCK_BARS)
    return CLOCK_FLOOR + (1.0 - CLOCK_FLOOR) / (1.0 + math.exp(-z))


@dataclass(slots=True)
class Score(Restorable):
    """One signal's live record: does it separate breaks from holds, on this desk, now.

    Held as a **rank statistic**, not an accuracy. Accuracy on a class that breaks a tenth of
    the time is maximised by never predicting a break, which is why `breaking.py` scored worse
    than its own base rate while its ranking was fine. What matters is whether the signal is
    larger on the touches that broke, so that is what is stored: the mean reading on each
    class, and the spread that separates them.
    """

    #: Bias-corrected exponential means of the standardised reading, per class.
    broke: float = 0.0
    broke_w: float = 0.0
    held: float = 0.0
    held_w: float = 0.0
    #: Second moments, so the separation can be expressed in standard deviations rather than
    #: in whatever units the feature happens to use.
    broke_sq: float = 0.0
    held_sq: float = 0.0
    seen: float = 0.0

    def observe(self, reading: float, broke: bool) -> None:
        decay = math.exp(-1.0 / WINDOW)
        if broke:
            self.broke = self.broke * decay + reading
            self.broke_sq = self.broke_sq * decay + reading * reading
            self.broke_w = self.broke_w * decay + 1.0
        else:
            self.held = self.held * decay + reading
            self.held_sq = self.held_sq * decay + reading * reading
            self.held_w = self.held_w * decay + 1.0
        self.seen += 1.0

    @property
    def separation(self) -> float:
        """Mean reading on breaks minus on holds, in pooled standard deviations.

        Cohen's d, which maps to an AUC monotonically - so it answers the same question the
        roster's claims are stated in, without needing to keep any history to rank against.
        """
        if self.broke_w < 1.0 or self.held_w < 1.0:
            return 0.0
        mb = self.broke / self.broke_w
        mh = self.held / self.held_w
        vb = max(self.broke_sq / self.broke_w - mb * mb, 0.0)
        vh = max(self.held_sq / self.held_w - mh * mh, 0.0)
        pooled = math.sqrt((vb + vh) / 2.0)
        if pooled <= 1e-9:
            # Both classes constant. Cohen's d is undefined, but the honest reading is
            # **perfect separation, not none** - returning zero here would silently discard a
            # signal that never disagrees with itself, which is the opposite of the truth.
            # Capped rather than infinite so one degenerate signal cannot swamp the ensemble.
            return 0.0 if abs(mb - mh) <= 1e-12 else math.copysign(D_CAP, mb - mh)
        return max(-D_CAP, min(D_CAP, (mb - mh) / pooled))

    @property
    def live(self) -> float:
        """The separation restated as an AUC, so it reads against the roster's claim.

        The normal-equal-variance relation `AUC = Phi(d / sqrt(2))`, which is exact when the
        two classes are normal with the same spread and close enough otherwise for a number
        whose job is to be compared with 0.51.
        """
        d = self.separation
        return 0.5 * (1.0 + math.erf(d / 2.0))

    @property
    def weight(self) -> float:
        """How much this signal is allowed to say, from its live record alone.

        Zero until `MIN_SEEN`, zero while it sits inside `MIN_EDGE` of a coin, and otherwise
        proportional to how far past that it has earned - so a signal that decays loses its
        vote without anyone editing a table.
        """
        if self.seen < MIN_SEEN:
            return 0.0
        edge = abs(self.live - 0.5)
        if edge < MIN_EDGE:
            return 0.0
        return edge - MIN_EDGE


@dataclass(slots=True)
class Registry(Restorable):
    """Every measured signal, its claim, its live score, and their combination."""

    scores: dict[str, Score] = field(default_factory=dict)
    #: Resolutions seen, so a reading can say how much evidence is behind it.
    seen: int = 0

    def _score(self, name: str) -> Score:
        got = self.scores.get(name)
        if got is None:
            got = Score()
            self.scores[name] = got
        return got

    @staticmethod
    def readings(features: object, age_bars: float | None = None) -> dict[str, float]:
        """Each signal's reading for one touch, oriented so larger always means likelier break.

        Orientation happens **here**, once, rather than in each consumer. Three of the seven
        are negatively signed and two of those are the strongest, so leaving the sign to the
        caller is how a registry of weak signals turns into a registry of wrong ones.
        """
        out: dict[str, float] = {}
        for name, _claim, sense, _where in ROSTER:
            if name == "clock":
                if age_bars is not None:
                    out["clock"] = clock_odds(age_bars)
                continue
            got = getattr(features, name, None)
            if isinstance(got, (int, float)) and math.isfinite(float(got)):
                value = float(got)
                # `slope` is carried as a magnitude: its sign says which way price is going,
                # which is a different question from whether the level survives.
                out[name] = abs(value) * sense if name == "slope" else value * sense
        return out

    def observe(self, features: object, broke: bool, age_bars: float | None = None) -> None:
        """Score every signal against one resolved touch.

        Called on resolution, so each observation is out of sample with respect to every
        reading it scores - the same predict-then-update discipline `breaking.py` uses, and
        the reason these numbers need no separate holdout.
        """
        for name, reading in self.readings(features, age_bars).items():
            self._score(name).observe(reading, broke)
        self.seen += 1

    def ensemble(self, features: object, age_bars: float | None = None) -> float | None:
        """The combined reading, in [0, 1], or `None` while nothing has earned a vote.

        Weighted by live separation, not by the roster's claims. A signal at chance
        contributes nothing and one below `MIN_SEEN` contributes nothing, so this returns
        `None` for a long time after a fresh deploy - which is correct and is not a fault.
        """
        total = 0.0
        stack = 0.0
        for name, reading in self.readings(features, age_bars).items():
            score = self.scores.get(name)
            if score is None:
                continue
            weight = score.weight
            if weight <= 0.0:
                continue
            # Each signal's own separation turns its reading into a direction; the magnitude
            # is the weight. Standardised by the pooled spread so features in different units
            # are comparable, which is the only reason this can be summed at all.
            centred = reading - (score.held / score.held_w if score.held_w >= 1.0 else 0.0)
            spread = abs(score.separation) or 1.0
            stack += weight * math.tanh(centred / spread)
            total += weight
        if total <= 0.0:
            return None
        return 0.5 * (1.0 + stack / total)

    def reading(self) -> dict[str, float]:
        """What every signal is worth **now**, for the journal.

        Publishes the live figure beside the backtested claim for each signal, because the
        gap between them is the quantity this whole class exists to expose - and the one
        nothing in this repository was previously arranged to notice.
        """
        out: dict[str, float] = {"registry_seen": float(self.seen)}
        for name, claim, _sense, _where in ROSTER:
            score = self.scores.get(name)
            if score is None or score.seen < MIN_SEEN:
                continue
            out[f"{name}_live"] = round(score.live, 4)
            # The **gap**, not the claim. The claim is a constant - it lives in `ROSTER` and in
            # the research - so publishing it on every level call would put seven numbers that
            # never move into every journal row, which `test_published.py` refuses and is right
            # to. The difference is what varies and is the quantity this class exists to expose:
            # negative means the signal is doing worse live than the backtest promised.
            out[f"{name}_drift"] = round(score.live - claim, 4)
            out[f"{name}_weight"] = round(score.weight, 4)
        return out
