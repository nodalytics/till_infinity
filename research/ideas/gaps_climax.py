"""Weekend gaps, volume climax, and the lead-lag family - with their base rates.

Three of the swing ideas proposed on 2026-10-14 that are both untested here and
computable. The fourth, the Fair Value Gap, is **already measured**: an FVG is
the displacement origin, `drawing/gaps.py` already proposes them, and this desk
recorded an **82% return rate** to it with the lesson attached - that is a
target hit rate, not an entry signal.

## Weekend gaps: the claim comes with a number, which is rare

> over 80% of these structural gaps are filled within the first 24 to 48 hours

A stated base rate is a gift, because it can be wrong rather than vague. The
gap is the Sunday open against Friday's close; "filled" is price trading back
through Friday's close. Reported with the **unconditional** fill rate beside it,
because a market that revisits any nearby price 80% of the time in two days
makes the gap irrelevant - the comparison is the gap's fill rate against a
**matched non-gap price** at the same distance, which is the same placebo design
every level test here uses.

## Volume climax: a conjunction, so each leg is reported

A daily volume spike beyond 2.5 standard deviations, at a new 20-day extreme,
read as exhaustion rather than continuation. `candle-screen.md` found volume
features null for direction individually, so the interest is the **conjunction**
- and each leg is scored alone as well, because a conjunction that beats its
legs has earned something and one that does not is its best leg.

## Lead-lag: three ideas with one structure

Gold leading AUDUSD, gold against the dollar, and a currency strength matrix are
all the same claim - a lagged cross-asset signal predicting a pair. Every lagged
measure on this desk has been null while contemporaneous vol and tails are
large, so the design that matters is the **honest null**: the relationship is
fitted on the first half and scored on the second, because an adaptive ratio
gives a Dickey-Fuller t of -29 from noise and -3.46 once the fit is out of
sample.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from level_signatures import JITTER, SEED, auc, shuffle_blocks  # noqa: E402
from screen import load  # noqa: E402

PAIRS = tuple(
    os.environ.get(
        "PAIRS", "EURUSD,GBPUSD,USDJPY,XAUUSD,AUDUSD,USDCAD,EURJPY,GBPJPY,EURGBP,USDCHF"
    ).split(",")
)
#: Hours a weekend gap is given to fill, matching "24 to 48".
FILL_HOURS = tuple(int(k) for k in os.environ.get("FILL_HOURS", "24,48").split(","))
#: Smallest gap counted, in typical bars of the prior week.
LEAST_GAP = float(os.environ.get("LEAST_GAP", "0.5"))


def weekend_gaps(bars) -> list[dict]:
    """Each week's open against the prior close, and whether it filled."""
    when, o, h, l_, c = bars["time"], bars["open"], bars["high"], bars["low"], bars["close"]
    # A gap is a break of more than twelve hours between consecutive bars,
    # which on an hourly feed is a weekend and nothing else.
    breaks = np.flatnonzero(np.diff(when) > 12 * 3600) + 1
    out: list[dict] = []
    for at in breaks:
        if at < 120 or at + max(FILL_HOURS) + 2 >= len(c):
            continue
        before = slice(at - 120, at)
        typical = float(np.median(h[before] - l_[before]))
        friday = float(c[at - 1])
        sunday = float(o[at])
        if not (typical > 0 and friday > 0):
            continue
        gap = sunday - friday
        if abs(gap) < LEAST_GAP * typical:
            continue
        row = {"gap": abs(gap) / typical, "up": 1.0 if gap > 0 else 0.0}
        for hours in FILL_HOURS:
            # **From the bar after the gap, not from the gap bar.** The first
            # version measured from `at`, so the Sunday bar's own range counted
            # toward the fill - while the intraday control measured from the bar
            # *after* its jump. A wide first bar would then hand the weekend arm
            # a fill the control could not have, and the comparison is the whole
            # test.
            window = slice(at + 1, at + 1 + hours)
            # Filled means price traded back through Friday's close.
            filled = (
                float(l_[window].min()) <= friday if gap > 0 else float(h[window].max()) >= friday
            )
            row[f"filled_{hours}"] = 1.0 if filled else 0.0
            # The placebo: a price the same distance the other side of the
            # open, which no gap story applies to.
            scale = 1.0 + float(np.random.default_rng(int(at)).uniform(-JITTER, JITTER))
            mirror = sunday + gap * scale
            reached = (
                float(h[window].max()) >= mirror if gap > 0 else float(l_[window].min()) <= mirror
            )
            row[f"placebo_{hours}"] = 1.0 if reached else 0.0
        out.append(row)
    return out


