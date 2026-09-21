"""Do the textbook chart patterns pay, once their own target rule is priced?

Run from the repository root:  python research/harness/patterns.py

The definitions come from Fidelity's *Identifying Chart Patterns* deck, which cites
*Technical Analysis: the Complete Resource for Financial Market Technicians*. They
are quoted rather than paraphrased, because the point of this file is to test what
the books actually say and not a convenient version of it.

## Each pattern is fully specified except for one tolerance

Double Top, verbatim: two successive peaks separated by an opposite reversal point;
peaks "usually at **roughly** the same price"; "price must break out of middle
reversal point"; target is the height from the highest peak to the trough,
subtracted from the breakout price.

Every clause is codeable except "roughly", so each pattern here has exactly one free
parameter - how close two peaks must be to count as equal - and it is **swept, not
tuned**. The whole grid is reported. Picking the tolerance that works and printing
only that is how a null becomes a finding, and this file exists partly because the
temptation is so strong.

## The pattern brings its own breakeven, and that is the first thing to check

Because the target rule is given, every pattern is a complete entry, stop and target,
so its reward-to-risk is *determined by its geometry* rather than chosen. The hit rate
it must reach follows immediately:

    breakeven = (1 + cost) / (1 + reward_to_risk)

That number is printed next to every result, and it is the number that decides
whether a pattern can pay at all. A pattern whose geometry gives 1:1 needs better
than 50% plus costs; one that gives 3:1 needs only 26%. **A pattern can therefore be
ruled out before any data is examined**, on its geometry alone.

## The control, which is the whole test

This desk has already established, four separate ways, that barrier geometry is a
reparameterisation: a stop and a target of given sizes produce fair odds, and moving
them around moves the hit rate and the payoff in step. So a pattern that hits 55%
with a 0.8:1 target has demonstrated nothing until it is compared against **the same
geometry entered at an arbitrary bar**.

That is the control here: for every setup, one placebo trade with an identical stop
distance and target distance, taken at a randomly chosen bar on the same instrument.
If the pattern and the placebo resolve alike, the pattern is a way of *choosing a
moment* that is worth nothing, and its apparent hit rate is its geometry talking.

## Causality

A swing high is only known `SWING` bars after it happens, so no pattern is allowed to
trigger until every peak and trough it uses has been confirmed. Entry is the close of
the bar that breaks the level, never the level itself - the break is knowable, the
fill at the exact level is not.

**Both barriers inside one bar counts as a stop**, because a bar does not record which
extreme came first. Every hit rate here is therefore biased downward.
"""

from __future__ import annotations

import argparse
import itertools
import sys
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "training"))

import candles  # noqa: E402

#: Bars either side of a swing for it to count as a pivot. A peak is confirmed this
#: many bars after it forms, and nothing may trade on it before then.
SWING = 5

#: Tolerances for "roughly the same price", in true ranges. Swept, never tuned.
TOLERANCES = (0.25, 0.5, 1.0, 2.0)

#: Bars allowed for the target or the stop to be reached after the trigger.
HORIZON = 120

#: Round-trip cost as a fraction of the risk leg.
COST = 0.03

#: Placebo draws per setup. One was too noisy to carry the comparison the whole
#: result rests on - the control needs a smaller standard error than the thing
#: being tested, not the same one.
PLACEBOS = 20

#: How far apart two peaks must be, in bars, to be "successive peaks" rather than
#: one ragged peak. The deck does not say; this is the smallest value that makes the
#: phrase mean anything and it is held fixed rather than swept, so it cannot quietly
#: become a second tuned parameter.
APART = SWING


def swings(bars: np.ndarray, k: int = SWING) -> tuple[list[int], list[int]]:
    """Indices of confirmed swing highs and lows.

    A fractal pivot: `high[i]` is the highest of the `2k+1` bars centred on it. Such
    a peak is only *knowable* at bar `i + k`, which every caller must respect.
    """
    high, low = bars[:, 2], bars[:, 3]
    peaks, troughs = [], []
    for i in range(k, len(bars) - k):
        window_hi = high[i - k : i + k + 1]
        window_lo = low[i - k : i + k + 1]
        if high[i] >= window_hi.max():
            peaks.append(i)
        if low[i] <= window_lo.min():
            troughs.append(i)
    return peaks, troughs


def _break_after(bars: np.ndarray, level: float, side: int, start: int, stop_by: int) -> int | None:
    """First bar at or after `start` whose close breaks `level` in `side`'s favour."""
    close = bars[:, 4]
    for at in range(start, min(stop_by, len(bars))):
        if (side < 0 and close[at] < level) or (side > 0 and close[at] > level):
            return at
    return None


