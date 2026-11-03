"""Short the carry cross on a risk-off reading: mean R, a day-block CI, PF and DSR.

The framing's trade, stated as a rule and scored as one. *When fear rises,
money runs to JPY, CHF and gold and out of AUD, NZD and CAD, so AUDJPY and
NZDJPY fall fast.* That is a short on the cross conditioned on a risk-off
reading, and the conditioning is the part that matters: the claim is not "JPY
crosses fall" but "JPY crosses fall **fast when fear is rising**".

## Judged on mean R, not on a win rate

The carry-crash shape predicts a **low** win rate - down moves faster and
deeper, up moves longer and slower - so a short arm should win rarely and pay
well, and hit rate would reject it by construction. So the deciding numbers
are mean R with a day-block confidence interval, profit factor, and the
deflated Sharpe over the trial count; a win rate is reported as a descriptive.

And the variance is reported with the mean, never without. A low-win-rate
high-payoff arm has a larger per-trade sd, and the sample a given confidence
needs scales with it, so each arm carries its sd and the **sample its own CI
implies** - `node.metrics.minimum_track_record`. Comparing two arms' means
when their variances differ by a factor of two is comparing two different
questions.

## Everything is gross, and the primary result says so

No cost is charged anywhere. Of these instruments only `eurusd`, `gbpusd` and
`gold` have enough recorded quotes for a median spread, and **a synthetic
cross's spread is not the product of its legs' spreads - it is wider**, with no
recorded AUDJPY quote in this store to measure it against. `audjpy`'s own
unit at 1d is about 44 bp of close-to-close move, so a round trip of even 3-4
bp would be about 0.1R at the 1.0-unit stop; that is a *hypothetical* and is
not applied. What a costed read needs is one thing: recorded quotes for the
cross from the venue that would trade it.

## The nulls, and the one comparison that is forbidden

**Never against the analytic 1/(1+N).** `research/docs/level-shield.md` measured
a bar-level barrier race departing from the closed form by -0.25 to +0.12R,
monotone in (stop - target) distance and *larger* on every surrogate, up to
-0.73R on GARCH bars. A race judged against 1/(1+N) inherits a spurious
"wide stops are better" tilt. So every arm here is scored against **the same
rule on the same surrogates**, and the race runs on **closes** - exact on a
synthetic cross, where the bar extremes are bounds inflated about 1.7x.

**Duty cycle.** Any gate that trades less shows a per-book improvement on a
losing rule, so every gate is reported per unit traded and against a **random
twin switching off at the same rate**. Every pause rule tested on this desk beat
its baseline by hundreds and none beat its own random twin (p 0.45-0.51).

## The gate is causal, and its boundary is measured rather than conventional

`Mood`'s +-0.5 thresholds are conventional and unmeasured, and on a synthetic
grind-up the reading was +0.216 and on a synthetic crash -0.332, so they never
fire. No gate here keys on them. The gate is a **trailing** quantile of the
basket index over the prior `LOOKBACK` bars - causal, so no threshold has seen
the future - and the absolute reading each quantile lands on is reported, which
is the measured boundary the conventional one was standing in for.
"""

from __future__ import annotations

import numpy as np

import research.ideas.fear_greed as F
from till_infinity.node.metrics import (
    minimum_track_record,
    profit_factor,
    sharpe,
    win_rate,
)

#: Bars of trailing history the gate's quantile is taken over. 500 at 1d is
#: about two years, which is long enough for a quantile of a bounded index and
#: short enough that the 2008 regime is not still setting the 2020 threshold.
LOOKBACK = 500

#: The quantile a reading has to clear. Top fifth, fixed before the run, and
#: the only threshold in the study - `sweep-thresholds-on-the-mean-not-z`
#: records a z grid faking a ridge at the chosen threshold while the mean grid
#: was monotone, so the alternatives are reported as a monotone sweep in
#: `GATE_QUANTILES` rather than as a best cell.
GATE_Q = 0.80
GATE_QUANTILES: tuple[float, ...] = (0.60, 0.70, 0.80, 0.90)

#: `(target, stop)` in volatility units. 2:1 and 1:2 both carried so the
#: (stop - target) tilt `level-shield.md` measured is visible as a trend across
#: rows rather than hidden inside one.
RACES: tuple[tuple[float, float], ...] = ((2.0, 1.0), (1.0, 1.0), (1.0, 2.0))

