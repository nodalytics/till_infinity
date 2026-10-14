"""A wide screen over candles, markets and targets, scored against the obvious predictor.

Asked on 2026-10-14: *go through the different markets and their candles
yourself and see if you can find things too, some help improve statespace by a
lot, hope for an auc above 0.80.*

**Where 0.80 lives, and where it does not.** Direction is closed - six
independent arrivals this session, and the production gate finds a *planted*
drift at z+2.90 and earns two percent of a spread. Nothing there approaches
0.80. Volatility-shaped targets are the opposite problem: `topology.md`
measured range **width** predicting containment at an AUC of 0.74 to 0.84 using
a ruler, so a high absolute AUC is cheap there and means almost nothing. The
number that matters is the AUC **inside strata of the predictor you already
have**, which is what every table below reports beside the raw one.

## What is new here

Four hundred and seventy-two equities sit in the cache and nothing in this
session has touched them. They are a different kind of market - an auction, an
overnight gap, an earnings date - and `gap_share` below is a feature foreign
exchange cannot have at all. If candles carry something, a market with gaps and
a closing auction is where it should show up most clearly.

## How it is scored

Per feed, never pooled across them: this desk has had a pooled median agree with
a claim every subgroup refuted, so each feed gets its own AUC and the family's
number is the **mean of those**, reported beside the share of feeds that agree
in sign. Windows are strided two deep so a window and its own forward window
never appear in another sample. Each feature is also read on a **block-shuffled
copy** of the same feed, and on synthetic families with known generators.

`dir_up` is carried through every table as the control that must read 0.5.
"""

from __future__ import annotations

import math
import os
import re
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from level_signatures import CACHE, FRAME, LIMIT, auc, shuffle_blocks  # noqa: E402

WINDOW = int(os.environ.get("WINDOW", "100"))
#: Two windows of stride, so a sample's forward window is never another
#: sample's own window.
STRIDE = int(os.environ.get("STRIDE", str(2 * WINDOW)))
EQUITIES = int(os.environ.get("EQUITIES", "80"))
#: Strata of the incumbent predictor for the incremental read.
STRATA = int(os.environ.get("STRATA", "10"))
#: Windows a feed needs. At forty with a hundred-bar stride only nine of a
#: hundred and twenty equities qualified - most carry about 1,900 hourly bars,
#: not the 50,000 a foreign exchange series has.
LEAST = int(os.environ.get("LEAST", "20"))
#: Bars a feed needs. The shared loader in `level_signatures` floors at eight
#: thousand, which is right for a 50,000-bar foreign exchange series and throws
#: away **every equity**: AAPL has 5,845 hourly bars and ABBV 1,883, so the
#: four hundred and seventy-two names that make this screen worth running were
#: silently dropped as "nothing read".
ENOUGH = int(os.environ.get("ENOUGH", "1500"))
#: Share of names a date must be held by to enter the cross-sectional panel.
#: At 0.6 across 118 equities only the span of the shortest histories survives.
PRESENT = float(os.environ.get("PRESENT", "0.35"))
#: The cross-section gets its own forward horizon and stride. Inheriting the
#: per-series `WINDOW`/`STRIDE` gave eighteen dates, because a 100-bar stride
#: over the ~1,900 shared dates is a per-series setting applied to a panel -
#: and a cross-sectional study wants many dates at a short horizon. Stride
#: equals the horizon so forward returns never overlap between dates, which is
#: what lets each date count as one draw in the t.
#: Horizons for the cross-section, in bars. A single five-bar read is five
#: **hours** on this frame - far shorter than the horizon short-term reversal
#: operates over, which is about a week, or forty hourly bars.
XAHEADS = tuple(int(k) for k in os.environ.get("XAHEADS", "5,20,40,80").split(","))


def load(name: str, frame: str = ""):
    """Like `level_signatures.load`, with a floor an equity can clear."""
    path = CACHE / f"{name}.{frame or FRAME}.npz"
    if not path.exists():
        return None
    with np.load(path) as bundle:
        need = {"time", "open", "high", "low", "close", "volume", "spread"}
        if not need <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        got = {k: np.asarray(bundle[k], dtype=float)[order] for k in need}
    keep = (
        (got["high"] >= got["low"])
        & (got["low"] > 0)
        & (got["volume"] > 0)
        & np.isfinite(got["close"])
    )
    got = {k: v[keep] for k, v in got.items()}
    if len(got["close"]) < ENOUGH:
        return None
    if len(got["close"]) > LIMIT:
        got = {k: v[-LIMIT:] for k, v in got.items()}
    return got


