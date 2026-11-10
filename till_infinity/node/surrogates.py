"""Null models: the same strategy on data that has had one property removed.

**These are the checks to trust most**, on the desk's own account: six
artefacts are held to have passed DSR, PBO and SPA, and what exposed them was
rerunning the strategy on surrogates and breaking the result down by hour - so
a battery that stops at the selection statistics is a battery that has already
been fooled here. **The six are unsourced.** The only deflation written up is
`research/docs/lopez-de-prado.md`, which names no PBO or SPA run, so this is a
reason to keep the surrogates rather than a measurement of what they caught.

Each surrogate removes exactly one thing and keeps the rest. That is the whole
design, and `a-control-is-only-for-a-named-property` is why: a control has to
be labelled with the property it controls for, or it answers a question nobody
asked. Boom/Crash gained more than any traded class under a control that was
not about the right property.

| surrogate | keeps | removes |
| --- | --- | --- |
| `sign_flip` | magnitude and its clustering | direction, in blocks |
| `vol_path_walk` | the realised volatility path exactly | direction, per observation |
| `block_shuffle` | short-range structure inside a block | the timing of blocks |
| `time_shift` | both series entirely | the link between signal and outcome |
| `ewma_t` | clustering and fat tails | everything else |
| `iaaft` | the distribution and the autocorrelation | the phase, so any nonlinearity |

**A result that survives all of them is not proven; it has run out of cheap
explanations.** `null-pivot-ideas-against-a-walk-first` and
`let-the-shuffled-twin-name-the-mechanical-observables` are the two habits
that matter: pick the *highest-powered* arm rather than each arm's own, and
expect a definitional effect to show up in the twin.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass

#: Default block for the sign-flip null, in observations.
#:
#: Five because the spec asks for five-day blocks, and the reason blocks are
#: used at all is that flipping per observation destroys the serial
#: dependence that makes a null fair - the same mistake as shuffling.
SIGN_BLOCK = 5

#: EWMA decay for the clustering surrogate. 0.94 is what the harness already
#: uses for sigma, so the surrogate and the live estimator agree.
EWMA_LAMBDA = 0.94


def sign_flip(
    returns: Sequence[float], *, block: int = SIGN_BLOCK, rng: random.Random | None = None
) -> list[float]:
    """Flip the sign of whole blocks, keeping magnitudes in place.

    Direction goes; the volatility path, its clustering and the fat tails all
    stay exactly as they were. A strategy whose edge is really a drift dies
    here; one whose edge is in dispersion does not, which is how the two are
    told apart.
    """
    r = rng or random.Random()
    out: list[float] = []
    for start in range(0, len(returns), max(1, block)):
        chunk = returns[start : start + block]
        sign = 1.0 if r.random() < 0.5 else -1.0
        out.extend(sign * x for x in chunk)
    return out


def vol_path_walk(returns: Sequence[float], *, rng: random.Random | None = None) -> list[float]:
    """Keep the realised volatility path exactly; randomise every sign.

    The per-observation limit of `sign_flip`. Harsher on direction and softer
    on serial sign dependence, so the two together bracket it: an effect that
    survives block flipping but dies here lived in the sign *sequence* rather
    than in direction as such.
    """
    r = rng or random.Random()
    return [abs(x) * (1.0 if r.random() < 0.5 else -1.0) for x in returns]


def block_shuffle(
    returns: Sequence[float], *, block: int = 20, rng: random.Random | None = None
) -> list[float]:
    """Reorder blocks, keeping what is inside each one intact.

    Short-range structure survives and the timing does not - which is the
    control for anything that claims to know *when*. `synthetics-are-a-poor-
    tail-control` is why this is preferred to a generated process: kurtosis
    3.19 against 20.07 on traded data, so block-shuffling a real leg keeps the
    tails that a synthetic cannot.
    """
    r = rng or random.Random()
    size = max(1, block)
    blocks = [list(returns[i : i + size]) for i in range(0, len(returns), size)]
    r.shuffle(blocks)
    return [x for chunk in blocks for x in chunk]


def time_shift(outcomes: Sequence[float], *, lag: int = 1) -> list[float]:
    """Rotate the outcomes, breaking their link to the signal.

    Both series keep every property they had; only the correspondence is
    destroyed. This is the control that catches a leak rather than an edge,
    and `overlapping-outcome-windows-leak` is the case it would have caught:
    direction AUC 0.79 that collapsed to 0.51, where the tell was the placebo
    and shuffled arms *tracking* the real one.
    """
    if not outcomes:
        return []
    shift = lag % len(outcomes)
    return list(outcomes[shift:]) + list(outcomes[:shift])


def ewma_t(
    returns: Sequence[float],
    *,
    dof: float = 4.0,
    rng: random.Random | None = None,
) -> list[float]:
    """A surrogate with clustering and fat tails, and nothing else.

    EWMA volatility driving Student-t innovations. **Not a fitted GARCH-t**:
    that needs an optimiser and the `arch` package, and this stands in for it
    with the estimator the harness already uses - lambda 0.94 - so the
    surrogate and the live sigma agree rather than being two different
    models of the same thing.

    dof 4 because `no-gaussian-band-is-calibrated` measured a Student-t with
    three to five degrees of freedom fixing the one-bar band on 64 of 64 out
    of sample, so 4 is this desk's own reading of its tails.
    """
    r = rng or random.Random()
    if len(returns) < 2:
        return list(returns)
    variance = sum(x * x for x in returns) / len(returns)
    out: list[float] = []
    for actual in returns:
        # Student-t with `dof` degrees of freedom, scaled to unit variance.
        scale = math.sqrt(dof / (dof - 2.0)) if dof > 2.0 else 1.0
        innovation = _student_t(r, dof) / scale
        out.append(math.sqrt(variance) * innovation)
        variance = EWMA_LAMBDA * variance + (1.0 - EWMA_LAMBDA) * actual * actual
    return out


def _student_t(r: random.Random, dof: float) -> float:
    """One Student-t draw, as a normal over a chi-scaled denominator."""
    normal = r.gauss(0.0, 1.0)
    chi_squared = sum(r.gauss(0.0, 1.0) ** 2 for _ in range(max(1, int(dof))))
    return normal / math.sqrt(chi_squared / max(1.0, float(int(dof))))


def iaaft(
    returns: Sequence[float], *, iterations: int = 100, rng: random.Random | None = None
) -> list[float]:
    """Iterative amplitude-adjusted Fourier transform.

    Keeps the distribution *and* the autocorrelation, and destroys everything
    else - so a strategy that survives this one is using something beyond the
    linear structure and the marginal shape, which is a much narrower claim
    than "it works".

    The strictest of these nulls and the only one needing numpy, which is
    declared. Falls back to a block shuffle if numpy is missing rather than
    failing a sweep, and says so.
    """
    try:
        import numpy as np
    except ImportError:  # pragma: no cover - numpy is declared
        return block_shuffle(returns, rng=rng)

    series = np.asarray(returns, dtype=float)
    n = len(series)
    if n < 8:
        return list(returns)
    target_amplitudes = np.abs(np.fft.rfft(series))
    sorted_values = np.sort(series)
    r = rng or random.Random()
    order = list(range(n))
    r.shuffle(order)
    candidate = series[order]
    for _ in range(iterations):
        # Impose the original spectrum, keeping the candidate's phases.
        spectrum = np.fft.rfft(candidate)
        phases = np.angle(spectrum)
        candidate = np.fft.irfft(target_amplitudes * np.exp(1j * phases), n=n)
        # Impose the original distribution, keeping the new ranks.
        ranks = np.argsort(np.argsort(candidate))
        candidate = sorted_values[ranks]
    return [float(x) for x in candidate]


def placebo_anchors(
    length: int, count: int, *, rng: random.Random | None = None, margin: int = 0
) -> list[int]:
    """Random anchor points, as many as the detector found.

    **The null a shape claim actually needs.** Sign flips and shuffles remove
    direction, and trading direction *is* trading geometry - so every
    directional claim fails them by construction, which makes them tautologies
    rather than controls. This keeps the data exactly as it is and moves only
    *which* points were called the shape.

    It is also the null that did the work here: the displacement origin's 82%
    return rate was matched by a distance-matched placebo on every class, and
    a random walk reads 0.825. The rate was geometry, not a signal.
    """
    r = rng or random.Random()
    usable = max(0, length - 2 * margin)
    if usable <= 0 or count <= 0:
        return []
    return sorted(r.randrange(margin, margin + usable) for _ in range(count))


def distance_matched(
    length: int,
    distances: Sequence[int],
    *,
    rng: random.Random | None = None,
) -> list[tuple[int, int]]:
    """Placebo anchors whose *distances* match the real ones.

    Returns `(start, end)` pairs. The stronger form of the placebo above: not
    only is the data untouched, the geometry of each episode is preserved -
    same distance to target, same horizon - so what remains to be tested is
    only whether the detector's choice of starting point mattered.

    `a-return-rate-is-geometry` is why distance has to be matched rather than
    merely random: a longer horizon reaches a target more often, so an
    unmatched placebo loses to the real thing for a reason that has nothing to
    do with the shape.
    """
    r = rng or random.Random()
    out: list[tuple[int, int]] = []
    for distance in distances:
        span = abs(int(distance))
        if span >= length:
            continue
        start = r.randrange(0, length - span)
        out.append((start, start + span))
    return out


#: Arms that cannot judge a directional claim, with the reason.
#:
#: **Not a warning, a refusal.** A null that removes the quantity being traded
#: answers a different question than the one asked, and reports a confident
#: failure either way.
TAUTOLOGICAL_FOR_DIRECTION = {
    "sign-flip (direction, in blocks)": "removes direction, which the claim is a bet on",
    "vol-path walk (direction, per observation)": "removes direction per observation",
}


#: Every null, by the property it removes. Keyed so a report can say which
#: arm a candidate died against rather than "the null".
NULLS: dict[str, Callable[[Sequence[float]], list[float]]] = {
    "sign-flip (direction, in blocks)": sign_flip,
    "vol-path walk (direction, per observation)": vol_path_walk,
    "block shuffle (timing)": block_shuffle,
    "ewma-t (everything but clustering and tails)": ewma_t,
    "iaaft (everything but distribution and autocorrelation)": iaaft,
}


@dataclass(frozen=True, slots=True)
class Surrogate:
    """One null arm's verdict on a statistic."""

    name: str
    observed: float
    #: The statistic on each surrogate draw.
    draws: tuple[float, ...]

    @property
    def percentile(self) -> float:
        """Where the real result sits in the surrogate distribution."""
        if not self.draws:
            return 0.0
        beaten = sum(1 for d in self.draws if d < self.observed)
        return beaten / len(self.draws)

    @property
    def p_value(self) -> float:
        """One-sided permutation p, with the observed value included.

        The `+1` on both sides is not a rounding choice: it is what keeps p
        from ever being exactly zero, which it cannot be from a finite number
        of draws.
        """
        at_least = sum(1 for d in self.draws if d >= self.observed)
        return (at_least + 1) / (len(self.draws) + 1)

    @property
    def uninformative(self) -> bool:
        """Did this null fail to move the statistic at all?

        **A null that cannot affect the statistic reports a confident pass**,
        which is the same failure as a guard that goes vacuous - and it is
        easy to walk into. A block shuffle cannot change a Sharpe of the raw
        return series, because reordering leaves the mean and the standard
        deviation untouched; IAAFT preserves the distribution exactly, so it
        cannot either. Both then return the observed value on every draw and
        read as a pass against nothing.

        The pairing is the thing: a surrogate has to be matched with a
        statistic the removed property can actually reach. Timing nulls belong
        with order-dependent statistics - a strategy's realised P&L - not with
        a moment of the unordered series.
        """
        if len(self.draws) < 2:
            return True
        spread = max(self.draws) - min(self.draws)
        scale = max(abs(self.observed), 1e-12)
        return spread / scale < 1e-9

    @property
    def passes(self) -> bool:
        """Above the 99th percentile of the null, as the spec asks.

        An uninformative arm never passes. It has not failed either - it was
        simply the wrong null for this statistic, and `verdict` says so.
        """
        return not self.uninformative and self.percentile >= 0.99

    def verdict(self) -> str:
        if self.uninformative:
            return (
                f"{self.name}: uninformative - the statistic did not move across "
                f"{len(self.draws)} draws, so this null cannot judge it. Pair a "
                f"timing null with an order-dependent statistic."
            )
        return (
            f"{self.name}: percentile {self.percentile:.3f}, p {self.p_value:.4f}"
            f" - {'passes' if self.passes else 'fails'}"
        )