def double_top(bars, tr, peaks, troughs, tol) -> list[dict]:
    """Two peaks at roughly one price, broken through the trough between them.

    Target is the height from the higher peak down to that trough, projected from
    the breakout - the deck's own rule, not a choice made here.
    """
    out = []
    for a, b in itertools.pairwise(peaks):
        if b - a < APART:
            continue
        between = [t for t in troughs if a < t < b]
        if not between:
            continue
        mid = min(between, key=lambda t: bars[t, 3])
        ha, hb = bars[a, 2], bars[b, 2]
        unit = max(tr[b] * bars[b, 4], 1e-12)
        if abs(ha - hb) > tol * unit:
            continue
        neck = bars[mid, 3]
        height = max(ha, hb) - neck
        if height <= 0:
            continue
        # Nothing may trade before the second peak is confirmed.
        trigger = _break_after(bars, neck, -1, b + SWING, b + SWING + HORIZON)
        if trigger is None:
            continue
        out.append(
            {
                "at": trigger,
                "side": -1,
                "entry": float(bars[trigger, 4]),
                "stop": float(max(ha, hb)),
                "target": float(bars[trigger, 4] - height),
            }
        )
    return out


def double_bottom(bars, tr, peaks, troughs, tol) -> list[dict]:
    """The mirror: two troughs at roughly one price, broken up through the peak."""
    out = []
    for a, b in itertools.pairwise(troughs):
        if b - a < APART:
            continue
        between = [p for p in peaks if a < p < b]
        if not between:
            continue
        mid = max(between, key=lambda p: bars[p, 2])
        la, lb = bars[a, 3], bars[b, 3]
        unit = max(tr[b] * bars[b, 4], 1e-12)
        if abs(la - lb) > tol * unit:
            continue
        neck = bars[mid, 2]
        height = neck - min(la, lb)
        if height <= 0:
            continue
        trigger = _break_after(bars, neck, 1, b + SWING, b + SWING + HORIZON)
        if trigger is None:
            continue
        out.append(
            {
                "at": trigger,
                "side": 1,
                "entry": float(bars[trigger, 4]),
                "stop": float(min(la, lb)),
                "target": float(bars[trigger, 4] + height),
            }
        )
    return out


def head_shoulders(bars, tr, peaks, troughs, tol) -> list[dict]:
    """Three peaks, centre highest, shoulders at approximately one level.

    "Pattern is only complete on breaking the neckline", and the target is "the
    distance from the head to the neckline projected from the neckline". The neckline
    is taken at the later trough, which is the conservative reading: a sloping
    neckline broken at its lower end triggers later and gives a smaller target.
    """
    out = []
    for i in range(len(peaks) - 2):
        left, head, right = peaks[i], peaks[i + 1], peaks[i + 2]
        if head - left < APART or right - head < APART:
            continue
        hl, hh, hr = bars[left, 2], bars[head, 2], bars[right, 2]
        if hh <= hl or hh <= hr:
            continue  # the centre peak must be the highest
        unit = max(tr[right] * bars[right, 4], 1e-12)
        if abs(hl - hr) > tol * unit:
            continue  # shoulders at approximately the same level
        first = [t for t in troughs if left < t < head]
        second = [t for t in troughs if head < t < right]
        if not first or not second:
            continue
        neck = float(bars[max(second, key=lambda t: t), 3])
        height = hh - neck
        if height <= 0:
            continue
        trigger = _break_after(bars, neck, -1, right + SWING, right + SWING + HORIZON)
        if trigger is None:
            continue
        out.append(
            {
                "at": trigger,
                "side": -1,
                "entry": float(bars[trigger, 4]),
                "stop": float(hr),
                "target": float(bars[trigger, 4] - height),
            }
        )
    return out


def inverse_head_shoulders(bars, tr, peaks, troughs, tol) -> list[dict]:
    """The bottom, which the deck calls "Head and Shoulders: Bottom (Inverse)"."""
    out = []
    for i in range(len(troughs) - 2):
        left, head, right = troughs[i], troughs[i + 1], troughs[i + 2]
        if head - left < APART or right - head < APART:
            continue
        ll, lh, lr = bars[left, 3], bars[head, 3], bars[right, 3]
        if lh >= ll or lh >= lr:
            continue
        unit = max(tr[right] * bars[right, 4], 1e-12)
        if abs(ll - lr) > tol * unit:
            continue
        first = [p for p in peaks if left < p < head]
        second = [p for p in peaks if head < p < right]
        if not first or not second:
            continue
        neck = float(bars[min(second, key=lambda p: p), 2])
        height = neck - lh
        if height <= 0:
            continue
        trigger = _break_after(bars, neck, 1, right + SWING, right + SWING + HORIZON)
        if trigger is None:
            continue
        out.append(
            {
                "at": trigger,
                "side": 1,
                "entry": float(bars[trigger, 4]),
                "stop": float(lr),
                "target": float(bars[trigger, 4] + height),
            }
        )
    return out


PATTERNS = {
    "double top": double_top,
    "double bottom": double_bottom,
    "head and shoulders": head_shoulders,
    "inverse head and shoulders": inverse_head_shoulders,
}


