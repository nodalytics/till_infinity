"""Questions this desk has already answered, and what it cost to answer them.

**A search that rediscovers a refuted idea has spent itself for nothing**, and
an automated one will do it repeatedly unless told. So a discovery node checks
a proposal against this register first: not to forbid it, but to make it say
what is different this time, and to hold it to the measurement that closed the
question rather than to a fresh threshold.

Shapes and patterns are where this matters most, because that is where the
most work has been done and nearly all of it came back null. An actor pointed
at candlestick geometry will find the same things again.

Each entry carries the measurement, because "we tried that" is not evidence
and cannot be argued with. A number can be.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Closed:
    """One refuted claim, with the reading that refuted it."""

    claim: str
    #: What was measured, in enough detail to repeat.
    evidence: str
    #: What a new proposal has to do to reopen it.
    reopen: str
    #: Words that mean a proposal is about this entry. **Explicit rather than
    #: inferred from the claim sentence**: word overlap missed "an engulfing
    #: candle shape predicts continuation" against "candlestick and SMC shapes
    #: carry an edge", because the only shared stem was shape/shapes. A list
    #: is duller and it works.
    keywords: tuple[str, ...] = ()


#: Refuted, with the measurement. Alphabetical by claim so the list stays
#: readable as it grows; it is expected to grow.
REGISTER: tuple[Closed, ...] = (
    Closed(
        claim="candlestick and SMC shapes carry an edge",
        evidence=(
            "SMC primitives overlap and are closed: an engulfing bar is the opposite "
            "shape to a displacement origin, and the best vs-walk z across 516 rows "
            "was +1.95. Pivots, Elliott, Wyckoff, Gann and z-score entries were all "
            "null on the same harness."
        ),
        reopen=(
            "a shape that is not a relabelling of an existing primitive, tested "
            "against a walk through the same detector with the same bar geometry"
        ),
        keywords=(
            "candle",
            "candlestick",
            "engulf",
            "pin bar",
            "shape",
            "shapes",
            "smc",
            "displacement",
            "order block",
            "orderblock",
            "fair value gap",
            "fvg",
            "pivot",
            "elliott",
            "wyckoff",
            "gann",
            "pattern",
            "formation",
            "geometry",
        ),
    ),
    Closed(
        claim="transitions between shapes carry an edge",
        evidence=(
            "Partly definitional rather than merely null. The primitives overlap and "
            "are complements: an engulfing bar is the *opposite shape* to a "
            "displacement origin, so a transition matrix over them encodes the "
            "definitions as much as the market - and overshoot at an extreme is "
            "definitional too, which the shuffled twin reproduces. Separately, a "
            "mixture whose centres are free states collapses onto the data; three "
            "members needed anchors before they meant anything."
        ),
        reopen=(
            "a transition between states that are *anchored* rather than fitted, "
            "with the shuffled twin reproducing none of it - and the transition "
            "measured against the marginal rate of the destination state, since a "
            "common state is arrived at often by construction"
        ),
        keywords=(
            "transition",
            "transitions",
            "state machine",
            "markov",
            "sequence of shapes",
            "shape change",
            "regime transition",
            "transition matrix",
        ),
    ),
    Closed(
        claim="levels, ranges and chart topology carry an edge",
        evidence=(
            "Topology restates volatility: levels, ranges and shapes all null once "
            "the strata sweep is kept. Range_Break is the positive control - a range "
            "by construction - and passing against a planted shift is not passing "
            "against the thing."
        ),
        reopen="a topological claim that survives within volatility strata",
        keywords=(
            "level",
            "levels",
            "range",
            "ranges",
            "support",
            "resistance",
            "topology",
            "zone",
            "zones",
            "breakout",
        ),
    ),
    Closed(
        claim="a return rate to a level or origin is an edge",
        evidence=(
            "A return rate is geometry. The displacement origin's 82% is matched by a "
            "distance-matched placebo on every class, and a random walk reads 0.825. "
            "It is a target hit rate, not an entry signal."
        ),
        reopen=(
            "a return rate that beats a distance-matched placebo, or a claim about "
            "the time exponent rather than the rate"
        ),
        keywords=(
            "return rate",
            "retrace",
            "revisit",
            "origin",
            "fill rate",
            "hit rate",
        ),
    ),
    Closed(
        claim="direction is predictable on these feeds",
        evidence=(
            "Direction is closed, not just null: the gate finds a *planted* drift at "
            "z +2.90 and earns 2% of a spread. probability_up read 0.6365 on "
            "overlapping touches and 0.5092 de-overlapped."
        ),
        reopen=(
            "a direction claim on a feed with a different microstructure, or one "
            "whose edge exceeds the round-trip spread rather than a fraction of it"
        ),
        keywords=(
            "direction",
            "directional",
            "probability_up",
            "bullish",
            "bearish",
            "predicts continuation",
            "next move",
        ),
    ),
    Closed(
        claim="a trailing z-score identifies reversion",
        evidence=(
            "Trailing z-scores fake reversion: the shuffled twin took +0.111 of a "
            "+0.137 effect at z 4.23 - more than an FX cross's spread is worth."
        ),
        reopen="a reversion measure whose shuffled twin does not reproduce it",
        keywords=(
            "z-score",
            "zscore",
            "z score",
            "reversion",
            "mean revert",
            "overbought",
            "oversold",
        ),
    ),
    Closed(
        claim="strategy rotation can be timed",
        evidence=(
            "Every pause rule tested matched random pausing at the same duty cycle. "
            "Controlling for duty cycle removed the whole effect."
        ),
        reopen="a rotation rule that beats random pausing at a matched duty cycle",
        keywords=(
            "rotation",
            "rotate",
            "pause",
            "duty cycle",
            "turn off",
            "disable when",
        ),
    ),
    Closed(
        claim="a martingale or recovery sizing scheme can pay",
        evidence=(
            "Any positive expectancy on a walk is a bug. Settling on the fill bar won "
            "0.470 of 2R races against a required 0.333, which was the bug."
        ),
        reopen="nothing; this is arithmetic rather than a measurement",
        keywords=(
            "martingale",
            "recovery",
            "double down",
            "averaging down",
            "after a loss",
        ),
    ),
    Closed(
        claim="the level magnet effect exists",
        evidence=(
            "Refuted in docs/ alongside the rolling-quantile edge gates. A magnet is "
            "a shared reference - liquidity rests where many participants compute the "
            "same price - so the testable form is watchedness and the time exponent."
        ),
        reopen="a watchedness measure, not a proximity measure",
        keywords=(
            "magnet",
            "attractor",
            "round number",
            "psychological level",
            "gravitate",
        ),
    ),
    Closed(
        claim="the up/down window edge is tradable",
        evidence=(
            "Good fills and -98%. The windows settle on Chainlink and were priced off "
            "Binance: a 0.38 sigma gap turns 0.500 into 0.648, which was the whole "
            "apparent edge. Fill quality is not signal validation."
        ),
        reopen="a feed that settles on what it is priced from",
        keywords=(
            "up/down",
            "updown",
            "binary window",
            "polymarket window",
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class Established:
    """A finding that *held*, which the register must not flag as closed."""

    claim: str
    evidence: str
    keywords: tuple[str, ...] = ()


#: What has survived here. **Checked before `REGISTER`, and that is not a
#: nicety.** The loose matcher flagged "dispersion is forecastable from the
#: bar range" as closed, because "range" is a keyword on the topology entry -
#: and that claim is this desk's strongest measured result. Flagging an
#: established finding as refuted is not an error in the cheap direction; it
#: is the expensive one.
ESTABLISHED: tuple[Established, ...] = (
    Established(
        claim="dispersion is forecastable, and the range is what drives it",
        evidence=(
            "Drive Q from the range: the range-versus-close estimator ratio reads "
            "0.648 within volatility strata on FX and 0.667 on 371 of 392 equities, "
            "and it grows as the window shortens."
        ),
        keywords=("dispersion", "variance", "volatility forecast", "garman", "range estimator"),
    ),
    Established(
        claim="the ladder belongs on log-volatility",
        evidence="+191 to +547 on 7 of 7 markets, and loses on 5 of 5 controls.",
        keywords=("ladder", "log-volatility", "log volatility"),
    ),
    Established(
        claim="the clock and the loop compose",
        evidence=(
            "+1567 together against +848 and +518 alone. The loop costs 933 where Q "
            "is constant and the clock costs 2, so they are not the same mechanism."
        ),
        keywords=("activity clock", "volume time", "q clock"),
    ),
    Established(
        claim="a Student-t band with 3 to 5 dof fixes the one-bar miscalibration",
        evidence="64 of 64 out of sample; only the one-bar band was miscalibrated.",
        keywords=("student-t", "one-bar band", "calibration"),
    ),
    Established(
        claim="one-sided quote revisions are 22.8% and are the only directional observable here",
        evidence=(
            "Measured on the terminal: flags 4 (ask only) 10.0%, 130 (bid only) 12.8%, "
            "134 (both) 77.2%. Testing flags in (2, 4) reports 10.0%, which is the "
            "error - bit 128 is undocumented."
        ),
        keywords=("quote asymmetry", "one-sided", "one sided", "tick flags"),
    ),
)


#: Which null a shape claim needs, by what kind of shape it is.
#:
#: **Trading direction is trading geometry**, so a null that removes direction
#: removes the thing being traded and every directional claim fails it by
#: construction. That is a tautology, not a control. The nulls below keep the
#: traded quantity and break only the *identification*.
SHAPE_NULLS: dict[str, str] = {
    "geometric": (
        "distance-matched placebo: keep the geometry - the same displacement size, "
        "the same retracement depth, the same distance to target - and move only "
        "*which* points are called the shape. This is what matched the displacement "
        "origin's 82% on every class, and a walk reads 0.825."
    ),
    "topological": (
        "a walk through the same detector, with the same bar geometry: connectivity "
        "and ordering are scale-free, so the null has to reproduce the *sequence* "
        "structure rather than the distances. Sweep the reach and test both sides, "
        "because a one-sided topological claim is half a claim."
    ),
}

#: Nulls that cannot judge a directional claim, and why.
TAUTOLOGICAL: dict[str, str] = {
    "sign-flip": "removes direction, which a directional claim is the bet on",
    "vol-path walk": "removes direction per observation; strictly worse for this",
}


def established(claim: str) -> Established | None:
    """Has this claim already *held* here? Checked before the closed register."""
    text = " " + claim.lower().replace("-", " ") + " "
    best: tuple[int, Established] | None = None
    for entry in ESTABLISHED:
        hits = sum(1 for word in entry.keywords if word.replace("-", " ") in text)
        if hits and (best is None or hits > best[0]):
            best = (hits, entry)
    return best[1] if best else None


def null_for(kind: str) -> str:
    """The null a shape claim of this kind needs.

    `kind` is "geometric" - distances, sizes, angles, scale-dependent - or
    "topological" - connectivity, ordering, enclosure, scale-free. They need
    different nulls, and using one for the other is how a geometric confound
    passes a topological test.
    """
    if kind not in SHAPE_NULLS:
        raise ValueError(f"kind must be one of {sorted(SHAPE_NULLS)}, got {kind!r}")
    return SHAPE_NULLS[kind]


def check(claim: str) -> Closed | None:
    """Is this claim one the register has already closed?

    Matched on each entry's own keywords, which is duller than inferring them
    from the claim sentence and catches what inference missed: word overlap
    failed on "an engulfing candle shape predicts continuation" against
    "candlestick and SMC shapes carry an edge", because the only shared stem
    was shape/shapes.

    Deliberately loose. A false match costs a sentence of justification and a
    missed one costs a sweep, so the error is made in the cheap direction.
    """
    text = " " + claim.lower().replace("-", " ") + " "
    best: tuple[tuple[int, int], Closed] | None = None
    for entry in REGISTER:
        matched = [w for w in entry.keywords if w.replace("-", " ") in text]
        if not matched:
            continue
        # **Ranked by the longest match, then by count.** A longer keyword is
        # a more specific one: "transitions between candle shapes" hits
        # `candle`, `shape` and `next move` on the shapes entry and only
        # `transitions` on its own - so counting hits returned the general
        # entry for a specific claim. Both are closed, so the warning was
        # right either way, but the specific entry carries the evidence that
        # actually applies.
        score = (max(len(w) for w in matched), len(matched))
        if best is None or score > best[0]:
            best = (score, entry)
    return best[1] if best else None


def warn(claim: str) -> str:
    """A line for a proposal that touches a closed question, or an empty one.

    An established finding wins over a closed one, because the matcher is
    loose and the cost of the two mistakes is not symmetric: a spurious
    "already refuted" on this desk's best result would stop the work that
    does pay.
    """
    held = established(claim)
    if held is not None:
        return ""
    entry = check(claim)
    if entry is None:
        return ""
    return (
        f"'{claim}' touches a closed question - {entry.claim}. {entry.evidence} "
        f"To reopen it: {entry.reopen}."
    )


def summary() -> str:
    return f"{len(REGISTER)} closed questions on record"
