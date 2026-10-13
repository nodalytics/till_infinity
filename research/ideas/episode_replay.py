"""Prod's own directional call, scored on prod's own episodes.

Asked whether the state-space members would pick similar or better trades than
production. The episode record turns that into something sharper than a
comparison of two opinions, because it carries **both sides of the question
already**: prod's prediction *and* the realised answer.

Every `kind=observation, actor=structures` entry in the journal holds

* what prod thought - `probability_up`, `base_rate_up`, `edge`, `actionable`,
  `velocity_r`;
* what the price then did - `first` (which barrier came first), `held_first`,
  `bars_up_1r`, `bars_down_1r`, `mfe_up_r`, `mfe_down_r`, `mae_at_up1_r`;
* and the geometry - `entry`, `level`, `r_price`, `r_vol`, `horizon_bars`.

So prod and a member can be scored on the **same binary, on the same events,
against the same realised outcome.** That is a proper scoring-rule comparison
rather than a confusion matrix, and it needs no broker, no MT5 and no price
history - everything is in the record.

## Four arms, and the second one is prod's own null

| arm | what it is |
| --- | --- |
| `probability_up` | prod's directional call |
| `base_rate_up` | **prod's own unconditional rate** - the null prod already carries |
| constant 0.5 | the floor |
| a member's drift, mapped to `P(up first)` | the addition under test |

The second arm is the one that matters. A `probability_up` that beats 0.5 but
not `base_rate_up` has learnt the marginal and nothing about the event - which
is exactly how `hmm.Direction` failed, where a two-state chain beat a fair coin
by +5.5 nats and its own shuffled signs by **-0.1**.

## The member's arm is a barrier probability, not a direction

`statespace-triple-barrier.md` settled the mapping. For symmetric barriers at
`+/- 1r` under Brownian motion with drift `mu` and volatility `sigma`,

    P(up first) = 1 / (1 + exp(-2 mu a / sigma^2))

and at zero drift that is gambler's ruin's one half, *whatever the volatility
path*. So a member's contribution here is entirely its drift estimate, scaled
by the barrier width in volatility units - and
`statespace-directional-edge.md` has just measured that drift's best case at
**2% of a spread on a planted drift**. The expectation is therefore 0.5 and
nothing added; the arm exists so that is a measurement rather than an
inference.

## Scored on Brier and log loss, and calibrated by bucket

A Brier score is the mean squared error of a probability and a log loss is its
negative log-likelihood; both are proper, so neither can be improved by
shading a forecast away from what is believed. The calibration curve - realised
up-rate against predicted, by bucket - is what says whether a number like
`probability_up = 0.62` means anything at all.

Reads the extract produced from the journal; see the harness header in
`statespace-episode-replay.md` for how that was taken safely off a live box.
"""

from __future__ import annotations

import gzip
import json
import math
import os
import statistics
from collections import Counter
from pathlib import Path

EXTRACT = Path(os.environ.get("EXTRACT", "episodes.jsonl.gz"))
BUCKETS = 10
#: Minimum episodes before a cell is reported at all.
LEAST = 200


def load(path: Path):
    rows = []
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def outcome(row) -> float | None:
    """1.0 if the up barrier came first, 0.0 if down, `None` if neither.

    Episodes that resolved to neither barrier are **dropped rather than
    counted either way**, and the share dropped is reported: a timed-out
    episode is a third outcome and folding it into a binary would bias
    whichever side happens to be commoner.
    """
    first = row.get("first")
    if isinstance(first, str):
        low = first.lower()
        if low in ("up", "u", "+1", "1", "true"):
            return 1.0
        if low in ("down", "d", "-1", "0", "false"):
            return 0.0
        return None
    if isinstance(first, (int, float)):
        if first > 0:
            return 1.0
        if first < 0:
            return 0.0
    return None


def brier(predictions, answers) -> float:
    return statistics.fmean((p - a) ** 2 for p, a in zip(predictions, answers, strict=True))


def logloss(predictions, answers, floor: float = 1e-6) -> float:
    total = 0.0
    for p, a in zip(predictions, answers, strict=True):
        q = min(max(p, floor), 1.0 - floor)
        total += -(a * math.log(q) + (1.0 - a) * math.log(1.0 - q))
    return total / len(answers)


