"""Which model class predicts which way a touch resolves.

Run from the repository root:  python research/harness/models.py

Every model is walk-forward: each touch is predicted before it is learned and
never from itself. Two nulls sit in the table and both matter. `always up` is
the majority class. `random 12` is a neighbour vote with no similarity at all,
which is the bar any similarity metric has to clear - and none of them do by
much.

Memory and time per call are reported because the box is 908MB with a 640MB
container cap and has been OOM-killed five times. A model that wins and does
not fit has not won.
"""

from __future__ import annotations

import math
import pickle
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from till_infinity.structures import facto  # noqa: E402

from river import (
    active,
    ensemble,
    forest,
    linear_model,
    naive_bayes,
    neural_net,
    preprocessing,
    tree,
)
from touches import FIELDS, load

K = 12
WARM = 150
KEYS = (*FIELDS, "above")


def euclid(a, b):
    return math.sqrt(sum((a[k] - b[k]) ** 2 for k in KEYS))


def cosine(a, b):
    dot = sum(a[k] * b[k] for k in KEYS)
    na = math.sqrt(sum(a[k] ** 2 for k in KEYS))
    nb = math.sqrt(sum(b[k] ** 2 for k in KEYS))
    return 1.0 - dot / (na * nb) if na and nb else 1.0


def manhattan(a, b):
    return sum(abs(a[k] - b[k]) for k in KEYS)


def build():
    """One of each family river offers that is plausible on this box."""
    return {
        "logistic regression": preprocessing.StandardScaler() | linear_model.LogisticRegression(),
        "gaussian naive bayes": naive_bayes.GaussianNB(),
        "hoeffding tree": tree.HoeffdingTreeClassifier(grace_period=50),
        "hoeffding adaptive tree": tree.HoeffdingAdaptiveTreeClassifier(grace_period=50, seed=7),
        "extremely fast tree": tree.ExtremelyFastDecisionTreeClassifier(grace_period=50),
        "adaptive random forest": forest.ARFClassifier(n_models=10, seed=7),
        "mondrian forest": forest.AMFClassifier(n_estimators=10, seed=7),
        "adwin bagging": ensemble.ADWINBaggingClassifier(
            model=tree.HoeffdingTreeClassifier(grace_period=50), n_models=10, seed=7
        ),
        "leveraging bagging": ensemble.LeveragingBaggingClassifier(
            model=tree.HoeffdingTreeClassifier(grace_period=50), n_models=10, seed=7
        ),
        "srp": ensemble.SRPClassifier(
            model=tree.HoeffdingTreeClassifier(grace_period=50), n_models=10, seed=7
        ),
        "mlp (regressor, thresholded)": preprocessing.StandardScaler()
        | neural_net.MLPRegressor(
            hidden_dims=(16,),
            activations=(neural_net.activations.ReLU, neural_net.activations.Identity),
            seed=7,
        ),
        # Active learning: the wrapper decides which touches are worth learning
        # from at all. Scored on accuracy *and* on how many labels it used.
        "entropy sampler (logistic)": active.EntropySampler(
            classifier=preprocessing.StandardScaler() | linear_model.LogisticRegression(),
            seed=7,
        ),
    }


def main() -> None:
    rows = load()
    print(f"touches: {len(rows):,}, {sum(1 for r in rows if r[1]) / len(rows):.1%} up\n")

    models = build()
    timing = dict.fromkeys(models, 0.0)
    learned = dict.fromkeys(models, 0)
    scores = {name: [0, 0] for name in models}
    for extra in (
        "always up",
        "random 12",
        "euclidean 12",
        "cosine 12",
        "manhattan 12",
        "farthest 12",
    ):
        scores[extra] = [0, 0]

    rand = random.Random(11)
    # `facto` is ours: a factorisation machine regressing the realised push,
    # reachable only from `till-infinity structures fit` and consumed by nothing
    # in the running service. Scored here on direction, by the sign of what it
    # predicts, so it sits in the same table as everything else.
    ours = facto.Model()
    scores["facto (ours, push sign)"] = [0, 0]
    facto_time = 0.0

    for i, (x, up, _feed, _interval, _when, raw, push) in enumerate(rows):
        start = time.perf_counter()
        encoded = facto.encode(raw)
        said = ours.predict(encoded)
        if i >= WARM and said:
            scores["facto (ours, push sign)"][1] += 1
            scores["facto (ours, push sign)"][0] += (said > 0) == up
        ours.learn(encoded, push)
        facto_time += time.perf_counter() - start

        for name, model in models.items():
            start = time.perf_counter()
            regressor = "mlp" in name
            sampler = "entropy" in name
            answer = model.predict_one(x)
            # An active learner answers with (prediction, is-this-label-worth-having).
            ask = True
            if sampler:
                answer, ask = answer
            said = (answer > 0.5) if regressor and answer is not None else answer
            if said is not None and i >= WARM:
                scores[name][1] += 1
                scores[name][0] += said == up
            # The whole point of the sampler is that it declines most labels.
            if ask:
                model.learn_one(x, float(up) if regressor else up)
                learned[name] += 1
            timing[name] += time.perf_counter() - start

        scores["always up"][1] += 1
        scores["always up"][0] += up

        window = rows[max(0, i - 3000) : i]
        if len(window) < K * 3 or i < WARM:
            continue

        def vote(picked):
            return sum(1 for r in picked if r[1]) * 2 > len(picked)

        by_e = sorted(window, key=lambda r: euclid(x, r[0]))
        for name, picked in (
            ("random 12", rand.sample(window, K)),
            ("euclidean 12", by_e[:K]),
            ("cosine 12", sorted(window, key=lambda r: cosine(x, r[0]))[:K]),
            ("manhattan 12", sorted(window, key=lambda r: manhattan(x, r[0]))[:K]),
            ("farthest 12", by_e[-K:]),
        ):
            scores[name][1] += 1
            scores[name][0] += vote(picked) == up

    baseline = scores["random 12"][0] / scores["random 12"][1]
    print(
        f"{'model':<30} {'scored':>7} {'right':>7} {'vs random':>10} {'size':>9}"
        f" {'us/call':>8} {'labels':>7}"
    )
    print("-" * 86)
    for name in sorted(scores, key=lambda n: -(scores[n][0] / scores[n][1] if scores[n][1] else 0)):
        hits, n = scores[name]
        if not n:
            continue
        got = hits / n
        if name in models:
            size = f"{len(pickle.dumps(models[name])) / 1024:.0f}KB"
            per = f"{timing[name] / len(rows) * 1e6:.0f}"
            used = f"{100 * learned[name] / len(rows):.0f}%"
        elif name.startswith("facto"):
            size = f"{len(pickle.dumps(ours)) / 1024:.0f}KB"
            per = f"{facto_time / len(rows) * 1e6:.0f}"
            used = "100%"
        else:
            size = per = used = "-"
        print(
            f"{name:<30} {n:>7} {got:>6.1%} {100 * (got - baseline):>+9.1f}pp"
            f" {size:>9} {per:>8} {used:>7}"
        )


if __name__ == "__main__":
    main()
