"""The three estimators for the bounce study, as count tensors with a block bootstrap.

Binned once to a `(block, bucket, stratum)` count tensor, so a bootstrap draw
is `cnt[pick].sum(axis=0)` rather than a mask over rows. `level_shield_agg`
records why: the mask version did not finish one series in seven minutes, and
it was also *wrong* - a block drawn twice cannot be represented by a presence
mask, which understated every standard error.

The estimators, weakest control to strongest:

* **`hold`** - the hold rate itself, against the same number on the placebo
  and the surrogate arms. This answers part 1 and leans entirely on the
  matched arm: `a-return-rate-is-geometry` is why a bare 0.58 means nothing.
* **`grade_gap`** - the hold rate of high-grade touches minus low-grade ones,
  **within compression quintile crossed with level-age bin**. This answers
  part 2. The split is at each cell's own median grade, which is a rank, so
  the bucket sizes are balanced by construction and a skewed grade
  distribution cannot do the work.
* **`grade_auc`** - the same claim as a rank statistic over the continuous
  grade, which does not need a threshold and so cannot be tuned by one.

Every one of them is computed identically on every arm. A number here is only
ever read against the same number on the hardest arm.
"""

from __future__ import annotations

import statistics as st
from dataclasses import dataclass

import numpy as np

from research.ideas.level_bounce import AGE_EDGES, BINS, Rows

#: Bootstrap draws per cell. 400, which puts the Monte Carlo error on a
#: standard error at a few percent of it - enough to compare a real arm with a
#: null arm and not enough to quote a p-value to three places.
DRAWS = 400

#: A bucket contributing fewer than this many episodes in a stratum is
#: dropped from that stratum rather than contributing a rate computed from
#: three rows. Pooled first and guarded second: `pool-events-before-a-per-feed-
#: guard` is a min-events guard that dropped 141 of 146 feeds and turned
#: 0.9 sigma into an apparent 4.8.
FLOOR = 10

#: Below this many scored episodes a cell reports nothing. The skill's own
#: line: under about 100 the prior is noise, and saying so is cheaper than a
#: table of cells that each rest on nine touches.
LEAST = 100


def age_bin(n_prev: np.ndarray) -> np.ndarray:
    """Which level-age bin each episode falls in, from `AGE_EDGES`."""
    return np.searchsorted(np.asarray(AGE_EDGES), n_prev, side="right").astype(np.int64)


def _tensor(block: np.ndarray, bucket: np.ndarray, stratum: np.ndarray, hit: np.ndarray, buckets: int):
    """`(hits, totals, blocks)` binned to `(block, bucket, stratum)`."""
    keys, index = np.unique(block, return_inverse=True)
    shape = (len(keys), buckets, int(stratum.max()) + 1 if len(stratum) else 1)
    size = int(np.prod(shape))
    flat = (index * shape[1] + bucket) * shape[2] + stratum
    totals = np.bincount(flat, minlength=size).reshape(shape)
    hits = np.bincount(flat, weights=hit.astype(float), minlength=size).reshape(shape)
    return hits, totals, keys


def _within(hits: np.ndarray, totals: np.ndarray, floor: int = FLOOR):
    """Per-bucket rate, averaged over strata and weighted by each stratum's n."""
    usable = totals >= floor
    rate = np.divide(hits, totals, out=np.zeros_like(hits), where=totals > 0)
    weight = np.where(usable, totals, 0.0)
    mass = weight.sum(axis=1)
    out = np.divide(
        (rate * weight).sum(axis=1), mass, out=np.full(len(mass), np.nan), where=mass > 0
    )
    return out, mass


@dataclass(frozen=True, slots=True)
class Stat:
    """One estimate with the spread of its own block-bootstrap draws."""

    n: int
    value: float
    sd: float
    #: The two bucket rates behind a gap, or `(value, nan)` for a bare rate.
    lo: float
    hi: float

    @property
    def z(self) -> float:
        return self.value / self.sd if self.sd > 0 else 0.0