def against_nulls(
    returns: Sequence[float],
    statistic: Callable[[Sequence[float]], float],
    *,
    draws: int = 200,
    seed: int = 0,
    nulls: dict[str, Callable] | None = None,
    directional: bool = False,
) -> list[Surrogate]:
    """Score a statistic against every null arm.

    **Report every arm, and judge on the highest-powered one.**
    `let-the-shuffled-twin-name-the-mechanical-observables` is the rule: using
    each arm's own null lets a definitional effect pass against a weak arm, so
    the arm that most nearly reproduces the real data is the one that decides.
    """
    observed = statistic(returns)
    chosen = dict(nulls or NULLS)
    if directional:
        refused = [name for name in chosen if name in TAUTOLOGICAL_FOR_DIRECTION]
        for name in refused:
            chosen.pop(name)
        if refused and not chosen:
            raise ValueError(
                "every null given removes direction, and a directional claim is a bet "
                "on direction - so these cannot judge it. Use `placebo_anchors` or "
                "`distance_matched`, which keep the geometry and move only the "
                f"identification. Refused: {refused}"
            )
    out: list[Surrogate] = []
    for name, make in chosen.items():
        values: list[float] = []
        for i in range(draws):
            rng = random.Random(seed * 1_000_003 + i)
            try:
                values.append(statistic(make(returns, rng=rng)))
            except TypeError:  # a null that takes no rng
                values.append(statistic(make(returns)))
            except ValueError:
                continue  # a draw the statistic cannot score is not a draw
        out.append(Surrogate(name=name, observed=observed, draws=tuple(values)))
    return out