FEATURES = (
    # Volatility structure: how much of the move happens inside the bar.
    "gk_cc",
    "park_cc",
    "rs_cc",
    "vol_ratio",
    "vol_of_vol",
    # Candles, which is what was asked for.
    "body_share",
    "upper_wick",
    "lower_wick",
    "wick_bias",
    "clv",
    "wick_vol_tie",
    "body_vol_tie",
    "doji_share",
    "run_len",
    "gap_share",
    # Path shape.
    "efficiency",
    "drawdown",
    "autocorr",
    "skew",
    "kurtosis",
    "up_share",
    "past_ret",
    "past_ret_tail",
    # Volume and cost.
    "vol_trend",
    "volume_cv",
    "spread_level",
)
#: Direction at four horizons, because "direction is closed" was measured on a
#: **hundred-bar** forward window, unconditionally. A microstructure effect that
#: lives one bar out is not in that evidence, and nor is anything conditional.
HORIZONS = (1, 5, 20, 100)
#: Three targets that are *not* terminal sign, because terminal sign is the
#: hardest and least relevant version of the question:
#:
#: `first_up` - which barrier arrives first, plus one sigma or minus one sigma.
#: Path-dependent, clock-free, and what a trade actually experiences.
#: `big_up` - direction **given** the move was large. Returns are heavy tailed
#: and the sign of a tail event can be predictable while the bulk is not; an
#: AUC over every window averages the two together.
#: `mfe_gt_mae` - did the favourable excursion beat the adverse one. This is
#: what a position monetises, and it is a magnitude statement, not a sign one.
#:
#: The common thread: an AUC on sign discards magnitude, and this desk already
#: knows the unexplained structure is in the tail shape.
#: One sigma is the typical move, not a tail, so the threshold is swept and
#: each level keeps only the windows whose forward move reached it - making
#: `big_up_3` a question about three-sigma events and nothing else.
TAILS = (1.0, 2.0, 3.0)
EXTRA = ("first_up", "mfe_gt_mae") + tuple(f"big_up_{k:g}" for k in TAILS)
TARGETS = ("vol_up", "vol_high", "held", "band_miss") + tuple(f"dir_{k}" for k in HORIZONS) + EXTRA
DIRECTION = tuple(f"dir_{k}" for k in HORIZONS) + EXTRA
#: The predictor each target already has, with no new idea in it.
INCUMBENT = {
    "vol_up": "now_vol",
    "vol_high": "now_vol",
    "held": "now_width",
    "band_miss": "now_vol",
    **{f"dir_{k}": "now_vol" for k in HORIZONS},
    **dict.fromkeys(EXTRA, "now_vol"),
}
#: Tail share for the conditional read. An AUC is a rank statistic over the
#: whole sample, so a feature that only pays in its extremes reads modest
#: overall and strong where it matters - and that is the shape a tradeable
#: direction edge would have.
TAIL = float(os.environ.get("TAIL", "0.10"))