def hold_for(rows: Rows, mask: np.ndarray, *, draws: int = DRAWS, seed: int = 0) -> Stat | None:
    """The hold rate, stratified, with a block-bootstrap standard error.

    **0.50 is the walk's answer by construction** - the race is one unit each
    way - so this is read against 0.50 and against the same statistic on the
    placebo and surrogate arms, never on its own.

    Undecided races are excluded here and **kept** by the R estimators: price
    that stayed inside one unit of the level for the whole horizon has no
    hold/break answer, but it does have an R, and dropping it there would
    discard the quiet outcomes and inflate every arm's variance.
    """
    mask = mask & rows.decided
    if int(mask.sum()) < LEAST:
        return None
    stratum = rows.stratum[mask]
    bucket = np.zeros_like(stratum)
    hits, totals, keys = _tensor(rows.block[mask], bucket, stratum, rows.held[mask], 1)

    def stat(h, t):
        rate, mass = _within(h.sum(axis=0), t.sum(axis=0))
        return (None if np.isnan(rate[0]) else float(rate[0])), mass

    value, mass = stat(hits, totals)
    if value is None:
        return None
    rng = np.random.default_rng(seed)
    spread = [
        got
        for got, _ in (
            stat(hits[pick], totals[pick])
            for pick in (rng.integers(0, len(keys), len(keys)) for _ in range(draws))
        )
        if got is not None
    ]
    return Stat(
        n=int(mass[0]),
        value=value,
        sd=float(st.pstdev(spread)) if len(spread) > 5 else 0.0,
        lo=value,
        hi=float("nan"),
    )


def _cell_median_split(grade: np.ndarray, cell: np.ndarray) -> np.ndarray:
    """1 where a grade is above its own cell's median, 0 below, -1 at it.

    Split **within the cell** and not globally, because the grade's level moves
    with compression and with level age: a global median would put most of one
    stratum in one bucket and the comparison would be between strata, which is
    the confound the stratification exists to remove.

    Ties go to -1 and are dropped. A discrete grade - and `sharp_share` over
    two previous episodes takes few values - ties often, and assigning ties to
    one side makes the bucket sizes depend on the grade's granularity.
    """
    out = np.full(len(grade), -1, dtype=np.int64)
    for key in np.unique(cell):
        here = cell == key
        mid = float(np.median(grade[here]))
        out[here & (grade > mid)] = 1
        out[here & (grade < mid)] = 0
    return out


def grade_gap_for(
    rows: Rows,
    mask: np.ndarray,
    grade: str,
    *,
    draws: int = DRAWS,
    seed: int = 0,
) -> Stat | None:
    """High-grade hold rate minus low-grade, within compression x level age.

    Positive means a level whose **previous** departures scored higher on this
    grade holds its next touch more often. The claim under test predicts
    positive for `sharp_share`.

    Only episodes with at least one previous one are usable: a grade over an
    empty history is the pooled prior and carries no information about the
    level, so including them would dilute the statistic toward zero with rows
    that cannot speak either way.
    """
    usable = mask & rows.decided & (rows.n_prev >= 1)
    if int(usable.sum()) < LEAST:
        return None
    values = getattr(rows, grade)[usable]
    cell = rows.stratum[usable] * (len(AGE_EDGES) + 1) + age_bin(rows.n_prev[usable])
    bucket = _cell_median_split(values, cell)
    keep = bucket >= 0
    if int(keep.sum()) < LEAST:
        return None
    hits, totals, keys = _tensor(
        rows.block[usable][keep],
        bucket[keep],
        cell[keep] - cell[keep].min(),
        rows.held[usable][keep],
        2,
    )
    if totals[:, 0].sum() < 30 or totals[:, 1].sum() < 30:
        return None

    def stat(h, t):
        rate, mass = _within(h.sum(axis=0), t.sum(axis=0))
        if np.isnan(rate).any():
            return None, rate, mass
        return float(rate[1] - rate[0]), rate, mass

    value, rate, mass = stat(hits, totals)
    if value is None:
        return None
    # Guarded on the mass that survived `FLOOR`, not on the row count. The
    # first version guarded only the rows and reported a bjorgum gap of
    # -0.0769 on **26** episodes, because 209 rows spread over 25 cells left
    # almost every cell under the floor. A cell that thin is the noise the
    # `LEAST` guard exists to refuse, and it had got past it.
    if mass.sum() < LEAST:
        return None
    rng = np.random.default_rng(seed)
    spread = []
    for _ in range(draws):
        pick = rng.integers(0, len(keys), len(keys))
        got, _, _ = stat(hits[pick], totals[pick])
        if got is not None:
            spread.append(got)
    return Stat(
        n=int(mass.sum()),
        value=value,
        sd=float(st.pstdev(spread)) if len(spread) > 5 else 0.0,
        lo=float(rate[0]),
        hi=float(rate[1]),
    )