def resolve(bars: np.ndarray, at: int, side: int, stop: float, target: float) -> int:
    """+1 if the target came first, -1 if the stop did, 0 if neither in `HORIZON`."""
    high, low = bars[:, 2], bars[:, 3]
    for step in range(1, HORIZON + 1):
        i = at + step
        if i >= len(bars):
            return 0
        if side < 0:
            hit_t, hit_s = low[i] <= target, high[i] >= stop
        else:
            hit_t, hit_s = high[i] >= target, low[i] <= stop
        if hit_t and hit_s:
            return -1  # adverse first, by convention
        if hit_t:
            return 1
        if hit_s:
            return -1
    return 0


def placebo(bars: np.ndarray, setup: dict, rng: np.random.Generator) -> int:
    """The same geometry, entered at an arbitrary bar on the same instrument.

    Distances rather than prices, so the trade is the pattern's risk and reward
    transplanted onto a moment the pattern had no opinion about. This is the
    comparison that matters: geometry alone already produces fair odds here.
    """
    risk = abs(setup["stop"] - setup["entry"])
    reward = abs(setup["target"] - setup["entry"])
    if risk <= 0 or reward <= 0:
        return 0
    at = int(rng.integers(SWING, max(SWING + 1, len(bars) - HORIZON - 1)))
    price = bars[at, 4]
    side = setup["side"]
    stop = price + risk if side < 0 else price - risk
    target = price - reward if side < 0 else price + reward
    return resolve(bars, at, side, stop, target)


def study(symbol: str, bars: np.ndarray, tally: dict, rng: np.random.Generator) -> None:
    tr = candles.true_range(bars)
    peaks, troughs = swings(bars)
    for tol in TOLERANCES:
        for name, find in PATTERNS.items():
            for setup in find(bars, tr, peaks, troughs, tol):
                risk = abs(setup["stop"] - setup["entry"])
                reward = abs(setup["target"] - setup["entry"])
                if risk <= 0 or reward <= 0:
                    continue
                got = resolve(bars, setup["at"], setup["side"], setup["stop"], setup["target"])
                if got == 0:
                    continue
                key = (name, tol)
                seen = tally.setdefault(key, {"hit": Counter(), "rr": [], "placebo": Counter()})
                seen["hit"][got > 0] += 1
                seen["rr"].append(reward / risk)
                for _ in range(PLACEBOS):
                    fake = placebo(bars, setup, rng)
                    if fake != 0:
                        seen["placebo"][fake > 0] += 1
    print(f"{symbol:<22} {len(peaks):>6} peaks {len(troughs):>6} troughs")


def report(tally: dict) -> None:
    print(
        f"\n{'pattern':<28}{'tol':>5}{'n':>7}{'R:R':>7}{'need':>8}{'hit':>9}"
        f"{'edge/R':>9}{'placebo':>9}{'gap':>8}{'+/-':>7}"
    )
    rows = []
    for (name, tol), seen in tally.items():
        total = seen["hit"][True] + seen["hit"][False]
        if total < 30:
            continue
        hit = seen["hit"][True] / total
        rr = float(np.median(seen["rr"]))
        need = (1.0 + COST) / (1.0 + rr)
        edge = hit * rr - (1 - hit) - COST
        ptotal = seen["placebo"][True] + seen["placebo"][False]
        prate = seen["placebo"][True] / ptotal if ptotal else float("nan")
        gap = hit - prate if ptotal else float("nan")
        se = ((hit * (1 - hit) / total) + (prate * (1 - prate) / max(ptotal, 1))) ** 0.5
        rows.append((name, tol, total, rr, need, hit, edge, prate, gap, 2 * se))
    for name, tol, total, rr, need, hit, edge, prate, gap, band in sorted(rows):
        mark = "  <-" if hit > need and gap > band else ""
        print(
            f"{name:<28}{tol:>5.2f}{total:>7,}{rr:>7.2f}{need:>8.1%}{hit:>9.1%}"
            f"{edge:>+9.3f}{prate:>9.1%}{gap:>+8.1%}{band:>7.1%}{mark}"
        )
    print(
        "\n  `need` is the hit rate the pattern's own target rule demands:\n"
        "  (1 + cost) / (1 + R:R). A pattern below it loses money however good it\n"
        "  looks. `placebo` is the same geometry entered at an arbitrary bar - if it\n"
        "  matches `hit`, the pattern chose a moment worth nothing and the number is\n"
        "  its geometry talking. An arrow needs both: above its own breakeven AND\n"
        "  clear of its placebo by more than two standard errors."
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("symbols", nargs="*", default=["xauusd", "eurusd", "gbpusd", "usdjpy"])
    ap.add_argument("--where", default=".secrets/broker-deep")
    ap.add_argument("--interval", default="1h")
    args = ap.parse_args()

    print(f"swing {SWING}, horizon {HORIZON} bars, cost {COST:.2f}R, tolerances {TOLERANCES}\n")
    tally: dict = {}
    rng = np.random.default_rng(0)
    for symbol in args.symbols:
        found = sorted(Path(args.where).glob(f"{symbol}_{args.interval}_*.csv.gz"))
        if not found:
            print(f"{symbol:<22} no {args.interval} file")
            continue
        bars, _repaired = candles.read(found[0])
        study(symbol, bars, tally, rng)
    report(tally)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
