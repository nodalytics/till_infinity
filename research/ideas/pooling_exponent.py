"""Pool members by precision to a power, and find the power the data wants.

`family.py` frames the thesis as a measurement between two imports: "which
filter does this state need" is asked per state. It never asks the next
question, which is whether several of them can be **pooled** - nothing in the
package combines members, so every comparison so far has been a contest with
one winner.

*Radical Markets* supplies the mechanism worth testing. Under **quadratic
voting** a voter's influence is the **square root** of the credits they spend,
so a strong preference costs disproportionately more and a minority can be
heard without one loud voice carrying the room. Written as a weight that is
`precision ** 0.5` rather than `precision`, it is a pooling rule - and this
desk has a measured defect it fits: `probability_up` reaches AUC 0.6365 while
being **about twice as confident as it should be**, patched with a fitted
shrink of 0.47.

Standard inverse-variance pooling weights a member by its precision, which
rewards exactly the member that has **understated** its own uncertainty. So the
exponent is swept rather than assumed.

## Two things are being varied and they must not be confused

**The weight exponent `alpha`**, with `w_i = (1 / sigma_i^2) ** alpha`.
`alpha = 1` is the Bayesian rule for independent estimates, `0.5` is quadratic
voting, `0` is one member one vote.

**And how the pooled spread is formed**, which is where the over-confidence
actually lives:

* **shrinking**, `1 / sum(precision)` - the textbook companion to `alpha = 1`.
  It is *below every member's own spread*, which is correct only if the members
  are independent. Members reading the same series are not remotely
  independent, so this is the term that manufactures confidence;
* **mixture**, `sum(w_i (sigma_i^2 + (mu_i - mu)^2))` - the law of total
  variance. It cannot fall below the members' own disagreement, so it is the
  conservative choice and the honest default for correlated estimators.

Reporting a sweep of `alpha` without saying which spread rule is in force
would confound the two, so both are run at every `alpha`.

## Scored on all three, because they disagree by design

`loglike` rewards sharpness, `pit` rewards calibration, and a rule can buy one
with the other. `crps` is the one that cannot be gamed either way - a band can
be perfectly calibrated and useless by being wide, and `crps` sees that.

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

from till_infinity.statespace.diagnostics import crps, pit_flatness  # noqa: E402
from till_infinity.statespace.family import members  # noqa: E402

CACHE = Path(os.environ.get("SEQLAB_CACHE", str(Path.home() / "till_infinity/data/seqlab")))
FRAME = os.environ.get("FRAME", "1h")
LIMIT = int(os.environ.get("LIMIT", "12000"))
ALPHAS = tuple(float(x) for x in os.environ.get("ALPHAS", "0,0.25,0.5,0.75,1,1.5").split(","))
SEED = 20261013
#: Members that carry a posterior spread, which pooling needs. `selective`
#: reports a fitted spread rather than an inferred one and `swarm` is a
#: particle cloud, so neither belongs in a precision weight.
#:
#: **`landau` is deliberately absent, and the single-member arm is why.** It
#: scored `2.9734 / 2591.38 / 0.005432` - identical to `reverting` in all three
#: figures to four decimal places - because `Landau` at its default `kappa = 0`
#: *is* `Reverting`, which its own docstring states: the same state, the same
#: covariance, the same likelihood, which is what makes it a nested
#: one-parameter test. Including both put **twice** the weight on reverting
#: behaviour and called it a four-member pool.
#:
#: `robust` is kept although it scores within 0.002 of `kalman`. It subclasses
#: `Gaussian` and only departs from it when an innovation is large enough to
#: trigger the redescending weight, so the near-identical median is expected
#: and the member is genuinely different where it matters - in the tails,
#: which is the part a pooled band is for.
USE = tuple(os.environ.get("USE", "kalman,reverting,robust").split(","))
TRADED = tuple(os.environ.get("TRADED", "EURUSD,GBPUSD,USDJPY,XAUUSD,AUDUSD,USDCAD").split(","))
GENERATED = tuple(os.environ.get("GENERATED", "Volatility_75_Index,Step_Index_200").split(","))
QUANTILES = tuple(i / 20.0 for i in range(1, 20))


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


def _normal_quantile(share: float) -> float:
    """Acklam's inverse normal, enough for a quantile grid."""
    from till_infinity.statespace.distance import _normal_quantile as inner

    return inner(share)


