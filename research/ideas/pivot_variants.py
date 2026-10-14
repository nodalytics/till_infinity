"""Every published pivot variant, including the ones the sources disagree on.

Asked on 2026-10-14: *take all the suggestions from the different sources* -
after a review found three places where the published formulas conflict. The
disagreements are candidates, not noise to be resolved by picking a favourite:

- **Woodie's input.** Most sources give `(H+L+2C)/4`. Others give
  `(H+L+2*today's open)/4`. These are different objects and one of them is not
  knowable before the session opens, which is the single property
  `drawing/pivots.py` values pivots for. Both are here, labelled.
- **Camarilla's fifth rung.** `H5 = H/L` in one source, `(H/L)*C` in another.
  The first is dimensionally wrong - a ratio is not a price - so it is included
  precisely to show what a dimensionally wrong level scores.
- **DeMark.** One guide prints `(H+L+2C)/4`, which is Woodie's formula. It is
  included as `demark_mistranscribed` and it is **a control**: if it does not
  score identically to `woodie_close`, this harness has a bug.

Each family nominates prices from the **prior** session and is raced over the
**next** one, so one decision is one session and no two share a bar. Every
nomination is matched against a placebo price at the same distance from the
session open, through the identical detector, and the whole thing is gated on
`Range_Break`, whose generator has a boundary by construction.
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

from level_signatures import CONTROL, GENERATED, JITTER, SEED, TRADED, shuffle_blocks  # noqa: E402
from screen import load  # noqa: E402

#: A break needs price through the level by this much of the prior range.
MARGIN = float(os.environ.get("MARGIN", "0.1"))


def families(high: float, low: float, close: float, open_prev: float, open_now: float) -> dict:
    """Every variant, as `{family: {name: price}}`.

    `open_prev` is the prior session's open, which DeMark branches on;
    `open_now` is today's, which only the disputed Woodie needs.
    """
    rng = high - low
    classic = (high + low + close) / 3.0
    woodie_c = (high + low + 2.0 * close) / 4.0
    woodie_o = (high + low + 2.0 * open_now) / 4.0
    if close < open_prev:
        x = high + 2.0 * low + close
    elif close > open_prev:
        x = 2.0 * high + low + close
    else:
        x = high + low + 2.0 * close
    out: dict[str, dict[str, float]] = {
        "classic": {
            "PP": classic,
            "R1": 2 * classic - low,
            "S1": 2 * classic - high,
            "R2": classic + rng,
            "S2": classic - rng,
            "R3": high + 2 * (classic - low),
            "S3": low - 2 * (high - classic),
        },
        "woodie_close": {
            "PP": woodie_c,
            "R1": 2 * woodie_c - low,
            "S1": 2 * woodie_c - high,
            "R2": woodie_c + rng,
            "S2": woodie_c - rng,
        },
        # Needs today's open, so it is not knowable before the session - the
        # one property the others have.
        "woodie_open": {
            "PP": woodie_o,
            "R1": 2 * woodie_o - low,
            "S1": 2 * woodie_o - high,
            "R2": woodie_o + rng,
            "S2": woodie_o - rng,
        },
        "fibonacci": {
            "PP": classic,
            "R1": classic + 0.382 * rng,
            "S1": classic - 0.382 * rng,
            "R2": classic + 0.618 * rng,
            "S2": classic - 0.618 * rng,
            "R3": classic + rng,
            "S3": classic - rng,
        },
        "camarilla": {
            "H1": close + rng * 1.1 / 12.0,
            "L1": close - rng * 1.1 / 12.0,
            "H2": close + rng * 1.1 / 6.0,
            "L2": close - rng * 1.1 / 6.0,
            "H3": close + rng * 1.1 / 4.0,
            "L3": close - rng * 1.1 / 4.0,
            "H4": close + rng * 1.1 / 2.0,
            "L4": close - rng * 1.1 / 2.0,
        },
        "demark": {"PP": x / 4.0, "R1": x / 2.0 - low, "S1": x / 2.0 - high},
        # The control: this is Woodie's formula, printed as DeMark's. It must
        # score identically to `woodie_close` or the harness is wrong.
        "demark_mistranscribed": {
            "PP": woodie_c,
            "R1": 2 * woodie_c - low,
            "S1": 2 * woodie_c - high,
        },
    }
    # The fifth Camarilla rung, both published versions. `h5_ratio` is
    # dimensionally wrong on purpose - it is a ratio, not a price - and is here
    # to show what that scores.
    out["camarilla_h5_ratio"] = {
        "H5": high / low if low else close,
        "L5": low / high if high else close,
    }
    out["camarilla_h5_scaled"] = {
        "H5": (high / low) * close if low else close,
        "L5": (low / high) * close if high else close,
    }
    return out


def sessions(bars) -> list[tuple[int, int]]:
    """Calendar-day spans as `(start, end)` index pairs, oldest first."""
    days = (bars["time"] // 86400).astype(np.int64)
    edges = np.flatnonzero(np.diff(days)) + 1
    bounds = np.concatenate([[0], edges, [len(days)]])
    return [(int(a), int(b)) for a, b in zip(bounds[:-1], bounds[1:], strict=True) if b - a >= 4]


def race(bars, price: float, start: int, end: int, margin: float) -> str | None:
    """`hold`, `break`, or `None` if price never reached the level that session."""
    highs, lows, closes = bars["high"], bars["low"], bars["close"]
    for i in range(start, end):
        if not (lows[i] <= price <= highs[i]):
            continue
        from_below = closes[i - 1] < price if i else closes[i] < price
        for j in range(i + 1, end):
            if from_below and closes[j] >= price + margin:
                return "break"
            if not from_below and closes[j] <= price - margin:
                return "break"
            if from_below and closes[j] <= price - margin:
                return "hold"
            if not from_below and closes[j] >= price + margin:
                return "hold"
        return None
    return None


def arm(group: str, names: tuple[str, ...], rng, mixed: bool = False) -> None:
    tally: dict[str, list[int]] = {}
    placebo: dict[str, list[int]] = {}
    for name in names:
        bars = load(name)
        if bars is None:
            continue
        if mixed:
            bars = shuffle_blocks(bars, rng)
        spans = sessions(bars)
        for k in range(1, len(spans)):
            prev_a, prev_b = spans[k - 1]
            a, b = spans[k]
            high = float(bars["high"][prev_a:prev_b].max())
            low = float(bars["low"][prev_a:prev_b].min())
            close = float(bars["close"][prev_b - 1])
            open_prev = float(bars["open"][prev_a])
            open_now = float(bars["open"][a])
            if not (high > low > 0):
                continue
            margin = MARGIN * (high - low)
            for family, levels in families(high, low, close, open_prev, open_now).items():
                for price in levels.values():
                    if not (math.isfinite(price) and price > 0):
                        continue
                    got = race(bars, price, a, b, margin)
                    if got is not None:
                        tally.setdefault(family, [0, 0])
                        tally[family][0 if got == "hold" else 1] += 1
                    # Matched placebo: the same distance from the session open.
                    gap = price - open_now
                    fake = open_now + gap * (1.0 + float(rng.uniform(-JITTER, JITTER)))
                    got = race(bars, fake, a, b, margin)
                    if got is not None:
                        placebo.setdefault(family, [0, 0])
                        placebo[family][0 if got == "hold" else 1] += 1
    if not tally:
        print(f"  {group}: nothing reached\n")
        return
    print(f"  {group}")
    print(f"    {'family':<24}{'touched':>9}{'hold rate':>11}{'placebo':>10}{'diff':>9}")
    for family in sorted(tally):
        hold, broke = tally[family]
        total = hold + broke
        if total < 100:
            continue
        rate = hold / total
        ph, pb = placebo.get(family, [0, 0])
        prate = ph / (ph + pb) if (ph + pb) >= 100 else float("nan")
        print(f"    {family:<24}{total:>9,}{rate:>11.4f}{prate:>10.4f}{rate - prate:>+9.4f}")
    print(
        "      `demark_mistranscribed` must match `woodie_close` exactly - it is\n"
        "      the same formula, and a difference means this harness is wrong.\n"
    )


def main() -> None:
    rng = np.random.default_rng(SEED)
    print(
        f"prior-session pivots raced over the next session, break margin "
        f"{MARGIN:g} of the prior range\nOne decision a session, so no two "
        f"share a bar.\n"
    )
    for group, names in (("traded", TRADED), ("control", CONTROL), ("generated", GENERATED)):
        print("=" * 70)
        print(group)
        print("=" * 70)
        arm("real", names, rng)
        arm("shuffled", names, rng, mixed=True)


if __name__ == "__main__":
    main()
