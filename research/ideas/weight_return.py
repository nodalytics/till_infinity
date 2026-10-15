"""Is a level's weight proportional to its return rate, or inversely - on eight level types.

Asked 2026-10-15: *the weight of a level is directly or inverse proportional to
its return rate, and not only for displacement origins, for other types too.*

`levels.Level.strength` is the desk's weight and its most-read number, with
seventeen consumers:

    0.4 * evidence + 0.25 * agreement + 0.2 * recency + 0.15 * breadth

`statespace/interacting.Attention` keeps the same four terms with the weights as
an argument, so they can be fitted instead of chosen - and until now there was
no **outcome** to fit them against. The hold rate is closed
(`statespace-conditional-holds.md`), and sweep depth and push are closed
(`level-shrinkage.md`). The return rate is the one that is not: `fade-to-value`
measures 82% of displacement origins being returned to, and that is a **target
hit rate**, which is exactly the quantity a weight should order if a weight
means anything.

## The confound that decides the whole design

**Return rate is overwhelmingly a function of distance.** A level a quarter of a
sigma away is returned to almost always; one five sigmas away rarely. And three
of the four weight terms move with distance through the same mechanism - a level
price was at recently is both *recent* and *near*. So a raw correlation between
weight and return rate measures distance and nothing else.

Every figure here is therefore computed **inside a distance stratum**, in
sigmas, and the pooled version is printed beside it so the size of the confound
is visible rather than argued. `reversion_origin.py` made exactly this mistake
earlier - scoring `-z * sign(line - price)`, which is large precisely when the
target is far - and read AUC 0.32 to 0.49 for it.

## Eight level types, because one would not answer the question

`swing`, `origin` (displacement), `round`, `pdh`/`pdl`, `pwh`/`pwl`, `dopen`,
`turn` (a momentum turn) and `poc` (the volume mode). The question is whether
the *sign* of the weight-to-return relationship is the same on all of them: a
weight that orders returns on swings and anti-orders them on round numbers is
not measuring level quality, it is measuring whatever those constructions have
in common with distance.

Controls: a distance-matched placebo price for every level, the generated feeds,
and `Range_Break_*` where a level exists by construction.
"""

from __future__ import annotations

import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from till_infinity.structures.statespace.interacting import Attention  # noqa: E402

CACHE = Path.home() / "till_infinity/data/seqlab"
FRAMES = ("1h", "4h")
LIMIT = 40000
#: Bars of history used to discover levels and accumulate their record.
LOOKBACK = 300
#: Decision points per feed. Raised from 220 after the first pass: once distance
#: was controlled at quarter-sigma resolution the surviving differences were
#: +0.03 to +0.05 over placebo, and the placebo arm's own readings wandered from
#: 0.459 to 0.563 - so the measurement had no power at the effect size left in
#: play, and a bigger sample is the only fix.
PER_FEED = 900
#: Bootstrap draws for the error bar on a stratified AUC. Resampling decision
#: points rather than comparisons, because the stratification makes a
#: closed-form AUC standard error awkward and a resample does not care.
BOOTS = 200
#: Planted weight-to-return effects, as the share of a level's return
#: probability that the weight is allowed to explain. The power curve.
PLANTS = (0.0, 0.05, 0.10, 0.20)
#: Horizons for "did price come back", in bars.
HORIZONS = (24, 96)
#: Distance strata in sigmas of one bar. Everything is scored inside one of
#: these, because return rate is mostly distance.
#:
#: **Narrow on purpose.** The first pass used 0-1, 1-2, 2-4, 4-8 and 8+, and
#: that is not fine enough to settle the result: `recency` carried the whole
#: effect, and inside a one-sigma-wide bin a level touched one bar ago is still
#: systematically nearer than one touched fifty bars ago, so the term could be
#: reading residual distance. Quarter-sigma bins to four sigmas remove that
#: room; the coarse version is kept as `WIDE` so the two can be compared.
STRATA = tuple(
    (round(0.25 * i, 2), round(0.25 * (i + 1), 2)) for i in range(16)
) + ((4.0, 6.0), (6.0, 8.0), (8.0, 12.0), (12.0, math.inf))
#: The coarse bins the first pass used, for the comparison.
WIDE = ((0.0, 1.0), (1.0, 2.0), (2.0, 4.0), (4.0, 8.0), (8.0, math.inf))
#: Bars in the **short** volatility window, which is the second thing to
#: condition on and the mechanism the swing result most likely runs through.
#:
#: At a fixed distance, a level touched recently means price covered that
#: distance faster - so `recency` is a volatility proxy, and higher volatility
#: traverses the same distance again more readily. Conditioning on distance
#: alone cannot separate the two. Every figure is therefore scored inside a
#: (distance, volatility ratio) cell, with distance measured in **current**
#: sigmas rather than the 300-bar ones.
SHORT = 24
#: Ratio of short-window to long-window volatility, as bins.
REGIMES = ((0.0, 0.7), (0.7, 1.0), (1.0, 1.4), (1.4, math.inf))
#: A level must be at least this far away to be a question at all.
AWAY = 0.25
JITTER = 0.15
SEED = 20261015
TRADED = (
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "XAUUSD",
    "AUDUSD",
    "USDCAD",
    "USDCHF",
    "NZDUSD",
    "EURJPY",
    "GBPJPY",
    "EURGBP",
    "AUDJPY",
    "EURAUD",
    "CADJPY",
    "XAGUSD",
)
GENERATED = (
    "Volatility_75_Index",
    "Volatility_100_Index",
    "Volatility_25_Index",
    "Step_Index",
    "Step_Index_200",
    "Multi_Step_2_Index",
)
CONTROL = ("Range_Break_100_Index", "Range_Break_200_Index")
GROUPS = (("traded", TRADED), ("generated", GENERATED), ("range-break", CONTROL))
TYPES = ("swing", "origin", "round", "prev_day", "prev_week", "dopen", "turn", "poc")
#: `Attention`'s four terms, named so a per-term table can be printed.
TERMS = ("evidence", "agreement", "recency", "breadth")