def alone(times, values, which: str):
    """The same three scores for **one** member, which is the arm that matters.

    **A pool cannot be judged without it.** Every pooled row below reads a PIT
    flatness in the tens or hundreds against the 1.0 of a calibrated band, and
    that is either a fact about pooling or a fact about the members. Only the
    single-member arm can say which, and leaving it out was the difference
    between a finding and a table.
    """
    import numpy as np

    built = members()
    if which not in built:
        return None
    one = built[which]()
    steps = [abs(values[i] - values[i - 1]) for i in range(1, len(values))]
    noise = statistics.pstdev(steps) or 1e-9
    start = len(times) // 2
    total, scores, pits = 0.0, [], []
    for i, (when, value) in enumerate(zip(times, values, strict=True)):
        one.predict(float(when))
        mu, sd = float(one.value), max(float(one.sd), 1e-12)
        if i >= start:
            z = (value - mu) / sd
            total += -0.5 * (z * z + math.log(2.0 * math.pi * sd * sd))
            pits.append(0.5 * (1.0 + math.erf(z / math.sqrt(2.0))))
            scores.append(
                crps([(q, mu + sd * _normal_quantile(q)) for q in QUANTILES], value)
            )
        one.update(float(value), noise * noise, float(when))
    if not scores:
        return None
    _ = np
    return total / len(scores), pit_flatness(pits), statistics.mean(scores)


def run(times, values, alpha: float, spread: str, pick: str = "weight", seed: int = 0):
    """One pass. Returns held-out `(loglike, pit, crps)` for the pool.

    `pick` chooses how the members are combined, which is the second question
    this harness answers:

    * `weight` - the precision-weighted blend, swept over `alpha`;
    * `argmax` - **winner takes all**, every step. *A Thousand Brains* argues
      the cortex's columns vote and one interpretation wins at a time, and the
      illusions it cites are the evidence: a vase or a face, never a blend of
      the two. As a rule here it is `alpha` at infinity;
    * `random` - **the null for `argmax`**, choosing a member uniformly at
      random each step. Winner-take-all that cannot beat this is not selecting,
      it is just being one member at a time. This desk has read a blend
      comparison wrong once already, where the rotation null scored +104.4
      against the real +35.6, so the null is built in from the start rather
      than added when the answer looks good;
    * `sticky` - one member chosen at random for the **whole** run, which is
      the null for *switching* rather than for selecting. It separates "picking
      the right member" from "picking a member at all".
    """
    import numpy as np

    built = members()
    pool = [built[name]() for name in USE if name in built]
    if len(pool) < 2:
        return None
    chooser = np.random.default_rng(seed)
    stuck = int(chooser.integers(0, len(pool)))
    steps = [abs(values[i] - values[i - 1]) for i in range(1, len(values))]
    noise = statistics.pstdev(steps) or 1e-9
    start = len(times) // 2
    total, scores, pits = 0.0, [], []
    for i, (when, value) in enumerate(zip(times, values, strict=True)):
        mus, sds = [], []
        for one in pool:
            one.predict(float(when))
            mus.append(float(one.value))
            sds.append(max(float(one.sd), 1e-12))
        precision = np.array([1.0 / (s * s) for s in sds])
        if pick == "argmax":
            weights = np.zeros(len(pool))
            weights[int(np.argmax(precision))] = 1.0
        elif pick == "random":
            weights = np.zeros(len(pool))
            weights[int(chooser.integers(0, len(pool)))] = 1.0
        elif pick == "sticky":
            weights = np.zeros(len(pool))
            weights[stuck] = 1.0
        else:
            weights = precision**alpha
            weights = weights / weights.sum()
        mu = float(np.dot(weights, mus))
        if pick != "weight":
            # A selection carries the chosen member's own spread. Using
            # `1/sum(precision)` here would hand a single member the precision
            # of the whole pool, which is the one way to make winner-take-all
            # look good for a reason that has nothing to do with selecting.
            chosen = int(np.argmax(weights))
            var = sds[chosen] ** 2
        elif spread == "shrinking":
            var = 1.0 / float(precision.sum())
        else:
            # Law of total variance: within-member plus between-member. Cannot
            # fall below the members' own disagreement.
            var = float(
                np.dot(weights, [s * s for s in sds])
                + np.dot(weights, [(m - mu) ** 2 for m in mus])
            )
        sd = math.sqrt(max(var, 1e-24))
        if i >= start:
            z = (value - mu) / sd
            total += -0.5 * (z * z + math.log(2.0 * math.pi * var))
            # A normal predictive, so the PIT is the normal CDF of z.
            pits.append(0.5 * (1.0 + math.erf(z / math.sqrt(2.0))))
            scores.append(
                crps([(q, mu + sd * _normal_quantile(q)) for q in QUANTILES], value)
            )
        for one in pool:
            one.update(float(value), noise * noise, float(when))
    if not scores:
        return None
    return total / len(scores), pit_flatness(pits), statistics.mean(scores)