def _auc(score: np.ndarray, label: np.ndarray) -> float | None:
    """Tie-aware AUC by mid-ranks. Reads 0.5 on a constant score, not 1.0.

    `conditional_holds.py` documents its own estimator reading **1.0000** for a
    constant arm, which is the defect this form avoids: with every score equal,
    every pair is a tie, mid-ranks are identical and the answer is 0.5. A cell
    where the grade has collapsed to one value must read "no information", not
    "perfect".
    """
    pos = int(label.sum())
    neg = len(label) - pos
    if pos == 0 or neg == 0:
        return None
    order = np.argsort(score, kind="mergesort")
    sorted_score = score[order]
    # Mid-ranks without a Python loop. The loop version cost 18.5s per series
    # pass on 978 episodes, almost all of it here: 400 bootstrap draws times 25
    # cells is 10,000 calls, each walking its own scores one at a time.
    # `starts` marks each tie group's first index, so the group every element
    # belongs to is a cumulative sum and its midpoint is two lookups.
    starts = np.ones(len(sorted_score), dtype=bool)
    starts[1:] = sorted_score[1:] != sorted_score[:-1]
    group = np.cumsum(starts) - 1
    first = np.flatnonzero(starts)
    last = np.append(first[1:], len(sorted_score)) - 1
    ranks = np.empty(len(score), dtype=float)
    ranks[order] = 0.5 * (first[group] + last[group]) + 1.0
    return float((ranks[label].sum() - pos * (pos + 1) / 2.0) / (pos * neg))


def grade_auc_for(
    rows: Rows,
    mask: np.ndarray,
    grade: str,
    *,
    draws: int = DRAWS,
    seed: int = 0,
) -> Stat | None:
    """AUC of the grade against the next touch holding, within cell, then pooled.

    Ranked **inside** each compression-by-age cell and pooled by episode count,
    because a pooled AUC over cells with different base rates orders on the
    cell and not on the grade - that confound was worth +0.112 of MSE in
    `level-shrinkage.md` and 0.004 of AUC in `record-auc.md`, and worth
    reporting as measured here rather than assumed either way.
    """
    usable = mask & rows.decided & (rows.n_prev >= 1)
    if int(usable.sum()) < LEAST:
        return None
    values = getattr(rows, grade)[usable]
    held = rows.held[usable]
    block = rows.block[usable]
    cell = rows.stratum[usable] * (len(AGE_EDGES) + 1) + age_bin(rows.n_prev[usable])

    # The cell index lists are built **once**. Recomputing `take & (cell ==
    # key)` inside the bootstrap cost a full-length boolean pass per cell per
    # draw - 25 cells times 400 draws times every row - and was most of the
    # 19s this function took per series pass.
    cells = [np.flatnonzero(cell == key) for key in np.unique(cell)]
    cells = [idx for idx in cells if len(idx) >= FLOOR]
    if not cells:
        return None
    span = int(block.max()) + 1

    def stat(pick_blocks=None):
        weights = None if pick_blocks is None else np.bincount(pick_blocks, minlength=span)[block]
        total = 0.0
        mass = 0.0
        for idx in cells:
            if weights is None:
                got = _auc(values[idx], held[idx])
                size = float(len(idx))
            else:
                keep = idx[weights[idx] > 0]
                if len(keep) < FLOOR:
                    continue
                got = _auc(values[keep], held[keep])
                size = float(weights[keep].sum())
            if got is None:
                continue
            total += got * size
            mass += size
        return (total / mass if mass > 0 else None), mass

    value, mass = stat()
    if value is None:
        return None
    rng = np.random.default_rng(seed)
    keys = np.unique(block)
    spread = []
    for _ in range(draws):
        got, _ = stat(rng.choice(keys, len(keys)))
        if got is not None:
            spread.append(got)
    return Stat(
        n=int(mass),
        value=value,
        sd=float(st.pstdev(spread)) if len(spread) > 5 else 0.0,
        lo=value,
        hi=float("nan"),
    )


