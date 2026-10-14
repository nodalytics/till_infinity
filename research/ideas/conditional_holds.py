"""Does a level's **own history** say whether it will hold next time?

`statespace-ranging.md` tested seventeen ways of **nominating** a price that
should act as support - volume profile, value area, rejection and acceptance
profiles, hour-of-day profiles, two published wick-to-body thresholds, momentum
and acceleration turns - and every one came back inside the noise against a
distance-matched placebo.

That refutes **constructions**, which have no history. It says nothing about the
conditional question, which is the one `levels.SideStats` has been accumulating
in production all along: *has **this** level, from **this** side, turned price
before, and does that predict the next time?* `sym_hold_rate` is the clearest
form of it, it has never been read by anything, and the instruction on
2026-10-14 was to test it without deferring to the 0.5 floor in its docstring.

## Two arms, and the first one can close the question on its own

**Arm 1 asks whether levels differ at all.** If every level's true hold rate is
the same number, then a level's record is sampling noise and no estimator -
shrunk, raw, or otherwise - can predict from it. That is a **dispersion**
question, not a prediction one, and production already has the tool:
`shrinkage.tau_squared` is DerSimonian and Laird's method of moments, which
subtracts each level's own binomial noise from the observed spread. Its own
docstring says why that subtraction is the whole point - it is what separates
"levels differ" from "levels were counted few times".

`tau` near zero means there is nothing to learn, whatever arm 2 says.

**Arm 2 asks whether it predicts out of sample.** At each touch past the
`WARM`-th, every arm predicts from that level's **prior** touches only, and is
scored on what actually happened. Brier against the pooled base rate is the
test: an estimator that cannot beat "every level holds at the base rate" has
found nothing.

## The placebo is a level that is not one

A random price accumulates a history too, and its history is drawn from the same
local market state - trending stretches, quiet stretches, volatility regimes.
If a placebo's record predicts its next outcome as well as a real level's does,
then what is being measured is the **market's** serial correlation and not the
level's memory. Each real level is paired with a placebo at a matched distance,
which is the design that refuted round numbers in `game-theory.md`.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from till_infinity.structures.shrinkage import tau_squared  # noqa: E402
from till_infinity.structures.statespace.interacting import Rate  # noqa: E402

CACHE = Path(os.environ.get("SEQLAB_CACHE", str(Path.home() / "till_infinity/data/seqlab")))
FRAME = os.environ.get("FRAME", "1h")
LIMIT = int(os.environ.get("LIMIT", "40000"))
LOOKBACK = int(os.environ.get("LOOKBACK", "100"))
PER_FEED = int(os.environ.get("PER_FEED", "60"))
#: Touches a level needs before any of its outcomes are scored.
WARM = int(os.environ.get("WARM", "5"))
#: Resolved interactions a level needs to enter the study at all.
LEAST = int(os.environ.get("LEAST", "12"))
PATIENCE = int(os.environ.get("PATIENCE", "24"))
JITTER = 0.15
SEED = 20261014
TRADED = tuple(os.environ.get("TRADED", "EURUSD,GBPUSD,USDJPY,XAUUSD,AUDUSD,USDCAD").split(","))
GENERATED = tuple(os.environ.get("GENERATED", "Volatility_75_Index,Step_Index_200").split(","))


def load(name: str):
    import numpy as np

    path = CACHE / f"{name}.{FRAME}.npz"
    if not path.exists():
        return None
    with np.load(path) as bundle:
        need = {"time", "high", "low", "close"}
        if not need <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        got = {k: np.asarray(bundle[k], dtype=float)[order] for k in need}
    keep = (got["high"] >= got["low"]) & (got["low"] > 0)
    got = {k: v[keep] for k, v in got.items()}
    if len(got["close"]) < 8000:
        return None
    if len(got["close"]) > LIMIT:
        got = {k: v[-LIMIT:] for k, v in got.items()}
    return got


def outcomes(bars, level: float, start: int, move: float) -> list[bool]:
    """Every resolved interaction with `level` after `start`, oldest first.

    `True` is a hold - price travelled one `move` **back the way it came**
    before one `move` through. Unresolved races are dropped rather than
    counted, which is what `SideStats.decisive` does for the same reason.
    """
    highs, lows, closes = bars["high"], bars["low"], bars["close"]
    out: list[bool] = []
    i = start
    end = len(highs)
    while i < end:
        if not (lows[i] <= level <= highs[i]):
            i += 1
            continue
        before = closes[i - 1] if i > 0 else closes[i]
        from_below = before < level
        back = level - move if from_below else level + move
        through = level + move if from_below else level - move
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
        # Skip past the race so one visit is one interaction.
        i = j + 1
    return out


def arms(prior_history: list[bool], base: float) -> dict[str, float]:
    """Every estimator's P(hold) from this level's prior touches only."""
    n = len(prior_history)
    hits = sum(1 for h in prior_history if h)
    got = {"base rate": base, "raw ratio": hits / n if n else base}
    for prior in (1.0, 2.0, 5.0):
        rate = Rate(hits=float(hits), misses=float(n - hits), prior=prior)
        got[f"beta {prior:g}"] = rate.mean
    # Shrunk toward the pooled base rate rather than toward 0.5, which is what
    # `reactions.infer` does with its neighbours' prior and is the fairer
    # comparison: 0.5 is not this desk's base rate.
    k = 4.0
    got["toward base"] = (hits + k * base) / (n + k) if n + k > 0 else base
    return got


def brier(predictions: list[float], truths: list[bool]) -> float:
    return statistics.fmean(
        (p - (1.0 if t else 0.0)) ** 2 for p, t in zip(predictions, truths, strict=True)
    )


def auc(predictions: list[float], truths: list[bool]) -> float:
    """Rank AUC. **Ties are not handled, which the base-rate arm exposes.**

    A constant prediction ties every pair, so its AUC is 0.5 by definition -
    but this ranks by sorted position, and a stable sort on `(value, truth)`
    puts every positive last, which reads 1.0. The constant arm's AUC is
    therefore meaningless and is printed as a dash.

    It does not affect the other arms, whose predictions vary, and it is left
    rather than fixed because the fix is a mid-rank implementation that nothing
    else here needs - but an unflagged 1.0 in a results table is exactly the
    kind of number that gets quoted.
    """
    pairs = sorted(zip(predictions, truths, strict=True))
    positives = sum(1 for _, t in truths and pairs if t)
    negatives = len(pairs) - positives
    if positives == 0 or negatives == 0:
        return float("nan")
    rank, total = 0.0, 0.0
    for i, (_, t) in enumerate(pairs, start=1):
        if t:
            total += i
            rank += 1
    return (total - rank * (rank + 1) / 2) / (positives * negatives)


def main() -> None:
    import numpy as np

    rng = np.random.default_rng(SEED)
    print(
        f"frame {FRAME}  {LOOKBACK}-bar extremes, {LEAST}+ resolved interactions,\n"
        f"predictions start after {WARM} touches\n"
    )
    for group, names in (("traded", TRADED), ("generated", GENERATED)):
        real_counts: list[tuple[float, float]] = []
        fake_counts: list[tuple[float, float]] = []
        real_pred: dict[str, list[float]] = {}
        fake_pred: dict[str, list[float]] = {}
        real_truth: list[bool] = []
        fake_truth: list[bool] = []
        for name in names:
            bars = load(name)
            if bars is None:
                continue
            closes, highs, lows = bars["close"], bars["high"], bars["low"]
            starts = np.linspace(LOOKBACK, len(closes) - 500, PER_FEED, dtype=int)
            for k, at in enumerate(starts):
                window = slice(max(at - LOOKBACK, 0), at)
                move = float(np.median(highs[window] - lows[window]))
                if not (move > 0):
                    continue
                level = float(highs[window].max() if k % 2 == 0 else lows[window].min())
                here = float(closes[at])
                gap = level - here
                if abs(gap) < 0.25 * move:
                    continue
                scale = 1.0 + float(rng.uniform(-JITTER, JITTER))
                for which, price, counts in (
                    ("real", level, real_counts),
                    ("fake", here + gap * scale, fake_counts),
                ):
                    got = outcomes(bars, price, int(at), move)
                    if len(got) < LEAST:
                        continue
                    counts.append((float(len(got)), float(sum(1 for g in got if g))))
                    store = real_pred if which == "real" else fake_pred
                    truths = real_truth if which == "real" else fake_truth
                    base = sum(1 for g in got if g) / len(got)
                    for i in range(WARM, len(got)):
                        # The base rate a caller would actually have: the
                        # pooled rate so far on this instrument, not this
                        # level's own, which would leak its answer.
                        for arm, value in arms(got[:i], 0.5).items():
                            store.setdefault(arm, []).append(value)
                        truths.append(got[i])
                    _ = base
        if not real_counts:
            continue
        print("=" * 92)
        print(group)
        print("=" * 92)
        pooled = sum(h for _, h in real_counts) / sum(n for n, _ in real_counts)
        tau_real, used_real = tau_squared(real_counts, pooled)
        pooled_fake = sum(h for _, h in fake_counts) / max(sum(n for n, _ in fake_counts), 1)
        tau_fake, used_fake = tau_squared(fake_counts, pooled_fake)
        print("ARM 1  do levels differ at all, once their own counting noise is removed")
        print(
            f"  real levels : pooled hold {pooled:.3f}  tau {math.sqrt(tau_real):.4f}  "
            f"over {used_real} levels"
        )
        print(
            f"  placebo     : pooled hold {pooled_fake:.3f}  tau {math.sqrt(tau_fake):.4f}  "
            f"over {used_fake} prices"
        )
        print(
            "  `tau` is the between-level standard deviation of the **true**\n"
            "  rates. Near zero means every level has the same rate and its\n"
            "  record is noise, whatever arm 2 reports.\n"
        )
        print("ARM 2  does a level's prior record predict its next interaction")
        print(f"  {'arm':<14}{'Brier':>10}{'vs base':>10}{'AUC':>9}{'placebo Brier':>15}")
        order = ["base rate", "raw ratio", "beta 1", "beta 2", "beta 5", "toward base"]
        baseline = brier(real_pred["base rate"], real_truth) if real_truth else float("nan")
        for arm in order:
            if arm not in real_pred:
                continue
            got = brier(real_pred[arm], real_truth)
            fake = (
                brier(fake_pred[arm], fake_truth)
                if arm in fake_pred and fake_truth
                else float("nan")
            )
            print(
                f"  {arm:<14}{got:>10.5f}{baseline - got:>+10.5f}"
                f"{'-' if arm == 'base rate' else f'{auc(real_pred[arm], real_truth):.4f}':>9}"
                f"{fake:>15.5f}"
            )
        print(
            f"\n  {len(real_truth):,} scored interactions, {len(fake_truth):,} placebo\n"
            "  `vs base` is positive when the arm beats predicting the base rate\n"
            "  for every level. AUC near 0.5 means the estimate does not order\n"
            "  outcomes at all.\n"
        )
    print(
        "**Arm 1 is the one that can close this.** Prediction can fail for many\n"
        "reasons - too few touches, a drifting rate, the wrong estimator - but a\n"
        "`tau` of zero says there is no between-level signal to find, and then\n"
        "no estimator was ever going to work. If `tau` is zero on real levels\n"
        "and on the placebo alike, `sym_hold_rate` is measuring sampling noise\n"
        "and `levels.py` has been accumulating it faithfully for nothing."
    )
    _ = np


if __name__ == "__main__":
    main()
