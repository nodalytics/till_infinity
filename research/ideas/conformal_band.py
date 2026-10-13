"""A band with no assumed shape, and why its calibration is not the evidence.

`statespace-tail-shape.md` left the forecast-distribution question in a precise
state. **No Gaussian band is calibrated on real data** - the PIT flatness runs
18 to 461 against the 1.0 that calibration means - and quoting the band as a
Student-t with the mean and variance held fixed, so it can only reshape, **over
corrects**. Two parametric shapes, two failures in opposite directions.

`robust.py` was nominated as the lever and that was already withdrawn: it
inflates the measurement variance when an innovation is surprising, which
changes the *gain* and leaves the predictive density Gaussian. It cannot move a
PIT, because a PIT is a statement about the density's shape.

So the remaining move is to **stop assuming a shape**. The predictive CDF at
time `t` is the empirical distribution of the residuals seen before `t`, which
is conformal prediction, and the band is read off its quantiles.

## The trap, stated before the measurement rather than after

**A conformal PIT is uniform almost by construction.** If the predictive CDF is
the empirical CDF of past residuals then the PIT of a new residual is its
**rank** among the old ones, and a rank among exchangeable draws is uniform by
definition. A flatness near 1.0 here is therefore close to tautological and is
**not** evidence of a better forecast.

So the PIT is a *check* - it says the machinery works - and **CRPS is the
evidence**, because a band can be perfectly calibrated and useless by being
wide. The question is whether a shape-free band is calibrated *and* no wider
than the Gaussian one, not whether it is calibrated.

The same trap in reverse is why the Gaussian arm is kept: it is sharp and
mis-shaped, so the pair brackets the answer.

## Three shape-free arms, because exchangeability is the thing that fails

Plain conformal assumes the residuals are exchangeable. On a real series they
are not - volatility clusters, so a quiet stretch and a violent one are not
draws from one distribution - and that is the failure adaptive conformal exists
for.

* **conformal** - the rank among *all* past residuals. Exact under
  exchangeability, and the arm that shows what exchangeability costs when it is
  false.
* **rolling** - the rank among the last `MEMORY` residuals, which forgets a
  regime rather than averaging over it.
* **adaptive** - Gibbs and Candes' correction: carry a per-level offset and
  step it by `gamma` whenever the realised coverage misses its target. This is
  the method `vol/envelope.py` already runs over the volatility envelope and
  `structures/conformal.py` over a level's zone, pointed at a third interval.

Written here rather than imported: `statespace` does not depend on a sibling
model, and this harness is measuring whether a *statespace* member should carry
the machinery at all.

## The controls

* **planted** - standardised Student-t draws, where a shape-free band must
  recover calibration that the Gaussian cannot, and standardised **normal**
  draws, where it must not beat the Gaussian, since there the Gaussian is
  correct by construction and anything beating it is an artefact;
* **the generated instruments** - verified constant-volatility GBM, so their
  residuals are genuinely exchangeable and the three shape-free arms should
  agree with each other and with the Gaussian.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import relationship_screen as screen  # noqa: E402

#: Forecast horizons in bars.
HORIZONS = tuple(int(h) for h in os.environ.get("HORIZONS", "1,5,20,60").split(","))
#: Trailing bars the walk's sigma is estimated over.
SPAN = int(os.environ.get("SPAN", "100"))
#: Residuals the rolling arm remembers.
MEMORY = int(os.environ.get("MEMORY", "500"))
#: Bins for the PIT histogram.
BINS = int(os.environ.get("BINS", "20"))
#: Residuals required before an arm is allowed to quote a band.
WARM = int(os.environ.get("WARM", "200"))
#: Coverage levels the adaptive arm carries a corrector for.
SHARES = (0.5, 0.8, 0.9, 0.95, 0.99)
#: Step sizes aggregated by the adaptive arm.
GAMMAS = (0.005, 0.02, 0.08)


def standardised(levels, horizon: int, span: int = SPAN):
    """`(y - mu)/sigma` for the walk's forecast, one per usable bar.

    The same construction `tail_shape.py` uses, so the arms here are comparable
    to the Gaussian and Student-t numbers already published: `mu` is the current
    level and `sigma` the trailing spread scaled by `sqrt(horizon)`.
    """
    import numpy as np

    moves = np.diff(levels)
    out = []
    for at in range(span, len(levels) - horizon):
        window = moves[at - span : at]
        spread = float(np.std(window))
        if spread <= 0:
            continue
        out.append(
            float(levels[at + horizon] - levels[at]) / (spread * math.sqrt(horizon))
        )
    return np.asarray(out)


def flatness(values, bins: int = BINS) -> float:
    """Chi-square of the PIT histogram against uniform, per degree of freedom."""
    import numpy as np

    values = np.asarray([v for v in values if math.isfinite(v)])
    if len(values) < 200:
        return float("nan")
    counts, _ = np.histogram(
        np.clip(values, 0.0, 1.0 - 1e-12), bins=bins, range=(0.0, 1.0)
    )
    want = len(values) / bins
    return float(np.sum((counts - want) ** 2 / want) / (bins - 1))


def coverage(pits, share: float) -> float:
    low, high = (1.0 - share) / 2.0, 1.0 - (1.0 - share) / 2.0
    usable = [p for p in pits if math.isfinite(p)]
    if not usable:
        return float("nan")
    return float(sum(1 for p in usable if low <= p <= high) / len(usable))


def crps_from_quantiles(quantiles, outcome: float) -> float:
    """CRPS by the quantile-loss identity, so every arm is scored one way.

    `CRPS = 2 * integral of pinball loss over the quantile level`, which needs
    only a set of quantiles and never a density - so a shape-free band and a
    Gaussian one are scored by the identical instrument. A closed form for the
    Gaussian would be a second instrument and a second set of assumptions.
    """
    total, last = 0.0, 0.0
    for tau, value in quantiles:
        loss = (
            (outcome - value) * tau
            if outcome >= value
            else (value - outcome) * (1.0 - tau)
        )
        total += loss * (tau - last)
        last = tau
    return 2.0 * total


#: The quantile grid every arm is scored on.
TAUS = tuple(i / 50.0 for i in range(1, 50))


def gaussian_arm(history, z):
    """The band the package quotes now: standard normal, shape assumed."""
    from scipy import stats

    _ = history
    return stats.norm.cdf(z), [(t, float(stats.norm.ppf(t))) for t in TAUS]


def student_arm(history, z, nu: float = 4.0):
    """The parametric reshape, with the variance held at one so it can only reshape."""
    from scipy import stats

    _ = history
    scale = math.sqrt((nu - 2.0) / nu)
    return stats.t.cdf(z / scale, nu), [
        (t, float(stats.t.ppf(t, nu) * scale)) for t in TAUS
    ]


def empirical_arm(history, z):
    """The rank among past residuals: conformal, and no shape at all."""
    import numpy as np

    past = np.asarray(history)
    pit = float((np.searchsorted(np.sort(past), z, side="right") + 0.5) / (len(past) + 1))
    return pit, [(t, float(np.quantile(past, t))) for t in TAUS]


class Adaptive:
    """Gibbs and Candes' corrector per coverage level, aggregated over `gamma`.

    One offset per `(share, gamma)`: when the realised interval misses, the
    offset widens by `gamma * (1 - share)`, and when it covers it narrows by
    `gamma * share`, which is the update whose fixed point is the target
    coverage. The aggregate over `gamma` is the mean, which is the part of AgACI
    that matters here - a single step size is either too slow for a regime
    change or too noisy in a calm stretch, and there is no way to know which in
    advance.
    """

    def __init__(self):
        self.offsets = {(s, g): 0.0 for s in SHARES for g in GAMMAS}

    @staticmethod
    def nearest(share: float) -> float:
        """The carried coverage level closest to `share`.

        Clamping to the *range* of `SHARES` is not the same as snapping to a
        member of it, and the first version did the former: a quantile level of
        0.98 asks for a coverage of 0.96, which has no corrector, and the
        lookup raised `KeyError: (0.96, 0.005)`.
        """
        return min(SHARES, key=lambda s: abs(s - share))

    def width(self, history, share: float) -> float:
        import numpy as np

        share = self.nearest(share)
        base = float(np.quantile(np.abs(history), share))
        shift = statistics.mean(self.offsets[(share, g)] for g in GAMMAS)
        return max(base + shift, 1e-9)

    def observe(self, history, z: float) -> None:
        import numpy as np

        for share in SHARES:
            base = float(np.quantile(np.abs(history), share))
            for gamma in GAMMAS:
                key = (share, gamma)
                wide = max(base + self.offsets[key], 1e-9)
                covered = abs(z) <= wide
                self.offsets[key] += gamma * ((1.0 - share) if not covered else -share)

    def readings(self, history, z: float):
        """A PIT from the nested intervals, and the quantile set for CRPS."""
        import numpy as np

        widths = sorted((self.width(history, s), s) for s in SHARES)
        # The PIT is read off the narrowest interval containing `z`, which is
        # the only PIT nested intervals define.
        inside = next((s for w, s in widths if abs(z) <= w), None)
        if inside is None:
            pit = 1.0 - 1e-9 if z > 0 else 1e-9
        else:
            half = (1.0 - inside) / 2.0
            pit = 1.0 - half if z > 0 else half
        middle = float(np.median(history))
        quantiles = []
        for t in TAUS:
            share = abs(2.0 * t - 1.0)
            wide = self.width(history, share)
            quantiles.append((t, middle + (wide if t > 0.5 else -wide)))
        return pit, quantiles


def score(zs):
    """Every arm on one standardised series, predict-then-update throughout."""
    import numpy as np

    if len(zs) < WARM + 400:
        return {}
    arms = {name: {"pit": [], "crps": []} for name in ("gaussian", "student", "conformal", "rolling", "adaptive")}
    adaptive = Adaptive()
    for at in range(WARM, len(zs)):
        z = float(zs[at])
        history = zs[:at]
        rolling = zs[max(0, at - MEMORY) : at]
        for name, (pit, quantiles) in (
            ("gaussian", gaussian_arm(history, z)),
            ("student", student_arm(history, z)),
            ("conformal", empirical_arm(history, z)),
            ("rolling", empirical_arm(rolling, z)),
            ("adaptive", adaptive.readings(history, z)),
        ):
            arms[name]["pit"].append(pit)
            arms[name]["crps"].append(crps_from_quantiles(quantiles, z))
        adaptive.observe(history, z)
    out = {}
    for name, got in arms.items():
        out[name] = {
            "flat": flatness(got["pit"]),
            "crps": float(np.mean(got["crps"])),
            "cover90": coverage(got["pit"], 0.9),
            "cover50": coverage(got["pit"], 0.5),
            "n": len(got["pit"]),
        }
    return out


def report(label: str, got) -> None:
    if not got:
        print(f"{label:<28}  too short")
        return
    base = got["gaussian"]["crps"]
    for name in ("gaussian", "student", "conformal", "rolling", "adaptive"):
        row = got[name]
        print(
            f"{label if name == 'gaussian' else '':<28}{name:<11}"
            f"{row['flat']:>9.1f}{row['crps']:>10.4f}"
            f"{row['crps'] / base if base > 0 else float('nan'):>9.3f}"
            f"{row['cover50']:>9.3f}{row['cover90']:>9.3f}{row['n']:>8}"
        )


def planted() -> None:
    """Normal draws, where the Gaussian must win, and t draws, where it must not."""
    import numpy as np
    from scipy import stats

    print("=" * 104)
    print("ARM 0  planted: the Gaussian is correct on one row and wrong on the other")
    print("=" * 104)
    print(
        f"{'planted':<28}{'arm':<11}{'flat':>9}{'crps':>10}{'vs g':>9}"
        f"{'cov50':>9}{'cov90':>9}{'n':>8}"
    )
    rng = np.random.default_rng(11)
    n = 6000
    report("standard normal", score(rng.standard_normal(n)))
    nu = 3.0
    draws = stats.t.rvs(nu, size=n, random_state=5) * math.sqrt((nu - 2.0) / nu)
    report(f"student t, nu={nu:g}", score(draws))
    print(
        "\nOn normal draws the Gaussian arm is correct **by construction**, so\n"
        "any arm beating its CRPS there is an artefact rather than a finding.\n"
        "On t draws the Gaussian is wrong by construction and a shape-free arm\n"
        "has something to recover. The pair is what makes the real rows readable."
    )


def main() -> None:
    print(
        f"horizons {HORIZONS}, sigma over {SPAN} trailing bars, rolling memory\n"
        f"{MEMORY}, {WARM} residuals before any arm quotes a band\n"
    )
    planted()

    traded = [n for n in screen.TRADED if screen.load(n) is not None][:8]
    generated = [
        n for n in screen.universe(screen.FRAME, cap=40) if screen.load(n) is not None
    ][:6]

    for horizon in HORIZONS:
        print("\n" + "=" * 104)
        print(f"ARM 1  real instruments at h={horizon}")
        print("=" * 104)
        print(
            f"{'instrument':<28}{'arm':<11}{'flat':>9}{'crps':>10}{'vs g':>9}"
            f"{'cov50':>9}{'cov90':>9}{'n':>8}"
        )
        rows = {}
        for name in traded + generated:
            got = screen.load(name)
            if got is None:
                continue
            zs = standardised(got[1], horizon)
            scored = score(zs)
            if scored:
                rows[name] = scored
        for name in traded:
            if name in rows:
                report(name, rows[name])
        for name in generated:
            if name in rows:
                report(f"*{name}", rows[name])
        if not rows:
            continue
        print(f"\n{'median over':<28}{'arm':<11}{'flat':>9}{'crps':>10}{'vs g':>9}")
        for kind, names in (("traded", traded), ("generated", generated)):
            here = [rows[n] for n in names if n in rows]
            if not here:
                continue
            for arm in ("gaussian", "student", "conformal", "rolling", "adaptive"):
                print(
                    f"{kind if arm == 'gaussian' else '':<28}{arm:<11}"
                    f"{statistics.median(r[arm]['flat'] for r in here):>9.1f}"
                    f"{statistics.median(r[arm]['crps'] for r in here):>10.4f}"
                    f"{statistics.median(r[arm]['crps'] / r['gaussian']['crps'] for r in here):>9.3f}"
                )
    print(
        "\n**Read the CRPS column, not the flatness one.** A conformal PIT is a\n"
        "rank among past residuals and a rank is uniform by construction, so a\n"
        "flatness near 1.0 is close to tautological. The question is whether a\n"
        "shape-free band is calibrated *and* no wider than the Gaussian, which\n"
        "is what `vs g` says."
    )


if __name__ == "__main__":
    main()