#: Size buckets, in typical bars of the prior week. A weekend gap is only
#: special if it fills more than an intraday move of the **same size**.
BUCKETS = ((0.5, 1.0), (1.0, 2.0), (2.0, 4.0), (4.0, 99.0))


def intraday_jumps(bars) -> list[dict]:
    """Single-bar moves, scored exactly as a weekend gap is.

    **The control the gap arm was missing.** Filling a gap is mean reversion
    while its placebo requires continuation, so the 86% could be the general
    post-jump reversion rather than anything about weekends. The analogue of a
    gap in continuous data is a bar that moved `s` typical bars - after which,
    does price come back to where it started?

    Bars adjacent to a time break are excluded, so a weekend cannot be counted
    here as well.
    """
    when, h, l_, c = bars["time"], bars["high"], bars["low"], bars["close"]
    steps = np.diff(when)
    typical_step = float(np.median(steps)) if len(steps) else 0.0
    out: list[dict] = []
    at = 120
    end = len(c) - max(FILL_HOURS) - 2
    while at < end:
        # Continuous on both sides: no weekend, no missing session.
        if steps[at - 1] > 1.5 * typical_step or steps[at] > 1.5 * typical_step:
            at += 1
            continue
        before = slice(at - 120, at)
        typical = float(np.median(h[before] - l_[before]))
        anchor = float(c[at - 1])
        if not (typical > 0 and anchor > 0):
            at += 1
            continue
        jump = float(c[at]) - anchor
        if abs(jump) < LEAST_GAP * typical:
            at += 1
            continue
        row = {"gap": abs(jump) / typical, "up": 1.0 if jump > 0 else 0.0}
        for hours in FILL_HOURS:
            window = slice(at + 1, at + 1 + hours)
            row[f"filled_{hours}"] = float(
                (float(l_[window].min()) <= anchor)
                if jump > 0
                else (float(h[window].max()) >= anchor)
            )
            scale = 1.0 + float(np.random.default_rng(int(at)).uniform(-JITTER, JITTER))
            mirror = float(c[at]) + jump * scale
            row[f"placebo_{hours}"] = float(
                (float(h[window].max()) >= mirror)
                if jump > 0
                else (float(l_[window].min()) <= mirror)
            )
        out.append(row)
        # No two jumps share a forward window.
        at += max(FILL_HOURS) + 1
    return out


def by_size(label: str, rows: list[dict]) -> None:
    """Fill rates bucketed by size, so weekend and intraday meet at like for like."""
    for lo, hi in BUCKETS:
        got = [r for r in rows if lo <= r["gap"] < hi]
        if len(got) < 40:
            continue
        cells = ""
        for hours in FILL_HOURS:
            filled = float(np.mean([r[f"filled_{hours}"] for r in got]))
            placebo = float(np.mean([r[f"placebo_{hours}"] for r in got]))
            cells += f"{filled:>10.3f}{placebo:>10.3f}"
        span = f"{lo:g}-{hi:g}" if hi < 90 else f"{lo:g}+"
        print(f"    {label:<12}{span:<8}{len(got):>7,}" + cells)


