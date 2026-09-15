"""Can ZMA learn its own mapping online, and does it learn to go quiet?

`research/zma.md` measured the shipped indicator as a working mean-reversion
detector pointed at processes that do not revert: AUC 0.62 on an OU control at
`theta = 0.15`, 0.49 to 0.52 on this desk's synthetics, and 0.376 to 0.461 -
reliably *wrong* - on Boom and Crash. **It still fires on ~15% of bars
everywhere**, because its thresholds are percentiles of its own history and a
percentile always has something above it.

That last sentence is the actual defect, and it is not a defect of the
*detector*. It is a defect of a **fixed rule**: the rule has no way to represent
"there is nothing here". This asks whether an online learner does, and it asks
it in a way that can come back "no".

## What "online" has to mean here, or the answer is meaningless

**Prequential.** Every prediction is made from a model that has not seen the bar
it is predicting, and the bar updates the model only afterwards. Test, then
train, one bar at a time. Any other order scores a model on its own training
data, and an online learner is *especially* easy to flatter this way because it
never has a train/test split to forget to make.

**Scored against saying nothing.** The baseline is not 0.5 - it is the running
base rate of the series itself, which on a drifting instrument is not 0.5. The
headline number is therefore **information gain**: the mean log-loss of the
always-base-rate predictor minus the model's own, in nats a bar. Zero means the
model added nothing. **Negative means it was worse than silence**, which is the
outcome the Boom and Crash arms should produce if this harness is honest.

## The four arms, and what each is for

* **`fixed`** - the shipped rule, unchanged. `agrees` as the direction, mapped
  to a fixed probability. The thing to beat.
* **`logistic`** - online logistic regression on ZMA's own features, SGD, one
  step a bar. The minimal conversion: same inputs, learned mapping.
* **`hedge`** - exponential weights over ZMA at four periods **plus a null
  expert that always predicts the running base rate**. The null expert is the
  point. Its final weight is a direct readout of how much signal the mixture
  believes is there, and on a random walk it should go to one.
* **`abstain`** - the logistic model, betting only when its probability is more
  than `TAU` from the base rate. No threshold is tuned: shrinkage does the
  abstaining, because a learner whose weights have gone to zero predicts the
  base rate and therefore stops betting by itself.

## The arm that is the whole argument

A fixed rule adapts to *scale* - that is what the percentiles are for - but it
cannot adapt to whether reversion exists at all. So the series that decides this
is **`switch`**: OU at `theta = 0.15` for 20,000 bars, geometric Brownian motion
for 20,000, then OU again. A learner worth having bets in the first segment,
falls quiet in the second, and comes back. The reported `bet rate by segment` is
that claim or its refutation.

    ./.secrets/lab.sh run research/harness/zmaonline.py

**Simulated, as `zma.md` was.** These are each family's documented mechanics,
not the feeds; `generators.md` and `grounding.md` are what they are faithful to.
The spread arm is the exception and needs the bar cache.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from till_infinity.structures.zma import Zma

#: Bars an arm. Long enough that the learners are past their own warm-up for
#: most of the sample, since a prequential score includes the learning.
BARS = int(os.environ.get("BARS", "40000"))

#: Bars discarded before scoring: the indicator needs its window and its
#: threshold history, and scoring a cold z-score measures the warm-up.
WARM = 400

#: Periods the mixture runs ZMA at. Spread wide on purpose - if the best period
#: is data-dependent, a mixture is the right object and a single fixed 50 is not.
PERIODS = (20, 50, 100, 200)

#: Learning rate for the logistic arm, and the mixture's inverse temperature.
#: Both fixed rather than tuned: a rate chosen by looking at the answer is a
#: fitted parameter wearing an online costume.
LR = 0.02
ETA = 0.5

#: Share of the mixture's weight mixed back toward uniform each bar, so that no
#: expert can be permanently killed. See `Hedge`.
ALPHA = 0.001

#: How far from the base rate the abstaining arm needs before it bets.
TAU = 0.02

#: What the fixed rule's `agrees` is worth as a probability. Deliberately mild -
#: the rule states a direction and not a confidence, and reading a hard 0.6 out
#: of it would score the number this harness invented.
FIXED_EDGE = 0.04


def sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-min(x, 60.0)))
    e = math.exp(max(x, -60.0))
    return e / (1.0 + e)


def auc(score: np.ndarray, label: np.ndarray) -> float:
    score, label = np.asarray(score, float), np.asarray(label)
    order = np.argsort(score)
    ranks = np.empty(len(score))
    ranks[order] = np.arange(1, len(score) + 1)
    n1, n0 = float((label == 1).sum()), float((label == 0).sum())
    if n1 == 0 or n0 == 0:
        return float("nan")
    return float((ranks[label == 1].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


def logloss(p: float, y: int) -> float:
    p = min(max(p, 1e-6), 1.0 - 1e-6)
    return -(math.log(p) if y else math.log(1.0 - p))


# --------------------------------------------------------------------- models


class Features:
    """ZMA's own readings, as a vector, scaled so a learning rate means something.

    The raw slope is in normalised-price units a bar and the raw z is in
    standard deviations, so they differ by orders of magnitude and a single
    learning rate would train one and ignore the other. The slope is divided by
    its own running mean absolute value - which the indicator already keeps for
    its thresholds - and the z by its own dynamic threshold, which is what the
    rule compares it against anyway.
    """

    def __init__(self, period: int) -> None:
        self.z = Zma(period=period)

    def push(self, price: float) -> list[float] | None:
        self.z.observe(price)
        if self.z.seen < WARM // 2:
            return None
        strong = max(self.z.strong, 1e-9)
        slopes = list(self.z._slopes)
        scale = (sum(slopes) / len(slopes)) if slopes else 0.0
        slope_n = self.z.slope / (scale + 1e-12)
        stretch = self.z.z_score / strong
        return [
            1.0,
            # Clipped because a percentile threshold can be tiny on a quiet
            # stretch, and one 300-sigma feature undoes a thousand updates.
            max(-5.0, min(5.0, stretch)),
            max(-5.0, min(5.0, slope_n)),
            # The interaction the fixed rule actually uses: displacement and
            # momentum pointing the same way. Given to the learner explicitly
            # rather than hoped for, so that "the learner did no better" cannot
            # be explained by it not having been shown the rule's own idea.
            max(-5.0, min(5.0, stretch)) * (1.0 if self.z.rising else -1.0),
        ]

    @property
    def agrees(self) -> int:
        return self.z.agrees


class Logistic:
    """Online logistic regression, one SGD step a bar, after the prediction."""

    def __init__(self, width: int, lr: float = LR) -> None:
        self.w = [0.0] * width
        self.lr = lr

    def predict(self, x: list[float]) -> float:
        return sigmoid(sum(wi * xi for wi, xi in zip(self.w, x, strict=True)))

    def update(self, x: list[float], y: int, p: float) -> None:
        g = y - p
        for i, xi in enumerate(x):
            self.w[i] += self.lr * g * xi


class Hedge:
    """Exponential weights over several ZMA periods **and over saying nothing**.

    The null expert is not a control bolted on beside the mixture - it is *in*
    the mixture, competing for weight. That makes "how much signal is here" a
    number the algorithm reports rather than a judgement somebody makes about
    its output, and it is the honest form of the question this study asks.

    **With fixed share, which the switching arm forced.** Plain exponential
    weights are a one-way door: after a few thousand bars the losing experts'
    weights underflow to exactly zero, and an expert at zero can never be
    revived by a multiplicative update however well it would now do. The first
    run of this harness showed it - the mixture ended a 60,000-bar OU/GBM/OU
    series at `null = 1.000` while sitting in a *reverting* segment, because the
    reverting experts had been killed off during the random walk in the middle
    and multiplication cannot bring back a zero.

    So each step mixes `ALPHA` of the weight back toward uniform
    (Herbster-Warmuth). That floors every expert at `ALPHA/N` and buys a regret
    bound against the best *sequence* of experts rather than the best single
    one - which is the right guarantee when the question is explicitly about a
    process that stops and starts.
    """

    def __init__(self, experts: int, eta: float = ETA, alpha: float = ALPHA) -> None:
        self.w = [1.0 / experts] * experts
        self.eta = eta
        self.alpha = alpha

    def predict(self, ps: list[float]) -> float:
        return sum(wi * pi for wi, pi in zip(self.w, ps, strict=True))

    def update(self, ps: list[float], y: int) -> None:
        losses = [logloss(p, y) for p in ps]
        best = min(losses)
        raw = [
            wi * math.exp(-self.eta * (li - best)) for wi, li in zip(self.w, losses, strict=True)
        ]
        total = sum(raw) or 1.0
        n = len(raw)
        self.w = [(1.0 - self.alpha) * (r / total) + self.alpha / n for r in raw]


# ------------------------------------------------------------------ the study


def scored(side: np.ndarray, y: np.ndarray, bet: np.ndarray) -> dict:
    """Hit rate on the bars the model bet, and its lift over guessing the drift.

    **Lift is against the majority class on the same bars, not against 0.50.**
    Boom and Crash move the same way on 499 of every 500 bars, so a raw hit rate
    there measures the drift: the first run of this harness reported 0.003,
    which reads as a catastrophic detector and is mostly a base rate. What a
    direction call has to beat is guessing the common direction every time.
    """
    if bet.sum() < 50:
        return {"hit": float("nan"), "lift": float("nan")}
    hit = float((side[bet] == (y[bet] == 1)).mean())
    majority = max(float((y[bet] == 1).mean()), float((y[bet] == 0).mean()))
    return {"hit": hit, "lift": hit - majority}


def thresholding(rows: list[dict], y: np.ndarray) -> dict:
    """What the `agrees` threshold costs, measured at an equal bet count.

    `-z`, because oversold is a *low* z and a rise is the label.

    The flag's own AUC is not comparable with the continuous one: `agrees` is
    zero on most bars, so the score is mostly ties and the AUC is pinned near
    0.5 by construction whatever the flag knows. What a flag can be asked is
    whether, on the bars it fires, it is right more often than the continuous
    reading is on **the same number** of its own most extreme bars. Same bet
    count, same series, so the only difference left is whether the threshold
    threw information away.
    """
    zs = -np.array([r["z"] for r in rows])
    out: dict = {"z_auc": auc(zs, y)}
    flag = np.array([r["agrees"] for r in rows])
    fires = flag != 0
    out["fired"] = int(fires.sum())
    if fires.sum() < 50:
        out["flag_hit"] = out["z_hit"] = float("nan")
        return out
    out["flag_hit"] = float(((flag[fires] > 0) == (y[fires] == 1)).mean())
    cut = np.quantile(np.abs(zs), 1.0 - fires.mean())
    top = np.abs(zs) >= cut
    out["z_hit"] = float(((zs[top] > 0) == (y[top] == 1)).mean())
    return out


def by_segment(rows: list[dict], bet: np.ndarray, segments: list[tuple[str, int, int]]) -> list:
    """Bet rate and mean null weight inside each segment of a switching series.

    The null weight is the self-silencing claim as a number the algorithm
    reports, rather than one read off its behaviour from outside.
    """
    idx = np.array([r["i"] for r in rows])
    nulls = np.array([r["null"] for r in rows])
    out = []
    for name, lo, hi in segments:
        inside = (idx >= lo) & (idx < hi)
        if not inside.sum():
            out.append((name, float("nan"), float("nan")))
            continue
        out.append((name, float(bet[inside].mean()), float(nulls[inside].mean())))
    return out


def run(prices: np.ndarray, segments: list[tuple[str, int, int]] | None = None) -> dict:
    """Every arm on one series, prequentially, sharing the same bars.

    One pass, all arms, so nothing can differ between them except the model -
    not the warm-up, not the sample, not the base rate they are scored against.
    """
    banks = [Features(p) for p in PERIODS]
    main = banks[PERIODS.index(50)]
    logistic = Logistic(4)
    hedge = Hedge(len(PERIODS) + 1)

    ups = downs = 0
    rows: list[dict] = []
    prior: dict | None = None

    for i, price in enumerate(prices):
        ready = [b.push(float(price)) for b in banks]
        if prior is not None:
            y = 1 if price > prior["price"] else 0
            base = prior["base"]
            rows.append(
                {
                    "i": prior["i"],
                    "y": y,
                    "base": base,
                    "fixed": prior["fixed"],
                    "logistic": prior["logistic"],
                    "hedge": prior["hedge"],
                    "bet": abs(prior["logistic"] - base) > TAU,
                    "z": prior["z"],
                    "null": prior["null"],
                    "agrees": prior["agrees"],
                }
            )
            logistic.update(prior["x"], y, prior["logistic"])
            hedge.update(prior["experts"], y)
            if y:
                ups += 1
            else:
                downs += 1
            prior = None

        x = ready[PERIODS.index(50)]
        if x is None or any(r is None for r in ready) or i < WARM:
            continue
        seen = ups + downs
        base = (ups + 1.0) / (seen + 2.0) if seen else 0.5
        experts = [sigmoid(-(r[1])) for r in ready]  # type: ignore[index]
        experts.append(base)
        prior = {
            "i": i,
            "price": float(price),
            "base": base,
            "x": x,
            "experts": experts,
            "fixed": min(max(base + FIXED_EDGE * main.agrees, 0.01), 0.99),
            "logistic": logistic.predict(x),
            "hedge": hedge.predict(experts),
            # The reading the rule thresholds, kept beside the flag it produces.
            # `zma.md` scored this and got 0.62 on the OU control; `agrees` is
            # what production publishes, and the two are not the same number.
            "z": main.z.z_score,
            "null": hedge.w[-1],
            "agrees": main.agrees,
        }

    if len(rows) < 1000:
        return {}

    y = np.array([r["y"] for r in rows])
    base = np.array([r["base"] for r in rows])
    silence = float(np.mean([logloss(b, int(yy)) for b, yy in zip(base, y, strict=True)]))
    out: dict = {"n": len(rows), "silence": silence, "null_weight": hedge.w[-1]}
    for arm in ("fixed", "logistic", "hedge"):
        p = np.array([r[arm] for r in rows])
        loss = float(np.mean([logloss(pi, int(yy)) for pi, yy in zip(p, y, strict=True)]))
        out[arm] = {"gain": silence - loss, "auc": auc(p, y)}

    out.update(thresholding(rows, y))
    bet = np.array([r["bet"] for r in rows])
    side = np.array([r["logistic"] for r in rows]) > base
    out["abstain"] = {"rate": float(bet.mean()), **scored(side, y, bet)}
    if segments:
        out["segments"] = by_segment(rows, bet, segments)
    out["weights"] = list(hedge.w)
    return out


# ---------------------------------------------------------------- generators


def ou(n: int, theta: float, sigma: float, rng, start: float = 100.0) -> np.ndarray:
    x = np.empty(n)
    x[0] = start
    shocks = rng.normal(0.0, sigma, n)
    for i in range(1, n):
        x[i] = x[i - 1] + theta * (start - x[i - 1]) + shocks[i]
    return x


def gbm(n: int, sigma_bar: float, rng, start: float = 100.0) -> np.ndarray:
    return start * np.exp(np.cumsum(rng.normal(0.0, sigma_bar, n)))


def step(n: int, rng, grid: float = 0.1, p_up: float = 0.499734, start: float = 7500.0):
    moves = np.where(rng.random(n) < p_up, grid, -grid)
    return start + np.cumsum(moves)


def spiky(n: int, rng, rate: int = 500, up: bool = True, start: float = 5000.0):
    drift = start * 0.00002
    out = np.empty(n)
    x = start
    for i in range(n):
        x += -drift if up else drift
        if rng.random() < 1.0 / rate:
            x += (1 if up else -1) * drift * rate * rng.uniform(0.8, 1.2)
        out[i] = max(x, 1.0)
    return out


def jumpy(n: int, sigma_bar: float, rng, rate: int = 25, start: float = 100.0):
    shocks = rng.normal(0.0, sigma_bar, n)
    hits = rng.random(n) < 1.0 / rate
    shocks[hits] += rng.normal(0.0, sigma_bar * 6.0, int(hits.sum()))
    return start * np.exp(np.cumsum(shocks))


def switching(n: int, rng) -> tuple[np.ndarray, list[tuple[str, int, int]]]:
    """Reverting, then not, then reverting again. **The arm that decides this.**

    Joined in log-return space and re-exponentiated so the level is continuous -
    a level jump at the seam would be a changepoint the detector could find,
    which is a different study.
    """
    third = n // 3
    minute = math.sqrt(1.0 / (365 * 24 * 60))
    parts = [
        ou(third, 0.15, 0.5, rng),
        gbm(third, 0.75 * minute, rng),
        ou(n - 2 * third, 0.15, 0.5, rng),
    ]
    rets = np.concatenate([np.diff(np.log(np.maximum(p, 1e-9))) for p in parts])
    prices = 100.0 * np.exp(np.cumsum(np.concatenate([[0.0], rets])))
    bounds = [
        ("reverting", 0, third),
        ("random walk", third, 2 * third),
        ("reverting again", 2 * third, len(prices)),
    ]
    return prices, bounds


def shuffled(prices: np.ndarray, rng) -> np.ndarray:
    rets = np.diff(np.log(np.maximum(prices, 1e-12)))
    rng.shuffle(rets)
    return float(prices[0]) * np.exp(np.concatenate([[0.0], np.cumsum(rets)]))


# --------------------------------------------------------------------- report


def show(name: str, got: dict) -> None:
    if not got:
        print(f"{name:26}  nothing scored")
        return
    print(
        f"{name:26} {got['n']:>7,} "
        f"{got['z_auc']:>6.3f} "
        f"{got['flag_hit']:>6.3f} {got['z_hit']:>6.3f} "
        f"{got['fixed']['gain'] * 1000:>+7.2f} "
        f"{got['logistic']['gain'] * 1000:>+8.2f} {got['logistic']['auc']:>6.3f} "
        f"{got['hedge']['gain'] * 1000:>+7.2f} "
        f"{got['null_weight']:>7.3f} "
        f"{got['abstain']['rate']:>6.1%} "
        f"{got['abstain']['lift']:>+7.3f}"
    )


def main() -> int:
    rng = np.random.default_rng(29)
    minute = math.sqrt(1.0 / (365 * 24 * 60))
    print("Can ZMA learn its own mapping online, and does it learn to go quiet?\n")
    print("Prequential: every prediction is made before the bar that scores it updates the")
    print("model. Gain is milli-nats a bar against always predicting the running base rate,")
    print("so 0 is 'added nothing' and negative is 'worse than silence'.")
    print("null wt is the mixture's weight on the expert that always says the base rate.")
    print("lift is the bet hit rate minus always guessing the common direction on those bars.")
    print("flag/top z: the rule's hit rate when `agrees` fires, against the continuous z's")
    print("hit rate on the same number of its own most extreme bars. Same bet count.\n")
    print(
        f"{'arm':26} {'n':>7} {'z auc':>6} {'flag':>6} {'top z':>6} {'fixed':>7} "
        f"{'logistic':>8} {'auc':>6} "
        f"{'hedge':>7} {'null wt':>7} {'bets':>6} {'lift':>7}"
    )

    switch, bounds = switching(60000, rng)
    arms: list[tuple[str, np.ndarray, list | None]] = [
        ("OU theta=0.02 (control)", ou(BARS, 0.02, 0.5, rng), None),
        ("OU theta=0.05 (control)", ou(BARS, 0.05, 0.5, rng), None),
        ("OU theta=0.15 (control)", ou(BARS, 0.15, 0.5, rng), None),
        ("switch OU/GBM/OU", switch, bounds),
        ("volatility 25", gbm(BARS, 0.25 * minute, rng), None),
        ("volatility 75", gbm(BARS, 0.75 * minute, rng), None),
        ("step index", step(BARS, rng), None),
        ("boom 500", spiky(BARS, rng, rate=500, up=True), None),
        ("crash 500", spiky(BARS, rng, rate=500, up=False), None),
        ("jump 25", jumpy(BARS, 0.25 * 1.322 * minute, rng, rate=25), None),
    ]
    results: dict[str, dict] = {}
    for name, series, segs in arms:
        got = run(series, segs)
        results[name] = got
        show(name, got)
        if got and name.startswith("OU theta=0.15"):
            show("  its own shuffle", run(shuffled(series, rng)))

    seg = results.get("switch OU/GBM/OU", {}).get("segments")
    if seg:
        print("\nThe arm that decides this - one series, one model, read by segment:")
        print(f"  {'segment':20} {'bets':>7} {'null wt':>8}")
        for label, rate, null in seg:
            print(f"  {label:20} {rate:>7.1%} {null:>8.3f}")
        print("A learner worth having bets in the reverting segments and falls quiet between.")

    best = results.get("OU theta=0.15 (control)", {}).get("weights")
    if best:
        print("\nMixture weights on the OU control, by ZMA period, null expert last:")
        print(
            "  " + "  ".join(f"{p}:{w:.3f}" for p, w in zip((*PERIODS, "null"), best, strict=True))
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