@dataclass(frozen=True, slots=True)
class Money:
    """A mean R with everything needed to judge it, including its variance.

    **The sd is not decoration.** A score that selects sharper bounces selects
    larger moves, so the arm it creates has a higher per-trade sd and needs a
    larger sample for the same confidence. Comparing two arms' means without
    their sds compares two different amounts of evidence, so `needed` is
    carried: the trades this arm's own mean and sd would require to reach
    |t| = 2. An arm that wins on the mean and needs four times the sample has
    not won.
    """

    n: int
    mean: float
    #: Block-bootstrap sd of the mean. Blocks, not rows: nearby episodes share
    #: outcome bars and an ordinary standard error is far too narrow.
    se: float
    #: Per-trade sd, which is what the sample requirement scales with.
    sd: float
    profit_factor: float
    win_rate: float
    sharpe: float

    @property
    def t(self) -> float:
        return self.mean / self.se if self.se > 0 else 0.0

    @property
    def needed(self) -> float:
        """Trades for |t| = 2 at this mean and per-trade sd."""
        return (2.0 * self.sd / abs(self.mean)) ** 2 if self.mean else float("inf")


def _money(values: np.ndarray, block: np.ndarray, *, draws: int, seed: int) -> Money | None:
    """Mean R, block-bootstrap se, per-trade sd, profit factor, win rate."""
    if len(values) < LEAST:
        return None
    keys, index = np.unique(block, return_inverse=True)
    sums = np.bincount(index, weights=values, minlength=len(keys))
    counts = np.bincount(index, minlength=len(keys)).astype(float)
    rng = np.random.default_rng(seed)
    spread = []
    for _ in range(draws):
        pick = rng.integers(0, len(keys), len(keys))
        total = counts[pick].sum()
        if total > 0:
            spread.append(sums[pick].sum() / total)
    wins = values[values > 0]
    losses = values[values < 0]
    sd = float(np.std(values, ddof=1)) if len(values) > 1 else 0.0
    mean = float(values.mean())
    return Money(
        n=len(values),
        mean=mean,
        se=float(st.pstdev(spread)) if len(spread) > 5 else 0.0,
        sd=sd,
        profit_factor=float(wins.sum() / -losses.sum()) if losses.sum() < 0 else float("inf"),
        win_rate=float((values > 0).mean()),
        sharpe=mean / sd if sd > 0 else 0.0,
    )


def r_for(
    rows: Rows,
    mask: np.ndarray,
    target: float,
    *,
    draws: int = DRAWS,
    seed: int = 0,
) -> Money | None:
    """Mean R over every episode in `mask`, at one reward-to-risk.

    **Zero is the walk's answer at every target**, because the target is a
    multiple of the realised risk, so this is read against zero and against
    the same number on the placebo and surrogate arms.
    """
    values = rows.r[target][mask]
    return _money(values, rows.block[mask], draws=draws, seed=seed)


