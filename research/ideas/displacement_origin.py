"""Does price return to a displacement's origin more than to a matched price?

Asked on 2026-10-14: *test the displacement origin again to be sure, we can
even create a statespace version for more tests, test across timeframes (4h and
daily included) and assets.*

This desk already records an **82% return rate** to the displacement origin,
with the lesson attached that it is *a target hit rate, not an entry signal*.
The number was measured on one configuration, so it is re-measured here across
four timeframes and five asset families - and against the control the original
number lacked.

## Why a return rate needs a placebo

Price returns to **any** nearby price often. The weekend-gap arm of
`gaps_climax.py` makes the point: gaps fill at 86% within a day, and a price
the same distance the *other* side of the open is reached 62% of the time. The
gap is worth something, but 24 points of it rather than 86.

So every origin here is matched against a price the same distance away on the
opposite side, reached through the identical walk. A return rate that does not
beat its placebo is a statement about how far away the price is, not about
displacement.

## The two definitions, because the sources disagree

A **fair value gap** is the three-candle form: candle one's high below candle
three's low, with candle two's body spanning the space. A **displacement** is
the single-bar form: a body larger than `IMPULSE` typical bars. They are not
the same set, so both are measured, and the origin is the 50% mark of the
displacing body in each case - which is what the idea specifies.

Nothing is read as an entry. The output is a return rate, its placebo, and the
difference, at four timeframes and across families - which is what a statespace
version would have to publish before it could be worth building.
"""

from __future__ import annotations

import math
import os
import re
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from level_signatures import CACHE, JITTER, SEED  # noqa: E402
from screen import load  # noqa: E402

FRAMES = tuple(os.environ.get("FRAMES", "15m,1h,4h,1d").split(","))
#: A displacing body, in typical bars of the prior window.
IMPULSE = float(os.environ.get("IMPULSE", "1.5"))
LOOK = int(os.environ.get("LOOK", "50"))
#: Bars the return is allowed within.
WAIT = int(os.environ.get("WAIT", "60"))
EQUITIES = int(os.environ.get("EQUITIES", "40"))


