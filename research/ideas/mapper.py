"""Mapper: let topology propose a subpopulation, then test it out of sample.

Asked on 2026-10-14: *we can even use topology to find things we were not
seeing or thinking about before too.*

That is a different mode from everything in `topology.md`, where persistent
homology was asked three questions and answered no to all three. This one lets
it **propose**, which is the mode TDA is actually famous for - Mapper's flares
are how a subpopulation nobody had hypothesised gets found - and it is also the
mode where a rich descriptor space and a free choice of subpopulation will find
something in a walk every time.

So the protocol is the finding here, not the graph:

1. **Discover on the earlier half.** Build the Mapper graph, take every node of
   at least `LEAST` windows, and rank them by how far their forward behaviour
   sits from the pooled mean. Nothing is claimed at this step and no p-value
   from it is reported.
2. **Carry the node as a rule.** A Mapper node is a set, not a rule, so each is
   reduced to its centroid in descriptor space and later-half windows are
   assigned by nearest centroid. That is what makes a proposal testable.
3. **Confirm on the later half** with a label permutation, against the
   **volatility-bin** comparison that killed the shape arm, and against the
   **hour of day**, because this desk's seasonality is already known and a
   rediscovery of it is not a discovery.
4. **Run all of it on a block-shuffled copy.** If the same pipeline proposes an
   equally striking node there, the striking node is the pipeline.

## What it is pointed at

The outcomes are chosen round the one problem this desk has open rather than
round what is easy to measure. Volatility is modelled, direction is closed, and
`no-gaussian-band-is-calibrated` says nothing beats the walk on CRPS while the
**tail shape** stays unsolved. So the panel carries the two tail readings that
would matter if a subpopulation did exist: the ratio of adverse to favourable
excursion, and how often the walk's own two-sigma band is breached.

A flare where the walk band is miscalibrated would be worth having. A flare
where volatility is high is not - that is a volatility bin, and it is already
in production.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from level_signatures import CONTROL, DRAWS, GENERATED, LOOKBACK, SEED, TRADED, load, shuffle_blocks  # noqa: E402
from topology import REGIME, cloud_of, persistence, range_score  # noqa: E402

#: Cover intervals over the lens, and their overlap. The classic Mapper dials.
INTERVALS = int(os.environ.get("INTERVALS", "12"))
OVERLAP = float(os.environ.get("MAPPER_OVERLAP", "0.4"))
#: Windows a node needs before it may be proposed. A node of nine windows will
#: always look extreme on some outcome.
LEAST = int(os.environ.get("LEAST", "40"))
#: Cut for the within-interval clustering, as a quantile of the pairwise
#: distances inside that interval. At 0.25 single linkage chained everything
#: into one cluster per interval - three nodes from seven hundred windows, each
#: half the data and therefore extreme on nothing.
CUT = float(os.environ.get("CUT", "0.06"))
#: Clusters per cover interval.
PER_INTERVAL = int(os.environ.get("PER_INTERVAL", "3"))
STRIDE = int(os.environ.get("STRIDE", str(LOOKBACK)))

DESCRIPTOR = (
    "h0_total",
    "h0_max",
    "b1",
    "h1_total",
    "h1_max",
    "h1_land",
    "loop",
    "vol_ratio",
    "skew",
    "kurtosis",
    "autocorr",
    "efficiency",
    "volume_tie",
    "wick_bias",
    "spread_level",
    "up_share",
    "drawdown",
)
OUTCOMES = ("vol after", "size after", "drift after", "held", "tail ratio", "band miss")
#: The seven coordinates topology contributes, against the ten anyone could
#: have written down. A node defined over all seventeen beat both volatility
#: dials out of sample - which says a **descriptor** did it, not that
#: persistence did, until the same protocol is run on each half alone.
SHAPELY = ("h0_total", "h0_max", "b1", "h1_total", "h1_max", "h1_land", "loop")
PLAIN = tuple(n for n in DESCRIPTOR if n not in SHAPELY)
SUBSETS = (
    ("all 17", DESCRIPTOR),
    ("plain 10", PLAIN),
    ("topology 7", SHAPELY),
)


def window_row(bars, at: int) -> tuple[list[float], dict[str, float], float, float, float] | None:
    """One window's descriptor, its forward outcomes, its volatility and its hour.

    Everything is a ratio or a standardised quantity so that windows from gold
    and from EURGBP sit in the same space - and so that no coordinate is simply
    the price or the volatility, which would make every cluster a volatility
    cluster before Mapper saw it.
    """
    o, h, l_, c = bars["open"], bars["high"], bars["low"], bars["close"]
    v, s, when = bars["volume"], bars["spread"], bars["time"]
    if at < 2 * LOOKBACK + 4 or at + LOOKBACK + 1 >= len(c):
        return None
    prior = np.diff(np.log(c[at - 2 * LOOKBACK : at - LOOKBACK + 1]))
    rets = np.diff(np.log(c[at - LOOKBACK : at + 1]))
    ahead = np.diff(np.log(c[at : at + LOOKBACK + 1]))
    sd = float(rets.std())
    if not (sd > 0 and prior.std() > 0) or not np.isfinite(rets).all():
        return None
    cloud = cloud_of(bars, at)
    if cloud is None:
        return None
    got = persistence(cloud)
    if got is None:
        return None
    loop = range_score(bars, slice(at - LOOKBACK, at))
    if not math.isfinite(loop):
        return None
    window = slice(at - LOOKBACK, at)
    ranges = h[window] - l_[window]
    body_top = np.maximum(o[window], c[window])
    body_low = np.minimum(o[window], c[window])
    spread_mean = float(ranges.mean())
    if not (spread_mean > 0):
        return None
    # `rets[k]` is the move *into* bar `at - LOOKBACK + 1 + k`, so anything
    # correlated against it indexes that way and not by `window`, which starts
    # a bar earlier and is one short.
    standard = (rets - rets.mean()) / sd
    path = np.cumsum(rets)
    peak = np.maximum.accumulate(path)
    forward = np.cumsum(ahead)
    band = 2.0 * sd * np.sqrt(np.arange(1, len(forward) + 1))
    favourable = float(forward.max()) if len(forward) else 0.0
    adverse = float(-forward.min()) if len(forward) else 0.0
    # Volume is constant on some generated feeds, and a correlation against a
    # constant is nan - which `isfinite` then drops, silently taking the whole
    # feed with it.
    heat = v[at - LOOKBACK + 1 : at + 1]
    tie = float(np.corrcoef(np.abs(standard), heat)[0, 1]) if float(np.std(heat)) > 0 else 0.0
    descriptor = [
        got["h0_total"],
        got["h0_max"],
        got["b1"],
        got["h1_total"],
        got["h1_max"],
        got["h1_land"],
        loop,
        sd / float(prior.std()),
        float((standard**3).mean()),
        float((standard**4).mean()) - 3.0,
        float(np.corrcoef(standard[:-1], standard[1:])[0, 1]) if len(standard) > 3 else 0.0,
        abs(float(rets.sum())) / float(np.abs(rets).sum()),
        tie,
        float(((h[window] - body_top) - (body_low - l_[window])).mean()) / spread_mean,
        float(s[window].mean()) / spread_mean if spread_mean > 0 else 0.0,
        float((rets > 0).mean()),
        float((peak - path).max()) / (sd * math.sqrt(LOOKBACK)),
    ]
    top, bottom = float(h[window].max()), float(l_[window].min())
    # **The width of this window's own range**, over what a walk of the same
    # volatility would span. `topology.md` measured this predicting containment
    # at an AUC of 0.74 to 0.84 - a ruler, with no topology in it - and it is
    # neither the volatility level nor the volatility ratio, so conditioning on
    # those two passes it through untouched. Any node that claims `held` has to
    # be matched on it.
    width = (
        (math.log(top) - math.log(bottom)) / (sd * math.sqrt(LOOKBACK)) if top > bottom > 0 else 0.0
    )
    after = slice(at, at + LOOKBACK)
    outcomes = {
        "vol after": float(ahead.std()) / sd,
        "size after": abs(float(ahead.sum())) / (sd * math.sqrt(LOOKBACK)),
        "drift after": float(ahead.sum()) / (sd * math.sqrt(LOOKBACK)),
        "held": float(h[after].max() <= top + 1e-12 and l_[after].min() >= bottom - 1e-12),
        # Adverse against favourable excursion: the asymmetry a stop pays for.
        # Bounded in [-1, 1] rather than a raw ratio, which ran to +24 when the
        # favourable leg happened to be near zero and made a mean meaningless.
        "tail ratio": (adverse - favourable) / (adverse + favourable)
        if (adverse + favourable) > 1e-12
        else 0.0,
        # How often the walk's own two-sigma band is breached, which is the
        # calibration the band is trusted for.
        "band miss": float(np.mean(np.abs(forward) > band)),
    }
    if not all(math.isfinite(x) for x in descriptor) or not all(
        math.isfinite(x) for x in outcomes.values()
    ):
        return None
    hour = float((when[at] / 3600.0) % 24.0)
    return descriptor, outcomes, sd, hour, width


def eccentricity(points: np.ndarray) -> np.ndarray:
    """Mean distance from each point to all others - the classic flare lens.

    A point far from the bulk in any direction scores high whatever direction
    that is, which is what makes a flare visible without naming it first.
    """
    total = np.zeros(len(points))
    chunk = 512
    for start in range(0, len(points), chunk):
        block = points[start : start + chunk]
        gaps = np.linalg.norm(block[:, None, :] - points[None, :, :], axis=2)
        total[start : start + chunk] = gaps.mean(axis=1)
    return total


def mapper_nodes(points: np.ndarray, lens: np.ndarray) -> list[np.ndarray]:
    """Mapper: cover the lens, cluster inside each interval, keep the clusters."""
    try:
        from scipy.cluster.hierarchy import fcluster, linkage
        from scipy.spatial.distance import pdist
    except ImportError:
        return []
    low, high = float(lens.min()), float(lens.max())
    if not (high > low):
        return []
    width = (high - low) / INTERVALS
    reach = width * (1.0 + OVERLAP) / 2.0
    nodes: list[np.ndarray] = []
    for k in range(INTERVALS):
        middle = low + width * (k + 0.5)
        inside = np.flatnonzero(np.abs(lens - middle) <= reach)
        if len(inside) < 4:
            continue
        gaps = pdist(points[inside])
        if len(gaps) == 0 or not np.isfinite(gaps).all() or gaps.max() <= 0:
            continue
        # **Ward, not single linkage.** Single linkage chains: at a cut of the
        # 6% quantile it returned sixty-six nodes of which four held forty
        # windows - one blob and a tail of singletons - so the discovery step
        # had effectively one candidate. A fixed count per interval keeps every
        # node readable, and the overlapping cover is what makes it Mapper.
        tags = fcluster(linkage(gaps, method="ward"), t=PER_INTERVAL, criterion="maxclust")
        for tag in np.unique(tags):
            nodes.append(inside[tags == tag])
    return nodes


def spread_p(flag: np.ndarray, values: np.ndarray, rng, draws: int = DRAWS) -> tuple[float, float]:
    """Difference of means for a 0/1 membership flag, and its permutation p."""
    inside, outside = values[flag > 0.5], values[flag < 0.5]
    if len(inside) < 5 or len(outside) < 5:
        return float("nan"), float("nan")
    seen = float(inside.mean() - outside.mean())
    wider = 0
    for _ in range(draws):
        drawn = rng.permutation(flag)
        if abs(float(values[drawn > 0.5].mean() - values[drawn < 0.5].mean())) >= abs(seen):
            wider += 1
    return seen, (wider + 1) / (draws + 1)


def best_split(values: np.ndarray, by: np.ndarray, bins: int, seed: int) -> tuple[float, float]:
    """The strongest single bin of `by`, scored exactly as a node would be.

    A Mapper node is chosen to be extreme, so comparing it with the *average*
    volatility bin flatters it. The honest comparison is the **most extreme**
    bin of a dial nobody needed topology for, picked the same way.
    """
    edges = np.quantile(by, np.linspace(0, 1, bins + 1)[1:-1])
    cell = np.clip(np.searchsorted(edges, by), 0, bins - 1)
    best = (0.0, float("nan"))
    for tag in range(bins):
        flag = (cell == tag).astype(float)
        if flag.sum() < 5 or (1 - flag).sum() < 5:
            continue
        got, p = spread_p(flag, values, np.random.default_rng(seed + tag))
        if math.isfinite(got) and abs(got) > abs(best[0]):
            best = (got, p)
    return best


def stratified_gap(
    flag: np.ndarray, values: np.ndarray, by: np.ndarray, bins: int, rng, draws: int = DRAWS
) -> tuple[float, float]:
    """The membership effect **within** strata of `by`, and its permutation p.

    This is the diagnostic that closed the range arm in `topology.md`: an effect
    that survives matching at five strata and walks to zero at twenty was never
    the thing being matched out. Here `by` is volatility, because a Mapper node
    in a space that contains a volatility ratio, a kurtosis and a drawdown is a
    volatility bin unless this says otherwise. Labels are permuted **inside**
    each stratum, so the null keeps the matching too.
    """
    edges = np.quantile(by, np.linspace(0, 1, bins + 1)[1:-1])
    cell = np.clip(np.searchsorted(edges, by), 0, bins - 1)

    def weigh(labels: np.ndarray) -> float:
        total = 0.0
        weight = 0.0
        for tag in range(bins):
            pick = cell == tag
            inside, outside = values[pick & (labels > 0.5)], values[pick & (labels < 0.5)]
            if len(inside) < 5 or len(outside) < 5:
                continue
            total += (float(inside.mean()) - float(outside.mean())) * pick.sum()
            weight += pick.sum()
        return total / weight if weight else float("nan")

    seen = weigh(flag)
    if not math.isfinite(seen):
        return float("nan"), float("nan")
    wider = 0
    for _ in range(draws):
        drawn = flag.copy()
        for tag in range(bins):
            pick = np.flatnonzero(cell == tag)
            drawn[pick] = rng.permutation(drawn[pick])
        got = weigh(drawn)
        if math.isfinite(got) and abs(got) >= abs(seen):
            wider += 1
    return seen, (wider + 1) / (draws + 1)


def arm(group: str, names: tuple[str, ...], rng, mixed: bool = False) -> None:
    rows: list[tuple[int, list[float], dict[str, float], float, float, float, float, str]] = []
    for name in names:
        bars = load(name)
        if bars is None:
            continue
        if mixed:
            bars = shuffle_blocks(bars, rng)
        marks = list(range(2 * LOOKBACK + 8, len(bars["close"]) - LOOKBACK - 2, STRIDE))
        if not marks:
            continue
        half = marks[len(marks) // 2]
        for at in marks:
            got = window_row(bars, at)
            if got is None:
                continue
            descriptor, outcomes, sd, hour, width = got
            rows.append(
                (
                    0 if at < half else 1,
                    descriptor,
                    outcomes,
                    sd,
                    hour,
                    descriptor[DESCRIPTOR.index("vol_ratio")],
                    width,
                    name,
                )
            )
    if len(rows) < 8 * LEAST:
        print(f"  {group}: {len(rows)} windows, too few to ask\n")
        return
    raw = np.array([r[1] for r in rows])
    keep = np.isfinite(raw).all(axis=1)
    raw, rows = raw[keep], [r for r, ok in zip(rows, keep, strict=True) if ok]
    # One descriptor pass, three coordinate spaces. `ripser` is the expensive
    # part and it does not depend on which columns are kept.
    for label, names_in in SUBSETS:
        columns = [DESCRIPTOR.index(n) for n in names_in]
        print(f"  -- {label}")
        analyse(group, rows, raw[:, columns])


def analyse(group: str, rows, picked: np.ndarray) -> None:
    table = picked
    middle, scale = table.mean(axis=0), table.std(axis=0)
    scale[scale <= 0] = 1.0
    table = (table - middle) / scale
    split = np.array([r[0] for r in rows])
    early, late = np.flatnonzero(split == 0), np.flatnonzero(split == 1)
    if len(early) < 4 * LEAST or len(late) < 4 * LEAST:
        print(f"  {group}: split too thin\n")
        return

    nodes = mapper_nodes(table[early], eccentricity(table[early]))
    big = [n for n in nodes if len(n) >= LEAST]
    print(
        f"  {len(rows)} windows, {len(early)} to discover on and {len(late)} to confirm; "
        f"{len(nodes)} Mapper nodes, {len(big)} of {LEAST}+"
    )
    if not big:
        print()
        return
    proposals: list[tuple[float, str, np.ndarray]] = []
    for outcome in OUTCOMES:
        values = np.array([rows[i][2][outcome] for i in early])
        pooled = float(values.mean())
        sd = float(values.std()) or 1.0
        for node in big:
            gap = abs(float(values[node].mean() - pooled)) / sd
            proposals.append((gap, outcome, node))
    proposals.sort(key=lambda t: -t[0])
    print(
        f"    {'outcome':<12}{'node':>6}{'discovered':>12}{'held out':>11}{'p':>8}"
        f"{'best vol bin':>14}{'p':>8}{'best hour bin':>15}{'p':>8}"
        f"{'best ratio bin':>15}{'p':>8}{'best width bin':>15}{'p':>8}"
    )
    seen: set[str] = set()
    for gap, outcome, node in proposals:
        if outcome in seen:
            continue
        seen.add(outcome)
        centre = table[early][node].mean(axis=0)
        others = np.array(
            [table[early][n].mean(axis=0) for n in big if not np.array_equal(n, node)]
        )
        here = table[late]
        mine = np.linalg.norm(here - centre, axis=1)
        theirs = (
            np.linalg.norm(here[:, None, :] - others[None, :, :], axis=2).min(axis=1)
            if len(others)
            else np.full(len(here), np.inf)
        )
        flag = (mine <= theirs).astype(float)
        values = np.array([rows[i][2][outcome] for i in late])
        vol = np.array([rows[i][3] for i in late])
        hour = np.array([rows[i][4] for i in late])
        # **The ratio, not only the level.** Stratifying on the volatility
        # *level* left the node's effect flat across 5, 10 and 20 strata, which
        # looked like a finding - and the block-shuffled arm reproduced it more
        # strongly. The descriptor carries `vol_ratio`, this window's volatility
        # over the previous window's, so a node can be reading volatility *mean
        # reversion*, which conditioning on the level does not touch and a block
        # shuffle preserves. It is in every GARCH and is not a discovery.
        # `vol_ratio` is a column of the descriptor, so its position moves with
        # the subset - and in the topology-only space it is not there at all,
        # which is exactly when this dial matters most. Taken from the raw
        # window instead, standardised, so every subset is scored against the
        # same dial.
        ratio = np.array([rows[i][5] for i in late])
        width = np.array([rows[i][6] for i in late])
        got, p = spread_p(flag, values, np.random.default_rng(SEED + 61))
        vol_gap, vol_p = best_split(values, vol, 6, SEED + 71)
        hour_gap, hour_p = best_split(values, hour, 6, SEED + 81)
        ratio_gap, ratio_p = best_split(values, ratio, 6, SEED + 101)
        width_gap, width_p = best_split(values, width, 6, SEED + 111)
        print(
            f"    {outcome:<12}{int(flag.sum()):>6}{gap:>12.3f}{got:>+11.4f}{p:>8.3f}"
            f"{vol_gap:>+14.4f}{vol_p:>8.3f}{hour_gap:>+15.4f}{hour_p:>8.3f}"
            f"{ratio_gap:>+15.4f}{ratio_p:>8.3f}{width_gap:>+15.4f}{width_p:>8.3f}"
        )
        if math.isfinite(p) and p < 0.05:
            for label, dial in (
                ("volatility", vol),
                ("vol ratio ", ratio),
                ("range width", width),
            ):
                inner = []
                for bins in (5, 10, 20):
                    within, within_p = stratified_gap(
                        flag, values, dial, bins, np.random.default_rng(SEED + 91)
                    )
                    if math.isfinite(within):
                        inner.append(f"{bins:>2}: {within:+.4f} p {within_p:.3f}")
                print(f"      within {label} strata  " + " | ".join(inner))
            # **Per feed, because a pooled answer here has form.** This desk has
            # had a pooled median agree with a claim that every subgroup
            # refuted, and this node is pooled over twelve instruments.
            feeds = sorted({rows[i][7] for i in late})
            if len(feeds) > 1:
                parts = []
                for feed in feeds:
                    pick = np.array([rows[i][7] == feed for i in late])
                    if pick.sum() < 60:
                        continue
                    one, one_p = spread_p(
                        flag[pick], values[pick], np.random.default_rng(SEED + 121)
                    )
                    if math.isfinite(one):
                        parts.append(f"{feed} {one:+.3f} ({one_p:.3f})")
                print("      by feed  " + "; ".join(parts))
    print(
        "      `discovered` is in standard deviations on the earlier half and is\n"
        "      not a claim. `held out` is the same node, carried over as a\n"
        "      centroid, on windows it was not built from. The last four columns\n"
        "      are the most extreme bin of volatility and of hour of day, chosen\n"
        "      the same way - a node has to beat a dial nobody needed topology\n"
        "      for.\n"
    )


def main() -> None:
    rng = np.random.default_rng(SEED)
    print(
        f"{LOOKBACK}-bar windows, stride {STRIDE}, {len(DESCRIPTOR)} coordinates\n"
        f"lens: eccentricity, {INTERVALS} intervals at {OVERLAP:.0%} overlap, "
        f"single linkage cut at the {CUT:.0%} quantile\n{DRAWS} permutations\n"
    )
    for group, names in (
        ("traded", TRADED),
        ("traded, block-shuffled", TRADED),
        ("control", CONTROL),
        ("regime", REGIME),
        ("generated", GENERATED),
    ):
        print("=" * 100)
        print(group)
        print("=" * 100)
        arm(group, names, rng, mixed=group.endswith("block-shuffled"))


if __name__ == "__main__":
    main()