def grade_r_for(
    rows: Rows,
    mask: np.ndarray,
    grade: str,
    target: float,
    *,
    draws: int = DRAWS,
    seed: int = 0,
) -> tuple[Money, Money, Money] | None:
    """`(high, low, difference)` mean R, split at each cell's own median grade.

    The deciding statistic. Positive on the difference means a level whose
    **previous** departures scored higher on this grade pays more on its next
    touch - which is the claim, and is not the same claim as "bounces more
    often". The two can disagree, and if they do the R is the one that matters.

    The difference's se is bootstrapped on the **same blocks** for both arms in
    each draw, so the two halves are paired and the common regime cancels
    instead of being added in quadrature.
    """
    usable = mask & (rows.n_prev >= 1)
    if int(usable.sum()) < 2 * LEAST:
        return None
    values = rows.r[target][usable]
    block = rows.block[usable]
    cell = rows.stratum[usable] * (len(AGE_EDGES) + 1) + age_bin(rows.n_prev[usable])
    bucket = _cell_median_split(getattr(rows, grade)[usable], cell)
    hi_mask, lo_mask = bucket == 1, bucket == 0
    if int(hi_mask.sum()) < LEAST or int(lo_mask.sum()) < LEAST:
        return None
    high = _money(values[hi_mask], block[hi_mask], draws=draws, seed=seed)
    low = _money(values[lo_mask], block[lo_mask], draws=draws, seed=seed + 1)
    if high is None or low is None:
        return None

    keys, index = np.unique(block, return_inverse=True)
    def sums_counts(sel):
        return (
            np.bincount(index[sel], weights=values[sel], minlength=len(keys)),
            np.bincount(index[sel], minlength=len(keys)).astype(float),
        )

    hs, hc = sums_counts(hi_mask)
    ls, lc = sums_counts(lo_mask)
    rng = np.random.default_rng(seed + 2)
    spread = []
    for _ in range(draws):
        pick = rng.integers(0, len(keys), len(keys))
        ht, lt = hc[pick].sum(), lc[pick].sum()
        if ht > 0 and lt > 0:
            spread.append(hs[pick].sum() / ht - ls[pick].sum() / lt)
    gap = high.mean - low.mean
    pooled = float(np.std(values[hi_mask | lo_mask], ddof=1))
    return (
        high,
        low,
        Money(
            n=high.n + low.n,
            mean=gap,
            se=float(st.pstdev(spread)) if len(spread) > 5 else 0.0,
            sd=pooled,
            profit_factor=float("nan"),
            win_rate=high.win_rate - low.win_rate,
            sharpe=gap / pooled if pooled > 0 else 0.0,
        ),
    )


def shares(rows: Rows, mask: np.ndarray) -> dict[str, float]:
    """What share of episodes each shape bit fired on.

    Reported because a rule firing on 2% of touches is a different object from
    one firing on 40%, and the bits **overlap** - they are a mask and not a
    partition, so these do not sum to one and are not meant to.
    """
    from research.ideas.level_bounce import (
        DRIFT,
        LEG,
        REJECT,
        RUN,
        SHARP,
        SHARP_BAR,
        SPIKE,
        STALL,
        THROUGH,
    )

    shape = rows.shape[mask]
    n = max(1, len(shape))
    bits = {
        "reject": REJECT,
        "spike": SPIKE,
        "leg": LEG,
        "run": RUN,
        "drift": DRIFT,
        "through": THROUGH,
        "stall": STALL,
        "sharp": SHARP,
        "sharp_bar": SHARP_BAR,
    }
    out = {name: float((shape & bit > 0).sum()) / n for name, bit in bits.items()}
    out["n"] = float(len(shape))
    return out


def by_stratum(rows: Rows, mask: np.ndarray) -> list[dict]:
    """Hold rate and sharp share per compression quintile, pooled over eras.

    The table that says whether conditioning on bounce shape is conditioning
    on volatility. If `sharp` climbs steeply across quintiles and the grade gap
    only exists pooled, the grade is a volatility reading wearing a shape's
    clothes - which is `topology-restates-volatility` in this study's own
    variables.
    """
    from research.ideas.level_bounce import SHARP

    eras = max(1, BINS // 5)
    quint = rows.stratum[mask] // eras
    shape = rows.shape[mask]
    held = rows.held[mask]
    out = []
    for q in range(5):
        here = quint == q
        if here.sum() < FLOOR:
            continue
        out.append(
            {
                "quintile": q,
                "n": int(here.sum()),
                "hold": float(held[here].mean()),
                "sharp": float((shape[here] & SHARP > 0).mean()),
            }
        )
    return out
