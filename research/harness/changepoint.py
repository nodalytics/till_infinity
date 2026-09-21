"""Two online detectors - FoCuS and a spiking neuron - and whether they sharpen a gap.

Run from the repository root:  python research/harness/changepoint.py

Two questions arrived together and they are the same question:

* can a changepoint detector find the moment a series changes character, and does an
  imbalance that sits **at** such a moment behave differently from one that does not;
* can a biologically-inspired spiking neuron detect spikes, up and down, in a series.

`imbalance.md` measured gaps as standing levels and nothing cleared 51.5%. The
hypothesis worth testing next is not that gaps work, but that **the gaps that matter are
the ones marking a genuine change** - fresh imbalance, in the operator's phrasing - and
that the rest are noise diluting the sample. That is a conditioning claim, so it needs a
detector that is not itself fitted to the outcome.

## Why this one is unusually testable

Almost nothing in this repository has ground truth. This does.

**Boom indices are constructed with sudden upward spikes against a slow grind down, and
Crash indices are the mirror.** So a spike detector has a known right answer before any
trading question is asked: the up-channel must fire far more often on Boom than on Crash,
and the down-channel the reverse, and both must be roughly symmetric on FX. If the
detector cannot recover a property the broker *built into the instrument*, it cannot be
trusted on anything subtler, and the trading results below should be discarded rather
than argued about. That check runs first for exactly that reason.

## FoCuS, and what is and is not implemented here

FoCuS - functional pruning CUSUM - keeps the exact maximum-likelihood CUSUM statistic
over every possible changepoint, at amortised logarithmic cost, by noticing that most
candidate changepoints can never become the maximiser and pruning them.

For a Gaussian change in mean with **known** pre-change mean, the log-likelihood ratio
for a change at `t` with post-change mean `θ`, observed to `n`, is

    Q(t, θ) = θ (S_n - S_t) - (θ² / 2) (n - t)

with `S` the partial sums. Maximising over `θ` gives `(S_n - S_t)² / (2 (n - t))`, and the
maximiser over `t` is always a **vertex of the lower convex hull of the partial-sum
path** - so the pruning is a convex hull maintained by monotone chain, which is what is
implemented here and is exact.

What is *not* implemented is the unknown-pre-change-mean case, whose pruning is
two-dimensional. Instead the mean is estimated from the first `WARMUP` bars of each
segment and the detector is restarted after every detection, which is how it is used
online anyway. **That makes this FoCuS0 with restarts, not full FoCuS**, and the
difference is worth stating rather than glossing.

Increments are divided by the EWMA true range before they reach either detector, so both
see a dimensionless series and a threshold means the same thing on gold and on Boom.

## The spiking neuron, and why a leak is the point

A leaky integrate-and-fire neuron holds a membrane potential that decays towards rest,
adds its input, and fires when it crosses a threshold - after which it resets and is
briefly refractory. Two of them are used, one taking the positive part of the input and
one the negative, which is how retinal ganglion cells are actually arranged: separate ON
and OFF channels rather than one signed one.

The leak is not decoration. **It makes the neuron a matched filter for a fast transient
and blind to slow drift**, because a slow accumulation leaks away before reaching
threshold while a sudden one does not. That is precisely the Boom/Crash construction -
fast one way, slow the other - so this is the right instrument for the stated question
rather than a fashionable one.

Spike-frequency adaptation is included: the threshold rises after each spike and decays
back. Without it a single volatile stretch produces a burst of spikes that are all one
event, which would inflate every count and every hit rate that conditions on them.

## What is measured, and the trap being avoided

Every trade uses a stop and a target the same distance from entry - one true range -
reusing `imbalance.resolve`. **Fair odds is therefore 50% for every row**, so nothing
here can be explained by geometry, which is what decided `premium_discount.py` (the
50%-of-range rule tracked `a / (a + b)` across ten deciles and 314,794 rows) and
`patterns.md` (a double bottom hitting 58% whose matched placebo hit 57.6%).

The ablation is the experiment. Detections alone, gaps alone, and gaps conditioned on
detections are all scored, because **if conditioning on a detection does not beat the gap
on its own, the detector is decoration** - and a conditioned cell is rarer, so it has a
wider error bar and more room to look good by chance. The count of scored cells is
printed with the number expected to clear two standard errors by chance.

Both barriers inside one bar counts as a stop, as everywhere here.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "training"))

import candles  # noqa: E402
import imbalance  # noqa: E402

#: Bars used to estimate the pre-change mean at the start of each segment.
WARMUP = 50

#: FoCuS thresholds on the statistic. A couple, so the reading is not one knob deep.
THRESHOLDS = (8.0, 12.0)

#: Membrane time constant, in bars. The leak is `exp(-1 / TAU)` per bar.
TAU = 6.0

#: Resting threshold, in units of the standardised increment, and the amount it rises
#: after a spike. Adaptation decays back with time constant `TAU_ADAPT`.
#:
#: **Calibrated, not chosen.** Run against 200,000 draws of pure Gaussian noise the
#: false-alarm rate per 1000 bars is 6.1 at a threshold of 3, 1.3 at 4, 0.20 at 5 and
#: 0.01 at 6. Five is the operating point: about one false spike per 5000 bars, which is
#: rare enough that a difference in firing rate between two instruments is about the
#: instruments. Real returns are fatter-tailed than Gaussian so the true rate will be
#: higher than 0.20 - that inflates both channels equally and leaves the ON-minus-OFF
#: asymmetry, which is what the ground-truth check actually reads, untouched.
THETA = 5.0
ADAPT = 2.0
TAU_ADAPT = 20.0

#: Time constant of the tonic inhibition each cell subtracts from its own drive. Slow,
#: because it is meant to track the prevailing level of activity rather than the event.
TAU_BASE = 200.0

#: Homeostatic set point: spikes per bar, per cell, that the shared threshold regulates
#: towards. 0.002 is two events per 1000 bars. This replaces the calibrated threshold
#: with a stated research budget - how many events the study is willing to look at -
#: which is the honest form of the same decision and survives a change of regime.
TARGET_RATE = 0.002

#: Learning rate of the homeostatic update. Multiplicative, so a spike raises the
#: threshold by 10% and each quiet bar lowers it by `ETA * TARGET_RATE`; the threshold
#: therefore adapts over roughly `1 / TARGET_RATE` bars, which is the fastest a rate can
#: honestly be estimated from events arriving at that rate.
ETA = 0.1

#: Bars of refractoriness after a spike.
REFRACTORY = 3

#: A detection counts as coinciding with a gap if it falls within this many bars.
NEAR = 3


def increments(bars: np.ndarray, tr: np.ndarray) -> np.ndarray:
    """Close-to-close moves divided by the EWMA true range, so they are dimensionless.

    Dividing by `tr` at the *earlier* bar, not the later one, because the later bar's
    true range already contains the move being standardised - using it would shrink
    exactly the large moves both detectors exist to find.
    """
    close = bars[:, 4]
    out = np.zeros(len(close))
    unit = tr[:-1] * np.maximum(close[:-1], 1e-12)
    safe = unit > 0
    out[1:][safe] = (close[1:] - close[:-1])[safe] / unit[safe]
    return np.clip(out, -25.0, 25.0)


def focus(series: np.ndarray, threshold: float, sign: int = 1) -> np.ndarray:
    """Detection times for an upward (`sign` +1) or downward change in mean.

    Exact FoCuS0 pruning: the maximiser of `(S_n - S_t)² / (2 (n - t))` is a vertex of
    the lower convex hull of `(t, S_t)`, so the candidate set is that hull, maintained
    by monotone chain in amortised constant time. The hull stays small - a few dozen
    points over a hundred thousand bars - so scanning it for the maximum is cheaper
    than the pointer walk the paper uses, and easier to read.

    The detector restarts after each detection, which is both how an online detector is
    used and the reason the pre-change mean can be estimated per segment at all.
    """
    x = series * sign
    hits: list[int] = []
    hull: list[tuple[int, float]] = [(0, 0.0)]
    total = 0.0
    mean = 0.0
    start = 0

    for n in range(1, len(x)):
        since = n - start
        if since <= WARMUP:
            # Still learning what "no change" looks like in this segment.
            mean = float(np.mean(x[start : n + 1]))
            total = 0.0
            hull = [(n, 0.0)]
            continue
        total += x[n] - mean
        # Monotone chain, lower hull: drop the top while it is not a vertex.
        while len(hull) >= 2:
            (t1, s1), (t2, s2) = hull[-2], hull[-1]
            if (s2 - s1) * (n - t2) >= (total - s2) * (t2 - t1):
                hull.pop()
            else:
                break
        hull.append((n, total))

        best = 0.0
        for t, s in hull:
            if t >= n or total <= s:
                continue
            best = max(best, (total - s) ** 2 / (2.0 * (n - t)))
        if best >= threshold:
            hits.append(n)
            start, total, mean = n, 0.0, 0.0
            hull = [(n, 0.0)]
    return np.array(hits, dtype=int)


def spikes(series: np.ndarray, target: float | None = TARGET_RATE) -> tuple[np.ndarray, np.ndarray]:
    """Firing times of an ON and an OFF leaky integrate-and-fire neuron.

    Both neurons share the input; the ON cell integrates its positive part and the OFF
    cell its negative part, which is the arrangement in a retina rather than one signed
    cell. The leak makes each one blind to slow drift and sensitive to a transient, and
    spike-frequency adaptation stops one volatile stretch registering as ten events.

    **Tonic inhibition is what makes this work rather than chatter.** The first version
    fired roughly every thirty bars on pure Gaussian noise, and the arithmetic says why:
    rectified unit-variance noise has mean `1/sqrt(2 pi) = 0.399`, and a leak of
    `exp(-1/6) = 0.846` accumulates that to `0.399 / (1 - 0.846) = 2.6` - within a
    whisker of a threshold of 3. The membrane was sitting just under firing all the time
    and the detector was measuring nothing.

    Real ON cells solve this with a maintained inhibitory baseline that the signal has to
    beat, and they adapt it to the prevailing contrast. So each cell subtracts a slow
    EWMA of its own drive and the potential floors at rest, which makes the neuron
    respond to drive **above its recent habit** rather than to drive. That is contrast
    adaptation, it is why a retina works across six orders of magnitude of light.

    ## The threshold adapts rather than being calibrated

    With `target` set, the threshold is **not a constant at all**. It is regulated by
    homeostatic plasticity: a neuron that fires more often than its set point raises its
    own threshold, one that fires too rarely lowers it, and the update is multiplicative
    so it stays positive and adapts proportionally:

        floor <- floor * exp(ETA * (fired - target))

    This is what real cortex does - intrinsic plasticity maintaining a firing rate across
    changing input statistics - and it is the right answer for a series whose character
    keeps changing. It also replaces an arbitrary voltage with an interpretable research
    choice: **how many events per 1000 bars is this study willing to look at**, which is a
    question about the experiment rather than about the neuron. The calibrated `THETA` is
    kept only as the initial condition, so the detector starts sane and then tunes itself.

    ## The trap, which cost this design a rewrite

    The obvious implementation gives **each cell its own homeostatic threshold**, and it is
    wrong here. If the ON cell and the OFF cell each regulate to the same set point, then
    by construction they fire equally often on every instrument - and the ground-truth
    check above, which reads the ON-minus-OFF asymmetry to confirm the detector can see
    that Boom spikes up and Crash spikes down, would return zero on everything. The
    homeostasis would have erased precisely the signal it was there to measure.

    So the regulated threshold is **shared** between the two cells. The pair holds its
    combined rate at the set point while the split between up and down stays free, which
    is the asymmetry being measured. Spike-frequency adaptation stays per-cell, as a fast
    offset above the shared floor, because that one is about not double-counting a single
    event and has nothing to do with the rate.

    Passing `target=None` restores the fixed calibrated threshold, which is how the two
    are compared rather than assumed.
    """
    leak = float(np.exp(-1.0 / TAU))
    relax = float(np.exp(-1.0 / TAU_ADAPT))
    slow = float(np.exp(-1.0 / TAU_BASE))
    out: list[list[int]] = [[], []]
    v = [0.0, 0.0]
    offset = [0.0, 0.0]
    base = [0.0, 0.0]
    rest = [0, 0]
    floor = THETA

    for i, raw in enumerate(series):
        fired = 0
        for cell, drive in ((0, max(raw, 0.0)), (1, max(-raw, 0.0))):
            # Fast, per-cell adaptation above the shared floor - this one stops a single
            # event registering as ten, and must not be confused with the rate control.
            offset[cell] *= relax
            base[cell] = base[cell] * slow + drive * (1.0 - slow)
            if rest[cell] > 0:
                rest[cell] -= 1
                v[cell] = 0.0
                continue
            # Drive above the cell's own recent habit, and the potential cannot go
            # below rest - a membrane has a reversal potential, and without the floor
            # a quiet stretch banks credit against the next spike.
            v[cell] = max(0.0, v[cell] * leak + drive - base[cell])
            if v[cell] >= floor + offset[cell]:
                out[cell].append(i)
                v[cell] = 0.0
                offset[cell] += ADAPT
                rest[cell] = REFRACTORY
                fired += 1
        if target is not None:
            # Shared, so the pair holds its rate while the up/down split stays free.
            floor = float(
                np.clip(floor * np.exp(ETA * (fired - 2.0 * target)), THETA / 4.0, THETA * 4.0)
            )
    return np.array(out[0], dtype=int), np.array(out[1], dtype=int)


def near(times: np.ndarray, at: int, window: int = NEAR) -> bool:
    """Did anything in `times` land within `window` bars of `at`?"""
    if not len(times):
        return False
    i = int(np.searchsorted(times, at))
    return any(0 <= j < len(times) and abs(int(times[j]) - at) <= window for j in (i - 1, i))


def ground_truth(symbol: str, series: np.ndarray) -> None:
    """The check that has a known answer: does the detector see the construction?

    Both threshold schemes are shown, because "the adaptive one is better" is a claim and
    not a licence. If the self-regulating threshold recovers the Boom/Crash asymmetry that
    the fixed one recovers, it has earned the place; if it flattens it, the shared-floor
    reasoning in `spikes` is wrong and the fixed one stands.
    """
    n = max(len(series), 1)
    per = 1000.0
    hi = focus(series, THRESHOLDS[0], sign=1)
    lo = focus(series, THRESHOLDS[0], sign=-1)
    line = f"  {symbol:<22}"
    for target in (TARGET_RATE, None):
        up, down = spikes(series, target=target)
        line += (
            f"{len(up) * per / n:>8.1f}{len(down) * per / n:>8.1f}"
            f"{(len(up) - len(down)) * per / n:>+9.1f}"
        )
    print(line + f"{len(hi) * per / n:>9.1f}{len(lo) * per / n:>8.1f}")


def study(symbol: str, bars: np.ndarray, tr: np.ndarray, tally: dict) -> int:
    """Score every cell: detectors alone, gaps alone, and gaps conditioned."""
    series = increments(bars, tr)
    up, down = spikes(series)
    detect = {f"focus {t:g}": (focus(series, t, 1), focus(series, t, -1)) for t in THRESHOLDS}
    counted = 0

    # The detectors on their own, traded in and against their own direction. On Boom
    # this should recover the drift asymmetry `jump_odds.py` found; anywhere else a
    # departure from 50% is the claim being tested.
    for name, (rise, fall) in [*detect.items(), ("spike", (up, down))]:
        for times, side in ((rise, 1), (fall, -1)):
            for raw in times:
                at = int(raw)
                if at + imbalance.HORIZON >= len(bars):
                    continue
                got = imbalance.resolve(bars, tr, at, side)
                if got == 0:
                    continue
                # Both directions of the same event, because a detector that loses
                # by the same margin it could have won by is the interesting case.
                tally[(f"{name} alone, with it", symbol)].append(got > 0)
                tally[(f"{name} alone, against it", symbol)].append(got < 0)
                counted += 1

    # Gaps, and gaps conditioned on a detection at the moment they formed.
    for gap in imbalance.gaps(bars, tr):
        j, side, _edge, _disp, _wick = gap
        matched = up if side > 0 else down
        marks = {
            "spike": near(matched, j),
            **{name: near(rise if side > 0 else fall, j) for name, (rise, fall) in detect.items()},
        }
        for at in imbalance.touches(bars, gap, tr):
            got = imbalance.resolve(bars, tr, at, side)
            if got == 0:
                continue
            tally[("gap alone", symbol)].append(got > 0)
            for name, hit in marks.items():
                key = f"gap + {name}" if hit else f"gap, no {name}"
                tally[(key, symbol)].append(got > 0)
            counted += 1
    return counted


def report(tally: dict) -> None:
    pooled: dict[str, list[bool]] = defaultdict(list)
    spread: dict[str, list[float]] = defaultdict(list)
    for (name, _symbol), got in tally.items():
        pooled[name].extend(got)
        if len(got) >= 200:
            spread[name].append(float(np.mean(got)) - 0.5)

    print(
        "\nstop and target both one true range, so fair odds is 50.0% for every row\n"
        f"\n  {'cell':<30}{'n':>9}{'hit':>8}{'excess':>9}{'+/-':>7}{'instruments':>13}"
    )
    rows = []
    for name, got in pooled.items():
        if len(got) < 300:
            continue
        won = np.array(got, dtype=float)
        hit = float(won.mean())
        band = 2.0 * float(np.sqrt(hit * (1 - hit) / len(won)))
        ups = sum(1 for g in spread.get(name, []) if g > 0)
        rows.append((hit - 0.5, name, len(won), hit, band, ups, len(spread.get(name, []))))

    for excess, name, n, hit, band, ups, total in sorted(rows, reverse=True):
        mark = "  <-" if abs(excess) > band else ""
        share = f"{ups}/{total}" if total else "-"
        print(f"  {name:<30}{n:>9,}{hit:>8.1%}{excess:>+9.2%}{band:>7.2%}{share:>13}{mark}")

    print(
        f"\n  {len(rows)} cells scored, so about {0.05 * len(rows):.0f} clear a two-sigma bar\n"
        "  by chance. The comparison that matters is `gap + X` against `gap, no X`\n"
        "  on the same instrument: if conditioning on a detection does not beat the\n"
        "  unconditioned gap, the detector added nothing and the gap result stands as\n"
        "  `imbalance.md` left it."
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "symbols",
        nargs="*",
        default=[
            "boom_1000_index",
            "crash_1000_index",
            "boom_500_index",
            "crash_500_index",
            "xauusd",
            "eurusd",
            "gbpusd",
            "usdjpy",
            "volatility_75_index",
        ],
    )
    ap.add_argument("--where", default=os.environ.get("WHERE", ".secrets/broker-deep"))
    ap.add_argument("--interval", default="1h")
    args = ap.parse_args()

    loaded: list[tuple[str, np.ndarray, np.ndarray]] = []
    for symbol in args.symbols:
        found = sorted(Path(args.where).expanduser().glob(f"{symbol}_{args.interval}_*.csv.gz"))
        if not found:
            print(f"{symbol:<24} no {args.interval} file")
            continue
        bars, _repaired = candles.read(found[0])
        if len(bars) < 2000:
            continue
        loaded.append((symbol, bars, candles.true_range(bars)))

    print(
        "ground truth first: Boom is built to spike UP and grind down, Crash the\n"
        "mirror. A detector that cannot recover that cannot be trusted below.\n"
        "\n  spikes and detections per 1000 bars\n"
        "                        --- adaptive threshold ---   --- fixed ---    -- focus --\n"
        f"  {'instrument':<22}{'ON':>8}{'OFF':>8}{'ON-OFF':>9}"
        f"{'ON':>8}{'OFF':>8}{'ON-OFF':>9}{'up':>9}{'down':>8}"
    )
    for symbol, bars, tr in loaded:
        ground_truth(symbol, increments(bars, tr))

    tally: dict[tuple[str, str], list] = defaultdict(list)
    print()
    for symbol, bars, tr in loaded:
        n = study(symbol, bars, tr, tally)
        print(f"  {symbol:<24} {n:>8,} resolved trades")
    report(tally)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