def main() -> None:
    print(f"frame {FRAME}  members {USE}  alphas {ALPHAS}\n")
    print(
        "`alpha` is the power the precision is raised to in the weight:\n"
        "1 is the Bayesian rule for independent estimates, 0.5 is quadratic\n"
        "voting, 0 is one member one vote. `spread` is how the pooled\n"
        "uncertainty is formed, and it is the term that makes a pool\n"
        "over-confident: `shrinking` is 1/sum(precision), which sits below\n"
        "every member's own spread and is only right if they are independent.\n"
        "`pit` of 1.0 is calibrated; above 1 is over-confident.\n"
    )
    for group, names in (("traded", TRADED), ("generated", GENERATED)):
        print("=" * 96)
        print(group)
        print("=" * 96)
        print(
            f"{'spread':<12}{'alpha':>7}{'loglike/bar':>13}{'pit':>9}"
            f"{'crps':>11}{'instruments':>13}"
        )
        for which in USE:
            cells = []
            for name in names:
                got = load(name)
                if got is None:
                    continue
                out = alone(got[0], got[1], which)
                if out and all(math.isfinite(v) for v in out):
                    cells.append(out)
            if cells:
                print(
                    f"{('one: ' + which):<12}{'-':>7}"
                    f"{statistics.median(c[0] for c in cells):>13.4f}"
                    f"{statistics.median(c[1] for c in cells):>9.2f}"
                    f"{statistics.median(c[2] for c in cells):>11.6f}"
                    f"{len(cells):>13}"
                )
        for spread in ("shrinking", "mixture"):
            for alpha in ALPHAS:
                cells = []
                for name in names:
                    got = load(name)
                    if got is None:
                        continue
                    out = run(got[0], got[1], alpha, spread)
                    if out and all(math.isfinite(v) for v in out):
                        cells.append(out)
                if not cells:
                    continue
                print(
                    f"{spread:<12}{alpha:>7.2f}"
                    f"{statistics.median(c[0] for c in cells):>13.4f}"
                    f"{statistics.median(c[1] for c in cells):>9.2f}"
                    f"{statistics.median(c[2] for c in cells):>11.6f}"
                    f"{len(cells):>13}"
                )
        # Winner-take-all and its two nulls, each carrying the chosen member's
        # own spread rather than the pool's.
        for pick in ("argmax", "random", "sticky"):
            cells = []
            for name in names:
                got = load(name)
                if got is None:
                    continue
                draws = [
                    run(got[0], got[1], 1.0, "own", pick=pick, seed=SEED + k)
                    for k in range(3 if pick != "argmax" else 1)
                ]
                good = [d for d in draws if d and all(math.isfinite(v) for v in d)]
                if good:
                    cells.append(tuple(statistics.median(g[i] for g in good) for i in range(3)))
            if cells:
                print(
                    f"{pick:<12}{'-':>7}"
                    f"{statistics.median(c[0] for c in cells):>13.4f}"
                    f"{statistics.median(c[1] for c in cells):>9.2f}"
                    f"{statistics.median(c[2] for c in cells):>11.6f}"
                    f"{len(cells):>13}"
                )
        print()
    print(
        "**Read `pit` first and `crps` second.** A pool can buy likelihood by\n"
        "being over-confident and the `pit` column is what catches it; `crps`\n"
        "is the one quantity that cannot be gamed in either direction, since a\n"
        "band can be perfectly calibrated and useless by being wide.\n\n"
        "The claim being tested is that `alpha = 0.5` caps how far one member\n"
        "that has understated its own uncertainty can carry the pool. If the\n"
        "`shrinking` rows are over-confident and fall as `alpha` rises while\n"
        "`mixture` does not, the over-confidence was the **spread rule** rather\n"
        "than the weights - and quadratic voting is answering a question that\n"
        "the law of total variance already answers better.\n\n"
        "**`argmax` against `random` is the selection test.** Winner-take-all\n"
        "that cannot beat a member chosen at random each step is not selecting\n"
        "anything, and `sticky` separates picking the *right* member from\n"
        "picking *a* member - a blend comparison here has been read wrong once\n"
        "already, with the rotation null at +104.4 against the real +35.6.\n\n"
        "**And the `one:` rows decide what any of it means.** If a single member\n"
        "is calibrated and every pool is not, pooling is the fault. If no\n"
        "member is calibrated either, then the pool inherited the problem and\n"
        "the weighting rule was never going to fix it."
    )


if __name__ == "__main__":
    main()