def families() -> dict[str, list[str]]:
    names = sorted({p.name.split(".")[0] for p in CACHE.glob("*.1h.npz")})
    synth = re.compile(r"(Volatility|Step|Jump|Boom|Crash|Drift_Switch|Range_Break|Spot_Up)")
    fx = re.compile(r"^(EUR|GBP|USD|AUD|NZD|CAD|CHF|JPY)[A-Z]{3}$")
    out: dict[str, list[str]] = {"fx": [], "metal": [], "equity": [], "synthetic": []}
    for name in names:
        if name.startswith(("XAU", "XAG")):
            out["metal"].append(name)
        elif fx.match(name):
            out["fx"].append(name)
        elif synth.search(name):
            out["synthetic"].append(name)
        elif "_Basket" not in name:
            out["equity"].append(name)
    out["fx"] = out["fx"][:12]
    out["synthetic"] = out["synthetic"][:8]
    step = max(len(out["equity"]) // EQUITIES, 1)
    out["equity"] = out["equity"][::step][:EQUITIES]
    return {k: v for k, v in out.items() if v}


def origins(bars, kind: str, rng) -> list[tuple[float, float]]:
    """`(returned, placebo reached)` per displacement, non-overlapping."""
    o, h, l_, c = bars["open"], bars["high"], bars["low"], bars["close"]
    out: list[tuple[float, float]] = []
    at = LOOK + 2
    end = len(c) - WAIT - 2
    while at < end:
        window = slice(at - LOOK, at)
        typical = float(np.median(h[window] - l_[window]))
        if not (typical > 0):
            at += 1
            continue
        body = float(c[at]) - float(o[at])
        if kind == "fvg":
            # Three candles: the first's high below the third's low, or mirror.
            if at + 2 >= end:
                break
            up = float(h[at - 1]) < float(l_[at + 1])
            down = float(l_[at - 1]) > float(h[at + 1])
            if not (up or down):
                at += 1
                continue
            start = at + 2
        else:
            if abs(body) < IMPULSE * typical:
                at += 1
                continue
            up = body > 0
            start = at + 1
        # The origin: the halfway mark of the displacing body.
        origin = (float(o[at]) + float(c[at])) / 2.0
        here = float(c[start - 1])
        gap = origin - here
        if abs(gap) < 0.1 * typical:
            at += 1
            continue
        placebo = here + gap * -(1.0 + float(rng.uniform(-JITTER, JITTER)))
        window = slice(start, start + WAIT)
        if start + WAIT >= len(c):
            break
        reached_origin = (
            float(l_[window].min()) <= origin if gap < 0 else float(h[window].max()) >= origin
        )
        reached_placebo = (
            float(l_[window].min()) <= placebo
            if placebo < here
            else float(h[window].max()) >= placebo
        )
        out.append((1.0 if reached_origin else 0.0, 1.0 if reached_placebo else 0.0))
        # No two displacements share a forward window.
        at = start + WAIT + 1
    return out


#: Pairs whose relationship this desk already knows is strong and
#: contemporaneous. The triangle legs are the positive control for any FX
#: relationship screen.
RELATED = (
    ("EURUSD", "GBPUSD"),
    ("EURUSD", "EURGBP"),
    ("XAUUSD", "AUDUSD"),
    ("XAUUSD", "XAGUSD"),
    ("USDJPY", "EURJPY"),
)


def across(leader: str, follower: str, frame: str, rng) -> tuple[int, float, float, float]:
    """When the leader displaces, does the follower return to **its** origin?

    The follower's origin is the halfway mark of its own contemporaneous bar,
    so the leader supplies only the **timing**. Three numbers come back: the
    follower's return rate on those bars, its placebo, and its return rate at
    bars chosen at random - which is the comparison that matters, because a
    follower that returns 86% of the time anyway has not been told anything.
    """
    a, b = load(leader, frame), load(follower, frame)
    if a is None or b is None:
        return 0, float("nan"), float("nan"), float("nan")
    common = np.intersect1d(a["time"], b["time"])
    if len(common) < 2000:
        return 0, float("nan"), float("nan"), float("nan")
    ia = np.searchsorted(a["time"], common)
    ib = np.searchsorted(b["time"], common)
    ao, ac, ah, al = (a[k][ia] for k in ("open", "close", "high", "low"))
    bo, bc, bh, bl = (b[k][ib] for k in ("open", "close", "high", "low"))

    def follower_return(at: int) -> tuple[float, float] | None:
        window = slice(max(at - LOOK, 0), at)
        typical = float(np.median(bh[window] - bl[window]))
        if not (typical > 0) or at + WAIT + 2 >= len(bc):
            return None
        origin = (float(bo[at]) + float(bc[at])) / 2.0
        here = float(bc[at])
        gap = origin - here
        if abs(gap) < 0.1 * typical:
            return None
        placebo = here + gap * -(1.0 + float(rng.uniform(-JITTER, JITTER)))
        ahead = slice(at + 1, at + 1 + WAIT)
        hit = float(bl[ahead].min()) <= origin if gap < 0 else float(bh[ahead].max()) >= origin
        other = (
            float(bl[ahead].min()) <= placebo
            if placebo < here
            else float(bh[ahead].max()) >= placebo
        )
        return (1.0 if hit else 0.0, 1.0 if other else 0.0)

    picked: list[tuple[float, float]] = []
    at = LOOK + 2
    while at < len(ac) - WAIT - 2:
        window = slice(at - LOOK, at)
        typical = float(np.median(ah[window] - al[window]))
        if typical > 0 and abs(float(ac[at]) - float(ao[at])) >= IMPULSE * typical:
            got = follower_return(at)
            if got is not None:
                picked.append(got)
                at += WAIT + 1
                continue
        at += 1
    if len(picked) < 60:
        return len(picked), float("nan"), float("nan"), float("nan")
    # The unconditional baseline: the same measurement at random bars.
    anywhere: list[float] = []
    for at in rng.integers(LOOK + 2, len(ac) - WAIT - 2, size=min(4 * len(picked), 4000)):
        got = follower_return(int(at))
        if got is not None:
            anywhere.append(got[0])
    return (
        len(picked),
        float(np.mean([x for x, _ in picked])),
        float(np.mean([y for _, y in picked])),
        float(np.mean(anywhere)) if anywhere else float("nan"),
    )


def main() -> None:
    rng = np.random.default_rng(SEED)
    print(
        f"displacement origin = the 50% mark of the displacing body,\n"
        f"impulse {IMPULSE} typical bars, return allowed within {WAIT} bars,\n"
        f"placebo the same distance the other side. Non-overlapping.\n"
    )
    groups = families()
    for kind in ("displacement", "fvg"):
        print("=" * 78)
        print(kind)
        print("=" * 78)
        print(f"  {'family':<12}{'frame':<6}{'events':>8}{'return':>9}{'placebo':>10}{'diff':>9}")
        for family, names in groups.items():
            for frame in FRAMES:
                rows: list[tuple[float, float]] = []
                for name in names:
                    bars = load(name, frame)
                    if bars is None:
                        continue
                    rows += origins(bars, kind, rng)
                if len(rows) < 100:
                    continue
                got = float(np.mean([a for a, _ in rows]))
                placebo = float(np.mean([b for _, b in rows]))
                print(
                    f"  {family:<12}{frame:<6}{len(rows):>8,}{got:>9.3f}"
                    f"{placebo:>10.3f}{got - placebo:>+9.3f}"
                )
        print()
    print(
        "  A return rate that does not beat its placebo is a statement about\n"
        "  how far the origin is, not about displacement. The 82% on record\n"
        "  was measured without this column.\n"
    )
    print("=" * 78)
    print("ACROSS A RELATIONSHIP - the leader supplies only the timing")
    print("=" * 78)
    print(
        f"  {'leader -> follower':<24}{'frame':<6}{'events':>8}{'return':>9}"
        f"{'placebo':>10}{'anywhere':>10}"
    )
    for leader, follower in RELATED:
        for frame in FRAMES:
            n, got, placebo, anywhere = across(leader, follower, frame, rng)
            if n < 60 or not math.isfinite(got):
                continue
            print(
                f"  {leader + ' -> ' + follower:<24}{frame:<6}{n:>8,}{got:>9.3f}"
                f"{placebo:>10.3f}{anywhere:>10.3f}"
            )
    print(
        "\n  `anywhere` is the follower's return rate at bars chosen at random.\n"
        "  A leader that tells the follower nothing leaves all three columns\n"
        "  together, and this desk's standing result is that relationships are\n"
        "  contemporaneous while every lagged measure is null."
    )
    _ = math


if __name__ == "__main__":
    main()
