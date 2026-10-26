"""Are the members of a family in the same regime at the same time?

A regime model on this desk is fitted per feed, but every pooled statistic
ever reported here has quietly assumed that members of a family share a
regime - that if EURUSD is in a high-volatility state then so is GBPUSD.
`pooled-medians-invert-subgroups` is the standing reason to distrust that:
the pooled answer there agreed with a claim that every subgroup refuted.

So the question is not "what regime is the market in" but **at what
granularity is a regime label a property of the data rather than of the
pooling**. The answer is expected to differ by what the regime is about:

* **Volatility** has a mechanism for being shared. `relationships-are-
  contemporaneous` found vol and tails are large contemporaneously across
  instruments while every lagged measure is null. FX majors all contain USD,
  equities all contain the market. Pooling should be *right* here, and this
  is the quantity the state-space service actually folds - log variance.
* **Drift** has a mechanism only where the family shares a leg. USD rallying
  moves every major the same way, so FX majors should agree on drift too.
  Across families - FX against softs against crypto - there is no such leg,
  and that is where the claim "families can be in different regimes" bites.

## The statistic is pairwise agreement, not a fit

Per timestamp each member carries a two-state label. The statistic is the
mean over member pairs and timestamps of `label_i == label_j`: literally
"are these two in the same regime right now". It is linear in pairs, so it
is comparable across families of different sizes, which a modal-vote share
is not.

Labels are **thresholds, not fitted states**. `definitions-cannot-be-states`
records that a mixture centre left free collapses onto the data; a fitted
two-state HMM would also give labels whose *meaning* differs per instrument,
making cross-sectional agreement uninterpretable. So volatility is labelled
against the instrument's own trailing mean log volatility and drift against
zero - both instrument-free, both causal.

## The null is a rotation, and why not a permutation

Each member's aligned label series is circularly rotated by an independent
random offset. That preserves the member's marginal rate **and its run-length
distribution exactly**, destroying only the cross-sectional alignment, which
is the one thing under test.

A permutation null gets the *level* right and the *spread* badly wrong, which
is the subtler failure. On persistent-but-independent labels a smoke test of
this harness read agreement 0.494 against a rotation null of 0.500 sd 0.0173
and a permutation null of 0.496 sd 0.0023 - the same centre, but a null 7.5x
too narrow, because a permutation treats every bar as an independent draw when
a label that persists for 100 bars contributes one. It would multiply every z
in these tables by about seven. This is `overlapping-windows-inflate-
permutation-nulls` in a different costume, and it is why the null rotates.

Power is shown rather than asserted, per `show-power-before-reporting-a-null`:
a shared regime planted under 15% per-member label noise reads z +19.5 through
this same statistic, and truncating a series leaves every overlapping label
bit-identical, so no label uses a future bar.

## The controls, each named for its property

* **Boom_* / Crash_* / Jump_*** - independent realisations of one generator.
  Same family, same statistical character, **zero shared timing by
  construction**. This is the negative control for cross-sectional regime
  sharing specifically, which is the only property it controls for -
  `a-control-is-only-for-a-named-property`, and the reason it is labelled
  that way here rather than as "synthetic".
* **FX majors** - every member contains USD, so a shared vol *and* drift
  regime is near-guaranteed. Positive control; a harness that misses it is
  broken, in the spirit of `currency-triangles-are-the-positive-control`.
* **Drift_Switch_*** - a planted drift regime per member. Whether the three
  share switch times is unknown here, so it is reported, not assumed.

## What the answer changes

If within-family drift agreement sits at the rotation null while volatility
sits far above it, then a pooled *volatility* regime is sound and a pooled
*drift* regime is not, and the service should fold variance across a family
but never direction. The between-family rows say whether a desk-wide regime
label means anything at all.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pattern_fingerprint import CACHE  # noqa: E402

FRAME = os.environ.get("FRAME", "1h")
WINDOWS = tuple(int(w) for w in os.environ.get("WINDOWS", "24,72,168").split(","))
#: How many bars the volatility threshold averages over. The threshold is a
#: *slow level*, so this wants to be long - but the daily equity cache holds
#: only ~270 bars a name, and `window + BASE + LEAST_TIMES` is the floor for a
#: single usable row. So it is configurable, and a run states what it used
#: rather than a reader having to infer it from an empty table.
BASE = int(os.environ.get("BASE", "500"))
REPS = int(os.environ.get("REPS", "200"))
LEAST_MEMBERS = 3
LEAST_TIMES = int(os.environ.get("LEAST_TIMES", "400"))
SEED = 20261026

FAMILIES: dict[str, tuple[str, ...]] = {
    "fx majors (shared USD leg, SPLIT quote convention)": (
        "EURUSD",
        "GBPUSD",
        "AUDUSD",
        "NZDUSD",
        "USDCAD",
        "USDCHF",
        "USDJPY",
    ),
    "fx crosses (no shared leg)": (
        "EURJPY",
        "GBPJPY",
        "AUDJPY",
        "CHFJPY",
        "EURGBP",
        "EURCHF",
        "EURAUD",
    ),
    "fx emerging": (
        "USDMXN",
        "USDZAR",
        "USDNOK",
        "USDPLN",
        "USDSEK",
        "USDCNH",
    ),
    "equity indices": (
        "Germany_40",
        "France_40",
        "UK_100",
        "Japan_225",
        "Europe_50",
        "Hong_Kong_50",
        "Netherlands_25",
        "Spain_35",
        "Swiss_20",
    ),
    "us mega-cap tech": (
        "AAPL",
        "MSFT",
        "NVDA",
        "GOOGL",
        "META",
        "AMZN",
        "AVGO",
        "ORCL",
    ),
    "us banks": ("JPM", "BAC", "C", "GS", "MS", "USB", "PNC", "TFC"),
    "us utilities": ("DUK", "SO", "D", "AEP", "EXC", "NEE", "ED", "XEL"),
    "us energy": ("CVX", "COP", "EOG", "SLB", "OXY", "FANG", "PSX", "MPC"),
    "softs": ("Cocoa", "CoffeeArab", "CoffeeRobu", "Cotton", "Sugar"),
    "energy futures": ("US_Oil", "UK_Brent_Oil", "NGAS"),
    "crypto": ("BTCUSD", "ETHUSD", "SOLUSD"),
    "boom (negative control: independent realisations)": (
        "Boom_50_Index",
        "Boom_100_Index",
        "Boom_150_Index",
        "Boom_200_Index",
        "Boom_300_Index",
        "Boom_500_Index",
        "Boom_600_Index",
        "Boom_900_Index",
        "Boom_1000_Index",
    ),
    "crash (negative control: independent realisations)": (
        "Crash_50_Index",
        "Crash_100_Index",
        "Crash_150_Index",
        "Crash_200_Index",
        "Crash_300_Index",
        "Crash_500_Index",
        "Crash_600_Index",
        "Crash_900_Index",
        "Crash_1000_Index",
    ),
    "jump (negative control: independent realisations)": (
        "Jump_10_Index",
        "Jump_25_Index",
        "Jump_50_Index",
        "Jump_75_Index",
        "Jump_100_Index",
    ),
    "drift switch (planted drift regime)": (
        "Drift_Switch_Index_10",
        "Drift_Switch_Index_20",
        "Drift_Switch_Index_30",
    ),
    "step (negative control: independent realisations)": (
        "Step_Index",
        "Step_Index_200",
        "Multi_Step_2_Index",
        "Multi_Step_3_Index",
        "Multi_Step_4_Index",
    ),
    # These ship in UP/DOWN pairs, which looked like a known-generator version
    # of the fx majors shape - a shared regime carrying an opposite sign. It is
    # not, and the run said so: both read null on |rho| (-2.3 and +1.2) with a
    # 24-bar label rate of 0.497. **Opposite drift bias is not a shared
    # regime.** Each member is its own realisation, and over 24 bars the
    # planted bias is far below the noise, so the label is a coin flip and
    # there is no common timing for `_abs_rho` to find. They are kept as what
    # they measurably are - more independent realisations - and the cache has
    # no positive control for anti-alignment, so the fx majors reading rests on
    # the planted smoke test in the docstring rather than on a Deriv family.
    "dex up/down (negative control: opposite bias, independent paths)": (
        "DEX_600_UP_Index",
        "DEX_600_DOWN_Index",
        "DEX_900_UP_Index",
        "DEX_900_DOWN_Index",
        "DEX_1500_UP_Index",
        "DEX_1500_DOWN_Index",
    ),
    "skew step up/down (negative control: opposite bias)": (
        "Skew_Step_Index_4_Up",
        "Skew_Step_Index_4_Down",
        "Skew_Step_Index_5_Up",
        "Skew_Step_Index_5_Down",
    ),
    # Deriv's volatility indices carry a **constant nominal** volatility - 10,
    # 25, 75 and so on - so their realised volatility moves only by sampling
    # noise, independently per member. They should read null, which makes them
    # the negative control with the most specific named property in the cache:
    # not "synthetic", but *no common volatility factor*.
    "deriv volatility (negative control: constant nominal vol)": (
        "Volatility_10_Index",
        "Volatility_25_Index",
        "Volatility_50_Index",
        "Volatility_75_Index",
        "Volatility_100_Index",
    ),
    "deriv volatility 1s (negative control: constant nominal vol)": (
        "Volatility_10_1s_Index",
        "Volatility_25_1s_Index",
        "Volatility_50_1s_Index",
        "Volatility_75_1s_Index",
        "Volatility_100_1s_Index",
    ),
    # The one synthetic cell that could legitimately fire. Each pair shares a
    # nominal volatility at two sampling rates, so if Deriv drives the standard
    # and `_1s` variants from one source these agree, and if each is its own
    # realisation they do not. Unknown here, so it is measured, not assumed -
    # and it is the only chance of a synthetic *positive* control for shared
    # volatility, which every other row in this block lacks.
    "deriv volatility pairs (same nominal vol, two sampling rates)": (
        "Volatility_25_Index",
        "Volatility_25_1s_Index",
        "Volatility_75_Index",
        "Volatility_75_1s_Index",
        "Volatility_100_Index",
        "Volatility_100_1s_Index",
    ),
    "precious metals": ("XAUUSD", "XAGUSD", "XPTUSD", "XPDUSD"),
    "us indices": ("Wall_Street_30", "US_Mid_Cap_400", "US_Small_Cap_2000"),
    "range break (synthetic: a range by construction)": (
        "Range_Break_100_Index",
        "Range_Break_200_Index",
        "Spot_Up_-_Volatility_Up_Index",
    ),
}

#: Families generated rather than traded. The **between-synthetic** row is the
#: negative control for the between-traded one: these families share no factor
#: at all, so anything the between-traded row shows has to clear this first.
SYNTHETIC = frozenset(
    name
    for name in FAMILIES
    if any(tag in name for tag in ("control", "planted", "synthetic", "deriv"))
)

#: **Asserted, because inferring the classification from the label failed
#: silently once.** `deriv volatility pairs` carries none of the words above and
#: was counted as a *traded* family, which puts a generated series inside the
#: control the traded row is read against. A contaminated null is not visible in
#: the output, so a family added without a tag stops the run instead of quietly
#: joining the wrong side.
EXPECT_SYNTHETIC = 11
if len(SYNTHETIC) != EXPECT_SYNTHETIC:
    stray = sorted(set(FAMILIES) - SYNTHETIC)
    raise SystemExit(
        f"synthetic families: {len(SYNTHETIC)}, expected {EXPECT_SYNTHETIC}.\n"
        f"counted as traded: {stray}"
    )


def _resolve(name: str) -> Path | None:
    """Find a name's file, allowing the cache's exchange suffixes.

    Equities are cached as `AAPL.OQ.1d.npz` and `JPM.N.1h.npz` while every
    index, pair and synthetic is bare. A bare lookup silently matched none of
    the 523 equities, and the table reported "too few members" for all four
    sectors - a missing row that reads exactly like a measured absence.
    """
    exact = CACHE / f"{name}.{FRAME}.npz"
    if exact.exists():
        return exact
    hits = sorted(CACHE.glob(f"{name}.*.{FRAME}.npz"))
    return hits[0] if hits else None


def _load(name: str) -> dict[str, np.ndarray] | None:
    path = _resolve(name)
    if path is None:
        return None
    with np.load(path) as bundle:
        if not {"time", "close"} <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        time = np.asarray(bundle["time"], dtype=float)[order]
        close = np.asarray(bundle["close"], dtype=float)[order]
    keep = close > 0
    time, close = time[keep], close[keep]
    uniq = np.concatenate(([True], np.diff(time) > 0))
    return {"time": time[uniq], "close": close[uniq]}


def _trailing_mean(values: np.ndarray, span: int) -> np.ndarray:
    """mean of the `span` values strictly before each point, from index span."""
    kernel = np.ones(span, dtype=float) / span
    rolled = np.convolve(values, kernel, mode="valid")
    return rolled[:-1]


def _labels(
    bars: dict[str, np.ndarray], window: int, kind: str
) -> tuple[np.ndarray, np.ndarray] | None:
    """Two-state causal labels, computed on this instrument's own series.

    Returns (times, labels). Computed before any cross-member alignment, so a
    session gap never becomes a one-bar return - `difference-before-aligning`.
    """
    close = bars["close"]
    if len(close) < window + BASE + LEAST_TIMES:
        return None
    ret = np.diff(np.log(close))
    kernel = np.ones(window, dtype=float) / window
    if kind == "vol":
        stat = np.sqrt(np.convolve(ret * ret, kernel, mode="valid"))
    else:
        stat = np.convolve(ret, kernel, mode="valid")
    # stat[i] closes at close index i+window, so it is known at that bar.
    when = bars["time"][window:]
    if len(stat) != len(when):
        return None
    if kind == "vol":
        good = stat > 0
        if not good.all():
            floor = stat[good].min() if good.any() else 1e-12
            stat = np.where(good, stat, floor)
        scored = np.log(stat)
        base = _trailing_mean(scored, BASE)
        labels = (scored[BASE:] > base).astype(np.int8)
    else:
        labels = (stat[BASE:] > 0.0).astype(np.int8)
    return when[BASE:], labels


def _aligned(
    members: dict[str, tuple[np.ndarray, np.ndarray]],
) -> tuple[list[str], np.ndarray, np.ndarray] | None:
    names = sorted(members)
    common = members[names[0]][0]
    for name in names[1:]:
        common = np.intersect1d(common, members[name][0], assume_unique=False)
    if len(common) < LEAST_TIMES:
        return None
    rows = []
    for name in names:
        when, labels = members[name]
        index = np.searchsorted(when, common)
        rows.append(labels[index])
    return names, np.vstack(rows), common


def _agreement(panel: np.ndarray) -> float:
    """Mean over member pairs and timestamps of label_i == label_j."""
    members = panel.shape[0]
    ones = panel.sum(axis=0).astype(float)
    pairs_same = ones * (ones - 1.0) / 2.0
    zeros = members - ones
    pairs_same += zeros * (zeros - 1.0) / 2.0
    total = members * (members - 1) / 2.0
    return float((pairs_same / total).mean())


def _abs_rho(panel: np.ndarray) -> float:
    """Mean |correlation| over member pairs of the labels read as -1/+1.

    Agreement is **directional**, so a family whose members share a regime
    with an inverted sign reads *below* the null rather than above it. The fx
    majors are exactly that: EURUSD and USDJPY both carry USD, so a USD trend
    labels them oppositely and their agreement falls to 9/21 = 0.429 when the
    sharing is perfect. An absolute correlation is blind to that sign, and the
    rotation null absorbs the upward bias the absolute value introduces, so no
    convention table is needed and nothing is fitted.
    """
    members, span = panel.shape
    scored = panel.astype(float) * 2.0 - 1.0
    scored -= scored.mean(axis=1, keepdims=True)
    sd = scored.std(axis=1)
    live = sd > 0
    if live.sum() < 2:
        return float("nan")
    scored = scored[live] / sd[live][:, None]
    grid = scored @ scored.T / span
    upper = np.triu_indices(scored.shape[0], k=1)
    return float(np.abs(grid[upper]).mean())


def _rotated(panel: np.ndarray, rng) -> tuple[float, float, float, float]:
    span = panel.shape[1]
    agree = np.empty(REPS, dtype=float)
    rho = np.empty(REPS, dtype=float)
    for rep in range(REPS):
        spun = np.vstack([np.roll(row, int(rng.integers(span))) for row in panel])
        agree[rep] = _agreement(spun)
        rho[rep] = _abs_rho(spun)
    return (
        float(agree.mean()),
        float(agree.std(ddof=1)),
        float(rho.mean()),
        float(rho.std(ddof=1)),
    )


def main() -> None:
    print(__doc__.split("\n\n")[0])
    print(
        f"\nframe {FRAME}, two-state causal labels, baseline {BASE} bars,\n"
        f"windows {WINDOWS}, at least {LEAST_TIMES} aligned bars a family,\n"
        f"{REPS} independent circular rotations per cell as the null.\n"
    )
    rng = np.random.default_rng(SEED)
    loaded: dict[str, dict[str, np.ndarray]] = {}
    for names in FAMILIES.values():
        for name in names:
            if name not in loaded:
                bars = _load(name)
                if bars is not None:
                    loaded[name] = bars
    print(f"loaded {len(loaded)} instruments at {FRAME}\n")

    for kind in ("vol", "drift"):
        head = "volatility regime" if kind == "vol" else "drift regime"
        for window in WINDOWS:
            print(f"=== {head}, {window}-bar window")
            print(
                f"{'family':52s} {'n':>3s} {'bars':>6s} {'rate':>6s} "
                f"{'agree':>7s} {'rotated':>8s} {'z':>7s} "
                f"{'|rho|':>6s} {'rot':>6s} {'z':>7s}"
            )
            marks: dict[str, tuple[np.ndarray, np.ndarray]] = {}
            for family, names in FAMILIES.items():
                members = {}
                for name in names:
                    if name not in loaded:
                        continue
                    got = _labels(loaded[name], window, kind)
                    if got is not None:
                        members[name] = got
                if len(members) < LEAST_MEMBERS:
                    print(f"{family:52s} {len(members):>3d}  too few members")
                    continue
                packed = _aligned(members)
                if packed is None:
                    print(f"{family:52s} {len(members):>3d}  too few bars")
                    continue
                kept, panel, common = packed
                real = _agreement(panel)
                truth = _abs_rho(panel)
                mean, sd, rmean, rsd = _rotated(panel, rng)
                z = (real - mean) / sd if sd > 0 else float("nan")
                rz = (truth - rmean) / rsd if rsd > 0 else float("nan")
                print(
                    f"{family:52s} {len(kept):>3d} {panel.shape[1]:>6d} "
                    f"{float(panel.mean()):>6.3f} {real:>7.3f} {mean:>8.3f} "
                    f"{z:>7.1f} {truth:>6.3f} {rmean:>6.3f} {rz:>7.1f}"
                )
                marks[family] = (
                    common,
                    (panel.mean(axis=0) > 0.5).astype(np.int8),
                )

            # Between families: each family reduced to its own modal label,
            # then the same statistic across families. This is the row that
            # answers whether a desk-wide regime label means anything.
            traded = {n: p for n, p in marks.items() if n not in SYNTHETIC}
            made = {n: p for n, p in marks.items() if n in SYNTHETIC}
            for scope, group in (
                ("traded families", traded),
                ("synthetic families (neg control)", made),
                ("all families", marks),
            ):
                if len(group) < LEAST_MEMBERS:
                    continue
                packed = _aligned(group)
                if packed is None:
                    print(f"{'between ' + scope:52s}   too few common bars")
                    continue
                kept, panel, _ = packed
                real = _agreement(panel)
                truth = _abs_rho(panel)
                mean, sd, rmean, rsd = _rotated(panel, rng)
                z = (real - mean) / sd if sd > 0 else float("nan")
                rz = (truth - rmean) / rsd if rsd > 0 else float("nan")
                print(
                    f"{'between ' + scope:52s} {len(kept):>3d} "
                    f"{panel.shape[1]:>6d} {float(panel.mean()):>6.3f} "
                    f"{real:>7.3f} {mean:>8.3f} {z:>7.1f} "
                    f"{truth:>6.3f} {rmean:>6.3f} {rz:>7.1f}"
                )
            print()


if __name__ == "__main__":
    main()