def member_probability(row, gain: float = 1.0) -> float | None:
    """`P(up first)` from the drift, by the barrier mapping.

    **The first version of this was a failed implementation, not a
    measurement, and the scores said so**: a Brier of 0.505 with a log loss of
    6.55 means predictions pinned near 0 and 1 and wrong about half the time,
    which is a saturating map rather than an informative-but-wrong signal. It
    assumed `velocity_r * horizon_bars` was already the drift in `r` units
    over the horizon, and it is evidently not on that scale.

    So `gain` is fitted on the training half instead of assumed. The mapping
    itself is the barrier one from `statespace-triple-barrier.md`: with
    symmetric barriers the exponent is `2 mu a / sigma^2`, so

        P(up first) = 1 / (1 + exp(-gain * velocity_r))

    and a `gain` fitted to zero would say the drift carries nothing - which is
    the honest version of the arm, and the one the directional work predicts.
    """
    velocity = row.get("velocity_r")
    if velocity is None:
        return None
    try:
        drift = float(velocity)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(drift):
        return None
    return 1.0 / (1.0 + math.exp(-max(min(gain * drift, 40.0), -40.0)))


def shrink(predictions, answers, half: int):
    """Fit `p' = 0.5 + k (p - 0.5)` on the first half, score on the second.

    A calibration curve that is **monotone but too steep** says the ordering is
    real and the magnitude is overstated, which is exactly what a single
    shrinkage coefficient repairs. Fitted by minimising the training Brier over
    a grid, and reported on data the fit never saw - a shrinkage chosen on the
    scored half would be guaranteed to help.
    """
    best = None
    for i in range(0, 161):
        k = i / 100.0
        got = brier([0.5 + k * (p - 0.5) for p in predictions[:half]], answers[:half])
        if best is None or got < best[1]:
            best = (k, got)
    k = best[0]
    held = [0.5 + k * (p - 0.5) for p in predictions[half:]]
    return k, held, answers[half:]


def auc(predictions, answers) -> float:
    """Rank-ordering power, which a miscalibrated probability keeps.

    Brier and log loss mix discrimination with calibration, so a signal that
    ranks well and is scaled badly scores worse than a constant. This separates
    the two: 0.5 is no ordering at all.
    """
    pairs = sorted(zip(predictions, answers, strict=True))
    ranks, i = [0.0] * len(pairs), 0
    while i < len(pairs):
        j = i
        while j + 1 < len(pairs) and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        shared = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[k] = shared
        i = j + 1
    ups = sum(1 for _p, a in pairs if a > 0.5)
    downs = len(pairs) - ups
    if not ups or not downs:
        return float("nan")
    rank_sum = sum(r for r, (_p, a) in zip(ranks, pairs, strict=True) if a > 0.5)
    return (rank_sum - ups * (ups + 1) / 2.0) / (ups * downs)


def calibration(predictions, answers, buckets: int = BUCKETS):
    """Realised rate by predicted bucket. The curve a probability has to pass."""
    rows = []
    for i in range(buckets):
        low, high = i / buckets, (i + 1) / buckets
        picked = [
            a
            for p, a in zip(predictions, answers, strict=True)
            if low <= p < high or (i == buckets - 1 and p == 1.0)
        ]
        if len(picked) < 30:
            rows.append(None)
            continue
        rows.append((len(picked), statistics.fmean(picked), (low + high) / 2.0))
    return rows


