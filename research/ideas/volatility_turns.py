"""Levels and slopes anchored where volatility turned, and whether turns coincide.

Two things came together here.

**The relationship work has an event-shaped blind spot.** Volatility spillover
was tested as a **linear cross-correlation of log-volatility changes** and read
0 of 106 against its null. A volatility *turn* is an **event with a timestamp**,
and a turn that leads by a few spans with a varying magnitude smears out of a
correlation entirely. Linear dependence and event synchrony are different
questions and only the first was asked.

**And the levels thesis is about where a turn happened, not that one did.** The
price level at which volatility turned, and - the part this adds - the **slope**
through it. A level is a horizontal line and a slope is a line with a gradient;
`rates.py` already makes the second a first-class object here, and `Gaussian`
carries `rate` as a state, so "the level and the slope at the turn" is a pair
the package can already express.

The level *magnet* form of this is already refuted in `docs/` - `bos-predict.md`,
`exits.md`, `order-block-zones.md` - so this does not retest it. What is new is
anchoring to a **volatility** turn rather than a price reversal, and carrying
the slope.

## The detector is the desk's own

`accruing.OneSided` is the exact CUSUM likelihood ratio over all changepoints,
run as a pair - "moves got bigger" and "moves got smaller" are different events,
which is why `paired.py` runs two. Feeding it standardised log-volatility
increments dates every turn, with its direction.

Using the shipped detector rather than a fresh one matters: a turn found by
something written for this harness would be a finding about the harness.

## Four questions, in the order that makes the later ones worth asking

* **do turns coincide** - `P(j turns within k spans | i turns)` less the
  unconditional rate. This is the event-shaped version of the spillover test;
* **does any turn lead** - the signed lag of the nearest turn, which is the
  question a correlation of changes cannot reach;
* **does the level matter** - forward returns against distance from the price
  level at the turn;
* **does the slope matter** - the same, conditioned on the sign and size of the
  slope through the turn.

## The controls

* **planted** - a common turn process, where coincidence must appear, and
  independent turns, where it must not;
* **rotation** - the other instruments rotated, which destroys coincidence and
  preserves every marginal exactly;
* **the synthetics** - `Volatility_*` is verified constant-volatility GBM with
  log-volatility autocorrelation of `+0.0182`, so **it has no turns to share**.
  A detector that finds synchronous turns there is finding its own threshold.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import panel_volatility as panel  # noqa: E402
import relationship_screen as screen  # noqa: E402

HOUR = 3600.0
#: Bars per volatility observation.
SPAN = int(os.environ.get("SPAN", "6"))
#: Spans either side counted as "the same turn".
NEAR = int(os.environ.get("NEAR", "2"))
#: Lags scanned for a lead, in spans.
LAGS = int(os.environ.get("LAGS", "8"))
#: Evidence threshold for the detector, in nats.
#: 6, not the 12 `accruing.THRESHOLD` ships. 12 is calibrated for a
#: *false-alarm rate* on a signed quantity; here the detector has to produce
#: enough dated events for a coincidence *rate* to exist, and at 12 it fired a
#: median of 2 times in 2,246 spans. At 6 it fires 16 times and 11 of 20
#: instruments clear the floor below.
THRESHOLD = float(os.environ.get("THRESHOLD", "6.0"))
#: A bar counts as wide at this multiple of the trailing range, and its body
#: has to be below this share of its own range for the flow to count as
#: contested. Both are ratios, so neither needs a per-instrument constant.
WIDE = float(os.environ.get("WIDE", "2.0"))
BODY = float(os.environ.get("BODY", "0.35"))
#: Bars of trailing true range the excess is measured in.
ATR = int(os.environ.get("ATR", "24"))
#: Turns an instrument needs before its coincidence rate is a rate at all.
#: With two turns the rate can only be 0, 0.5 or 1, and the rotation null read
#: a maximum of +0.9911 off exactly that.
LEAST_TURNS = int(os.environ.get("LEAST_TURNS", "15"))
#: Spans of trailing mean the CUSUM measures the level against.
MEMORY = int(os.environ.get("MEMORY", "20"))
#: How far past the previous bar's range a close has to settle to count, in
#: true ranges. The sign alone is not an event.
#: 2 true ranges, which fires on **4.2%** of spans - an event. The sweep is
#: 58.6% at 0.5, 22.3% at 1, 4.2% at 2 and 1.4% at 3, so the scale now has the
#: range to express the question; against the current bar's own range it went
#: from 86% straight to zero.
EXCESS = float(os.environ.get("EXCESS", "2.0"))
#: Null repetitions.
REPS = int(os.environ.get("REPS", "6"))
SEED = 20261013


def ohlc(name: str):
    """`(times, high, low, close)` on the common filters, since high and low matter.

    `relationship_screen.load` returns log closes and discards the bar's
    extremes, which is the right shape for a spread and the wrong one for an
    **event**. A spike is a close that leaves the previous bar's range, and a
    range needs a high and a low.
    """
    import numpy as np

    path = screen.CACHE / f"{name}.{screen.FRAME}.npz"
    if not path.exists():
        return None
    with np.load(path) as bundle:
        if not {"time", "high", "low", "close"} <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        times = np.asarray(bundle["time"], dtype=float)[order]
        high = np.asarray(bundle["high"], dtype=float)[order]
        low = np.asarray(bundle["low"], dtype=float)[order]
        close = np.asarray(bundle["close"], dtype=float)[order]
    keep = (close > 0) & (high > 0) & (low > 0) & (times >= screen.SINCE)
    times, high, low, close = times[keep], high[keep], low[keep], close[keep]
    if len(times) > screen.LIMIT:
        times, high, low, close = (
            times[-screen.LIMIT :],
            high[-screen.LIMIT :],
            low[-screen.LIMIT :],
            close[-screen.LIMIT :],
        )
    return times, high, low, close


def range_breaks(bars, span: int = SPAN):
    """Turns as **level crossings**: a close beyond the previous bar's range.

    `spiking = close - previous high` and `crashing = close - previous low`.
    Threshold-free and scale-free, and it is what a `Boom` spike actually looks
    like - a close that leaves the previous bar's range entirely - where a
    six-sigma rule on *returns* throws the extremes away and needs a constant
    chosen.

    It is also a **levels** statement rather than a statistical one: the
    previous bar's high is a level, and the event is the close crossing it. The
    turn is dated at the span containing the crossing, so it lines up with the
    volatility spans the other detector uses.
    """
    import numpy as np

    times, high, low, close = bars
    if len(close) < span * 60:
        return []
    # **The excess is the quantity, not the sign.** `close - previous high` is
    # a size, and an hourly close clears the previous high about a third of the
    # time: using the sign alone found 3,289 "events" in 3,333 spans, which is
    # a description of every bar rather than an event. Scaled by the bar's own
    # true range so a threshold means the same thing on EURUSD and on BTCUSD.
    reach = np.maximum.reduce(
        [
            high[1:] - low[1:],
            np.abs(high[1:] - close[:-1]),
            np.abs(low[1:] - close[:-1]),
        ]
    )
    # **A trailing average range, not this bar's.** The current bar's true
    # range already contains `|high - previous close|`, so it bounds
    # `close - previous high` almost by construction: normalising by it put
    # 86% of spans past 0.25 and **none** past 1.0, which is a scale that
    # cannot express the question. An average over `ATR` bars can.
    if len(reach) < ATR + 2:
        return []
    trailing = np.convolve(reach, np.ones(ATR) / ATR, mode="valid")
    scale = np.maximum(trailing, 1e-12)
    offset = ATR - 1
    high, low, close = high[offset:], low[offset:], close[offset:]
    over_raw = close[1:] - high[:-1]
    under_raw = low[:-1] - close[1:]
    scale = scale[: len(over_raw)]
    over_raw, under_raw = over_raw[: len(scale)], under_raw[: len(scale)]
    over = over_raw / scale
    under = under_raw / scale
    found = {}
    for i in np.flatnonzero((over > EXCESS) | (under > EXCESS)):
        at = int((i + 1 + offset) // span)
        size = float(max(over[i], under[i]))
        # The largest excess in a span, so a burst is one turn and the one kept
        # is the strongest rather than the earliest.
        if at not in found or size > found[at][0]:
            found[at] = (size, 1 if over[i] >= under[i] else -1)
    return [(at, side) for at, (_, side) in sorted(found.items())]


def align_on(names, pool):
    """`panel.aligned`, with its span forced to agree with this module's.

    **`panel_volatility` carries its own `SPAN` and `aligned` cuts the matrix
    with it.** Calling it from here at a different span silently returned
    24-bar spans while every turn index assumed 6, which is most of why the
    first run found a median of two turns in 561 spans.
    """
    was = panel.SPAN
    panel.SPAN = SPAN
    try:
        return panel.aligned(names, pool)
    finally:
        panel.SPAN = was


def candles(bars, span: int = SPAN):
    """Turns from the **candlestick**, which is a summary of the interval's flow.

    A bar is not four numbers, it is what the order flow did in that interval:
    the **body** is how much of the move was net directional, the **wicks** are
    what was offered and rejected, and the **settle** is where in the range the
    flow finished. A statistic on closes alone throws all of that away, and the
    range-break arm above uses only two of the four.

    The event here is a **wide bar that went nowhere**: a range well past the
    trailing average with a body that is a small share of it. That is contested
    flow - size traded in both directions and neither won - which is the bar
    shape a volatility regime turns on, and it is scale-free because both parts
    are ratios.

    Reported with the settle so the direction is kept: a wide contested bar that
    closes at its low is a different event from one that closes at its high.
    """
    import numpy as np

    times, high, low, close = bars
    if len(close) < ATR + span * 20:
        return []
    # An open is not in the cache, so the previous close stands in for it -
    # which is the right object anyway on a continuously quoted feed, where
    # this bar's open *is* the last one's close.
    open_ = close[:-1]
    high, low, close = high[1:], low[1:], close[1:]
    span_range = np.maximum(high - low, 1e-12)
    reach = np.maximum.reduce(
        [span_range, np.abs(high - open_), np.abs(low - open_)]
    )
    if len(reach) < ATR + 2:
        return []
    trailing = np.convolve(reach, np.ones(ATR) / ATR, mode="valid")
    offset = ATR - 1
    high, low, close, open_, span_range = (
        high[offset:],
        low[offset:],
        close[offset:],
        open_[offset:],
        span_range[offset:],
    )
    width = len(trailing)
    high, low, close, open_, span_range = (
        high[:width],
        low[:width],
        close[:width],
        open_[:width],
        span_range[:width],
    )
    wide = span_range / np.maximum(trailing, 1e-12)
    body = np.abs(close - open_) / span_range
    settle = (close - low) / span_range

    found = {}
    for i in np.flatnonzero((wide > WIDE) & (body < BODY)):
        at = int((i + 1 + offset) // span)
        size = float(wide[i])
        if at not in found or size > found[at][0]:
            # Settling in the lower half is a rejection of the highs.
            found[at] = (size, 1 if settle[i] >= 0.5 else -1)
    return [(at, side) for at, (_, side) in sorted(found.items())]


def turns_of(series, threshold: float = THRESHOLD):
    """Indices and directions of volatility turns, from the shipped detector.

    Standardised log-volatility increments into a pair of one-sided CUSUMs, each
    reset when it fires, so the output is a list of dated turns rather than a
    statistic.
    """
    import numpy as np

    from till_infinity.statespace.accruing import OneSided

    # **The level's deviation from a trailing mean, not the increment.** A
    # volatility turn is a shift in the *level* of log-volatility; its
    # increments are near-white, so a CUSUM looking for a mean shift in them
    # finds nothing - fed increments it returned a median of **0** turns per
    # instrument over 2,246 spans.
    values = np.asarray(series, dtype=float)
    if len(values) < MEMORY + 60:
        return []
    trailing = np.convolve(values, np.ones(MEMORY) / MEMORY, mode="valid")
    steps = values[MEMORY - 1 :] - trailing
    spread = float(steps.std())
    if spread <= 0:
        return []
    steps = (steps - steps.mean()) / spread

    up = OneSided(threshold=threshold, up=True)
    down = OneSided(threshold=threshold, up=False)
    found = []
    for i, step in enumerate(steps):
        rose = up.update(float(step), 1.0)
        fell = down.update(float(step), 1.0)
        if rose:
            found.append((i + MEMORY - 1, 1))
            up.reset()
            down.reset()
        elif fell:
            found.append((i + MEMORY - 1, -1))
            up.reset()
            down.reset()
    return found


def coincidence(mine, theirs, total: int, near: int = NEAR) -> float | None:
    """`P(they turned nearby | I turned)` less their unconditional rate."""
    if not mine or not theirs or total <= 0:
        return None
    where = {i for i, _ in theirs}
    hits = sum(
        1 for i, _ in mine if any((i + k) in where for k in range(-near, near + 1))
    )
    # The rate a turn of theirs lands in a window of this width by chance.
    width = 2 * near + 1
    base = min(len(theirs) * width / total, 1.0)
    return hits / len(mine) - base


def lead_of(mine, theirs, lags: int = LAGS) -> tuple[float, int] | None:
    """The lag at which their turns most often follow mine, and by how much."""
    if not mine or not theirs:
        return None
    where = {i for i, _ in theirs}
    best, at = 0.0, 0
    for lag in range(-lags, lags + 1):
        if lag == 0:
            continue
        rate = sum(1 for i, _ in mine if (i + lag) in where) / len(mine)
        if rate > best:
            best, at = rate, lag
    return best, at


def planted() -> None:
    """A shared turn process, and independent turns, through the same detector."""
    import numpy as np

    print("=" * 104)
    print("ARM 0  planted: coincidence must appear with a shared turn and not without")
    print("=" * 104)
    rng = np.random.default_rng(3)
    spans, count = 1200, 10
    print(f"{'planted':<30}{'turns each':>12}{'coincidence':>14}{'best lead':>12}{'at lag':>8}")
    for label, shared_rate in (("a shared turn process", 1.0), ("independent turns", 0.0)):
        # A common regime that switches, plus an idiosyncratic one.
        common = np.zeros(spans)
        level = 0.0
        for i in range(spans):
            if rng.random() < 0.01:
                level = rng.standard_normal()
            common[i] = level
        series = []
        for _ in range(count):
            own = np.zeros(spans)
            mine = 0.0
            for i in range(spans):
                if rng.random() < 0.01:
                    mine = rng.standard_normal()
                own[i] = mine
            drive = shared_rate * common + (1.0 - shared_rate) * own
            series.append(np.cumsum(drive + rng.standard_normal(spans) * 0.3))
        found = [turns_of(s) for s in series]
        counts = [len(f) for f in found]
        pairs, leads = [], []
        for i in range(count):
            for j in range(count):
                if i == j:
                    continue
                got = coincidence(found[i], found[j], spans)
                if got is not None:
                    pairs.append(got)
                led = lead_of(found[i], found[j])
                if led is not None:
                    leads.append(led)
        if not pairs:
            print(f"{label:<30}  no turns found")
            continue
        best = max(leads, key=lambda r: r[0]) if leads else (float("nan"), 0)
        print(
            f"{label:<30}{statistics.median(counts):>12.0f}"
            f"{statistics.median(pairs):>+14.4f}{best[0]:>12.4f}{best[1]:>8}"
        )
    print(
        "\nIf the shared row does not show coincidence the detector cannot see\n"
        "what this harness is for, and the universe arms below mean nothing."
    )


def main() -> None:
    print(
        f"turns from accruing.OneSided at {THRESHOLD} nats on {SPAN}-bar\n"
        f"log-volatility, within {NEAR} spans counted as the same turn,\n"
        f"leads scanned to {LAGS} spans\n"
    )
    planted()

    import numpy as np

    traded = [n for n in screen.TRADED if screen.load(n) is not None]
    synthetic = [
        n for n in screen.universe(screen.FRAME, cap=40) if screen.load(n) is not None
    ]
    series = {n: screen.load(n) for n in traded + synthetic}

    print("\n" + "=" * 104)
    print("ARM 1  do volatility turns coincide, which a correlation of changes cannot ask")
    print("=" * 104)
    print(
        f"{'':<34}{'pairs':>8}{'median':>11}{'99th pct':>11}{'max':>9}{'turns':>8}"
    )

    def measure(names, pool):
        kept, matrix = align_on(names, pool)
        if kept is None:
            return None, None, None
        found = [turns_of(matrix[i]) for i in range(len(kept))]
        total = matrix.shape[1]
        pairs, leads = [], []
        enough = [i for i in range(len(kept)) if len(found[i]) >= LEAST_TURNS]
        for i in enough:
            for j in enough:
                if i == j:
                    continue
                got = coincidence(found[i], found[j], total)
                if got is not None:
                    pairs.append(got)
                led = lead_of(found[i], found[j])
                if led is not None:
                    leads.append((led[0], led[1], kept[i], kept[j]))
        return pairs, leads, [len(f) for f in found]

    def summarise(label, pairs, counts):
        if not pairs:
            print(f"{label:<34}  nothing measurable")
            return
        ordered = sorted(pairs)
        print(
            f"{label:<34}{len(ordered):>8}{statistics.median(ordered):>+11.4f}"
            f"{ordered[max(len(ordered) - len(ordered) // 100 - 1, 0)]:>+11.4f}"
            f"{ordered[-1]:>+9.4f}"
            f"{statistics.median(counts) if counts else float('nan'):>8.0f}"
        )

    real_pairs, real_leads, real_counts = measure(traded, {n: series[n] for n in traded})
    summarise("traded, cusum on log-vol", real_pairs, real_counts)

    # The same question with turns defined as a **level crossing** rather than
    # a statistic: a close beyond the previous bar's high or low.
    def measure_breaks(names, detect=range_breaks, shifted=None):
        found, total = [], 0
        for name in names:
            bars = ohlc(name)
            if bars is None:
                found.append([])
                continue
            total = max(total, len(bars[0]) // SPAN)
            got = detect(bars)
            if shifted is not None and got:
                # The null for an event series: the same events, moved as a
                # block, so the rate and the clustering survive and only the
                # alignment to the other instrument dies.
                step = random.Random(SEED + len(got)).randrange(50, max(total, 60))
                got = [((at + step) % max(total, 1), side) for at, side in got]
                got.sort()
            found.append(got)
        pairs = []
        for i in range(len(names)):
            for j in range(len(names)):
                if i == j:
                    continue
                got = coincidence(found[i], found[j], total)
                if got is not None:
                    pairs.append(got)
        return pairs, [len(f) for f in found]

    break_pairs, break_counts = measure_breaks(traded)
    summarise("traded, close beyond prev range", break_pairs, break_counts)
    syn_break_pairs, syn_break_counts = measure_breaks(synthetic)
    summarise("  generated, same definition", syn_break_pairs, syn_break_counts)

    candle_pairs, candle_counts = measure_breaks(traded, detect=candles)
    summarise("traded, contested candle", candle_pairs, candle_counts)
    syn_candle, syn_candle_counts = measure_breaks(synthetic, detect=candles)
    summarise("  generated, same definition", syn_candle, syn_candle_counts)
    null_candle = []
    for _ in range(REPS):
        order = list(traded)
        random.Random(SEED + len(null_candle)).shuffle(order)
        got, _ = measure_breaks(traded, detect=candles, shifted=order)
        null_candle.extend(got)
    summarise("  shifted null", null_candle, None)
    print(
        "\nThe second definition is threshold-free and uses the bar's extremes,\n"
        "which the log-volatility route discards. It is also a levels statement:\n"
        "the previous bar's high is a level and the event is the close crossing\n"
        "it."
    )

    picker = random.Random(SEED)
    null_pairs, null_counts = [], []
    for _ in range(REPS):
        spun = {n: series[n] for n in traded}
        for n in traded[1:]:
            spun[n] = panel.rotated(spun[n], picker)
        got, _, counts = measure(traded, spun)
        if got:
            null_pairs.extend(got)
            null_counts.extend(counts or [])
    summarise("  rotation null", null_pairs, null_counts)

    syn_pairs, _, syn_counts = measure(synthetic, {n: series[n] for n in synthetic})
    summarise("generated", syn_pairs, syn_counts)
    print(
        "\nThe generated row is the sharpest control here: `Volatility_*` is\n"
        "verified constant-volatility GBM with log-volatility autocorrelation of\n"
        "+0.0182, so it has **no turns to share**. Coincidence there would be\n"
        "the detector finding its own threshold."
    )

    if real_pairs and null_pairs:
        bar = max(null_pairs)
        beat = sum(1 for v in real_pairs if v > bar)
        print(
            f"\n{beat} of {len(real_pairs)} traded pairs exceed the rotation null's "
            f"maximum coincidence ({bar:+.4f})"
        )

    print("\n" + "=" * 104)
    print("ARM 2  does any instrument's turn lead another's")
    print("=" * 104)
    if real_leads:
        real_leads.sort(key=lambda r: -r[0])
        nulls = []
        for _ in range(REPS):
            spun = {n: series[n] for n in traded}
            for n in traded[1:]:
                spun[n] = panel.rotated(spun[n], picker)
            _, got, _ = measure(traded, spun)
            if got:
                nulls.extend(r[0] for r in got)
        bar = max(nulls) if nulls else float("nan")
        print(f"rotation null's best lead rate: {bar:.4f}\n")
        print(f"{'leader':<12}{'follower':<12}{'rate':>9}{'at lag':>8}{'beats':>8}")
        for rate, lag, leader, follower in real_leads[:12]:
            print(
                f"{leader:<12}{follower:<12}{rate:>9.4f}{lag:>8}"
                f"{'yes' if rate > bar else '':>8}"
            )
        print(
            f"\n{sum(1 for r in real_leads if r[0] > bar)} of {len(real_leads)} "
            "ordered pairs beat it. A lead is the one shape here that could carry\n"
            "a direction, because it says something before the event rather than\n"
            "during it."
        )
    else:
        print("  no leads measurable")


if __name__ == "__main__":
    main()
