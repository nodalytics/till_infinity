"""Weights from **realised** score, against weights from **claimed** precision.

`pooling.Pooled` weights each member by its precision raised to `alpha`, and
`statespace-pooling-exponent.md` measured that the Bayesian `alpha = 1` beats
quadratic voting's 0.5. But precision is what a member **claims** about itself,
and `statespace-river-against-members.md` then showed that claim was badly
wrong: the members were so over-confident that a River tree beat the pool by
3.6x, and 87% of that gap closed by letting each member fit its own `Q`.

**So the obvious correction is to stop asking members how good they are and
measure it.** A bandit policy over the members, rewarded by whichever one
actually predicted best, never reads a precision at all.

Two measurements make this worth running rather than assuming:

* **switching is where the value is.** Holding one good member and never
  changing it scores CRPS 0.009007; switching between the same members by
  precision scores 0.001688. A 5.3-fold gap, larger than the gap between
  winner-take-all and the best blend;
* **and blending beats winner-take-all by only 5%** - 0.001601 against
  0.001688 - so the selection rule is carrying almost all of the gain and the
  averaging almost none. A better selection rule has room; a better average
  does not.

## It is full information, and saying so is the honest part

A bandit normally learns only about the arm it pulled. Here every member's
predictive density is computable at every step whether it was chosen or not, so
withholding that would handicap the policy for no reason. Every arm is updated
every step.

That makes this **exponential weights on realised score** rather than a bandit
in the usual sense, and the comparison is the cleaner for it: both sides see
everything, and the only difference is whether the weight comes from what a
member claims or from what it has done.

The reward is binary - **was this member the best this step** - because UCB and
epsilon-greedy expect a bounded reward and a log density is unbounded. A member
that is usually second gets nothing, which is the rule's own bias and is
reported rather than hidden: it is why `Exp3` is carried too, since it weights
by accumulated reward rather than by a mean.

## The null

`random` picks a member uniformly every step. A policy that cannot beat it is
not selecting, and `statespace-pooling-exponent.md` records that random
selection scores 4.7 times worse than precision-weighted winner-take-all - so
the bar is real and already measured.

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

from till_infinity.structures.statespace.diagnostics import crps, pit_flatness  # noqa: E402
from till_infinity.structures.statespace.distance import _normal_quantile  # noqa: E402
from till_infinity.structures.statespace.pooling import DEFAULT, LEVERS, Pooled  # noqa: E402

CACHE = Path(os.environ.get("SEQLAB_CACHE", str(Path.home() / "till_infinity/data/seqlab")))
FRAME = os.environ.get("FRAME", "1h")
LIMIT = int(os.environ.get("LIMIT", "12000"))
SEED = 20261014
QUANTILES = tuple(i / 20.0 for i in range(1, 20))
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
        times, closes = bundle["time"][order], bundle["close"][order]
    keep = closes > 0
    times, closes = times[keep], closes[keep]
    if len(times) < 3000:
        return None
    if len(times) > LIMIT:
        times, closes = times[-LIMIT:], closes[-LIMIT:]
    return times.tolist(), np.log(closes).tolist()


def adapting_members():
    from till_infinity.structures.statespace.adapting import Adapting
    from till_infinity.structures.statespace.family import members

    built = members()
    return [
        Adapting(build=built[name], lever=LEVERS[name], mode="matching")
        for name in DEFAULT
        if name in built
    ]


class Selector:
    """Picks one member per step from a policy rewarded by realised score."""

    def __init__(self, policy: str) -> None:
        self.name = policy
        self.pool = adapting_members()
        self.policy = self._build(policy, len(self.pool))
        self.chosen = 0
        self.value = 0.0
        self.variance = 1.0
        self.switches = 0

    @staticmethod
    def _build(policy: str, arms: int):
        import random as _random

        from river import bandit

        if policy == "ucb":
            return bandit.UCB(delta=1.0, seed=SEED)
        if policy == "epsilon":
            return bandit.EpsilonGreedy(epsilon=0.1, seed=SEED)
        if policy == "exp3":
            return bandit.Exp3(gamma=0.1, seed=SEED)
        if policy == "thompson":
            from river import proba

            return bandit.ThompsonSampling(reward_obj=proba.Beta(), seed=SEED)
        rng = _random.Random(SEED)
        return rng  # the random null, handled in `choose`

    @property
    def sd(self) -> float:
        return math.sqrt(max(self.variance, 1e-24))

    def choose(self) -> None:
        import random as _random

        if isinstance(self.policy, _random.Random):
            pick = self.policy.randrange(len(self.pool))
        else:
            got = self.policy.pull(range(len(self.pool)))
            pick = int(got) if isinstance(got, int) else int(next(iter(got)))
        self.switches += pick != self.chosen
        self.chosen = pick

    def predict(self, when: float) -> None:
        for one in self.pool:
            one.predict(float(when))
        self.choose()
        picked = self.pool[self.chosen]
        self.value = float(picked.value)
        self.variance = float(picked.sd) ** 2

    def update(self, measured: float, noise: float, when: float | None = None) -> None:
        import random as _random

        # Every member's density, whether or not it was chosen: the information
        # is free, so withholding it would handicap the policy for no reason.
        densities = []
        for one in self.pool:
            spread = float(one.sd) ** 2 + noise
            residual = float(measured) - float(one.value)
            densities.append(
                -0.5 * (residual * residual / spread + math.log(2.0 * math.pi * spread))
                if spread > 0
                else -math.inf
            )
        best = max(range(len(densities)), key=lambda i: densities[i])
        if not isinstance(self.policy, _random.Random):
            for i in range(len(self.pool)):
                self.policy.update(i, 1.0 if i == best else 0.0)
        for one in self.pool:
            one.update(float(measured), float(noise), when)


def score(times, values, arm):
    steps = [abs(values[i] - values[i - 1]) for i in range(1, len(values))]
    noise = statistics.pstdev(steps) or 1e-9
    start = len(times) // 2
    total, scores, pits = 0.0, [], []
    for i, (when, value) in enumerate(zip(times, values, strict=True)):
        arm.predict(float(when))
        spread = float(arm.sd) ** 2 + noise * noise
        mu, sd = float(arm.value), math.sqrt(spread)
        if i >= start:
            z = (value - mu) / sd
            total += -0.5 * (z * z + math.log(2.0 * math.pi * spread))
            pits.append(0.5 * (1.0 + math.erf(z / math.sqrt(2.0))))
            scores.append(crps([(q, mu + sd * _normal_quantile(q)) for q in QUANTILES], value))
        arm.update(float(value), noise * noise, float(when))
    if not scores:
        return None
    return total / len(scores), pit_flatness(pits), statistics.mean(scores)


def main() -> None:
    print(f"frame {FRAME}  members {DEFAULT}  adapting\n")
    print(
        "`Pooled` arms weight by what a member **claims** about itself; the\n"
        "policy arms weight by which one actually predicted best. Both see\n"
        "every member's density every step, so the only difference is the\n"
        "source of the weight.\n"
    )
    arms = {
        "Pooled, alpha 1": Pooled,
        "Pooled, argmax": lambda: Pooled(rule="argmax"),
        "ucb": lambda: Selector("ucb"),
        "epsilon greedy": lambda: Selector("epsilon"),
        "exp3": lambda: Selector("exp3"),
        "random (the null)": lambda: Selector("random"),
    }
    for group, names in (("traded", TRADED), ("generated", GENERATED)):
        print("=" * 84)
        print(group)
        print("=" * 84)
        print(f"{'arm':<20}{'loglike/bar':>13}{'pit':>10}{'crps':>12}{'switch %':>10}{'cells':>7}")
        for label, make in arms.items():
            cells, switching = [], []
            for name in names:
                got = load(name)
                if got is None:
                    continue
                arm = make()
                out = score(got[0], got[1], arm)
                if out and all(math.isfinite(v) for v in out):
                    cells.append(out)
                    if isinstance(arm, Selector):
                        switching.append(100.0 * arm.switches / max(len(got[0]), 1))
            if not cells:
                continue
            print(
                f"{label:<20}{statistics.median(c[0] for c in cells):>13.4f}"
                f"{statistics.median(c[1] for c in cells):>10.2f}"
                f"{statistics.median(c[2] for c in cells):>12.6f}"
                f"{(statistics.median(switching) if switching else float('nan')):>10.1f}"
                f"{len(cells):>7}"
            )
        print()
    print(
        "**`random` is the arm that makes the others mean something.** A policy\n"
        "that cannot beat picking a member by coin flip is not selecting, and\n"
        "`statespace-pooling-exponent.md` already measured random selection at\n"
        "4.7 times worse than precision-weighted winner-take-all - so the bar\n"
        "is real and was set before this ran.\n\n"
        "And `switch %` is worth reading beside the score. A policy that never\n"
        "switches has collapsed onto one member, which is the `sticky` arm that\n"
        "scored 5.3 times worse; one that switches every step is not selecting\n"
        "either, it is averaging with extra steps."
    )


if __name__ == "__main__":
    main()
