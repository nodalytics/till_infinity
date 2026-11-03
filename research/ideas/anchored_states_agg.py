"""The statistics for the anchored-states study, and the traps in each.

Three things decide whether a number here means anything, and all three are
recorded failures on this desk rather than style preferences.

**The contrast is within volatility strata, always.**
`AUC-is-free-on-volatility-targets` measured an AUC of **0.805** on a
constant-volatility process where the true answer is 0.5, falling to **0.525
within strata**, with incumbent features alone reading 0.74-0.78. A dispersion
target is exactly that kind of target, so the pooled figure is carried only to
show the size of the gap and is labelled as not a result.

**The de-meaning is a fixed effect, not a per-cell table.** Flooring a
(stratum x level) table at this row count empties it: 70 de-overlapped rows at
15m over 5 quintiles and 4 session levels is 3.5 rows a cell. `level-bounce.md`
is the recorded version - `grade_gap_for` guarded on the rows going *in*, and
209 rows over 25 cells left almost every cell under the 10-episode floor while
it still reported -0.0769 on the 26 that survived. So the statistic centres
each row on its own stratum's mean and then compares level means, which needs
mass per level rather than per cell, and the guard sits on the mass that
**survives** the flooring with that share printed beside every number.

**The null's own spread is estimated from 16 draws.** A one-sided t with 15
degrees of freedom is the honest p, not a normal on a sd taken as known.
`stop-anchor.md`: "the z's sd comes from the same draws, so every p and BH q is
too small - use z only to rank cells". The exceedance count against its own
chance expectation is carried beside every BH figure for that reason.
"""

from __future__ import annotations

import math
import statistics as st
from dataclasses import dataclass, field

import numpy as np

#: The fewest rows a state level needs before it may contribute a mean.
#: Levels below it are dropped and their share of the rows is reported.
LEVEL_FLOOR = 8

#: The fewest rows that must survive the flooring, and the fewest levels.
MASS_FLOOR = 30
LEVELS_FLOOR = 2

#: The fewest rows a stratum needs before its mean is used for centring. A
#: stratum below it contributes nothing rather than a mean of three rows.
STRATUM_FLOOR = 5


def _mbb(rng: np.random.Generator, n: int, block: int) -> np.ndarray:
    """Moving-block bootstrap indices. Block 1 is the ordinary bootstrap."""
    if block <= 1 or n <= block:
        return rng.integers(0, n, n)
    starts = rng.integers(0, n - block + 1, math.ceil(n / block))
    idx = (starts[:, None] + np.arange(block)[None, :]).ravel()[:n]
    return np.minimum(idx, n - 1)


