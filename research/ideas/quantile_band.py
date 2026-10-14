"""Can a **conditional** band beat an unconditional one on CRPS?

`statespace-tail-shape.md` and `statespace-conformal-band.md` left this desk's
forecast-distribution problem in a precise state.

**No Gaussian band is calibrated on real data** - PIT flatness 18 to 461 - and a
Student-t that can only reshape over-corrects. A **shape-free** band, the
empirical distribution of past residuals, closes the calibration gap almost
completely: flatness 73.3 to **1.5** on traded and 40.6 to **1.1** on generated.

And it barely improves sharpness. **CRPS 0.991** against the Gaussian on traded
and 0.997 on generated. So the band got honest and did not get better, which is
why `no-gaussian-band-is-calibrated` records the open problem as the **tail
shape** rather than the calibration.

**The PIT cannot settle this and the doc says why**: a conformal PIT is the rank
of a new residual among past ones, and a rank among exchangeable draws is
uniform by definition, so a flatness near 1.0 is close to tautological. **CRPS
is the evidence.** 0.991 is the number to beat.

## The hypothesis, and why River is the right tool for it

The shape-free band is **unconditional**: the empirical quantiles of the last
`WINDOW` residuals, which are the same whatever the market is doing right now.
If the *shape* of the next return's distribution depends on the recent path -
not just its width, which a volatility estimate already handles - then
**conditional** quantiles should beat it, and an unconditional band cannot
express that however well calibrated it is.

River fits a separate linear model per quantile level under the pinball loss,
online, which is exactly a conditional quantile function and is the one thing
this desk has no implementation of.

## Every band is modelled in **standardised** units, and the first run shows why

The arms predict quantiles of `z = return / sigma`, where `sigma` is the same
exponential mean of squared returns the Gaussian arm uses, and the band is
`sigma` times those quantiles.

That is the correct framing for the question rather than a convenience: the
**width** of the next return's distribution is a volatility forecast, which this
desk has studied to death and which every arm here should share, and the **shape**
is what is open. Standardising separates them, so a difference between arms is a
difference in shape.

It is also the only way the conditional arm works at all. The first version fed
River raw log returns, which are of order `1e-4`, and a linear model under
pinball loss with a default step size stays near zero on a target that small -
so every quantile came back near zero, the band had no width, and CRPS read
**26.8** times the Gaussian with a PIT of 664. That is not a conditional band
losing; that is a regression that never left the origin. Working in units where
the target is of order one is the same lesson as
`the-ladder-belongs-on-log-volatility`.

## The comparison is of **bands only**

Every arm shares the same point forecast - the last value, which is the walk,
and which `the-walk-is-the-best-calibrated-band` records as the thing nothing
has beaten. Only the distribution around it differs. That isolates the question
to the band's shape, which is the open problem, rather than mixing it with a
point-forecast contest that has already been run.

* `gaussian` - mean zero, sigma from an exponential mean of squared returns.
  The baseline, CRPS 1.000 by construction;
* `conformal` - the empirical quantiles of the last `WINDOW` returns.
  Unconditional and shape-free. The incumbent;
* `river` - a River linear model per quantile level on the last `LAGS` returns.
  Conditional and shape-free;
* `river sorted` - the same with monotonicity enforced, which it needs: the
  models are fitted **independently**, so nothing stops the 60th percentile
  landing below the 40th, and `diagnostics.crps` integrates a left Riemann sum
  over ascending levels. Quantile crossing would not raise, it would quietly
  score a distribution that is not one.

## The control decides it

On the generated feeds the true shape **is** Gaussian - validated at kurtosis
3.00 and Jarque-Bera p 0.40 to 0.95 on 86,411 bars - so a conditional band must
**not** beat the Gaussian there. If it does, it is fitting noise, and its traded
number means nothing. The conformal band passes that test at 0.997, which is
the standard to match.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import statistics
import sys
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from till_infinity.structures.statespace.diagnostics import crps, pit_flatness  # noqa: E402
from till_infinity.structures.statespace.distance import _normal_quantile  # noqa: E402

CACHE = Path(os.environ.get("SEQLAB_CACHE", str(Path.home() / "till_infinity/data/seqlab")))
FRAME = os.environ.get("FRAME", "1h")
LIMIT = int(os.environ.get("LIMIT", "12000"))
LAGS = int(os.environ.get("LAGS", "8"))
#: Residuals the unconditional band keeps. Long enough for a 5% tail quantile
#: to have observations behind it.
WINDOW = int(os.environ.get("WINDOW", "500"))
#: Half-life in bars for the Gaussian arm's variance.
HALF_LIFE = 60.0
LEVELS = tuple(i / 20.0 for i in range(1, 20))
TRADED = tuple(os.environ.get("TRADED", "EURUSD,GBPUSD,USDJPY,XAUUSD,AUDUSD,USDCAD").split(","))
GENERATED = tuple(os.environ.get("GENERATED", "Volatility_75_Index,Step_Index_200").split(","))


def load(name: str):
    import numpy as np

    path = CACHE / f"{name}.{FRAME}.npz"
    if not path.exists():
        return None
    with np.load(path) as bundle:
        if not {"time", "close"} <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        closes = bundle["close"][order]
    closes = closes[closes > 0]
    if len(closes) < 4000:
        return None
    if len(closes) > LIMIT:
        closes = closes[-LIMIT:]
    return np.diff(np.log(closes)).tolist()


def _alpha(half_life: float) -> float:
    return 1.0 - 0.5 ** (1.0 / max(half_life, 1e-9))


class Scale:
    """The shared width. Every arm divides by it, so only shape differs."""

    def __init__(self) -> None:
        self.var = 0.0

    @property
    def sd(self) -> float:
        return math.sqrt(self.var) if self.var > 0 else 0.0

    def learn(self, value: float) -> None:
        self.var = (
            value * value
            if not self.var
            else self.var + _alpha(HALF_LIFE) * (value * value - self.var)
        )


class Gaussian:
    """A normal shape on the standardised return. The baseline."""

    name = "gaussian"

    def shape(self, lags) -> list[float] | None:  # noqa: ARG002
        return [_normal_quantile(level) for level in LEVELS]

    def learn(self, lags, z: float) -> None:  # noqa: ARG002
        return


class Conformal:
    """Empirical quantiles of the last `WINDOW` standardised returns.

    Unconditional: the same shape whatever the market is doing now. The
    incumbent, at CRPS 0.991 on traded and 0.997 on generated.
    """

    name = "conformal"

    def __init__(self) -> None:
        self.seen: deque[float] = deque(maxlen=WINDOW)

    def shape(self, lags) -> list[float] | None:  # noqa: ARG002
        if len(self.seen) < 200:
            return None
        got = sorted(self.seen)
        # Nearest-rank, which is what an empirical quantile is; no
        # interpolation, so nothing is invented between observations.
        return [got[min(int(level * len(got)), len(got) - 1)] for level in LEVELS]

    def learn(self, lags, z: float) -> None:  # noqa: ARG002
        self.seen.append(z)


class River:
    """One River linear model per quantile level. Conditional and shape-free."""

    def __init__(self, *, sort: bool) -> None:
        from river import linear_model, optim, preprocessing

        self.sort = sort
        self.name = "river sorted" if sort else "river"
        self.models = {
            level: preprocessing.StandardScaler()
            | linear_model.LinearRegression(loss=optim.losses.Quantile(alpha=level))
            for level in LEVELS
        }
        self.trained = 0

    def shape(self, lags) -> list[float] | None:
        if len(lags) < LAGS or self.trained < 300:
            return None
        row = {f"lag{i}": v for i, v in enumerate(lags)}
        got = [float(m.predict_one(row) or 0.0) for m in self.models.values()]
        if self.sort:
            # **Fitted independently, so nothing enforces monotonicity.** A
            # crossing would not raise; `crps` would integrate a left Riemann
            # sum over a thing that is not a distribution and return a number.
            got = sorted(got)
        return got

    def learn(self, lags, z: float) -> None:
        if len(lags) < LAGS:
            return
        row = {f"lag{i}": v for i, v in enumerate(lags)}
        for m in self.models.values():
            m.learn_one(row, z)
        self.trained += 1


def score(returns, arm):
    """Held-out `(crps, pit flatness, n)` over the second half.

    The shared `Scale` is updated from the realised return **after** the band is
    read, so the width in force at each step uses only the past.
    """
    lags: deque[float] = deque(maxlen=LAGS)
    scale = Scale()
    start = len(returns) // 2
    scores, pits = [], []
    for i, value in enumerate(returns):
        sd = scale.sd
        got = arm.shape(list(lags)) if sd > 0 else None
        if i >= start and got:
            band = [(level, sd * q) for level, q in zip(LEVELS, got, strict=True)]
            scores.append(crps(band, value))
            # Where the outcome falls among the predicted quantiles: the PIT,
            # read off the band itself rather than from a density.
            below = sum(1 for _, q in band if q <= value)
            pits.append(below / (len(band) + 1))
        z = value / sd if sd > 0 else 0.0
        arm.learn(list(lags), z)
        scale.learn(value)
        lags.append(z)
    if len(scores) < 500:
        return None
    return statistics.mean(scores), pit_flatness(pits), len(scores)


def main() -> None:
    print(f"frame {FRAME}  lags {LAGS}  window {WINDOW}  levels {len(LEVELS)}\n")
    print(
        "Every arm shares the same point forecast - the last value - so only\n"
        "the band differs. `crps` is relative to the Gaussian arm on the same\n"
        "instrument, which is the convention `statespace-conformal-band.md`\n"
        "uses. **Below 1.000 is sharper.** The incumbent is the unconditional\n"
        "shape-free band at 0.991 traded and 0.997 generated.\n"
    )
    builds = (Gaussian, Conformal, lambda: River(sort=False), lambda: River(sort=True))
    for group, names in (("traded", TRADED), ("generated", GENERATED)):
        print("=" * 78)
        print(group)
        print("=" * 78)
        print(f"{'arm':<16}{'CRPS vs gaussian':>18}{'PIT':>9}{'cells':>7}{'beats 0.991':>13}")
        rows: dict[str, list[tuple[float, float]]] = {}
        for name in names:
            returns = load(name)
            if returns is None:
                continue
            base = None
            for build in builds:
                arm = build()
                got = score(returns, arm)
                if got is None:
                    continue
                if arm.name == "gaussian":
                    base = got[0]
                if base and base > 0:
                    rows.setdefault(arm.name, []).append((got[0] / base, got[1]))
        for label in ("gaussian", "conformal", "river", "river sorted"):
            cells = rows.get(label)
            if not cells:
                continue
            ratio = statistics.median(c[0] for c in cells)
            print(
                f"{label:<16}{ratio:>18.4f}{statistics.median(c[1] for c in cells):>9.2f}"
                f"{len(cells):>7}{'yes' if ratio < 0.991 else 'no':>13}"
            )
        print()
    print(
        "**Read the generated block as the gate.** There the true shape is\n"
        "Gaussian - kurtosis 3.00, Jarque-Bera p 0.40 to 0.95 on 86,411 bars -\n"
        "so a conditional band that beats the Gaussian there is fitting noise\n"
        "and its traded number means nothing. The unconditional band scores\n"
        "0.997 there, which is the standard to match rather than to beat.\n\n"
        "And the PIT column is a **check, not evidence**: a band built from the\n"
        "empirical quantiles of its own past residuals is uniform by\n"
        "construction, so a flatness near 1.0 is close to tautological for both\n"
        "shape-free arms."
    )


if __name__ == "__main__":
    main()
