"""Aggregation for the level-shield test: count tensors, not boolean masks.

The first version resampled days by OR-ing a boolean mask per day per draw -
76 days x 200 draws x 50,000 rows per cell, which did not finish a single
series in seven minutes. Everything here bins to a `(day, bucket, stratum)`
count tensor once, so a bootstrap draw is `cnt[pick].sum(axis=0)`. It is also
*more* correct: a day drawn twice counts twice, which a presence mask cannot
represent and which was understating the sd.

Three estimators, weakest to strongest control:

* `gap` - shielded against clear path at matched distance, within volatility
  quintiles. Leans on a clear arm that is 7-9% of anchors.
* `dose` - reach rate against how many levels block the path, within strata.
  Uses every anchor and asks for monotonicity.
* `mirror` - **the one that decides.** Anchors where one side is blocked and
  the other is clear, paired within the anchor. The day, the hour, the
  volatility and the forward window are identical by construction, so none of
  them can produce the gap. `docs/magnet.md` §5 is why this is the headline:
  a level exists on days price travels 8-17% less far, which accounted for the
  whole of its -4.6 point deficit, and its own day-fixed control took the
  level effect to -0.009 [-0.062, +0.038].

The mirror needs the up/down excursion skew removed. Placebos there ran 0.562
up against 0.478 down, so an estimator that compared "blocked up" against
"clear down" without correcting would read 8 points of skew as a barrier.
`mirror` corrects from the concordant anchors of the same series and distance.
"""

import math
import statistics as st
from dataclasses import dataclass

import numpy as np

from research.ideas.level_shield import BINS, OTHER, SHIELD

#: Levels in the path, capped. 3+ is one bucket: the fourth is not a
#: distinguishable dose at this sample size.
DOSE = (0, 1, 2, 3)


def _tensor(day: np.ndarray, bucket: np.ndarray, stratum: np.ndarray, hit: np.ndarray, buckets: int):
    """`(hits, totals, day_index)` binned to `(day, bucket, stratum)`."""
    keys, index = np.unique(day, return_inverse=True)
    shape = (len(keys), buckets, BINS)
    flat = (index * buckets + bucket) * BINS + stratum
    totals = np.bincount(flat, minlength=int(np.prod(shape))).reshape(shape)
    hits = np.bincount(flat, weights=hit.astype(float), minlength=int(np.prod(shape))).reshape(shape)
    return hits, totals, keys


def _within(hits: np.ndarray, totals: np.ndarray, floor: int = 10) -> tuple[np.ndarray, np.ndarray]:
    """Per-bucket rate, averaged over strata and weighted by each stratum's n.

    A stratum with fewer than `floor` observations in a bucket contributes
    nothing rather than a rate computed from three rows.
    """
    usable = totals >= floor
    rate = np.divide(hits, totals, out=np.zeros_like(hits), where=totals > 0)
    weight = np.where(usable, totals, 0.0)
    mass = weight.sum(axis=1)
    out = np.divide((rate * weight).sum(axis=1), mass, out=np.full(len(mass), np.nan), where=mass > 0)
    return out, mass


@dataclass(frozen=True, slots=True)
class Gap:
    n_clear: int
    n_shield: int
    p_clear: float
    p_shield: float
    gap: float
    sd: float

    @property
    def z(self) -> float:
        return self.gap / self.sd if self.sd > 0 else 0.0


