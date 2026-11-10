"""What the catalogue's most-boosted volatility script is, reduced to its arithmetic.

    ./.secrets/lab.sh run research/ideas/tv_squeeze.py CLOCKS=15,60 OUT=.data/tvsurvey

`Squeeze Momentum Indicator [LazyBear]` is the second most-boosted script in
TradingView's whole community library (118,116 boosts on 2026-11-10, behind one
SMC drawing tool). Its source, read off `pine-facade`, computes

    basis  = sma(close, 20)
    dev    = multKC * stdev(close, 20)        # multKC, NOT mult
    ma     = sma(close, 20)
    rangema= sma(tr, 20)
    sqzOn  = lowerBB > lowerKC and upperBB < upperKC

**`mult` - the input labelled "BB MultFactor", default 2.0 - is declared and
never used.** `dev` is scaled by `multKC` (1.5), the Keltner multiplier. With
both lengths at 20 the two centres are the same `sma(close, 20)`, so the
multiplier cancels on both sides and the published squeeze is exactly

    sqzOn  <=>  stdev(close, 20) < sma(tr, 20)

a comparison of a close-to-close volatility estimator against a range
estimator. That is the statistic `drive-q-from-the-range` measured here
(range-vs-close estimator ratio: 0.648 within strata on FX, 0.667 on 371 of 392
equities), thresholded at 1 and thrown away as a bit.

So this harness asks two things, and neither is "does the squeeze predict
direction" - `statespace-directional-edge.md` closed that at 2% of a spread.

1. **The identity.** Share of bars where `sqzOn` equals `sd < mean_tr`. If it is
   not 1.000 the reduction above is wrong and nothing else here means anything.
2. **What binarising costs.** Three readings against the same forward-volatility
   target: the published bit, the continuous ratio behind it, and the desk's
   shipped incumbent (`tr_percentile`, the 14-bar mean true range ranked in its
   own last 1,500 bars). A bit cannot carry more than the statistic it came
   from, so the measurement is the size of the loss, not its sign.

Three controls, each of which has caught a wrong answer on this desk:

* **Within volatility strata.** `AUC is free on volatility targets` - about 0.80
  on a constant-volatility process and 0.525 within strata, with incumbents
  alone at 0.74-0.78. Every pooled number here is reported beside its
  within-strata twin and only the second one is evidence.
* **Non-overlapping windows.** The forward window is 20 bars, so neighbouring
  rows share 19 of them. Overlap inflates a permutation null and has produced a
  p of 0.015 here out of anchor overlap alone, so the quoted figures use every
  20th bar and the all-bars column is printed beside them to show the gap.
* **A matched iid walk and a block-shuffled twin.** The walk says what the
  statistic reads where no volatility clustering exists; the block shuffle keeps
  the reading's own serial structure and breaks only its alignment to the
  target, which is the null for "the reading is aligned to the future" rather
  than for "the reading has structure".

And a **positive control**, because a null is worthless without power: the same
scoring against a target built to depend on the ratio. If the harness cannot
recover a planted dependence it cannot report its absence.
"""

from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.harness.scalp_cost import SLOW, aggregate, load, m1_sources  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/tvsurvey"))
CLOCKS = tuple(int(k) for k in os.environ.get("CLOCKS", "15,60").split(","))
SEED = int(os.environ.get("SEED", "20261110"))
#: LazyBear's defaults, as read off the source.
BB_LEN = KC_LEN = 20
#: The shipped incumbent's window and rank history, from `expansion.md`.
TR_N, RANK_N = 14, 1500
#: The forward window the target measures, in bars.
HORIZON = 20
BLOCK = 50


def true_range(high, low, close):
    prev = np.concatenate(([close[0]], close[:-1]))
    return np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))


def rolling(values: np.ndarray, n: int, fn) -> np.ndarray:
    """`fn` over every full window of length n, left-padded with nan."""
    if len(values) < n:
        return np.full(len(values), np.nan)
    windows = np.lib.stride_tricks.sliding_window_view(values, n)
    out = np.full(len(values), np.nan)
    out[n - 1 :] = fn(windows)
    return out