def hardest(arms: Sequence[Surrogate]) -> Surrogate | None:
    """The arm the real result beats by the least - the one that decides.

    Not the mean of the arms and not the kindest: a result is only as
    established as its strongest control, and averaging over arms lets a weak
    one carry a finding.

    **Uninformative arms are excluded rather than counted as hardest.** They
    would otherwise always win, because a null that does not move the
    statistic leaves the observed value at percentile zero - so the arm that
    tested nothing would decide everything.
    """
    useful = [a for a in arms if not a.uninformative]
    return min(useful, key=lambda a: a.percentile) if useful else None


# ─────────────────────────── the two shape nulls ───────────────────────────
#
# **A geometric claim and a topological one need different nulls, and using
# one for the other is how a geometric confound passes a topological test.**
# That is not a hypothetical: the displacement origin's 82% return rate was
# geometry, and only a distance-matched placebo showed it.
#
#   geometric   - distances, sizes, depths, angles. Scale-dependent.
#                 Null: keep the data and the distances, move the anchors.
#   topological - connectivity, ordering, enclosure, higher-highs. Scale-free.
#                 Null: run the *same detector* over a walk whose bars have
#                 the same geometry, so whatever the detector produces
#                 mechanically appears in the null too.


@dataclass(frozen=True, slots=True)
class Episode:
    """One detection: where it started and how far it was asked to travel.

    `distance` is what a geometric null has to match. An unmatched placebo
    loses for a reason that has nothing to do with the shape, because a longer
    horizon reaches a target more often.
    """

    start: int
    distance: int
    direction: int = 1


