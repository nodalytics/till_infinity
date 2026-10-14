"""The published MT5 direction ideas, every one measured on the same detector.

Six batches of ideas arrived naming specific setups: the WM/Refinitiv London
fix as a 24-to-72-hour magnet, the London-New York overlap sweep, the Wednesday
triple-swap squeeze, the daily-open reversal from an extreme close, and the
pre-announcement volatility squeeze. They are written in different vocabularies
but they are **one shape**: a clock- or geometry-anchored condition fires, and a
direction is claimed over a forward window.

So they get one detector, and each idea is a row in it. That is the only way the
answers are comparable, and it is also the only way a shared artefact shows up
as a shared number rather than as five separate discoveries.

## What the controls are for, each earned the hard way here

- **A block-shuffled twin.** Every rule runs again on a surrogate built from
  the same feed - blocks of 50 bars, re-levelled in log space, per-bar OHLCV
  geometry carried - which keeps the bar shapes and destroys the calendar. A
  rule that fires on structure the shuffle preserves is reading its own
  definition. This is what caught `overshoot`.
- **Deriv synthetic placebos.** These are real markets with a known generator
  and **no London fix, no carry crowd and no rollover**. Any calendar rule that
  pays on them is reading something that cannot be what it claims.
- **Spacing by the full horizon.** Overlapping forward windows have produced a
  direction AUC of 0.79 here that collapsed to 0.51 once separated. Events
  inside one horizon of an accepted event are dropped.
- **Power before any null.** Each rule reports the drift it *would* detect, by
  planting a known effect in the forward returns of its own detected events and
  sweeping the size. A null with no power statement is not a measurement.

## The clock is checked, not assumed

Every one of these rules names a GMT hour, and MT5 server time is usually
UTC+2 or UTC+3. An offset error silently shifts every window and would null
all of them for a reason that has nothing to do with the ideas. So the
timestamps are verified against a fact already measured in this repo: **FX
volatility peaks at 14-15 UTC at about three times its trough**. If the
observed peak is not there, the clock is wrong and every calendar row is void.

The London fix is run at both 15:00 and 16:00 UTC, because 16:00 London is one
or the other depending on British Summer Time and the cache does not carry the
offset. Reporting both is cheaper than being wrong half the year.
"""

from __future__ import annotations

import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from level_signatures import shuffle_blocks  # noqa: E402
from screen import load  # noqa: E402

MAJORS = ("EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD", "EURJPY")
CARRY = ("USDMXN", "USDZAR", "USDPLN", "USDNOK", "USDSEK")
PLACEBO = (
    "Volatility_75_Index",
    "Volatility_100_Index",
    "Step_Index",
    "Boom_500_Index",
    "Crash_500_Index",
)
DRAWS = int(os.environ.get("DRAWS", "200"))
PLANT = tuple(float(k) for k in os.environ.get("PLANT", "0.05,0.1,0.2,0.4").split(","))
SEED = int(os.environ.get("SEED", "11"))


def hours(stamps: np.ndarray) -> np.ndarray:
    return np.array([datetime.fromtimestamp(t, timezone.utc).hour for t in stamps])


def weekdays(stamps: np.ndarray) -> np.ndarray:
    return np.array([datetime.fromtimestamp(t, timezone.utc).weekday() for t in stamps])