def readings(bars: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """The published bit, the ratio behind it, and the shipped incumbent."""
    high, low, close = bars["high"], bars["low"], bars["close"]
    # LazyBear's own comparison is between two **price-unit** quantities, so the
    # identity and the ratio are computed that way or they would not be his.
    # Everything that forecasts is computed on the range as a **fraction of the
    # close** instead: the first run of this harness used price units throughout
    # and the iid-walk arm read |rho| 0.370 for `tr_pct` against a forward
    # volatility a constant-volatility walk cannot possibly carry - a walk's
    # level wanders over 20,000 bars and a price-unit range inherits the level on
    # both sides of the comparison. `volatility-estimators.md` records the same
    # defect reading 0.57 against a true 0.21, with the same fix: divide by the
    # close, and the target too. The bit and the ratio are scale-free already
    # (one is a comparison, the other a quotient), so only the incumbent moved.
    tr = true_range(high, low, close)
    relative = tr / close
    sd = rolling(close, BB_LEN, lambda w: w.std(axis=1, ddof=0))
    mean_tr = rolling(tr, KC_LEN, lambda w: w.mean(axis=1))
    #: LazyBear's own expressions, evaluated as written rather than as reduced,
    #: so the identity below is a measurement and not a restatement.
    basis = rolling(close, BB_LEN, lambda w: w.mean(axis=1))
    dev = 1.5 * sd
    squeeze_on = ((basis - dev) > (basis - mean_tr * 1.5)) & (
        (basis + dev) < (basis + mean_tr * 1.5)
    )
    smooth_tr = rolling(relative, TR_N, lambda w: w.mean(axis=1))
    percentile = np.full(len(close), np.nan)
    for i in range(RANK_N, len(close)):
        window = smooth_tr[i - RANK_N : i]
        good = window[np.isfinite(window)]
        if good.size and np.isfinite(smooth_tr[i]):
            percentile[i] = float((good <= smooth_tr[i]).mean())
    return {
        "sqz_bit": squeeze_on.astype(float),
        "ratio": sd / mean_tr,
        "tr_pct": percentile,
        "_sd": sd,
        "_mean_tr": mean_tr,
        "_relative": relative,
        "_smooth_tr": smooth_tr,
    }


def target_of(relative: np.ndarray, smooth_tr: np.ndarray) -> dict[str, np.ndarray]:
    """Two forward-volatility targets, and two defects this signature prevents.

    The target averages the **raw** relative true range over bars `i+1 .. i+20`.
    Two earlier versions of this function did it differently and both leaked:

    * averaging `smooth_tr` over the forward window instead of the raw range.
      `smooth_tr[i+1]` is a 14-bar mean ending at `i+1`, so it shares 13 of its
      14 bars with the feature `smooth_tr[i]`. The incumbent then read |rho|
      0.425 on a **constant-volatility iid walk**, which has no forecastable
      volatility at all. A walk arm that cannot be zero and is not is the
      cheapest possible detector for this, and it is why the arm is here.
    * true range in **price** units. A walk's level wanders over 20,000 bars and
      a price-unit range inherits the level on both sides, which is the defect
      `volatility-estimators.md` records at 0.57 against a true 0.21.

    `expansion` divides the forward window by the trailing `smooth_tr[i]`, which
    is how a compression-to-expansion question is usually written. It shares no
    *bars* with the numerator but it is the feature's own quantity in the
    denominator, and `tr_pct` is a rank of exactly that - so some of the
    incumbent's score on this target is one quantity dividing by itself. `level`
    has no shared term with any feature and is the number this study leads with.

    Every score is a rank statistic within one series, so nothing is compared
    across instruments in price units.
    """
    n = len(relative)
    forward = np.full(n, np.nan)
    for i in range(n - HORIZON):
        window = relative[i + 1 : i + 1 + HORIZON]
        if np.isfinite(window).all():
            forward[i] = window.mean()
    return {"level": forward, "expansion": forward / smooth_tr}


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    good = np.isfinite(x) & np.isfinite(y)
    if good.sum() < 50 or np.unique(x[good]).size < 2:
        return float("nan")
    rx = np.argsort(np.argsort(x[good])).astype(float)
    ry = np.argsort(np.argsort(y[good])).astype(float)
    rx -= rx.mean()
    ry -= ry.mean()
    denominator = np.sqrt((rx**2).sum() * (ry**2).sum())
    return float((rx * ry).sum() / denominator) if denominator else float("nan")


def auc(score: np.ndarray, label: np.ndarray) -> float:
    """Rank AUC with ties at 0.5. The squeeze bit has nothing but ties."""
    good = np.isfinite(score) & np.isfinite(label)
    score, label = score[good], label[good].astype(bool)
    if label.sum() < 20 or (~label).sum() < 20:
        return float("nan")
    ranks = np.empty(len(score), dtype=float)
    order = np.argsort(score)
    sorted_score = score[order]
    start = 0
    for i in range(1, len(sorted_score) + 1):
        if i == len(sorted_score) or sorted_score[i] != sorted_score[start]:
            ranks[order[start:i]] = (start + i + 1) / 2.0
            start = i
    positives = label.sum()
    negatives = (~label).sum()
    return float((ranks[label].sum() - positives * (positives + 1) / 2) / (positives * negatives))


def walk(bars: dict[str, np.ndarray], rng: np.random.Generator) -> dict[str, np.ndarray]:
    """An iid Student-t(4) geometric walk with this series' own volatility.

    Built by sampling 32 sub-steps a bar, because the high and low of a discrete
    walk are not the continuous expressions and a closed form would make the
    walk's bars the wrong shape - the arm exists to say what the readings give
    where no clustering exists, so its bar geometry has to be comparable.
    """
    close = bars["close"]
    steps = np.diff(np.log(close))
    sigma = float(np.std(steps[np.isfinite(steps)]))
    sub = 32
    draws = rng.standard_t(4, size=(len(close), sub)) * sigma / np.sqrt(sub) / np.sqrt(2.0)
    path = float(np.log(close[0])) + np.cumsum(draws.ravel())
    grid = np.exp(path.reshape(len(close), sub))
    return {
        "high": grid.max(axis=1),
        "low": grid.min(axis=1),
        "close": grid[:, -1],
    }


def shuffled(values: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Block shuffle: keeps the reading's serial structure, breaks alignment."""
    blocks = [values[i : i + BLOCK] for i in range(0, len(values), BLOCK)]
    rng.shuffle(blocks)
    return np.concatenate(blocks)


def score(reading: np.ndarray, target: np.ndarray, strata: np.ndarray) -> dict[str, float]:
    """Pooled and within-strata, on every bar and on non-overlapping bars."""
    thin = np.zeros(len(target), dtype=bool)
    thin[::HORIZON] = True
    label = target > np.nanquantile(target, 0.9)
    out = {
        "rho_all": spearman(reading, target),
        "rho": spearman(np.where(thin, reading, np.nan), target),
        "auc": auc(np.where(thin, reading, np.nan), label.astype(float)),
    }
    out["rows"] = int((np.isfinite(reading) & np.isfinite(target) & thin).sum())
    edges = np.nanquantile(strata, [0.2, 0.4, 0.6, 0.8])
    bands = list(zip([-np.inf, *edges], [*edges, np.inf], strict=True))
    for suffix, mask in (("", thin), ("_all", np.ones(len(thin), dtype=bool))):
        within = []
        for lower, upper in bands:
            inside = (strata > lower) & (strata <= upper) & mask
            value = spearman(np.where(inside, reading, np.nan), target)
            if np.isfinite(value):
                within.append(value)
        out[f"rho_strata{suffix}"] = float(np.mean(within)) if within else float("nan")
        out[f"strata_n{suffix}"] = len(within)
    return out


def main() -> None:
    sources = m1_sources()
    for folder in SLOW:
        if folder.exists():
            for path in sorted(folder.glob("*.1m.npz")):
                sources.setdefault(path.name[: -len(".1m.npz")], path)
    if not sources:
        raise SystemExit("no M1 stores found - run on the lab")
    rng = np.random.default_rng(SEED)
    rows: list[dict[str, object]] = []
    identity: list[dict[str, object]] = []
    for symbol, path in sorted(sources.items()):
        raw = load(path, keys=("high", "low", "close"))
        for clock in CLOCKS:
            bars = aggregate(raw, clock)
            # The identity needs 20 bars; the skill comparison needs the
            # incumbent's 1,500-bar rank history, so the two arms cover
            # different instrument sets and each one says which.
            if len(bars["close"]) < 500:
                continue
            deep = len(bars["close"]) >= RANK_N + HORIZON + 100
            for arm, series in (("real", bars), ("walk", walk(bars, rng))):
                read = readings(series)
                targets = target_of(read["_relative"], read["_smooth_tr"])
                reduced = read["_sd"] < read["_mean_tr"]
                good = np.isfinite(read["_sd"]) & np.isfinite(read["_mean_tr"])
                identity.append(
                    {
                        "symbol": symbol,
                        "clock": clock,
                        "arm": arm,
                        "bars": int(good.sum()),
                        "deep": int(deep),
                        "agree": float((read["sqz_bit"][good] == reduced[good]).mean()),
                        "squeezed": float(read["sqz_bit"][good].mean()),
                    }
                )
                if not deep:
                    continue
                for label, target in targets.items():
                    common = {"symbol": symbol, "clock": clock, "arm": arm, "target": label}
                    for name in ("sqz_bit", "ratio", "tr_pct"):
                        rows.append(
                            {**common, "reading": name, **score(read[name], target, read["tr_pct"])}
                        )
                    for name in ("ratio", "sqz_bit"):
                        rows.append(
                            {
                                **common,
                                "reading": f"{name}_shuffled",
                                **score(shuffled(read[name], rng), target, read["tr_pct"]),
                            }
                        )
                if arm != "real":
                    continue
                # The positive control: a target that depends on the ratio and
                # nothing else, so "the bit carries less" has a known answer to
                # be measured against rather than only a plausible one.
                planted = read["ratio"] * -3.0 + rng.standard_normal(len(read["ratio"]))
                for name in ("ratio", "sqz_bit"):
                    rows.append(
                        {
                            "symbol": symbol,
                            "clock": clock,
                            "arm": "planted",
                            "target": "planted",
                            "reading": name,
                            **score(read[name], planted, read["tr_pct"]),
                        }
                    )
    OUT.mkdir(parents=True, exist_ok=True)
    for name, table in (("squeeze_cells.csv", rows), ("squeeze_identity.csv", identity)):
        with (OUT / name).open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(table[0]))
            writer.writeheader()
            writer.writerows(table)

    print(f"{len(sources)} instruments, clocks {CLOCKS}, horizon {HORIZON}, seed {SEED}")
    print("\n== the identity: sqzOn == (sd(close,20) < mean(TR,20)) ==")
    for clock in CLOCKS:
        cells = [r for r in identity if r["clock"] == clock and r["arm"] == "real"]
        if not cells:
            continue
        agree = [float(r["agree"]) for r in cells]
        print(
            f"  {clock}m: {sum(a >= 1.0 for a in agree)} of {len(cells)} instruments agree on "
            f"1.000000 of bars, min {min(agree):.6f}; squeezed share "
            f"{np.mean([float(r['squeezed']) for r in cells]):.3f} "
            f"[{min(float(r['squeezed']) for r in cells):.3f}, "
            f"{max(float(r['squeezed']) for r in cells):.3f}]; "
            f"{sum(int(r['deep']) for r in cells)} deep enough to score"
        )
    print("\n== skill at the forward volatility, median over instruments ==")
    print("   rho on non-overlapping bars (every 20th); a squeeze is low volatility, so")
    print("   the bit and the ratio point opposite ways and the comparison is on |rho|.")
    print(
        f"  {'clock':>5} {'target':<10}{'arm':<8}{'reading':<16}"
        f"{'rho':>9}{'|rho|':>8}{'rho_all':>9}{'strata':>9}{'str_all':>9}{'auc':>8}{'rows':>7}{'n':>4}"
    )
    for clock in CLOCKS:
        for target in ("level", "expansion", "planted"):
            for arm in ("real", "walk", "planted"):
                for reading in ("sqz_bit", "ratio", "tr_pct", "ratio_shuffled", "sqz_bit_shuffled"):
                    cells = [
                        r
                        for r in rows
                        if r["clock"] == clock
                        and r["arm"] == arm
                        and r["target"] == target
                        and r["reading"] == reading
                    ]
                    if not cells:
                        continue
                    pick = {
                        key: float(np.nanmedian([float(r[key]) for r in cells]))
                        for key in ("rho", "rho_all", "rho_strata", "rho_strata_all", "auc", "rows")
                    }
                    absolute = float(np.nanmedian([abs(float(r["rho"])) for r in cells]))
                    print(
                        f"  {clock:>5} {target:<10}{arm:<8}{reading:<16}{pick['rho']:>9.4f}"
                        f"{absolute:>8.4f}{pick['rho_all']:>9.4f}{pick['rho_strata']:>9.4f}"
                        f"{pick['rho_strata_all']:>9.4f}{pick['auc']:>8.4f}{pick['rows']:>7.0f}"
                        f"{len(cells):>4}"
                    )
    print(f"\nwrote {OUT}/squeeze_cells.csv and {OUT}/squeeze_identity.csv")


if __name__ == "__main__":
    main()
