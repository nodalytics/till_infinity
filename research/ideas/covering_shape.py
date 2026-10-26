"""Why does a correctly-scaled spread make a worse band?

Three explanations for the published spread being three times too small have
been tested and killed: composition (`adapting-strata.md` - planted
clustering, a planted daily cycle and the real estimator shape all absorb at
`E[z^2]` near 1.03), units (`normalised_input` moves it by at most 0.015), and
heavy tails (`student_t_target` fits `nu` at 12 to 50 with a likelihood gap of
+0.001 to +0.006 a bar, and the implied variance only recovers the sample).

What is left is mechanical. At 1h with the clamp released every member reads
`E[z^2]` of 1.01 to 1.05 and the pool reads 2.05 under `shrinking`, so the
residual is the dropped between-member term - and `mixture`, which restores it,
fixes the spread (0.93 to 0.98) and **degrades the band**: breach 0.110 to
0.112 against a 0.090-0.110 line where `shrinking` reads 0.099 to 0.101.

## The construction that makes that possible

`facade.Desk._quantiles` is exact about it:

    sd = sqrt(member.variance + noise)
    band(level) = member.value + sd * sorted(past surprises)[level]

Each past surprise was divided by **its own** instantaneous predictive sd, and
the band multiplies the quantile of those by **today's**. That is only correct
if the standardised residuals are identically distributed - and a rule that
adds a spiky between-member term makes them less so, because the thing being
divided by now jumps around for a reason unrelated to the next observation.

So the question is not the level of the spread. It is whether the band's
**shape** should be estimated in units that move.

## Four band constructions on one fold

The fold is done once per rule and clamp, recording the pre-update prediction,
the pre-update predictive variance and the observation, and every band is then
built offline from the same three series - so nothing here is a difference in
the filter.

* `live` - the shipped construction, quantiles of `e / sd_now`, times `sd_now`;
* `raw` - quantiles of the residual itself, no standardising and no rescaling.
  It cannot follow a change in volatility, which is the cost the shipped
  construction is paying to avoid;
* `smoothed` - standardise by a **long exponentially weighted** predictive
  variance and rescale by the same, so the band's shape stops moving when the
  spread spikes while its level still follows;
* `gaussian` - a fixed normal multiplier on `sd_now`, which
  `no-gaussian-band-is-calibrated` measured breaching 18 to 461 times its
  label. Here to keep the others honest.

Beside them, two diagnostics that say whether the mechanism is even present:
the coefficient of variation of `sd_now`, and the lag-one autocorrelation of
`z^2`. If `mixture` raises both and `smoothed` recovers the coverage that
`live` loses under it, the band's shape was the problem and the rule was never
at fault.

The constant-sigma family is the arm's own null: its spread barely moves, so
all four constructions should agree there and no rule should separate them.

**Quantiles are refreshed every `REFRESH` bars** rather than every bar. The
window is 500 and shifts by one, so the approximation is small, and it is the
difference between a minute and an hour - but it is an approximation, and the
shipped code does recompute every bar.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
for q in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(q))

from pattern_fingerprint import CACHE, classify, load  # noqa: E402

from till_infinity.statespace.adapting import MOST, Adapting  # noqa: E402
from till_infinity.statespace.engine import dispersion  # noqa: E402
from till_infinity.statespace.facade import LEAST, WINDOW  # noqa: E402
from till_infinity.statespace.pooling import DEFAULT, LEVERS, Pooled, _factories  # noqa: E402

#: **Both, and the shipped one first.** The first version of this harness ran
#: only at 0.265, the estimator's physically correct noise - while
#: `adapting-strata.md` had just finished showing that the service runs 0.670
#: and that pinning the correct value describes a desk nobody operates. The
#: band failure this page exists to explain - `mixture` breaching 0.117 to
#: 0.131 - was measured at **0.670**, so a run at 0.265 cannot reach it.
SHIPPED = 0.670
NOISES = (SHIPPED, 0.265)
RULES = ("shrinking", "mixture")
CLAMPS = (MOST, 1e7)
COVERS = (0.90, 0.95, 0.99)
#: Central Gaussian multipliers for `COVERS`, for the arm that keeps the others
#: honest rather than for any claim.
GAUSSIAN = {0.90: 1.6449, 0.95: 1.9600, 0.99: 2.5758}
#: Memory of the reference variance the `smoothed` arm standardises by, in
#: observations. Long on purpose: it is there to stop the band's shape moving
#: with a spike, so a short one would defeat it.
REFERENCE = 2_000.0
REFRESH = 25

FRAMES = ("1h",)
TRADED = ("fx_major", "fx_cross", "metal")
CONTROLS = ("volatility",)
PER_CLASS = 3
LIMIT = 12_000
WARM = 500


def _pool(rule: str, most: float) -> Pooled:
    built = _factories(DEFAULT)
    return Pooled(
        names=DEFAULT,
        rule=rule,
        _pool=[
            Adapting(build=make, lever=LEVERS.get(name, "jerk"), mode="matching", most=most)
            for name, make in zip(DEFAULT, built, strict=False)
        ],
    )


def _fold(
    values: np.ndarray, stamps: np.ndarray, rule: str, most: float, noise: float
) -> dict[str, np.ndarray]:
    """One pass, recording what every band construction needs and nothing else."""
    pool = _pool(rule, most)
    before = np.full(len(values), np.nan)
    spread = np.full(len(values), np.nan)
    for i, value in enumerate(values):
        pool.predict(float(stamps[i]), 0.0)
        before[i] = float(pool.value)
        spread[i] = float(pool.variance) + noise
        pool.update(float(value), noise, float(stamps[i]))
    return {"before": before, "spread": spread, "x": values}


def _bands(got: dict[str, np.ndarray]) -> dict[str, dict[float, float]]:
    """Breach rate per construction per coverage, on identical rows."""
    before, spread, x = got["before"], got["spread"], got["x"]
    sd = np.sqrt(np.maximum(spread, 1e-300))
    residual = x - before
    live = residual / sd

    reference = np.full(len(spread), np.nan)
    decay = 1.0 - 1.0 / REFERENCE
    running = float(spread[0])
    for i in range(len(spread)):
        running = decay * running + (1.0 - decay) * float(spread[i])
        reference[i] = running
    reference_sd = np.sqrt(np.maximum(reference, 1e-300))
    smoothed = residual / reference_sd

    arms = {
        "live": (live, sd),
        "raw": (residual, np.ones(len(sd))),
        "smoothed": (smoothed, reference_sd),
    }
    out: dict[str, dict[float, float]] = {name: {} for name in (*arms, "gaussian")}
    counts: dict[str, dict[float, list[int]]] = {
        name: {cover: [0, 0] for cover in COVERS} for name in out
    }

    held: dict[str, dict[float, tuple[float, float]]] = {}
    for i in range(WARM, len(x)):
        if (i - WARM) % REFRESH == 0 or not held:
            held = {}
            start = max(0, i - WINDOW)
            for name, (series, _) in arms.items():
                window = series[start:i]
                window = window[np.isfinite(window)]
                if len(window) < LEAST:
                    continue
                ordered = np.sort(window)
                held[name] = {}
                for cover in COVERS:
                    low = min(int(0.5 * (1.0 - cover) * len(ordered)), len(ordered) - 1)
                    high = min(int(0.5 * (1.0 + cover) * len(ordered)), len(ordered) - 1)
                    held[name][cover] = (float(ordered[low]), float(ordered[high]))
        for name, (_, scale) in arms.items():
            if name not in held:
                continue
            for cover in COVERS:
                low, high = held[name][cover]
                inside = before[i] + scale[i] * low <= x[i] <= before[i] + scale[i] * high
                counts[name][cover][0] += 0 if inside else 1
                counts[name][cover][1] += 1
        for cover in COVERS:
            reach = GAUSSIAN[cover] * sd[i]
            inside = before[i] - reach <= x[i] <= before[i] + reach
            counts["gaussian"][cover][0] += 0 if inside else 1
            counts["gaussian"][cover][1] += 1

    for name, per in counts.items():
        for cover, (breaches, total) in per.items():
            out[name][cover] = breaches / total if total else float("nan")
    return out


def _diagnostics(got: dict[str, np.ndarray], noise: float) -> tuple[float, float, float]:
    """How much the spread moves, how clustered `z^2` is, and `E[z^2]`."""
    sd = np.sqrt(np.maximum(got["spread"], 1e-300))[WARM:]
    z = ((got["x"] - got["before"]) / np.sqrt(np.maximum(got["spread"], 1e-300)))[WARM:]
    squared = z * z
    centred = squared - squared.mean()
    denominator = float(np.sum(centred * centred))
    auto = float(np.sum(centred[1:] * centred[:-1]) / denominator) if denominator > 0 else math.nan
    return float(sd.std() / sd.mean()), auto, float(squared.mean())


def main() -> None:
    print(
        "Why does a correctly-scaled spread make a worse band?\n"
        "`_quantiles` divides each past residual by its own instantaneous predictive\n"
        "sd and multiplies the quantile of those by today's, which is only right if\n"
        "the standardised residuals are identically distributed. Four constructions\n"
        "on one fold, so nothing here is a difference in the filter.\n"
        f"Quantiles refreshed every {REFRESH} bars; window {WINDOW}, floor {LEAST}.\n",
        flush=True,
    )
    groups: dict[str, list[str]] = {}
    for path in sorted(CACHE.glob("*.1h.npz")):
        name = path.name[: -len(".1h.npz")]
        groups.setdefault(classify(name), []).append(name)
    wanted = {k: v[:PER_CLASS] for k, v in groups.items() if k in TRADED + CONTROLS}
    print("classes:", ", ".join(f"{k} ({len(v)})" for k, v in sorted(wanted.items())), flush=True)

    for frame in FRAMES:
        for klass, names in sorted(wanted.items()):
            series = []
            for name in names:
                bars = load(name, frame)
                if bars is None:
                    continue
                bars = {k: v[-LIMIT:] for k, v in bars.items()}
                out: list[float] = []
                when: list[float] = []
                for i in range(len(bars["close"])):
                    one = dispersion(
                        float(bars["open"][i]),
                        float(bars["high"][i]),
                        float(bars["low"][i]),
                        float(bars["close"][i]),
                    )
                    if one is not None:
                        out.append(one)
                        when.append(float(bars["time"][i]))
                if len(out) > WARM + 2_000:
                    series.append((np.asarray(out, dtype=float), np.asarray(when, dtype=float)))
            if not series:
                continue
            print(f"\n=== {frame}, {klass}")
            print(
                f"{'R':>7}{'clamp':>8}{'rule':>10}{'band':>10}{'breach .90':>12}"
                f"{'breach .95':>12}{'breach .99':>12}{'cv(sd)':>9}{'ac1(z2)':>9}{'E[z^2]':>9}"
            )
            for noise in NOISES:
                for most in CLAMPS:
                    for rule in RULES:
                        folded = [_fold(v, t, rule, most, noise) for v, t in series]
                        diags = [_diagnostics(one, noise) for one in folded]
                        scored = [_bands(one) for one in folded]
                        cv = float(np.median([one[0] for one in diags]))
                        auto = float(np.median([one[1] for one in diags]))
                        zvar = float(np.median([one[2] for one in diags]))
                        for band in ("live", "raw", "smoothed", "gaussian"):
                            row = [one[band] for one in scored if band in one]
                            if not row:
                                continue
                            marks = "".join(
                                f"{float(np.median([r[c] for r in row])):>12.4f}" for c in COVERS
                            )
                            tail = (
                                f"{cv:>9.3f}{auto:>9.3f}{zvar:>9.3f}"
                                if band == "live"
                                else " " * 27
                            )
                            shipped = (
                                " <-"
                                if (band, rule, most, noise) == ("live", "shrinking", MOST, SHIPPED)
                                else ""
                            )
                            print(
                                f"{noise:>7.3f}{most:>8.0e}{rule:>10}{band:>10}"
                                f"{marks}{tail}{shipped}",
                                flush=True,
                            )
    print(
        "\n\n`cv(sd)` and `ac1(z2)` say whether the mechanism is present at all: a rule\n"
        "that spikes the spread raises the first, and standardising by something that\n"
        "jumps leaves structure in the second. Then the question is whether\n"
        "`smoothed` holds its coverage where `live` loses it. If it does, the band's\n"
        "shape was being estimated in units that move and the rule was never at\n"
        "fault; if both fail together, the band is not where this lives either.",
        flush=True,
    )


if __name__ == "__main__":
    main()