def gap_for(rows, mask: np.ndarray, *, draws: int = 400, seed: int = 0, strata: bool = True):
    """Clear minus shielded reach rate. Positive means the level suppressed it."""
    cls = rows.cls[mask]
    keep = cls != OTHER
    if keep.sum() < 60:
        return None
    bucket = (cls[keep] == SHIELD).astype(np.int64)
    stratum = rows.stratum[mask][keep].astype(np.int64)
    if not strata:
        stratum = np.zeros_like(stratum)
    hit = rows.reached[mask][keep]
    hits, totals, keys = _tensor(rows.day[mask][keep], bucket, stratum, hit, 2)
    if totals[:, 0].sum() < 30 or totals[:, 1].sum() < 30:
        return None

    def stat(h, t):
        rate, mass = _within(h.sum(axis=0), t.sum(axis=0))
        if np.isnan(rate).any():
            return None, rate, mass
        return float(rate[0] - rate[1]), rate, mass

    observed, rate, mass = stat(hits, totals)
    if observed is None:
        return None
    rng = np.random.default_rng(seed)
    spread = []
    for _ in range(draws):
        pick = rng.integers(0, len(keys), len(keys))
        got, _, _ = stat(hits[pick], totals[pick])
        if got is not None:
            spread.append(got)
    return Gap(
        n_clear=int(mass[0]),
        n_shield=int(mass[1]),
        p_clear=float(rate[0]),
        p_shield=float(rate[1]),
        gap=observed,
        sd=float(st.pstdev(spread)) if len(spread) > 5 else 0.0,
    )


@dataclass(frozen=True, slots=True)
class Dose:
    n: tuple[int, ...]
    rate: tuple[float, ...]
    slope: float
    sd: float

    @property
    def z(self) -> float:
        return self.slope / self.sd if self.sd > 0 else 0.0

    @property
    def monotone(self) -> bool:
        """Falls at every step over buckets with a usable n.

        Asked separately from the slope because a hump produces a slope too,
        and the grid's shape is what `sweep-thresholds-on-the-mean-not-z`
        says to read.
        """
        got = [r for r, k in zip(self.rate, self.n, strict=True) if k >= 30 and not math.isnan(r)]
        return len(got) >= 3 and all(b <= a for a, b in zip(got, got[1:], strict=False))


def _slope(xs: np.ndarray, ys: np.ndarray, ws: np.ndarray) -> float:
    total = ws.sum()
    if total <= 0:
        return 0.0
    mx = float((ws * xs).sum() / total)
    my = float((ws * ys).sum() / total)
    sxx = float((ws * (xs - mx) ** 2).sum())
    return float((ws * (xs - mx) * (ys - my)).sum() / sxx) if sxx > 0 else 0.0


def dose_for(rows, mask: np.ndarray, *, draws: int = 400, seed: int = 0):
    """Reach rate against levels in the path, within strata; slope per level."""
    blocked = np.minimum(rows.blocked[mask], DOSE[-1]).astype(np.int64)
    if len(blocked) < 200:
        return None
    hits, totals, keys = _tensor(
        rows.day[mask],
        blocked,
        rows.stratum[mask].astype(np.int64),
        rows.reached[mask],
        len(DOSE),
    )
    xs = np.asarray(DOSE, dtype=float)

    def stat(h, t):
        rate, mass = _within(h.sum(axis=0), t.sum(axis=0))
        ok = (mass >= 30) & ~np.isnan(rate)
        if ok.sum() < 3:
            return None, rate, mass
        return _slope(xs[ok], rate[ok], mass[ok]), rate, mass

    observed, rate, mass = stat(hits, totals)
    if observed is None:
        return None
    rng = np.random.default_rng(seed)
    spread = []
    for _ in range(draws):
        pick = rng.integers(0, len(keys), len(keys))
        got, _, _ = stat(hits[pick], totals[pick])
        if got is not None:
            spread.append(got)
    return Dose(
        n=tuple(int(x) for x in mass),
        rate=tuple(float(x) for x in rate),
        slope=observed,
        sd=float(st.pstdev(spread)) if len(spread) > 5 else 0.0,
    )


@dataclass(frozen=True, slots=True)
class Mirror:
    """The within-anchor paired test, skew-corrected.

    `n` is discordant anchors: one side blocked, the other clear. `raw` is
    blocked-minus-clear on those; `skew` is the same quantity's up/down
    asymmetry measured on concordant anchors; `gap` is `-(raw - skew)` so a
    positive number means the level suppressed the move, matching `Gap`.
    """

    n: int
    n_concordant: int
    p_blocked: float
    p_clear: float
    raw: float
    skew: float
    gap: float
    sd: float

    @property
    def z(self) -> float:
        return self.gap / self.sd if self.sd > 0 else 0.0


