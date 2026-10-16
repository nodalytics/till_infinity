"""Where the inside-bar excess lives: the clock, the coupling, or the marginal.

[`family-fits.md`](../docs/family-fits.md) fitted a mean-reverting sub-bar term
and took every traded class from 70-131 away from its nearest process family to
4.8-25.4, which is where the Deriv synthetics sit. Three shape statistics that
no parameterisation could reach - `imbalance`, `body share`, `CRT` - went away.

What is left leads on **`inside bar`** on every traded class, at `z` 4.9 to
13.7: markets read 0.149 to 0.194 where the fitted families give 0.126 to
0.135. This asks what produces it, and the question is asked of the data
before any new family is built.

## An inside bar is a joint event, not a size

A bar is inside its predecessor when `high <= prior high` and
`low >= prior low`. Because the child opens at the parent's close, that needs
**two** things at once: the parent has to close away from its own extremes -
otherwise the child's first tick is already at the boundary and one side can
only be equalled, never beaten - and the child has to be small. So the rate
couples the parent's **shape** to the child's **size**, and there are three
candidate sources:

1. **the marginal** - how dispersed bar sizes are, with no dependence at all;
2. **the clock** - a deterministic hour-of-day activity cycle, so a quiet hour
   systematically follows a busy one (`seasonality-belongs-on-q`: intraday
   pattern lives in volatility, and FX peaks at three times its trough);
3. **the coupling** - a wide reversing bar actually predicting a quiet one,
   which is consolidation and is a volatility-of-volatility story.

## How they are separated, on one detector

Each bar is reduced to its **own geometry** in logs - the gap into it, the
reach above its open, the reach below, and its body - and a series is rebuilt
from those tuples in a new order, chaining each open onto the previous close.
Every bar keeps its exact shape and only the order changes, so the detector
never sees a different kind of bar
(`null-structure-claims-on-the-same-detector`):

| arm | keeps | destroys |
| --- | --- | --- |
| `real` | everything | - |
| `by hour` | the hour profile - a bar is only replaced by one from its own
  slot | day-to-day dependence |
| `shuffled` | the marginal alone | the hour profile and all dependence |
| `no gap` | the order, with every gap set to zero | the close-to-open move |

`body share` and the median reach are per-bar marginals and **must** be
identical across the first three arms. They are printed as an invariant,
because a rebuild that silently changed a bar's geometry would otherwise look
like a finding.

## The sign, which a smoke test got the wrong way round first

A planted smooth 24-bar cycle of span 10 was put through these arms before any
market was touched. It read `real` 0.182, `by hour` 0.139, `shuffled` 0.242 -
so **the clock lowered the inside rate** rather than raising it, and the
shuffle was the highest of the three. The reason is that a smooth cycle makes
neighbouring bars **similar in size**, and nesting needs a *difference*; any
positive dependence in bar size - a cycle or GARCH clustering alike - therefore
suppresses nesting relative to free draws from the same marginal.

So `shuffled` is an **upper bound** and not a baseline, and the readings are:

- `shuffled - real`, how much the ordering suppresses nesting in total;
- `shuffled - by hour`, how much of that the hour profile alone accounts for;
- `real - no gap`, what the close-to-open move contributes, which came out
  **negative** on the toy.

The same toy read `real` **above** its `by hour` with no day-to-day coupling
planted at all, and its `no gap` arm at 0.219 against a real 0.182 - so the
close-to-open move alone was worth 0.037 of inside-bar rate, which is larger
than the entire market residual being chased here. The arms are therefore
entangled rather than additive, and the `no gap` arm is necessary rather than
tidy: a bid-ask bounce lands squarely in that move, and the families already
carry one.

With the sign known, the question the residual poses becomes answerable: the
fitted family is at 0.126-0.135 and the market at 0.149-0.194, and either the
market's **bound** is higher - its reach distribution is more dispersed at
matched return kurtosis - or the market's **suppression** is weaker. The
dispersion of the reach is therefore reported beside the arms, since the
fingerprint never measured it.

## The control

The Deriv synthetics run without a session, with no auction and a constant tick
rate (`deriv-synthetics-are-real-markets`). Their clock term has to come out at
nothing. If the `by hour` arm moves them, it is measuring the stratification
and not a cycle.

## Stage two, registered before the market arms were read

Three mechanisms were put through the arms on 1,200 simulated bars, on top of
the `micro` family fx majors picked, before stage 1 was ever run:

| mechanism | inside | reach 90/10 |
| --- | ---: | ---: |
| none | 0.125 | 2.6 |
| `clock`, a deterministic 24-bar cycle at amplitude 0.7 | 0.128 | 5.2 |
| `slow`, AR(1) log variance, amplitude 0.6, phi 0.95 | 0.128 | 3.6 |
| `burst`, i.i.d. gamma activity, shape 3 | **0.157** | 3.6 |
| `burst`, shape 1 | **0.218** | 6.4 |

The market sits at 0.149-0.194. **Only the i.i.d. burst reaches it**, and the
two mechanisms that carry memory - the cycle and the slow component - leave the
rate where it was while moving the reach's spread as much. That is the smoke
test's sign again: nesting needs neighbouring bars to *differ*, so a scale that
varies **unpredictably** from bar to bar produces it and a scale that varies
smoothly does not.

So the prediction for stage 1 is that the market's own `order` column is
**small** - its `real` close to its `shuffled` - and its reach 90/10 high,
because that is the signature an i.i.d. burst leaves. A market whose `real` sat
far below its `shuffled` would be clustering-dominated and would need the other
answer.

An i.i.d. burst has a cost that is worth stating before it is paid: it dilutes
the **size autocorrelation**, which the fitted families already match at 0.21.
`both` is therefore carried as a fourth mechanism - an i.i.d. burst times a
persistent component - and the full fingerprint distance is printed beside
every mechanism so that buying the inside-bar rate with something else is
visible rather than quiet.

## Stage two is a signature check and not a fit

Mechanisms are simulated on top of the family each class already picked. The
question is not which fits best - that would need a joint refit - but which one
reproduces the **decomposition**, since a mechanism can reach the right
inside-bar rate by the wrong route and the arms tell them apart.

## What the first pass measured, and why this one differs

The registered prediction was **refuted**. Every traded class came back with a
large positive `order` - `shuffled` 0.197 to 0.229 against a `real` 0.141 to
0.170 - so bar scale varies *predictably* and the ordering holds the inside
rate **down** by 0.044 to 0.072. An i.i.d. burst leaves that column at zero,
which is the opposite signature. The hour profile accounted for 0.018 to 0.032
of it, between a third and a half.

The Deriv feeds controlled it exactly: `order` -0.001 to +0.001, `span` 1.04
to 1.06. The `gap` arm, worth 0.037 on the toy, came out at 0.002 on every
market.

What stands out is the marginal the fingerprint never measured: the reach's
90/10 spread is **4.7 to 6.7** on traded classes against 2.7 to 3.1 for every
fitted family. So a market's bar sizes are twice as spread out *and* strongly
dependent, and the two pull the inside rate in opposite directions.

Three things follow, and this pass makes them:

1. **The clock is measured, not fitted.** A span of `S` fixes the amplitude of
   a `exp(a cos)` cycle at `a = ln(S)/2`, so each class gets its own observed
   cycle and only what sits *on top* of it is swept. The simulated span is
   printed beside the measured one so the calibration is visible.
2. **The arms must share a pair set.** `real` ran on contiguous pairs while the
   permutations ran on every pair, which is harmless at 0.9% seams on FX and
   wrong on a session-limited instrument: softs came back with an inverted
   `quiet`/`busy` split and a negative `order`. Both arms now use only bars
   whose incoming gap is contiguous.
3. **The horizon of the suppression is worth knowing.** A block shuffle keeps
   dependence inside a block and destroys it beyond, so sweeping the block
   length from 2 bars to 120 says whether the clustering that suppresses
   nesting is intraday or multi-day.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from family_fits import (  # noqa: E402
    BARS,
    PER_CLASS,
    SUB,
    STATS,
    bars_from,
    draws,
    gap,
    pooled,
    steps_for,
)
from pattern_fingerprint import (  # noqa: E402
    CACHE,
    classify,
    fingerprint,
    load,
)

FRAME = "1h"
HOURS = 24
SEED = 20261016
#: Permutation draws per arm, for a mean and a spread.
REDRAWS = 6
#: Replicates per simulated point, matching `family_fits` so the distance
#: column means the same thing it does there.
REPLICATES = 4
#: Fewest usable pairs before an instrument is skipped.
LEAST_PAIRS = 4000
#: Block lengths for the horizon sweep. One block is kept intact and the
#: blocks are reordered, so a length of 1 is the full shuffle and a length of
#: the whole series is the real thing.
BLOCKS = (2, 6, 24, 120)
TRADED = ("fx_major", "fx_cross", "metal", "index", "energy", "soft", "basket")
GENERATED = ("volatility", "step", "boom", "jump")
#: The family each class picked in `family-fits.md`, with its fitted point.
PICKED = {
    "fx_major": ("micro", (1.0, 0.6)),
    "fx_cross": ("micro", (1.0, 0.6)),
    "basket": ("micro", (1.0, 0.6)),
    "metal": ("joint", (0.38, 0.60, 0.7)),
    "index": ("joint", (0.38, 0.60, 0.7)),
    "energy": ("joint", (0.38, 0.60, 0.7)),
    "soft": ("joint", (0.38, 0.60, 0.4)),
}
#: Stage two. Each of these is run alone and again on top of the class's own
#: calibrated cycle, so the table reads as "what the observed daily cycle
#: leaves behind".
ON_TOP: tuple[tuple[str, tuple], ...] = (
    ("none", ()),
    ("burst", (8.0,)),
    ("burst", (3.0,)),
    ("burst", (1.5,)),
    ("slow", (0.3, 0.98)),
    ("slow", (0.6, 0.98)),
)


def geometry(bars: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Each bar's own shape in logs: the gap into it and three reaches.

    The gap of the first bar is unused by the rebuild of a permuted series -
    it only sets where the path starts - so it is left at zero.
    """
    log = {k: np.log(bars[k]) for k in ("open", "high", "low", "close")}
    count = len(log["open"])
    into = np.zeros(count)
    into[1:] = log["open"][1:] - log["close"][:-1]
    return {
        "gap": into,
        "up": log["high"] - log["open"],
        "down": log["open"] - log["low"],
        "body": log["close"] - log["open"],
    }