def _centred(stratum: np.ndarray, value: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Each row less its own stratum's mean, and which rows are usable.

    A fixed-effects de-meaning: the volatility stratum is removed to first
    order from every row before any level is compared, which is the within
    comparison `topology-restates-volatility` requires and the only version
    this row count supports.
    """
    keep = np.zeros(len(value), dtype=bool)
    out = np.zeros(len(value))
    for s in np.unique(stratum):
        if s < 0:
            continue
        sel = stratum == s
        if sel.sum() < STRATUM_FLOOR:
            continue
        out[sel] = value[sel] - value[sel].mean()
        keep |= sel
    return out, keep


@dataclass(slots=True)
class Spread:
    """How far apart the state's levels put the outcome, within strata.

    `spread` is the mass-weighted root mean square of the per-level mean
    residual, in volatility units of the decision bar - so it is directly
    comparable with a stop distance, which is what the cost check needs.

    **`effect` is `spread / resid_sd` and is the statistic that decides**,
    because an unstandardised spread compares an arm's effect against a noise
    floor set by that arm's own variance. Measured on eurusd 1d: the real
    arm's `size` has mean 2.300 and sd 1.904, while `level_shield.garch_bars`
    reads **1.257-1.410 and 1.054-1.195** - its bar ranges are about 1.5x too
    wide against its close path, because the arm scales a range by the
    simulated *sd* against a *median* absolute return. So the arms differ from
    the real series on the marginal scale of the outcome, and a raw spread
    would read that difference as structure.

    `kw` is the same question asked on within-stratum ranks, carried because
    `size` has this market's tails (kurtosis 47-74 on traded feeds) and a mean
    of twelve rows is not robust to them.
    """

    n: int
    mass: int
    kept: float
    used: int
    spread: float
    sd: float
    effect: float
    effect_sd: float
    resid_sd: float
    kw: float
    per_level_n: tuple[int, ...]
    per_level_mean: tuple[float, ...]
    per_level_sd: tuple[float, ...]
    pooled_mean: float
    row_sd: float
    n_eff: float

    @property
    def z(self) -> float:
        return self.effect / self.effect_sd if self.effect_sd > 0 else 0.0


def _kruskal(level: np.ndarray, stratum: np.ndarray, value: np.ndarray, bins: int) -> float:
    """Kruskal-Wallis H summed over strata, on within-stratum ranks."""
    total = 0.0
    for s in np.unique(stratum):
        if s < 0:
            continue
        sel = stratum == s
        n = int(sel.sum())
        if n < 10:
            continue
        order = np.argsort(np.argsort(value[sel], kind="stable"), kind="stable") + 1.0
        here = level[sel]
        groups = [order[here == g] for g in range(bins)]
        groups = [g for g in groups if len(g) > 0]
        if len(groups) < 2:
            continue
        mid = (n + 1) / 2.0
        total += 12.0 / (n * (n + 1.0)) * sum(len(g) * (g.mean() - mid) ** 2 for g in groups)
    return total


def spread_for(
    level: np.ndarray,
    stratum: np.ndarray,
    value: np.ndarray,
    *,
    bins: int,
    block: int = 1,
    draws: int = 400,
    seed: int = 0,
) -> Spread | None:
    """The decision statistic, with a moving-block bootstrap sd.

    `None` where the guards refuse: fewer than two levels above the floor, or
    under `MASS_FLOOR` surviving rows. A refusal is a cell this study cannot
    answer and is counted as such, never as a null.
    """
    ok = (level >= 0) & (stratum >= 0) & np.isfinite(value)
    if ok.sum() < MASS_FLOOR:
        return None
    lv, sr, val = level[ok], stratum[ok], value[ok]
    resid, usable = _centred(sr, val)
    if usable.sum() < MASS_FLOOR:
        return None
    lv, sr, val, resid = lv[usable], sr[usable], val[usable], resid[usable]

    counts = np.asarray([int((lv == g).sum()) for g in range(bins)])
    live = counts >= LEVEL_FLOOR
    if live.sum() < LEVELS_FLOOR:
        return None
    keep = np.isin(lv, np.flatnonzero(live))
    if keep.sum() < MASS_FLOOR:
        return None
    kept = float(keep.sum()) / float(len(lv))
    lv, sr, val, resid = lv[keep], sr[keep], val[keep], resid[keep]

    def stat(idx: np.ndarray) -> tuple[float, float] | None:
        """`(spread, effect)` on these rows: the raw one and the scale-free one."""
        here_l, here_r = lv[idx], resid[idx]
        total = 0.0
        mass = 0.0
        for g in range(bins):
            sel = here_l == g
            k = int(sel.sum())
            if k < 2:
                continue
            total += k * float(here_r[sel].mean()) ** 2
            mass += k
        if mass <= 0:
            return None
        spread = math.sqrt(total / mass)
        scale = float(np.std(here_r, ddof=1)) if len(here_r) > 1 else 0.0
        return spread, (spread / scale if scale > 0 else 0.0)

    whole = np.arange(len(lv))
    observed = stat(whole)
    if observed is None:
        return None
    rng = np.random.default_rng(seed)
    got: list[float] = []
    effects: list[float] = []
    means: list[float] = []
    for _ in range(draws):
        idx = _mbb(rng, len(lv), block)
        drawn = stat(idx)
        if drawn is not None:
            got.append(drawn[0])
            effects.append(drawn[1])
            means.append(float(val[idx].mean()))
    sd = float(st.pstdev(got)) if len(got) > 5 else 0.0
    effect_sd = float(st.pstdev(effects)) if len(effects) > 5 else 0.0
    mean_sd = float(st.pstdev(means)) if len(means) > 5 else 0.0
    row_sd = float(np.std(val, ddof=1)) if len(val) > 1 else 0.0
    return Spread(
        n=int(ok.sum()),
        mass=int(len(lv)),
        kept=kept,
        used=int(live.sum()),
        spread=observed[0],
        sd=sd,
        effect=observed[1],
        effect_sd=effect_sd,
        resid_sd=float(np.std(resid, ddof=1)) if len(resid) > 1 else 0.0,
        kw=_kruskal(lv, sr, val, bins),
        per_level_n=tuple(int((lv == g).sum()) for g in range(bins)),
        per_level_mean=tuple(
            float(resid[lv == g].mean()) if (lv == g).sum() else float("nan") for g in range(bins)
        ),
        per_level_sd=tuple(
            float(np.std(resid[lv == g], ddof=1)) if (lv == g).sum() > 1 else float("nan")
            for g in range(bins)
        ),
        pooled_mean=float(val.mean()),
        row_sd=row_sd,
        n_eff=(row_sd / mean_sd) ** 2 if mean_sd > 0 else 0.0,
    )


def duty_draws(
    level: np.ndarray,
    stratum: np.ndarray,
    value: np.ndarray,
    *,
    bins: int,
    block: int,
    draws: int,
    seed: int,
) -> list[float]:
    """The duty-cycle twin: the state's own times, the outcome permuted.

    Keeps the state's firing rate and the bars it fires on **by
    construction** - the labels never move - and permutes the outcome within
    the compression stratum, so the stratum marginals are identical too and
    the only thing destroyed is the association between the state and the
    outcome. Pass rule 4 is what this exists for: otherwise a finding is the
    firing rate rather than the state.

    The permutation is legitimate here because the rows are already
    de-overlapped by at least `H` bars, so they are close to exchangeable
    within a stratum. On overlapping anchors it would not be:
    `overlapping-windows-inflate-permutation-nulls` is the record - a level
    finding at p 0.015 was anchor overlap, and the tell was the no-level
    control passing.
    """
    out: list[float] = []
    for draw in range(draws):
        rng = np.random.default_rng(seed + draw)
        shuffled = value.copy()
        for s in np.unique(stratum):
            if s < 0:
                continue
            sel = np.flatnonzero(stratum == s)
            if len(sel) < 2:
                continue
            shuffled[sel] = value[sel][rng.permutation(len(sel))]
        got = spread_for(
            level, stratum, shuffled, bins=bins, block=block, draws=0, seed=seed + draw
        )
        if got is not None:
            out.append(got.effect)
    return out


def sign_flip_draws(
    level: np.ndarray,
    stratum: np.ndarray,
    signed: np.ndarray,
    *,
    bins: int,
    block: int,
    draws: int,
    seed: int,
) -> list[float]:
    """The secondary claim's own null: the magnitudes kept, the signs coined.

    The prereg's extra requirement for direction - "the state's own direction
    effect is larger than the same state's effect on a `signed` outcome with
    the sign randomised". Keeping the magnitudes means this arm has the right
    tails, which a Gaussian null for a direction claim does not:
    `fear-greed.md` found Gaussian GARCH reading -0.079 to +0.116 on all
    fourteen legs, so clustering contributed nothing and the mechanism was
    skewness.
    """
    out: list[float] = []
    for draw in range(draws):
        rng = np.random.default_rng(seed + 7919 * draw)
        flipped = np.abs(signed) * rng.choice([-1.0, 1.0], size=len(signed))
        got = spread_for(
            level, stratum, flipped, bins=bins, block=block, draws=0, seed=seed + draw
        )
        if got is not None:
            out.append(got.effect)
    return out


# ────────────────────────────── the AUC pair ──────────────────────────────


def _auc(score: np.ndarray, hit: np.ndarray) -> float | None:
    """Mann-Whitney AUC with midranks, so a 3-level score is not mis-scored."""
    if len(score) < 10:
        return None
    pos = int(hit.sum())
    neg = len(hit) - pos
    if pos == 0 or neg == 0:
        return None
    order = np.argsort(score, kind="stable")
    ranks = np.empty(len(score), dtype=float)
    sorted_score = score[order]
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and sorted_score[j + 1] == sorted_score[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return float((ranks[hit].sum() - pos * (pos + 1) / 2.0) / (pos * neg))


@dataclass(slots=True)
class Auc:
    """The stratified AUC, and the pooled one beside it as a warning.

    **The pooled figure is not a result and is not reported as one.** It is
    carried because the size of `pooled - strata` is the measurement that
    `AUC-is-free-on-volatility-targets` is about, and a reader cannot see it
    if only the stratified number is printed.
    """

    strata: float | None
    pooled: float | None
    n: int


def auc_crossfit(
    level: np.ndarray,
    stratum: np.ndarray,
    value: np.ndarray,
    *,
    bins: int,
    half: np.ndarray,
) -> Auc:
    """AUC of the state, with the level ordering fitted on the other half.

    The ordering of the levels is the only thing fitted anywhere in this
    study, and it is fitted **out of sample**: half A ranks the levels by mean
    residual, half B is scored with that ranking, and the reverse. A
    within-sample ordering would make the AUC a restatement of the ordering,
    which is `fit-on-the-edge-not-the-raw-score`'s half of the same point.
    """
    ok = (level >= 0) & (stratum >= 0) & np.isfinite(value)
    lv, sr, val, hf = level[ok], stratum[ok], value[ok], half[ok]
    resid, usable = _centred(sr, val)
    if usable.sum() < MASS_FLOOR:
        return Auc(strata=None, pooled=None, n=0)
    lv, sr, val, hf, resid = lv[usable], sr[usable], val[usable], hf[usable], resid[usable]

    def scores(fit_on: np.ndarray) -> np.ndarray:
        """Each row's level, ranked by `fit_on` on the **other** half."""
        out = np.full(len(lv), np.nan)
        for side in (0, 1):
            train, test = hf != side, hf == side
            if train.sum() < MASS_FLOOR or test.sum() < LEVEL_FLOOR:
                continue
            ranking = {}
            for g in range(bins):
                sel = train & (lv == g)
                if sel.sum() >= LEVEL_FLOOR:
                    ranking[g] = float(fit_on[sel].mean())
            if len(ranking) < 2:
                continue
            order = {g: r for r, g in enumerate(sorted(ranking, key=lambda k: ranking[k]))}
            for g, rank in order.items():
                out[test & (lv == g)] = float(rank)
        return out

    #: Two orderings, because the pooled figure exists to show what the naive
    #: procedure reads. The stratified one ranks levels by their **residual**
    #: mean and scores within strata; the pooled one ranks them by their
    #: **raw** mean and scores pooled, which is the procedure that produced
    #: the 0.805 on a constant-volatility process. Centring the pooled
    #: ordering too would delete the thing the comparison is for.
    strat_score, raw_score = scores(resid), scores(val)
    live = np.isfinite(strat_score)
    if live.sum() < MASS_FLOOR:
        return Auc(strata=None, pooled=None, n=int(live.sum()))

    per: list[tuple[float, int]] = []
    for stratum_id in np.unique(sr[live]):
        sel = live & (sr == stratum_id)
        if sel.sum() < 10:
            continue
        got = _auc(strat_score[sel], val[sel] > float(np.median(val[sel])))
        if got is not None:
            per.append((got, int(sel.sum())))
    strata = sum(a * k for a, k in per) / sum(k for _a, k in per) if per else None
    raw_live = np.isfinite(raw_score)
    pooled = (
        _auc(raw_score[raw_live], val[raw_live] > float(np.median(val[raw_live])))
        if raw_live.sum() >= MASS_FLOOR
        else None
    )
    return Auc(strata=strata, pooled=pooled, n=int(live.sum()))


def cramers_v(level: np.ndarray, stratum: np.ndarray, *, bins: int) -> float:
    """How much of the state is the compression quintile relabelled.

    The prereg's first "uninteresting even if it passes" clause: if the state
    is monotone in the compression quintile it restates the volatility
    estimate, and `topology-restates-volatility` already covers it - levels,
    ranges and shapes all read null once volatility is stratified. 0 means the
    state and the stratum are independent, 1 that one determines the other.
    """
    ok = (level >= 0) & (stratum >= 0)
    if ok.sum() < MASS_FLOOR:
        return float("nan")
    lv, sr = level[ok], stratum[ok]
    rows, cols = bins, int(sr.max()) + 1
    table = np.zeros((rows, cols))
    for g in range(rows):
        for s in range(cols):
            table[g, s] = float(((lv == g) & (sr == s)).sum())
    total = table.sum()
    expected = np.outer(table.sum(axis=1), table.sum(axis=0)) / total
    live = expected > 0
    chi2 = float((((table - expected) ** 2)[live] / expected[live]).sum())
    k = min(rows, cols) - 1
    return math.sqrt(chi2 / (total * k)) if k > 0 and total > 0 else float("nan")


# ─────────────────────────── arms and multiplicity ───────────────────────────


@dataclass(slots=True)
class Verdict:
    """A cell read against its arms. Everything the pass rule needs, once."""

    real: float
    hardest: float
    hardest_arm: str
    hardest_mean: float
    hardest_sd: float
    draws: int
    excess: float
    z: float
    p: float
    beats_hardest: bool
    per_arm: dict[str, tuple[float, float, float]] = field(default_factory=dict)


def _student_p(t: float, df: int) -> float:
    """One-sided upper-tail p for Student's t, by the incomplete beta.

    A t and not a normal, because the arm's sd comes from 16 draws: a normal
    on a sd taken as known is the mistake `stop-anchor.md` names, where every
    p and BH q came out too small.
    """
    if df <= 0:
        return 1.0
    if t <= 0:
        return 1.0 - _student_p(-t, df) if t < 0 else 0.5
    x = df / (df + t * t)
    return 0.5 * _betainc(df / 2.0, 0.5, x)


def _betainc(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta `I_x(a, b)`, by its continued fraction."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(lbeta + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _cf(a, b, x) / a
    return 1.0 - math.exp(lbeta + b * math.log1p(-x) + a * math.log(x)) * _cf(b, a, 1.0 - x) / b


def _cf(a: float, b: float, x: float) -> float:
    """Lentz's continued fraction for the incomplete beta."""
    tiny = 1e-30
    c, d = 1.0, 1.0 - (a + b) * x / (a + 1.0)
    d = tiny if abs(d) < tiny else d
    d = 1.0 / d
    out = d
    for m in range(1, 200):
        num = m * (b - m) * x / ((a + 2.0 * m - 1.0) * (a + 2.0 * m))
        d = 1.0 + num * d
        d = tiny if abs(d) < tiny else d
        c = 1.0 + num / c
        c = tiny if abs(c) < tiny else c
        d = 1.0 / d
        out *= d * c
        num = -(a + m) * (a + b + m) * x / ((a + 2.0 * m) * (a + 2.0 * m + 1.0))
        d = 1.0 + num * d
        d = tiny if abs(d) < tiny else d
        c = 1.0 + num / c
        c = tiny if abs(c) < tiny else c
        d = 1.0 / d
        delta = d * c
        out *= delta
        if abs(delta - 1.0) < 1e-10:
            break
    return out


def judge(real: float, real_sd: float, arms: dict[str, list[float]]) -> Verdict | None:
    """Read a cell against its arms, hardest arm first.

    "Exceeds its hardest null arm" is the prereg's bar and it is applied to
    the **maximum over every draw of every deciding arm**, which with four
    arms at sixteen draws is 64 draws and a chance pass of 1 in 65. The count
    is what makes the raw exceedance tally readable, and it is reported with
    its Poisson spread: `fear-greed.md`'s eighth defect is a hardest-of-20
    test manufacturing both of a study's positive cells, where one of sixteen
    `bar-shuffle` draws reached -0.334 against a real -0.297 and the four
    panel draws had landed in a range of 0.06 against a true range of 0.44.
    """
    live = {name: got for name, got in arms.items() if len(got) >= 2}
    if not live:
        return None
    stats = {
        name: (float(np.mean(got)), float(np.std(got, ddof=1)), len(got))
        for name, got in live.items()
    }
    hardest_arm = max(stats, key=lambda k: stats[k][0])
    mean, sd, k = stats[hardest_arm]
    every = [x for got in live.values() for x in got]
    combined = math.sqrt(real_sd**2 + sd**2 * (1.0 + 1.0 / k)) if (real_sd or sd) else 0.0
    z = (real - mean) / combined if combined > 0 else 0.0
    return Verdict(
        real=real,
        hardest=float(max(every)),
        hardest_arm=hardest_arm,
        hardest_mean=mean,
        hardest_sd=sd,
        draws=len(every),
        excess=real - mean,
        z=z,
        p=_student_p(z, max(1, k - 1)),
        beats_hardest=real > max(every),
        per_arm=stats,
    )


def benjamini_hochberg(ps: list[float], q: float = 0.10) -> list[bool]:
    """Which p-values survive at FDR `q`, over every cell looked at.

    Picking the best of 43 instruments gives a winner every time; on this desk
    18 of 43 were nominally profitable where chance gives 22, and none
    survived this as profitable while five survived as losers.
    """
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    m = len(ps)
    cut = 0
    for rank, i in enumerate(order, start=1):
        if ps[i] <= q * rank / m:
            cut = rank
    keep = [False] * m
    for rank, i in enumerate(order, start=1):
        if rank <= cut:
            keep[i] = True
    return keep


def expected_passes(cells: int, draws: int) -> tuple[float, float]:
    """How many cells beat their hardest of `draws` by chance, and its spread.

    `cells / (draws + 1)`, Poisson. Quoting a raw pass count without this is
    the mistake `stop-anchor.md` reports: a hardcoded "12 draws give about
    10.8" printed whatever `--draws` was, understated the bar fourfold, and
    made 3 of 140 read as "far below chance".
    """
    mean = cells / (draws + 1.0)
    return mean, math.sqrt(mean)