def climax(bars) -> tuple[list[float], list[float], dict[str, list[float]]]:
    """Daily volume spike at an extreme, scored as a reversal call."""
    o, h, l_, c, v = bars["open"], bars["high"], bars["low"], bars["close"], bars["volume"]
    if len(c) < 120:
        return [], [], {}
    scores: list[float] = []
    truths: list[float] = []
    legs: dict[str, list[float]] = {"spike": [], "extreme": [], "small body": []}
    at = 60
    while at < len(c) - 6:
        window = slice(at - 50, at)
        mean, sd = float(v[window].mean()), float(v[window].std())
        bar = float(h[at] - l_[at])
        if not (sd > 0 and bar > 0):
            at += 1
            continue
        spike = (float(v[at]) - mean) / sd
        new_high = float(h[at]) >= float(h[at - 20 : at].max())
        new_low = float(l_[at]) <= float(l_[at - 20 : at].min())
        if not (new_high or new_low):
            at += 1
            continue
        body = abs(float(c[at]) - float(o[at])) / bar
        # The idea's reversal: price should go against the extreme.
        ahead = math.log(float(c[at + 5]) / float(c[at]))
        reversed_ = (ahead < 0) if new_high else (ahead > 0)
        scores.append(spike)
        truths.append(1.0 if reversed_ else 0.0)
        legs["spike"].append(spike)
        legs["extreme"].append(1.0)
        legs["small body"].append(1.0 - body)
        at += 6  # no two calls share an outcome bar
    return scores, truths, legs


def lead_lag(leader: str, follower: str, frame: str) -> None:
    """Does the leader's move predict the follower's, fitted out of sample?"""
    a, b = load(leader, frame), load(follower, frame)
    if a is None or b is None:
        print(f"    {leader} -> {follower}: missing")
        return
    common = np.intersect1d(a["time"], b["time"])
    if len(common) < 4000:
        print(f"    {leader} -> {follower}: {len(common)} shared bars")
        return
    pa = a["close"][np.searchsorted(a["time"], common)]
    pb = b["close"][np.searchsorted(b["time"], common)]
    ra, rb = np.diff(np.log(pa)), np.diff(np.log(pb))
    half = len(ra) // 2
    # Fitted on the first half: the sign of the contemporaneous relationship.
    sign = 1.0 if float(np.corrcoef(ra[:half], rb[:half])[0, 1]) >= 0 else -1.0
    for lag in (1, 2, 6, 12):
        if len(ra) <= half + lag + 100:
            continue
        # Scored on the second half only, leader leading by `lag` bars.
        lead = sign * ra[half:-lag]
        follow = rb[half + lag :]
        keep = np.isfinite(lead) & np.isfinite(follow) & (follow != 0)
        if keep.sum() < 500:
            continue
        truth = (follow[keep] > 0).astype(float)
        got = auc(lead[keep][truth > 0.5], lead[keep][truth < 0.5])
        contemporaneous = float(np.corrcoef(ra[half:], rb[half:])[0, 1])
        print(
            f"    {leader} -> {follower}  lag {lag:>2}  n {int(keep.sum()):>6,}  "
            f"AUC {got:.4f}   contemporaneous r {contemporaneous:+.3f}"
        )