def rebuild(shape: dict[str, np.ndarray], order: np.ndarray) -> dict[str, np.ndarray]:
    """A log-price series from these bars' geometry, taken in this order."""
    into = shape["gap"][order]
    body = shape["body"][order]
    closes = np.cumsum(into + body)
    opens = closes - body
    return {
        "open": opens,
        "high": opens + shape["up"][order],
        "low": opens - shape["down"][order],
        "close": closes,
    }


def nested(series: dict[str, np.ndarray], valid: np.ndarray | None = None) -> float:
    """Inside-bar rate: the whole reach within the previous bar's."""
    high, low = series["high"], series["low"]
    hit = (high[1:] <= high[:-1]) & (low[1:] >= low[:-1])
    return float(hit[valid].mean()) if valid is not None else float(hit.mean())


def swallowed(series: dict[str, np.ndarray], valid: np.ndarray | None = None) -> float:
    """Engulf rate, the complementary event, as the control on direction."""
    high, low = series["high"], series["low"]
    reach = high - low
    hit = (high[1:] >= high[:-1]) & (low[1:] <= low[:-1]) & (reach[1:] > reach[:-1])
    return float(hit[valid].mean()) if valid is not None else float(hit.mean())


def marginals(series: dict[str, np.ndarray]) -> tuple[float, float]:
    """`(median body share, median reach)` - invariant under any reordering."""
    reach = series["high"] - series["low"]
    good = reach > 0
    body = np.abs(series["close"] - series["open"])
    return float(np.median(body[good] / reach[good])), float(np.median(reach[good]))


