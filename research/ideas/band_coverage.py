"""Does a coverage-addressed band hold its coverage, out past where it was counted?

Asked on 2026-10-17: "wire the t band to a consumer". `statespace/tails.py` has
been measured and shipped since `one-bar-band.md` - a Student-t with 3 to 5
degrees of freedom beat a Gaussian on PIT flatness *and* CRPS on 64 of 64
out-of-sample feed-frames - and nothing has ever called it. `Readout.quantiles`
and `Readout.band_covering` sat side by side with no rule saying which to use,
and the rule is not guessable: a 2-sigma band is about right while a 4-sigma
band is breached **88 times** more often than its Gaussian label promises.

`facade.Readout.covering` is that rule. It serves the body from the measured
quantiles and the tail from the fitted t, **anchored** to the measured edge:
each side of the 0.90 band is grown by the ratio of the t's reach at the asked
coverage to its reach at 0.90. The counted part sets the scale, the assumed
part sets only the shape.

## What is actually in question

Not whether the t beats a Gaussian on shape - that is measured and on record.
What is in question is the **anchoring**, and the unit tests already pin down
the trade in a vacuum:

* where `spread` is the right scale for the residuals, the pure t is exact and
  anchoring costs a little sampling noise in the 0.90 edge;
* where `spread` is wrong by a factor, the pure t's error is **proportional to
  the mistake** and the anchored arm does not move at all.

So the whole question is whether production's `spread` is the right scale. There
is a reason to think it is not: `statespace-river-against-members.md` measured
the pool's PIT flatness at **43.05**, which is the signature of a filter whose
sd is too small. If that is right, the pure t inherits it and the anchored arm
does not. This harness is what decides it, on real bars, one step ahead.

## Three arms and a control

Every arm is asked for the same central coverage on the same bar and scored
against the **next** close, so nothing here is in-sample:

* `covering` - measured inside the grid, anchored outside it;
* `pure t` - `band_covering`, the fitted t over the filter's own sd;
* `gaussian` - `band(z)` at the Gaussian multiplier for the same coverage.

The control is a **Gaussian random walk** fed through the identical path. On it
the Gaussian arm must win and both t arms must come out too wide. If that does
not happen the harness is measuring something other than what it claims, and no
reading on real bars means anything.
"""

from __future__ import annotations

import math
import random
import statistics
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
for q in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(q))

from pattern_fingerprint import CACHE, classify, load  # noqa: E402

from till_infinity.statespace.facade import Desk  # noqa: E402

#: The frames the cache holds and `tails.DOF` has a measured index for.
FRAMES = ("1h", "4h")
#: Central coverages asked for. 0.95 is inside the measured grid's reach, the
#: rest are past it - which is the half of the range this is about.
TARGETS = (0.95, 0.99, 0.995, 0.999)
TRADED = ("fx_major", "fx_cross", "metal")
PER_CLASS = 8
#: Bars per instrument. `facade.LEAST` is 200 residuals before an interval is
#: offered at all, so a short series would score almost nothing.
LIMIT = 8000
#: Measurement variance as a share of the squared median one-bar move.
#:
#: **The first version of this harness guessed 0.05 and every arm was broken.**
#: `noise` is the filter's measurement variance `R`, and at 5% of a bar move it
#: says each close is known to a twentieth of a bar: the gain goes to one, the
#: filter sits exactly on price, and the one-step predictive spread collapses to
#: something ~20x narrower than the next bar's move. A nominal 0.95 band was
#: breached **93.5% of the time on a Gaussian random walk**, which is what the
#: control exists to catch.
#:
#: So it is not guessed here either. The walk control has a known right answer -
#: a Gaussian band on Gaussian data must read `x = 1.00` - and PHASE ONE sweeps
#: `R` against it and reports which value calibrates. The panel then runs at
#: that value and its neighbours, so the ranking of the arms can be read against
#: a scale that was fitted to a control rather than to the data in question.
NOISES = (0.25, 0.5, 1.0, 2.0, 4.0)
SEED = 20261017


def _gaussian_walk(n: int, rng: random.Random) -> dict[str, np.ndarray]:
    """The control: a driftless Gaussian walk, where the Gaussian arm is right."""
    step = 0.001
    closes = [100.0]
    for _ in range(n):
        closes.append(closes[-1] * math.exp(rng.gauss(0.0, step)))
    price = np.asarray(closes[1:], dtype=float)
    return {
        "time": np.arange(len(price), dtype=float) * 3600.0,
        "open": price,
        "high": price,
        "low": price,
        "close": price,
    }


def _normal_reach(coverage: float) -> float:
    """The Gaussian multiplier for a central interval, so the arm is honest."""
    return statistics.NormalDist().inv_cdf(0.5 * (1.0 + coverage))


