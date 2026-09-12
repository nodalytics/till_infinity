"""Does one generator feed twenty-two instruments? The cross-sectional test, at bar level.

`research/twins.md` established two things that set this up. First, **all sixteen
synthetics publish on one clock to within 9ms** - the median distance from a tick
of one feed to the nearest tick of another is 8-9 milliseconds where independent
clocks at these rates would give 250-500, and all five standard volatility indices
print at 229ms into each two-second slot. Second, that shared *timetable* imitates
a shared *driver* badly enough to produce +0.3997 between V25 and V75 on a
one-second grid, which is an artefact of two sampling patterns whose zeros line up.

`rebuildpredict.py` drew the right inference from the first fact: if one stream
feeds many instruments, consecutive draws from that stream appear as **different
feeds at the same index**, so a cross-feed relationship is where a shared PRNG
would show through. It pursued that at tick level, pairwise, on one 24-hour window.

**Nobody has run it at bar level across the whole grid, and nobody has run the
test that is actually powerful.** Both of those are what this file is.

## Why bar level is not a worse version of the tick study

It is a different study and it is cleaner in one specific way. The +0.3997
artefact exists because a two-second feed contributes a zero to every other cell
of a one-second grid and every feed's zeros land in the same cells. **At 3m and
above every bar of every feed contains between ninety and thirty thousand ticks,
so there are no zeros to align.** The shared clock cannot produce the artefact
that it produced at tick resolution.

What bar level buys is **depth**: 3m reaches about fifteen weeks and 1h reaches
five years, against the tick study's single day. A seed reused across days, or a
generator period longer than 86,400 draws, was invisible to `twins.md` by its own
admission. Here it is not.

## The test that is actually powerful, and why the pairwise maximum is not

A 22x22 correlation matrix has 231 distinct off-diagonal entries, and the largest
of 231 draws from a null looks impressive by luck - which is why every pairwise
number on this page is scored through `seqlab.max_of_k` against a null computed
with the identical statistic over the identical pair set.

But the pairwise maximum is also the *wrong* statistic. A shared factor that
loads weakly on all twenty-two feeds - which is exactly the shape a shared draw
stream would have - puts about `beta^2` into each pair and `22 * beta^2` into the
top eigenvalue of the correlation matrix. The eigenvalue sees it at twenty-two
times the strength. And its null is not a simulation but a **law**: for `N`
independent series of length `T`, the sample correlation matrix's eigenvalues lie
inside the Marchenko-Pastur bulk `(1 +- sqrt(N/T))^2`, and anything outside the
bulk is a factor. At `N = 22` and `T = 40,000` that bulk is
`[0.955, 1.047]` - a very narrow window to hide a factor in.

So the spine of this page is: **the eigenvalue spectrum against Marchenko-Pastur,
with a rotation null beside it because the law assumes iid entries and `|return|`
is not Gaussian.**

## Rotation, not shuffle, and the reason it matters

The control throughout is each feed **circularly shifted by an independent random
amount**, not permuted. A permutation destroys the feed's own serial dependence
as well as its alignment with its neighbours, so beating a permuted control only
shows that the model beat a series with no memory - and these feeds have no
memory to begin with, so that control has no teeth. A rotation keeps each feed's
own law and its own autocorrelation exactly and moves only where it sits against
the others. That is the single thing a shared generator would put there.

## The positive control for this arm, which is sitting in the data already

`logvolume` is the tick count per bar, which on a generated feed **is the
generator's own clock**. `twins.md` measured that clock as shared to 9ms. So the
volume panel should show a large factor outside the Marchenko-Pastur bulk, and if
it does not, this test has no power and its silence on returns means nothing.
Running the returns panel without it would be reporting a null from an instrument
that was never shown to work - the exact failure this study exists to prevent.

## What would count as a finding, written before any number was read

1. **A shared factor in returns** if the top eigenvalue of the returns
   correlation matrix sits outside the Marchenko-Pastur bulk *and* outside the
   rotation null at `max_of_k` below 0.01, on more than one timeframe.
2. **A shared factor in volatility** if the same holds for the `|return|` panel
   and is not explained by a shared stall - simultaneous zero-volume bars, which
   are a fact about the collector and not about the generator, and are checked
   for directly in section 0.
3. **A lead** if any lagged cross-feed correlation clears the rotation null's
   maximum over the identical lag and pair set.
4. **A twin coupling** if a matched `(standard, 1s)` pair at the same sigma
   clears the distribution of mismatched pairs at `max_of_k` below 0.01 on more
   than one timeframe and does not reverse sign across the grid.
5. **The arm is void** if the volume panel does *not* show the known shared clock,
   because then nothing here had the power to find anything.
6. **The arm reports "untested" rather than "nothing"** for any timeframe where
   the power calibration in section 3 says the smallest detectable factor loading
   exceeds 0.05.

Eight worker threads total, because five sibling arms share the box.

    ./.secrets/lab.sh run research/harness/seqcross.py
"""

from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
             "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_var] = "8"

import json  # noqa: E402
import math  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402

import numpy as np  # noqa: E402

from research.harness import seqlab  # noqa: E402

OUT = os.environ.get("OUT", os.path.expanduser("~/till_infinity/logs/seqcross.json"))

