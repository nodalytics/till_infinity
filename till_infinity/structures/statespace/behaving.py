"""What each market class measurably *is*, as a table the library can look up.

`bounding.SHIFTS` holds the measured barrier walls per synthetic family and
`bounding.shifts_for` resolves a feed name to them. That pattern - measure once,
record the constant, let callers look it up by name - is the right one, and it
was about to be duplicated: a second table of measured per-class behaviour
would have carried a second copy of the same prefix matching.

So the classifier lives here once, `bounding.shifts_for` uses it, and this
module adds the traits that are not about barriers.

## The three-way split, which is the finding rather than the schema

`statespace-orderflow-from-bars.md` compared each instrument's intra-bar
geometry against a **matched random walk** built from its own per-bar tick
counts. The ratio of `|imbalance|` - how far from the middle of its range a bar
closes - to the walk's own value separates markets into three states, and the
separation is unanimous within each:

| state | ratio | what it is |
| --- | ---: | --- |
| **absorbing** | 0.94 to 0.97 | a real book: price travels its range and comes back |
| **neutral** | 1.00 | a generator with no jumps. `Step_Index_200` reads **0.998** |
| **running** | 1.13 to 1.23 | a generator with jumps: a bar containing one closes at its extreme |

The neutral row is not a rounding of either neighbour. `Step_Index_200` is
specified as a pure step process with no jump in it, and it reads as neither
absorbing nor running - which is what its specification says it is.

The middle row is why this is worth a table. A two-way "real against generated"
split would have put `Step_Index_200` on the wrong side of a line; measured, it
sits exactly on the walk, and the families that depart from it are the ones
whose generators contain a jump. The statistic was not designed to find jumps.

## What the traits are for

**Not for prediction.** None of these is a signal and `orderflow_from_bars.py`
measured what the directional version is worth - about a quarter of a spread.
They are for **configuration and for checking**:

* `activity_extent` says whether driving `Q` from activity can do anything at
  all. The synthetics post a nearly fixed tick count, so their activity share
  is one and `pacing.Pace` is inert on them without being told to be. A caller
  that wants to know *in advance* can ask here;
* `absorption` is a **specification test**. A synthetic family whose ratio
  drifts off its recorded value has changed, and that is worth knowing about a
  venue that generates its own feeds;
* `tail_alpha` says which moments exist. Below 2 there is no variance and below
  1 no mean, and the measured values forbid quoting a kurtosis as a parameter.

## Unmeasured means absent, not assumed

Equities, crypto and the FX crosses are not in this table because they were not
in the study that produced it. `traits_for` returns `None` for them, in the same
spirit as `shifts_for` returning a symmetric wall for an unlisted feed: an
unmeasured class has not been measured, and a plausible-looking default is the
one thing a lookup table must never invent.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Prefixes that name a generated family, longest first so `dex_` resolves
#: before any shorter match could.
GENERATED_PREFIXES = (
    "dex_",
    "drift_switch",
    "multi_step",
    "skew_step",
    "step",
    "boom",
    "crash",
    "volatility",
    "jump",
    "range_break",
    # `Spot_Up_-_Volatility_Up_Index`. Found by `class_traits.py`, which
    # reported fifteen instruments as `unknown` - fourteen stock indices and
    # this one generated feed.
    "spot",
)

#: Traded classes, by the names the cache uses. Checked after the generated
#: prefixes, because a traded symbol never starts with one of those.
TRADED_CLASSES: dict[str, tuple[str, ...]] = {
    "metal": ("XAUUSD", "XAGUSD", "XPTUSD", "XPDUSD", "XCUUSD"),
    "energy": ("US_Oil", "UK_Brent_Oil", "NGAS"),
    "basket": ("USD_Basket", "EUR_Basket", "GBP_Basket"),
    "soft": ("Sugar", "Cocoa", "Cotton", "CoffeeArab", "CoffeeRobu"),
    #: Cash stock indices. They were `unknown` until `class_traits.py` listed
    #: what the classifier was failing to name, and they are traded - they
    #: absorb at -0.0438 with an activity extent of 7.95.
    "index": (
        "Germany_40",
        "France_40",
        "UK_100",
        "Japan_225",
        "Hong_Kong_50",
        "Europe_50",
        "Swiss_20",
        "Spain_35",
        "Netherlands_25",
        "US_SP_500",
        "US_Tech_100",
        "Wall_Street_30",
        "US_Mid_Cap_400",
        "US_Small_Cap_2000",
    ),
}

#: The eight majors, as the pairs that are quoted against the dollar either way.
FX_MAJORS = (
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "USDCHF",
    "USDCAD",
    "AUDUSD",
    "NZDUSD",
)


def classify(feed: str) -> str:
    """The family a feed name belongs to. One place, used by `bounding` too.

    Returns a generated family name (`boom`, `dex_up`, `step`, ...), a traded
    class (`fx_major`, `fx_cross`, `metal`, `energy`, `basket`, `soft`,
    `equity`), or `"unknown"`.
    """
    raw = str(feed)
    name = raw.lower()
    if name.startswith("dex_"):
        if name.endswith("up_index"):
            return "dex_up"
        if name.endswith("down_index"):
            return "dex_down"
        return "dex"
    for prefix in GENERATED_PREFIXES:
        if name.startswith(prefix):
            return prefix.rstrip("_")
    for label, names in TRADED_CLASSES.items():
        if raw in names:
            return label
    # Reuters-coded equities, which the cache holds as `AAPL.OQ` and `JPM.N`.
    if "." in raw and raw.rsplit(".", maxsplit=1)[-1].isalpha():
        return "equity"
    letters = "".join(c for c in raw if c.isalpha())
    if len(letters) == 6 and letters.isupper():
        return "fx_major" if raw in FX_MAJORS else "fx_cross"
    return "unknown"


def geometry(opens, highs, lows, closes) -> dict[str, float]:
    """The intra-bar statistics `TRAITS` is built from, so it can be rebuilt.

    `imbalance` is `(C - O) / (H - L)` - where in its own range the bar closed -
    and `wick` is `((H - C) - (C - L)) / (H - L)`, which side was rejected.
    Returned as medians of their absolute values, plus the share of bars that
    closed past half their range.

    **A figure from this means nothing on its own.** All three take perfectly
    ordinary values on a random walk, because they are functions of path
    geometry rather than of order flow - which is why `TRAITS.absorption` is a
    **ratio to a matched walk** and not a level. `absorption` below computes
    that ratio once a caller has the walk's own value.
    """
    import numpy as np

    opens = np.asarray(opens, dtype=float)
    highs = np.asarray(highs, dtype=float)
    lows = np.asarray(lows, dtype=float)
    closes = np.asarray(closes, dtype=float)
    span = highs - lows
    keep = span > 0
    if keep.sum() < 100:
        return {}
    opens, highs, lows, closes, span = (v[keep] for v in (opens, highs, lows, closes, span))
    imbalance = (closes - opens) / span
    wick = ((highs - closes) - (closes - lows)) / span
    return {
        "imbalance": float(np.median(np.abs(imbalance))),
        "wick": float(np.median(np.abs(wick))),
        "run_share": float(np.mean(np.abs(imbalance) > 0.5)),
        "bars": float(len(span)),
    }


def absorption(measured: float, walk: float) -> float:
    """`measured / walk - 1`: the fingerprint, as a departure from a walk.

    Negative absorbs - a real order book, where price travels its range and
    comes back. Zero is a walk. Positive runs - a generator with a jump, whose
    bars close at their extremes.

    The departures are a few per cent, so **the sign is the claim and the
    magnitude only its size**. Measured across nineteen classes and about five
    hundred instruments, the sign separates a real book from a generator with
    no exceptions: every traded class absorbs, every jump generator runs, and
    every jump-free generator is neutral.
    """
    if not walk:
        return float("nan")
    return measured / walk - 1.0


@dataclass(frozen=True, slots=True)
class Traits:
    """What one market class was measured to do. Every field has a source."""

    #: `|imbalance|` over a matched walk's own `|imbalance|`, minus one. The
    #: sign is the state: negative absorbs, zero is a walk, positive runs.
    #: From `statespace-orderflow-from-bars.md`.
    absorption: float

    #: Ninetieth over tenth percentile of `pacing.shares`. One means a fixed
    #: tick count and so an inert activity channel. From
    #: `statespace-activity-on-q.md`'s survey of 553 cached feeds at 1h.
    activity_extent: float

    #: The exponent relating a bar's variance to its activity share, swept
    #: with a turn on both sides. `None` where activity carries nothing.
    q_exponent: float | None

    #: Hill tail index on raw returns, from `statespace-measurement-audit.md`.
    #: Below 2 no variance exists, below 1 no mean.
    tail_alpha: float | None

    @property
    def absorbs(self) -> bool:
        """A real order book, by the sign of its intra-bar geometry."""
        return self.absorption < -0.01

    @property
    def runs(self) -> bool:
        """A generator with a jump in it."""
        return self.absorption > 0.01

    @property
    def informative_activity(self) -> bool:
        """Whether driving `Q` from activity can do anything on this class."""
        return self.activity_extent > 1.5


#: Measured per class by `research/ideas/class_traits.py`, at 1h, each
#: instrument against **its own matched walk** - a walk built from that
#: instrument's per-bar tick counts and volatility, so path geometry is removed
#: rather than assumed away.
#:
#: **The sign separates a real order book from a generator with no exceptions.**
#: Nineteen classes and about five hundred instruments:
#:
#: * every **traded** class absorbs - basket, energy, equity, both FX classes,
#:   index, metal, soft;
#: * every generated family **with a jump** runs - boom, crash, both DEX
#:   directions, drift switch, jump, range break;
#: * every generated family **without** one is neutral - the three step
#:   variants and the volatility indices, which read `-0.0005`.
#:
#: Not one traded class fails to absorb and not one generated class absorbs,
#: which is what makes this a fingerprint rather than an index. The departures
#: are a few per cent, so the **sign** is the claim and the magnitude only its
#: size.
#:
#: `q_exponent` is recorded only where `activity_clock.py` actually swept it -
#: the three traded classes it ran on - and is `None` elsewhere. A class whose
#: `activity_extent` is near one cannot have one at all.
TRAITS: dict[str, Traits] = {
    # Traded: all absorbing, with activity worth driving `Q` from.
    "fx_major": Traits(absorption=-0.0439, activity_extent=5.678, q_exponent=2.0, tail_alpha=2.90),
    "fx_cross": Traits(absorption=-0.0698, activity_extent=4.421, q_exponent=None, tail_alpha=2.90),
    "metal": Traits(absorption=-0.0623, activity_extent=5.814, q_exponent=2.0, tail_alpha=2.62),
    "energy": Traits(absorption=-0.0369, activity_extent=9.420, q_exponent=2.0, tail_alpha=2.40),
    # The most uneven activity in the cache by a wide margin, which is what a
    # market with a session open and close looks like.
    "equity": Traits(absorption=-0.0801, activity_extent=26.335, q_exponent=None, tail_alpha=2.44),
    "index": Traits(absorption=-0.0438, activity_extent=7.954, q_exponent=None, tail_alpha=2.72),
    "soft": Traits(absorption=-0.0276, activity_extent=2.995, q_exponent=None, tail_alpha=3.42),
    # Traded, but a **derived** quote: the basket absorbs like a real market
    # and its tick count is nearly fixed, so the activity channel is inert on
    # it for a reason that has nothing to do with its being generated.
    "basket": Traits(absorption=-0.0519, activity_extent=1.111, q_exponent=None, tail_alpha=2.81),
    # Generated, with a jump in the generator: all running.
    "boom": Traits(absorption=+0.1058, activity_extent=1.007, q_exponent=None, tail_alpha=5.34),
    "crash": Traits(absorption=+0.0968, activity_extent=1.006, q_exponent=None, tail_alpha=5.37),
    "dex_up": Traits(absorption=+0.2276, activity_extent=1.009, q_exponent=None, tail_alpha=4.08),
    "dex_down": Traits(absorption=+0.2309, activity_extent=1.005, q_exponent=None, tail_alpha=4.04),
    "drift_switch": Traits(
        absorption=+0.2086, activity_extent=1.016, q_exponent=None, tail_alpha=8.52
    ),
    "jump": Traits(absorption=+0.0490, activity_extent=1.002, q_exponent=None, tail_alpha=5.67),
    "range_break": Traits(
        absorption=+0.1240, activity_extent=1.001, q_exponent=None, tail_alpha=3.24
    ),
    # Generated, without one: neutral, which is the row that makes the table
    # three-way. The volatility indices are specified geometric Brownian
    # motion and read -0.0005 - a pure walk, to four places.
    "step": Traits(absorption=-0.0033, activity_extent=1.001, q_exponent=None, tail_alpha=5.94),
    "multi_step": Traits(
        absorption=+0.0077, activity_extent=1.001, q_exponent=None, tail_alpha=6.01
    ),
    "skew_step": Traits(
        absorption=-0.0061, activity_extent=1.000, q_exponent=None, tail_alpha=5.73
    ),
    "volatility": Traits(
        absorption=-0.0005, activity_extent=1.003, q_exponent=None, tail_alpha=6.06
    ),
}


def traits_for(feed: str) -> Traits | None:
    """What this feed's class was measured to do, or `None` if unmeasured.

    `None` rather than a default. An unmeasured class has not been measured,
    and the one thing a table of measurements must not do is invent a
    plausible row for a market nobody looked at.
    """
    return TRAITS.get(classify(feed))


def drives_q(feed: str) -> bool:
    """Whether an activity channel on `Q` is worth wiring for this feed.

    Unmeasured classes return `True`: `pacing.Pace` is self-limiting - a feed
    with a fixed tick count has a share of one and a factor of one - so the
    cost of trying is nothing and the cost of refusing a market that was never
    studied is a mechanism that silently does not run.
    """
    traits = traits_for(feed)
    return True if traits is None else traits.informative_activity
