"""When the next volatile move arrives - asked as a survival problem, with its hazard null.

Asked on 2026-10-17: "if we know that a volatile move is about to happen soon,
also if we can estimate the time it will happen that would be great too".

The first half is `dispersion_class.py`. This is the second, and it is the
harder one because **this desk has measured a timing claim into the ground
twice**:

* `structures/cycles.py` ran a head predicting *how long* until the next price
  turn and found it *"scores positive on the nulls too, so its positive values
  are a property of the metric rather than of the series"*;
* `research/docs/magnets.md` found the time-to-return exponent at about 1.0 on
  real markets - genuinely linear rather than diffusive - but **identical on
  every arm**, including an arbitrary price the same distance away. The
  ballistic exponent belongs to the market and no level earns it.

Both failures have the same shape: a timing statistic that looks skilful
because the *base hazard* is skilful. If volatility is persistent then a high
reading now means a high reading soon, and a model that has learnt only that
has learnt nothing about timing.

So this is framed as survival rather than regression, and the three things that
make it readable are the censoring, the hazard baseline and the strata.

## The question, stated so it can fail

Fix a threshold from the **training** half: the top `share` of log-variance.
From each bar, the event is the **first** bar within `HORIZON` whose
log-variance exceeds it. Rows with no such bar are **censored**, not dropped -
dropping them conditions on the event happening, which is the single easiest
way to manufacture a timing result.

* **C-index** over comparable pairs, which is the metric censoring allows. 0.50
  is no ordering skill. A pair is comparable when the earlier of the two events
  is uncensored, so a censored row still constrains every pair it can.
* **median absolute error** on the uncensored rows, against the **training
  half's median time** as the baseline - the same causal-baseline discipline
  `depths.Skill` uses, because a timing error without its baseline is a number
  with no scale.

## The nulls

* `base` - the unconditional hazard: every row predicted the same time. It must
  read a C-index of exactly 0.50, and an arm that cannot beat it has no timing
  skill whatever its error looks like.
* **strata** - every metric recomputed inside bins of the incumbent reading,
  which is where `auc-is-free-on-volatility-targets` says the apparent skill on
  a volatility target goes to die: 0.805 pooled against 0.525 within strata.
* **shuffled** labels and the **constant-sigma synthetics**, whose hazard is
  constant by construction, so any timing skill there is an artefact and is the
  reading that would refute the whole thing.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
for q in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(q))

from dispersion_ml import SIZE, _ridge, onescale, parkinson  # noqa: E402
from pattern_fingerprint import CACHE, classify, load  # noqa: E402

FRAMES = ("1h", "4h")
TRADED = ("fx_major", "fx_cross", "metal")
CONTROLS = ("volatility",)
PER_CLASS = 8
LIMIT = 12000
LAGS = (1, 5, 22)
#: Bars to look ahead for the event. Beyond this a row is censored.
HORIZON = 40
SHARES = (0.20, 0.10)
STRATA = 5
RIDGES = (1e-6, 1e-4, 1e-2, 1.0, 100.0)
SEED = 20261017


def _events(logvar: np.ndarray, mark: float, start: int, stop: int):
    """Time to the first exceedance from each bar, and whether it was seen."""
    when, seen = [], []
    for i in range(start, stop):
        found = 0
        for k in range(1, HORIZON + 1):
            if logvar[i + k] > mark:
                found = k
                break
        when.append(found if found else HORIZON)
        seen.append(bool(found))
    return np.asarray(when, dtype=float), np.asarray(seen, dtype=bool)


def _concordance(when: np.ndarray, seen: np.ndarray, score: np.ndarray, most=400000) -> float:
    """C-index: of comparable pairs, how many the score orders correctly.

    Higher `score` means *sooner*. A pair is comparable when the earlier event
    is uncensored; a pair of censored rows, or one where the censoring time is
    earlier than the other's event, says nothing and is skipped. Sampled rather
    than exhaustive above `most` pairs, with a fixed generator.
    """
    n = len(when)
    if n < 20:
        return float("nan")
    rng = np.random.default_rng(11)
    total = concordant = ties = 0
    pairs = min(most, n * (n - 1) // 2)
    left = rng.integers(0, n, size=pairs)
    right = rng.integers(0, n, size=pairs)
    for a, b in zip(left, right, strict=True):
        if a == b or when[a] == when[b]:
            continue
        first, last = (a, b) if when[a] < when[b] else (b, a)
        if not seen[first]:
            continue  # the earlier one is censored: the order is unknown
        total += 1
        if score[first] > score[last]:
            concordant += 1
        elif score[first] == score[last]:
            ties += 1
    if not total:
        return float("nan")
    return (concordant + 0.5 * ties) / total


def _tuned(x: np.ndarray, y: np.ndarray, keep: np.ndarray, cut: int) -> np.ndarray:
    """Ridge fitted on the uncensored training rows; returns a score for all rows."""
    fit = keep[:cut]
    if fit.sum() < 50:
        return np.zeros(len(x))
    best, pick = -math.inf, RIDGES[0]
    rows = x[:cut][fit]
    want = y[:cut][fit]
    half = max(len(rows) // 2, 1)
    for lam in RIDGES:
        coef, _ = _ridge(rows[:half], want[:half], lam)
        guess = coef[0] + rows[half:] @ coef[1:]
        err = float(np.sum((want[half:] - guess) ** 2))
        if -err > best:
            best, pick = -err, lam
    coef, _ = _ridge(rows, want, pick)
    # Negated, so a *shorter* predicted time is a *higher* score.
    return -(coef[0] + x @ coef[1:])


def score(bars: dict[str, np.ndarray], share: float, rng, shuffle=False) -> dict:
    logvar = parkinson(bars["high"], bars["low"])
    good = np.isfinite(logvar)
    if good.sum() < 2000:
        return {}
    logvar = logvar[good]
    start = max(LAGS)
    stop = len(logvar) - HORIZON - 1
    if stop - start < 1000:
        return {}

    rows = np.asarray(
        [[float(np.mean(logvar[i - lag + 1 : i + 1])) for lag in LAGS] for i in range(start, stop)],
        dtype=float,
    )
    deep = np.asarray(
        [[float(logvar[i - k]) for k in range(SIZE)] for i in range(start, stop)], dtype=float
    )
    cut = len(rows) // 2
    mark = float(np.quantile(logvar[: start + cut], 1.0 - share))
    when, seen = _events(logvar, mark, start, stop)
    if shuffle:
        order = rng.permutation(len(when))
        when, seen = when[order], seen[order]

    target = np.log1p(when)
    scores = {
        "base": np.zeros(len(rows)),
        "last": rows[:, 0],
        "har": _tuned(rows, target, seen, cut),
        "lin48": _tuned(deep, target, seen, cut),
    }

    held = slice(cut, None)
    incumbent = rows[held, 0]
    edges = np.quantile(incumbent, np.linspace(0.0, 1.0, STRATA + 1)[1:-1])
    bins = np.digitize(incumbent, edges)
    base_time = float(np.median(when[:cut][seen[:cut]])) if seen[:cut].any() else float("nan")

    out: dict[str, dict[str, float]] = {}
    for arm, series in scores.items():
        got = series[held]
        row = {
            "c": _concordance(when[held], seen[held], got),
            "seen": float(np.mean(seen[held])),
        }
        # Error only where the event was seen, against the training median.
        mask = seen[held]
        if mask.sum() > 50 and not math.isnan(base_time):
            row["base err"] = float(np.median(np.abs(when[held][mask] - base_time)))
        out[arm] = row

        inner = []
        for b in range(STRATA):
            pick = bins == b
            if pick.sum() < 200 or seen[held][pick].sum() < 30:
                continue
            inner.append(_concordance(when[held][pick], seen[held][pick], got[pick]))
        if inner:
            out[f"{arm} (strata)"] = {"c": float(np.nanmean(inner)), "seen": row["seen"]}
    return out


def main() -> None:
    print(
        "When the next volatile move arrives. C-index over comparable pairs,\n"
        f"censored at {HORIZON} bars. 0.500 is no ordering skill, and `base` -\n"
        "the unconditional hazard - must read exactly that. `(strata)` holds\n"
        "the incumbent constant, which is where a volatility-target metric\n"
        "usually stops being skilful. `seen` is the share of rows whose event\n"
        "arrived inside the horizon.\n"
    )
    rng = np.random.default_rng(SEED)
    groups: dict[str, list[str]] = {}
    for path in sorted(CACHE.glob("*.1h.npz")):
        name = path.name[: -len(".1h.npz")]
        groups.setdefault(classify(name), []).append(name)

    arms = ("base", "last", "har", "lin48")
    for frame in FRAMES:
        for label in ("onescale", *TRADED, *CONTROLS):
            if label != "onescale" and label not in groups:
                continue
            for share in SHARES:
                for shuffle in (False, True):
                    pooled: dict[str, list[dict[str, float]]] = {}
                    names = (
                        [f"onescale{k}" for k in range(PER_CLASS)]
                        if label == "onescale"
                        else sorted(groups[label])[:PER_CLASS]
                    )
                    for name in names:
                        bars = onescale(LIMIT, rng) if label == "onescale" else load(name, frame)
                        if bars is None:
                            continue
                        cut = {k: v[-LIMIT:] for k, v in bars.items()}
                        for arm, row in score(cut, share, rng, shuffle=shuffle).items():
                            pooled.setdefault(arm, []).append(row)
                    if not pooled:
                        continue
                    tag = f"{label}, {frame}, top {share:.0%}" + ("  [SHUFFLED]" if shuffle else "")
                    print(f"\n=== {tag}")
                    print(f"  {'arm':<16}{'c-index':>9}{'above .5':>10}{'seen':>7}{'base err':>10}")
                    for arm in arms:
                        for key in (arm, f"{arm} (strata)"):
                            rows = pooled.get(key)
                            if not rows:
                                continue
                            cs = [r["c"] for r in rows if not math.isnan(r.get("c", float("nan")))]
                            if not cs:
                                continue
                            errs = [r["base err"] for r in rows if "base err" in r]
                            print(
                                f"  {key:<16}{float(np.median(cs)):>9.4f}"
                                f"{sum(v > 0.5 for v in cs):>7}/{len(cs):<3}"
                                f"{float(np.median([r['seen'] for r in rows])):>7.3f}"
                                f"{(float(np.median(errs)) if errs else float('nan')):>10.2f}"
                            )


if __name__ == "__main__":
    main()
