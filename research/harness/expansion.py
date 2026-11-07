"""How much of the +2.969R expansion ceiling is actually predictable?

    ./.secrets/lab.sh exec "cd \\$HOME/till_infinity/repo && \\
      OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \\
      nohup \\$HOME/itb-venv/bin/python -u research/harness/expansion.py \\
      > \\$HOME/till_infinity/logs/expansion.log 2>&1 &"

`atrstate.py` measured the ceiling: gating a 24-bar breakout on the **true**
forward excursion lifts it from +0.090R to **+2.969R** at a 13% duty cycle,
where a random gate at the same duty cycle reads -0.059. Gating a fade on a
**narrow** forward excursion flips it from -0.221R to +0.160R. The two rules
want opposite gates, and bucketing by trailing ATR *level* recovered none of
it - because the oracle conditions on excursion **relative to** current ATR,
which is expansion, and the level is a different quantity.

This asks what a model of that expansion recovers.

## Three things this harness has to get right

**The cut must come from the training fold.** The label is "forward excursion
is in the top third", and the boundary of that third is itself estimated. Using
the full sample's percentile would hand the model a threshold computed partly
from its own test period. Each fold takes its cut from its training rows only.

**The oracle is recomputed on the same test rows.** The +2.969 figure was
measured over all bars; comparing a walk-forward prediction against it would
be comparing two different row sets. Here both gates select the same share of
the same fold, so the only difference is foresight.

**The incumbent is the baseline, not 0.5.**
`auc-is-free-on-volatility-targets`: a volatility target reads AUC 0.805 on a
*constant-volatility* process and 0.525 within strata, while trailing-volatility
incumbents alone read 0.74-0.78. So an impressive AUC here means nothing on
its own. The model is run twice - on everything, and on the trailing-volatility
features alone - and the gap between them is the only part that is new.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parent))
import atrstate as a  # noqa: E402
import itb1h as itb  # noqa: E402

TRAIN = 8_000
TEST = 1_000
EMBARGO = a.HORIZON
TOP_Q = 67
LOW_Q = 33
SHARES = [0.13, 0.32]
SEED = 20261107
DRAWS = 2000

#: Features that are already a volatility reading, so a model restricted to
#: them is the incumbent this has to beat rather than 0.5.
INCUMBENT = ("atr_rel", "range_rel", "vol12", "vol24", "vol48", "vol96")


def _non_overlapping(rows: np.ndarray, ranking: np.ndarray, take: int) -> list[int]:
    """Up to `take` positions off `ranking`, best first, none overlapping.

    **One position at a time, as a desk would hold them.** Without this a
    24-bar outcome can be counted on every one of 24 consecutive firing bars,
    which both inflates n and makes the rows dependent - the defect that
    turned a direction AUC of 0.79 into 0.51 elsewhere in this repository. The
    duty cycle therefore means "up to this share, non-overlapping", and the
    arms are all held to the same rule so the comparison survives it.
    """
    # **Returns rows, not ranking positions.** The first version returned the
    # index into `ranking` - the live subset - and the caller used it to index
    # the full fold, so every arm read the wrong bars and most of them had no
    # trade at all: the whole table came back NaN.
    picked: list[int] = []
    free = -1
    for position in np.argsort(-ranking):
        row = int(rows[position])
        if row <= free:
            continue
        picked.append(row)
        free = row + a.HORIZON
        if len(picked) >= take:
            break
    return picked


def summarise(name: str, rows: list[tuple[int, float]], rng, base: float | None = None) -> float:
    """Mean R with a block bootstrap, blocks the length of the hold.

    Resampling single trades would assume independence the selection does not
    give, even de-overlapped: two trades a day apart in the same volatility
    regime are not two draws.
    """
    if len(rows) < 8:
        print(f"    {name:34s} n {len(rows):5d}   too few")
        return float("nan")
    order = sorted(rows)
    values = np.asarray([value for _, value in order])
    mean = float(values.mean())
    index = np.asarray([i for i, _ in order], dtype=np.float64)
    keyed: dict[int, list[float]] = {}
    for i, value in order:
        keyed.setdefault(int((i - index[0]) // (a.HORIZON * 4)), []).append(value)
    blocks = list(keyed.values())
    boots = []
    for _ in range(DRAWS):
        drawn = [blocks[k] for k in rng.integers(0, len(blocks), len(blocks))]
        flat = [v for b in drawn for v in b]
        if flat:
            boots.append(float(np.mean(flat)))
    lo, hi = float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))
    delta = f"{mean - base:+8.3f}" if base is not None else "        "
    print(f"    {name:34s} n {len(values):5d}  meanR {mean:+7.3f}  [{lo:+7.3f},{hi:+7.3f}] {delta}")
    return mean


def main() -> int:
    rng = np.random.default_rng(SEED)
    bars = itb.load()
    unit = a.atr(bars["high"], bars["low"], bars["close"], a.ATR_N)
    excursion = a.forward_excursion(bars, unit)
    matrix, names = itb.features(bars)
    sides = a.rules(bars, unit)
    incumbent_cols = [names.index(n) for n in INCUMBENT if n in names]

    usable = np.isfinite(matrix).all(axis=1) & np.isfinite(excursion)
    index = np.flatnonzero(usable)
    print(f"BTCUSD H1 {len(bars['close'])} bars, {len(names)} features, "
          f"{len(index)} usable rows, horizon {a.HORIZON}")
    print(f"incumbent subset: {[names[i] for i in incumbent_cols]}\n")

    outcomes = {name: a.outcomes(bars, unit, side) for name, side in sides.items()}

    aucs: dict[str, list[float]] = {"all-features": [], "incumbent": [], "strata": []}
    gathered: dict[tuple[str, float, str], list[float]] = {}

    start = 0
    while start + TRAIN + EMBARGO + TEST <= len(index):
        tr = index[start : start + TRAIN]
        te = index[start + TRAIN + EMBARGO : start + TRAIN + EMBARGO + TEST]
        # The boundary of "the top third" estimated on training rows only.
        cut_hi = float(np.percentile(excursion[tr], TOP_Q))
        y_tr = (excursion[tr] >= cut_hi).astype(float)
        y_te = (excursion[te] >= cut_hi).astype(float)
        if len(np.unique(y_tr)) < 2 or len(np.unique(y_te)) < 2:
            start += TEST
            continue

        full = HistGradientBoostingClassifier(
            max_depth=3, max_iter=200, learning_rate=0.05, random_state=SEED
        ).fit(matrix[tr], y_tr)
        score = full.predict_proba(matrix[te])[:, 1]
        aucs["all-features"].append(float(roc_auc_score(y_te, score)))

        only = HistGradientBoostingClassifier(
            max_depth=3, max_iter=200, learning_rate=0.05, random_state=SEED
        ).fit(matrix[tr][:, incumbent_cols], y_tr)
        aucs["incumbent"].append(
            float(roc_auc_score(y_te, only.predict_proba(matrix[te][:, incumbent_cols])[:, 1]))
        )

        # Within trailing-volatility strata, where the free part of a
        # volatility AUC disappears.
        vol = matrix[te][:, names.index("atr_rel")]
        edges = np.quantile(vol, np.linspace(0, 1, 6))
        parts, weights = [], []
        for b in range(5):
            inside = (vol >= edges[b]) & (vol <= edges[b + 1])
            if inside.sum() >= 50 and len(np.unique(y_te[inside])) == 2:
                parts.append(float(roc_auc_score(y_te[inside], score[inside])))
                weights.append(int(inside.sum()))
        if parts:
            aucs["strata"].append(float(np.average(parts, weights=weights)))

        for rule_name, (r, fires) in outcomes.items():
            # A fade wants the NARROW end, a breakout the WIDE end.
            wide = rule_name == "breakout"
            signal = score if wide else -score
            truth = excursion[te] if wide else -excursion[te]
            live = np.isfinite(r[te]) & fires[te]
            if live.sum() < 20:
                continue
            for share in SHARES:
                take = max(int(round(share * live.sum())), 1)
                for arm, ranking in (
                    ("predicted", signal[live]),
                    ("oracle", truth[live]),
                    ("random", rng.random(int(live.sum()))),
                ):
                    rows = _non_overlapping(np.flatnonzero(live), ranking, take)
                    gathered.setdefault((rule_name, share, arm), []).extend(
                        (te[i], float(r[te][i])) for i in rows
                    )
                keep = _non_overlapping(
                    np.flatnonzero(live), np.zeros(int(live.sum())), int(live.sum())
                )
                gathered.setdefault((rule_name, share, "unfiltered"), []).extend(
                    (te[i], float(r[te][i])) for i in keep
                )
        start += TEST

    print("=== the expansion target, out of sample ===")
    for key, values in aucs.items():
        if values:
            print(
                f"  {key:14s} folds {len(values):3d}  AUC {np.mean(values):.4f} "
                f"+-{np.std(values) / np.sqrt(len(values)):.4f}"
            )
    if aucs["all-features"] and aucs["incumbent"]:
        gap = np.mean(aucs["all-features"]) - np.mean(aucs["incumbent"])
        print(f"  all-features minus incumbent: {gap:+.4f}  <- the only part that is new")

    for rule_name in sides:
        print(f"\n=== {rule_name} ===")
        for share in SHARES:
            base = gathered.get((rule_name, share, "unfiltered"))
            if not base:
                continue
            baseline = summarise(f"unfiltered @{share:.0%}", base, rng)
            got = {}
            for arm in ("oracle", "predicted", "random"):
                got[arm] = summarise(
                    f"  {arm} @{share:.0%}", gathered.get((rule_name, share, arm), []), rng, baseline
                )
            ceiling = got["oracle"] - baseline
            recovered = got["predicted"] - baseline
            if np.isfinite(ceiling) and abs(ceiling) > 1e-9:
                print(
                    f"      recovered {recovered / ceiling:+6.1%} of the oracle's "
                    f"{ceiling:+.3f} lift"
                )

    print(
        "\nThe AUC rows decide whether there is anything new; the `recovered` lines decide\n"
        "whether it is worth anything. A prediction that beats `random` but recovers a few\n"
        "percent of the ceiling is a real signal that cannot pay for a trade."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
