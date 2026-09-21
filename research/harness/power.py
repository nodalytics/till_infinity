"""Could these experiments ever have found what they were looking for?

Run from the repository root:  python research/harness/power.py

Nothing in this repository has ever reported a minimum detectable effect, and that is a gap
with teeth. **An experiment whose smallest detectable effect is larger than its own cost
hurdle cannot succeed whatever it returns** - a negative result from it means nothing, and a
positive one is almost certainly the largest of many comparisons. Several months of "measured
null" may be underpowered rather than negative, and the two are not the same finding.

This is a retro-audit. It takes each study's own reported sample size and cell count and asks
what it was capable of seeing.

## The hurdle a result has to clear

Every barrier study here uses a stop and target the same distance apart, so fair odds is 50%
and the question is how far above it a rule must sit to pay for itself. With cost `c` in units
of the stop, break-even is

    p (1) - (1 - p)(1 + c) = 0    ->    p = (1 + c) / (2 + c)

At the measured live costs - **0.063 of slippage** from 305 journal stop-outs and 0.020 of
spread - that is `p = 1.083 / 2.083 = 52.0%`, so a rule needs about **+2.0 points** over fair
odds. Boom and Crash carry a spread of 0.004 rather than 0.020, giving
`1.067 / 2.067 = 51.6%` and a slightly lower hurdle of **+1.6 points**.

## The effect a study could see

For a two-sided binomial test against `p0 = 0.5` at significance `alpha` and power `1 - beta`,

    MDE = (z_{alpha/2} + z_beta) * sqrt(0.25 / n)

At 80% power and `alpha = 0.05` that is `2.80 * 0.5 / sqrt(n) = 1.401 / sqrt(n)`. To detect
+2.0 points a study needs `n = (1.401 / 0.020)^2 = 4,907` resolved trades **in the cell**, not
in the study.

## Why multiple comparisons dominate the arithmetic

This is the part that changes the verdicts. A study scoring `k` cells and marking whichever
clear a bar is running `k` tests, so the honest `alpha` is `0.05 / k`. That inflates
`z_{alpha/2}` and therefore the MDE:

| cells | corrected alpha | z | MDE multiplier | n needed for +2.0 points |
|---|---|---|---|---|
| 1 | 0.05 | 1.96 | 1.00x | 4,907 |
| 100 | 0.0005 | 3.48 | 1.54x | 11,700 |
| 1536 | 0.000033 | 4.00 | 1.73x | 14,700 |

So a study with fifteen hundred cells needs **three times** the sample per cell that a
single-hypothesis study does. `stretch.py` scored 1536 cells with 400-1500 trades in each; it
was about **thirty times** short of being able to see a tradable effect, and its null is
therefore close to uninformative about effects that size.

Bonferroni is conservative for correlated tests, and the cells here are correlated - adjacent
deciles of the same measure share bars. The honest reading is that the true requirement sits
between the uncorrected and corrected columns, nearer the corrected one when the cells span
different measures and timeframes.

## What this does not excuse

A large-sample study that lands on the fair-odds line to within a fraction of a point is
**not** underpowered, and this audit must not be used to reopen one. `premium_discount.py`
tracked `a / (a + b)` across 314,794 rows and ten deciles; `imbalance.py` and `patterns.py`
ran into the hundreds of thousands. Those had the power and found nothing, which is a real
negative result.

The studies this audit indicts are the ones with a few hundred trades per cell and a lot of
cells - and it indicts them symmetrically, so the one marginally positive cell in each is
demoted at the same time.
"""

from __future__ import annotations

import argparse
import math

#: Measured costs, in units of the stop. Slippage is the live figure from 305 journal
#: stop-outs; spread is per instrument class from `spread_cost.py`.
SLIPPAGE = 0.063
SPREAD_FX = 0.020
SPREAD_SYNTH = 0.004

#: Conventional power. 80% is the usual floor for "would have seen it".
POWER = 0.80
ALPHA = 0.05


def normal_quantile(p: float) -> float:
    """Inverse normal CDF, Acklam's rational approximation.

    Written out rather than imported because this harness has no other reason to require
    scipy, and a power calculation that cannot run on a bare interpreter will not get run.
    """
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0, 1)")
    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    ]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00, 3.754408661907416e00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    if p > phigh:
        return -normal_quantile(1 - p)
    q = p - 0.5
    r = q * q
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
        * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    )


def hurdle(cost: float) -> float:
    """Points above fair odds a rule needs to pay for itself, at reward-to-risk one."""
    return (1.0 + cost) / (2.0 + cost) - 0.5


def mde(n: int, cells: int = 1, power: float = POWER, alpha: float = ALPHA) -> float:
    """Smallest hit-rate excess a cell of `n` trades could detect, Bonferroni-corrected."""
    if n <= 0:
        return float("inf")
    z_a = normal_quantile(1.0 - alpha / (2.0 * max(cells, 1)))
    z_b = normal_quantile(power)
    return (z_a + z_b) * math.sqrt(0.25 / n)