def days(stamps: np.ndarray) -> np.ndarray:
    return (stamps // 86400).astype(np.int64)


# --------------------------------------------------------------------- rules
# Each returns `(index, sign)` pairs: the bar the bet is placed on the close
# of, and +1 for long or -1 for short.


def london_fix(bars: dict, at: int = 16) -> list[tuple[int, int]]:
    """Price returning to the fix window's median, on drying volume.

    The claim: the 15-minute block spanning 16:00 London is a fair-value
    anchor and a magnet for 24 to 72 hours. The bet is taken when price comes
    back to the block's median with tick volume below its 50-bar average,
    directed **out of** the zone the way it arrived.
    """
    hour, day = hours(bars["time"]), days(bars["time"])
    close, volume = bars["close"], bars["volume"]
    pace = np.convolve(volume, np.ones(50) / 50.0, mode="full")[: len(volume)]
    out: list[tuple[int, int]] = []
    anchors: dict[int, tuple[float, int]] = {}
    for i in range(50, len(close)):
        if hour[i] == at:
            window = (hour == at) & (day == day[i])
            if window.sum():
                anchors[int(day[i])] = (
                    0.5 * (bars["high"][window].max() + bars["low"][window].min()),
                    i,
                )
        # Any anchor from the last three days is live, per "24 to 72 hours".
        for born, (median, where) in list(anchors.items()):
            if day[i] - born > 3:
                anchors.pop(born, None)
                continue
            if i <= where + 1 or volume[i] >= pace[i]:
                continue
            crossed = (close[i - 1] - median) * (close[i] - median) <= 0
            if crossed:
                out.append((i, 1 if close[i - 1] > median else -1))
                anchors.pop(born, None)
    return out


def ny_overlap_fade(bars: dict) -> list[tuple[int, int]]:
    """A sweep of the 13:00-15:00 range on thin volume, faded.

    The claim: at 15:00 London settles, and a push through the New York
    opening range that is not backed by volume is market makers absorbing the
    last orders, so it retraces to the 13:00 open.
    """
    hour, day = hours(bars["time"]), days(bars["time"])
    high, low, close, volume = bars["high"], bars["low"], bars["close"], bars["volume"]
    pace = np.convolve(volume, np.ones(20) / 20.0, mode="full")[: len(volume)]
    out: list[tuple[int, int]] = []
    for i in range(20, len(close)):
        if hour[i] < 15 or hour[i] > 17 or volume[i] >= pace[i]:
            continue
        window = (day == day[i]) & (hour >= 13) & (hour < 15)
        if window.sum() < 2:
            continue
        top, floor = high[window].max(), low[window].min()
        if high[i] > top:
            out.append((i, -1))
        elif low[i] < floor:
            out.append((i, 1))
    return out


def wednesday_swap(bars: dict) -> list[tuple[int, int]]:
    """The triple-swap squeeze: Wednesday evening, joining the break.

    The claim: retail crowds the positive-carry side and institutions clear
    those stops between 19:00 and 22:00 GMT on Wednesday, before the triple
    swap is charged. The bet joins the squeeze on an hourly close through the
    day's extreme.
    """
    hour, day, weekday = hours(bars["time"]), days(bars["time"]), weekdays(bars["time"])
    high, low, close = bars["high"], bars["low"], bars["close"]
    out: list[tuple[int, int]] = []
    for i in range(24, len(close)):
        if weekday[i] != 2 or not 19 <= hour[i] < 22:
            continue
        earlier = (day == day[i]) & (hour < hour[i])
        if earlier.sum() < 4:
            continue
        if close[i] < low[earlier].min():
            out.append((i, -1))
        elif close[i] > high[earlier].max():
            out.append((i, 1))
    return out


def daily_open_reversal(bars: dict) -> list[tuple[int, int]]:
    """An extreme daily close, faded the next day.

    The claim: a close in the top 5% of its own range is an inventory
    backlog, so the next session pushes a little further and then rebalances
    toward the midpoint.
    """
    high, low, close = bars["high"], bars["low"], bars["close"]
    span = high - low
    where = np.where(span > 0, (close - low) / np.maximum(span, 1e-12), 0.5)
    out: list[tuple[int, int]] = []
    for i in range(1, len(close) - 1):
        if span[i] <= 0:
            continue
        if where[i] > 0.95:
            out.append((i, -1))
        elif where[i] < 0.05:
            out.append((i, 1))
    return out


def squeeze_fade(bars: dict) -> list[tuple[int, int]]:
    """A spike out of a volatility squeeze, faded.

    The pre-announcement idea without the calendar. Its mechanism is a
    liquidity vacuum: width compresses to its own low percentile, and a spike
    with no institutional orders behind it fails. Conditioning on the width
    percentile tests that mechanism directly and needs no calendar feed, which
    the cache does not carry anyway.
    """
    high, low, close = bars["high"], bars["low"], bars["close"]
    span = np.log(np.maximum(high, 1e-12)) - np.log(np.maximum(low, 1e-12))
    out: list[tuple[int, int]] = []
    for i in range(500, len(close) - 1):
        past = span[i - 500 : i]
        quiet = np.quantile(past, 0.05)
        if span[i - 1] > quiet:
            continue
        typical = float(np.median(past))
        if typical <= 0 or span[i] < 2.0 * typical:
            continue
        out.append((i, -1 if close[i] > close[i - 1] else 1))
    return out


RULES = (
    ("london fix 16 UTC", lambda b: london_fix(b, 16), "15m", 96, MAJORS),
    ("london fix 15 UTC", lambda b: london_fix(b, 15), "15m", 96, MAJORS),
    ("ny overlap fade", ny_overlap_fade, "1h", 6, MAJORS),
    ("wednesday swap", wednesday_swap, "1h", 3, CARRY),
    ("daily open reversal", daily_open_reversal, "1d", 1, MAJORS),
    ("squeeze fade", squeeze_fade, "1h", 6, MAJORS),
)


def forward(bars: dict, events: list[tuple[int, int]], horizon: int) -> np.ndarray:
    """Signed forward log return per event, in units of the feed's own bar."""
    close = bars["close"]
    span = np.log(np.maximum(bars["high"], 1e-12)) - np.log(np.maximum(bars["low"], 1e-12))
    scale = float(np.median(span[span > 0])) if (span > 0).any() else 0.0
    if scale <= 0:
        return np.empty(0)
    out = []
    last = -(10**9)
    for i, sign in events:
        if i - last < horizon or i + horizon >= len(close):
            continue
        last = i
        moved = math.log(close[i + horizon]) - math.log(close[i])
        out.append(sign * moved / scale)
    return np.asarray(out)


def arm(names: tuple[str, ...], rule, frame: str, horizon: int, shuffled: bool) -> np.ndarray:
    pooled: list[np.ndarray] = []
    rng = np.random.default_rng(SEED)
    for name in names:
        bars = load(name, frame)
        if bars is None:
            continue
        if shuffled:
            bars = shuffle_blocks(bars, rng)
        got = forward(bars, rule(bars), horizon)
        if len(got):
            pooled.append(got)
    return np.concatenate(pooled) if pooled else np.empty(0)


def main() -> None:
    # The clock, before anything that depends on it.
    probe = load("EURUSD", "1h")
    if probe is not None:
        hour = hours(probe["time"])
        span = np.log(np.maximum(probe["high"], 1e-12)) - np.log(np.maximum(probe["low"], 1e-12))
        by_hour = np.array([np.median(span[hour == h]) for h in range(24)])
        peak, trough = int(np.argmax(by_hour)), int(np.argmin(by_hour))
        print(
            f"clock check on EURUSD 1h: volatility peaks at {peak:02d} UTC,"
            f" troughs at {trough:02d} UTC, ratio {by_hour[peak] / by_hour[trough]:.2f}x"
        )
        print(
            "  expected from this repo: a peak at 14-15 UTC at about 3x."
            f" {'Clock agrees.' if peak in (13, 14, 15) else 'CLOCK DISAGREES - calendar rows are void.'}\n"
        )

    print(
        f"{'rule':<21}{'n':>6}{'mean':>8}{'hit':>7}{'null sd':>9}{'z':>7}{'placebo':>9}{'shuffled':>10}"
    )
    for label, rule, frame, horizon, names in RULES:
        live = arm(names, rule, frame, horizon, shuffled=False)
        if len(live) < 50:
            print(f"{label:<21}{len(live):>6}   too few events to measure")
            continue
        twin = arm(names, rule, frame, horizon, shuffled=True)
        fake = arm(PLACEBO, rule, frame, horizon, shuffled=False)
        # The null: the same events with their signs redrawn, which keeps the
        # event geometry and destroys only the claimed direction.
        rng = np.random.default_rng(SEED)
        draws = np.array(
            [float(np.mean(live * rng.choice((-1.0, 1.0), size=len(live)))) for _ in range(DRAWS)]
        )
        spread = float(np.std(draws)) or float("nan")
        mean = float(np.mean(live))
        print(
            f"{label:<21}{len(live):>6}{mean:>8.4f}"
            f"{float(np.mean(live > 0)):>7.3f}{spread:>9.4f}{mean / spread:>7.2f}"
            f"{(float(np.mean(fake)) if len(fake) > 20 else float('nan')):>9.4f}"
            f"{(float(np.mean(twin)) if len(twin) > 20 else float('nan')):>10.4f}"
        )
        # Power: plant a known drift in these same events and see it or not.
        seen = []
        for size in PLANT:
            lifted = live + size
            seen.append(f"{size:g}:{float(np.mean(lifted)) / spread:.1f}")
        print(f"  {'power, planted drift -> z':<26}" + "  ".join(seen))
    print(
        "\n  A rule is real only if its z clears the null, its placebo arm stays at\n"
        "  zero, its shuffled twin stays at zero, and the power line shows it could\n"
        "  have seen an effect of the size being claimed."
    )


if __name__ == "__main__":
    main()