def dispersion(series: dict[str, np.ndarray]) -> float:
    """The reach's 90th percentile over its 10th, in logs.

    The fingerprint carries the kurtosis of the **return** and the
    autocorrelation of its size, and nothing about how spread out a bar's
    **reach** is - which is the quantity nesting actually depends on. It is
    invariant to a reordering, so it belongs with the marginals.
    """
    reach = series["high"] - series["low"]
    reach = reach[reach > 0]
    if len(reach) < 100:
        return float("nan")
    low = float(np.quantile(reach, 0.1))
    return float(np.quantile(reach, 0.9) / low) if low > 0 else float("nan")


def slots(times: np.ndarray, step: float) -> np.ndarray:
    """Hour-of-day slot per bar, from the broker's own clock."""
    return ((times // step).astype(np.int64) % HOURS).astype(np.int64)


def by_hour_order(hours: np.ndarray, rng) -> np.ndarray:
    """A permutation that only ever swaps bars sharing an hour slot."""
    order = np.arange(len(hours))
    for hour in np.unique(hours):
        where = np.flatnonzero(hours == hour)
        if len(where) > 1:
            order[where] = rng.permutation(where)
    return order


def block_order(count: int, length: int, rng) -> np.ndarray:
    """Contiguous blocks of `length`, kept intact and reordered."""
    cuts = np.arange(length, count, length)
    pieces = np.split(np.arange(count), cuts)
    rng.shuffle(pieces)
    return np.concatenate(pieces)


def decompose(bars, hours, pairs, pool, rng) -> dict:
    """The arms on one series, plus the marginal invariants.

    `pairs` selects which consecutive pairs the `real` and `no gap` arms read,
    and `pool` which bars the permutations draw from. They are chosen together
    so that both only ever involve bars whose incoming gap is a real one: a
    session break carried into a rebuilt series is a gap no intraday bar ever
    has, and on a session-limited instrument there are enough of them to
    reverse the sign of the answer.
    """
    shape = geometry(bars)
    count = len(hours)
    straight = rebuild(shape, np.arange(count))
    out = {
        "pairs": int(pairs.sum()) if pairs is not None else count - 1,
        "real": nested(straight, pairs),
        "real engulf": swallowed(straight, pairs),
        "reach 90/10": dispersion(straight),
    }
    out["share"], out["reach"] = marginals(straight)
    # The order is kept and only the close-to-open move is removed, so this arm
    # is not a permutation and the marginal invariant does not apply to it.
    flat = dict(shape)
    flat["gap"] = np.zeros_like(shape["gap"])
    out["no gap"] = nested(rebuild(flat, np.arange(count)), pairs)

    inner = {k: v[pool] for k, v in shape.items()} if pool is not None else shape
    seats = hours[pool] if pool is not None else hours
    size = len(seats)
    # The invariant has to be read on the bars the permutations actually use.
    # Read on the whole series instead, the pool - which drops the bar that
    # starts each contiguous run - shows up as a 0.002 discrepancy and looks
    # like a broken rebuild.
    out["share"] = marginals(rebuild(inner, np.arange(size)))[0]
    arms: list[tuple[str, object]] = [
        ("by hour", lambda: by_hour_order(seats, rng)),
        ("shuffled", lambda: rng.permutation(size)),
    ]
    arms += [(f"block {n}", (lambda n=n: block_order(size, n, rng))) for n in BLOCKS]
    for arm, maker in arms:
        got, engulfed, shares = [], [], []
        for _ in range(REDRAWS):
            moved = rebuild(inner, maker())
            got.append(nested(moved))
            engulfed.append(swallowed(moved))
            shares.append(marginals(moved)[0])
        out[arm] = float(np.mean(got))
        out[f"{arm} sd"] = float(np.std(got, ddof=1))
        out[f"{arm} engulf"] = float(np.mean(engulfed))
        out[f"{arm} share"] = float(np.mean(shares))
    return out


def cycle(bars: dict[str, np.ndarray], hours: np.ndarray) -> dict:
    """The activity cycle itself, and the inside rate at each end of it.

    Hour slots with no bars are skipped rather than averaged, because a
    session-limited instrument has them and a median of nothing is a `nan`
    that silently became the whole class's span on the first pass.
    """
    reach = np.log(bars["high"]) - np.log(bars["low"])
    filled = [h for h in range(HOURS) if (hours == h).sum() >= 50]
    if len(filled) < 4:
        return {"slots": len(filled), "span": float("nan")}
    middle = np.array([np.median(reach[hours == h]) for h in filled])
    middle = middle / max(float(np.median(middle)), 1e-12)
    ranked = np.argsort(middle)
    ends = max(1, len(filled) // 4)
    quiet = {filled[i] for i in ranked[:ends]}
    busy = {filled[i] for i in ranked[-ends:]}
    log = {k: np.log(bars[k]) for k in ("high", "low")}
    hit = (log["high"][1:] <= log["high"][:-1]) & (log["low"][1:] >= log["low"][:-1])
    child = hours[1:]
    at_quiet = np.isin(child, list(quiet))
    at_busy = np.isin(child, list(busy))
    return {
        "slots": len(filled),
        "span": float(middle.max() / max(middle.min(), 1e-12)),
        "inside quiet": float(hit[at_quiet].mean()) if at_quiet.any() else float("nan"),
        "inside busy": float(hit[at_busy].mean()) if at_busy.any() else float("nan"),
    }


def by_parent(bars, hours, pairs, rng) -> dict:
    """Inside rate in terciles of the **parent's** body share, real vs shuffled.

    Conditioning on the parent only, never on the child, because the child's
    size is half the outcome. A coupling that lives in the reversing bars - the
    low-body-share parents - shows up here and nowhere else.
    """
    shape = geometry(bars)
    count = len(hours)
    straight = rebuild(shape, np.arange(count))

    def shares(series):
        reach = series["high"] - series["low"]
        good = reach > 0
        body = np.abs(series["close"] - series["open"])
        return np.where(good, body / np.where(good, reach, 1.0), np.nan)

    share = shares(straight)
    cuts = np.nanquantile(share, (1 / 3, 2 / 3))
    bands = (("low", -np.inf, cuts[0]), ("mid", cuts[0], cuts[1]), ("high", cuts[1], np.inf))
    hit = (straight["high"][1:] <= straight["high"][:-1]) & (
        straight["low"][1:] >= straight["low"][:-1]
    )
    fakes = []
    for _ in range(REDRAWS):
        moved = rebuild(shape, rng.permutation(count))
        fakes.append((shares(moved), (moved["high"][1:] <= moved["high"][:-1]) & (
            moved["low"][1:] >= moved["low"][:-1]
        )))
    out = {}
    for label, low, high in bands:
        parent = (share[:-1] > low) & (share[:-1] <= high)
        if pairs is not None:
            parent = parent & pairs
        if parent.sum() < 100:
            continue
        drawn = []
        for share_m, got in fakes:
            mine = (share_m[:-1] > low) & (share_m[:-1] <= high)
            if mine.sum():
                drawn.append(float(got[mine].mean()))
        fake = float(np.mean(drawn)) if drawn else float("nan")
        out[label] = (float(hit[parent].mean()), fake)
    return out


def one_factor(kind: str, theta, bars: int, pots: dict[str, np.ndarray]) -> np.ndarray:
    """One activity layer, before the layers are multiplied together."""
    if kind == "none":
        return np.ones(bars)
    if kind == "clock":
        amplitude = float(theta[0])
        return np.exp(amplitude * np.cos(2.0 * np.pi * np.arange(bars) / HOURS))
    if kind == "burst":
        from scipy.stats import gamma as gamma_law

        shape_k = float(theta[0])
        even = np.clip(pots["burst"][:bars], 1e-9, 1 - 1e-9)
        return np.sqrt(gamma_law.ppf(even, shape_k, scale=1.0 / shape_k))
    if kind == "slow":
        from scipy.signal import lfilter
        from scipy.special import ndtri

        amplitude, phi = float(theta[0]), float(theta[1])
        shocks = ndtri(np.clip(pots["slow"][:bars], 1e-9, 1 - 1e-9))
        level = lfilter([np.sqrt(1.0 - phi**2)], [1.0, -phi], shocks)
        return np.exp(0.5 * amplitude * level)
    raise ValueError(kind)


def factor(layers, bars: int, pots: dict[str, np.ndarray]) -> np.ndarray:
    """The per-bar activity factor, at root-mean-square one so scale is held."""
    out = np.ones(bars)
    for kind, theta in layers:
        out = out * one_factor(kind, theta, bars, pots)
    return out / max(float(np.sqrt(np.mean(out**2))), 1e-12)


def modulated(family: str, theta, layers, common: dict, pots: dict) -> dict:
    """Bars from a picked family with activity layers laid over it."""
    base = steps_for(family, theta, common)[: BARS * SUB].reshape(BARS, SUB)
    steps = (base * factor(layers, BARS, pots)[:, None]).ravel()
    spread = float(np.std(steps))
    return bars_from(steps / spread if spread > 0 else steps, BARS, SUB)


def read_class(names: list[str], rng) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """Every instrument of one class through the arms, the cycle and the cells."""
    arms, cycles, parents, prints = [], [], [], []
    for name in names:
        bars = load(name, FRAME)
        if bars is None:
            continue
        times = bars["time"]
        spacing = np.diff(times)
        step = float(np.median(spacing[spacing > 0])) if len(spacing) else 3600.0
        # `valid[i]` is the pair `(i, i+1)`; a bar is in the pool when its own
        # incoming gap is contiguous, and a pair is read when both of its bars
        # are - so the arms share one multiset of bars.
        valid = np.isclose(spacing, step)
        inpool = np.zeros(len(times), dtype=bool)
        inpool[1:] = valid
        pairs = valid & inpool[:-1]
        if pairs.sum() < LEAST_PAIRS:
            continue
        hours = slots(times, step)
        pool = np.flatnonzero(inpool)
        arms.append(decompose(bars, hours, pairs, pool, rng))
        cycles.append(cycle(bars, hours))
        parents.append(by_parent(bars, hours, pairs, rng))
        prints.append(fingerprint(bars))
    return arms, cycles, parents, prints


def main() -> None:
    rng = np.random.default_rng(SEED)
    print(
        f"Inside bars: the clock, the coupling, or the marginal. {FRAME} bars,\n"
        f"{REDRAWS} permutation draws per arm, every arm on the same detector and\n"
        "the same bars.\n"
    )

    groups: dict[str, list[str]] = {}
    for path in sorted(CACHE.glob(f"*.{FRAME}.npz")):
        name = path.name[: -len(f".{FRAME}.npz")]
        groups.setdefault(classify(name), []).append(name)
    wanted = [c for c in (*TRADED, *GENERATED) if c in groups]

    held: dict[str, dict] = {}
    for label in wanted:
        arms, cycles, parents, prints = read_class(sorted(groups[label])[:PER_CLASS], rng)
        if not arms:
            continue

        def middle(key, source):
            values = [r[key] for r in source if r.get(key) == r.get(key)]
            return float(np.median(values)) if values else float("nan")

        got = {k: middle(k, arms) for k in arms[0]}
        got.update({k: middle(k, cycles) for k in ("slots", "span", "inside quiet", "inside busy")})
        got["parents"] = parents
        got["target"] = pooled(prints) if prints else {}
        held[label] = got

    print("=" * 100)
    print("STAGE 1  the arms, per class")
    print("=" * 100)
    print(
        f"  {'class':<12}{'pairs':>9}{'real':>8}{'by hour':>9}{'shuffled':>10}"
        f"{'no gap':>8}{'order':>8}{'hour':>7}{'gap':>7}"
    )
    for label, got in held.items():
        print(
            f"  {label:<12}{got['pairs']:>9,.0f}{got['real']:>8.3f}{got['by hour']:>9.3f}"
            f"{got['shuffled']:>10.3f}{got['no gap']:>8.3f}"
            f"{got['shuffled'] - got['real']:>8.3f}"
            f"{got['shuffled'] - got['by hour']:>7.3f}"
            f"{got['real'] - got['no gap']:>7.3f}"
        )
    print(
        "\n  order = shuffled - real, the total suppression from the ordering; hour is\n"
        "  the part the hour profile alone accounts for; gap = real - no gap, what the\n"
        "  close-to-open move contributes. A positive order column means the ordering\n"
        "  holds the rate DOWN, which the smoke test said to expect.\n"
    )

    print("  the cycle, the reach's spread, and the engulf control:")
    print(
        f"  {'class':<12}{'slots':>6}{'reach 90/10':>12}{'span':>7}{'quiet':>8}"
        f"{'busy':>8}{'engulf':>9}{'shuf':>8}"
    )
    for label, got in held.items():
        print(
            f"  {label:<12}{got['slots']:>6.0f}{got['reach 90/10']:>12.2f}{got['span']:>7.2f}"
            f"{got['inside quiet']:>8.3f}{got['inside busy']:>8.3f}"
            f"{got['real engulf']:>9.3f}{got['shuffled engulf']:>8.3f}"
        )
    print(
        "\n  slots is how many of the 24 hours the class trades in - a class with fewer\n"
        "  than 24 has a session, and its span and quiet/busy split are not a cycle.\n"
        "  span is the busiest hour's median reach over the quietest's.\n"
    )

    print("  the horizon: blocks kept intact and reordered")
    print(
        f"  {'class':<12}{'real':>8}" + "".join(f"{'b' + str(n):>8}" for n in BLOCKS)
        + f"{'shuffled':>10}"
    )
    for label, got in held.items():
        print(
            f"  {label:<12}{got['real']:>8.3f}"
            + "".join(f"{got[f'block {n}']:>8.3f}" for n in BLOCKS)
            + f"{got['shuffled']:>10.3f}"
        )
    print(
        "\n  Reading left to right is reading the dependence away. Where the curve\n"
        "  leaves the real value is the horizon the suppression lives on.\n"
    )

    print("  invariant check - a reordering cannot move a per-bar marginal:")
    print(f"  {'class':<12}{'body share':>12}{'by hour':>10}{'shuffled':>10}{'block 24':>10}")
    for label, got in held.items():
        print(
            f"  {label:<12}{got['share']:>12.4f}{got['by hour share']:>10.4f}"
            f"{got['shuffled share']:>10.4f}{got['block 24 share']:>10.4f}"
        )

    print("\n" + "=" * 100)
    print("STAGE 1b  inside rate by the parent's body share, real vs shuffled")
    print("=" * 100)
    print(f"  {'class':<12}" + "".join(f"{t:>10}{'shuf':>8}" for t in ("low", "mid", "high")))
    for label, got in held.items():
        line = f"  {label:<12}"
        for tercile in ("low", "mid", "high"):
            real = [c[tercile][0] for c in got["parents"] if tercile in c]
            fake = [c[tercile][1] for c in got["parents"] if tercile in c]
            line += f"{np.median(real):>10.3f}" if real else f"{'-':>10}"
            line += f"{np.median(fake):>8.3f}" if fake else f"{'-':>8}"
        print(line)

    print("\n" + "=" * 100)
    print("STAGE 2  with each class's own cycle calibrated, what is left to add")
    print("=" * 100)
    commons = [draws(BARS * SUB, rng) for _ in range(REPLICATES)]
    pots = [{"burst": rng.random(BARS), "slow": rng.random(BARS)} for _ in commons]
    hours = np.arange(BARS, dtype=np.int64) % HOURS
    for label, (family, theta) in PICKED.items():
        got = held.get(label)
        if got is None or not got["target"]:
            continue
        target = got["target"]
        span = got["span"]
        amplitude = 0.5 * float(np.log(span)) if span == span and span > 1 else 0.0
        print(
            f"  --- {label}, {family}{theta}: class inside {got['real']:.3f}, "
            f"order {got['shuffled'] - got['real']:+.3f}, 90/10 {got['reach 90/10']:.2f}, "
            f"span {span:.2f} -> cycle amplitude {amplitude:.2f}"
        )
        print(
            f"  {'':<10}{'mechanism':<20}{'inside':>8}{'order':>8}{'90/10':>7}"
            f"{'span':>6}{'kurt':>7}{'size ac':>9}{'distance':>10}"
        )
        for clocked in (False, True):
            for kind, phi in ON_TOP:
                if clocked and amplitude <= 0:
                    continue
                layers = ([("clock", (amplitude,))] if clocked else []) + (
                    [] if kind == "none" else [(kind, phi)]
                )
                if not layers:
                    layers = [("none", ())]
                seen, shapes, spans = [], [], []
                for common, pot in zip(commons, pots, strict=True):
                    bars = modulated(family, theta, layers, common, pot)
                    seen.append(decompose(bars, hours, None, None, rng))
                    shapes.append(fingerprint(bars))
                    spans.append(cycle(bars, hours)["span"])
                both = {}
                for stat in STATS:
                    values = [f[stat] for f in shapes if f[stat] == f[stat]]
                    both[stat] = (
                        (float(np.mean(values)), float(np.std(values, ddof=1)))
                        if len(values) > 1
                        else (float("nan"), float("nan"))
                    )
                named = ("cycle + " if clocked else "") + (
                    kind if kind == "none" else f"{kind}{tuple(round(float(x), 2) for x in phi)}"
                )
                inside = float(np.mean([r["real"] for r in seen]))
                shuffled = float(np.mean([r["shuffled"] for r in seen]))
                print(
                    f"  {'':<10}{named:<20}{inside:>8.3f}{shuffled - inside:>8.3f}"
                    f"{np.mean([r['reach 90/10'] for r in seen]):>7.2f}"
                    f"{np.mean(spans):>6.2f}{both['kurtosis'][0]:>7.1f}"
                    f"{both['size ac'][0]:>9.3f}{gap(target, both):>10.1f}"
                )
    print(
        "\n  The target line above each block is what the class actually reads, so a\n"
        "  mechanism has to land on four numbers at once and not just on `inside`.\n"
    )


if __name__ == "__main__":
    main()