#: Bars a position may stay open. `SETTINGS[interval]["horizon"]`, so a hold
#: is the same length as every other forward window in the study.
#: Overridden per interval by the caller.
HORIZON = 20


def races(
    series: F.Series,
    unit: np.ndarray,
    entries: np.ndarray,
    *,
    side: int,
    target: float,
    stop: float,
    horizon: int,
) -> dict[str, np.ndarray]:
    """One flat-to-flat race per entry, on closes, no pyramiding.

    `side` is -1 to sell the cross and +1 to buy it. The outcome is in R: the
    reward-to-risk on a target hit, -1.0 on a stop, and the mark-to-market at
    the horizon otherwise.

    **Closes only.** A first passage read off bar highs and lows is an
    excursion rather than a close path and is crossed sooner than a diffusion
    calculation implies, which is the -0.25 to +0.12R departure from 1/(1+N)
    `level-shield.md` measured. On a synthetic cross the extremes are bounds
    as well, so the close path is both the exact series and the better-behaved
    race.

    **One position at a time**, which is also the de-overlapping: two entries
    inside one horizon would share their outcome window, and
    `overlapping-outcome-windows-leak` records a short skip rule with a long
    forward window giving direction AUC 0.79 that collapsed to 0.51.
    """
    n = len(series.close)
    reward = target / stop
    out_r: list[float] = []
    out_at: list[int] = []
    out_bars: list[int] = []
    out_hit: list[int] = []
    i = 0
    while i < n - 1:
        if not entries[i]:
            i += 1
            continue
        scale = float(unit[i])
        if not np.isfinite(scale) or scale <= 0.0:
            i += 1
            continue
        entry = float(series.close[i])
        up = entry + side * target * scale
        down = entry - side * stop * scale
        stop_at = min(n, i + horizon + 1)
        got = None
        for k in range(i + 1, stop_at):
            price = float(series.close[k])
            # The stop is checked first: on a bar that would cross both, the
            # conservative reading is the loss. It biases against every arm
            # equally and against the wide-target rows hardest, which is the
            # opposite sign to the tilt being guarded against.
            if (price - down) * side <= 0.0:
                got = (-1.0, k - i, -1)
                break
            if (price - up) * side >= 0.0:
                got = (reward, k - i, 1)
                break
        if got is None:
            k = stop_at - 1
            mark = side * (float(series.close[k]) - entry) / (stop * scale)
            got = (float(mark), k - i, 0)
        out_r.append(got[0])
        out_at.append(i)
        out_bars.append(got[1])
        out_hit.append(got[2])
        i += got[1]
    return {
        "r": np.asarray(out_r, dtype=float),
        "at": np.asarray(out_at, dtype=np.int64),
        "bars": np.asarray(out_bars, dtype=np.int64),
        "hit": np.asarray(out_hit, dtype=np.int8),
    }


def gate(values: np.ndarray, quantile: float, *, lookback: int = LOOKBACK) -> np.ndarray:
    """Bars where `values` is at or above its own **trailing** quantile.

    Causal: the threshold at bar `t` is taken over `[t - lookback, t)` and
    never includes `t` itself or anything after it. A whole-sample quantile
    would be lookahead of exactly the kind `open-gap-filters-are-lookahead`
    records costing +0.50R a trade, and it is invisible in the output - the
    gate fires at a plausible rate either way.
    """
    n = len(values)
    out = np.zeros(n, dtype=bool)
    for t in range(lookback, n):
        here = values[t]
        if not np.isfinite(here):
            continue
        window = values[max(0, t - lookback) : t]
        window = window[np.isfinite(window)]
        if len(window) < lookback // 2:
            continue
        if here >= np.quantile(window, quantile):
            out[t] = True
    return out


def boundary(values: np.ndarray, quantile: float, *, lookback: int = LOOKBACK) -> float:
    """The median absolute reading the trailing `quantile` lands on.

    **The measured boundary**, reported because `Mood`'s conventional +-0.5 is
    not one: on a synthetic grind-up the reading was +0.216 and on a crash
    -0.332, so +-0.5 never fires and a gate keyed on it refuses everything.
    """
    marks: list[float] = []
    for t in range(lookback, len(values)):
        window = values[max(0, t - lookback) : t]
        window = window[np.isfinite(window)]
        if len(window) >= lookback // 2:
            marks.append(float(np.quantile(window, quantile)))
    return float(np.median(marks)) if marks else float("nan")


