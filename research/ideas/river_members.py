"""Does adding River to the statespace members improve them?

River has been tried here twice and both times on a **classification** target:
`research/docs/models.md` ran its bagging and forests on level touches, where
plain logistic regression won, and `riverbench.py` ran its boosting and stacking
on the expansion alert. Neither asked it the question the members are actually
scored on.

**The members' question is a one-step predictive density**, scored on held-out
log-likelihood, PIT flatness and CRPS. That is a harder thing to supply than a
point forecast, and it is where River has to be handicapped carefully or the
comparison is meaningless.

## The handicap, and why it is the fair one rather than a kindness

A River regressor returns a **point**. To be scored against a filter it needs a
spread, so each one is given an exponentially-weighted scale of its own absolute
residuals and a Gaussian predictive around its point.

That is not an invention for this harness: `family.py` already records that
`selective` reports "a **fitted** spread rather than an inferred one", and it is
in the family on exactly those terms. So River is being held to the same
standard as an existing member rather than a lower one.

Both sides see the same information - the last `LAGS` log-returns - and both
predict the next log price. The members get it through their own state; the
River models get it as features.

## The three arms, and the third is the question

* **each River model alone**, so a bad pooled result can be attributed;
* **the statespace pool**, `pooling.Pooled` at its measured defaults, which is
  the incumbent at a CRPS of 0.001601;
* **the pool with the River model added as a member.** This is the question as
  asked. `Pooled` weights by precision, so a model that is worse but
  *differently* wrong can still improve the pool - that is exactly what the 5.6x
  came from - and a model that is better but redundant will not.

## The control

The generated feeds, whose processes are specified. A learner that improves on
`Volatility_75_Index` - geometric Brownian motion with no learnable structure -
is fitting noise, and that invalidates its traded numbers before they are read.

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
from till_infinity.structures.statespace.pooling import Pooled  # noqa: E402

CACHE = Path(os.environ.get("SEQLAB_CACHE", str(Path.home() / "till_infinity/data/seqlab")))
FRAME = os.environ.get("FRAME", "1h")
LIMIT = int(os.environ.get("LIMIT", "8000"))
LAGS = int(os.environ.get("LAGS", "8"))
#: Half-life in bars for the residual scale a River model is given.
SCALE_HALF_LIFE = 60.0
QUANTILES = tuple(i / 20.0 for i in range(1, 20))
TRADED = tuple(os.environ.get("TRADED", "EURUSD,GBPUSD,USDJPY,XAUUSD").split(","))
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
        times, closes = bundle["time"][order], bundle["close"][order]
    keep = closes > 0
    times, closes = times[keep], closes[keep]
    if len(times) < 3000:
        return None
    if len(times) > LIMIT:
        times, closes = times[-LIMIT:], closes[-LIMIT:]
    return times.tolist(), np.log(closes).tolist()


def _alpha(half_life: float) -> float:
    return 1.0 - 0.5 ** (1.0 / max(half_life, 1e-9))


class Learner:
    """A River regressor dressed as something scoreable against a member.

    Predicts the next **log return** from the last `LAGS` of them and adds it to
    the current level, so it is forecasting the same quantity the members
    forecast rather than an easier one. The spread is an exponential mean of its
    own absolute residuals, scaled to a standard deviation.
    """

    def __init__(self, build) -> None:
        self.model = build()
        self.lags: deque[float] = deque(maxlen=LAGS)
        self.level = 0.0
        self.scale = 0.0
        self.value = 0.0
        self.rate = 0.0
        self.seen = 0
        self.loglike = 0.0

    def _features(self) -> dict[str, float]:
        return {f"lag{i}": v for i, v in enumerate(self.lags)}

    @property
    def sd(self) -> float:
        # 1.2533 is sqrt(pi/2): the ratio of a half-normal's standard deviation
        # to its mean absolute deviation, so a mean |residual| becomes a sigma.
        return max(self.scale * 1.2533, 1e-12)

    def predict(self, when: float, control: float = 0.0) -> None:  # noqa: ARG002
        step = 0.0
        if len(self.lags) == LAGS and self.seen > LAGS:
            try:
                step = float(self.model.predict_one(self._features()) or 0.0)
            except Exception:  # noqa: BLE001 - a learner that throws scores as flat
                step = 0.0
        self.value = self.level + step
        self.rate = step

    def update(self, measured: float, noise: float, when: float | None = None) -> float:  # noqa: ARG002
        measured = float(measured)
        residual = measured - self.value
        self.scale = (
            abs(residual)
            if not self.scale
            else self.scale + _alpha(SCALE_HALF_LIFE) * (abs(residual) - self.scale)
        )
        if len(self.lags) == LAGS:
            self.model.learn_one(self._features(), measured - self.level)
        self.lags.append(measured - self.level)
        self.level = measured
        self.seen += 1
        return residual / self.sd

    def at_time(self, when: float) -> float:  # noqa: ARG002
        return self.value

    def band(self, when: float, sigmas: float = 2.0) -> tuple[float, float]:  # noqa: ARG002
        return self.value - sigmas * self.sd, self.value + sigmas * self.sd

    def output(self) -> tuple[float, ...]:
        return (self.value,)

    def observation(self) -> tuple[tuple[float, ...], ...]:
        return ((1.0,),)


def score(times, values, one, *, observation_noise: bool):
    """Held-out `(loglike/bar, pit, crps)`.

    **`observation_noise` is the whole fairness of this comparison and the first
    run of it got the answer wrong.** A filter's `sd` is `sqrt(p00)`, the spread
    of the **state**. The thing being scored is an **observation**, whose
    one-step predictive variance is `p00 + R` - the state's uncertainty plus the
    measurement noise. Leaving `R` out makes every filter look over-confident by
    exactly that term, which is what produced a PIT flatness of 147 on
    processes the filters are correctly specified for.

    A River learner needs no such correction, because its spread is an
    exponential mean of its own **residuals** - and a residual is
    `observation - prediction`, so the measurement noise is already inside it.
    Handing it `R` a second time would make it under-confident by the same
    amount, so the flag is per arm rather than global, and that asymmetry is a
    property of what each one reports rather than a thumb on the scale.
    """
    steps = [abs(values[i] - values[i - 1]) for i in range(1, len(values))]
    noise = statistics.pstdev(steps) or 1e-9
    start = len(times) // 2
    total, scores, pits = 0.0, [], []
    for i, (when, value) in enumerate(zip(times, values, strict=True)):
        one.predict(float(when))
        spread = float(one.sd) ** 2
        if observation_noise:
            spread += noise * noise
        mu, sd = float(one.value), max(math.sqrt(spread), 1e-12)
        if i >= start:
            z = (value - mu) / sd
            total += -0.5 * (z * z + math.log(2.0 * math.pi * sd * sd))
            pits.append(0.5 * (1.0 + math.erf(z / math.sqrt(2.0))))
            scores.append(crps([(q, mu + sd * _normal_quantile(q)) for q in QUANTILES], value))
        one.update(float(value), noise * noise, float(when))
    if not scores:
        return None
    return total / len(scores), pit_flatness(pits), statistics.mean(scores)


class Rescaled:
    """Any filter, with its spread replaced by a mean of its own residuals.

    **This is the arm that says what River's advantage actually is.** On the
    generated feeds there is nothing to learn - driftless geometric Brownian
    motion, validated - and the River learners still beat the pool there, with a
    PIT flatness near 1.0 against the pool's 43. A gain that survives on a
    process with no structure is not a learning gain.

    What the learners have instead is a spread taken from their own realised
    residuals, where a filter's spread comes from a process-noise parameter.
    So: keep the member's point forecast exactly, replace only its spread, and
    see how much of the gap closes. Whatever is left is learning; whatever
    closes was never about River at all.
    """

    def __init__(self, inner) -> None:
        self.inner = inner
        self.scale = 0.0

    @property
    def value(self) -> float:
        return float(self.inner.value)

    @property
    def sd(self) -> float:
        return max(self.scale * 1.2533, 1e-12)

    def predict(self, when: float, control: float = 0.0) -> None:  # noqa: ARG002
        self.inner.predict(float(when))

    def update(self, measured: float, noise: float, when: float | None = None) -> float:
        residual = float(measured) - self.value
        self.scale = (
            abs(residual)
            if not self.scale
            else self.scale + _alpha(SCALE_HALF_LIFE) * (abs(residual) - self.scale)
        )
        return self.inner.update(float(measured), float(noise), when)


#: The process-noise lever each member names. `Adapting` defaults to `jerk`,
#: which `reverting` does not have.
LEVERS = {"kalman": "jerk", "robust": "jerk", "reverting": "sigma2"}


def adapting_pool() -> Pooled:
    """`Pooled` whose members each learn their own process noise online.

    **This is the arm the diagnosis points at, and it uses machinery that is
    already here and already measured.** `adapting.Adapting` learns the
    process-noise lever from the member's own standardised innovation, driving
    its exponentially-weighted square toward 1.0 - which its docstring calls
    "an honest filter" - and `family.py` records it at **+848 nats median**.

    If the River gap is a mis-set `Q`, then members that fit their own `Q`
    should close it **generatively**, without a residual-scale patch bolted on
    the outside and without a learner. If it does not close, the remainder is
    something the members' form cannot represent, and that is worth knowing
    precisely.
    """
    from till_infinity.structures.statespace.adapting import Adapting
    from till_infinity.structures.statespace.family import members

    built = members()
    pool = Pooled()
    pool._pool = [  # noqa: SLF001 - the arm is the point
        Adapting(build=built[name], lever=LEVERS[name], mode="matching")
        for name in pool.names
        if name in built
    ]
    return pool


class WithRiver(Pooled):
    """`Pooled` with a River learner added as one more member.

    Subclassed rather than parameterised because `Pooled.names` resolves through
    `family.members()` and a River model is not in that registry - correctly, it
    is not a member of the family. This is the arm, not a proposal to put it
    there.
    """

    def add(self, learner) -> None:
        self._pool.append(learner)


def main() -> None:
    from river import forest, linear_model, preprocessing, tree

    builds = {
        "river linear": lambda: preprocessing.StandardScaler() | linear_model.LinearRegression(),
        "river tree": tree.HoeffdingAdaptiveTreeRegressor,
        "river forest": lambda: forest.ARFRegressor(n_models=5, seed=7),
    }
    print(f"frame {FRAME}  lags {LAGS}  limit {LIMIT}\n")
    print(
        "Each River model predicts the next log **return** from the last eight,\n"
        "and is given an exponential mean of its own absolute residuals as a\n"
        "spread - the same footing `selective` is in the family on.\n"
    )
    for group, names in (("traded", TRADED), ("generated", GENERATED)):
        print("=" * 84)
        print(group)
        print("=" * 84)
        print(f"{'arm':<26}{'loglike/bar':>13}{'pit':>10}{'crps':>12}{'cells':>7}")

        def run(make, names=names, observation_noise=True):
            cells = []
            for name in names:
                got = load(name)
                if got is None:
                    continue
                out = score(got[0], got[1], make(), observation_noise=observation_noise)
                if out and all(math.isfinite(v) for v in out):
                    cells.append(out)
            return cells

        def show(label, cells):
            if not cells:
                return
            print(
                f"{label:<26}{statistics.median(c[0] for c in cells):>13.4f}"
                f"{statistics.median(c[1] for c in cells):>10.2f}"
                f"{statistics.median(c[2] for c in cells):>12.6f}{len(cells):>7}"
            )

        show("Pooled() incumbent", run(Pooled))
        # Its spread already contains the measurement noise, so it is not
        # given it again.
        show(
            "Pooled, residual spread",
            run(lambda: Rescaled(Pooled()), observation_noise=False),
        )
        show("Pooled, Adapting members", run(adapting_pool))
        show(
            "Pooled, Adapting + residual",
            run(lambda: Rescaled(adapting_pool()), observation_noise=False),
        )
        for label, build in builds.items():
            # A learner's residual scale already contains the measurement
            # noise, so it is not given it twice.
            show(f"{label} alone", run(lambda b=build: Learner(b), observation_noise=False))

            def pooled_with(b=build):
                pool = WithRiver()
                pool.add(Learner(b))
                return pool

            show(f"Pooled + {label}", run(pooled_with))
        print()
    print(
        "**The third arm of each pair is the question.** `Pooled` weights by\n"
        "precision, so a model that is worse but *differently* wrong can still\n"
        "improve the pool - that is where the 5.6x came from - and one that is\n"
        "better but redundant will not. A River model that only helps where it\n"
        "also helps alone is not adding anything the members lacked.\n\n"
        "And read the generated block first. A learner that improves on\n"
        "geometric Brownian motion with no learnable structure is fitting noise."
    )


if __name__ == "__main__":
    main()