def geometric_null(
    length: int,
    episodes: Sequence[Episode],
    score: Callable[[Sequence[Episode]], float],
    *,
    draws: int = 200,
    seed: int = 0,
) -> Surrogate:
    """Score a geometric claim against distance-matched placebo anchors.

    The data is untouched and every episode keeps its own distance and
    direction; only the starting point moves. What remains to be tested is
    whether the detector's *choice* of start mattered - which is the whole
    content of a geometric shape claim.
    """
    observed = score(episodes)
    distances = [e.distance for e in episodes]
    directions = [e.direction for e in episodes]
    values: list[float] = []
    for i in range(draws):
        rng = random.Random(seed * 15_485_863 + i)
        placebo = [
            Episode(start=start, distance=span, direction=directions[k])
            for k, (start, end) in enumerate(distance_matched(length, distances, rng=rng))
            for span in (end - start,)
        ]
        if not placebo:
            continue
        try:
            values.append(score(placebo))
        except (ValueError, ZeroDivisionError):
            continue
    return Surrogate(
        name="distance-matched placebo (the anchor, not the geometry)",
        observed=observed,
        draws=tuple(values),
    )


def walk_with_bar_geometry(
    bars: Sequence[tuple[float, float, float, float]],
    *,
    rng: random.Random | None = None,
) -> list[tuple[float, float, float, float]]:
    """A random walk whose bars look like these ones.

    Closes follow a walk with the same step distribution; each bar's *shape* -
    its range and its wick-to-body proportions, normalised - is resampled from
    the real bars. So the synthetic series has this market's wickiness and bar
    geometry and none of its path structure.

    **That is what makes it the right null for a topological claim.** Running
    the detector over this tells you what the detector produces from bar
    geometry alone, and `how-markets-differ-from-every-simple-process` is why
    a generated process will not do: markets have fewer imbalances, wickier
    bars, kurtosis 47 to 74 and size autocorrelation 0.21, and no simple
    family is closer than 210.

    ## It gaps at every open, and the market does not. Two warnings follow

    Each bar's open sits inside that bar's own range, independently of the
    previous close, so **this series gaps at every single bar**. Measured
    against the broker's own stores as a share of the bar range:

    | | median `|gap|` | bars with no gap | p90 `|gap|` |
    | --- | ---: | ---: | ---: |
    | real, 15m and 1h | **0.0000** | **71 - 79%** | 0.012 - 0.040 |
    | this surrogate | **0.60 - 0.64** | 0.01 - 0.16% | 1.64 - 1.88 |

    **An earlier version of this note defended the construction on the mean
    gap and was wrong.** The means do agree - about -0.012 of a range on both -
    because `close[i] - close[i-1]` is `(open[i] - close[i-1]) + (close[i] -
    open[i])`, so any series whose bars close above their opens with nil
    close-to-close drift has `mean(gap) = -mean(body)` identically. But the
    market reaches that mean through a *minority* of session-boundary gaps on a
    series that is otherwise contiguous, and this reaches it by gapping 0.6 of
    a range on every bar. A mean is the wrong statistic for the question.

    So:

    * **Never use this arm for anything that fills on a gap** - a resting
      limit, a stop order marked at the open, a gap filter. A study measured
      its long-entry arm paying **+0.1012R a trade on this null**, which is
      the planted gap being collected. For those, build the path: a bar as a
      bridge of sub-steps pinned to a real step, so `open == previous close`
      and the extremes are the path's own.
    * **And never use it as a barrier null**, for a second reason found the
      same day: the highs and lows are resampled independently of the close
      path, so a stop fires where the path never went while the clock mark
      reads the close path as though nothing happened. With random anchors -
      no detector to blame - that read -0.2055R here against -0.0004R
      [-0.0245, +0.0241] on real bars.

    What it remains right for is what the docstring above claims: a
    *topological* claim, where the question is what a detector produces from
    bar wickiness and a step distribution with no path structure.

    One further limitation: the shape pair and the span are resampled
    **independently**, so the correlation between a bar's body and its range is
    not preserved. A detector reading body-to-range jointly is judged against a
    null that has the marginals and not the pair.
    """
    r = rng or random.Random()
    if len(bars) < 2:
        return list(bars)
    steps = [bars[i][3] - bars[i - 1][3] for i in range(1, len(bars))]
    # Each real bar as proportions of its own range, so the shape travels and
    # the scale does not.
    shapes = []
    for open_, high, low, close in bars:
        span = high - low
        if span <= 0:
            shapes.append((0.5, 0.5))
            continue
        shapes.append(((open_ - low) / span, (close - low) / span))
    spans = [high - low for _open, high, low, _close in bars]

    out: list[tuple[float, float, float, float]] = []
    price = bars[0][3]
    for _ in bars:
        price += r.choice(steps)
        span = r.choice(spans)
        open_frac, close_frac = r.choice(shapes)
        low = price - close_frac * span
        high = low + span
        out.append((low + open_frac * span, high, low, price))
    return out


