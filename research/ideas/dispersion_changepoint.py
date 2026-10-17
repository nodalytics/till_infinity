"""Does a change-point posterior add to a dispersion forecast, or restate it?

`cusum.md` measured BOCPD's three readings adding **+0.035 to +0.043** to HAR
on 1h FX log Parkinson variance, at h=1, 5 and 20, with the constant-sigma
control null. It left two questions open, and both of them could make that
number worth nothing.

## 1. Does it survive more history?

HAR carries three backward averages and a memory of 22 bars. The shelf's 48-lag
ridge reads **+0.198** on fx_cross 1h h=20 against HAR's +0.110, so plain extra
history is worth **+0.088** where BOCPD was worth +0.0428 - twice as much, from
a model with no change-point in it at all. A run-length posterior is partly a
long-memory statistic by construction: "how long has this held" is a summary of
the same bars the extra lags see. So the question is not whether BOCPD beats
HAR. It is whether `lin48 + bocpd` beats `lin48`.

## 2. Is the increment the change-point, or the variance it infers?

`Changepoint` publishes three numbers and they are not the same kind of thing.
`changepoint` and `run_length` are statements about *when the regime turned*.
`sd` is the predictive standard deviation, marginalised over run lengths - and
that is a volatility estimate, which is **the quantity being forecast**. An
increment that is entirely `sd` would mean the member is a competent variance
filter and says nothing about change-points.

So the three readings are split and each half is fitted on its own:

* `cp` - `changepoint` and `log1p(run_length)`. The regime claim.
* `sd` - the predictive standard deviation alone. The variance claim.
* `bocpd` - all three, as `cusum.md` ran it.

Crossed with both baselines, which gives the whole answer in one table: if
`lin48+cp` beats `lin48` the change-point carries something no amount of lags
provides, and if it does not, the +0.04 was memory and variance wearing a
posterior.

## What is held fixed

Everything that made the last run's baseline reproduce. The series is cut to
the last `LIMIT` bars, `har` is also fitted with `dispersion_ml`'s own fixed
ridge as a reference column, and a guard prints a warning when a traded class
at h=20 falls below +0.05 - `dispersion-forecast.md` has +0.103, +0.110 and
+0.791 for those cells and the table is not to be read until they come back.
Controls: a shuffled target, and the Deriv volatility family whose generator
fixes sigma.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
for q in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(q))

from cusum_regime import REFERENCE_RIDGE, _bocpd, _fit, _plain  # noqa: E402
from dispersion_ml import LIMIT, SIZE, _design, parkinson  # noqa: E402
from pattern_fingerprint import CACHE, classify, load  # noqa: E402

FRAMES = ("1h", "4h")
TRADED = ("fx_major", "fx_cross", "metal")
CONTROLS = ("volatility",)
PER_CLASS = 6
HORIZONS = (1, 5, 20)
SEED = 20261017

#: Arms, as (name, baseline, extra columns). `None` extras is the baseline.
BASES = ("har", "lin48")
EXTRAS = ("cp", "sd", "bocpd")

#: Which of `_bocpd`'s three columns each extra uses. `_bocpd` returns
#: (changepoint, log1p(run_length), sd) per bar.
COLUMNS: dict[str, tuple[int, ...]] = {
    "cp": (0, 1),
    "sd": (2,),
    "bocpd": (0, 1, 2),
}

#: The published value for each h=20 traded cell, from dispersion-forecast.md.
#: The guard reads these rather than one shared floor, because metals is an
#: order of magnitude above FX and a single floor would pass a broken metals.
KNOWN = {("fx_major", 0.103), ("fx_cross", 0.110), ("metal", 0.791)}


def _lags(logvar: np.ndarray, start: int, rows: int, wrap: bool = False) -> np.ndarray:
    """`SIZE` raw lags of `logvar`, from row `start`.

    **`wrap=True` reproduces a lookahead in `dispersion_ml`'s own design.** It
    builds `logvar[i - k]` for `k` up to `SIZE - 1 = 47` starting at
    `i = max(LAGS) = 22`, so the index goes negative and Python wraps it to the
    **end of the series** - which is the test half. The first
    `SIZE - start = 26` rows of a twelve-thousand-row training design therefore
    contain future values.

    Twenty-six rows of twelve thousand should be worth nothing, and the arm is
    kept here so that "should" becomes a number instead of an assumption. The
    honest design starts where every lag exists.
    """
    if wrap:
        return np.asarray(
            [[float(logvar[i - k]) for k in range(SIZE)] for i in range(start, start + rows)],
            dtype=float,
        )
    return np.asarray(
        [
            [float(logvar[i - k]) for k in range(SIZE)]
            for i in range(start, start + rows)
            if i >= SIZE - 1
        ],
        dtype=float,
    )


def score(bars, frame: str) -> dict[tuple[int, str], float]:
    """Every arm at every horizon for one instrument.

    BOCPD is run **once** per instrument and frame rather than once per
    horizon: it is an online filter over the series and does not depend on the
    target, so re-running it three times would only cost three times as long.
    """
    bars = {k: v[-LIMIT:] for k, v in bars.items()}
    logvar = parkinson(bars["high"], bars["low"])
    if len(logvar) < 600 + SIZE:
        return {}
    readings = _bocpd(logvar, frame)

    out: dict[tuple[int, str], float] = {}
    for horizon in HORIZONS:
        x, y, start = _design(logvar, horizon)
        if len(y) < 600:
            continue
        # **Every arm is scored on the same rows.** The 48-lag design cannot
        # state a row before bar `SIZE - 1`, and `_design` starts at
        # `max(LAGS) = 22`, so the first `SIZE - 1 - start` rows are dropped
        # from *all* of them rather than only from the one that cannot fill
        # them. Scoring HAR on rows lin48 never saw would make the comparison
        # a comparison of samples.
        skip = max(0, SIZE - 1 - start)
        x, y = x[skip:], y[skip:]
        first = start + skip
        cut = len(y) // 2
        base = float(y[:cut].mean())
        rows = slice(first, first + len(y))
        designs = {"har": x, "lin48": _lags(logvar, first, len(y))}

        out[(horizon, "har.reference")] = _plain(x, y, cut, base)
        # The reference's own leaky design, on the reference's own rows, so the
        # wrap-around is priced rather than assumed to be harmless.
        leaky_x, leaky_y, leaky_start = _design(logvar, horizon)
        leaky = _lags(logvar, leaky_start, len(leaky_y), wrap=True)
        leaky_cut = len(leaky_y) // 2
        out[(horizon, "lin48.leaky")] = _fit(
            leaky, leaky_y, leaky_cut, float(leaky_y[:leaky_cut].mean())
        )
        for name, design in designs.items():
            out[(horizon, name)] = _fit(design, y, cut, base)
            for extra, picks in COLUMNS.items():
                wide = np.hstack([design, readings[rows][:, picks]])
                out[(horizon, f"{name}+{extra}")] = _fit(wide, y, cut, base)
        shuffled = y.copy()
        np.random.default_rng(SEED).shuffle(shuffled)
        out[(horizon, "shuffled")] = _fit(x, shuffled, cut, float(shuffled[:cut].mean()))
    return out


def main() -> None:
    print(
        "Does a change-point posterior add to a dispersion forecast, or restate it?\n"
        "Target: mean log Parkinson variance over the next h bars. Fitted on each\n"
        "series' first half, scored only on the second, median across instruments.\n"
        "Two baselines - HAR's 3 averages and 48 raw lags - each crossed with the\n"
        "change-point pair, the inferred predictive sd, and all three together.\n"
        f"Reference ridge {REFERENCE_RIDGE:g}, last {LIMIT} bars, {SIZE} lags.\n",
        flush=True,
    )
    groups: dict[str, list[str]] = {}
    for path in sorted(CACHE.glob("*.1h.npz")):
        name = path.name[: -len(".1h.npz")]
        groups.setdefault(classify(name), []).append(name)
    wanted = {k: v[:PER_CLASS] for k, v in groups.items() if k in TRADED + CONTROLS}
    print("classes:", ", ".join(sorted(wanted)), flush=True)

    for frame in FRAMES:
        per_class: dict[str, list[dict]] = {}
        for klass, names in sorted(wanted.items()):
            for name in names:
                bars = load(name, frame)
                if bars is None:
                    continue
                got = score(bars, frame)
                if got:
                    per_class.setdefault(klass, []).append(got)

        for horizon in HORIZONS:
            print(f"\n=== {frame}, h={horizon}")
            print(
                f"{'class':>12} {'ref':>8} {'har':>8} {'+cp':>8} {'+sd':>8} {'+all':>8}   "
                f"{'lin48':>8} {'+cp':>8} {'+sd':>8} {'+all':>8}   {'leak':>8} {'shuf':>8}  n"
            )
            for klass, rows in sorted(per_class.items()):

                def med(key: str) -> float:
                    vals = [r[(horizon, key)] for r in rows if (horizon, key) in r]
                    return float(np.median(vals)) if vals else float("nan")

                har, lin = med("har"), med("lin48")
                ref = med("har.reference")
                if klass in TRADED and horizon == 20:
                    published = next((v for k, v in KNOWN if k == klass), 0.05)
                    floor = published * 0.6
                    if ref < floor:
                        print(
                            f"  WARN {klass}: reference reads {ref:+.4f}, below the "
                            f"{floor:+.4f} floor, which is 60% of the published "
                            f"{published:+.3f}. Do not read the increments."
                        )
                print(
                    f"{klass:>12} {ref:+8.4f} {har:+8.4f} "
                    f"{med('har+cp') - har:+8.4f} {med('har+sd') - har:+8.4f} "
                    f"{med('har+bocpd') - har:+8.4f}   "
                    f"{lin:+8.4f} {med('lin48+cp') - lin:+8.4f} "
                    f"{med('lin48+sd') - lin:+8.4f} {med('lin48+bocpd') - lin:+8.4f}   "
                    f"{med('lin48.leaky') - lin:+8.4f} {med('shuffled'):+8.4f}  {len(rows)}",
                    flush=True,
                )
            print(
                "  (+cp, +sd, +all are increments over the baseline to their left;"
                " leak is the reference's wrapped design minus the honest one;"
                " shuf must read ~0)"
            )


if __name__ == "__main__":
    main()