def score(bars: dict[str, np.ndarray], frame: str, share: float, feed: str) -> dict:
    """Walk one series bar by bar, band the next close, and count the breaches.

    The readout at bar `i` carries `spread`, the one-step spread of the **next**
    observation, and quantiles built from exactly that sd - so bar `i+1`'s close
    is the out-of-sample draw each band is scored against.
    """
    closes = bars["close"]
    when = bars["time"]
    if len(closes) < 1000:
        return {}
    moves = np.abs(np.diff(closes))
    typical = float(np.median(moves[moves > 0])) if np.any(moves > 0) else 0.0
    if typical <= 0:
        return {}
    noise = (share * typical) ** 2

    desk = Desk()
    out: dict = {
        "sources": {"measured": 0, "anchored": 0, "assumed": 0},
        "cells": {},
    }
    for target in TARGETS:
        for arm in ("covering", "pure t", "gaussian"):
            out["cells"][(target, arm)] = [0, 0]  # scored, breached

    reach = {target: _normal_reach(target) for target in TARGETS}
    for i in range(len(closes) - 1):
        got = desk.read(feed, frame, float(when[i]), float(closes[i]), noise)
        if not got.warm:
            continue
        nxt = float(closes[i + 1])
        for target in TARGETS:
            band = got.covering(target)
            out["sources"][band.source] += 1
            arms = {
                "covering": (band.low, band.high),
                "pure t": got.band_covering(target),
                "gaussian": got.band(reach[target]),
            }
            for arm, (low, high) in arms.items():
                cell = out["cells"][(target, arm)]
                cell[0] += 1
                if not low <= nxt <= high:
                    cell[1] += 1
    return out


def merge(into: dict, got: dict) -> None:
    if not got:
        return
    if not into:
        into.update(
            {
                "sources": dict(got["sources"]),
                "cells": {k: list(v) for k, v in got["cells"].items()},
            }
        )
        return
    for key, value in got["sources"].items():
        into["sources"][key] += value
    for key, (scored, breached) in got["cells"].items():
        into["cells"][key][0] += scored
        into["cells"][key][1] += breached


def report(label: str, pooled: dict) -> None:
    if not pooled:
        print(f"\n=== {label}: nothing scored")
        return
    seen = pooled["sources"]
    total = sum(seen.values()) or 1
    print(f"\n=== {label}")
    print(
        f"  arms: measured {seen['measured'] / total:.2f} of asks, "
        f"anchored {seen['anchored'] / total:.2f}, assumed {seen['assumed'] / total:.2f}"
    )
    print(f"  {'target':>7}{'arm':>11}{'n':>9}{'realised':>10}{'breach':>9}{'wanted':>8}{'x':>7}")
    for target in TARGETS:
        for arm in ("covering", "pure t", "gaussian"):
            scored, breached = pooled["cells"][(target, arm)]
            if not scored:
                continue
            realised = 1.0 - breached / scored
            wanted = 1.0 - target
            ratio = (breached / scored) / wanted if wanted > 0 else float("nan")
            print(
                f"  {target:>7.3f}{arm:>11}{scored:>9}{realised:>10.4f}"
                f"{breached / scored:>9.4f}{wanted:>8.4f}{ratio:>7.2f}"
            )


def main() -> None:
    print(
        "Coverage-addressed bands, one step ahead, scored on the next close.\n"
        "`x` is realised breach over wanted breach: 1.00 is calibrated, above\n"
        "is too narrow, below is too wide. The walk control must favour the\n"
        "gaussian arm; if it does not, read nothing else here.\n"
    )
    rng = random.Random(SEED)
    groups: dict[str, list[str]] = {}
    for path in sorted(CACHE.glob("*.1h.npz")):
        name = path.name[: -len(".1h.npz")]
        groups.setdefault(classify(name), []).append(name)

    print("\n################ phase one: what R calibrates the control")
    print("  The gaussian arm on a gaussian walk has a known right answer, so")
    print("  this picks R rather than assuming it. `x` nearest 1.00 at 0.95 wins.\n")
    best: dict[str, float] = {}
    for frame in FRAMES:
        rows = []
        for share in NOISES:
            walk: dict = {}
            merge(walk, score(_gaussian_walk(LIMIT, rng), frame, share, f"WALK{share}"))
            if not walk:
                continue
            scored, breached = walk["cells"][(0.95, "gaussian")]
            got = (breached / scored) / 0.05 if scored else float("nan")
            rows.append((share, got))
            print(f"  {frame}  R at {share:>5.2f} of a bar move -> gaussian x {got:>8.2f}")
        if rows:
            best[frame] = min(rows, key=lambda r: abs(math.log(max(r[1], 1e-9))))[0]
            print(f"  {frame}: calibrated at R = {best[frame]:.2f}\n")

    print("\n################ phase two: the panel, at the calibrated R and either side")
    for frame in FRAMES:
        pick = best.get(frame)
        if pick is None:
            continue
        near = [s for s in NOISES if abs(math.log(s / pick)) < 1.5]
        for share in near:
            print(
                f"\n---------------- {frame}, R at {share:.2f}"
                + ("  <- calibrated" if share == pick else "")
            )
            walk: dict = {}
            merge(walk, score(_gaussian_walk(LIMIT, rng), frame, share, f"CTRL{share}"))
            report(f"gaussian walk control, {frame}", walk)
            for label in TRADED:
                if label not in groups:
                    continue
                pooled: dict = {}
                for name in sorted(groups[label])[:PER_CLASS]:
                    bars = load(name, frame)
                    if bars is None:
                        continue
                    cut = {k: v[-LIMIT:] for k, v in bars.items()}
                    merge(pooled, score(cut, frame, share, name))
                report(f"{label}, {frame}", pooled)


if __name__ == "__main__":
    main()
