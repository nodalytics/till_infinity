"""How much of each instrument's variance is jumps — and so where `b / (a + b)` is wrong.

Run from the repository root:  python research/harness/jump_share.py

`overshoot_theory.py` derived the driftless first-passage probability for a process with jumps,

    p = (b + d) / (a + u + b + d)

and showed that scoring Boom and Crash against the continuous-path `b / (a + b) = 0.5` invented
a +4.1-point edge that does not exist: against the corrected benchmark the excess is +0.09
points on 16,231 trades.

**That error is not confined to Boom.** Every barrier study in this repository uses
`b / (a + b)`, so every instrument with a jump component has been mis-scored, and the size of
the error grows with how jumpy the instrument is. This measures that, per instrument, so the
affected studies can be ranked rather than guessed at.

## The decomposition, and where it comes from

Total variance splits into independent contributions that add in quadrature - the same structure
as the relativistic energy-momentum relation, where rest mass and momentum add as squares to
give the total. Here:

    total variance = continuous variance + jump variance

The estimator is standard and due to Barndorff-Nielsen and Shephard. **Realised variance**

    RV = sum r_i^2

captures everything. **Bipower variation**

    BV = (pi / 2) * sum |r_i| |r_{i-1}|

captures only the continuous part, and the reason is the trick worth understanding: a jump lands
in **one** return, so multiplying neighbouring absolute returns leaves it multiplied by an
ordinary-sized neighbour instead of by itself. Squaring a jump keeps it; pairing it with its
neighbour dilutes it. So

    jump share = max(0, 1 - BV / RV)

with the `pi / 2` being `1 / E[|Z|]^2` for a standard normal, which is what makes `BV` an
unbiased estimate of the continuous variance in the absence of jumps.

## The prediction, recorded before the run

If the benchmark error is really caused by jumps, then **the jump share should order the
instruments by how far their measured hit rate sits from 0.5** at fixed reward-to-risk one.

* Boom and Crash should be the jumpiest, since they are built that way;
* the `1s` synthetics should be next - they are the same generators at higher frequency;
* FX majors should be the least jumpy, and their barrier studies the least affected;
* and the correlation between jump share and `|p - 0.5|` across instruments should be strongly
  positive.

**If that correlation is absent, the jump explanation is wrong** and the Boom coincidence needs
another account. That is the falsifiable content here, and it is why both quantities are measured
on the same bars rather than one being taken on trust.

## What it is for

Two uses, both concrete.

**Ranking the damage.** `power-and-sizing.md` graded fifteen studies on whether they could detect
an effect. This grades them on whether their yardstick was right, which is a different and prior
question - a well-powered study against the wrong benchmark is worse than an underpowered one,
because it produces confident nonsense.

**Choosing instruments.** An instrument with a high jump share cannot be studied with the barrier
machinery in this repository without the corrected benchmark, and the correction needs both
overshoots measured, which doubles the work. A low jump share means `b / (a + b)` is close enough
and the existing results stand.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "training"))

import candles  # noqa: E402

#: Bars per estimation block. Both estimators are block sums, and blocking rather than using
#: the whole series lets the share be reported as a distribution instead of one number.
BLOCK = 500

#: Barriers for the hit-rate half, in true ranges. Equal, so the continuous benchmark is 0.5.
BARRIER = 1.0
HORIZON = 192
EVERY = 8


def shares(bars: np.ndarray) -> tuple[float, float]:
    """Median jump share by bipower variation, and the range-to-close variance ratio.

    **The second number exists because the first was the wrong estimator, and the failure is
    worth keeping.** Bipower variation reads close-to-close returns, and the first run of this
    harness gave Boom 1000 a jump share of 0.008 - essentially none - while its barrier hit
    rate sat 4.31% from the continuous benchmark, the largest gap of twelve instruments. Brent,
    the jumpiest by bipower at 0.148, sat 0.57% away. The predicted rank correlation was
    strongly positive and came out at +0.266.

    The reason is that **Boom's spikes live inside bars.** A spike prints in the high and
    reverts before the close, so the close-to-close return is ordinary and bipower sees
    nothing - while the barrier machinery tests `high >= target` and sees all of it.

    So the diagnostic that matters compares variance estimated from the **range** against
    variance estimated from **closes**. Parkinson's estimator uses `log(high/low)` and is
    unbiased for a diffusion, so for a continuous process the ratio is about 1; when price
    travels inside the bar and comes back, the range estimator is far larger. That ratio is
    what the barrier logic is exposed to, and it is reported beside the bipower figure rather
    than instead of it, so the wrong estimator stays visible next to the right one.
    """
    close = bars[:, 4]
    good = close > 0
    if good.sum() < BLOCK * 3:
        return float("nan"), float("nan")
    rets = np.diff(np.log(close[good]))
    out = []
    for start in range(0, len(rets) - BLOCK, BLOCK):
        block = rets[start : start + BLOCK]
        rv = float(np.sum(block**2))
        if rv <= 0:
            continue
        bv = (math.pi / 2.0) * float(np.sum(np.abs(block[1:]) * np.abs(block[:-1])))
        # Bipower is scaled for one fewer term than realised variance; correcting for that
        # matters at this block size and would otherwise read as a constant jump share.
        bv *= len(block) / max(len(block) - 1, 1)
        out.append(max(0.0, 1.0 - bv / rv))
    # Parkinson variance from the range against close-to-close variance, per block.
    high, low = bars[good, 2], bars[good, 3]
    ratios = []
    for start in range(0, len(rets) - BLOCK, BLOCK):
        block = rets[start : start + BLOCK]
        hi = high[start + 1 : start + BLOCK + 1]
        lo = low[start + 1 : start + BLOCK + 1]
        ok = (hi > 0) & (lo > 0) & (hi >= lo)
        if ok.sum() < BLOCK // 2:
            continue
        close_var = float(np.mean(block**2))
        park = float(np.mean(np.log(hi[ok] / lo[ok]) ** 2) / (4.0 * math.log(2.0)))
        if close_var > 0:
            ratios.append(park / close_var)
    if not out or not ratios:
        return float("nan"), float("nan")
    return float(np.median(out)), float(np.median(ratios))


def hit_rate(bars: np.ndarray, tr: np.ndarray, side: int) -> tuple[float, int, float, float]:
    """Hit rate, count, and the two overshoots, at reward-to-risk one.

    **The overshoots are measured, not proxied, and that is the finding.** Two proxies for
    "how jumpy is this instrument" were tried first and both failed to predict the benchmark
    gap: bipower variation gave Boom 0.008 against Brent's 0.148 while Boom had the largest
    gap of twelve instruments, and the range-to-close variance ratio came back with the
    *opposite* sign to the prediction at -0.441.

    The direct measurement matched to 0.09 points on the first try. A proxy for a quantity
    that appears in a formula is worth having only when the quantity is hard to measure, and
    here it is not: `u` and `d` fall out of the same loop that computes the hit rate.
    """
    close, high, low = bars[:, 4], bars[:, 2], bars[:, 3]
    wins = total = 0
    ups: list[float] = []
    downs: list[float] = []
    for at in range(0, len(bars) - HORIZON, EVERY):
        here = close[at]
        unit = tr[at] * here
        if unit <= 0:
            continue
        target, stop = here + side * BARRIER * unit, here - side * BARRIER * unit
        for step in range(1, HORIZON + 1):
            i = at + step
            if i >= len(bars):
                break
            if side > 0:
                hit_t, hit_s = high[i] >= target, low[i] <= stop
            else:
                hit_t, hit_s = low[i] <= target, high[i] >= stop
            if hit_t or hit_s:
                total += 1
                won = bool(hit_t and not hit_s)
                wins += won
                # Overshoot past whichever barrier was taken, in the same true-range unit.
                if won:
                    ups.append((high[i] - target) / unit if side > 0 else (target - low[i]) / unit)
                else:
                    downs.append((stop - low[i]) / unit if side > 0 else (high[i] - stop) / unit)
                break
    u = float(np.mean(ups)) if ups else 0.0
    d = float(np.mean(downs)) if downs else 0.0
    return (wins / total if total else float("nan")), total, u, d


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "symbols",
        nargs="*",
        default=[s.strip() for s in os.environ.get("SYMBOLS", "").split(",") if s.strip()]
        or ["xauusd", "eurusd", "gbpusd", "usdjpy", "boom_1000_index", "crash_1000_index"],
    )
    ap.add_argument("--where", default=os.environ.get("WHERE", ".secrets/broker-deep"))
    ap.add_argument("--interval", default="1h")
    args = ap.parse_args()

    print(
        "jump share of variance by bipower variation, against how far the measured hit rate\n"
        "sits from the continuous-path benchmark of 0.5000 at reward-to-risk one\n"
        f"\n  {'instrument':<26}{'rng/cls':>7}{'u':>7}{'d':>7}"
        f"{'p long':>8}{'fair':>8}{'p short':>8}{'fair':>8}"
        f"{'vs 0.5':>8}{'vs fair':>9}{'n':>8}"
    )
    rows = []
    for symbol in args.symbols:
        found = sorted(Path(args.where).expanduser().glob(f"{symbol}_{args.interval}_*.csv.gz"))
        if not found:
            print(f"  {symbol:<26} no {args.interval} file")
            continue
        bars, _repaired = candles.read(found[0])
        if len(bars) < BLOCK * 4 + HORIZON:
            continue
        tr = candles.true_range(bars)
        share, prevalence = shares(bars)
        p_long, n, u_l, d_l = hit_rate(bars, tr, 1)
        p_short, _n, u_s, d_s = hit_rate(bars, tr, -1)
        if not (np.isfinite(share) and np.isfinite(p_long)):
            continue
        gap = max(abs(p_long - 0.5), abs(p_short - 0.5))
        # The corrected benchmark, per side, from the measured overshoots.
        fair_l = (1.0 + d_l) / (1.0 + u_l + 1.0 + d_l)
        fair_s = (1.0 + d_s) / (1.0 + u_s + 1.0 + d_s)
        excess = max(abs(p_long - fair_l), abs(p_short - fair_s))
        rows.append((prevalence, gap, symbol))
        print(
            f"  {symbol:<26}{prevalence:>7.2f}{u_l:>7.3f}{d_l:>7.3f}"
            f"{p_long:>8.4f}{fair_l:>8.4f}{p_short:>8.4f}{fair_s:>8.4f}"
            f"{gap:>8.2%}{excess:>9.2%}{n:>8,}"
        )

    if len(rows) >= 4:
        share = np.array([r[0] for r in rows])
        gap = np.array([r[1] for r in rows])
        # Spearman by hand: rank correlation, so one violent instrument cannot carry it.
        rs = np.argsort(np.argsort(share)).astype(float)
        rg = np.argsort(np.argsort(gap)).astype(float)
        rho = float(np.corrcoef(rs, rg)[0, 1])
        print(
            f"\n  rank correlation between range/close ratio and |p - 0.5| across "
            f"{len(rows)} instruments: {rho:+.3f}"
        )
        print(
            "  The prediction was strongly positive. A positive value says the benchmark error\n"
            "  is caused by jumps and the jump share ranks which studies were mis-scored;\n"
            "  near zero says the jump account of the Boom coincidence is wrong and something\n"
            "  else produced it."
        )
        worst = sorted(rows, reverse=True)[:3]
        print("\n  jumpiest, where `b / (a + b)` should not be used without the correction:")
        for s, g, name in worst:
            print(f"    {name:<26} jump share {s:.3f}, sits {g:.2%} from 0.5")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