def main() -> None:
    rng = np.random.default_rng(SEED)
    # The named target assets, plus crypto as a negative control: BTCUSD and
    # ETHUSD trade continuously, so a weekend gap should not exist there. If
    # the detector finds them anyway and they fill like FX, the detector is
    # the finding.
    groups = {
        "fx": list(PAIRS),
        "index": [
            "Germany_40",
            "US_SP_500",
            "US_Tech_100",
            "UK_100",
            "Japan_225",
            "France_40",
            "Europe_50",
            "Hong_Kong_50",
        ],
        "energy": ["US_Oil", "UK_Brent_Oil", "NGAS"],
        "crypto (24/7, control)": ["BTCUSD", "ETHUSD"],
    }
    print("WEEKEND GAPS BY ASSET FAMILY - the claim is over 80% filled in 24 to 48h\n")
    print(
        f"    {'family':<24}{'gaps':>7}"
        + "".join(f"{f'fill {h}h':>10}{'placebo':>10}" for h in FILL_HOURS)
    )
    for family, names in groups.items():
        rows: list[dict] = []
        for name in names:
            bars = load(name, "1h")
            if bars is None:
                continue
            rows += weekend_gaps(bars)
        if len(rows) < 40:
            print(f"    {family:<24}{len(rows):>7}  too few")
            continue
        cells = ""
        for hours in FILL_HOURS:
            cells += f"{float(np.mean([r[f'filled_{hours}'] for r in rows])):>10.3f}"
            cells += f"{float(np.mean([r[f'placebo_{hours}'] for r in rows])):>10.3f}"
        print(f"    {family:<24}{len(rows):>7,}" + cells)
    print()

    print("WEEKEND GAPS - the claim is over 80% filled within 24 to 48 hours\n")
    print(
        f"    {'arm':<10}{'gaps':>7}"
        + "".join(f"{f'fill {h}h':>10}{'placebo':>10}" for h in FILL_HOURS)
    )
    for label, mixed in (("real", False), ("shuffled", True)):
        rows: list[dict] = []
        for name in PAIRS:
            bars = load(name, "1h")
            if bars is None:
                continue
            if mixed:
                bars = shuffle_blocks(bars, rng)
            rows += weekend_gaps(bars)
        if len(rows) < 50:
            print(f"    {label:<10}{len(rows):>7}  too few")
            continue
        cells = ""
        for hours in FILL_HOURS:
            filled = float(np.mean([r[f"filled_{hours}"] for r in rows]))
            placebo = float(np.mean([r[f"placebo_{hours}"] for r in rows]))
            cells += f"{filled:>10.3f}{placebo:>10.3f}"
        print(f"    {label:<10}{len(rows):>7,}" + cells)
    print(
        "      `placebo` is a price the same distance the **other** side of the\n"
        "      open. A gap fill only means something if it beats that.\n"
    )
    print("    matched on size, against intraday moves of the same size\n")
    print(
        f"    {'arm':<12}{'size':<8}{'n':>7}"
        + "".join(f"{f'fill {h}h':>10}{'placebo':>10}" for h in FILL_HOURS)
    )
    weekend: list[dict] = []
    intraday: list[dict] = []
    for name in PAIRS:
        bars = load(name, "1h")
        if bars is None:
            continue
        weekend += weekend_gaps(bars)
        intraday += intraday_jumps(bars)
    by_size("weekend", weekend)
    by_size("intraday", intraday)
    print(
        "\n      If the two arms agree inside a size bucket, the weekend is not\n"
        "      the story - post-jump mean reversion is, and a gap is simply a\n"
        "      jump that happened to occur over a weekend.\n"
    )

    print("VOLUME CLIMAX - a spike at a 20-day extreme, read as exhaustion\n")
    print(f"    {'arm':<10}{'calls':>7}{'reversal rate':>15}{'AUC of spike':>14}")
    for label, mixed in (("real", False), ("shuffled", True)):
        every_score: list[float] = []
        every_truth: list[float] = []
        for name in tuple(PAIRS) + (
            "US_Oil",
            "UK_Brent_Oil",
            "BTCUSD",
            "ETHUSD",
            "Germany_40",
            "US_SP_500",
        ):
            bars = load(name, "1d")
            if bars is None:
                continue
            if mixed:
                bars = shuffle_blocks(bars, rng)
            s, t, _ = climax(bars)
            every_score += s
            every_truth += t
        if len(every_truth) < 100:
            print(f"    {label:<10}{len(every_truth):>7}  too few")
            continue
        s, t = np.asarray(every_score), np.asarray(every_truth)
        got = auc(s[t > 0.5], s[t < 0.5]) if 0 < t.sum() < len(t) else float("nan")
        print(f"    {label:<10}{len(t):>7,}{float(t.mean()):>15.3f}{got:>14.4f}")
    print(
        "      A reversal rate near a half is no exhaustion. The AUC asks whether\n"
        "      a **bigger** spike reverses more, which is the idea's own claim.\n"
    )

    print("LEAD-LAG - fitted on the first half, scored on the second\n")
    # The cache has no 30m frame, which is why this arm silently printed
    # "missing" three times on its first run.
    for leader, follower in (
        ("XAUUSD", "AUDUSD"),
        ("US_Oil", "USDCAD"),
        ("UK_Brent_Oil", "USDCAD"),
        ("XAUUSD", "EURUSD"),
        ("EURUSD", "GBPUSD"),
    ):
        lead_lag(leader, follower, "1h")
    print(
        "\n      The sign of the relationship is taken from the first half only.\n"
        "      An AUC at 0.5 with a large contemporaneous r is this desk's\n"
        "      standing result: relationships are contemporaneous."
    )


if __name__ == "__main__":
    main()
