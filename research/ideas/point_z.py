"""Point Z's three structural criteria, with the 0.86 swept.

`statespace-displacement-sequences.md` left this as the last untested item in
the reversal family, and said why it was left: Point Z's depth constraint
rests on **the same 0.86 that measured at 0.99**, so the threshold is the
first thing that has to be swept, and *a lone threshold that works at one
value and nowhere else is a fit rather than a finding*.

The claim. Point Z is where a downtrend reverses, valid only if all three hold:

1. **Three consecutive lower lows** - `Low[t] < Low[t-1] < Low[t-2] < Low[t-3]`,
   to confirm a genuine downtrend rather than noise.
2. **At least two buyer interventions** - two local maxima between the first
   and last of those lows, read as failed rally attempts.
3. **A depth constraint** - `Z < 0.86 (H - L) + L`, where `H` and `L` bound the
   previous uptrend. A reversal is only valid once the correction has exceeded
   "the typical 86% retracement".

## What is being tested, and what the right null is

Not "does price sometimes rise after a low". **Does each criterion add
anything over the others, and does the 0.86 do anything that 0.5 or 0.95 does
not?**

The null that matters is a **random walk run through the same detector**. The
lesson from the rest of this family is explicit: every claim in it reduced to
the pivot detector's own alternation, the arithmetic of a ratio of consecutive
terms, or volatility clustering. Three consecutive lower lows and two local
maxima between them are *definitions over an alternating sequence produced by
a thresholded detector*, and such a sequence has strong structure of its own.
So the walk gets the identical pipeline - same `nodes()`, same `span`, same
criteria, same forward measurement - and the gap between market and walk is
the only result.

Three further controls:

* **The Deriv synthetics**, whose generators are known: `Volatility_*` has no
  structure to find, and `Drift_Switch_Index_*` has a genuinely switching
  drift, so a criterion that fires usefully there is reading drift.
* **Matched duty cycle.** A criterion that fires rarely changes the average
  without knowing anything, so each combination is scored against random
  selection of the same number of bars - the control that disposed of every
  pause rule this desk has tested.
* **Cost.** The forward move is reported in spread units as well as sigma,
  because every directional result here so far loses exactly the spread.

## The sweep is the point

The depth threshold runs 0.50 to 1.20 in sixteen steps - deliberately past
1.0, since a "retracement" deeper than the whole prior move is a break rather
than a pullback and there is no reason to assume the useful boundary is
inside. If the forward edge is flat in the threshold, the 0.86 is decoration.
If it peaks at 0.86 and nowhere else, that is a fit. **Only a monotone or
broad-plateau response would be a finding**, and the shape is printed rather
than summarised so it can be read directly.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import random
import statistics
from pathlib import Path

from till_infinity.structures.statespace.displacements import PEAK, TROUGH, nodes

HOUR = 3600.0
SEED = 20261012

TRADED = ("EURUSD", "GBPUSD", "USDJPY", "USDCHF", "XAUUSD", "XAGUSD", "BTCUSD", "ETHUSD")
GENERATED = ("Volatility_75_Index", "Volatility_25_Index", "Drift_Switch_Index_20", "Step_Index")
FRAMES = tuple(os.environ.get("FRAMES", "1h,4h").split(","))
#: Confirmation reach in bars. **`2` is the literal Bill Williams fractal** -
#: an extreme with two lower highs (or higher lows) on each side - so it is in
#: the grid rather than only the larger spans, and the question of whether the
#: detector choice is what killed this is answered rather than assumed.
SPANS = tuple(int(s) for s in os.environ.get("SPANS", "2,3,8").split(","))
#: Depth is a **retracement fraction, so its domain is 0 to 1** and the sweep
#: has to cover it.
#:
#: **The first version of this swept 0.50 to 1.20 and therefore never tested
#: the paper's own threshold.** `Z < 0.86 (H - L) + L` means Point Z sits below
#: 86% of the way up the prior move, which is a retracement of **more than
#: 0.14** - not 0.86. Reading the constraint as a depth of 0.86 inverted it,
#: and the grid started three times above the value being replicated.
#:
#: Two rungs past 1.0 are kept because a retracement deeper than the move it
#: retraces is a break rather than a pullback, and the decline there is worth
#: seeing - but they are outside the claim's domain and the adaptive schemes
#: are clamped to `[0, 1]`.
DEPTHS = tuple(round(0.05 * i, 2) for i in range(1, 23))
#: The paper's actual constraint, for the column that matters.
CLAIMED_DEPTH = 0.14
#: How far ahead the reversal is given to work, in nodes rather than bars: the
#: claim is structural, so the test is whether the *next peak* exceeds the one
#: before Point Z, not whether price is up in twenty bars.
AHEAD = int(os.environ.get("AHEAD", "40"))
SINCE = float(os.environ.get("SINCE", "99792000"))
LIMIT = int(os.environ.get("LIMIT", "60000"))
CACHE = Path.home() / "till_infinity" / "data" / "seqlab"


def load(name: str, frame: str):
    import numpy as np

    path = CACHE / f"{name}.{frame}.npz"
    if not path.exists():
        return None
    with np.load(path) as bundle:
        if not {"time", "close", "high", "low"} <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        got = {
            k: np.asarray(bundle[k], dtype=float)[order] for k in ("time", "close", "high", "low")
        }
        got["spread"] = (
            np.asarray(bundle["spread"], dtype=float)[order]
            if "spread" in bundle
            else np.zeros_like(got["close"])
        )
    keep = (got["close"] > 0) & (got["time"] >= SINCE)
    got = {k: v[keep] for k, v in got.items()}
    if len(got["time"]) > LIMIT:
        got = {k: v[-LIMIT:] for k, v in got.items()}
    return got if len(got["time"]) > 2000 else None


def walk_like(series):
    """A random walk with the same length, scale and starting price.

    Gaussian increments at the series' own standard deviation, with highs and
    lows built from the same intra-bar range the real series had - so the
    **detector sees bars of the same shape** and the comparison is of ordering
    rather than of bar geometry. Without that the walk's nodes would be
    detected at a different rate and every count would differ for the wrong
    reason.
    """
    import numpy as np

    rng = np.random.default_rng(SEED)
    closes = series["close"]
    moves = np.diff(np.log(closes))
    scale = float(np.std(moves))
    fake = float(closes[0]) * np.exp(np.cumsum(rng.normal(0.0, scale, len(closes))))
    # Reuse each bar's own high-low reach as a fraction of its close.
    up = (series["high"] - closes) / closes
    down = (closes - series["low"]) / closes
    order = rng.permutation(len(closes))
    return {
        "time": series["time"],
        "close": fake,
        "high": fake * (1.0 + up[order]),
        "low": fake * (1.0 - down[order]),
        "spread": series["spread"],
    }


def candidates(series, span: int, side: int = TROUGH):
    """Every trough that satisfies criteria 1 and 2, with its depth.

    Returns one row per candidate: the counts that criteria 1 and 2 ask for,
    the retracement depth criterion 3 thresholds, and what happened next.

    `depth` is `(H - Z) / (H - L)` where `H` is the prior uptrend's high and
    `L` the low before it started - so the paper's `Z < 0.86 (H - L) + L`
    becomes `depth > 0.14`. **Reported as the retracement rather than the
    level**, because the level is not comparable across instruments and the
    paper's inequality quietly is.
    """
    found = nodes(series["time"], series["close"], series["high"], series["low"], span=span)
    if len(found) < 8:
        return []

    # `side` makes the whole thing mirrorable. `TROUGH` is the paper's stated
    # case - a downtrend reversing up - and `PEAK` is the same claim turned
    # over: three consecutive *higher highs*, at least two local minima
    # between them, and a rise that has exceeded the prior downtrend's depth.
    #
    # **Running both separates two explanations that look alike on one side.**
    # If the criteria fail because they select for continuation, they must
    # fail on both. If they fail only on troughs, the effect is a directional
    # bias - these series have an upward drift - and not the definition.
    other = PEAK if side == TROUGH else TROUGH
    beats = (lambda a, b: a > b) if side == TROUGH else (lambda a, b: a < b)
    extends = (lambda a, b: a < b) if side == TROUGH else (lambda a, b: a > b)

    rows = []
    for i, node in enumerate(found):
        if node.kind != side or i < 4 or i + 2 >= len(found):
            continue
        # Criterion 1: three consecutive lower lows (or higher highs).
        same = [n for n in found[: i + 1] if n.kind == side][-4:]
        if len(same) < 4:
            continue
        lower = sum(
            1 for a, b in zip(same[:-1], same[1:], strict=True) if extends(b.level, a.level)
        )
        # Criterion 2: opposite-kind nodes strictly between the first and last.
        between = [n for n in found if n.kind == other and same[0].index < n.index < node.index]
        # Criterion 3: the retracement, against the move that preceded it.
        prior = [n for n in found[: i + 1] if n.kind == other]
        if not prior:
            continue
        high = prior[-1]
        before = [n for n in found[: high.index + 1] if n.kind == side and n.index < high.index]
        if not before:
            continue
        low = before[-1]
        reach = abs(high.level - low.level)
        if reach <= 0:
            continue
        depth = abs(high.level - node.level) / reach

        # What happened next, structurally: does the next opposite-kind node
        # get past the one before Point Z?
        ahead = found[i + 1 : i + 1 + 4]
        opposite = [n for n in ahead if n.kind == other]
        if not opposite:
            continue
        nxt = opposite[0]
        if nxt.index - node.index > AHEAD:
            continue
        # Causal: the window of moves that ended at this node and nothing after.
        back = max(node.index - 128, 1)
        moves = [
            math.log(series["close"][k] / series["close"][k - 1])
            for k in range(back, node.index + 1)
            if series["close"][k] > 0 and series["close"][k - 1] > 0
        ]
        rows.append(
            {
                "index": node.index,
                "hurst": local_hurst(moves),
                "lower": lower,
                "between": len(between),
                "depth": depth,
                # The claim's own success condition.
                "reclaimed": 1.0 if beats(nxt.level, high.level) else 0.0,
                # **Positive by construction and therefore not an edge**: the
                # node after a trough is higher than it, by definition. Kept
                # only to size the leg, never read as a return.
                "move": abs(nxt.level - node.level) / node.level,
                "spread": float(series["spread"][node.index]) / float(series["close"][node.index])
                if series["spread"][node.index] > 0
                else float("nan"),
            }
        )
    return rows


def local_hurst(moves, lags=(1, 2, 4, 8, 16)) -> float:
    """`H` from aggregated variance: slope of `log var(k-step sums)` on `log k`,
    halved.

    The same second-moment estimator `rough_volatility.hurst` uses, written
    causally over one window so it can gate a candidate without seeing
    anything after it.

    **Why it is the right conditioning variable for a reversal pattern.**
    `H < 0.5` is anti-persistent - a move is more likely to be undone than
    continued - which is precisely the regime in which a reversal signal
    should work. `H > 0.5` is trending. If Point Z works below 0.5 and not
    above it, that is a finding; if it is flat in `H`, the pattern is not
    reading persistence at all and neither is it reading its opposite.
    """
    series = [float(v) for v in moves]
    n = len(series)
    if n < 4 * max(lags):
        return float("nan")
    xs, ys = [], []
    for lag in lags:
        chunks = [sum(series[i : i + lag]) for i in range(0, n - lag + 1, lag)]
        if len(chunks) < 8:
            continue
        middle = statistics.fmean(chunks)
        spread = sum((c - middle) ** 2 for c in chunks) / (len(chunks) - 1)
        if spread <= 0:
            continue
        xs.append(math.log(lag))
        ys.append(math.log(spread))
    if len(xs) < 3:
        return float("nan")
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    den = sum((x - mx) ** 2 for x in xs)
    if den <= 0:
        return float("nan")
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / den / 2.0


def adaptive(
    rows,
    *,
    mode: str,
    start: float = CLAIMED_DEPTH,
    step: float = 0.03,
    bands: int = 8,
    warm: int = 30,
    window: int = 120,
):
    """A self-correcting depth threshold, strictly causal and clamped to `[0, 1]`.

    The static sweep answers a narrower question than the claim: it rules out
    any **fixed** cut-point, because the hit rate is flat across the grid, but
    not a cut-point that *moves*. These are three ways it could move, none of
    them a rolling quantile - a quantile tracks the depth distribution, which
    is a statement about how deep retracements are and not about which depths
    work.

    * `"feedback"` - the paper's own loop: start at its 0.14, **raise** after a
      candidate that failed and **lower** after one that succeeded.
    * `"bandit"` - the properly specified version of that idea. Split `[0, 1]`
      into `bands` depth bands, track each band's running success rate, and
      take a candidate only when its band's rate is the best available, by
      upper confidence bound so an untried band is explored rather than
      ignored. This *learns which depth works* instead of hunting blind.
    * `"volatility"` - a mechanism rather than a learner: the threshold scales
      with recent realised volatility, because a deeper retracement means less
      in a volatile stretch. Scaled so its median equals the paper's 0.14.

    Everything uses only candidates and outcomes already seen, and the
    threshold is clamped to the claim's own domain - the earlier version let
    the feedback loop run to 2.0, where a "retracement" is twice the move it
    retraces and almost nothing qualifies.

    Returns the hit rate, the count, and the threshold's range: a dynamic
    threshold that never moves is a static one wearing a loop.
    """
    cut = min(max(start, 0.0), 1.0)
    taken, hits = 0, 0.0
    low, high = cut, cut
    width = 1.0 / bands
    tries = [0] * bands
    wins = [0.0] * bands
    sizes: list[float] = []

    for seen, row in enumerate(rows):
        depth = row["depth"]
        if mode == "bandit":
            which = min(int(min(depth, 0.999) / width), bands - 1)
            total = sum(tries) or 1
            scores = []
            for b in range(bands):
                if tries[b] == 0:
                    scores.append(math.inf)
                else:
                    bonus = math.sqrt(2.0 * math.log(total) / tries[b])
                    scores.append(wins[b] / tries[b] + bonus)
            wanted = max(range(bands), key=lambda b: scores[b])
            if seen >= warm and which != wanted:
                tries[which] += 1
                wins[which] += row["reclaimed"]
                continue
            taken += 1
            hits += row["reclaimed"]
            tries[which] += 1
            wins[which] += row["reclaimed"]
            cut = wanted * width
        else:
            if mode == "volatility":
                sizes.append(row["move"])
                if len(sizes) >= warm:
                    recent = sizes[-window:]
                    middle = statistics.median(sizes)
                    now = statistics.median(recent)
                    cut = min(max(start * (now / middle) if middle > 0 else start, 0.0), 1.0)
            if depth > cut:
                taken += 1
                hits += row["reclaimed"]
                if mode == "feedback":
                    cut += step if row["reclaimed"] < 0.5 else -step
                    cut = min(max(cut, 0.0), 1.0)
        low, high = min(low, cut), max(high, cut)
    if taken < 25:
        return None
    return {"n": taken, "reclaimed": hits / taken, "low": low, "high": high}


def swept(rows, scale: float, *, strict: bool):
    """Hit rate and move by depth threshold, with and without criteria 1 and 2.

    `strict` applies criteria 1 and 2 as written - three consecutive lower
    lows and at least two peaks between them. Without it only the depth
    matters, which isolates what the structural criteria are worth.
    """
    if strict:
        rows = [r for r in rows if r["lower"] == 3 and r["between"] >= 2]
    out = []
    for cut in DEPTHS:
        picked = [r for r in rows if r["depth"] > cut]
        if len(picked) < 25:
            out.append(None)
            continue
        out.append(
            {
                "n": len(picked),
                "reclaimed": statistics.fmean(r["reclaimed"] for r in picked),
                "move": statistics.fmean(r["move"] for r in picked) / scale,
                "spreads": statistics.fmean(
                    r["move"] / r["spread"] for r in picked if r["spread"] > 0
                )
                if any(r["spread"] > 0 for r in picked)
                else float("nan"),
            }
        )
    return out


def main() -> None:
    print(
        f"frames {FRAMES} spans {SPANS}, depth swept {DEPTHS[0]} to {DEPTHS[-1]}\n"
        "depth is the retracement (H-Z)/(H-L), so the paper's 0.86 level\n"
        "constraint is depth > 0.14 and the interesting region is far deeper.\n"
        "'recl' is the share where the next peak exceeded the prior high -\n"
        "the claim's own success condition. 'move' is trough-to-next-peak in\n"
        "the series' own sigma. Every market row has a walk row beneath it\n"
        "built from the same bar geometry and run through the same detector.\n"
    )

    print("=" * 112)
    print("ARM 1  the depth sweep, strict criteria, market against its own walk")
    print("=" * 112)

    heads = [f"{c:>7.2f}" for c in DEPTHS[::2]]
    collected: dict[str, list] = {}
    for group, names in (("traded", TRADED), ("generated", GENERATED)):
        print(f"\n--- {group} ---")
        print(f"{'instrument':<22}{'frame':<6}{'span':>5}{'arm':<8}{'cands':>7}" + "".join(heads))
        for name in names:
            for frame in FRAMES:
                series = load(name, frame)
                if series is None:
                    continue
                import numpy as np

                scale = float(np.std(np.diff(np.log(series["close"]))))
                if scale <= 0:
                    continue
                for span in SPANS:
                    for arm, data in (("market", series), ("walk", walk_like(series))):
                        rows = candidates(data, span)
                        if len(rows) < 60:
                            continue
                        got = swept(rows, scale, strict=True)
                        cells = "".join(
                            f"{g['reclaimed']:>7.2f}" if g else f"{'-':>7}" for g in got[::2]
                        )
                        print(f"{name:<22}{frame:<6}{span:>5}{arm:<8}{len(rows):>7}{cells}")
                        collected.setdefault(f"{group}:{arm}", []).append(got)

    print("\n" + "=" * 112)
    print("ARM 2  is the 0.86 special? median hit rate by threshold, pooled")
    print("=" * 112)
    print(f"{'arm':<22}{'cells':>7}" + "".join(f"{c:>7.2f}" for c in DEPTHS))
    for key in sorted(collected):
        rows = collected[key]
        line = ""
        for i in range(len(DEPTHS)):
            values = [r[i]["reclaimed"] for r in rows if r[i]]
            line += f"{statistics.median(values):>7.2f}" if len(values) >= 3 else f"{'-':>7}"
        print(f"{key:<22}{len(rows):>7}{line}")

    print("\n" + "=" * 112)
    print("ARM 3  what criteria 1 and 2 are worth, and the duty-cycle control")
    print("=" * 112)
    print(
        f"{'instrument':<22}{'frame':<6}{'span':>5}{'all n':>7}{'all recl':>10}"
        f"{'strict n':>10}{'strict recl':>13}{'random recl':>13}{'z':>7}{'spreads':>9}"
    )
    rng = random.Random(SEED)
    for name in TRADED + GENERATED:
        for frame in FRAMES:
            series = load(name, frame)
            if series is None:
                continue
            for span in SPANS:
                rows = candidates(series, span)
                if len(rows) < 100:
                    continue
                strict = [r for r in rows if r["lower"] == 3 and r["between"] >= 2]
                if len(strict) < 25:
                    continue
                loose = statistics.fmean(r["reclaimed"] for r in rows)
                tight = statistics.fmean(r["reclaimed"] for r in strict)
                draws = [
                    statistics.fmean(r["reclaimed"] for r in rng.sample(rows, len(strict)))
                    for _ in range(400)
                ]
                middle = statistics.fmean(draws)
                spread = statistics.stdev(draws)
                spreads = [r["move"] / r["spread"] for r in strict if r["spread"] > 0]
                print(
                    f"{name:<22}{frame:<6}{span:>5}{len(rows):>7}{loose:>10.3f}"
                    f"{len(strict):>10}{tight:>13.3f}{middle:>13.3f}"
                    f"{(tight - middle) / spread if spread > 0 else float('nan'):>+7.2f}"
                    f"{statistics.fmean(spreads) if spreads else float('nan'):>9.2f}"
                )
    print("\n" + "=" * 112)
    print("ARM 4  the mirror: three higher highs reversing down, the same claim turned over")
    print("=" * 112)
    print(
        f"{'instrument':<22}{'frame':<6}{'span':>5}{'side':<8}{'all':>7}{'all recl':>10}"
        f"{'strict':>8}{'strict recl':>13}{'random':>9}{'z':>7}"
    )
    rng = random.Random(SEED)
    sides = []
    for name in TRADED + GENERATED:
        for frame in FRAMES:
            series = load(name, frame)
            if series is None:
                continue
            for span in SPANS:
                for side, label in ((TROUGH, "trough"), (PEAK, "peak")):
                    rows = candidates(series, span, side)
                    if len(rows) < 100:
                        continue
                    strict = [r for r in rows if r["lower"] == 3 and r["between"] >= 2]
                    if len(strict) < 25:
                        continue
                    loose = statistics.fmean(r["reclaimed"] for r in rows)
                    tight = statistics.fmean(r["reclaimed"] for r in strict)
                    draws = [
                        statistics.fmean(r["reclaimed"] for r in rng.sample(rows, len(strict)))
                        for _ in range(200)
                    ]
                    middle = statistics.fmean(draws)
                    spread = statistics.stdev(draws)
                    z = (tight - middle) / spread if spread > 0 else float("nan")
                    sides.append((name in GENERATED, label, span, z))
                    print(
                        f"{name:<22}{frame:<6}{span:>5}{label:<8}{len(rows):>7}{loose:>10.3f}"
                        f"{len(strict):>8}{tight:>13.3f}{middle:>9.3f}{z:>+7.2f}"
                    )
    print()
    for generated, group in ((False, "traded"), (True, "generated")):
        for label in ("trough", "peak"):
            cells = [
                z for g, s_, _sp, z in sides if g is generated and s_ == label and not math.isnan(z)
            ]
            if cells:
                print(
                    f"{group:<10}{label:<8}cells {len(cells):>3}  median z "
                    f"{statistics.median(cells):+.2f}  worst {max(cells):+.2f}"
                )
    print("\nand by detector span, pooled over both sides:")
    for span in SPANS:
        cells = [z for g, _s, sp, z in sides if not g and sp == span and not math.isnan(z)]
        if cells:
            tag = "  (the Bill Williams fractal)" if span == 2 else ""
            print(
                f"  span {span:<3} cells {len(cells):>3}  median z "
                f"{statistics.median(cells):+.2f}{tag}"
            )

    print("\n" + "=" * 112)
    print("ARM 5  a self-correcting threshold, which the static sweep does not cover")
    print("=" * 112)
    print(
        "base is no depth filter at all. claimed is the paper's own 0.14.\n"
        "static is the best fixed threshold **in hindsight** - an upper bound\n"
        "no causal rule can reach. feedback is the paper's loop; bandit is the\n"
        "same idea specified properly, learning which depth band wins by upper\n"
        "confidence bound; volatility scales the cut with recent range. All\n"
        "three are clamped to [0, 1] and use only what they have already seen.\n"
    )
    print(
        f"{'instrument':<22}{'frame':<6}{'span':>5}{'base':>7}{'claimed':>9}{'static':>8}"
        f"{'feedback':>10}{'bandit':>8}{'volatil':>9}{'bandit moved':>14}"
    )
    scored: dict[str, list[float]] = {}
    for name in TRADED + GENERATED:
        for frame in FRAMES:
            series = load(name, frame)
            if series is None:
                continue
            for span in SPANS:
                rows = candidates(series, span, TROUGH)
                strict = [r for r in rows if r["lower"] == 3 and r["between"] >= 2]
                if len(strict) < 60:
                    continue
                base = statistics.fmean(r["reclaimed"] for r in strict)
                claimed = [r for r in strict if r["depth"] > CLAIMED_DEPTH]
                at_claim = (
                    statistics.fmean(r["reclaimed"] for r in claimed)
                    if len(claimed) >= 25
                    else float("nan")
                )
                fixed = max(
                    (
                        statistics.fmean(r["reclaimed"] for r in picked)
                        for cut in DEPTHS
                        if len(picked := [r for r in strict if r["depth"] > cut]) >= 25
                    ),
                    default=float("nan"),
                )
                got = {m: adaptive(strict, mode=m) for m in ("feedback", "bandit", "volatility")}
                for key, value in (
                    ("base", base),
                    ("claimed", at_claim),
                    ("static", fixed),
                    *((m, g["reclaimed"] if g else float("nan")) for m, g in got.items()),
                ):
                    if not math.isnan(value):
                        scored.setdefault(
                            ("generated:" if name in GENERATED else "traded:") + key, []
                        ).append(value)
                moved = (
                    f"{got['bandit']['low']:>6.2f}-{got['bandit']['high']:<7.2f}"
                    if got["bandit"]
                    else f"{'-':>14}"
                )
                print(
                    f"{name:<22}{frame:<6}{span:>5}{base:>7.3f}{at_claim:>9.3f}{fixed:>8.3f}"
                    + "".join(
                        f"{g['reclaimed']:>10.3f}" if g else f"{'-':>10}"
                        for g in (got["feedback"],)
                    )
                    + "".join(
                        f"{g['reclaimed']:>8.3f}" if g else f"{'-':>8}" for g in (got["bandit"],)
                    )
                    + "".join(
                        f"{g['reclaimed']:>9.3f}" if g else f"{'-':>9}"
                        for g in (got["volatility"],)
                    )
                    + moved
                )
    print()
    for group in ("traded", "generated"):
        line = f"{group:<12}"
        for key in ("base", "claimed", "static", "feedback", "bandit", "volatility"):
            values = scored.get(f"{group}:{key}", [])
            line += f"  {key} {statistics.median(values):.3f}" if values else f"  {key} -"
        print(line)

    print("\n" + "=" * 112)
    print("ARM 6  fractals: does Point Z work where the market is anti-persistent?")
    print("=" * 112)
    print(
        "H below 0.5 is anti-persistent - a move more likely undone than\n"
        "continued - which is the regime a reversal pattern should want. The\n"
        "walk sits at 0.5 by construction, so its row is the calibration.\n"
    )
    print(
        f"{'instrument':<22}{'frame':<6}{'span':>5}{'arm':<8}{'med H':>8}"
        f"{'recl H low':>12}{'recl H mid':>12}{'recl H high':>13}{'low-high':>10}"
    )
    gaps = []
    for name in TRADED + GENERATED:
        for frame in FRAMES:
            series = load(name, frame)
            if series is None:
                continue
            for span in SPANS:
                for arm, data in (("market", series), ("walk", walk_like(series))):
                    rows = [r for r in candidates(data, span, TROUGH) if not math.isnan(r["hurst"])]
                    if len(rows) < 150:
                        continue
                    order = sorted(rows, key=lambda r: r["hurst"])
                    third = len(order) // 3
                    bands = (order[:third], order[third : 2 * third], order[2 * third :])
                    rates = [statistics.fmean(r["reclaimed"] for r in b) for b in bands]
                    gap = rates[0] - rates[2]
                    if arm == "market":
                        gaps.append((name in GENERATED, gap))
                    print(
                        f"{name:<22}{frame:<6}{span:>5}{arm:<8}"
                        f"{statistics.median(r['hurst'] for r in rows):>8.3f}"
                        f"{rates[0]:>12.3f}{rates[1]:>12.3f}{rates[2]:>13.3f}{gap:>+10.3f}"
                    )
    print()
    for generated, group in ((False, "traded"), (True, "generated")):
        cells = [g for gen, g in gaps if gen is generated]
        if cells:
            print(
                f"{group:<10}cells {len(cells):>3}  median low-minus-high "
                f"{statistics.median(cells):+.3f}  share positive "
                f"{sum(1 for c in cells if c > 0) / len(cells):.2f}"
            )

    print("\nDONE")


if __name__ == "__main__":
    main()