def day_block_ci(
    r: np.ndarray, day: np.ndarray, draws: int, rng, level: float = 0.95
) -> tuple[float, float, float]:
    """`(low, high, sd_of_mean)` for the mean R, resampling **whole days**.

    Days and not trades. Trades cluster in days and regime labels persist for
    hours, so an ordinary standard error is far too narrow - the skill names
    this as a control that has caught a wrong answer here.
    """
    if len(r) < 8:
        return float("nan"), float("nan"), float("nan")
    unique = np.unique(day)
    index = {b: np.flatnonzero(day == b) for b in unique}
    means: list[float] = []
    for _ in range(draws):
        picked = np.concatenate(
            [index[unique[rng.randrange(len(unique))]] for _ in range(len(unique))]
        )
        if len(picked):
            means.append(float(r[picked].mean()))
    if len(means) < 8:
        return float("nan"), float("nan"), float("nan")
    lo = float(np.quantile(means, (1.0 - level) / 2.0))
    hi = float(np.quantile(means, 1.0 - (1.0 - level) / 2.0))
    return lo, hi, float(np.std(means, ddof=1))


def score(
    got: dict[str, np.ndarray], ts: np.ndarray, draws: int, rng, horizon: int
) -> dict:
    """Every number the verdict rests on, for one arm's trade list.

    `trades_for_95` is `minimum_track_record`: how many trades this arm's own
    mean, sd, skew and kurtosis would need before a 95% probabilistic Sharpe
    was reachable. Reported beside the mean because a mean whose own arithmetic
    says it needs 4,000 trades has not failed at 300 - it is unmeasurable,
    which is a different and cheaper decision.
    """
    r, at, held = got["r"], got["at"], got["bars"]
    # Duty cycle is **bars held** over bars available, not trades over bars: a
    # rule taking few long positions and one taking many short ones can trade
    # at the same rate and occupy the book for very different shares of it,
    # and the random twin has to match the share that matters.
    out: dict = {"n": int(len(r)), "duty": float(held.sum()) / max(1, len(ts))}
    if len(r) < 8:
        return out
    day = F.days(ts[at])
    lo, hi, se = day_block_ci(r, day, draws, rng)
    values = r.tolist()
    out.update(
        {
            "mean_r": float(r.mean()),
            "sd_r": float(r.std(ddof=1)),
            "ci_low": lo,
            "ci_high": hi,
            "se_mean": se,
            "t": float(r.mean() / se) if se and np.isfinite(se) and se > 0 else float("nan"),
            "profit_factor": profit_factor(values),
            "win_rate": win_rate(values),
            "sharpe": sharpe(values),
            "total_r": float(r.sum()),
            "target_share": float((got["hit"] > 0).mean()),
            "stop_share": float((got["hit"] < 0).mean()),
            "timeout_share": float((got["hit"] == 0).mean()),
            "median_hold": float(np.median(held)),
            "horizon": horizon,
        }
    )
    try:
        out["trades_for_95"] = float(minimum_track_record(values, 0.95))
    except (ValueError, ZeroDivisionError):
        # `minimum_track_record` raises where the PSR variance estimate goes
        # non-positive, which happens at strong skew and a high Sharpe. Left
        # absent rather than filled with a sentinel: `absent-is-not-zero`.
        out["trades_for_95"] = float("nan")
    return out


def random_twin(
    series: F.Series,
    unit: np.ndarray,
    rate: float,
    *,
    side: int,
    target: float,
    stop: float,
    horizon: int,
    rng,
) -> dict[str, np.ndarray]:
    """The duty-cycle control: entries at `rate`, placed at random.

    The arm every pause rule on this desk has failed against. Without it "the
    gate improves the book" is indistinguishable from "the gate trades less".
    """
    n = len(series.close)
    entries = np.zeros(n, dtype=bool)
    for i in range(LOOKBACK, n):
        if rng.random() < rate:
            entries[i] = True
    return races(
        series, unit, entries, side=side, target=target, stop=stop, horizon=horizon
    )
