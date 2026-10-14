"""Can persistent homology nominate a level, and does a touch leave a topological trace?

Two questions, asked together on 2026-10-14: *we are also looking for tiny
signals in TDA and also can TDA be used to extract levels too.*

`level-signatures.md` left exactly one door open. Nineteen observables at a
touch carry about 0.02 standard deviations **where the level is built into the
generator** and nothing at all on traded instruments - so the panel is sensitive
rather than blind, and what is unsettled is the **level definition**, not the
measurement. This goes at the definition.

## Levels as topological prominence

A price level, stated carefully, is a mode of the measure that says how much
trading happened where. A volume profile says this already and its answer
depends on the bin width, which is the thing persistent homology exists to
remove: the **prominence** of a mode - how far the density has to fall before
that mode merges into a taller one - is its persistence under the superlevel
filtration, and persistence is stable under perturbation of the density. So the
bandwidth stops being a parameter that decides which levels exist and becomes
one that decides how fine a mode can be.

`prominence_levels` builds the price-visitation density (each bar spreading its
volume across its own range), smooths it, and returns the modes ranked by
prominence. The sweep is the standard elder-rule union-find over a 1-D
function - exact, no library, and portable into `statespace` if it earns it.

## Ranges as one-dimensional homology

A range-bound stretch, embedded as `(price_t, price_{t+k})`, traces a **loop**:
out to one boundary, back to the other, round again. A trending stretch does
not. So the longest-lived `H1` class of the delay embedding is a range score,
and its birth scale is the range width - which is a claim with an unambiguous
positive control, because Deriv publishes processes whose generator **has** a
range that breaks.

## Tiny signals

Six persistence features of the pre-touch path, on the delay embedding of
**standardised** returns so that none of them is a volatility proxy in
disguise: total and maximum `H0` persistence, which is the minimum spanning tree
of the embedded cloud; `H1` count, total and maximum; and the `L1` norm of the
first persistence landscape, which is the Gidea-Katz crash indicator.

## The gate

Every arm runs on `Range_Break_100_Index` and `Range_Break_200_Index` as well as
on traded instruments. An extractor that cannot find the boundary of a process
built to have one does not get read on FX - the same rule that says an FX screen
missing currency triangles is broken whatever else it reports.
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

from level_signatures import (  # noqa: E402
    AFTER,
    CONTROL,
    DRAWS,
    FRAME,
    GENERATED,
    HORIZON,
    JITTER,
    LOOKBACK,
    PER_FEED,
    SEED,
    TRADED,
    WARM,
    auc,
    load,
    shuffle_blocks,
)
from till_infinity.structures.statespace.dispersion import differ  # noqa: E402

#: Grid the density is evaluated on. Prominence is stable in this; the levels it
#: finds are not supposed to move when it changes, and `GRID=1024` is the check.
GRID = int(os.environ.get("GRID", "512"))
#: Smoothing, as a fraction of the window's price span. Also meant not to decide
#: which levels exist - only how fine a mode may be.
BANDWIDTH = float(os.environ.get("BANDWIDTH", "0.02"))
#: Levels taken per window, most prominent first.
KEEP = int(os.environ.get("KEEP", "3"))
#: Delay for the embeddings.
DELAY = int(os.environ.get("DELAY", "1"))
#: Points in the pre-touch cloud, and the embedding dimension.
CLOUD = int(os.environ.get("CLOUD", "60"))
DIM = int(os.environ.get("DIM", "3"))
PATIENCE = int(os.environ.get("PATIENCE", "24"))
#: Deriv's drift-switch processes, whose generator plants a drift that
#: changes. The positive control for the shape arm: a taxonomy of path
#: shapes that cannot separate a planted regime change is not reporting on
#: the market when it finds nothing on FX. They are also a negative control
#: for the other two arms - a drift process has no levels and no range.
REGIME = tuple(
    os.environ.get(
        "REGIME", "Drift_Switch_Index_10,Drift_Switch_Index_20,Drift_Switch_Index_30"
    ).split(",")
)

TDA = ("h0_total", "h0_max", "b1", "h1_total", "h1_max", "h1_land")


def superlevel_pairs(y: np.ndarray) -> list[tuple[int, float]]:
    """Modes of `y` and their prominences, by the elder rule.

    Sweeping down from the highest value, each grid point either starts a
    component (a local maximum), extends one, or merges two - and on a merge the
    **younger** component dies with persistence `its birth - this height`. That
    persistence is the prominence: how far the density falls before this mode
    stops being its own mode. The oldest component never dies and is given the
    full height of the function, so the dominant mode is always returned.
    """
    n = len(y)
    parent = np.full(n, -1, dtype=int)
    birth = np.zeros(n)
    out: list[tuple[int, float]] = []

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    order = np.argsort(-y, kind="stable")
    for i in order:
        i = int(i)
        touching = [j for j in (i - 1, i + 1) if 0 <= j < n and parent[j] != -1]
        if not touching:
            parent[i] = i
            birth[i] = y[i]
            continue
        roots = {find(j) for j in touching}
        elder = max(roots, key=lambda r: birth[r])
        parent[i] = elder
        for r in roots:
            if r != elder:
                out.append((r, float(birth[r] - y[i])))
                parent[r] = elder
    top = find(int(order[0]))
    out.append((top, float(birth[top] - y.min())))
    return out


def prominence_levels(bars, window: slice, keep: int = KEEP) -> list[tuple[float, float]]:
    """Prices that are modes of the visitation density, most prominent first.

    Each bar spreads its volume uniformly across its own range, which is the
    same measure `ranging.Profile` accumulates, and the result is smoothed by a
    Gaussian of `BANDWIDTH` of the span. What differs is the selection: not the
    tallest bins, but the modes that survive the deepest valley.
    """
    highs, lows, vols = bars["high"][window], bars["low"][window], bars["volume"][window]
    lo, hi = float(lows.min()), float(highs.max())
    if not (hi > lo):
        return []
    grid = np.linspace(lo, hi, GRID)
    step = (hi - lo) / (GRID - 1)
    density = np.zeros(GRID)
    start = np.clip(((lows - lo) / step).astype(int), 0, GRID - 1)
    stop = np.clip(((highs - lo) / step).astype(int), 0, GRID - 1)
    for a, b, v in zip(start, stop, vols, strict=True):
        density[a : b + 1] += v / max(b - a + 1, 1)
    width = max(BANDWIDTH * (hi - lo) / step, 1.0)
    half = int(math.ceil(3 * width))
    kernel = np.exp(-0.5 * (np.arange(-half, half + 1) / width) ** 2)
    density = np.convolve(density, kernel / kernel.sum(), mode="same")
    if not np.isfinite(density).all() or density.max() <= 0:
        return []
    density /= density.max()
    found = sorted(superlevel_pairs(density), key=lambda pair: -pair[1])
    return [(float(grid[i]), p) for i, p in found[:keep] if p > 0]


def cloud_of(bars, end: int, points: int = CLOUD) -> np.ndarray | None:
    """Delay embedding of **standardised** returns ending just before `end`.

    Standardised inside the window, because an unnormalised persistence diagram
    scales with volatility and would make every one of these a volatility proxy
    - and this desk has already learnt that vol and tails are where all the
    large effects are, so a feature that is secretly vol will look wonderful.
    """
    closes = bars["close"]
    first = end - points - DIM * DELAY
    if first < 1:
        return None
    rets = np.diff(np.log(closes[first - 1 : end]))
    sd = float(rets.std())
    if not (sd > 0) or not np.isfinite(rets).all():
        return None
    rets = rets / sd
    rows = len(rets) - (DIM - 1) * DELAY
    if rows < 8:
        return None
    return np.stack([rets[k * DELAY : k * DELAY + rows] for k in range(DIM)], axis=1)


def persistence(cloud: np.ndarray) -> dict[str, float] | None:
    """`H0` and `H1` of the Rips filtration, as six numbers."""
    try:
        from ripser import ripser
    except ImportError:
        return None
    out = ripser(cloud, maxdim=1)["dgms"]
    h0 = out[0][:, 1]
    h0 = h0[np.isfinite(h0)]
    h1 = out[1]
    lives = (h1[:, 1] - h1[:, 0]) if len(h1) else np.array([])
    lives = lives[np.isfinite(lives)]
    # The first persistence landscape's L1 norm is the area under the tent
    # functions, which for a diagram of disjoint tents is sum of (life/2)^2.
    land = float(np.sum((lives / 2.0) ** 2)) if len(lives) else 0.0
    return {
        "h0_total": float(h0.sum()),
        "h0_max": float(h0.max()) if len(h0) else 0.0,
        "b1": float(len(lives)),
        "h1_total": float(lives.sum()) if len(lives) else 0.0,
        "h1_max": float(lives.max()) if len(lives) else 0.0,
        "h1_land": land,
    }


def range_score(bars, window: slice) -> float:
    """Longest-lived `H1` class of the price delay embedding, over price sd.

    A range traces a loop: out to one boundary, back to the other, round again.
    A trend does not close.
    """
    closes = bars["close"][window]
    if len(closes) < 3 * DELAY + 8:
        return float("nan")
    level = np.log(closes)
    sd = float(level.std())
    if not (sd > 0):
        return float("nan")
    level = (level - level.mean()) / sd
    rows = len(level) - DELAY
    cloud = np.stack([level[:rows], level[DELAY : DELAY + rows]], axis=1)
    got = persistence(cloud)
    return float("nan") if got is None else got["h1_max"]


def races(bars, price: float, start: int, move: float) -> list[bool]:
    """Resolved interactions with `price`: `True` came back, `False` went through."""
    highs, lows, closes = bars["high"], bars["low"], bars["close"]
    out: list[bool] = []
    end = min(start + HORIZON, len(closes))
    i = max(start, 1)
    while i < end:
        if not (lows[i] <= price <= highs[i]):
            i += 1
            continue
        from_below = closes[i - 1] < price
        back = price - move if from_below else price + move
        through = price + move if from_below else price - move
        settled = None
        j = i + 1
        while j < min(i + 1 + PATIENCE, end):
            if (highs[j] >= through) if from_below else (lows[j] <= through):
                settled = False
                break
            if (lows[j] <= back) if from_below else (highs[j] >= back):
                settled = True
                break
            j += 1
        if settled is not None:
            out.append(settled)
        i = j + 1
    return out


def flip_null(real: np.ndarray, fake: np.ndarray, rng, draws: int = DRAWS) -> tuple[float, float]:
    """Matched-pair difference of means, and the p its own label flips give."""
    seen = float(np.mean(real) - np.mean(fake))
    wider = 0
    for _ in range(draws):
        flip = rng.random(len(real)) < 0.5
        left = np.where(flip, fake, real)
        right = np.where(flip, real, fake)
        if abs(float(np.mean(left) - np.mean(right))) >= abs(seen):
            wider += 1
    return seen, (wider + 1) / (draws + 1)


def extractor_arm(group: str, names: tuple[str, ...], rng) -> None:
    """Do prices nominated by prominence hold better than matched placebos?"""
    rows: list[tuple[float, float, float, float, str]] = []
    counts_real: list[tuple[float, float]] = []
    counts_fake: list[tuple[float, float]] = []
    shuffled: list[tuple[float, float]] = []
    for name in names:
        bars = load(name)
        if bars is None:
            continue
        mixed = shuffle_blocks(bars, rng)
        closes, highs, lows = bars["close"], bars["high"], bars["low"]
        last = len(closes) - HORIZON - AFTER - 2
        span = last - LOOKBACK
        if span <= 0:
            continue
        step = max(HORIZON, span // max(PER_FEED, 1))
        for at in range(LOOKBACK, last, step):
            window = slice(at - LOOKBACK, at)
            move = float(np.median(highs[window] - lows[window]))
            if not (move > 0):
                continue
            here = float(closes[at])
            for price, strength in prominence_levels(bars, window):
                gap = price - here
                if abs(gap) < 0.25 * move:
                    continue
                placebo = here + gap * (1.0 + float(rng.uniform(-JITTER, JITTER)))
                real, fake = races(bars, price, at, move), races(bars, placebo, at, move)
                if len(real) < 3 or len(fake) < 3:
                    continue
                rows.append(
                    (
                        strength,
                        sum(real) / len(real),
                        sum(fake) / len(fake),
                        float(len(real)),
                        name,
                    )
                )
                counts_real.append((float(len(real)), float(sum(real))))
                counts_fake.append((float(len(fake)), float(sum(fake))))
            for price, _ in prominence_levels(mixed, window):
                gap = price - float(mixed["close"][at])
                if abs(gap) < 0.25 * move:
                    continue
                got = races(mixed, price, at, move)
                if len(got) >= 3:
                    shuffled.append((float(len(got)), float(sum(got))))
    if len(rows) < 20:
        print(f"  {group}: {len(rows)} nominations, too few to ask\n")
        return
    strengths = np.array([r[0] for r in rows])
    real_rate = np.array([r[1] for r in rows])
    fake_rate = np.array([r[2] for r in rows])
    diff, p = flip_null(real_rate, fake_rate, np.random.default_rng(SEED + 31))
    pooled_real = sum(h for _, h in counts_real) / sum(n for n, _ in counts_real)
    pooled_fake = sum(h for _, h in counts_fake) / sum(n for n, _ in counts_fake)
    print(f"  {len(rows)} nominations over {len({r[4] for r in rows})} feeds")
    print(f"    hold at a prominent mode : {pooled_real:.4f}")
    print(f"    hold at a matched price  : {pooled_fake:.4f}")
    print(f"    paired difference        : {diff:+.4f}  p {p:.3f}")
    if shuffled:
        mixed_rate = sum(h for _, h in shuffled) / sum(n for n, _ in shuffled)
        print(f"    same modes, shuffled bars: {mixed_rate:.4f}  ({len(shuffled)} prices)")
    tau, null, tau_p = differ(counts_real, pooled_real)
    tau_f, null_f, tau_fp = differ(counts_fake, pooled_fake)
    print(f"    do modes differ          : tau {tau:.4f} vs null {null:.4f}, p {tau_p:.3f}")
    print(f"    do the placebos differ   : tau {tau_f:.4f} vs null {null_f:.4f}, p {tau_fp:.3f}")
    print(
        "      The second line is the one that decides the first. Dispersion\n"
        "      across nominated modes means something only if matched prices on\n"
        "      the same process do not show it too."
    )
    strong = strengths >= np.median(strengths)
    if strong.sum() >= 10 and (~strong).sum() >= 10:
        hi, hi_p = flip_null(real_rate[strong], fake_rate[strong], np.random.default_rng(SEED + 32))
        lo, lo_p = flip_null(
            real_rate[~strong], fake_rate[~strong], np.random.default_rng(SEED + 33)
        )
        print(f"    prominent half           : {hi:+.4f}  p {hi_p:.3f}")
        print(f"    less prominent half      : {lo:+.4f}  p {lo_p:.3f}")
        print(
            "      Prominence is the whole claim: if the deep modes do not beat\n"
            "      the shallow ones, persistence added nothing to a histogram."
        )
    print()


def stratified_auc(score: np.ndarray, truth: np.ndarray, by: np.ndarray, bins: int = 5) -> float:
    """AUC of `score` within strata of `by`, pooled by stratum size.

    The unstratified version of this arm read 0.33 to 0.42 on every group
    including driftless volatility indices, which is the tell for a mechanical
    relationship: "price stayed inside the window's range" is largely a
    statement about **how wide that range was**, and a range-bound window has a
    narrow one. Matching on width is what turns it back into a question about
    topology.
    """
    edges = np.quantile(by, np.linspace(0, 1, bins + 1)[1:-1])
    cell = np.clip(np.searchsorted(edges, by), 0, bins - 1)
    total = 0.0
    weight = 0.0
    for tag in range(bins):
        pick = cell == tag
        yes, no = score[pick & (truth > 0.5)], score[pick & (truth < 0.5)]
        if len(yes) < 3 or len(no) < 3:
            continue
        got = auc(yes, no)
        if math.isfinite(got):
            total += got * pick.sum()
            weight += pick.sum()
    return total / weight if weight else float("nan")


def range_arm(group: str, names: tuple[str, ...], rng) -> None:
    """Does a loop in the embedding say the range will hold - beyond its width?

    The baseline is deliberately crude: the window's range over what a walk of
    the same volatility would span. That is range-boundedness with no topology
    in it at all, and `H1` has to beat it or add to it within strata of it.
    """
    loops: list[float] = []
    widths: list[float] = []
    kept: list[float] = []
    for name in names:
        bars = load(name)
        if bars is None:
            continue
        closes, highs, lows = bars["close"], bars["high"], bars["low"]
        last = len(closes) - HORIZON - AFTER - 2
        span = last - LOOKBACK
        if span <= 0:
            continue
        step = max(HORIZON, span // max(PER_FEED, 1))
        for at in range(LOOKBACK, last, step):
            window = slice(at - LOOKBACK, at)
            score = range_score(bars, window)
            if not math.isfinite(score):
                continue
            rets = np.diff(np.log(closes[window]))
            sd = float(rets.std())
            top, bottom = float(highs[window].max()), float(lows[window].min())
            if not (sd > 0 and top > bottom):
                continue
            ahead = slice(at, at + LOOKBACK)
            here = math.log(top) - math.log(bottom)
            later = math.log(float(highs[ahead].max())) - math.log(float(lows[ahead].min()))
            loops.append(score)
            widths.append(here / (sd * math.sqrt(LOOKBACK)))
            # The range held or narrowed, scale-free and independent of how wide
            # this window's own range happened to be.
            kept.append(float(later <= here))
    if len(kept) < 60:
        print(f"  {group}: {len(kept)} windows, too few to ask\n")
        return
    score = np.array(loops)
    width = np.array(widths)
    truth = np.array(kept)
    if truth.sum() < 10 or (1 - truth).sum() < 10:
        print(f"  {group}: {truth.mean():.1%} held, too one-sided to ask\n")
        return
    raw = auc(score[truth > 0.5], score[truth < 0.5])
    plain = auc(width[truth > 0.5], width[truth < 0.5])
    print(f"  {len(kept)} windows, {truth.mean():.1%} held or narrowed")
    print(f"    H1 score, unmatched          : {raw:.4f}")
    print(f"    window width, no topology    : {plain:.4f}")
    # **Sweep the matching, because five strata do not match much.** `H1`
    # correlates hard with width - unmatched it reads 0.33 against width's 0.74 -
    # so a residue of width survives inside a wide stratum and reappears as a
    # topological finding. If the effect is width it walks to 0.5 as the strata
    # narrow; if it is topology it does not move.
    for bins in (5, 10, 20, 40):
        inside = stratified_auc(score, truth, width, bins=bins)
        if not math.isfinite(inside):
            continue
        wider = 0
        rng_local = np.random.default_rng(SEED + 41)
        for _ in range(DRAWS):
            drawn = rng_local.permutation(truth)
            if abs(stratified_auc(score, drawn, width, bins=bins) - 0.5) >= abs(inside - 0.5):
                wider += 1
        print(
            f"    H1 within {bins:>2} width strata    : {inside:.4f}  "
            f"p {(wider + 1) / (DRAWS + 1):.3f}"
        )
    print(
        "      The second line is what a ruler already knows. Topology earns a\n"
        "      place only if the strata lines hold up as they narrow.\n"
    )


#: Shapes fitted. Six is enough to be read in a table and few enough that each
#: holds a few hundred windows.
SHAPES = int(os.environ.get("SHAPES", "6"))
BEFORE_AFTER = ("vol before", "move before", "vol after", "size after", "drift after", "held")


def window_shape(bars, at: int) -> tuple[list[float], dict[str, float]] | None:
    """One window's topological descriptor, and what happened either side of it.

    Everything is standardised **inside** the window so a shape cannot simply be
    "this was a volatile stretch" - the before and after columns are ratios and
    standardised moves for the same reason.
    """
    closes, highs, lows = bars["close"], bars["high"], bars["low"]
    if at < 2 * LOOKBACK + CLOUD + DIM * DELAY + 2 or at + LOOKBACK + 1 >= len(closes):
        return None
    rets = np.diff(np.log(closes[at - 2 * LOOKBACK : at + LOOKBACK]))
    prior, now, ahead = rets[:LOOKBACK], rets[LOOKBACK : 2 * LOOKBACK], rets[2 * LOOKBACK :]
    sd = float(now.std())
    if not (sd > 0 and prior.std() > 0) or not np.isfinite(rets).all():
        return None
    cloud = cloud_of(bars, at, CLOUD)
    if cloud is None:
        return None
    got = persistence(cloud)
    if got is None:
        return None
    loop = range_score(bars, slice(at - LOOKBACK, at))
    if not math.isfinite(loop):
        return None
    top = float(highs[at - LOOKBACK : at].max())
    bottom = float(lows[at - LOOKBACK : at].min())
    after = slice(at, at + LOOKBACK)
    return (
        [got[k] for k in TDA] + [loop],
        {
            "vol before": float(prior.std()) / sd,
            "move before": float(now.sum()) / (sd * math.sqrt(LOOKBACK)),
            "vol after": float(ahead.std()) / sd,
            "size after": float(np.abs(ahead.sum())) / (sd * math.sqrt(LOOKBACK)),
            "drift after": float(ahead.sum()) / (sd * math.sqrt(LOOKBACK)),
            "held": float(
                highs[after].max() <= top + 1e-12 and lows[after].min() >= bottom - 1e-12
            ),
        },
    )


def eta_squared(labels: np.ndarray, values: np.ndarray) -> float:
    """Share of the variance that sits between groups rather than inside them."""
    total = float(((values - values.mean()) ** 2).sum())
    if not (total > 0):
        return 0.0
    between = 0.0
    for tag in np.unique(labels):
        sub = values[labels == tag]
        between += len(sub) * (float(sub.mean()) - float(values.mean())) ** 2
    return between / total


def spread_p(
    labels: np.ndarray, values: np.ndarray, rng, draws: int = DRAWS
) -> tuple[float, float]:
    """`eta^2` and the p its own label permutation gives."""
    seen = eta_squared(labels, values)
    wider = sum(1 for _ in range(draws) if eta_squared(rng.permutation(labels), values) >= seen)
    return seen, (wider + 1) / (draws + 1)


def shapes_arm(group: str, names: tuple[str, ...], rng) -> None:
    """Recurring shapes of the path, and what sits either side of each.

    The shapes are fitted on the **first half** of each feed and read on the
    second, because a taxonomy fitted on the data it is scored against finds
    structure in a walk. The comparison that matters is the last line: six bins
    of plain realised volatility, scored identically. A shape that explains no
    more than those is a volatility proxy wearing a persistence diagram.
    """
    try:
        from sklearn.cluster import KMeans
    except ImportError:
        print("  sklearn missing; the shape arm cannot run\n")
        return
    rows: list[tuple[int, list[float], dict[str, float], float]] = []
    for name in names:
        bars = load(name)
        if bars is None:
            continue
        closes = bars["close"]
        stride = LOOKBACK
        first = 2 * LOOKBACK + CLOUD + DIM * DELAY + 4
        marks = list(range(first, len(closes) - LOOKBACK - 2, stride))
        half = marks[len(marks) // 2] if marks else 0
        for at in marks:
            got = window_shape(bars, at)
            if got is None:
                continue
            desc, outcome = got
            rets = np.diff(np.log(closes[at - LOOKBACK : at + 1]))
            rows.append((0 if at < half else 1, desc, outcome, float(rets.std())))
    if len(rows) < 8 * SHAPES:
        print(f"  {group}: {len(rows)} windows, too few to ask\n")
        return
    table = np.array([r[1] for r in rows], dtype=float)
    keep = np.isfinite(table).all(axis=1)
    table, rows = table[keep], [r for r, ok in zip(rows, keep, strict=True) if ok]
    middle, scale = table.mean(axis=0), table.std(axis=0)
    scale[scale <= 0] = 1.0
    table = (table - middle) / scale
    split = np.array([r[0] for r in rows])
    if (split == 0).sum() < 2 * SHAPES or (split == 1).sum() < 2 * SHAPES:
        print(f"  {group}: split too thin\n")
        return
    fitted = KMeans(n_clusters=SHAPES, n_init=10, random_state=SEED).fit(table[split == 0])
    labels = fitted.predict(table[split == 1])
    held = [r for r, s in zip(rows, split, strict=True) if s == 1]
    print(f"  {len(held)} held-out windows, {SHAPES} shapes fitted on the earlier half")
    print(f"    {'shape':<7}{'n':>6}" + "".join(f"{c:>13}" for c in BEFORE_AFTER))
    for tag in range(SHAPES):
        pick = labels == tag
        if pick.sum() == 0:
            continue
        line = "".join(
            f"{np.mean([held[i][2][c] for i in np.flatnonzero(pick)]):>13.3f}" for c in BEFORE_AFTER
        )
        print(f"    {tag:<7}{int(pick.sum()):>6}" + line)
    vol = np.array([r[3] for r in held])
    bins = np.clip(
        np.searchsorted(np.quantile(vol, np.linspace(0, 1, SHAPES + 1)[1:-1]), vol), 0, SHAPES - 1
    )
    print(f"\n    {'outcome':<13}{'eta2 shape':>12}{'p':>8}{'eta2 vol bins':>16}{'p':>8}")
    for col in BEFORE_AFTER:
        values = np.array([h[2][col] for h in held])
        shape_e, shape_p = spread_p(labels, values, np.random.default_rng(SEED + 51))
        vol_e, vol_p = spread_p(bins, values, np.random.default_rng(SEED + 52))
        print(f"    {col:<13}{shape_e:>12.4f}{shape_p:>8.3f}{vol_e:>16.4f}{vol_p:>8.3f}")
    print(
        "      A shape beats a volatility bin only where its eta2 is larger.\n"
        "      Anywhere else the topology is restating the volatility.\n"
    )


def main() -> None:
    rng = np.random.default_rng(SEED)
    if persistence(np.random.default_rng(0).normal(size=(20, 2))) is None:
        print("ripser is not installed; the H1 arms cannot run")
    print(
        f"frame {FRAME}  {LOOKBACK}-bar windows, grid {GRID}, bandwidth {BANDWIDTH}, "
        f"{KEEP} modes a window\nembedding dim {DIM} delay {DELAY}, "
        f"{CLOUD}-point clouds, {DRAWS} draws\n"
    )
    groups = (
        ("control", CONTROL),
        ("regime", REGIME),
        ("traded", TRADED),
        ("generated", GENERATED),
    )
    for title, arm in (
        ("LEVELS FROM TOPOLOGICAL PROMINENCE", extractor_arm),
        ("RANGES FROM ONE-DIMENSIONAL HOMOLOGY", range_arm),
        ("SHAPES OVER TIME, AND EITHER SIDE OF EACH", shapes_arm),
    ):
        print("=" * 86)
        print(title)
        print("=" * 86)
        for group, names in groups:
            print(f"-- {group}")
            arm(group, names, rng)
    print(
        "The control is the gate. A mode that cannot find the boundary of a\n"
        "process built to have one does not get read on FX, however it reads.\n"
        f"{WARM} bars of warmup are required of every observable."
    )


if __name__ == "__main__":
    main()