def main() -> None:
    if not EXTRACT.exists():
        print(f"no extract at {EXTRACT}")
        return
    rows = load(EXTRACT)
    print(f"{len(rows):,} episode records read from {EXTRACT}\n")

    kinds = Counter(str(r.get("first")) for r in rows)
    print("`first` values:", ", ".join(f"{k}={v:,}" for k, v in kinds.most_common(6)))
    feeds = Counter(str(r.get("feed")) for r in rows)
    print(
        f"{len(feeds)} feeds, commonest:", ", ".join(f"{k}={v:,}" for k, v in feeds.most_common(5))
    )
    shapes = Counter(str(r.get("shape")) for r in rows)
    print(
        f"{len(shapes)} shapes, commonest:",
        ", ".join(f"{k}={v:,}" for k, v in shapes.most_common(5)),
    )

    usable, dropped = [], 0
    for row in rows:
        got = outcome(row)
        if got is None:
            dropped += 1
            continue
        usable.append((row, got))
    print(
        f"\n{len(usable):,} resolved to a barrier, {dropped:,} did not "
        f"({dropped / max(len(rows), 1):.1%} dropped rather than folded in)"
    )
    if len(usable) < LEAST:
        print("too few to score")
        return
    answers = [a for _r, a in usable]
    print(f"realised up-first rate: {statistics.fmean(answers):.4f}")

    print("\n" + "=" * 96)
    print("ARM 1  prod's own call against prod's own null")
    print("=" * 96)
    print(f"{'arm':<26}{'n':>9}{'Brier':>10}{'log loss':>11}{'vs 0.5':>10}{'vs base':>10}")

    arms: dict[str, list[float]] = {"constant 0.5": [0.5] * len(usable)}
    for name, key in (
        ("prod probability_up", "probability_up"),
        ("prod base_rate_up", "base_rate_up"),
    ):
        got = [float(r[key]) for r, _a in usable if isinstance(r.get(key), (int, float))]
        if len(got) == len(usable):
            arms[name] = got
    half = len(usable) // 2
    # Fit the member's gain on the training half only.
    best_gain, best_score = 0.0, None
    for i in range(-60, 61):
        gain = i / 2.0
        got = [member_probability(r, gain) for r, _a in usable[:half]]
        if any(g is None for g in got):
            break
        score = brier([float(g) for g in got], answers[:half])
        if best_score is None or score < best_score:
            best_gain, best_score = gain, score
    member = [member_probability(r, best_gain) for r, _a in usable]
    if all(m is not None for m in member):
        arms[f"member drift (gain {best_gain:g})"] = [float(m) for m in member]

    floor = brier(arms["constant 0.5"], answers)
    base = brier(arms.get("prod base_rate_up", arms["constant 0.5"]), answers)
    for name, predictions in arms.items():
        b = brier(predictions, answers)
        print(
            f"{name:<26}{len(predictions):>9,}{b:>10.5f}{logloss(predictions, answers):>11.5f}"
            f"{floor - b:>+10.5f}{base - b:>+10.5f}"
        )
    print(
        "\n'vs 0.5' and 'vs base' are Brier improvements, so **positive is\n"
        "better**. Beating 0.5 and not `base_rate_up` means the marginal was\n"
        "learnt and the event was not."
    )

    if "prod probability_up" in arms:
        print("\n" + "=" * 96)
        print("ARM 2  is `probability_up` calibrated?")
        print("=" * 96)
        print(f"{'predicted':<14}{'n':>9}{'realised':>11}{'gap':>9}")
        for row in calibration(arms["prod probability_up"], answers):
            if row is None:
                continue
            n, realised, middle = row
            print(f"{middle:<14.2f}{n:>9,}{realised:>11.4f}{realised - middle:>+9.4f}")

        print("\n" + "=" * 96)
        print("ARM 3  the ordering is real; does shrinking it repair the score?")
        print("=" * 96)
        print(
            "A monotone but too-steep curve says the ordering is real and the\n"
            "magnitude overstated, which one coefficient repairs. `k` is fitted\n"
            "on the first half and everything below is the second half only.\n"
        )
        predictions = arms["prod probability_up"]
        k, held, held_answers = shrink(predictions, answers, half)
        raw = brier(predictions[half:], answers[half:])
        print(f"{'arm':<30}{'n':>9}{'Brier':>10}{'log loss':>11}{'AUC':>9}")
        for name, ps in (
            ("constant 0.5", [0.5] * len(held_answers)),
            ("probability_up, raw", predictions[half:]),
            (f"probability_up x {k:g}", held),
        ):
            print(
                f"{name:<30}{len(ps):>9,}{brier(ps, held_answers):>10.5f}"
                f"{logloss(ps, held_answers):>11.5f}{auc(ps, held_answers):>9.4f}"
            )
        print(
            f"\nfitted shrinkage k = {k:g}; raw held-out Brier {raw:.5f}, "
            f"shrunk {brier(held, held_answers):.5f}, "
            f"constant {brier([0.5] * len(held_answers), held_answers):.5f}"
        )

        actionable = [
            (p, a)
            for (r, a), p in zip(usable, arms["prod probability_up"], strict=True)
            if r.get("actionable")
        ]
        if len(actionable) > LEAST:
            ps = [p for p, _a in actionable]
            as_ = [a for _p, a in actionable]
            print(
                f"\nactionable only: {len(actionable):,} episodes "
                f"({len(actionable) / len(usable):.1%}), "
                f"Brier {brier(ps, as_):.5f} against {brier([0.5] * len(as_), as_):.5f} for 0.5, "
                f"realised up-rate {statistics.fmean(as_):.4f}"
            )
    print("\nDONE")


if __name__ == "__main__":
    main()