def load(name: str, frame: str):
    import numpy as np

    path = CACHE / f"{name}.{frame}.npz"
    if not path.exists():
        return None
    with np.load(path) as bundle:
        need = {"time", "high", "low", "close", "open"}
        if not need <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        got = {k: np.asarray(bundle[k], dtype=float)[order] for k in need}
        # The cache calls it `volume` and it is a **tick count** - median 827 at
        # 15m and 2,544 at 1h on EURUSD. The first version of this read
        # `tick_volume`, which does not exist, and fell back to `ones` - which
        # makes a volume profile a plain mid-price histogram and a tick z-score
        # all-NaN, since a constant has no spread. Raise rather than fall back.
        if "volume" not in bundle:
            raise KeyError(f"no volume in {path.name}")
        got["volume"] = np.asarray(bundle["volume"], dtype=float)[order]
    keep = (got["high"] >= got["low"]) & (got["low"] > 0)
    got = {k: v[keep] for k, v in got.items()}
    if len(got["close"]) < 8000:
        return None
    if len(got["close"]) > LIMIT:
        got = {k: v[-LIMIT:] for k, v in got.items()}
    return got


def nominate(bars, at: int, sigma: float) -> dict[str, float]:
    """One candidate price per level type, from history strictly before `at`.

    Each is a construction the desk or the literature actually uses, and none
    of them looks forward. `statespace-ranging.md` refuted seventeen of these as
    *ways of nominating a price*; that is not the question here, which is
    whether a **weight** orders what a nominated price then does.
    """
    import numpy as np

    window = slice(max(at - LOOKBACK, 0), at)
    highs, lows, closes = bars["high"][window], bars["low"][window], bars["close"][window]
    opens, volume = bars["open"][window], bars["volume"][window]
    times = bars["time"][window]
    if len(closes) < 64 or sigma <= 0:
        return {}
    here = float(bars["close"][at])
    out: dict[str, float] = {}

    # A swing extreme, the construction every other harness here has used.
    out["swing"] = float(highs.max()) if (at // 7) % 2 == 0 else float(lows.min())

    # The displacement origin: the start of the largest directional run in the
    # window, which is what `fade-to-value` targets.
    span = 12
    if len(closes) > span:
        moves = closes[span:] - closes[:-span]
        where = int(np.argmax(np.abs(moves)))
        out["origin"] = float(closes[where])

    # The nearest round number, on the quote grid implied by the price itself.
    step = 10.0 ** (math.floor(math.log10(abs(here))) - 2) if here > 0 else 0.0
    if step > 0:
        out["round"] = float(round(here / (step * 10.0)) * step * 10.0)

    # Previous day and previous week extremes, by timestamp rather than by bar
    # count, so a frame change does not silently change the definition.
    day = 86_400.0
    last = float(times[-1])
    for label, length in (("prev_day", day), ("prev_week", 7 * day)):
        prior = (times >= last - 2 * length) & (times < last - length)
        if prior.sum() >= 4:
            out[label] = (
                float(highs[prior].max())
                if (at // 11) % 2 == 0
                else float(lows[prior].min())
            )
    # The session open: the first bar of the current day.
    today = times >= last - (last % day)
    if today.sum() >= 1:
        out["dopen"] = float(opens[today][0])

    # A momentum turn: where the smoothed slope changed sign most recently.
    if len(closes) > 40:
        smooth = np.convolve(closes, np.ones(8) / 8.0, mode="valid")
        slope = np.diff(smooth)
        flips = np.flatnonzero(np.sign(slope[1:]) != np.sign(slope[:-1]))
        if len(flips):
            out["turn"] = float(smooth[int(flips[-1]) + 1])

    # The volume mode - a point of control over the window, on tick volume.
    if volume.sum() > 0:
        mid = (highs + lows) / 2.0
        edges = np.linspace(float(lows.min()), float(highs.max()), 41)
        if edges[-1] > edges[0]:
            which = np.clip(np.digitize(mid, edges) - 1, 0, len(edges) - 2)
            weight = np.zeros(len(edges) - 1)
            np.add.at(weight, which, volume)
            best = int(np.argmax(weight))
            out["poc"] = float((edges[best] + edges[best + 1]) / 2.0)

    # Only levels price is actually away from are a question.
    return {k: v for k, v in out.items() if abs(v - here) >= AWAY * sigma}


def record(bars, price: float, at: int, sigma: float, half_life_days: float):
    """The level's own history before `at`: touches, their spread, recency, episodes.

    One *episode* is a visit: consecutive bars containing the price count once,
    which is what `levels.py` means by a touch and what stops a level that price
    loitered at for a day reading as twenty pieces of evidence.
    """
    highs, lows = bars["high"], bars["low"]
    times = bars["time"]
    start = max(at - LOOKBACK, 0)
    touched: list[float] = []
    episodes = 0
    last = 0.0
    inside = False
    for i in range(start, at):
        if lows[i] <= price <= highs[i]:
            if not inside:
                episodes += 1
                inside = True
            touched.append(float((highs[i] + lows[i]) / 2.0))
            last = float(times[i])
        else:
            inside = False
    if not touched:
        return None
    spread = statistics.pstdev(touched) if len(touched) > 1 else 0.0
    since = float(times[at]) - last
    return {
        "touches": float(episodes),
        "spread": float(spread),
        "unit": float(sigma),
        "since": max(0.0, since),
        "swings": float(episodes),
        "half_life_days": half_life_days,
    }


def returned(bars, price: float, at: int, horizon: int) -> bool | None:
    """Did price trade at `price` within `horizon` bars after `at`?"""
    highs, lows = bars["high"], bars["low"]
    end = min(at + horizon + 1, len(highs))
    if end <= at + 1:
        return None
    for i in range(at + 1, end):
        if lows[i] <= price <= highs[i]:
            return True
    return False


def auc(scores: list[float], truths: list[bool]) -> float:
    """Tie-aware `P(score | returned > score | not) + 0.5 P(equal)`."""
    import numpy as np

    yes = np.sort(np.asarray([s for s, t in zip(scores, truths, strict=True) if t], dtype=float))
    no = np.sort(
        np.asarray([s for s, t in zip(scores, truths, strict=True) if not t], dtype=float)
    )
    if not len(yes) or not len(no):
        return float("nan")
    left = np.searchsorted(no, yes, side="left")
    right = np.searchsorted(no, yes, side="right")
    return (float(left.sum()) + 0.5 * float((right - left).sum())) / (len(yes) * len(no))


def stratified_auc(rows: list[tuple[int, float, bool]]) -> tuple[float, int]:
    """AUC with every comparison confined to one distance stratum.

    Weighted by each stratum's pair count, which is the only version that can
    be about the level rather than about how far away it is.
    """
    groups: dict[int, list[tuple[float, bool]]] = {}
    for stratum, score, truth in rows:
        groups.setdefault(stratum, []).append((score, truth))
    top, weight, used = 0.0, 0.0, 0
    for found in groups.values():
        scores = [s for s, _ in found]
        truths = [t for _, t in found]
        got = auc(scores, truths)
        if got != got:
            continue
        yes = sum(1 for t in truths if t)
        pairs = float(yes) * float(len(truths) - yes)
        if pairs <= 0:
            continue
        top += got * pairs
        weight += pairs
        used += 1
    return (top / weight if weight > 0 else float("nan")), used


def bootstrap_auc(rows, draws: int, seed: int) -> float:
    """Standard error of a stratified AUC, by resampling decision points.

    The point of the exercise: the first pass reported differences of +0.03 to
    +0.05 with no error bar, and the placebo arm - which must be zero - ranged
    over 0.104 of AUC by itself. A figure without this number cannot be read.
    """
    import numpy as np

    if len(rows) < 50:
        return float("nan")
    rng = np.random.default_rng(seed)
    index = np.arange(len(rows))
    got: list[float] = []
    for _ in range(draws):
        taken = rng.choice(index, size=len(index), replace=True)
        drawn = [rows[int(i)] for i in taken]
        value, _used = stratified_auc(drawn)
        if value == value:
            got.append(value)
    if len(got) < 10:
        return float("nan")
    return float(np.std(got, ddof=1))


def plant(rows, share: float, seed: int):
    """Give the weight a known share of the return probability, and relabel.

    A real weight-to-return effect, planted inside the distance strata so it
    cannot be mistaken for the confound: each row's outcome is redrawn at its
    stratum's own base rate, tilted by where its weight sits.

    **Every share redraws, including zero.** The first version returned the rows
    unchanged at `share` of 0, which put the *real* effect in the first row of
    the power table and planted ones in the rest - so a planted 0.05 read
    **below** the unplanted row and the curve looked broken when it was only
    mislabelled. A share of 0 is now the size check: redrawn with no tilt, it
    must read 0.5.
    """
    import numpy as np

    rng = np.random.default_rng(seed)
    rates: dict[int, list[bool]] = {}
    for row in rows:
        rates.setdefault(row[0], []).append(row[2])
    base = {k: sum(v) / len(v) for k, v in rates.items()}
    weights = sorted(row[1] for row in rows)
    out = []
    for row in rows:
        # Where this weight sits in the pool, in [0, 1].
        rank = float(np.searchsorted(weights, row[1])) / max(1, len(weights) - 1)
        here = base[row[0]]
        tilted = here * (1.0 - share) + share * rank * 2.0 * here
        tilted = min(1.0, max(0.0, tilted))
        out.append((row[0], row[1], bool(rng.random() < tilted), row[3], row[4]))
    return out


def stratum_of(distance: float, sigma: float, bins=STRATA) -> int:
    reach = distance / sigma if sigma > 0 else 0.0
    for index, (low, high) in enumerate(bins):
        if low <= reach < high:
            return index
    return len(bins) - 1


def regime_of(short: float, long: float) -> int:
    """Which volatility-ratio bin this moment sits in."""
    ratio = short / long if long > 0 else 1.0
    for index, (low, high) in enumerate(REGIMES):
        if low <= ratio < high:
            return index
    return len(REGIMES) - 1


def gather(names: tuple[str, ...], frame: str):
    """Scored decision points per level type, for real levels and placebos."""
    import numpy as np

    rng = np.random.default_rng(SEED)
    hours = {"1h": 1.0, "4h": 4.0}.get(frame, 1.0)
    half_life = 14.0
    out: dict[tuple[str, str, int], list[tuple[int, float, bool, tuple]]] = {}
    rates: dict[tuple[str, str], list[bool]] = {}
    for name in names:
        bars = load(name, frame)
        if bars is None:
            continue
        closes = bars["close"]
        steps = np.diff(np.log(closes))
        points = np.linspace(LOOKBACK + 8, len(closes) - max(HORIZONS) - 2, PER_FEED, dtype=int)
        for at in points:
            at = int(at)
            local = steps[max(at - LOOKBACK, 0) : at]
            if len(local) < 64:
                continue
            sigma = float(np.std(local)) * float(closes[at])
            recent = float(np.std(steps[max(at - SHORT, 0) : at])) * float(closes[at])
            if not (sigma > 0) or not (recent > 0):
                continue
            regime = regime_of(recent, sigma)
            found = nominate(bars, at, sigma)
            for kind, price in found.items():
                here = float(closes[at])
                gap = price - here
                scale = 1.0 + float(rng.uniform(-JITTER, JITTER))
                for arm, candidate in (("real", price), ("fake", here + gap * scale)):
                    got = record(bars, candidate, at, sigma, half_life)
                    if got is None:
                        continue
                    weight = Attention().of(**got)
                    terms = Attention().terms(**got)
                    gap_sd = abs(candidate - here)
                    # Distance in **current** sigmas, and the cell carries the
                    # volatility regime too, so neither channel is left open.
                    stratum = stratum_of(gap_sd, recent) * len(REGIMES) + regime
                    coarse = stratum_of(gap_sd, sigma, WIDE)
                    for horizon in HORIZONS:
                        back = returned(bars, candidate, at, horizon)
                        if back is None:
                            continue
                        out.setdefault((arm, kind, horizon), []).append(
                            (stratum, weight, back, terms, coarse)
                        )
                        rates.setdefault((arm, kind), []).append(back)
        _ = hours
    return out, rates


def main() -> None:
    print(
        "Does a level's weight order whether price returns to it?\n"
        f"{LOOKBACK}-bar history, {PER_FEED} decision points per feed, horizons "
        f"{HORIZONS} bars.\n"
        "Every AUC is computed inside a distance stratum in sigmas, because the\n"
        f"return rate is mostly distance. Strata: {[s[0] for s in STRATA]}+\n"
    )
    for frame in FRAMES:
        for group, names in GROUPS:
            rows, rates = gather(names, frame)
            if not rows:
                continue
            print("=" * 104)
            print(f"{frame}  {group}")
            print("=" * 104)
            head = f"  {'type':<11}{'h':>4}{'n':>8}{'rate':>7}{'pooled':>9}{'wide':>9}"
            print(
                head
                + f"{'narrow':>9}{'placebo':>9}{'gap':>9}{'SE':>8}{'z':>7}{'bins':>6}   "
                + "".join(f"{t[:7]:>9}" for t in TERMS)
            )
            for kind in TYPES:
                for horizon in HORIZONS:
                    real = rows.get(("real", kind, horizon))
                    fake = rows.get(("fake", kind, horizon))
                    if not real or len(real) < 200:
                        continue
                    rate = sum(1 for r in real if r[2]) / len(real)
                    pooled = auc([r[1] for r in real], [r[2] for r in real])
                    inside, used = stratified_auc([(r[0], r[1], r[2]) for r in real])
                    coarse, _ = stratified_auc([(r[4], r[1], r[2]) for r in real])
                    shadow = (
                        stratified_auc([(r[0], r[1], r[2]) for r in fake])[0]
                        if fake
                        else float("nan")
                    )
                    per_term = []
                    for index in range(len(TERMS)):
                        got, _ = stratified_auc(
                            [(r[0], r[3][index], r[2]) for r in real]
                        )
                        per_term.append(got)
                    error = bootstrap_auc(
                        [(r[0], r[1], r[2]) for r in real], BOOTS, SEED
                    )
                    gap = inside - shadow
                    print(
                        f"  {kind:<11}{horizon:>4}{len(real):>8,}{rate:>7.3f}{pooled:>9.4f}"
                        f"{coarse:>9.4f}{inside:>9.4f}{shadow:>9.4f}{gap:>+9.4f}"
                        f"{error:>8.4f}{gap / (error * 1.41) if error else float('nan'):>7.2f}"
                        f"{used:>6}   " + "".join(f"{v:>9.4f}" for v in per_term)
                    )
            # The power curve, on the one type with the most decision points.
            best = max(
                (k for k in TYPES if ("real", k, HORIZONS[-1]) in rows),
                key=lambda k: len(rows[("real", k, HORIZONS[-1])]),
                default=None,
            )
            if best is not None:
                real = rows[("real", best, HORIZONS[-1])]
                print(f"\n  power, on {best} at h={HORIZONS[-1]}:")
                print(f"  {'planted':>9}{'narrow':>9}{'SE':>8}{'z vs 0.5':>10}")
                for share in PLANTS:
                    spiked = plant(real, share, SEED + int(share * 1000))
                    value, _ = stratified_auc([(r[0], r[1], r[2]) for r in spiked])
                    error = bootstrap_auc([(r[0], r[1], r[2]) for r in spiked], BOOTS, SEED)
                    print(
                        f"  {share:>9.2f}{value:>9.4f}{error:>8.4f}"
                        f"{(value - 0.5) / error if error else float('nan'):>10.2f}"
                    )
            print(
                "  `rate` is the share returned to. `pooled` ignores distance and is the\n"
                "  confounded figure. `wide` uses one-sigma bins and `narrow` quarter-sigma\n"
                "  ones: if an effect is really residual distance it shrinks between them.\n"
                "  Above 0.5 means a heavier level is returned to **more** often, below\n"
                "  means less. `placebo` is the same weight on a distance-matched price\n"
                "  that is not a level, scored in the narrow bins. `gap` is narrow minus\n"
                "  placebo and `z` is it over the difference's own standard error, which\n"
                "  is the only column that settles anything. The power block says what\n"
                "  size of real effect this sample would have found.\n"
            )


if __name__ == "__main__":
    main()