def mirror_for(walked, distance: int, *, draws: int = 400, seed: int = 0):
    """Pair each anchor against itself: blocked side against clear side.

    The day, the hour, the volatility estimate and the forward window are the
    same bar's, so nothing about the regime can produce the difference. What
    remains is the up/down excursion skew, which is measured on the anchors
    where both sides fall in the same class and subtracted.
    """
    up = walked.up[:, distance] <= walked.horizon
    dn = walked.dn[:, distance] <= walked.horizon
    blocked_up = walked.blocked_up[:, distance] > 0
    blocked_dn = walked.blocked_dn[:, distance] > 0

    up_only = blocked_up & ~blocked_dn
    dn_only = blocked_dn & ~blocked_up
    both = blocked_up & blocked_dn
    neither = ~blocked_up & ~blocked_dn
    if up_only.sum() + dn_only.sum() < 60:
        return None

    day = walked.day
    keys, index = np.unique(day, return_inverse=True)
    nd = len(keys)

    def tally(sel, a, b):
        """Per-day (sum of a-hits, sum of b-hits, count) on `sel`."""
        where = index[sel]
        return (
            np.bincount(where, weights=a[sel].astype(float), minlength=nd),
            np.bincount(where, weights=b[sel].astype(float), minlength=nd),
            np.bincount(where, minlength=nd),
        )

    #: Discordant: the blocked side's outcome against the clear side's, with
    #: the sign of the pair fixed so both orientations contribute the same
    #: quantity rather than cancelling.
    d_up = tally(up_only, up, dn)
    d_dn = tally(dn_only, dn, up)
    #: Concordant anchors give the skew: up minus down where both sides are
    #: in the same class, so the asymmetry is this series' own.
    c_sel = both | neither
    conc = tally(c_sel, up, dn)

    def stat(idx):
        nb = d_up[0][idx].sum() + d_dn[0][idx].sum()
        nc = d_up[1][idx].sum() + d_dn[1][idx].sum()
        k = d_up[2][idx].sum() + d_dn[2][idx].sum()
        if k < 30:
            return None
        p_b, p_c = nb / k, nc / k
        kk = conc[2][idx].sum()
        if kk < 30:
            return None
        skew = conc[0][idx].sum() / kk - conc[1][idx].sum() / kk
        #: The discordant pairs are a mix of up-blocked and down-blocked, so
        #: the skew enters weighted by the imbalance between them, not whole.
        n_u, n_d = d_up[2][idx].sum(), d_dn[2][idx].sum()
        share = (n_u - n_d) / k
        return p_b, p_c, (p_b - p_c), skew * share, k, kk

    whole = np.arange(nd)
    got = stat(whole)
    if got is None:
        return None
    p_b, p_c, raw, skew, k, kk = got
    rng = np.random.default_rng(seed)
    spread = []
    for _ in range(draws):
        pick = rng.integers(0, nd, nd)
        drawn = stat(pick)
        if drawn is not None:
            spread.append(-(drawn[2] - drawn[3]))
    return Mirror(
        n=int(k),
        n_concordant=int(kk),
        p_blocked=float(p_b),
        p_clear=float(p_c),
        raw=float(raw),
        skew=float(skew),
        gap=float(-(raw - skew)),
        sd=float(st.pstdev(spread)) if len(spread) > 5 else 0.0,
    )


def within_strata(rows, mask: np.ndarray, **kw):
    return gap_for(rows, mask, strata=True, **kw)


def benjamini_hochberg(ps: list[float], q: float = 0.10) -> list[bool]:
    """Which p-values survive at FDR `q`, counted over every cell looked at.

    Picking the best of 43 instruments gives a winner every time; on this desk
    18 of 43 were nominally profitable where chance gives 22 and none survived
    this as profitable.
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


def two_sided_p(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2.0))