def needed(effect: float, cells: int = 1, power: float = POWER, alpha: float = ALPHA) -> int:
    """Trades per cell required to detect `effect`, at the same correction."""
    if effect <= 0:
        return 2**62
    z_a = normal_quantile(1.0 - alpha / (2.0 * max(cells, 1)))
    z_b = normal_quantile(power)
    return math.ceil(0.25 * ((z_a + z_b) / effect) ** 2)


#: Each study as (name, trades in the cell being judged, cells scored, cost).
#:
#: `n` is deliberately the **cell** size and not the study total. A study with 390,000
#: trades split across 7 cells has the power of its cells, and one with 400 in each of 1536
#: has almost none however large the header number looks. Getting this wrong is how a study
#: with a big total is mistaken for a powerful one.
STUDIES = (
    ("premium_discount", 31_479, 10, SPREAD_FX),
    ("imbalance, gap edges", 52_000, 24, SPREAD_FX),
    ("patterns, double bottom", 8_000, 16, SPREAD_FX),
    ("changepoint, gap alone", 390_603, 7, SPREAD_SYNTH),
    ("changepoint, gap + spike", 15_038, 7, SPREAD_SYNTH),
    ("changepoint, spike alone", 1_266, 7, SPREAD_SYNTH),
    ("jump_odds, Boom R:R 1", 16_000, 72, SPREAD_SYNTH),
    ("displacement, ALL THREE", 1_200, 8, SPREAD_FX),
    ("regression_channel, best", 2_673, 144, SPREAD_FX),
    ("smc, sweep", 1_500, 18, SPREAD_FX),
    ("stretch, best cell", 437, 1536, SPREAD_FX),
    ("stretch, typical cell", 800, 1536, SPREAD_FX),
    ("stopfree, fade ON spike", 247, 300, SPREAD_SYNTH),
    ("maker_exits, fade 5m", 404, 300, SPREAD_SYNTH),
    ("breakout_runs, duration", 13_291, 32, SPREAD_FX),
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--power", type=float, default=POWER)
    args = ap.parse_args()

    print(
        f"minimum detectable hit-rate excess at {args.power:.0%} power, against the cost\n"
        f"hurdle each study has to clear. slippage {SLIPPAGE:.3f} from live fills.\n"
        f"\n  {'study':<28}{'n/cell':>9}{'cells':>7}{'hurdle':>8}"
        f"{'MDE':>8}{'MDE*':>8}{'n needed*':>11}  verdict"
    )

    for name, n, cells, spread in STUDIES:
        cost = SLIPPAGE + spread
        need = hurdle(cost)
        plain = mde(n, 1, args.power)
        corrected = mde(n, cells, args.power)
        want = needed(need, cells, args.power)
        if corrected <= need:
            verdict = "could have seen it"
        elif plain <= need:
            verdict = "only without the cell count"
        else:
            short = want / max(n, 1)
            verdict = f"blind - needs {short:.0f}x the sample"
        print(
            f"  {name:<28}{n:>9,}{cells:>7}{need:>8.2%}"
            f"{plain:>8.2%}{corrected:>8.2%}{want:>11,}  {verdict}"
        )

    print(
        "\n  MDE is uncorrected, MDE* and n needed* are Bonferroni-corrected for the cell\n"
        "  count. Bonferroni is conservative when cells are correlated - adjacent deciles\n"
        "  of one measure share bars - so the truth sits between the two columns, nearer\n"
        "  the corrected one the more the cells differ in measure and timeframe."
    )

    print(
        f"\n  {'cost hurdle at reward-to-risk 1':<40}"
        f"{'FX/metals':>12}{'synthetics':>12}\n"
        f"  {'break-even hit rate':<40}{0.5 + hurdle(SLIPPAGE + SPREAD_FX):>11.1%}"
        f"{0.5 + hurdle(SLIPPAGE + SPREAD_SYNTH):>12.1%}\n"
        f"  {'points needed over fair odds':<40}"
        f"{hurdle(SLIPPAGE + SPREAD_FX):>11.2%}{hurdle(SLIPPAGE + SPREAD_SYNTH):>12.2%}\n"
        f"  {'trades needed, single hypothesis':<40}"
        f"{needed(hurdle(SLIPPAGE + SPREAD_FX)):>11,}"
        f"{needed(hurdle(SLIPPAGE + SPREAD_SYNTH)):>12,}"
    )

    print(
        "\n  How to read a 'blind' row: that study could not have detected a tradable\n"
        "  effect even if one were there, so its null says nothing about effects that\n"
        "  size - **and its one marginally positive cell is demoted by the same\n"
        "  arithmetic**. The audit cuts both ways, which is the only way it is honest.\n"
        "\n  The large-sample rows are different in kind. A study that lands on the\n"
        "  fair-odds line to within a fraction of a point across hundreds of thousands\n"
        "  of trades had the power and found nothing. That is a real negative and this\n"
        "  audit does not reopen it."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