def families() -> dict[str, list[str]]:
    names = sorted({p.name.split(f".{FRAME}.npz")[0] for p in CACHE.glob(f"*.{FRAME}.npz")})
    synth = re.compile(r"(Volatility|Step|Jump|Boom|Crash|Drift_Switch|Range_Break|Spot_Up)")
    fx = re.compile(r"^(EUR|GBP|USD|AUD|NZD|CAD|CHF|JPY)[A-Z]{3}$")
    out: dict[str, list[str]] = {
        "fx": [],
        "metal": [],
        "equity": [],
        "deriv vol": [],
        "deriv jump": [],
        "deriv structured": [],
    }
    for name in names:
        if name.startswith(("XAU", "XAG")):
            out["metal"].append(name)
        elif fx.match(name):
            out["fx"].append(name)
        elif synth.search(name):
            if name.startswith("Volatility"):
                out["deriv vol"].append(name)
            elif name.startswith(("Boom", "Crash", "Jump")):
                out["deriv jump"].append(name)
            else:
                out["deriv structured"].append(name)
        elif "_Basket" not in name:
            out["equity"].append(name)
    out["equity"] = out["equity"][:: max(len(out["equity"]) // EQUITIES, 1)][:EQUITIES]
    out["deriv vol"] = out["deriv vol"][:12]
    out["deriv jump"] = out["deriv jump"][:12]
    return {k: v for k, v in out.items() if v}


def read(bars, at: int) -> tuple[dict[str, float], dict[str, float], float, float] | None:
    """Every feature of the window ending at `at`, and every forward target."""
    o, h, l_, c = bars["open"], bars["high"], bars["low"], bars["close"]
    v, s = bars["volume"], bars["spread"]
    if at < WINDOW + 2 or at + WINDOW + 1 >= len(c):
        return None
    window = slice(at - WINDOW, at)
    rets = np.diff(np.log(c[at - WINDOW : at + 1]))
    ahead = np.diff(np.log(c[at : at + WINDOW + 1]))
    sd = float(rets.std())
    ranges = h[window] - l_[window]
    bar = np.where(ranges > 0, ranges, np.nan)
    if not (sd > 0) or not np.isfinite(rets).all() or np.isnan(bar).all():
        return None
    top = np.maximum(o[window], c[window])
    bottom = np.minimum(o[window], c[window])
    upper = (h[window] - top) / bar
    lower = (bottom - l_[window]) / bar
    body = np.abs(c[window] - o[window]) / bar
    # Garman-Klass, Parkinson and Rogers-Satchell against close-to-close: each
    # is a ratio of **intrabar** information to the interbar move, so each says
    # how much of the window's variance the candles saw and the closes did not.
    logs = np.log(h[window] / l_[window])
    park = math.sqrt(float(np.nanmean(logs**2)) / (4.0 * math.log(2.0)))
    co = np.log(c[window] / o[window])
    gk = math.sqrt(max(float(np.nanmean(0.5 * logs**2 - (2 * math.log(2) - 1) * co**2)), 0.0))
    rs = math.sqrt(
        max(
            float(
                np.nanmean(
                    np.log(h[window] / c[window]) * np.log(h[window] / o[window])
                    + np.log(l_[window] / c[window]) * np.log(l_[window] / o[window])
                )
            ),
            0.0,
        )
    )
    prior = np.diff(np.log(c[at - 2 * WINDOW : at - WINDOW + 1])) if at >= 2 * WINDOW else rets
    signs = np.sign(rets)
    turns = int(np.count_nonzero(np.diff(signs) != 0))
    heat = v[at - WINDOW + 1 : at + 1]
    standard = (rets - rets.mean()) / sd
    hot = float(np.std(heat)) > 0
    # The overnight gap, which is the thing foreign exchange does not have.
    gaps = np.abs(o[at - WINDOW + 1 : at + 1] - c[at - WINDOW : at]) / np.where(
        ranges > 0, ranges, np.nan
    )
    peak = np.maximum.accumulate(np.cumsum(rets))
    width = float(np.log(h[window].max()) - np.log(l_[window].min()))
    features = {
        "gk_cc": gk / sd,
        "park_cc": park / sd,
        "rs_cc": rs / sd,
        "vol_ratio": sd / float(prior.std()) if float(prior.std()) > 0 else 1.0,
        "vol_of_vol": float(np.nanstd(logs)) / float(np.nanmean(logs)),
        "body_share": float(np.nanmean(body)),
        "upper_wick": float(np.nanmean(upper)),
        "lower_wick": float(np.nanmean(lower)),
        "wick_bias": float(np.nanmean(upper - lower)),
        "clv": float(np.nanmean((2 * c[window] - h[window] - l_[window]) / bar)),
        "wick_vol_tie": float(np.corrcoef(np.nan_to_num(upper + lower), heat)[0, 1])
        if hot
        else 0.0,
        "body_vol_tie": float(np.corrcoef(np.nan_to_num(body), heat)[0, 1]) if hot else 0.0,
        "doji_share": float(np.nanmean(body < 0.1)),
        "run_len": WINDOW / max(turns, 1),
        "gap_share": float(np.nanmean(gaps)),
        "efficiency": abs(float(rets.sum())) / float(np.abs(rets).sum()),
        "drawdown": float((peak - np.cumsum(rets)).max()) / (sd * math.sqrt(WINDOW)),
        "autocorr": float(np.corrcoef(standard[:-1], standard[1:])[0, 1]),
        "skew": float((standard**3).mean()),
        "kurtosis": float((standard**4).mean()) - 3.0,
        "up_share": float((rets > 0).mean()),
        # **The signed past return, which this library did not have.**
        # `up_share` and `efficiency` are unsigned proxies, and for a
        # cross-section the signed return is the canonical feature - short-term
        # reversal is the most replicated equity anomaly there is. Leaving it
        # out meant the cross-sectional arm never carried the one predictor
        # most likely to work.
        "past_ret": float(rets.sum()) / (sd * math.sqrt(WINDOW)),
        "past_ret_tail": float(rets[-max(WINDOW // 5, 1) :].sum())
        / (sd * math.sqrt(max(WINDOW // 5, 1))),
        "vol_trend": float(np.polyfit(np.arange(WINDOW), heat, 1)[0]) / float(heat.mean())
        if float(heat.mean()) > 0
        else 0.0,
        "volume_cv": float(np.std(heat)) / float(heat.mean()) if float(heat.mean()) > 0 else 0.0,
        "spread_level": float(s[window].mean()) / float(np.nanmean(bar)),
    }
    forward = float(ahead.std())
    run = np.cumsum(ahead)
    band = 2.0 * sd * np.sqrt(np.arange(1, len(run) + 1))
    after = slice(at, at + WINDOW)
    targets = {
        "vol_up": float(forward > sd),
        "vol_high": forward,  # turned into a tercile flag per feed below
        "held": float(
            h[after].max() <= h[window].max() + 1e-12
            and l_[after].min() >= l_[window].min() - 1e-12
        ),
        "band_miss": float(np.any(np.abs(run) > band)),
    }
    for step in HORIZONS:
        targets[f"dir_{step}"] = float(run[step - 1] > 0) if len(run) >= step else 0.5
    # Which barrier first, at one window-sigma scaled to the horizon.
    reach = sd * math.sqrt(WINDOW)
    up = np.flatnonzero(run >= reach)
    down = np.flatnonzero(run <= -reach)
    first = (
        float(up[0] < down[0])
        if len(up) and len(down)
        else (1.0 if len(up) else (0.0 if len(down) else 0.5))
    )
    targets["first_up"] = first
    favourable, adverse = float(run.max()), float(-run.min())
    targets["mfe_gt_mae"] = float(favourable > adverse)
    # Defined only where the move reached that tail; elsewhere 0.5, which the
    # caller drops - so each AUC is read on tail windows alone.
    end = float(run[-1])
    for k in TAILS:
        targets[f"big_up_{k:g}"] = float(end > 0) if abs(end) > k * reach else 0.5
    if not all(math.isfinite(x) for x in features.values()):
        return None
    return features, targets, sd, width


def stratified(score: np.ndarray, truth: np.ndarray, by: np.ndarray) -> float:
    """AUC inside strata of the incumbent, pooled by stratum size.

    **The strata count follows the sample.** Fixed at ten it returned `nan` for
    every tail target: a feed holds 22 to 38 two-sigma windows, ten strata leave
    two to four apiece, and the three-per-class floor rejects all of them - so
    the one column that says whether a feature adds anything was blank exactly
    where the question was being asked.
    """
    bins = max(min(STRATA, len(truth) // 20), 2)
    edges = np.quantile(by, np.linspace(0, 1, bins + 1)[1:-1])
    cell = np.clip(np.searchsorted(edges, by), 0, bins - 1)
    total = weight = 0.0
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


def walk(bars) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray], np.ndarray, np.ndarray]:
    rows = []
    for at in range(WINDOW + 2, len(bars["close"]) - WINDOW - 2, STRIDE):
        got = read(bars, at)
        if got is not None:
            rows.append(got)
    if len(rows) < LEAST:
        return {}, {}, np.array([]), np.array([])
    features = {n: np.array([r[0][n] for r in rows]) for n in FEATURES}
    targets = {n: np.array([r[1][n] for r in rows]) for n in TARGETS}
    cut = float(np.quantile(targets["vol_high"], 2 / 3))
    targets["vol_high"] = (targets["vol_high"] > cut).astype(float)
    return (
        features,
        targets,
        np.array([r[2] for r in rows]),
        np.array([r[3] for r in rows]),
    )


def tail_report(group: str, pooled: dict[str, list[tuple[dict[str, float], float]]]) -> None:
    """The tail question, with every feed's events in one pot.

    **Why pooling is not optional here.** Scored per feed, a tail target needs
    eight up and eight down events before that feed counts, and a 1,900-bar
    equity holds a handful of two-sigma moves - so 141 of 146 names were
    discarded and the equity base rate came from five. Pooling is what turns
    110 events into 3,000 and the question from unanswerable into answered.

    The claim being tested is *directional value might also lie in the tails*,
    and it has two parts. The **base rate** is whether large moves lean one way
    at all, which needs no predictor; the **AUC** is whether anything says which
    way, given one is happening.
    """
    print(f"  {group}: tails pooled across feeds")
    print(f"    {'level':<8}{'events':>8}{'up rate':>10}{'z':>8}   best predictors")
    for name, events in pooled.items():
        if len(events) < 60:
            print(f"    {name:<8}{len(events):>8}  too few")
            continue
        up = np.array([u for _, u in events])
        rate = float(up.mean())
        z = (rate - 0.5) / math.sqrt(0.25 / len(up))
        rows = []
        for feature in FEATURES:
            score = np.array([f[feature] for f, _ in events])
            one = auc(score[up > 0.5], score[up < 0.5])
            if math.isfinite(one):
                rows.append((abs(one - 0.5), feature, one))
        rows.sort(reverse=True)
        best = ", ".join(f"{f} {a:.3f}" for _, f, a in rows[:3])
        print(f"    {name:<8}{len(up):>8}{rate:>10.4f}{z:>8.2f}   {best}")
    print(
        "      `z` is a binomial z against 0.5 on the pooled events. An AUC here\n"
        "      is read on tail events alone, so 0.5 means nothing says which\n"
        "      tail even though the level itself may lean.\n"
    )


def screen(group: str, names: list[str], mixed: bool = False) -> None:
    rng = np.random.default_rng(7)
    pooled: dict[str, list[tuple[dict[str, float], float]]] = {f"{k:g}-sigma": [] for k in TAILS}
    got: dict[tuple[str, str], list[float]] = {}
    inner: dict[tuple[str, str], list[float]] = {}
    base: dict[str, list[float]] = {}
    rate: dict[str, list[float]] = {}
    share: dict[str, list[float]] = {}
    tails: dict[tuple[str, str], list[tuple[float, float]]] = {}
    windows = 0
    used = 0
    for name in names:
        bars = load(name)
        if bars is None:
            continue
        if mixed:
            bars = shuffle_blocks(bars, rng)
        features, targets, now_vol, now_width = walk(bars)
        if not features:
            continue
        # Pool every tail event before the per-feed guard can discard its feed.
        for k in TAILS:
            flag = targets[f"big_up_{k:g}"]
            for row in np.flatnonzero(flag != 0.5):
                pooled[f"{k:g}-sigma"].append(
                    ({f: features[f][row] for f in FEATURES}, float(flag[row]))
                )
        used += 1
        windows += len(now_vol)
        dials = {"now_vol": now_vol, "now_width": now_width}
        for target in TARGETS:
            truth = targets[target]
            keep = truth != 0.5
            scored = features
            if not keep.all():
                # `big_up` and `first_up` are undefined where no barrier was
                # reached. A 0.5 is not a class, so those windows leave.
                truth = truth[keep]
                scored = {n: features[n][keep] for n in FEATURES}
            if truth.sum() < 8 or (1 - truth).sum() < 8:
                continue
            rate.setdefault(target, []).append(float(truth.mean()))
            share.setdefault(target, []).append(float(len(truth)))
            dial = dials[INCUMBENT[target]]
            if len(dial) != len(truth):
                dial = dial[keep]
            base.setdefault(target, []).append(auc(dial[truth > 0.5], dial[truth < 0.5]))
            for feature in FEATURES:
                score = scored[feature]
                one = auc(score[truth > 0.5], score[truth < 0.5])
                if math.isfinite(one):
                    got.setdefault((target, feature), []).append(one)
                within = stratified(score, truth, dial)
                if math.isfinite(within):
                    inner.setdefault((target, feature), []).append(within)
                if target in DIRECTION:
                    edge = np.quantile(score, [TAIL, 1.0 - TAIL])
                    low, high = score <= edge[0], score >= edge[1]
                    if low.sum() >= 8 and high.sum() >= 8:
                        tails.setdefault((target, feature), []).append(
                            (float(truth[high].mean()), float(truth[low].mean()))
                        )
    if not got:
        print(f"  {group}: nothing read\n")
        return
    print(f"  {group}: {used} feeds, {windows:,} windows")
    for target in TARGETS:
        rows = [
            (float(np.mean(v)), f, float(np.mean(inner.get((target, f), [float("nan")]))))
            for (t, f), v in got.items()
            if t == target
        ]
        if not rows:
            continue
        rows.sort(key=lambda r: -abs(r[0] - 0.5))
        dial = float(np.mean(base.get(target, [float("nan")])))
        born = float(np.mean(rate.get(target, [float("nan")])))
        kept = float(np.mean(share.get(target, [float("nan")])))
        print(f"    {target:<11} base rate {born:.3f} on {kept:.0f} windows a feed, ")
        for mean, feature, within in rows[:5]:  # noqa: B007
            agree = got[(target, feature)]
            same = sum(1 for a in agree if (a > 0.5) == (mean > 0.5)) / len(agree)
            extra = ""
            if (target, feature) in tails:
                pairs = tails[(target, feature)]
                high = float(np.mean([a for a, _ in pairs]))
                low = float(np.mean([b for _, b in pairs]))
                extra = f"  top {TAIL:.0%} {high:.3f} / bottom {low:.3f}"
            print(
                f"      {feature:<13}{mean:>8.4f}  within {within:>7.4f}  "
                f"sign {same:>5.0%} of {len(agree)}{extra}"
            )
    print()
    tail_report(group, pooled)


def cross_section(names: list[str], ahead_bars: int, mixed: bool = False) -> None:
    """Rank the cross-section, not each series - the framing that was missing.

    Everything else in this file asks each instrument whether its own next move
    is up. That is the weakest form of the question. A cross-section asks which
    **of** four hundred names outruns the others: a relative statement, needing
    no view on the market as a whole, and where direction has historically been
    found when it is found at all.

    The alignment is on **raw bar timestamps**, intersected across names before
    anything is strided. A first version strided each series independently and
    then intersected the sample times, which shared almost nothing because the
    names have different histories - 5,845 hourly bars for AAPL against 1,883
    for ABBV - and reported "0 feeds aligned".

    Scored two ways per date: the AUC of the feature for beating the
    cross-sectional median, and the top-minus-bottom decile return spread in
    units of that date's dispersion, which is what a long-short book earns
    before costs. Names are ranked **within** a date, so a market-wide move
    cannot manufacture a spread.
    """
    rng = np.random.default_rng(11)
    feeds: dict[str, dict] = {}
    for name in names:
        bars = load(name)
        if bars is None:
            continue
        if mixed:
            bars = shuffle_blocks(bars, rng)
        feeds[name] = bars
    if len(feeds) < 20:
        print(f"  cross-section: {len(feeds)} feeds loaded, too few\n")
        return
    # **An unbalanced panel, not an intersection.** Requiring a bar to exist in
    # every name left twelve dates out of 5,845: these are 118 equities with
    # different listing histories and halts, so the intersection is nearly
    # empty. A date qualifies when `PRESENT` of the names have it, and each
    # date is then ranked across whichever names were trading.
    stamps = np.concatenate([bars["time"] for bars in feeds.values()])
    seen, counts = np.unique(stamps, return_counts=True)
    common = seen[counts >= max(int(PRESENT * len(feeds)), 20)]
    if len(common) < 4 * WINDOW:
        print(
            f"  cross-section: {len(common)} dates held by {PRESENT:.0%} of "
            f"{len(feeds)} names, too few\n"
        )
        return
    # Stride the common grid, not each series.
    marks = list(range(WINDOW + 2, len(common) - WINDOW - 2, ahead_bars))
    board = {f: np.full((len(marks), len(feeds)), np.nan) for f in FEATURES}
    forward = np.full((len(marks), len(feeds)), np.nan)
    for column, bars in enumerate(feeds.values()):
        where = np.searchsorted(bars["time"], common)
        where = np.clip(where, 0, len(bars["time"]) - 1)
        # A name need not hold every qualifying date - that is the point of an
        # unbalanced panel - so each date is checked rather than the whole grid.
        holds = bars["time"][where] == common
        closes = bars["close"]
        for row, mark in enumerate(marks):
            if not holds[mark]:
                continue
            at = int(where[mark])
            ahead_mark = min(mark + ahead_bars, len(common) - 1)
            if not holds[ahead_mark]:
                continue
            ahead = int(where[ahead_mark])
            got = read(bars, at)
            if got is None or ahead <= at:
                continue
            for feature in FEATURES:
                board[feature][row, column] = got[0][feature]
            forward[row, column] = math.log(closes[ahead] / closes[at])
    live = int(np.isfinite(forward).any(axis=0).sum())
    print(
        f"  cross-section: {live} names, {len(marks)} dates on a shared grid, {ahead_bars}-bar forward"
    )
    rows = []
    for feature in FEATURES:
        aucs, spreads = [], []
        for row in range(len(marks)):
            score, later = board[feature][row], forward[row]
            ok = np.isfinite(score) & np.isfinite(later)
            if ok.sum() < 20:
                continue
            score, later = score[ok], later[ok]
            spread = float(later.std())
            if not (spread > 0):
                continue
            beat = (later > float(np.median(later))).astype(float)
            if beat.sum() < 5 or (1 - beat).sum() < 5:
                continue
            one = auc(score[beat > 0.5], score[beat < 0.5])
            if math.isfinite(one):
                aucs.append(one)
            edge = np.quantile(score, [0.1, 0.9])
            high, low = score >= edge[1], score <= edge[0]
            if high.sum() >= 2 and low.sum() >= 2:
                spreads.append((float(later[high].mean()) - float(later[low].mean())) / spread)
        if len(aucs) < 20:
            continue
        rows.append((float(np.mean(aucs)), feature, aucs, spreads))
    if not rows:
        print("    nothing scored\n")
        return
    rows.sort(key=lambda r: -abs(r[0] - 0.5))
    print(f"      {'feature':<14}{'AUC':>8}{'t':>8}{'decile spread':>15}{'t':>8}  dates")
    for mean, feature, aucs, spreads in rows[:10]:
        # A t over dates, because once names are ranked within a date each date
        # is one independent draw of the cross-section.
        auc_t = (
            (mean - 0.5) / (float(np.std(aucs)) / math.sqrt(len(aucs)))
            if float(np.std(aucs)) > 0
            else float("nan")
        )
        spread_mean = float(np.mean(spreads)) if spreads else float("nan")
        spread_t = (
            spread_mean / (float(np.std(spreads)) / math.sqrt(len(spreads)))
            if len(spreads) > 2 and float(np.std(spreads)) > 0
            else float("nan")
        )
        print(
            f"      {feature:<14}{mean:>8.4f}{auc_t:>8.2f}{spread_mean:>+15.4f}"
            f"{spread_t:>8.2f}  {len(aucs)}"
        )
    print(
        "      The spread is in units of that date's cross-sectional dispersion,\n"
        "      so it is what a long-short book earns before costs.\n"
    )


def main() -> None:
    print(
        f"{WINDOW}-bar windows, stride {STRIDE}, {len(FEATURES)} features, "
        f"{len(TARGETS)} targets, {STRATA} strata, limit {LIMIT}\n"
        "`within` is the AUC inside strata of the incumbent - the only column\n"
        "that says whether a feature adds anything. For the direction targets\n"
        f"the last column is the up rate in the feature's top and bottom {TAIL:.0%},\n"
        "which is where a conditional edge shows even when the AUC is modest.\n"
    )
    groups = families()
    for group, names in groups.items():
        print("=" * 76)
        print(f"{group} ({len(names)})")
        print("=" * 76)
        screen(group, names)
    if "equity" in groups:
        print("=" * 76)
        print("CROSS-SECTION, which is the framing nothing here has used")
        print("=" * 76)
        cross_section(groups["equity"])
        print("  -- the same, block-shuffled")
        cross_section(groups["equity"], mixed=True)
    print("=" * 76)
    print("block-shuffled controls")
    print("=" * 76)
    for group in ("fx", "equity"):
        if group in groups:
            screen(f"{group}, shuffled", groups[group], mixed=True)


if __name__ == "__main__":
    main()