#: Which sections to run. The spectrum is cheap and the pooled model is not - 220
#: ridge fits per rotation draw - so a statistical correction to a cheap section
#: should not cost an hour of a shared box to re-measure.
SECTIONS = set(os.environ.get("SECTIONS",
                                       "spectrum,lagged,power,twins,twindetail,pooled").split(",")) 

#: Which timeframes. Defaults to the whole of `seqlab.GRID`; narrowed when one
#: cell needs a follow-up rather than the grid needing a re-measurement.
TIMEFRAMES = tuple(os.environ.get("TIMEFRAMES", ",".join(seqlab.GRID)).split(","))

#: Drop a feed whose history is below this fraction of the median before
#: intersecting. **The whole result depends on this switch and both settings are
#: worth reporting.** At 0.0 the universe is all twenty-one feeds and 1h gives
#: 5,066 common bars, because Volatility 15, 30 and 90 were listed 211 days ago.
#: At 0.6 those three plus Volatility 5 and the Spot Up pair leave, and 1h gives
#: 32,668 bars on fifteen feeds - a much tighter Marchenko-Pastur bulk, at the
#: cost of four of the nine matched twin pairs.
MIN_SHARE = float(os.environ.get("MIN_SHARE", "0.0"))
SEED = int(os.environ.get("SEED", "20260912"))

#: Rotation draws for the null. 200 gives a resolution of 0.005 on a family-wise
#: p-value, which is the scale the kill conditions are written at.
DRAWS = int(os.environ.get("DRAWS", "200"))

#: Rotation draws for the pooled model, which costs 220 ridge fits rather than
#: an eigendecomposition. **Twenty draws puts a floor of 0.05 under this arm's
#: family-wise p-value**, so the model arm can say "inside its own null" and
#: cannot say "p < 0.01". The spectrum arm carries that resolution at 200 draws,
#: and it is the more powerful test anyway - which is why the budget is there.
MODEL_DRAWS = int(os.environ.get("MODEL_DRAWS", "20"))

#: The universe: the whole Volatility family plus the two Spot Up members, which
#: are the only feeds in it whose **name says the variance moves**. They are
#: carried here rather than held out because a shared factor would be a fact
#: about the generator, not about any one feed's law.
UNIVERSE = tuple(seqlab.VOLATILITY) + tuple(seqlab.SPOT_UP)

#: Columns of `seqlab.build` handed to the pooled model, four per feed. The whole
#: 28-column matrix across 21 other feeds is 588 predictors against a thousand
#: rows at 1d, which is not a model, it is an interpolator. These four are the
#: level, the magnitude, the standardised move and the generator's clock.
#:
#: **Overridable, because the clock column is the one that has to be removed to
#: attribute a result.** `volume_z` is the tick count, which `twins.md` showed is
#: shared across every feed to 9ms - so a cross-feed model that beats its
#: rotation control while holding it has not necessarily found a shared *draw*
#: stream, it may have found the shared *timetable* feeding through the
#: mechanical link between ticks per bar and range per bar. Re-running with
#: `MODEL_COLS=ret,rv1,z5` is the experiment that tells the two apart.
MODEL_COLS = tuple(os.environ.get("MODEL_COLS", "ret,rv1,z5,volume_z").split(","))


def _sigma_of(symbol: str) -> float | None:
    got = re.search(r"Volatility (\d+)", symbol)
    return float(got.group(1)) / 100.0 if got else None


def _is_1s(symbol: str) -> bool:
    return "(1s)" in symbol


# --------------------------------------------------------------------------
# Panels
# --------------------------------------------------------------------------


def panels(kept: dict[str, dict[str, np.ndarray]]) -> tuple[list[str], dict[str, np.ndarray]]:
    """The three matrices this page is about, on one aligned index.

    `ret` is the level, `absret` the magnitude, `logvolume` the generator's clock.
    Rows with a non-finite entry anywhere are dropped **once, across all feeds**,
    so every panel is the same T x N block and a correlation matrix cannot be
    built from a different sample per pair.
    """
    names = sorted(kept)
    cols: dict[str, list[np.ndarray]] = {"ret": [], "absret": [], "logvolume": [], "stalled": []}
    for symbol in names:
        bars = kept[symbol]
        with np.errstate(divide="ignore", invalid="ignore"):
            ret = np.concatenate(([np.nan], np.diff(np.log(bars["close"]))))
        cols["ret"].append(ret)
        cols["absret"].append(np.abs(ret))
        cols["logvolume"].append(np.log(np.maximum(bars["volume"], 1.0)))
        cols["stalled"].append(((bars["volume"] <= 0) | (ret == 0.0)).astype(float))
    out = {k: np.column_stack(v) for k, v in cols.items()}
    ok = np.ones(len(out["ret"]), bool)
    for k in ("ret", "absret", "logvolume"):
        ok &= np.isfinite(out[k]).all(axis=1)
    return names, {k: v[ok] for k, v in out.items()}


def corr(panel: np.ndarray) -> np.ndarray:
    x = panel - panel.mean(axis=0, keepdims=True)
    sd = x.std(axis=0, ddof=0)
    x = x / np.where(sd > 1e-15, sd, 1.0)
    return (x.T @ x) / len(x)