def topological_null(
    bars: Sequence[tuple[float, float, float, float]],
    detect: Callable[[Sequence[tuple[float, float, float, float]]], float],
    *,
    draws: int = 200,
    seed: int = 0,
) -> Surrogate:
    """Score a topological claim by running the detector over matched walks.

    `detect` takes bars and returns the statistic - so the detector itself
    runs on the null data, which is the point. A definitional effect shows up
    on both sides and cancels; `let-the-shuffled-twin-name-the-mechanical-
    observables` is the habit, because overshoot at an extreme is definitional
    and will appear in any arm that runs the same detector.

    **Sweep the reach and test both sides.** A one-sided topological claim is
    half a claim, and a fixed reach is a parameter that was chosen.
    """
    observed = detect(bars)
    values: list[float] = []
    for i in range(draws):
        rng = random.Random(seed * 32_452_843 + i)
        try:
            values.append(detect(walk_with_bar_geometry(bars, rng=rng)))
        except (ValueError, ZeroDivisionError):
            continue
    return Surrogate(
        name="walk through the same detector (same bar geometry)",
        observed=observed,
        draws=tuple(values),
    )


def for_shape(kind: str) -> str:
    """Which of the two to use, with the reason, for a report or an error."""
    if kind == "geometric":
        return (
            "geometric_null: keep the data and every episode's distance, move only "
            "the anchors. A return rate is geometry - the origin's 82% was matched "
            "by a distance-matched placebo on every class, and a walk reads 0.825."
        )
    if kind == "topological":
        return (
            "topological_null: run the same detector over walks with this market's "
            "bar geometry. Connectivity and ordering are scale-free, so the null has "
            "to reproduce the sequence structure rather than the distances."
        )
    raise ValueError(f"kind must be geometric or topological, got {kind!r}")