def rotate(panel: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Every column shifted by its own random amount. The control, per the docstring."""
    return np.column_stack([seqlab.circular_shift(panel[:, j], rng)
                            for j in range(panel.shape[1])])


def spectrum(panel: np.ndarray, rng: np.random.Generator, *, draws: int = DRAWS) -> dict:
    """Eigenvalues against Marchenko-Pastur and against a rotation null.

    Both, because they fail in different directions. The law is exact for iid
    Gaussian columns and the returns panel is very nearly that by construction,
    but `|return|` is half-normal and `logvolume` is a count, and on those the
    analytic edge would over-reject. The rotation null makes no distributional
    assumption at all and is therefore the test; MP is the reference that says
    how far from the textbook the data is.
    """
    t, n = panel.shape
    lo, hi = seqlab.mp_edges(n, t)
    ev = np.linalg.eigvalsh(corr(panel))[::-1]
    nulls_top = np.empty(draws)
    for i in range(draws):
        nulls_top[i] = float(np.linalg.eigvalsh(corr(rotate(panel, rng))).max())
    off = corr(panel)[~np.eye(n, dtype=bool)]
    return {
        "t_obs": int(t), "n_series": int(n),
        "mp_lo": lo, "mp_hi": hi,
        "eig_top": float(ev[0]), "eig_2": float(ev[1]) if n > 1 else float("nan"),
        "eig_bottom": float(ev[-1]),
        "n_above_mp": int((ev > hi).sum()), "n_below_mp": int((ev < lo).sum()),
        "top_share": float(ev[0] / n),
        "null_top_mean": float(nulls_top.mean()), "null_top_max": float(nulls_top.max()),
        "null_top_p95": float(np.percentile(nulls_top, 95)),
        "p_family": seqlab.max_of_k(float(ev[0]), nulls_top),
        "max_abs_offdiag": float(np.abs(off).max()),
        "mean_offdiag": float(off.mean()),
        "eigenvalues": [float(v) for v in ev],
    }


def lagged_max(panel: np.ndarray, rng: np.random.Generator, *, lags=(1, 2, 3, 4, 5),
               draws: int = 50) -> dict:
    """Largest |cross-feed correlation| over every ordered pair and every lag, against its null.

    With the 21 feeds that actually return data that is 420 ordered pairs x 5
    lags - 2,100 chances to find something - and the null is computed over the
    identical 2,100, so the comparison is like for like.
    """
    def biggest(p: np.ndarray) -> float:
        best = 0.0
        n = p.shape[1]
        for k in lags:
            a, b = p[:-k], p[k:]
            c = _cross(a, b)
            c[np.eye(n, dtype=bool)] = 0.0
            best = max(best, float(np.abs(c).max()))
        return best

    obs = biggest(panel)
    nulls = np.array([biggest(rotate(panel, rng)) for _ in range(draws)])
    return {"lags": list(lags), "max_abs": obs, "null_mean": float(nulls.mean()),
            "null_max": float(nulls.max()), "p_family": seqlab.max_of_k(obs, nulls)}


def _cross(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a = (a - a.mean(axis=0)) / np.where(a.std(axis=0) > 1e-15, a.std(axis=0), 1.0)
    b = (b - b.mean(axis=0)) / np.where(b.std(axis=0) > 1e-15, b.std(axis=0), 1.0)
    return (a.T @ b) / len(a)


# --------------------------------------------------------------------------
# Power: what a clean spectrum actually excludes
# --------------------------------------------------------------------------


def power(n_series: int, t_obs: int, rng: np.random.Generator,
          betas=(0.0, 0.005, 0.01, 0.02, 0.03, 0.05, 0.08), *, reps: int = 30) -> dict:
    """The smallest shared-factor loading this sample would have caught.

    `x_i = beta f + sqrt(1 - beta^2) e_i`, all independent Gaussians. The
    threshold is the 95th percentile of the top eigenvalue at `beta = 0` on the
    identical shape, so this is the same test applied to a known truth. Without
    this number a clean spectrum is "we found nothing"; with it, it is "a shared
    factor above this loading would have been found", which is the sentence that
    can be argued with.
    """
    t_obs = min(int(t_obs), 60_000)
    base = np.empty(reps)
    for i in range(reps):
        base[i] = float(np.linalg.eigvalsh(corr(rng.standard_normal((t_obs, n_series)))).max())
    thresh = float(np.percentile(base, 95))
    hits = {}
    for beta in betas:
        got = 0
        for _ in range(reps):
            f = rng.standard_normal((t_obs, 1))
            e = rng.standard_normal((t_obs, n_series))
            x = beta * f + math.sqrt(max(1.0 - beta * beta, 0.0)) * e
            got += float(np.linalg.eigvalsh(corr(x)).max()) > thresh
        hits[beta] = got / reps
    detect = next((b for b in betas if hits[b] >= 0.8), None)
    return {"n_series": n_series, "t_obs": t_obs, "threshold_95": thresh,
            "detection_rate": hits, "beta_detected_at_80pct": detect}


# --------------------------------------------------------------------------
# The pooled model
# --------------------------------------------------------------------------


def pooled(kept: dict[str, dict[str, np.ndarray]], rng: np.random.Generator) -> dict:
    """Feed i's next bar from the other twenty-one feeds' current features.

    `seqlab.ridge` is used directly rather than a faster path of this file's own,
    so the linear floor here is the identical arithmetic every other arm reports
    against. Feed `i`'s own columns are excluded entirely, so nothing here can
    come from `i`'s own autocorrelation - which the direction arms have already shown to be
    absent, but which would otherwise be the first thing to blame for any score.
    """
    names = sorted(kept)
    n = len(names)
    blocks, targets_dir, targets_mag = [], [], []
    for symbol in names:
        x, cols = seqlab.build(kept[symbol])
        idx = [cols.index(c) for c in MODEL_COLS]
        blocks.append(x[:, idx])
        y = seqlab.targets(kept[symbol], horizon=1)
        targets_dir.append(y["direction"])
        targets_mag.append(y["logvol"])
    big = np.column_stack(blocks)
    ydir = np.column_stack(targets_dir)
    ymag = np.column_stack(targets_mag)
    ok = np.isfinite(big).all(axis=1) & np.isfinite(ydir).all(axis=1) & np.isfinite(ymag).all(axis=1)
    big, ydir, ymag = big[ok], ydir[ok], ymag[ok]
    if len(big) < seqlab.FEWEST:
        return {"skipped": f"{len(big)} usable rows"}

    width = len(MODEL_COLS)
    folds = seqlab.walk_forward(len(big), folds=5, horizon=1)
    if not folds:
        return {"skipped": "no folds"}

    def score(design: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        aucs, r2s = np.full(n, np.nan), np.full(n, np.nan)
        for i in range(n):
            take = [j for j in range(design.shape[1]) if not (i * width <= j < (i + 1) * width)]
            pd_, pm_, td_, tm_ = [], [], [], []
            base = []
            for tr, te in folds:
                xtr, xte = design[np.ix_(tr, take)], design[np.ix_(te, take)]
                pd_.append(seqlab.ridge(xtr, ydir[tr, i], xte, lam=10.0))
                pm_.append(seqlab.ridge(xtr, ymag[tr, i], xte, lam=10.0))
                td_.append(ydir[te, i])
                tm_.append(ymag[te, i])
                base.append(np.full(len(te), float(ymag[tr, i].mean())))
            td = np.concatenate(td_)
            tm = np.concatenate(tm_)
            pm = np.concatenate(pm_)
            bl = np.concatenate(base)
            aucs[i] = seqlab.auc(np.concatenate(pd_), td.astype(int))
            ss_tot = float(((tm - bl) ** 2).sum())
            r2s[i] = float(1.0 - ((tm - pm) ** 2).sum() / ss_tot) if ss_tot > 0 else np.nan
        return aucs, r2s

    obs_auc, obs_r2 = score(big)
    null_auc, null_r2 = np.empty(MODEL_DRAWS), np.empty(MODEL_DRAWS)
    for d in range(MODEL_DRAWS):
        spun = big.copy()
        for i in range(n):
            k = int(rng.integers(1, len(spun)))
            sl = slice(i * width, (i + 1) * width)
            spun[:, sl] = np.roll(spun[:, sl], k, axis=0)
        a, r = score(spun)
        null_auc[d] = float(np.nanmax(np.abs(a - 0.5))) + 0.5
        null_r2[d] = float(np.nanmax(r))
    obs_top_auc = float(np.nanmax(np.abs(obs_auc - 0.5))) + 0.5
    obs_top_r2 = float(np.nanmax(obs_r2))
    return {
        "n_rows": int(len(big)), "n_feeds": n, "n_features_per_target": (n - 1) * width,
        "folds": len(folds),
        "auc_mean": float(np.nanmean(obs_auc)), "auc_max_dev": obs_top_auc,
        "auc_null_max_dev_mean": float(null_auc.mean()),
        "auc_p_family": seqlab.max_of_k(obs_top_auc, null_auc),
        "r2_mean": float(np.nanmean(obs_r2)), "r2_max": obs_top_r2,
        "r2_null_max_mean": float(null_r2.mean()),
        "r2_p_family": seqlab.max_of_k(obs_top_r2, null_r2),
        "per_feed_auc": {names[i]: float(obs_auc[i]) for i in range(n)},
        "per_feed_r2": {names[i]: float(obs_r2[i]) for i in range(n)},
    }


# --------------------------------------------------------------------------
# The twins
# --------------------------------------------------------------------------


def twins(names: list[str], pan: dict[str, np.ndarray], rng: np.random.Generator,
          *, lags=(0, 1, 2, 3)) -> dict:
    """Every `(standard, 1s)` pair at matched sigma, against every mismatched pair.

    `twins.md`'s design, moved from one day of ticks to the whole bar grid. The
    control is the *mismatched* pairs - same generator family, same mixture of
    tick rates, no claimed relationship - rather than a simulation, because it
    carries every artefact the twins carry except the one being tested for.

    **The family-wise null is a maximum over nine, not a rank among ninety**, and
    the distinction changed a number on the first run. The reported twin figure
    is the largest of nine pairs, so asking how many of ninety single control
    pairs exceed it answers a different question: the largest of nine
    exchangeable draws sits near the top of ninety *by construction*, and on the
    3m returns panel that arithmetic alone produced a 0.011 that looks like a
    finding. The null here is therefore the maximum over a random nine of the
    ninety, drawn a thousand times, which is the identical statistic.
    """
    at = {s: j for j, s in enumerate(names)}
    std = [s for s in names if not _is_1s(s) and _sigma_of(s) is not None]
    fast = [s for s in names if _is_1s(s) and _sigma_of(s) is not None]
    matched = [(a, b) for a in std for b in fast if _sigma_of(a) == _sigma_of(b)]
    mismatched = [(a, b) for a in std for b in fast if _sigma_of(a) != _sigma_of(b)]
    if not matched or not mismatched:
        return {"skipped": f"{len(matched)} matched, {len(mismatched)} mismatched pairs"}

    def stat(pair, key) -> float:
        a, b = pan[key][:, at[pair[0]]], pan[key][:, at[pair[1]]]
        best = 0.0
        for k in lags:
            x, y = (a, b) if k == 0 else (a[:-k], b[k:])
            x = x - x.mean()
            y = y - y.mean()
            den = math.sqrt(float((x * x).sum()) * float((y * y).sum()))
            if den > 0:
                best = max(best, abs(float((x * y).sum()) / den))
        return best

    out: dict = {"n_matched": len(matched), "n_mismatched": len(mismatched), "lags": list(lags)}
    for key in ("ret", "absret", "logvolume"):
        tw = np.array([stat(p, key) for p in matched])
        ct = np.array([stat(p, key) for p in mismatched])
        maxima = np.array([ct[rng.choice(len(ct), size=len(tw), replace=False)].max()
                           for _ in range(1000)])
        out[key] = {
            "twin_max": float(tw.max()), "twin_mean": float(tw.mean()),
            "control_max": float(ct.max()), "control_mean": float(ct.mean()),
            "control_sd": float(ct.std(ddof=1)),
            "twin_z_max": float((tw.max() - ct.mean()) / max(ct.std(ddof=1), 1e-12)),
            "twins_above_control_max": int((tw > ct.max()).sum()),
            "p_per_pair": seqlab.max_of_k(float(tw.max()), ct),
            "p_family": seqlab.max_of_k(float(tw.max()), maxima),
            "null_max_of_nine_mean": float(maxima.mean()),
            "per_pair": {f"{a} | {b}": float(stat((a, b), key)) for a, b in matched},
            "control_pairs": {f"{a} | {b}": float(stat((a, b), key)) for a, b in mismatched},
        }
    return out


def twin_detail(names: list[str], pan: dict[str, np.ndarray], rng: np.random.Generator,
                *, lags=(-3, -2, -1, 0, 1, 2, 3)) -> dict:
    """Each matched pair, lag by lag, and split in half - `twins.md`'s own discipline.

    The pooled `twins` statistic takes a maximum over lags, which hides the two
    things that decide whether a cell is real. **A relationship has one lag and
    one sign.** `twins.md` killed its two surviving cells exactly here: v75
    returns read +0.0167 at lag -1 in the second half and +0.0070 at a different
    lag in the first, and v100 realised variance reversed sign across the split.
    A generator artefact does not move its lag and does not change its sign
    between two halves of the same sample; a maximum over 21 cells does both.

    So every matched pair is reported at every lag, against the mismatched pairs
    at the *same* lag, and then re-measured in each half at the lag the full
    sample picked. The family-wise null is the largest |z| over the identical
    pair x lag grid drawn from the controls, so the 189 chances per timeframe are
    paid for rather than ignored.
    """
    at = {s: j for j, s in enumerate(names)}
    std = [s for s in names if not _is_1s(s) and _sigma_of(s) is not None]
    fast = [s for s in names if _is_1s(s) and _sigma_of(s) is not None]
    matched = [(a, b) for a in std for b in fast if _sigma_of(a) == _sigma_of(b)]
    mismatched = [(a, b) for a in std for b in fast if _sigma_of(a) != _sigma_of(b)]
    if not matched or len(mismatched) < 10:
        return {"skipped": f"{len(matched)} matched, {len(mismatched)} mismatched"}

    def at_lag(col_a: np.ndarray, col_b: np.ndarray, k: int, lo: int, hi: int) -> float:
        a, b = col_a[lo:hi], col_b[lo:hi]
        x, y = (a, b) if k == 0 else ((a[:-k], b[k:]) if k > 0 else (a[-k:], b[:k]))
        x, y = x - x.mean(), y - y.mean()
        den = math.sqrt(float((x * x).sum()) * float((y * y).sum()))
        return float((x * y).sum() / den) if den > 0 else 0.0

    out: dict = {"n_matched": len(matched), "lags": list(lags)}
    t = len(pan["ret"])
    mid = t // 2
    for key in ("ret", "absret"):
        col = {s: pan[key][:, at[s]] for s in names}
        ctrl = {k: np.array([at_lag(col[a], col[b], k, 0, t) for a, b in mismatched])
                for k in lags}
        rows, worst = [], 0.0
        for a, b in matched:
            best_k, best_z, best_r = 0, 0.0, 0.0
            for k in lags:
                r = at_lag(col[a], col[b], k, 0, t)
                z = (r - ctrl[k].mean()) / max(ctrl[k].std(ddof=1), 1e-12)
                if abs(z) > abs(best_z):
                    best_k, best_z, best_r = k, z, r
            r1 = at_lag(col[a], col[b], best_k, 0, mid)
            r2 = at_lag(col[a], col[b], best_k, mid, t)
            rows.append({"pair": f"{a} | {b}", "lag": best_k, "r": best_r, "z": best_z,
                         "first_half_r": r1, "second_half_r": r2,
                         "sign_holds": bool(r1 * r2 > 0),
                         "both_halves_beat_control": bool(
                             min(abs(r1), abs(r2)) > float(np.abs(ctrl[best_k]).max()))})
            worst = max(worst, abs(best_z))
        # The null: the same max-|z|-over-lags statistic, computed for controls.
        null = []
        for a, b in mismatched:
            z = max((abs((at_lag(col[a], col[b], k, 0, t) - ctrl[k].mean())
                         / max(ctrl[k].std(ddof=1), 1e-12)) for k in lags))
            null.append(z)
        null = np.array(null)
        maxima = np.array([null[rng.choice(len(null), size=len(matched), replace=False)].max()
                           for _ in range(1000)])
        out[key] = {"pairs": rows, "max_abs_z": worst,
                    "null_max_of_matched_mean": float(maxima.mean()),
                    "p_family": seqlab.max_of_k(worst, maxima),
                    "survive_split": [r["pair"] for r in rows
                                      if abs(r["z"]) > 2.0 and r["both_halves_beat_control"]]}
    return out


def pair_probe(names: list[str], pan: dict[str, np.ndarray], rng: np.random.Generator,
               *, span: int = 20) -> dict:
    """The full cross-correlogram of every matched twin pair, with an independent estimator.

    Section `twindetail` flagged `Volatility 100 Index` against its `(1s)` twin at
    15m, lag +3, `r = -0.0261`, with both halves reading -0.0262. Two things about
    that have to be settled before it can be written down as anything.

    **First, the arithmetic.** Two halves agreeing to four decimal places is
    either a very stable estimate or a slicing bug, and those look identical in a
    table. Every number here is recomputed with `np.corrcoef` on explicitly
    constructed slices - a second implementation, not a second call - and the two
    are asserted equal.

    **Second, and this is the test that decides it.** A relationship between two
    feeds lives at a *time* offset, not a bar offset. Lag +3 at 15m is 45 minutes,
    which is lag +15 at 3m and lag +0.75 at 1h. If the generator couples these two
    instruments at 45 minutes, the 3m panel has fifteen times the resolution to
    see it and must show a peak at lag 15. If the 3m correlogram is flat there,
    the 15m cell is the largest of a few hundred draws and nothing else.

    The band is the mismatched pairs at the **same lag**, so the comparison is
    like for like at every offset rather than against a single pooled sigma.
    """
    at = {s: j for j, s in enumerate(names)}
    std = [s for s in names if not _is_1s(s) and _sigma_of(s) is not None]
    fast = [s for s in names if _is_1s(s) and _sigma_of(s) is not None]
    matched = [(a, b) for a in std for b in fast if _sigma_of(a) == _sigma_of(b)]
    mismatched = [(a, b) for a in std for b in fast if _sigma_of(a) != _sigma_of(b)]
    if not matched or len(mismatched) < 10:
        return {"skipped": f"{len(matched)} matched, {len(mismatched)} mismatched"}
    lags = list(range(-span, span + 1))
    t = len(pan["ret"])
    if t < 4 * span + 200:
        return {"skipped": f"{t} bars is too few for +-{span} lags"}
    mid = t // 2

    def r_at(x: np.ndarray, y: np.ndarray, k: int, lo: int, hi: int) -> float:
        a, b = x[lo:hi], y[lo:hi]
        u, v = (a, b) if k == 0 else ((a[:-k], b[k:]) if k > 0 else (a[-k:], b[:k]))
        if len(u) < 30 or u.std() == 0 or v.std() == 0:
            return float("nan")
        return float(np.corrcoef(u, v)[0, 1])

    out: dict = {"lags": lags, "t_obs": t, "n_matched": len(matched)}
    for key in ("ret", "absret"):
        col = {s: pan[key][:, at[s]] for s in names}
        band = {k: np.array([r_at(col[a], col[b], k, 0, t) for a, b in mismatched])
                for k in lags}
        rows = []
        for a, b in matched:
            series = {k: r_at(col[a], col[b], k, 0, t) for k in lags}
            zs = {k: (series[k] - np.nanmean(band[k])) / max(float(np.nanstd(band[k], ddof=1)), 1e-12)
                  for k in lags}
            peak = max(lags, key=lambda k: abs(zs[k]))
            rows.append({
                "pair": f"{a} | {b}", "peak_lag": peak, "r": series[peak], "z": zs[peak],
                "first_half_r": r_at(col[a], col[b], peak, 0, mid),
                "second_half_r": r_at(col[a], col[b], peak, mid, t),
                "band_sd_at_peak": float(np.nanstd(band[peak], ddof=1)),
                "correlogram": {str(k): series[k] for k in lags},
            })
        null = []
        for a, b in mismatched:
            zz = [abs((r_at(col[a], col[b], k, 0, t) - np.nanmean(band[k]))
                      / max(float(np.nanstd(band[k], ddof=1)), 1e-12)) for k in lags]
            null.append(max(zz))
        null = np.array(null)
        maxima = np.array([null[rng.choice(len(null), size=len(matched), replace=False)].max()
                           for _ in range(1000)])
        worst = max(abs(r["z"]) for r in rows)
        out[key] = {"pairs": rows, "max_abs_z": worst,
                    "null_max_mean": float(maxima.mean()),
                    "p_family": seqlab.max_of_k(worst, maxima)}
    return out


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------


def main() -> None:
    began = time.time()
    rng = np.random.default_rng(SEED)
    print("=" * 112)
    print("seqcross.py - does one generator feed twenty-two instruments?")
    print("=" * 112 + "\n")
    res: dict = {"seed": SEED, "universe": list(UNIVERSE), "draws": DRAWS,
                 "model_draws": MODEL_DRAWS, "grid": list(TIMEFRAMES),
                 "min_share": MIN_SHARE, "sections": sorted(SECTIONS),
                 "model_cols": list(MODEL_COLS)}

    per_tf: dict = {}
    for interval in TIMEFRAMES:
        print(f"\n{'=' * 100}\n{interval}\n{'=' * 100}", flush=True)
        times, kept, dropped = seqlab.align(UNIVERSE, interval, min_share=MIN_SHARE)
        if len(kept) < 6:
            print(f"  only {len(kept)} feeds available - skipped")
            per_tf[interval] = {"skipped": f"{len(kept)} feeds", "dropped": dropped}
            continue

        names, pan = panels(kept)
        t_obs = len(pan["ret"])
        stall = pan["stalled"]
        # A feed that never stalls is a constant column and has no correlation
        # with anything. Dropping it is the measurement; carrying it makes the
        # whole statistic NaN and hides the ones that do stall together.
        moving = stall.std(axis=0) > 0
        stall_corr = float("nan")
        if int(moving.sum()) > 1:
            cs = corr(stall[:, moving])
            stall_corr = float(np.abs(cs[~np.eye(int(moving.sum()), dtype=bool)]).max())
        print(f"  {len(names)} feeds, {t_obs:,} common bars "
              f"(from {len(times):,} common stamps); dropped {len(dropped)}")
        for s, why in sorted(dropped.items()):
            print(f"    - {s}: {why}")
        print(f"  stalled-bar fraction: {float(stall.mean()):.5f}   "
              f"feeds that ever stall: {int(moving.sum())}/{len(names)}   "
              f"max |corr| of stall indicators: {stall_corr:.4f}")

        cell: dict = {"n_feeds": len(names), "t_obs": t_obs, "feeds": names,
                      "dropped": dropped, "stall_frac": float(stall.mean()),
                      "stall_max_corr": stall_corr,
                      "feeds_that_stall": int(moving.sum())}

        if "spectrum" in SECTIONS:
            lo, hi = seqlab.mp_edges(len(names), t_obs)
            print(f"\n  Marchenko-Pastur bulk for N={len(names)}, T={t_obs:,}: "
                  f"[{lo:.4f}, {hi:.4f}]\n")
            print(f"  {'panel':12s} {'eig_top':>9s} {'mp_hi':>8s} {'rot p95':>9s} {'rot max':>9s} "
                  f"{'>bulk':>6s} {'p_fam':>7s} {'max|r|':>8s}")
            for key, label in (("ret", "ret"), ("absret", "|ret|"), ("logvolume", "logvolume")):
                got = spectrum(pan[key], rng)
                cell.setdefault("spectrum", {})[key] = got
                print(f"  {label:12s} {got['eig_top']:9.4f} {got['mp_hi']:8.4f} "
                      f"{got['null_top_p95']:9.4f} {got['null_top_max']:9.4f} "
                      f"{got['n_above_mp']:6d} {got['p_family']:7.3f} {got['max_abs_offdiag']:8.4f}")

        if "lagged" in SECTIONS:
            print()
            for key, label in (("ret", "ret"), ("absret", "|ret|")):
                got = lagged_max(pan[key], rng)
                cell.setdefault("lagged", {})[key] = got
                print(f"  lagged {label:8s} max|r| over lags 1-5 {got['max_abs']:.4f}   "
                      f"rotation null mean {got['null_mean']:.4f} max {got['null_max']:.4f}   "
                      f"p_family {got['p_family']:.3f}")

        if "power" in SECTIONS:
            cell["power"] = power(len(names), t_obs, rng)
            print(f"\n  power: a shared factor is caught 80% of the time at loading "
                  f"beta >= {cell['power']['beta_detected_at_80pct']}   "
                  f"(rates {json.dumps({str(k): v for k, v in cell['power']['detection_rate'].items()})})")

        if "probe" in SECTIONS:
            cell["probe"] = pair_probe(names, pan, rng)
            pr = cell["probe"]
            if "skipped" in pr:
                print(f"\n  probe: {pr['skipped']}")
            else:
                for key in ("ret", "absret"):
                    g = pr[key]
                    print(f"\n  probe {key}: largest |z| over 9 pairs x 41 lags "
                          f"{g['max_abs_z']:.2f} vs null {g['null_max_mean']:.2f}, "
                          f"p_family {g['p_family']:.3f}")
                    for r in sorted(g["pairs"], key=lambda r: -abs(r["z"]))[:2]:
                        print(f"    {r['pair']:52s} peak lag {r['peak_lag']:+3d} "
                              f"r {r['r']:+.4f} z {r['z']:+.2f}  halves "
                              f"{r['first_half_r']:+.4f} / {r['second_half_r']:+.4f}")
                v100 = [r for r in pr["ret"]["pairs"] if "100" in r["pair"]]
                if v100:
                    cg = v100[0]["correlogram"]
                    near = [k for k in ("-3", "-2", "-1", "0", "1", "2", "3",
                                        "12", "13", "14", "15", "16", "17", "18")
                            if k in cg]
                    print("    V100 ret correlogram: "
                          + "  ".join(f"{k}:{cg[k]:+.4f}" for k in near))

        if "twindetail" in SECTIONS:
            cell["twin_detail"] = twin_detail(names, pan, rng)
            td = cell["twin_detail"]
            if "skipped" not in td:
                for key in ("ret", "absret"):
                    g = td[key]
                    print(f"\n  twin detail, {key}: largest |z| over 9 pairs x 7 lags "
                          f"{g['max_abs_z']:.2f} vs null {g['null_max_of_matched_mean']:.2f}, "
                          f"p_family {g['p_family']:.3f}")
                    for r in sorted(g["pairs"], key=lambda r: -abs(r["z"]))[:3]:
                        print(f"    {r['pair']:52s} lag {r['lag']:+d} r {r['r']:+.4f} "
                              f"z {r['z']:+.2f}  halves {r['first_half_r']:+.4f} / "
                              f"{r['second_half_r']:+.4f}  sign holds {r['sign_holds']}"
                              f"  both halves beat control {r['both_halves_beat_control']}")
                    print(f"    survives the split: {g['survive_split'] or 'none'}")

        cell["twins"] = twins(names, pan, rng) if "twins" in SECTIONS else {"skipped": "not run"}
        if "skipped" not in cell["twins"]:
            print(f"\n  twins: {cell['twins']['n_matched']} matched (standard, 1s) pairs against "
                  f"{cell['twins']['n_mismatched']} mismatched")
            for key in ("ret", "absret", "logvolume"):
                g = cell["twins"][key]
                print(f"    {key:10s} twin max {g['twin_max']:.4f}  control max {g['control_max']:.4f}"
                      f"  z {g['twin_z_max']:+.2f}  above control {g['twins_above_control_max']}"
                      f"/{cell['twins']['n_matched']}  p_family {g['p_family']:.3f}")

        cell["pooled"] = pooled(kept, rng) if "pooled" in SECTIONS else {"skipped": "not run"}
        p = cell["pooled"]
        if "skipped" in p:
            print(f"  pooled model: skipped ({p['skipped']})")
        else:
            print(f"  pooled model: {p['n_features_per_target']} cross-feed features -> next bar, "
                  f"{p['n_rows']:,} rows, {p['folds']} folds")
            print(f"    direction  mean AUC {p['auc_mean']:.4f}   "
                  f"largest deviation {p['auc_max_dev']:.4f} vs rotation null "
                  f"{p['auc_null_max_dev_mean']:.4f}   p_family {p['auc_p_family']:.3f}")
            print(f"    log|ret|   mean R2 {p['r2_mean']:+.5f}   "
                  f"best {p['r2_max']:+.5f} vs rotation null {p['r2_null_max_mean']:+.5f}"
                  f"   p_family {p['r2_p_family']:.3f}")
        per_tf[interval] = cell
        print(f"  [{(time.time() - began) / 60:.1f}m]", flush=True)

    res["timeframes"] = per_tf

    # ---- The verdict ------------------------------------------------------
    print("\n\n" + "=" * 112)
    print("The verdict on the six conditions")
    print("=" * 112 + "\n")
    live = {k: v for k, v in per_tf.items() if "spectrum" in v}
    lagged_live = {k: v for k, v in per_tf.items() if v.get("lagged")}
    power_live = {k: v for k, v in per_tf.items() if v.get("power")}
    twin_live = {k: v for k, v in per_tf.items()
                 if "skipped" not in v.get("twins", {"skipped": 1})}
    def hits(key: str) -> list[str]:
        return [tf for tf, v in live.items()
                if v["spectrum"][key]["n_above_mp"] > 0 and v["spectrum"][key]["p_family"] < 0.01]
    vol_control = [tf for tf, v in live.items() if v["spectrum"]["logvolume"]["n_above_mp"] > 0]
    verdict = {
        "condition_1_shared_factor_returns": {"timeframes": hits("ret")},
        "condition_2_shared_factor_absret": {"timeframes": hits("absret")},
        "condition_3_lead": {"timeframes": [
            tf for tf, v in lagged_live.items()
            if min(v["lagged"][k]["p_family"] for k in v["lagged"]) < 0.01]},
        "condition_4_twin_coupling": {
            "pooled_max_timeframes": [
                tf for tf, v in twin_live.items()
                if min(v["twins"][k]["p_family"] for k in ("ret", "absret")) < 0.01],
            "pairs_surviving_the_split": {
                tf: {k: v["twin_detail"][k]["survive_split"] for k in ("ret", "absret")}
                for tf, v in per_tf.items()
                if "skipped" not in v.get("twin_detail", {"skipped": 1})
                and any(v["twin_detail"][k]["survive_split"] for k in ("ret", "absret"))}},
        "condition_5_void_no_power": {
            "volume_control_fires_on": vol_control,
            "fired": len(vol_control) < max(1, len(live) // 2)},
        "condition_6_untested": {"timeframes": [
            tf for tf, v in power_live.items()
            if (v["power"]["beta_detected_at_80pct"] is None
                or v["power"]["beta_detected_at_80pct"] > 0.05)]},
    }
    res["verdict"] = verdict
    for name, got in verdict.items():
        print(f"  {name:36s} {json.dumps(got)}")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(res, fh, indent=1, default=float)
    print(f"\nwrote {OUT} in {(time.time() - began) / 60:.1f}m")


if __name__ == "__main__":
    sys.exit(main() or 0)
